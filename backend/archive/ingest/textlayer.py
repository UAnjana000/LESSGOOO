"""Born-digital route: extract the PDF text layer directly (do not OCR what is already text)."""

from __future__ import annotations

import io
from dataclasses import dataclass

from archive.ingest.quality import garbage_rate, script_share

MIN_CHARS = 40
MAX_GARBAGE_RATE = 0.1
# Legacy non-Unicode Devanagari fonts (Kruti Dev and similar) extract as Latin mojibake with a low
# garbage rate, so hi/mr pages must also be mostly Devanagari letters to be trusted.
DEVANAGARI_LANGS = {"hi", "mr"}
MIN_DEVANAGARI_SHARE = 0.6


@dataclass
class TextLayerPage:
    index: int
    text: str
    reliable: bool
    image_png: bytes


def text_layer_reliable(text: str, language: str | None) -> bool:
    if len(text) < MIN_CHARS or garbage_rate(text) >= MAX_GARBAGE_RATE:
        return False
    if language in DEVANAGARI_LANGS and script_share(text, language) < MIN_DEVANAGARI_SHARE:
        return False
    return True


class PdfPages:
    """One parsed PDF. Pages are text-extracted or rendered on demand, one page per call, so the cost of
    processing page i does not depend on how many pages the document has. Close it (or use it as a
    context manager) to release the pdfium document."""

    def __init__(self, data: bytes) -> None:
        import pypdfium2 as pdfium
        from pypdf import PdfReader

        self._reader = PdfReader(io.BytesIO(data))
        self._pdf = pdfium.PdfDocument(data)

    def __len__(self) -> int:
        return len(self._reader.pages)

    def text(self, index: int) -> str:
        return (self._reader.pages[index].extract_text() or "").strip()

    def render_png(self, index: int, scale: float = 2.0) -> bytes:
        page = self._pdf[index]
        try:
            bitmap = page.render(scale=scale)
            try:
                buf = io.BytesIO()
                bitmap.to_pil().convert("L").save(buf, format="PNG")
                return buf.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()

    def page(self, index: int, language: str | None = None, render_scale: float = 2.0) -> TextLayerPage:
        text = self.text(index)
        return TextLayerPage(index=index, text=text, reliable=text_layer_reliable(text, language),
                             image_png=self.render_png(index, render_scale))

    def close(self) -> None:
        self._pdf.close()

    def __enter__(self) -> PdfPages:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def extract_pdf(data: bytes, render_scale: float = 2.0, language: str | None = None) -> list[TextLayerPage]:
    """Every page of a PDF. Ingestion must not call this per page; use PdfPages for single pages."""
    with PdfPages(data) as doc:
        return [doc.page(i, language, render_scale) for i in range(len(doc))]
