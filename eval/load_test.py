"""Simulated kiosk sessions for the edge-server capacity benchmark (spec 3.4, 10.2 Edge-server capacity).

Each simulated kiosk loops: search -> open a result's item page -> (optional) Ask. Run it once with
visitor load alone and once while an ingestion batch runs, with the SAME arguments, and compare against
the targets written in eval/templates/latency_targets.json BEFORE the run.

    python eval/load_test.py --base-url https://localhost:8443 --insecure --sessions 4 --minutes 10 \
        --scenario visitor_only --queries eval/questions/load_queries.txt --out eval/results/load-visitor.json

--ask is off by default: Ask writes answer-log rows and may spend LLM budget. CPU, RAM, swap and disk I/O
are recorded separately from the host (for example `docker stats` or `vmstat 5`), not by this script.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import ssl
import threading
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from evalkit import percentile, write_json


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.samples: dict[str, list[float]] = {}
        self.errors: dict[str, int] = {}
        self.server_ms: dict[str, list[float]] = {}

    def add(self, name: str, ms: float, ok: bool, server_ms: float | None = None) -> None:
        with self.lock:
            if ok:
                self.samples.setdefault(name, []).append(ms)
                if server_ms is not None:
                    self.server_ms.setdefault(name, []).append(server_ms)
            else:
                self.errors[name] = self.errors.get(name, 0) + 1

    def summary(self) -> dict[str, Any]:
        out = {}
        for name in sorted(set(self.samples) | set(self.errors)):
            v = self.samples.get(name, [])
            out[name] = {"n": len(v), "errors": self.errors.get(name, 0),
                         "p50_ms": percentile(v, 50), "p95_ms": percentile(v, 95)}
            if name in self.server_ms:
                s = self.server_ms[name]
                out[name].update({"server_p50_ms": percentile(s, 50), "server_p95_ms": percentile(s, 95)})
        return out


def _call(ctx, method: str, url: str, body: dict[str, Any] | None = None) -> tuple[float, dict[str, Any] | None]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        payload = json.loads(resp.read() or b"null")
    return (time.perf_counter() - t0) * 1000, payload


def session(base: str, ctx, queries: list[str], deadline: float, ask: bool, rec: Recorder, seed: int) -> None:
    rng = random.Random(seed)
    sid = f"loadtest-{uuid.uuid4().hex[:12]}"
    while time.time() < deadline:
        q = rng.choice(queries)
        try:
            ms, res = _call(ctx, "GET", f"{base}/api/visitor/search?q={urllib.parse.quote(q)}")
            rec.add("search", ms, True)
        except Exception:
            rec.add("search", 0, False)
            continue
        hits = (res or {}).get("results", [])
        if hits:
            try:
                ms, _ = _call(ctx, "GET", f"{base}/api/visitor/items/{hits[0]['item_id']}")
                rec.add("page_open", ms, True)
            except Exception:
                rec.add("page_open", 0, False)
        if ask:
            try:
                ms, res = _call(ctx, "POST", f"{base}/api/visitor/ask",
                                {"question": q, "history": [], "language": "en", "session_id": sid})
                rec.add("ask", ms, True, (res or {}).get("latency_ms"))
            except Exception:
                rec.add("ask", 0, False)
        time.sleep(rng.uniform(1.0, 4.0))  # visitor think time


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--sessions", type=int, required=True, help="number of simulated kiosks")
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--scenario", required=True, choices=["visitor_only", "with_ingestion",
                                                          "langfuse_on_box", "langfuse_off_box"])
    ap.add_argument("--queries", required=True, help="text file, one visitor query per line")
    ap.add_argument("--ask", action="store_true")
    ap.add_argument("--insecure", action="store_true", help="accept the demo's self-signed certificate")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    queries = [line.strip() for line in open(args.queries, encoding="utf-8") if line.strip()]
    ctx = ssl._create_unverified_context() if args.insecure else None
    rec = Recorder()
    started = dt.datetime.now(dt.UTC)
    deadline = time.time() + args.minutes * 60
    with ThreadPoolExecutor(max_workers=args.sessions) as pool:
        for i in range(args.sessions):
            pool.submit(session, args.base_url.rstrip("/"), ctx, queries, deadline, args.ask, rec, i)
    result = {"scenario": args.scenario, "kiosks_simulated": args.sessions, "minutes": args.minutes,
              "ask_included": args.ask, "started_at": started.isoformat(),
              "finished_at": dt.datetime.now(dt.UTC).isoformat(), "base_url": args.base_url,
              "endpoints": rec.summary(),
              "note": "Client-side latency. Provider (LLM) time comes from answer_log/Langfuse, not from here."}
    print(write_json(args.out, result))
    print(json.dumps(result["endpoints"], indent=2))


if __name__ == "__main__":
    main()
