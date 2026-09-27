"""Repeatable Ask benchmark over the synthetic fixture corpus (docs/ARCHITECTURE_REVIEW.md).

Unlike the standalone eval/ scripts this one imports the backend. Run from the repo root with the backend venv:

    backend\\.venv\\Scripts\\python.exe eval/bench/bench_ask.py --label before --out eval/results/bench-ask-before.json
    # real local models (fastembed MiniLM embedder + Jina cross-encoder), downloaded into --model-cache:
    backend\\.venv\\Scripts\\python.exe eval/bench/bench_ask.py --models live --model-cache %TEMP%\\archive-bench-models ...
    # a few live answer-model calls (settings from .env; hard cap shared across runs, see LIVE_CAP):
    ... --live-llm 8

What it does
- Creates/migrates a separate database `archive_bench` (never the app or test DB), truncates it, and seeds the
  synthetic fixture texts (fixtures/ground_truth.json) plus 30 synthetic distractor passages, a withdrawn item and
  a restricted item (rights probes), and two items whose rights forbid external processing ("local-only").
- Runs eval/bench/ask_questions.json through the real `archive.ask.service.ask` (graph, cache, delivery
  rights check, answer log) --repeat times with a cold answer cache, then once more warm (cache hit rate).
- The answer model is a deterministic test double unless --live-llm is given. Its token counts are tiktoken
  o200k_base counts of the exact system+user text (+7 chat-format tokens); its latency is excluded (0 ms).
- Node timings come from wrapping the functions the graph calls (language ID, rewrite, embed, keyword,
  semantic, load_hits, rerank, answer model, validation, delivery rights check); "other" is the rest of ask()
  (cache lookup, graph overhead, answer log writes, trace sink).
- Retrieval Recall@k / MRR use the ordered passages the graph retrieved (answer_log.passages_retrieved).

Needs tiktoken on sys.path (e.g. `uv pip install --target %TEMP%\\bench-tk tiktoken` and PYTHONPATH).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LIVE_CAP = 20
LIVE_LEDGER = ROOT / "eval" / "results" / "live-llm-calls.json"
# gpt-4o-mini list prices (USD per 1M tokens) used only to estimate cost here; .env sets no prices.
PRICE_IN, PRICE_CACHED, PRICE_OUT = 0.15, 0.075, 0.60


def _setup_env(args) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bench-ask-"))
    for role in ("PRESERVATION", "DELIVERY", "DERIVATIVE", "QUARANTINE", "TRACE", "BACKUP"):
        os.environ[f"ARCHIVE_{role}_ROOT"] = str(tmp / role.lower())
    os.environ["ARCHIVE_DATABASE_URL"] = args.db_url
    os.environ["ARCHIVE_SARVAM_API_KEY"] = ""  # no live query translation in the benchmark
    os.environ["ARCHIVE_LANGFUSE_PUBLIC_KEY"] = ""
    os.environ["ARCHIVE_LANGFUSE_SECRET_KEY"] = ""
    os.environ["ARCHIVE_ENVIRONMENT"] = "test"
    if args.models == "doubles":
        os.environ["ARCHIVE_EMBEDDING_BACKEND"] = "hash"
        os.environ["ARCHIVE_RERANKER_BACKEND"] = "lexical"
        os.environ.setdefault("ARCHIVE_SUFFICIENCY_THRESHOLD", "0.3")  # same as the test suite
    else:
        os.environ["ARCHIVE_EMBEDDING_BACKEND"] = "fastembed"
        os.environ["ARCHIVE_RERANKER_BACKEND"] = "fastembed"
        os.environ["ARCHIVE_MODEL_CACHE"] = args.model_cache
    for kv in args.set or []:
        k, v = kv.split("=", 1)
        os.environ[k] = v
    sys.path.insert(0, str(ROOT / "backend"))


# ------------------------------------------------------------------ database + corpus

def _prepare_db(db_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    admin = db_url.rsplit("/", 1)[0] + "/postgres"
    name = db_url.rsplit("/", 1)[1]
    eng = create_engine(admin, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    with eng.connect() as c:
        if not c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": name}).scalar():
            c.execute(text(f'CREATE DATABASE "{name}"'))
    eng.dispose()
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    command.upgrade(cfg, "head")
    from archive.db import get_engine

    with get_engine().begin() as c:
        tables = c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN "
                                "('alembic_version') AND tablename NOT LIKE 'checkpoint%'")).scalars().all()
        c.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))


def _png(text: str) -> bytes:
    import io

    from PIL import Image, ImageDraw

    img = Image.new("L", (800, 1000), 250)
    ImageDraw.Draw(img).text((60, 80), text, fill=10)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _rights(db, key, external="allowed"):
    from archive.models import RightsRecord

    r = RightsRecord(source_key=key, title=f"rights {key}", source_institution="Synthetic benchmark source",
                     rights_holder="Synthetic", basis_for_use="benchmark", display_permission="allowed",
                     training_permission="allowed", external_processing=external, evidence="synthetic",
                     attribution="Synthetic", date_checked=dt.date(2026, 9, 27), checked_by="bench",
                     discovery_only=False, is_fixture=True, training_basis="synthetic")
    db.add(r)
    db.flush()
    return r


def _item(db, rights, key, texts, language="en", access="public", title=None):
    from archive import storage
    from archive.ingest import processing, publish, review
    from archive.models import ArchivalItem, FileVersion, Page

    item = ArchivalItem(title=title or key, item_type="printed_scan", collection="writings",
                        source_institution="Synthetic benchmark source", original_languages=[language],
                        scripts=["Latn"], rights_record_id=rights.id, access_level=access, created_by="bench",
                        is_fixture=True, capture_details={"item_key": key, "work_key": key})
    db.add(item)
    db.flush()
    for seq, text in enumerate(texts, 1):
        data = _png(f"{key} page {seq}")
        stored = storage.put_bytes(data, "preservation_master", ".png")
        fv = FileVersion(item_id=item.id, role="preservation_master", kind="original", format="image/png",
                         byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri)
        db.add(fv)
        db.flush()
        page = Page(item_id=item.id, sequence=seq, image_file_id=fv.id, doc_class="printed", language=language,
                    status="needs_full_review", ocr_route="local")
        db.add(page)
        db.flush()
        processing._store_delivery(db, page, data, fv.id)
        review.review_page(db, page, "approve", "bench-reviewer", "archivist", text=text)
    db.flush()
    db.refresh(item)
    publish.publish_item(db, item, "bench")
    return item


DISTRACTOR_TOPICS = [
    ("railway timetable", "The Samarpur railway timetable of {y} listed {n} trains a day to the district town, "
                          "and the evening train waited for the mill whistle before leaving."),
    ("grain prices", "In {y} the price of jowar in the Samarpur market rose to {n} annas a measure after the "
                     "late rains, and the grain dealers met to fix a common rate."),
    ("cricket club", "The Samarpur cricket club played {n} matches in {y} on the maidan behind the court house "
                     "and lost most of them to the teachers' eleven."),
    ("weather report", "The monsoon of {y} brought {n} inches of rain to Samarpur, and the river rose above the "
                       "old ghat steps twice in August."),
    ("post office", "The Samarpur post office opened a second counter in {y} and handled about {n} money orders "
                    "a month, mostly from workers sending wages home."),
    ("dispensary", "The municipal dispensary treated {n} patients in {y}; the report asks for a second compounder "
                   "and a cart to bring medicines from the district."),
]


def seed_corpus(db) -> dict[str, Any]:
    from archive.ingest import publish

    gt = json.loads((ROOT / "fixtures" / "ground_truth.json").read_text(encoding="utf-8"))["texts"]
    open_r, local_r = _rights(db, "bench-open"), _rights(db, "bench-local-only", external="not_allowed")
    _item(db, open_r, "fx-essay", gt["essay"], title="On Public Reading Rooms")
    _item(db, open_r, "fx-lecture-education", gt["lecture_clean"], title="Lecture on Education and Work")
    _item(db, open_r, "fx-lecture-tank", gt["lecture_degraded"], title="Lecture on Water and the Common Tank")
    _item(db, open_r, "fx-proceedings", gt["proceedings"], title="Proceedings of the Samarpur Civic Assembly")
    _item(db, open_r, "fx-pamphlet-hi", gt["hindi"], language="hi", title="Pamphlet on public reading rooms")
    _item(db, local_r, "fx-petition-mr", gt["marathi"], language="mr", title="Petition on the public tank")
    _item(db, open_r, "fx-manuscript-note", gt["manuscript"], title="Note on the library board")
    _item(db, local_r, "fx-online-only", gt["online_only"], access="public_online_only",
          title="Newspaper report on the library board")
    _item(db, open_r, "fx-restricted", gt["restricted"], access="restricted", title="Draft memorandum")
    wd = _item(db, open_r, "fx-withdrawn", ["Synthetic leaflet (withdrawn). The leaflet said the ferry toll on the "
                                            "Samarpur river was eight annas for a cart and one anna for a person."],
               title="Leaflet on the ferry toll")
    publish.withdraw(db, wd, "bench", "rights probe")
    for i in range(30):
        topic, tpl = DISTRACTOR_TOPICS[i % len(DISTRACTOR_TOPICS)]
        _item(db, open_r, f"dx-{i:02d}", [tpl.format(y=1920 + i % 9, n=3 + i * 7)], title=f"Samarpur {topic} {i}")
    db.commit()
    return {"items": 40, "local_only_items": ["fx-petition-mr", "fx-online-only"],
            "forbidden_items": ["fx-restricted", "fx-withdrawn"]}


def resolve_passages(db) -> tuple[dict[str, set[int]], dict[int, str], set[int]]:
    """item_key -> published passage ids (all versions for forbidden items), passage_id -> item_key,
    and the passage ids whose item forbids external processing."""
    from sqlalchemy import select

    from archive.models import ArchivalItem, Passage, RightsRecord

    rows = db.execute(select(Passage.id, Passage.text, ArchivalItem.capture_details, RightsRecord.external_processing)
                      .join(ArchivalItem, Passage.item_id == ArchivalItem.id)
                      .join(RightsRecord, ArchivalItem.rights_record_id == RightsRecord.id)).all()
    by_key: dict[str, set[int]] = {}
    key_of: dict[int, str] = {}
    local_only: set[int] = set()
    texts: dict[int, str] = {}
    for pid, text, cap, ext in rows:
        key = (cap or {}).get("item_key", "?")
        by_key.setdefault(key, set()).add(pid)
        key_of[pid] = key
        texts[pid] = text
        if ext != "allowed":
            local_only.add(pid)
    resolve_passages.texts = texts  # type: ignore[attr-defined]
    return by_key, key_of, local_only


# ------------------------------------------------------------------ instrumentation

class Timers:
    def __init__(self) -> None:
        self.cur: dict[str, float] = {}

    def wrap(self, fn, name):
        def timed(*a, **k):
            t0 = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                self.cur[name] = self.cur.get(name, 0.0) + (time.perf_counter() - t0) * 1000
        return timed

    def install(self) -> None:
        import archive.ask.graph as g
        import archive.ask.service as svc
        import archive.search.hybrid as hy
        from archive.search.models import get_embedder, get_reranker

        for mod, attr, name in [(g, "detect_language", "langid"), (g, "rewrite_query", "rewrite"),
                                (g, "validate", "validation"), (hy, "keyword_ids", "keyword"),
                                (hy, "semantic_ids", "semantic"), (hy, "load_hits", "load_hits"),
                                (svc, "_deliverable", "delivery_rights")]:
            if hasattr(mod, attr):
                setattr(mod, attr, self.wrap(getattr(mod, attr), name))
        emb, rr = get_embedder(), get_reranker()
        emb.embed_query = self.wrap(emb.embed_query, "embed")
        rr.score = self.wrap(rr.score, "rerank")


class TokenCounter:
    def __init__(self) -> None:
        import tiktoken

        self.enc = tiktoken.get_encoding("o200k_base")

    def __call__(self, text: str) -> int:
        return len(self.enc.encode(text))


class FakeLLM:
    """Deterministic answer-model double: one cited paraphrase of the first prompt passage, no quotes."""

    model = "bench-fake-llm"

    def __init__(self, count: TokenCounter, timers: Timers) -> None:
        self.count, self.timers = count, timers
        self.calls: list[dict[str, Any]] = []

    def complete(self, system: str, user: str, max_tokens: int):
        from archive.ask.llm import LLMResult

        t0 = time.perf_counter()
        ids = [int(x) for x in re.findall(r"^\[(\d+)\]", user, flags=re.M)]
        body = user.split("\n", 1)[-1]
        first = re.search(r"^\[\d+\][^\n]*\n(.+)$", body, flags=re.M)
        words = re.sub(r"\[[^\]]*\]", "", first.group(1) if first else "").replace('"', "").split()[:25]
        content = json.dumps({"sentences": [{"text": "The passage says that " + " ".join(words) + ".",
                                             "citations": ids[:1]}]}, ensure_ascii=False)
        tin, tout = self.count(system) + self.count(user) + 7, self.count(content)
        self.calls.append({"prompt_ids": ids, "tokens_in": tin, "tokens_out": tout, "system_len": len(system)})
        self.timers.cur["llm"] = self.timers.cur.get("llm", 0.0) + (time.perf_counter() - t0) * 1000
        return LLMResult(content=content, tokens_in=tin, tokens_out=tout, cached_tokens=0, model=self.model,
                         latency_ms=0)


class LiveLLM:
    """Real answer model from .env, behind a hard cap on total live calls across benchmark runs."""

    def __init__(self, budget: int, timers: Timers, label: str) -> None:
        from archive.ask.llm import get_llm

        self.inner = get_llm()
        if self.inner is None:
            raise SystemExit("--live-llm needs ARCHIVE_LLM_PROVIDER/API_KEY/MODEL in .env")
        self.model = self.inner.model
        self.budget, self.timers, self.label = budget, timers, label
        self.calls: list[dict[str, Any]] = []

    def complete(self, system: str, user: str, max_tokens: int):
        from archive.ask.llm import LLMUnavailable

        ledger = json.loads(LIVE_LEDGER.read_text()) if LIVE_LEDGER.exists() else {"calls": 0, "runs": []}
        if ledger["calls"] >= LIVE_CAP or len(self.calls) >= self.budget:
            raise LLMUnavailable("benchmark live-call cap reached")
        ledger["calls"] += 1
        ledger["runs"].append({"label": self.label, "at": dt.datetime.now(dt.UTC).isoformat()})
        LIVE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LIVE_LEDGER.write_text(json.dumps(ledger, indent=2))
        t0 = time.perf_counter()
        try:
            res = self.inner.complete(system, user, max_tokens)
        finally:
            self.timers.cur["llm"] = self.timers.cur.get("llm", 0.0) + (time.perf_counter() - t0) * 1000
        ids = [int(x) for x in re.findall(r"^\[(\d+)\]", user, flags=re.M)]
        self.calls.append({"prompt_ids": ids, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
                           "cached_tokens": res.cached_tokens, "latency_ms": res.latency_ms, "raw": res.content})
        return res


# ------------------------------------------------------------------ run

def pct(v: list[float], p: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return round(s[max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))], 2)


EXPECTED_OK = {"answer": {"answered", "extractive"}, "not_in_archive": {"insufficient"}, "refusal": {"refused"},
               "rejected": {"rejected_input"}}


def run_question(db, q, llm, timers, by_key, local_only, top_k) -> dict[str, Any]:
    from archive.ask.service import ask
    from archive.models import AnswerLog

    timers.cur = {}
    n_calls_before = len(llm.calls)
    t0 = time.perf_counter()
    res = ask(db, q["question"], q.get("history", []), q.get("ui_language", q["language"]), f"bench-{q['id']}",
              llm=llm)
    e2e = (time.perf_counter() - t0) * 1000
    calls = llm.calls[n_calls_before:]
    log = db.get(AnswerLog, res["answer_id"])
    retrieved = list(log.passages_retrieved or [])
    positives = set().union(*[{p for p in by_key.get(pos["item_key"], set())
                               if pos["anchor"] in resolve_passages.texts[p]} for pos in q["positives"]]) \
        if q["positives"] else set()
    forbidden = set().union(*[by_key.get(k, set()) for k in q.get("forbidden", [])]) if q.get("forbidden") else set()
    prompt_ids = sorted({i for c in calls for i in c["prompt_ids"]})
    cited = [c["passage_id"] for c in res["citations"]] if res["outcome"] == "answered" else []
    shown = [c["passage_id"] for c in res["citations"]]
    rank = next((i for i, p in enumerate(retrieved, 1) if p in positives), None)
    nodes = dict(timers.cur)
    nodes["other"] = max(0.0, e2e - sum(v for k, v in nodes.items() if k != "llm") - nodes.get("llm", 0.0))
    return {
        "id": q["id"], "category": q["category"], "expected": q["expected"], "outcome": res["outcome"],
        "ok": res["outcome"] in EXPECTED_OK[q["expected"]], "cache_hit": bool(res.get("cache_hit")),
        "e2e_ms": round(e2e, 2), "nodes_ms": {k: round(v, 3) for k, v in nodes.items()},
        "llm_calls": len(calls), "tokens_in": sum(c["tokens_in"] for c in calls),
        "tokens_out": sum(c["tokens_out"] for c in calls),
        "cached_tokens": sum(c.get("cached_tokens", 0) for c in calls),
        "prompt_passages": len(prompt_ids), "retrieved": retrieved, "positives": sorted(positives),
        "recall_at_k": (len(set(retrieved[:top_k]) & positives) / len(positives)) if positives else None,
        "rr": (1 / rank if rank else 0.0) if positives else None,
        "citations_resolve_to_prompt": all(c in prompt_ids for c in cited) if cited else None,
        "citation_hits_positive": (any(c in positives for c in cited) if cited else None) if positives else None,
        "forbidden_in_prompt": len(forbidden & set(prompt_ids)) + len(forbidden & set(shown)),
        "local_only_in_prompt": len(local_only & set(prompt_ids)),
        "paraphrase_only": res.get("paraphrase_only"), "retried": res.get("retried_retrieval"),
        "live_raw": [c.get("raw") for c in calls] if calls and "raw" in calls[0] else None,
    }


def summarise(rows: list[dict[str, Any]], warm: list[dict[str, Any]], cold_start_ms: float, meta) -> dict[str, Any]:
    llm_rows = [r for r in rows if r["llm_calls"]]
    node_names = sorted({k for r in rows for k in r["nodes_ms"]})
    ans = [r for r in rows if r["recall_at_k"] is not None]
    cited = [r for r in rows if r["citations_resolve_to_prompt"] is not None]
    cache_eligible = [r for r in warm if r["category"] in ("answerable", "local_only")]
    cost = sum(r["tokens_in"] - r["cached_tokens"] for r in rows) / 1e6 * PRICE_IN + \
        sum(r["cached_tokens"] for r in rows) / 1e6 * PRICE_CACHED + sum(r["tokens_out"] for r in rows) / 1e6 * PRICE_OUT
    return {
        **meta,
        "n_question_runs_cold": len(rows), "n_questions": len({r["id"] for r in rows}),
        "behaviour_accuracy": round(sum(r["ok"] for r in rows) / len(rows), 4),
        "behaviour_by_category": {c: f"{sum(r['ok'] for r in rows if r['category'] == c)}/"
                                     f"{sum(1 for r in rows if r['category'] == c)}"
                                  for c in sorted({r["category"] for r in rows})},
        "outcomes": {o: sum(1 for r in rows if r["outcome"] == o) for o in sorted({r["outcome"] for r in rows})},
        "llm_calls_per_question": round(sum(r["llm_calls"] for r in rows) / len(rows), 3),
        "questions_with_llm_call": len(llm_rows),
        "tokens_in_mean": round(statistics.fmean(r["tokens_in"] for r in llm_rows), 1) if llm_rows else None,
        "tokens_in_p95": pct([r["tokens_in"] for r in llm_rows], 95),
        "tokens_out_mean": round(statistics.fmean(r["tokens_out"] for r in llm_rows), 1) if llm_rows else None,
        "tokens_out_p95": pct([r["tokens_out"] for r in llm_rows], 95),
        "cached_tokens_share": round(sum(r["cached_tokens"] for r in rows) / max(1, sum(r["tokens_in"] for r in rows)), 4),
        "prompt_passages_mean": round(statistics.fmean(r["prompt_passages"] for r in llm_rows), 2) if llm_rows else None,
        "est_cost_usd_per_llm_question": round(cost / len(llm_rows), 6) if llm_rows else None,
        "cache_hit_rate_warm_pass_all": round(sum(r["cache_hit"] for r in warm) / len(warm), 4) if warm else None,
        "cache_hit_rate_warm_pass_answerable": round(sum(r["cache_hit"] for r in cache_eligible) / len(cache_eligible), 4)
        if cache_eligible else None,
        "cold_start_first_ask_ms": round(cold_start_ms, 1),
        "e2e_ms": {"p50": pct([r["e2e_ms"] for r in rows], 50), "p95": pct([r["e2e_ms"] for r in rows], 95)},
        "e2e_ms_excl_llm": {"p50": pct([r["e2e_ms"] - r["nodes_ms"].get("llm", 0) for r in rows], 50),
                            "p95": pct([r["e2e_ms"] - r["nodes_ms"].get("llm", 0) for r in rows], 95)},
        "warm_cache_hit_e2e_ms": {"p50": pct([r["e2e_ms"] for r in warm if r["cache_hit"]], 50),
                                  "p95": pct([r["e2e_ms"] for r in warm if r["cache_hit"]], 95)},
        "nodes_ms": {n: {"n": sum(1 for r in rows if n in r["nodes_ms"]),
                         "p50": pct([r["nodes_ms"][n] for r in rows if n in r["nodes_ms"]], 50),
                         "p95": pct([r["nodes_ms"][n] for r in rows if n in r["nodes_ms"]], 95)} for n in node_names},
        "retrieval": {"n": len(ans), "k": meta["top_k"],
                      "recall_at_k": round(statistics.fmean(r["recall_at_k"] for r in ans), 4) if ans else None,
                      "mrr": round(statistics.fmean(r["rr"] for r in ans), 4) if ans else None},
        "citation_validity": {"n_answered": len(cited),
                              "cited_ids_in_prompt": round(sum(r["citations_resolve_to_prompt"] for r in cited) / len(cited), 4) if cited else None,
                              "cites_a_positive": round(sum(bool(r["citation_hits_positive"]) for r in cited
                                                            if r["citation_hits_positive"] is not None) /
                                                        max(1, sum(1 for r in cited if r["citation_hits_positive"] is not None)), 4)},
        "rights": {"forbidden_passages_in_prompt_or_citations": sum(r["forbidden_in_prompt"] for r in rows),
                   "local_only_passages_sent_to_model": sum(r["local_only_in_prompt"] for r in rows)},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--models", choices=["doubles", "live"], default="doubles")
    ap.add_argument("--model-cache", default=str(Path(tempfile.gettempdir()) / "archive-bench-models"))
    ap.add_argument("--live-llm", type=int, default=0, help="max live answer-model calls in this run")
    ap.add_argument("--db-url", default="postgresql+psycopg://archive:archive-dev@127.0.0.1:55432/archive_bench")
    ap.add_argument("--set", action="append", help="extra ARCHIVE_*=value overrides")
    ap.add_argument("--questions", default=str(ROOT / "eval" / "bench" / "ask_questions.json"))
    args = ap.parse_args()
    _setup_env(args)

    from sqlalchemy import delete

    from archive.config import get_settings
    from archive.db import new_session
    from archive.models import AnswerCache
    from archive.search.models import get_embedder, get_reranker

    s = get_settings()
    _prepare_db(args.db_url)
    db = new_session()
    t_seed = time.perf_counter()
    corpus = seed_corpus(db)
    seed_s = time.perf_counter() - t_seed
    by_key, _key_of, local_only = resolve_passages(db)
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))["questions"]
    timers = Timers()
    timers.install()
    count = TokenCounter()
    llm = LiveLLM(args.live_llm, timers, args.label) if args.live_llm else FakeLLM(count, timers)

    # cold start: first ask in the process (model warm-up), not counted in the table
    t0 = time.perf_counter()
    from archive.ask.service import ask

    ask(db, "Warm up question about the reading room lamp", [], "en", "bench-warmup", llm=FakeLLM(count, timers))
    cold_ms = (time.perf_counter() - t0) * 1000
    db.execute(delete(AnswerCache))
    db.commit()

    rows: list[dict[str, Any]] = []
    for rep in range(args.repeat):
        db.execute(delete(AnswerCache))
        db.commit()
        for q in questions:
            if args.live_llm and rep > 0:
                break
            r = run_question(db, q, llm, timers, by_key, local_only, s.retrieval_top_k)
            r["repeat"] = rep
            rows.append(r)
    warm = [run_question(db, q, llm, timers, by_key, local_only, s.retrieval_top_k) for q in questions] \
        if not args.live_llm else []
    meta = {"label": args.label, "measured_at": dt.datetime.now(dt.UTC).isoformat(),
            "embedder": get_embedder().name, "embedder_is_test_double": get_embedder().is_test_double,
            "reranker": get_reranker().name, "reranker_is_test_double": get_reranker().is_test_double,
            "answer_model": llm.model, "top_k": s.retrieval_top_k, "candidate_k": s.retrieval_candidate_k,
            "rerank_candidate_k": getattr(s, "rerank_candidate_k", None),
            "rerank_max_chars": getattr(s, "rerank_max_chars", None),
            "passage_max_chars": s.passage_max_chars, "max_output_tokens": s.llm_max_output_tokens,
            "sufficiency_threshold": s.sufficiency_threshold, "prompt_version": s.prompt_version,
            "repeat": args.repeat if not args.live_llm else 1, "corpus": corpus, "seed_s": round(seed_s, 1),
            "token_counter": "provider usage" if args.live_llm else "tiktoken o200k_base (+7 chat overhead)"}
    summary = summarise(rows, warm, cold_ms, meta)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows, "warm_rows": warm}, indent=2,
                                         ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    db.close()


if __name__ == "__main__":
    main()
