"""Unit tests for the local OCR wrapper with a test double for the tesseract binary (no Tesseract needed)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from archive.ingest import ocr_local

_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
_ROWS = [
    "1\t1\t0\t0\t0\t0\t0\t0\t800\t1000\t-1\t",
    "5\t1\t1\t1\t1\t1\t60\t80\t120\t30\t96.734\tWe,",
    "5\t1\t1\t1\t1\t2\t190\t80\t90\t30\t91.2\tthe",
    "5\t1\t1\t1\t2\t1\t60\t120\t140\t30\t88\tpeople",
    "5\t1\t1\t1\t2\t2\t210\t120\t10\t30\t95\t ",
    "5\t1\t2\t1\t1\t1\t60\t300\t160\t30\t-1\t",
    "5\t1\t2\t1\t1\t2\t230\t300\t80\t30\t42.9\tIndia",
]
_HOCR = b"<?xml version='1.0'?><html><body><div class='ocr_page'></div></body></html>"


@pytest.fixture
def fake_tesseract(monkeypatch):
    calls: list[dict] = []

    def run_tesseract(input_filename, output_filename_base, extension, lang, config="", nice=0, timeout=0):
        calls.append({"input": input_filename, "extension": extension, "lang": lang, "config": config})
        Path(f"{output_filename_base}.tsv").write_text("\n".join([_HEADER, *_ROWS]) + "\n", encoding="utf-8")
        Path(f"{output_filename_base}.hocr").write_bytes(_HOCR)

    monkeypatch.setattr(ocr_local, "run_tesseract", run_tesseract)
    monkeypatch.setattr(ocr_local.pytesseract, "get_tesseract_version", lambda: "5.3.0")
    return calls


def _page() -> np.ndarray:
    return np.full((100, 80), 250, dtype=np.uint8)


def test_one_tesseract_process_yields_words_text_and_hocr(fake_tesseract):
    out = ocr_local.run_ocr(_page(), "en")

    assert len(fake_tesseract) == 1
    call = fake_tesseract[0]
    assert call["extension"] == "tsv hocr" and call["lang"] == "eng"
    assert "tessedit_create_tsv=1" in call["config"] and "--oem 1 --psm 3" in call["config"]
    assert out.engine_version == "tesseract 5.3.0 eng psm3"
    assert out.hocr == _HOCR
    assert out.text == "We, the\npeople\n\nIndia"


def test_words_keep_boxes_integer_confidences_and_line_keys(fake_tesseract):
    words = ocr_local.run_ocr(_page(), "en").words

    assert [w["t"] for w in words] == ["We,", "the", "people", "India"]
    assert words[0] == {"t": "We,", "c": 96.0, "bbox": [60, 80, 180, 110], "line": [1, 1, 1]}
    assert [w["c"] for w in words] == [96.0, 91.0, 88.0, 42.0]
    assert words[3]["line"] == [2, 1, 1]


@pytest.mark.parametrize("language,code", [("en", "eng"), ("hi", "hin"), ("mr", "mar"), ("xx", "eng")])
def test_language_codes(fake_tesseract, language, code):
    ocr_local.run_ocr(_page(), language)
    assert fake_tesseract[0]["lang"] == code


def test_temporary_files_are_removed(fake_tesseract):
    ocr_local.run_ocr(_page(), "en")
    base = Path(fake_tesseract[0]["input"]).with_suffix("")
    assert not list(base.parent.glob(base.name + "*"))


def test_missing_binary_raises_unavailable(monkeypatch):
    def missing():
        raise ocr_local.pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(ocr_local.pytesseract, "get_tesseract_version", missing)
    with pytest.raises(ocr_local.LocalOcrUnavailable):
        ocr_local.run_ocr(_page(), "en")


@pytest.fixture
def settings_env(monkeypatch):
    from archive.config import get_settings

    def set_env(**values: str) -> None:
        for k, v in values.items():
            monkeypatch.setenv(f"ARCHIVE_{k.upper()}", v)
        get_settings.cache_clear()
        ocr_local._installed_langs.cache_clear()

    get_settings.cache_clear()
    ocr_local._installed_langs.cache_clear()
    yield set_env
    get_settings.cache_clear()
    ocr_local._installed_langs.cache_clear()


@pytest.fixture
def installed_langs(monkeypatch):
    """Control pytesseract.get_languages so fallback tests do not depend on the host binary."""
    langs: set[str] = {"eng", "hin", "mar"}

    def set_langs(*names: str) -> None:
        langs.clear()
        langs.update(names)
        ocr_local._installed_langs.cache_clear()

    monkeypatch.setattr(ocr_local.pytesseract, "get_languages", lambda config="": sorted(langs))
    ocr_local._installed_langs.cache_clear()
    yield set_langs
    ocr_local._installed_langs.cache_clear()


def _text_page(columns: int, heading: bool = False) -> np.ndarray:
    """Synthetic 1000x1400 page: dark 'text lines' in one full-width column or two columns with a gutter."""
    img = np.full((1400, 1000), 245, dtype=np.uint8)
    spans = [(80, 920)] if columns == 1 else [(80, 470), (530, 920)]
    for y in range(160, 1300, 28):
        for x0, x1 in spans:
            img[y:y + 14, x0:x1] = 20
    if heading:
        img[130:144, 80:920] = 20
    return img


def test_gutter_detected_on_two_columns_not_on_one():
    assert ocr_local.has_column_gutter(_text_page(2))
    assert ocr_local.has_column_gutter(_text_page(2, heading=True))
    assert not ocr_local.has_column_gutter(_text_page(1))
    assert not ocr_local.has_column_gutter(np.full((1400, 1000), 245, dtype=np.uint8))
    assert not ocr_local.has_column_gutter(np.full((100, 80), 245, dtype=np.uint8))


def test_gutter_needs_text_on_both_sides():
    img = _text_page(1)
    img[:, 450:] = 245
    assert not ocr_local.has_column_gutter(img)


@pytest.mark.parametrize("mode,columns,psm", [("3", 1, 3), ("6", 2, 6), ("auto", 1, 6), ("auto", 2, 3)])
def test_page_segmentation_setting(fake_tesseract, settings_env, mode, columns, psm):
    settings_env(ocr_tesseract_psm=mode)
    out = ocr_local.run_ocr(_text_page(columns), "en")
    assert f"--oem 1 --psm {psm}" in fake_tesseract[0]["config"]
    assert out.engine_version.endswith(f"psm{psm}")


def test_per_language_tesseract_models(fake_tesseract, settings_env, installed_langs):
    installed_langs("eng", "hin", "mar", "Devanagari")
    settings_env(ocr_tesseract_lang_hi="Devanagari")
    hi = ocr_local.run_ocr(_page(), "hi")
    en = ocr_local.run_ocr(_page(), "en")
    assert [c["lang"] for c in fake_tesseract] == ["Devanagari", "eng"]
    assert hi.engine_version == "tesseract 5.3.0 Devanagari psm3" and en.engine_version == "tesseract 5.3.0 eng psm3"


def test_falls_back_to_hin_when_devanagari_not_installed(fake_tesseract, settings_env, installed_langs):
    installed_langs("eng", "hin", "mar")
    settings_env(ocr_tesseract_lang_hi="Devanagari")
    out = ocr_local.run_ocr(_page(), "hi")
    assert fake_tesseract[0]["lang"] == "hin"
    assert out.engine_version == "tesseract 5.3.0 hin psm3"


def test_compound_model_falls_back_if_any_part_is_missing(fake_tesseract, settings_env, installed_langs):
    installed_langs("eng", "hin", "mar")
    settings_env(ocr_tesseract_lang_hi="Devanagari+eng")
    ocr_local.run_ocr(_page(), "hi")
    assert fake_tesseract[0]["lang"] == "hin"


def test_probe_failure_uses_configured_model(fake_tesseract, settings_env, monkeypatch):
    def boom(config=""):
        raise ocr_local.pytesseract.TesseractError(1, "list-langs failed")

    monkeypatch.setattr(ocr_local.pytesseract, "get_languages", boom)
    ocr_local._installed_langs.cache_clear()
    settings_env(ocr_tesseract_lang_hi="Devanagari")
    ocr_local.run_ocr(_page(), "hi")
    assert fake_tesseract[0]["lang"] == "Devanagari"


def test_runtime_error_on_configured_model_retries_debian_lang(settings_env, installed_langs, monkeypatch):
    calls: list[str] = []

    def run_tesseract(input_filename, output_filename_base, extension, lang, config="", nice=0, timeout=0):
        calls.append(lang)
        if lang == "Devanagari":
            raise ocr_local.pytesseract.TesseractError(1, "Error opening data file Devanagari.traineddata")
        Path(f"{output_filename_base}.tsv").write_text("\n".join([_HEADER, *_ROWS]) + "\n", encoding="utf-8")
        Path(f"{output_filename_base}.hocr").write_bytes(_HOCR)

    monkeypatch.setattr(ocr_local, "run_tesseract", run_tesseract)
    monkeypatch.setattr(ocr_local.pytesseract, "get_tesseract_version", lambda: "5.3.0")
    installed_langs("eng", "hin", "mar", "Devanagari")
    settings_env(ocr_tesseract_lang_hi="Devanagari")
    out = ocr_local.run_ocr(_page(), "hi")
    assert calls == ["Devanagari", "hin"]
    assert out.engine_version == "tesseract 5.3.0 hin psm3"
    assert out.text == "We, the\npeople\n\nIndia"


def test_runtime_error_on_debian_lang_is_not_retried(settings_env, installed_langs, monkeypatch):
    def run_tesseract(input_filename, output_filename_base, extension, lang, config="", nice=0, timeout=0):
        raise ocr_local.pytesseract.TesseractError(1, "tesseract crashed")

    monkeypatch.setattr(ocr_local, "run_tesseract", run_tesseract)
    monkeypatch.setattr(ocr_local.pytesseract, "get_tesseract_version", lambda: "5.3.0")
    installed_langs("eng", "hin", "mar")
    settings_env(ocr_tesseract_lang_hi="hin")
    with pytest.raises(ocr_local.pytesseract.TesseractError):
        ocr_local.run_ocr(_page(), "hi")
