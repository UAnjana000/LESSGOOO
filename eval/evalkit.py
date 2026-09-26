"""Shared helpers for the standalone evaluation scripts (spec 10). Standard library only, so the
scripts run on any machine with Python 3.10+ and never import or modify the backend."""

from __future__ import annotations

import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Iterable

UNMEASURED = "UNMEASURED"
MEASURED = "MEASURED"
BLOCKED = "BLOCKED"
STATUSES = {UNMEASURED, MEASURED, BLOCKED}

SEEDED_REVIEWERS = {"fixture-seed"}


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, obj: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def percentile(values: Iterable[float], p: float) -> float | None:
    """Nearest-rank percentile (p in 0..100). None for an empty sample: never invent a number."""
    v = sorted(values)
    if not v:
        return None
    rank = max(1, math.ceil(p / 100 * len(v)))
    return v[rank - 1]


def bootstrap_mean_ci(values: list[float], samples: int = 1000, seed: int = 7,
                      alpha: float = 0.05) -> tuple[float, float, float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples))
    lo = means[int(alpha / 2 * samples)]
    hi = means[min(samples - 1, int((1 - alpha / 2) * samples) - 1)]
    return statistics.fmean(values), lo, hi


def paired_bootstrap_diff(a: list[float], b: list[float], samples: int = 1000, seed: int = 7,
                          alpha: float = 0.05) -> tuple[float, float, float]:
    """Mean of (b - a) over paired questions with a percentile bootstrap CI."""
    if len(a) != len(b) or not a:
        raise ValueError("paired samples must be non-empty and the same length")
    diffs = [y - x for x, y in zip(a, b)]
    ci = bootstrap_mean_ci(diffs, samples, seed, alpha)
    assert ci is not None
    return ci


def is_seeded(row: dict[str, Any]) -> bool:
    """Seeded fixture approvals (reviewer 'fixture-seed' or is_seeded_fixture=true) are not human evidence."""
    flag = str(row.get("is_seeded_fixture", "")).strip().lower() in {"1", "true", "yes"}
    who = str(row.get("reviewer") or row.get("grader") or row.get("verifier") or "").strip().lower()
    return flag or who in SEEDED_REVIEWERS
