"""Paired cross-encoder latency benchmark for the rerank candidate pool / per-passage character cap.

End-to-end runs of bench_ask.py on a shared, busy machine drift by tens of percent between runs, so
configuration latency is compared here in one process: every round scores the same fused candidates for every
question under every configuration, in shuffled order, and reports each configuration's time relative to the
baseline in the same round. Accuracy for the same configurations comes from bench_ask.py (--set ...).

Needs the archive_bench database seeded by bench_ask.py (run that first). Run from the repo root:

    backend\\.venv\\Scripts\\python.exe eval/bench/bench_rerank.py --out eval/results/bench-rerank.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = [(30, 900), (15, 900), (10, 900), (30, 512), (10, 512)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--db-url", default="postgresql+psycopg://archive:archive-dev@127.0.0.1:55432/archive_bench")
    ap.add_argument("--model-cache", default=str(Path(tempfile.gettempdir()) / "archive-bench-models"))
    args = ap.parse_args()
    os.environ.update({"ARCHIVE_DATABASE_URL": args.db_url, "ARCHIVE_EMBEDDING_BACKEND": "fastembed",
                       "ARCHIVE_RERANKER_BACKEND": "fastembed", "ARCHIVE_MODEL_CACHE": args.model_cache,
                       "ARCHIVE_LANGFUSE_PUBLIC_KEY": "", "ARCHIVE_LANGFUSE_SECRET_KEY": ""})
    sys.path.insert(0, str(ROOT / "backend"))

    from archive.db import new_session
    from archive.search.hybrid import SearchFilters, hybrid_search
    from archive.search.models import get_reranker

    questions = [q for q in json.loads((ROOT / "eval/bench/ask_questions.json").read_text(encoding="utf-8"))["questions"]
                 if q["expected"] in ("answer", "not_in_archive")]
    db = new_session()
    cands = []
    for q in questions:
        hits, _ = hybrid_search(db, q["question"], SearchFilters(), limit=max(k for k, _ in CONFIGS), rerank=False)
        cands.append((q["question"], [h.text for h in hits]))
    db.close()
    if not any(t for _, t in cands):
        raise SystemExit("archive_bench is empty: run eval/bench/bench_ask.py first")
    rr = get_reranker()
    rr.score("warm up", ["warm up passage"])

    ms: dict[tuple[int, int], list[float]] = {c: [] for c in CONFIGS}
    rel: dict[tuple[int, int], list[float]] = {c: [] for c in CONFIGS}
    rng = random.Random(7)
    for _ in range(args.rounds):
        for query, texts in cands:
            order = CONFIGS[:]
            rng.shuffle(order)
            took = {}
            for k, c in order:
                t0 = time.perf_counter()
                rr.score(query, [t[:c] for t in texts[:k]])
                took[(k, c)] = (time.perf_counter() - t0) * 1000
            for cfg, v in took.items():
                ms[cfg].append(v)
                rel[cfg].append(v / took[CONFIGS[0]])
    out = {
        "measured_at": dt.datetime.now(dt.UTC).isoformat(), "reranker": rr.name, "rounds": args.rounds,
        "n_questions": len(cands), "n_samples_per_config": args.rounds * len(cands),
        "candidates_available_mean": round(statistics.fmean(len(t) for _, t in cands), 1),
        "configs": {f"k{k}-c{c}": {"p50_ms": round(statistics.median(ms[(k, c)]), 1),
                                   "p95_ms": round(sorted(ms[(k, c)])[int(0.95 * (len(ms[(k, c)]) - 1))], 1),
                                   "median_ratio_vs_k30_c900": round(statistics.median(rel[(k, c)]), 3)}
                    for k, c in CONFIGS},
    }
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
