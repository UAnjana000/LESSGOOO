"""Validate a filled results file before any number is quoted (spec 10: "every claim comes from this table,
reported with sample size").

    python eval/check_results.py eval/results/results-2026-10-01.json [--markdown]

Exit code 1 if any rule is broken. --markdown prints the results table with sample sizes, showing
UNMEASURED for everything that was not measured.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from evalkit import MEASURED, STATUSES, UNMEASURED, load_json
from results_schema import AREAS, REQUIRED_AREAS


def check(results: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    areas = results.get("areas", {})
    for key in REQUIRED_AREAS:
        if key not in areas:
            errors.append(f"area '{key}' missing (every spec 10.2 area must be present, even if UNMEASURED)")
            continue
        for name, _unit, _comp, _how, _hg in AREAS[key]["metrics"]:
            if name not in areas[key].get("metrics", {}):
                errors.append(f"{key}.{name}: metric missing")

    any_measured = False
    synthetic = bool(results.get("run", {}).get("dataset", {}).get("is_synthetic_fixture"))
    for key, area in areas.items():
        gated = bool(area.get("gated"))
        gate_met = (area.get("gate") or {}).get("met") is True
        for name, m in area.get("metrics", {}).items():
            where = f"{key}.{name}"
            status = m.get("status")
            if status not in STATUSES:
                errors.append(f"{where}: status must be one of {sorted(STATUSES)}, got {status!r}")
                continue
            if status != MEASURED:
                if m.get("value") is not None:
                    errors.append(f"{where}: {status} metric must have value null")
                if m.get("n") not in (0, None):
                    errors.append(f"{where}: {status} metric must have n 0 or blank")
                continue
            any_measured = True
            if m.get("value") is None:
                errors.append(f"{where}: MEASURED but value is null")
            n = m.get("n")
            if not isinstance(n, int) or n <= 0:
                errors.append(f"{where}: MEASURED needs an integer sample size n > 0")
            for field in ("measured_at", "method", "evidence"):
                if not m.get(field):
                    errors.append(f"{where}: MEASURED needs '{field}'")
            if m.get("human_graded"):
                if not m.get("graders"):
                    errors.append(f"{where}: human-graded metric needs named graders")
                if m.get("seeded_rows_excluded") is not True:
                    errors.append(f"{where}: seeded fixture rows must be excluded (seeded_rows_excluded: true)")
            if gated and not gate_met:
                errors.append(f"{where}: trained-model result reported but the spec 7.3 gate is not met")
            if name.endswith("_delta") and (m.get("ci_low") is None or m.get("ci_high") is None):
                errors.append(f"{where}: a difference needs a confidence interval (ci_low, ci_high)")
            if synthetic:
                warnings.append(f"{where}: measured on synthetic fixtures - smoke test, not spec 10 evidence")

    if any_measured:
        run = results.get("run", {})
        if not run.get("date"):
            errors.append("run.date is required once anything is measured")
        ds = run.get("dataset", {})
        if ds.get("is_synthetic_fixture") is None:
            errors.append("run.dataset.is_synthetic_fixture must be true or false once anything is measured")
        versions = run.get("versions", {})
        for v in ("gate_version", "prompt_version", "embedding_model", "reranker_model"):
            if not versions.get(v):
                warnings.append(f"run.versions.{v} is blank; spec 10 asks for model, prompt and gate versions")
    return errors, warnings


def counts(results: dict[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for key, area in results.get("areas", {}).items():
        c = {"MEASURED": 0, "UNMEASURED": 0, "BLOCKED": 0}
        for m in area.get("metrics", {}).values():
            c[m.get("status", UNMEASURED)] = c.get(m.get("status", UNMEASURED), 0) + 1
        out[key] = c
    return out


def markdown(results: dict[str, Any]) -> str:
    lines = ["| Area | Metric | Status | Value | n | Comparison | Evidence |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for key, area in results.get("areas", {}).items():
        for name, m in area.get("metrics", {}).items():
            value = "" if m.get("value") is None else m["value"]
            n = "" if not m.get("n") else m["n"]
            lines.append(f"| {area.get('title', key)} | {name} | {m.get('status')} | {value} | {n} | "
                         f"{m.get('comparison', '')} | {m.get('evidence') or ''} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    results = load_json(args.path)
    errors, warnings = check(results)
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR   {e}")
    for key, c in counts(results).items():
        print(f"{key:18s} measured={c['MEASURED']:2d} unmeasured={c['UNMEASURED']:2d} blocked={c['BLOCKED']:2d}")
    if args.markdown:
        print()
        print(markdown(results))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
