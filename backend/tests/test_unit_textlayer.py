"""Unit tests (no database): born-digital text-layer reliability check, and per-page PDF cost.

The PDF tests use small synthetic PDFs generated in-process (fixtures/generate_fixtures.py make_pdf)."""

from __future__ import annotations

import importlib.util
import itertools
from types import SimpleNamespace

import pypdf
import pypdfium2
import pytest

from archive import storage
from archive.ingest import processing
from archive.ingest.quality import garbage_rate
from archive.ingest.textlayer import PdfPages, extract_pdf, text_layer_reliable

from .conftest import FIXTURES

# Legacy Kruti Dev-style font extracted as Latin mojibake (not real Hindi text).
MOJIBAKE = "lfpo us dgk fd lafo/kku lHkk dh cSBd esa ekuuh; lnL;ksa us izLrko ij fopkj fd;k vkSj mls ikl fd;k A"
DEVANAGARI = "सचिव ने कहा कि संविधान सभा की बैठक में माननीय सदस्यों ने प्रस्ताव पर विचार किया और उसे पास किया।"
ENGLISH = "The Secretary said that the Constituent Assembly considered the motion and adopted it."


class TestTextLayerReliability:
    def test_mojibake_passes_garbage_check_alone(self):
        assert garbage_rate(MOJIBAKE) < 0.1

    def test_mojibake_is_unreliable_for_hindi_and_marathi(self):
        assert not text_layer_reliable(MOJIBAKE, "hi")
        assert not text_layer_reliable(MOJIBAKE, "mr")

    def test_real_devanagari_is_reliable(self):
        assert text_layer_reliable(DEVANAGARI, "hi")
        assert text_layer_reliable(DEVANAGARI, "mr")

    def test_english_layer_unaffected(self):
        assert text_layer_reliable(ENGLISH, "en")
        assert not text_layer_reliable(ENGLISH, "hi")

    def test_short_text_still_unreliable(self):
        assert not text_layer_reliable("सभा", "hi")


def _make_pdf(n: int) -> bytes:
    spec = importlib.util.spec_from_file_location("genfx", FIXTURES / "generate_fixtures.py")
    genfx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(genfx)
    return genfx.make_pdf([f"Synthetic born digital page {i + 1} with a real text layer about public reading "
                           f"rooms and night schools; not a historical document." for i in range(n)])


@pytest.fixture
def counts(monkeypatch):
    c = SimpleNamespace(opens=0, renders=0, texts=0, reads=0, closes=0)
    doc_init, doc_close = pypdfium2.PdfDocument.__init__, pypdfium2.PdfDocument.close
    render, extract, read = pypdfium2.PdfPage.render, pypdf.PageObject.extract_text, storage.read_bytes

    def bump(name, fn):
        def wrapped(*a, **k):
            setattr(c, name, getattr(c, name) + 1)
            return fn(*a, **k)
        return wrapped

    monkeypatch.setattr(pypdfium2.PdfDocument, "__init__", bump("opens", doc_init))
    monkeypatch.setattr(pypdfium2.PdfDocument, "close", bump("closes", doc_close))
    monkeypatch.setattr(pypdfium2.PdfPage, "render", bump("renders", render))
    monkeypatch.setattr(pypdf.PageObject, "extract_text", bump("texts", extract))
    monkeypatch.setattr(storage, "read_bytes", bump("reads", read))
    return c


class _FakeDB:
    """Just enough Session for the born-digital route (get master, add, flush, commit)."""

    def __init__(self, master):
        self.master, self._ids = master, itertools.count(100)

    def get(self, _model, _id):
        return self.master

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = next(self._ids)

    def flush(self):
        pass

    def commit(self):
        pass


def _born_digital(n: int):
    stored = storage.put_bytes(_make_pdf(n), "preservation_master", ".pdf")
    db = _FakeDB(SimpleNamespace(id=1, format="application/pdf", storage_uri=stored.uri))
    pages = [SimpleNamespace(id=i + 1, item_id=1, item=None, doc_class="born_digital", image_file_id=1,
                             preprocessing_params={"pdf_page_index": i}, language="en", delivery_file_id=None,
                             status="pending", ocr_route=None, review_mode=None, gate_passed=None,
                             quality_signals={}) for i in range(n)]
    return db, pages


class TestPdfPerPageCost:
    @pytest.mark.parametrize("n", [3, 24])
    def test_single_page_access_touches_only_that_page(self, counts, n):
        data = _make_pdf(n)
        with PdfPages(data) as doc:
            assert len(doc) == n
            assert f"page {n}" in doc.text(n - 1)
            assert doc.render_png(n - 1).startswith(b"\x89PNG")
        assert (counts.opens, counts.renders, counts.texts, counts.closes) == (1, 1, 1, 1)

    @pytest.mark.parametrize("n", [3, 12])
    def test_item_run_opens_each_pdf_once_and_renders_each_page_once(self, counts, n):
        db, pages = _born_digital(n)
        with processing.pdf_documents():
            outs = [processing.process_page(db, p, None) for p in pages]
        assert all(o.route == "text_layer" for o in outs)
        assert counts.reads == 1 and counts.opens == 1 and counts.closes == 1
        assert counts.renders == n and counts.texts == n

    def test_page_outside_an_item_run_still_costs_one_page(self, counts):
        db, pages = _born_digital(12)
        out = processing.process_page(db, pages[7], None)
        assert out.route == "text_layer" and pages[7].status == "in_batch_review"
        assert counts.renders == 1 and counts.texts == 1
        assert counts.opens == counts.closes  # nothing left open

    def test_extract_pdf_still_returns_every_page(self):
        pages = extract_pdf(_make_pdf(4), language="en")
        assert [p.index for p in pages] == [0, 1, 2, 3]
        assert all(p.reliable and p.image_png.startswith(b"\x89PNG") for p in pages)
        assert "page 3" in pages[2].text
