"""Score OCR engine runs against the sample ground truth (docs/OCR_ENGINE_EVAL.md).

    backend\\.venv\\Scripts\\python.exe eval/ocr_engine/score.py --baseline t-fast-prod \
        --runs t-fast-prod t-best-cli paddle-v5 --out eval/results/ocr-engine-eval.json

Imports the backend (quality gate), so run it with the backend venv. For every run, language and page set
(clean / degraded) it reports page-mean CER and WER with a bootstrap 95% CI, the paired bootstrap CI of the
CER difference against --baseline (negative = fewer errors than the baseline), wall and CPU seconds per page,
and how the current quality gate's pass/fail lines up with CER. A page is "bad" when CER > --bad-cer; that
threshold is a working assumption until the archivist sets one (spec 4.3).

--calibration-out writes, per run, a file in the `archive.cli eval-ocr` row format so eval/calibrate_gate.py
can propose thresholds for that engine. Pages alternate between the calibration and test halves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

from evalkit import bootstrap_mean_ci, paired_bootstrap_diff, write_json  # noqa: E402

from archive.ingest.quality import apply_gate, compute_signals, load_gate_config  # noqa: E402

_DROP = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\ufffe\u00ad"), None)
# Visually identical or typographic variants an OCR engine cannot tell apart on the page.
_FOLD = str.maketrans({"ः": ":", "|": "।", "‘": "'", "’": "'", "“": "\"", "”": "\"", "–": "-", "—": "-",
                       "॰": ".", "\u2011": "-"})


def normalize(text: str) -> str:
    s = unicodedata.normalize("NFC", text).translate(_DROP).translate(_FOLD)
    s = s.replace("''", "\"").replace("ाॅ", "ॉ")
    return " ".join(s.split())


def cer_wer(ref: str, hyp: str) -> tuple[float, float]:
    r, h = normalize(ref), normalize(hyp)
    rw, hw = r.split(), h.split()
    return Levenshtein.distance(r, h) / max(1, len(r)), Levenshtein.distance(rw, hw) / max(1, len(rw))


def bow_error(ref: str, hyp: str) -> float:
    """Order-independent word error: 1 - Dice overlap of the word multisets. Tables read column-wise
    instead of row-wise score a high CER but a low bag-of-words error."""
    rc, hc = Counter(normalize(ref).split()), Counter(normalize(hyp).split())
    total = sum(rc.values()) + sum(hc.values())
    return 1.0 - 2 * sum((rc & hc).values()) / total if total else 0.0


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1])


def _ci(vals: list[float], samples: int) -> dict[str, Any]:
    m, lo, hi = bootstrap_mean_ci(vals, samples)
    return {"mean": round(m, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4)}


def load_run(runs_dir: Path, name: str, exclude: frozenset[str] = frozenset()
             ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    d = runs_dir / name
    meta = json.loads((d / "run.json").read_text(encoding="utf-8"))
    pages = {}
    for f in d.glob("*__*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r["key"].split("|")[0] not in exclude:
            pages[r["key"]] = r
    return meta, pages


def split_of(page_id: str) -> str:
    return "calibration" if int(hashlib.sha256(page_id.encode()).hexdigest(), 16) % 2 == 0 else "test"


def score_run(pages: dict[str, dict[str, Any]], gt: dict[str, str], gate_cfg: dict[str, Any],
              bad_cer: float) -> list[dict[str, Any]]:
    rows = []
    for key, r in sorted(pages.items()):
        pid, pset = key.split("|")
        c, w = cer_wer(gt[pid], r["text"])
        sig = compute_signals(r["words"], r["text"], r["language"], r["text_blocks"])
        dec = apply_gate(sig, "printed", r["language"], gate_cfg)
        rows.append({"key": key, "page_id": pid, "set": pset, "language": r["language"], "cer": c, "wer": w,
                     "bow": bow_error(gt[pid], r["text"]),
                     "seconds": r["seconds"], "cpu_seconds": r["cpu_seconds"], "signals": sig.as_dict(),
                     "gate_passed": dec.passed, "failed_checks": dec.failed_checks, "bad_page": c > bad_cer,
                     "words_have_boxes": bool(r["words"]) and all("bbox" in x for x in r["words"]),
                     "word_level": bool(r["words"]) and not any(x.get("approx") for x in r["words"])})
    return rows


def summarize(rows: list[dict[str, Any]], samples: int) -> dict[str, Any]:
    cer = [r["cer"] for r in rows]
    bad = [r for r in rows if r["bad_page"]]
    good = [r for r in rows if not r["bad_page"]]
    conf = [r["signals"]["mean_confidence"] for r in rows]
    return {
        "n": len(rows), "cer": _ci(cer, samples), "wer": _ci([r["wer"] for r in rows], samples),
        "bow": _ci([r["bow"] for r in rows], samples),
        "cer_median": round(statistics.median(cer), 4),
        "wall_s_per_page": round(statistics.fmean(r["seconds"] for r in rows), 2),
        "cpu_s_per_page": round(statistics.fmean(r["cpu_seconds"] for r in rows), 2),
        "gate": {
            "bad_pages": len(bad), "gate_pass_rate": round(sum(r["gate_passed"] for r in rows) / len(rows), 3),
            "bad_caught": round(sum(not r["gate_passed"] for r in bad) / len(bad), 3) if bad else None,
            "good_sent": round(sum(not r["gate_passed"] for r in good) / len(good), 3) if good else None,
            "spearman_meanconf_vs_cer": (round(s, 3) if (s := spearman(conf, cer)) is not None else None),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", default="data/ocr_eval")
    ap.add_argument("--runs-dir", default="data/ocr_eval/runs")
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--bad-cer", type=float, default=0.05)
    ap.add_argument("--samples", type=int, default=10000)
    ap.add_argument("--gate-config", default=None, help="gate_thresholds.json to test (default: current)")
    ap.add_argument("--out", default="eval/results/ocr-engine-eval.json")
    ap.add_argument("--calibration-out", default=None, help="directory for calibrate_gate.py inputs")
    ap.add_argument("--exclude", nargs="*", default=[], help="page ids left out (sensitivity analysis)")
    args = ap.parse_args()

    sample = Path(args.sample)
    gt = {p.stem: p.read_text(encoding="utf-8") for p in (sample / "gt").glob("*.txt")}
    gate_cfg = load_gate_config(args.gate_config)
    exclude = frozenset(args.exclude)
    base_meta, base_pages = load_run(Path(args.runs_dir), args.baseline, exclude)
    base_rows = {r["key"]: r for r in score_run(base_pages, gt, gate_cfg, args.bad_cer)}
    result: dict[str, Any] = {"baseline": args.baseline, "bad_cer": args.bad_cer, "gate_version": gate_cfg["version"],
                              "bootstrap_samples": args.samples, "excluded_pages": sorted(exclude), "runs": {}}
    for name in args.runs:
        meta, pages = load_run(Path(args.runs_dir), name, exclude)
        rows = base_rows.values() if name == args.baseline else score_run(pages, gt, gate_cfg, args.bad_cer)
        rows = list(rows)
        entry: dict[str, Any] = {"engine_version": meta["engine_version"], "config": meta["config"],
                                 "peak_memory": meta["peak_memory"], "host": meta["host"],
                                 "word_level_boxes": all(r["word_level"] for r in rows),
                                 "groups": {}}
        for lang in sorted({r["language"] for r in rows}):
            for pset in ("clean", "degraded", "all"):
                g = [r for r in rows if r["language"] == lang and (pset == "all" or r["set"] == pset)]
                if not g:
                    continue
                s = summarize(g, args.samples)
                paired = [(base_rows[r["key"]]["cer"], r["cer"]) for r in g if r["key"] in base_rows]
                if name != args.baseline and paired:
                    d, lo, hi = paired_bootstrap_diff([a for a, _ in paired], [b for _, b in paired], args.samples)
                    s["cer_diff_vs_baseline"] = {"n": len(paired), "delta": round(d, 4), "ci_low": round(lo, 4),
                                                 "ci_high": round(hi, 4), "separated": lo > 0 or hi < 0}
                entry["groups"][f"{lang}:{pset}"] = s
        result["runs"][name] = entry
        if args.calibration_out:
            cal_rows = [{"page_id": r["key"], "split": split_of(r["page_id"]), "doc_class": "printed",
                         "language": r["language"], "bad_page": r["bad_page"], "cer": round(r["cer"], 4),
                         "signals": r["signals"]} for r in rows]
            write_json(Path(args.calibration_out) / f"evalocr-{name}.json",
                       {"note": f"OCR engine eval sample: real archive PDF pages rendered clean plus synthetic "
                                f"degradations of the same pages, run {name}; "
                                f"bad_page = CER > {args.bad_cer}", "measured_at": meta["measured_at"],
                        "rows": cal_rows})
    write_json(args.out, result)
    print(f"{'run':24s} {'group':14s} {'n':>3s} {'CER':>7s} {'95% CI':>17s} {'WER':>7s} {'BoW':>6s} "
          f"{'dCER vs base [CI]':>28s} {'s/pg':>6s} {'cpu/pg':>6s} {'pass':>5s} {'rho':>6s}")
    for name, e in result["runs"].items():
        for gk, s in e["groups"].items():
            d = s.get("cer_diff_vs_baseline")
            ds = f"{d['delta']:+.4f} [{d['ci_low']:+.4f},{d['ci_high']:+.4f}]" if d else "-"
            print(f"{name:24s} {gk:14s} {s['n']:3d} {s['cer']['mean']:7.4f} "
                  f"[{s['cer']['ci_low']:.4f},{s['cer']['ci_high']:.4f}] {s['wer']['mean']:7.4f} {s['bow']['mean']:6.4f} {ds:>28s} "
                  f"{s['wall_s_per_page']:6.2f} {s['cpu_s_per_page']:6.2f} {s['gate']['gate_pass_rate']:5.2f} "
                  f"{str(s['gate']['spearman_meanconf_vs_cer']):>6s}")


if __name__ == "__main__":
    main()
