"""Two-column check pages for the page-segmentation (psm) decision (docs/OCR_ENGINE_EVAL.md).

    backend\\.venv\\Scripts\\python.exe eval/ocr_engine/build_multicol.py

The main sample has no multi-column pages. The index of BAWS English vol. 1 (PDF pages 508-511) is set in
two columns with a Unicode text layer whose content-stream order is column-major (left column top to
bottom, then the right column), checked by eye against the rendered pages; that text is the ground truth.
The output uses the build_sample layout, so run_engine.py and score.py work on it with
--sample data/ocr_eval_multicol.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from build_sample import DPI, render

PAGES = [508, 509, 510, 511]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", default="data/incoming/baws/mea_Volume1.pdf")
    ap.add_argument("--out", default="data/ocr_eval_multicol")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "gt").mkdir(exist_ok=True)
    doc = pdfium.PdfDocument(args.pdf)
    manifest = {"dpi": DPI, "pages": []}
    for p in PAGES:
        pid = f"{Path(args.pdf).stem}_p{p:04d}"
        text = doc[p - 1].get_textpage().get_text_range()
        (out / "gt" / f"{pid}.txt").write_text(text, encoding="utf-8")
        Image.fromarray(render(doc, p - 1)).save(out / "pages" / f"{pid}.png", optimize=True)
        manifest["pages"].append({"id": pid, "source": args.pdf, "pdf_page": p, "language": "en",
                                  "gt_chars": len(text), "layout": "two-column index"})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(PAGES)} pages -> {out}")


if __name__ == "__main__":
    main()
