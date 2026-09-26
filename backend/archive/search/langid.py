"""Language identification without an LLM (spec 5.7 step 2).

Uses the Lingua detector restricted to English, Hindi and Marathi (offline, rule+n-gram model).
IndicLID was considered but needs a large BERT model plus fastText; Lingua covers the three
prototype languages at a fraction of the memory. Devanagari script is used as a hard prior.
"""

from __future__ import annotations

from functools import lru_cache

from lingua import Language, LanguageDetectorBuilder

_MAP = {Language.ENGLISH: "en", Language.HINDI: "hi", Language.MARATHI: "mr"}


@lru_cache
def _detector():
    return LanguageDetectorBuilder.from_languages(*_MAP).with_preloaded_language_models().build()


def _has_devanagari(text: str) -> bool:
    return any(0x0900 <= ord(c) <= 0x097F for c in text)


def detect_language(text: str, fallback: str = "en") -> str:
    text = text.strip()
    if not text:
        return fallback
    if not _has_devanagari(text):
        return "en"
    values = _detector().compute_language_confidence_values(text)
    deva = [v for v in values if v.language in (Language.HINDI, Language.MARATHI)]
    if not deva:
        return "hi"
    return _MAP[max(deva, key=lambda v: v.value).language]
