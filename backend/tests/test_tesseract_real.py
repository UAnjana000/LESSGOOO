"""Real Tesseract (marker `tesseract`): skipped when the binary or eng/hin/mar data are missing."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from archive.config import get_settings
from archive.ingest import ocr_local, preprocess
from archive.ingest.quality import script_share

from .conftest import FIXTURES

pytestmark = pytest.mark.tesseract


def _installed_langs() -> set[str]:
    cmd = get_settings().tesseract_cmd
    if shutil.which(cmd) is None:
        return set()
    out = subprocess.run([cmd, "--list-langs"], capture_output=True, text=True, timeout=30)
    return {ln.strip() for ln in (out.stdout + out.stderr).splitlines()}


if not {"eng", "hin", "mar"} <= _installed_langs():
    pytest.skip("tesseract with eng/hin/mar data not installed", allow_module_level=True)


def _page(lines: list[str]) -> np.ndarray:
    img = Image.new("L", (1700, 900), 255)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 44)
    except OSError:
        font = ImageFont.load_default(size=44)
    for i, line in enumerate(lines):
        d.text((100, 100 + i * 90), line, fill=0, font=font)
    return np.array(img)


LINES = ["WE, THE PEOPLE OF INDIA, having solemnly", "resolved to constitute India into a",
         "SOVEREIGN SOCIALIST SECULAR DEMOCRATIC REPUBLIC"]


def test_english_page_words_boxes_confidences_and_hocr():
    out = ocr_local.run_ocr(_page(LINES), "en")

    assert out.engine_version.startswith("tesseract 5")
    assert "PEOPLE OF INDIA" in out.text and "SOVEREIGN" in out.text
    assert len(out.words) >= 15
    for w in out.words:
        x0, y0, x1, y1 = w["bbox"]
        assert 0 <= x0 < x1 and 0 <= y0 < y1
        assert 0 <= w["c"] <= 100
    assert sum(w["c"] for w in out.words) / len(out.words) > 80
    assert b"ocr_page" in out.hocr and b"ocrx_word" in out.hocr


def test_single_pass_matches_separate_data_and_hocr_calls():
    gray = _page(LINES)
    out = ocr_local.run_ocr(gray, "en")
    data = ocr_local.pytesseract.image_to_data(Image.fromarray(gray), lang="eng", config="--oem 1 --psm 3",
                                               output_type=ocr_local.pytesseract.Output.DICT)
    expected = [(t, float(c)) for t, c in zip(data["text"], data["conf"]) if float(c) >= 0 and t.strip()]

    assert [(w["t"], w["c"]) for w in out.words] == expected


@pytest.mark.parametrize("fixture,language", [("fx-pamphlet-hi.png", "hi"), ("fx-petition-mr.png", "mr")])
def test_devanagari_fixture_pages(fixture, language):
    gray = preprocess.load_gray((FIXTURES / "files" / fixture).read_bytes())
    out = ocr_local.run_ocr(gray, language)

    assert len(out.words) >= 20
    assert script_share(out.text, language) > 0.9
    assert sum(w["c"] for w in out.words) / len(out.words) > 70
    assert b"ocrx_word" in out.hocr
