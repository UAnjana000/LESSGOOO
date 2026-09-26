"""Base-model baseline with a confidence interval (P1), and trained-vs-base comparison (P2, gated).

Input CSV, one row per held-out TEST question: question_id,language,base[,trained]
(the per-question metric, e.g. reciprocal rank from eval-retrieval, for each model on identical candidates).

    # P1: baseline only - no trained model, no improvement claim
    python eval/paired_bootstrap.py scores.csv --baseline-only

    # P2: only when the spec 7.3 minimum-data gate is met
    python eval/paired_bootstrap.py scores.csv --gate-report dataset_gate_report.json

The comparison refuses to run unless the gate report (DatasetVersion.gate_report from
`archive.cli freeze-dataset`) says met: true. Per-language results are printed only for languages the
gate lists as claimable (enough test examples of their own). A difference is called separated only when
its confidence interval excludes zero.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any

from evalkit import bootstrap_mean_ci, load_json, paired_bootstrap_diff


def read_scores(path: str) -> list[dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def baseline(rows: list[dict[str, Any]], samples: int) -> dict[str, Any]:
    vals = [float(r["base"]) for r in rows]
    ci = bootstrap_mean_ci(vals, samples)
    out: dict[str, Any] = {"n": len(vals), "mode": "baseline_only", "improvement_claimed": False}
    if ci:
        out.update({"base_mean": round(ci[0], 4), "ci_low": round(ci[1], 4), "ci_high": round(ci[2], 4)})
    by_lang: dict[str, Any] = {}
    for lang in sorted({r["language"] for r in rows}):
        lv = [float(r["base"]) for r in rows if r["language"] == lang]
        lci = bootstrap_mean_ci(lv, samples)
        if lci:
            by_lang[lang] = {"n": len(lv), "base_mean": round(lci[0], 4), "ci_low": round(lci[1], 4),
                             "ci_high": round(lci[2], 4)}
    out["by_language"] = by_lang
    return out


def compare(rows: list[dict[str, Any]], gate: dict[str, Any], samples: int) -> dict[str, Any]:
    if gate.get("met") is not True:
        raise PermissionError("spec 7.3 minimum-data gate not met: report the base-model baseline only")
    rows = [r for r in rows if (r.get("trained") or "").strip()]
    a = [float(r["base"]) for r in rows]
    b = [float(r["trained"]) for r in rows]
    mean_d, lo, hi = paired_bootstrap_diff(a, b, samples)
    out: dict[str, Any] = {"n": len(rows), "mode": "paired_comparison", "gate_version": gate.get("gate_version"),
                           "base_mean": round(sum(a) / len(a), 4), "trained_mean": round(sum(b) / len(b), 4),
                           "delta": round(mean_d, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                           "separated": lo > 0 or hi < 0}
    claimable = set(gate.get("claimable_languages", []))
    by_lang: dict[str, Any] = {}
    for lang in sorted({r["language"] for r in rows}):
        if lang not in claimable:
            by_lang[lang] = {"status": "UNMEASURED", "reason": "not enough test examples in this language for a claim"}
            continue
        la = [float(r["base"]) for r in rows if r["language"] == lang]
        lb = [float(r["trained"]) for r in rows if r["language"] == lang]
        d, llo, lhi = paired_bootstrap_diff(la, lb, samples)
        by_lang[lang] = {"n": len(la), "delta": round(d, 4), "ci_low": round(llo, 4), "ci_high": round(lhi, 4),
                         "separated": llo > 0 or lhi < 0}
    out["by_language"] = by_lang
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scores")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline-only", action="store_true")
    mode.add_argument("--gate-report", help="JSON gate report from the frozen dataset version")
    ap.add_argument("--samples", type=int, default=1000)
    args = ap.parse_args()
    rows = read_scores(args.scores)
    if args.baseline_only:
        print(json.dumps(baseline(rows, args.samples), indent=2))
        return
    try:
        print(json.dumps(compare(rows, load_json(args.gate_report), args.samples), indent=2))
    except PermissionError as exc:
        sys.exit(f"Refusing: {exc}")


if __name__ == "__main__":
    main()
