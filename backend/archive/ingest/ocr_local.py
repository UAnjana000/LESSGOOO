"""Local OCR engine: Tesseract 5 with eng/hin/mar traineddata (via pytesseract).

Chosen because it runs fully offline on the edge-server CPU, ships English, Hindi and Marathi
models in Debian packages, and emits word-level confidences, boxes and hOCR for citation regions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pytesseract
from PIL import Image

from archive.config import get_settings

LANG_CODES = {"en": "eng", "hi": "hin", "mr": "mar"}


@dataclass
class LocalOcrOutput:
    text: str
    words: list[dict[str, Any]]
    hocr: bytes
    engine_version: str


class LocalOcrUnavailable(RuntimeError):
    pass


def engine_version() -> str:
    pytesseract.pytesseract.tesseract_cmd = get_settings().tesseract_cmd
    try:
        return f"tesseract {pytesseract.get_tesseract_version()}"
    except (pytesseract.TesseractNotFoundError, OSError) as exc:
        raise LocalOcrUnavailable(str(exc)) from exc


def run_ocr(gray: np.ndarray, language: str) -> LocalOcrOutput:
    version = engine_version()
    lang = LANG_CODES.get(language, "eng")
    img = Image.fromarray(gray)
    config = "--oem 1 --psm 3"
    data = pytesseract.image_to_data(img, lang=lang, config=config, output_type=pytesseract.Output.DICT)
    words: list[dict[str, Any]] = []
    lines: dict[tuple[int, int, int], list[str]] = {}
    for i, token in enumerate(data["text"]):
        conf = float(data["conf"][i])
        if conf < 0 or not token.strip():
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        words.append({"t": token, "c": round(conf, 1), "bbox": [x, y, x + w, y + h],
                      "line": [data["block_num"][i], data["par_num"][i], data["line_num"][i]]})
        lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(token)
    paragraphs: dict[tuple[int, int], list[str]] = {}
    for (b, p, _l), toks in sorted(lines.items()):
        paragraphs.setdefault((b, p), []).append(" ".join(toks))
    text = "\n\n".join("\n".join(ls) for _, ls in sorted(paragraphs.items()))
    hocr = pytesseract.image_to_pdf_or_hocr(img, lang=lang, config=config, extension="hocr")
    return LocalOcrOutput(text=text, words=words, hocr=hocr, engine_version=version)
