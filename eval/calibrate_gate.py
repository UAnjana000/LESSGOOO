"""Propose OCR quality-gate thresholds from the CALIBRATION half of the OCR ground-truth set and report
them on the TEST half (spec 4.3 "Calibration", 10.1, 10.2 OCR gate).

Input is the JSON written by `python -m archive.cli eval-ocr <ground_truth.json>` (its "rows" carry
split, doc_class, language, bad_page and the per-page quality signals). This script only reads that file
and writes a proposal under eval/results/. It never edits backend/archive/ingest/gate_thresholds.json;
the archivist and the backend owner adopt a proposal by hand and bump the gate version.

    python eval/calibrate_gate.py eval/results/ocr-2026-10-01.json --version gate-v1 \
        --out eval/results/gate-proposal-v1.json [--min-calibration-pages 10] [--allow-synthetic]

Rule per (doc_class, language) and per signal: pick the loosest threshold that still sends EVERY bad
calibration page to fallback, then count the good pages it would send unnecessarily. A group with fewer
than --min-calibration-pages pages, or with no bad page, gets no proposal.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from typing import Any

from evalkit import UNMEASURED, load_json, write_json

# signal -> (gate key, direction). "min": page fails when value < threshold. "max": fails when value > threshold.
SIGNALS: dict[str, tuple[str, str]] = {
    "mean_confidence": ("min_mean_confidence", "min"),
    "p10_confidence": ("min_p10_confidence", "min"),
    "coverage": ("min_coverage", "min"),
    "script_share": ("min_script_share", "min"),
    "lexicon_ratio": ("min_lexicon_ratio", "min"),
    "garbage_rate": ("max_garbage_rate", "max"),
    "word_count": ("min_words", "min"),
}
EPS = 1e-4


def _fails(value: float, threshold: float, direction: str) -> bool:
    return value < threshold if direction == "min" else value > threshold


def propose_threshold(bad: list[float], direction: str, integer: bool = False) -> float:
    if direction == "min":
        return float(max(bad) + (1 if integer else EPS))
    return float(min(bad) - EPS)


def calibrate(rows: list[dict[str, Any]], min_pages: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[f"{r['doc_class']}:{r['language']}"].append(r)
    out: dict[str, Any] = {}
    for gkey, grows in sorted(groups.items()):
        cal = [r for r in grows if r.get("split") == "calibration"]
        test = [r for r in grows if r.get("split") == "test"]
        bad = [r for r in cal if r.get("bad_page")]
        entry: dict[str, Any] = {"calibration_pages": len(cal), "calibration_bad_pages": len(bad),
                                 "test_pages": len(test), "signals": {}, "proposal": None}
        if len(cal) < min_pages:
            entry["status"] = f"INSUFFICIENT_SAMPLE (need >= {min_pages} calibration pages)"
        elif not bad:
            entry["status"] = "NO_BAD_PAGES_IN_CALIBRATION (cannot place a threshold)"
        else:
            entry["status"] = "PROPOSED"
        for signal, (gate_key, direction) in SIGNALS.items():
            cal_vals = [r for r in cal if signal in r.get("signals", {})]
            bad_vals = [r["signals"][signal] for r in cal_vals if r.get("bad_page")]
            if not bad_vals:
                continue
            thr = propose_threshold(bad_vals, direction, integer=signal == "word_count")
            good_cal = [r for r in cal_vals if not r.get("bad_page")]
            s: dict[str, Any] = {
                "gate_key": gate_key, "threshold": round(thr, 4),
                "calibration_good_sent": sum(_fails(r["signals"][signal], thr, direction) for r in good_cal),
                "calibration_good_pages": len(good_cal),
            }
            t_rows = [r for r in test if signal in r.get("signals", {})]
            t_bad = [r for r in t_rows if r.get("bad_page")]
            t_good = [r for r in t_rows if not r.get("bad_page")]
            s["test_bad_recall"] = (round(sum(_fails(r["signals"][signal], thr, direction) for r in t_bad) / len(t_bad), 4)
                                    if t_bad else UNMEASURED)
            s["test_good_sent_share"] = (round(sum(_fails(r["signals"][signal], thr, direction) for r in t_good) / len(t_good), 4)
                                         if t_good else UNMEASURED)
            s["test_n"] = len(t_rows)
            entry["signals"][signal] = s
        if entry["status"] == "PROPOSED" and entry["signals"]:
            best = min(entry["signals"].items(), key=lambda kv: kv[1]["calibration_good_sent"])
            entry["proposal"] = {best[1]["gate_key"]: best[1]["threshold"]}
            entry["proposal_basis"] = (f"'{best[0]}' catches every bad calibration page and sends the fewest "
                                       f"good ones; the archivist decides whether that loss is acceptable")
        out[gkey] = entry
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("eval_ocr_result", help="JSON written by archive.cli eval-ocr")
    ap.add_argument("--version", required=True, help="name for the proposed gate version, e.g. gate-v1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-calibration-pages", type=int, default=10)
    ap.add_argument("--allow-synthetic", action="store_true",
                    help="permit a smoke run on synthetic fixture pages (the proposal is labelled smoke-only)")
    args = ap.parse_args()

    data = load_json(args.eval_ocr_result)
    synthetic = "synthetic" in str(data.get("note", "")).lower()
    if synthetic and not args.allow_synthetic:
        sys.exit("Refusing: the OCR result was measured on SYNTHETIC fixture pages. Real calibration needs "
                 "hand-transcribed archive pages (spec 10.1). Use --allow-synthetic for a smoke run only.")
    groups = calibrate(data.get("rows", []), args.min_calibration_pages)
    proposal = {
        "version": args.version + ("-SMOKE-ONLY" if synthetic else ""),
        "status": "PROPOSAL - not adopted. Adopting it means copying thresholds into gate_thresholds.json "
                  "by the backend owner after archivist sign-off.",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "source_result": args.eval_ocr_result,
        "source_measured_at": data.get("measured_at"),
        "synthetic_fixture_input": synthetic,
        "min_calibration_pages": args.min_calibration_pages,
        "groups": groups,
    }
    print(write_json(args.out, proposal))
    for g, e in groups.items():
        print(f"{g:14s} {e['status']:60s} cal={e['calibration_pages']} bad={e['calibration_bad_pages']} "
              f"test={e['test_pages']} proposal={e['proposal']}")


if __name__ == "__main__":
    main()
