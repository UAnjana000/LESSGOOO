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


def extract_pdf(data: bytes, render_scale: float = 2.0, language: str | None = None) -> list[TextLayerPage]:
    import pypdfium2 as pdfium
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pdf = pdfium.PdfDocument(data)
    pages = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        reliable = text_layer_reliable(text, language)
        bitmap = pdf[i].render(scale=render_scale)
        buf = io.BytesIO()
        bitmap.to_pil().convert("L").save(buf, format="PNG")
        pages.append(TextLayerPage(index=i, text=text, reliable=reliable, image_png=buf.getvalue()))
    return pages
