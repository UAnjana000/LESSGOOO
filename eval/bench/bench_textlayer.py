"""Born-digital ingestion cost per page vs PDF length (docs/ARCHITECTURE_REVIEW.md, ingestion finding).

Unlike the other eval/ scripts this one imports the backend, so run it with the backend venv:

    backend\\.venv\\Scripts\\python.exe eval/bench/bench_textlayer.py --pages 50 200 --sample 5 --out eval/results/bench-textlayer.json

It drives the real `archive.ingest.processing.process_page` (born-digital route: delivery render + text layer)
over a synthetic multi-page PDF built by fixtures/generate_fixtures.py. The metadata DB is replaced by an
in-memory stand-in, so the numbers are PDF/render/storage cost only. Storage goes to a temporary directory.

--sample K processes K pages spread across the document and reports the per-page mean; --full processes every
page (inside `processing.pdf_documents()` when that exists, i.e. how the ingestion graph runs). Totals from a
sample are labelled "extrapolated". pdfium document opens, page renders and pypdf text extractions are counted.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import itertools
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
_TMP = Path(tempfile.mkdtemp(prefix="bench-textlayer-"))
for role in ("PRESERVATION", "DELIVERY", "DERIVATIVE", "QUARANTINE", "TRACE", "BACKUP"):
    os.environ[f"ARCHIVE_{role}_ROOT"] = str(_TMP / role.lower())
sys.path.insert(0, str(ROOT / "backend"))

import pypdf  # noqa: E402
import pypdfium2  # noqa: E402

from archive import storage  # noqa: E402
from archive.ingest import processing  # noqa: E402

PAGE_TEXT = ("Synthetic born digital page {n} with a real text layer about public reading rooms, night schools "
             "and the rules of the common tank. It is not a historical document. ") * 4


def make_pdf(n: int) -> bytes:
    spec = importlib.util.spec_from_file_location("genfx", ROOT / "fixtures" / "generate_fixtures.py")
    genfx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(genfx)
    return genfx.make_pdf([PAGE_TEXT.format(n=i + 1) for i in range(n)])


class Counters:
    def __init__(self) -> None:
        self.opens = self.renders = self.texts = 0

    @contextlib.contextmanager
    def installed(self):
        doc_init, render, extract = pypdfium2.PdfDocument.__init__, pypdfium2.PdfPage.render, \
            pypdf.PageObject.extract_text

        def counting_init(obj, *a, **k):
            self.opens += 1
            return doc_init(obj, *a, **k)

        def counting_render(obj, *a, **k):
            self.renders += 1
            return render(obj, *a, **k)

        def counting_extract(obj, *a, **k):
            self.texts += 1
            return extract(obj, *a, **k)

        pypdfium2.PdfDocument.__init__, pypdfium2.PdfPage.render = counting_init, counting_render
        pypdf.PageObject.extract_text = counting_extract
        try:
            yield self
        finally:
            pypdfium2.PdfDocument.__init__, pypdfium2.PdfPage.render = doc_init, render
            pypdf.PageObject.extract_text = extract


class FakeDB:
    """Just enough of a Session for the born-digital route: get(master), add, flush, commit."""

    def __init__(self, master) -> None:
        self.master = master
        self._ids = itertools.count(100)

    def get(self, _model, _id):
        return self.master

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = next(self._ids)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        pass


def _page(i: int):
    return SimpleNamespace(id=i + 1, item_id=1, item=None, doc_class="born_digital", image_file_id=1,
                           preprocessing_params={"pdf_page_index": i}, language="en", delivery_file_id=None,
                           status="pending", ocr_route=None, review_mode=None, gate_passed=None,
                           quality_signals={})


def run(n: int, sample: int | None) -> dict:
    data = make_pdf(n)
    stored = storage.put_bytes(data, "preservation_master", ".pdf")
    master = SimpleNamespace(id=1, format="application/pdf", storage_uri=stored.uri)
    db = FakeDB(master)
    idx = list(range(n)) if sample is None else sorted({round(j * (n - 1) / max(1, sample - 1))
                                                        for j in range(sample)})
    scope = getattr(processing, "pdf_documents", None)
    per_page: list[float] = []
    with Counters().installed() as c:
        t_all = time.perf_counter()
        with (scope() if scope else contextlib.nullcontext()):
            for i in idx:
                t0 = time.perf_counter()
                out = processing.process_page(db, _page(i), None)
                per_page.append((time.perf_counter() - t0) * 1000)
                assert out.route == "text_layer", out
        wall = (time.perf_counter() - t_all) * 1000
    mean = statistics.fmean(per_page)
    return {
        "pdf_pages": n, "pages_processed": len(idx), "pdf_bytes": len(data),
        "mode": "full" if sample is None else f"sample of {len(idx)}",
        "per_page_ms_mean": round(mean, 1), "per_page_ms_max": round(max(per_page), 1),
        "total_s": round(wall / 1000, 2) if sample is None else None,
        "total_s_extrapolated": round(mean * n / 1000, 1) if sample is not None else None,
        "pdfium_opens": c.opens, "renders": c.renders, "text_extractions": c.texts,
        "renders_per_processed_page": round(c.renders / len(idx), 1),
        "opens_per_processed_page": round(c.opens / len(idx), 2),
        "uses_pdf_documents_scope": scope is not None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", type=int, nargs="+", default=[50, 200])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sample", type=int, default=None, help="process K pages spread over the document")
    g.add_argument("--full", action="store_true", help="process every page")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    rows = [run(n, None if args.full else (args.sample or 5)) for n in args.pages]
    result = {"label": args.label, "python": sys.version.split()[0], "rows": rows}
    print(json.dumps(result, indent=2))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
