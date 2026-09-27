"""Local OCR engine: Tesseract 5 with eng/hin/mar traineddata (via pytesseract).

Chosen because it runs fully offline on the edge-server CPU, ships English, Hindi and Marathi
models in Debian packages, and emits word-level confidences, boxes and hOCR for citation regions.
Re-evaluated against PaddleOCR, EasyOCR and tessdata_best on archive pages: docs/OCR_ENGINE_EVAL.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract.pytesseract import file_to_dict, run_tesseract, save

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


def _tsv_and_hocr(img: Image.Image, lang: str, config: str) -> tuple[str, bytes]:
    """One tesseract process writes both TSV (words, confidences) and hOCR; recognition runs once."""
    with save(img) as (base, path):
        run_tesseract(path, base, "tsv hocr", lang, config=f"-c tessedit_create_tsv=1 {config}")
        return Path(f"{base}.tsv").read_text(encoding="utf-8"), Path(f"{base}.hocr").read_bytes()


def has_column_gutter(gray: np.ndarray) -> bool:
    """True when the page body has an (almost) empty vertical band in its middle 40% with text on both sides:
    two or more columns, or a table. A full-width heading may cross the band (up to 3% of body rows)."""
    h, w = gray.shape
    if h < 200 or w < 200:
        return False
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    body = binary[int(h * 0.08): int(h * 0.92)] > 0
    rows_inked = body.any(axis=1).sum()
    if rows_inked == 0:
        return False
    col_ink = body.sum(axis=0)
    lo, hi = int(w * 0.3), int(w * 0.7)
    empty = col_ink[lo:hi] <= 0.03 * rows_inked
    need = max(3, w // 100)
    run = best = best_end = 0
    for i, e in enumerate(empty):
        run = run + 1 if e else 0
        if run > best:
            best, best_end = run, lo + i
    if best < need:
        return False
    x = best_end - best // 2
    left, right = col_ink[:x].sum(), col_ink[x:].sum()
    return min(left, right) >= 0.2 * (left + right)


def page_segmentation_mode(gray: np.ndarray) -> int:
    mode = get_settings().ocr_tesseract_psm
    if mode == "auto":
        return 3 if has_column_gutter(gray) else 6
    return int(mode)


@lru_cache(maxsize=4)
def _installed_langs(tesseract_cmd: str) -> frozenset[str] | None:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    try:
        return frozenset(pytesseract.get_languages(config=""))
    except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError, OSError):
        return None


def debian_lang(language: str) -> str:
    return LANG_CODES.get(language, "eng")


def tesseract_lang(language: str) -> str:
    """Configured model for the page language; Debian eng/hin/mar when that model is not installed.

    The ocr-deva image sets Hindi to the tessdata_best Devanagari script model. api:local does not
    ship that file, so a missing-language probe (or a later TesseractError) falls back to hin.
    """
    s = get_settings()
    default = debian_lang(language)
    configured = {"en": s.ocr_tesseract_lang_en, "hi": s.ocr_tesseract_lang_hi,
                  "mr": s.ocr_tesseract_lang_mr}.get(language) or default
    installed = _installed_langs(s.tesseract_cmd)
    if installed is not None and not set(configured.split("+")) <= installed:
        return default
    return configured


def run_ocr(gray: np.ndarray, language: str) -> LocalOcrOutput:
    psm = page_segmentation_mode(gray)
    tess = engine_version()
    lang = tesseract_lang(language)
    config = f"--oem 1 --psm {psm}"
    img = Image.fromarray(gray)
    try:
        tsv, hocr = _tsv_and_hocr(img, lang, config)
    except pytesseract.TesseractError:
        fallback = debian_lang(language)
        if lang == fallback:
            raise
        lang = fallback
        tsv, hocr = _tsv_and_hocr(img, lang, config)
    version = f"{tess} {lang} psm{psm}"
    data = file_to_dict(tsv, "\t", -1)
    words: list[dict[str, Any]] = []
    lines: dict[tuple[int, int, int], list[str]] = {}
    for i, token in enumerate(data.get("text", [])):
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
    return LocalOcrOutput(text=text, words=words, hocr=hocr, engine_version=version)
