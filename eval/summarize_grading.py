"""Summarise human grading sheets into results-schema metric blocks (spec 5.7 "What validation does not
prove", 1.1 direct-quotation rule, 10.2 Answers and Translation).

    python eval/summarize_grading.py --claims eval/results/claim_support_grading.csv \
        --quotes eval/results/quote_verification_log.csv --translations eval/results/translation_ratings.csv

Rows from seeded fixtures (reviewer/grader/verifier 'fixture-seed' or is_seeded_fixture=true) are dropped
and counted separately: a seeded approval is not evidence that a person checked a real source.
Empty or missing sheets produce UNMEASURED blocks with n 0.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import statistics
from pathlib import Path
from typing import Any

from evalkit import MEASURED, UNMEASURED, is_seeded

SUPPORT_VALUES = {"supported", "partial", "unsupported"}


def read_rows(path: str | None) -> list[dict[str, str]]:
    if not path or not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]


def _block(value: Any, n: int, graders: set[str], evidence: str | None, **extra: Any) -> dict[str, Any]:
    if n == 0:
        return {"status": UNMEASURED, "value": None, "n": 0, "graders": [], "seeded_rows_excluded": True, **extra}
    return {"status": MEASURED, "value": value, "n": n, "graders": sorted(graders), "seeded_rows_excluded": True,
            "measured_at": dt.date.today().isoformat(), "evidence": evidence, "human_graded": True, **extra}


def claim_support(rows: list[dict[str, str]], evidence: str | None) -> dict[str, Any]:
    seeded = [r for r in rows if is_seeded(r)]
    human = [r for r in rows if not is_seeded(r)]
    graded = [r for r in human if (r.get("support") or "").strip().lower() in SUPPORT_VALUES and (r.get("grader") or "").strip()]
    invalid = len(human) - len(graded)
    graders = {r["grader"].strip() for r in graded}
    n = len(graded)
    supported = sum(1 for r in graded if r["support"].strip().lower() == "supported")
    not_supported = n - supported
    by_version: dict[str, dict[str, int]] = {}
    for r in graded:
        key = f"{r.get('prompt_version', '')}|{r.get('model', '')}"
        b = by_version.setdefault(key, {"n": 0, "supported": 0})
        b["n"] += 1
        b["supported"] += r["support"].strip().lower() == "supported"
    extra = {"seeded_rows_dropped": len(seeded), "ungraded_or_invalid_rows": invalid,
             "questions": len({r.get("question_id") for r in graded}), "by_prompt_model": by_version}
    return {
        "claim_support_rate": _block(round(supported / n, 4) if n else None, n, graders, evidence, **extra),
        "unsupported_claim_rate": _block(round(not_supported / n, 4) if n else None, n, graders, evidence,
                                         notes="'partial' counts as unsupported", **extra),
    }


def quote_checks(rows: list[dict[str, str]], evidence: str | None) -> dict[str, Any]:
    seeded = [r for r in rows if is_seeded(r)]
    human = [r for r in rows if not is_seeded(r)
             and (r.get("verifier") or "").strip()
             and (r.get("compared_with") or "").strip().lower() in {"scan", "recording"}
             and (r.get("result") or "").strip().lower() in {"match", "corrected"}]
    verifiers = {r["verifier"].strip() for r in human}
    return {"quotes_human_verified_against_source": _block(len(human) if human else None, len(human), verifiers,
                                                          evidence, seeded_rows_dropped=len(seeded))}


def translations(rows: list[dict[str, str]], evidence: str | None) -> dict[str, Any]:
    seeded = [r for r in rows if is_seeded(r)]
    human = [r for r in rows if not is_seeded(r) and (r.get("reviewer") or "").strip()]
    out: dict[str, Any] = {}
    for lang in ("hi", "mr"):
        lrows = [r for r in human if r.get("language") == lang]
        reviewers = {r["reviewer"].strip() for r in lrows}
        for field in ("adequacy", "fluency"):
            vals = [float(r[field]) for r in lrows if (r.get(field) or "").strip()]
            by_system: dict[str, float] = {}
            for system in sorted({r.get("system", "") for r in lrows}):
                sv = [float(r[field]) for r in lrows if r.get("system") == system and (r.get(field) or "").strip()]
                if sv:
                    by_system[system] = round(statistics.fmean(sv), 3)
            out[f"translation_{field}_{lang}"] = _block(round(statistics.fmean(vals), 3) if vals else None, len(vals),
                                                        reviewers, evidence, breakdown=by_system,
                                                        seeded_rows_dropped=len(seeded))
    appr = [r for r in human if (r.get("approved_without_edit") or "").strip().lower() in {"yes", "no"}]
    out["approved_without_edit_share"] = _block(
        round(sum(r["approved_without_edit"].strip().lower() == "yes" for r in appr) / len(appr), 4) if appr else None,
        len(appr), {r["reviewer"].strip() for r in appr}, evidence)
    ed = [float(r["edit_distance"]) for r in human if (r.get("edit_distance") or "").strip()]
    out["edit_distance_to_approved"] = _block(round(statistics.fmean(ed), 2) if ed else None, len(ed),
                                              {r["reviewer"].strip() for r in human if (r.get("edit_distance") or "").strip()},
                                              evidence)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claims")
    ap.add_argument("--quotes")
    ap.add_argument("--translations")
    args = ap.parse_args()
    result = {
        "answers": {**claim_support(read_rows(args.claims), args.claims),
                    **quote_checks(read_rows(args.quotes), args.quotes)},
        "multilingual": translations(read_rows(args.translations), args.translations),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
