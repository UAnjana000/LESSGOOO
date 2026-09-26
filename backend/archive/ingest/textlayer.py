"""Born-digital route: extract the PDF text layer directly (do not OCR what is already text)."""

from __future__ import annotations

import io
from dataclasses import dataclass

import pypdfium2 as pdfium
from pypdf import PdfReader

from archive.ingest.quality import garbage_rate


@dataclass
class TextLayerPage:
    index: int
    text: str
    reliable: bool
    image_png: bytes


def extract_pdf(data: bytes, render_scale: float = 2.0) -> list[TextLayerPage]:
    reader = PdfReader(io.BytesIO(data))
    pdf = pdfium.PdfDocument(data)
    pages = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        reliable = len(text) >= 40 and garbage_rate(text) < 0.1
        bitmap = pdf[i].render(scale=render_scale)
        buf = io.BytesIO()
        bitmap.to_pil().convert("L").save(buf, format="PNG")
        pages.append(TextLayerPage(index=i, text=text, reliable=reliable, image_png=buf.getvalue()))
    return pages
