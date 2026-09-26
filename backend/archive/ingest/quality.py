"""Per-page OCR quality signals and the versioned quality gate (spec 4.3)."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from archive.config import get_settings
from archive.ingest.lexicon import lexicon_for

SCRIPT_RANGES = {
    "Latn": [(0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F)],
    "Deva": [(0x0900, 0x097F), (0xA8E0, 0xA8FF)],
}
LANG_SCRIPT = {"en": "Latn", "hi": "Deva", "mr": "Deva"}
TOKEN_RE = re.compile(r"\S+")
WORD_STRIP = "\"'“”‘’.,;:!?()[]{}—–-…।॥"


def _in_script(ch: str, script: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in SCRIPT_RANGES[script])


def script_share(text: str, language: str) -> float:
    script = LANG_SCRIPT.get(language, "Latn")
    letters = [c for c in text if unicodedata.category(c).startswith(("L", "M"))]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _in_script(c, script)) / len(letters)


def _is_garbage(token: str) -> bool:
    core = token.strip(WORD_STRIP)
    if not core:
        return len(token) > 2  # runs of stray punctuation
    letters = sum(1 for c in core if unicodedata.category(c).startswith(("L", "M")))
    digits = sum(1 for c in core if c.isdigit())
    symbols = len(core) - letters - digits
    if symbols / len(core) > 0.3:
        return True
    if letters and digits and letters < len(core) * 0.6:
        return True  # mixed junk like "l1I|"
    if re.search(r"(.)\1{3,}", core):
        return True
    return False


def garbage_rate(text: str) -> float:
    tokens = TOKEN_RE.findall(text)
    if not tokens:
        return 1.0
    return sum(1 for t in tokens if _is_garbage(t)) / len(tokens)


def lexicon_ratio(text: str, language: str) -> float:
    lex = lexicon_for(language)
    tokens = [t.strip(WORD_STRIP).lower() for t in TOKEN_RE.findall(text)]
    tokens = [t for t in tokens if t]
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if t in lex) / len(tokens)


def _box_area(b: list[int]) -> int:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def coverage(text_blocks: list[list[int]], words: list[dict[str, Any]], min_conf: float = 30.0) -> float:
    """Share of layout-detected text-block area that produced OCR words (spec 4.3 item 2)."""
    total = sum(_box_area(b) for b in text_blocks)
    if total == 0:
        return 0.0 if words else 1.0
    covered = 0
    good = [w["bbox"] for w in words if w.get("c", 0) >= min_conf and w.get("t", "").strip()]
    for block in text_blocks:
        hit = any(
            not (w[2] < block[0] or w[0] > block[2] or w[3] < block[1] or w[1] > block[3]) for w in good
        )
        if hit:
            covered += _box_area(block)
    return covered / total


@dataclass
class QualitySignals:
    word_count: int
    mean_confidence: float
    p10_confidence: float
    coverage: float
    script_share: float
    lexicon_ratio: float
    garbage_rate: float

    def as_dict(self) -> dict[str, Any]:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def compute_signals(words: list[dict[str, Any]], text: str, language: str,
                    text_blocks: list[list[int]]) -> QualitySignals:
    confs = np.array([w["c"] for w in words if w.get("t", "").strip()], dtype=float)
    return QualitySignals(
        word_count=int(confs.size),
        mean_confidence=float(confs.mean()) if confs.size else 0.0,
        p10_confidence=float(np.percentile(confs, 10)) if confs.size else 0.0,
        coverage=coverage(text_blocks, words),
        script_share=script_share(text, language),
        lexicon_ratio=lexicon_ratio(text, language),
        garbage_rate=garbage_rate(text),
    )


@dataclass
class GateDecision:
    passed: bool
    version: str
    failed_checks: list[str]
    thresholds: dict[str, float]


@lru_cache
def load_gate_config(path: str | None = None) -> dict[str, Any]:
    p = Path(path or get_settings().gate_config_path)
    return json.loads(p.read_text(encoding="utf-8"))


def thresholds_for(config: dict[str, Any], doc_class: str, language: str) -> dict[str, float]:
    merged = dict(config["default"])
    merged.update(config.get(f"{doc_class}:{language}", {}))
    return merged


def apply_gate(signals: QualitySignals, doc_class: str, language: str,
               config: dict[str, Any] | None = None) -> GateDecision:
    config = config or load_gate_config()
    t = thresholds_for(config, doc_class, language)
    checks = {
        "min_words": signals.word_count >= t["min_words"],
        "min_mean_confidence": signals.mean_confidence >= t["min_mean_confidence"],
        "min_p10_confidence": signals.p10_confidence >= t["min_p10_confidence"],
        "min_coverage": signals.coverage >= t["min_coverage"],
        "min_script_share": signals.script_share >= t["min_script_share"],
        "min_lexicon_ratio": signals.lexicon_ratio >= t["min_lexicon_ratio"],
        "max_garbage_rate": signals.garbage_rate <= t["max_garbage_rate"],
    }
    failed = [k for k, ok in checks.items() if not ok]
    return GateDecision(passed=not failed, version=config["version"], failed_checks=failed, thresholds=t)


def review_priority(signals: QualitySignals, disagreement: float | None) -> float:
    """Higher = review sooner. Gate score and local/Sarvam disagreement only set priority."""
    base = (100 - signals.mean_confidence) / 100 + (1 - signals.coverage) + signals.garbage_rate
    return round(base + (disagreement or 0.0), 4)
