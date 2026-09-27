"""Bounded LangGraph question workflow (spec 5.7). The graph is a DAG, so the bounds are structural:

check_input -> detect_language -> rewrite -> retrieve
   strong -> generate                weak -> retry_retrieve (the only retry node)
retry_retrieve: strong -> generate   weak -> abstain
generate -> validate: ok -> finalize | model found no support -> abstain | failed -> generate_paraphrase
generate_paraphrase -> validate_paraphrase: ok -> finalize | failed -> abstain
Any node failure (retrieval, answer model) routes to finalize with outcome "error"; nothing raises to the API.

No open-ended agent loop and no tool use beyond retrieval. Language ID, rewrite, retrieval,
reranking, sufficiency and validation make zero LLM calls. The graph is compiled once per process;
the DB session, answer model and query translator arrive per call as runtime context (AskDeps).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive.ask import policy
from archive.ask.llm import AnswerLLM, cost_usd
from archive.ask.validate import validate
from archive.config import get_settings
from archive.models import Passage
from archive.rights import external_processing_item_ids
from archive.search.hybrid import Hit, SearchFilters, hybrid_search, keyword_ids
from archive.search.langid import detect_language
from archive.search.models import get_reranker

log = logging.getLogger(__name__)

REWRITE_VERSION = "rule-rewrite-v1"
# Longest path is 11 nodes (check_input .. retry .. paraphrase .. abstain -> finalize); the DAG cannot exceed it.
RECURSION_LIMIT = 12
NO_SUPPORT = "model found no support in passages"
RARE_TERM_DF_FRACTION = 0.05
ANAPHORA = {
    "en": {"he", "him", "his", "she", "her", "it", "its", "they", "them", "their", "that", "this", "those",
           "these", "there", "then", "same"},
    "hi": {"वह", "वे", "उन्होंने", "उनका", "उनकी", "उनके", "उसने", "उसका", "यह", "इसका", "इसमें", "उसमें"},
    "mr": {"ते", "त्यांनी", "त्यांचा", "त्यांची", "त्यांचे", "तो", "ती", "हे", "याचा", "त्यात"},
}
STOP = {"what", "did", "does", "do", "say", "said", "about", "the", "a", "an", "of", "in", "on", "is", "was",
        "were", "how", "why", "when", "who", "which", "tell", "me", "and", "or", "to", "for", "dr", "dr.",
        "क्या", "के", "की", "का", "में", "बारे", "ने", "है", "था", "काय", "बद्दल", "च्या", "ला", "आहे", "होते"}
# \w alone splits Devanagari words at every vowel sign and virama; the dandas (U+0964-5) stay separators.
_TOK = re.compile(r"[\w\u0900-\u0963\u0966-\u097F]+", re.UNICODE)

SYSTEM_PROMPT = """You answer visitor questions for a heritage archive about Dr. B. R. Ambedkar.
Rules (always apply):
1. Use ONLY the numbered archive passages provided. If they do not answer the question, return {"sentences": []}.
2. Every sentence must list the passage numbers it relies on in "citations".
3. Never attribute words or views to Dr. Ambedkar unless the cited passage contains them.
4. Put text in double quotes ONLY when copying it verbatim from a passage marked quote_ok=true. Otherwise paraphrase without quotation marks.
5. If passages disagree or authorship is disputed, say so and cite both.
6. Do not speculate about present-day parties, politicians or events.
7. Be concise: at most 4 short sentences. Write in the requested language.
Return JSON only: {"sentences": [{"text": "...", "citations": [<passage number>, ...]}]}"""
PARAPHRASE_SUFFIX = "\nIMPORTANT: Your previous draft failed citation or quotation checks. Do not use any quotation marks. Paraphrase only."
LANG_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi"}


@dataclass
class AskDeps:
    db: Session
    llm: AnswerLLM | None = None
    translate_query: Callable[[str, str], str] | None = None


class AskState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]
    ui_language: str
    language: str
    query_language: str
    query: str
    rewritten: bool
    hits: list[dict[str, Any]]
    best_score: float
    retried: bool
    retrieval_info: dict[str, Any]
    prompt_ids: list[int]
    withheld_ids: list[int]
    attempt: int
    raw_answer: str
    validation: dict[str, Any]
    sentences: list[dict[str, Any]]
    paraphrase_only: bool
    outcome: str
    reason: str
    tokens_in: int
    tokens_out: int
    cached_tokens: int
    cost_usd: float
    provider_ms: int
    model: str
    trace_spans: list[dict[str, Any]]


def rewrite_query(question: str, history: list[dict[str, str]], language: str,
                  force: bool = False) -> tuple[str, bool]:
    """Rule-based standalone-query rewrite from the last 2-3 turns (no LLM). Without `force` it only fires
    for short or anaphoric follow-ups; the retry node forces it when the first retrieval was weak."""
    if not history:
        return question, False
    toks = [t.lower() for t in _TOK.findall(question)]
    has_anaphora = any(t in ANAPHORA.get(language, set()) | ANAPHORA["en"] for t in toks)
    if not force and not has_anaphora and len(toks) > 6:
        return question, False
    prev = history[-1].get("q", "")
    carry = [t for t in _TOK.findall(prev) if t.lower() not in STOP and len(t) > 2][:8]
    if not carry:
        return question, False
    return f"{' '.join(carry)} {question}", True


def keywordise(query: str) -> str:
    return " ".join(t for t in _TOK.findall(query) if t.lower() not in STOP and len(t) > 2) or query


def _hit_summary(h: Hit) -> dict[str, Any]:
    return {"passage_id": h.passage_id, "item_id": h.item_id, "text": h.text, "quote_verified": h.quote_verified,
            "citation": h.citation, "deep_link": h.deep_link, "kind_label": h.kind_label, "title": h.title,
            "rerank_score": h.rerank_score, "language": h.language, "is_fixture": h.extra.get("is_fixture")}


def build_prompt(question: str, language: str, hits: list[dict[str, Any]], max_chars: int) -> str:
    blocks = []
    for h in hits:
        blocks.append(f"[{h['passage_id']}] quote_ok={'true' if h['quote_verified'] else 'false'} "
                      f"source: {h['citation']}\n{h['text'][:max_chars]}")
    return (f"Answer language: {LANG_NAMES.get(language, 'English')}\n\nArchive passages:\n\n"
            + "\n\n".join(blocks) + f"\n\nQuestion: {question}")


def relaxed_keyword_query(db: Session, query: str) -> str | None:
    """OR of the question's rare content terms (in at most RARE_TERM_DF_FRACTION of passages), or of its two
    rarest terms if none is rare. websearch_to_tsquery ANDs every word, so a full natural-language question
    usually matches no passage at all."""
    terms = list(dict.fromkeys(t.lower() for t in _TOK.findall(keywordise(query)) if len(t) > 2))
    if len(terms) < 2:
        return None
    total = db.execute(select(func.count()).select_from(Passage)).scalar() or 0
    cap = max(1, int(total * RARE_TERM_DF_FRACTION))
    df = {t: len(keyword_ids(db, t, SearchFilters(), cap + 1)) for t in terms}
    present = sorted((t for t in terms if df[t]), key=lambda t: df[t])
    rare = [t for t in present if df[t] <= cap] or present[:2]
    return " or ".join(rare) if rare else None


def _fused_candidates(db: Session, query: str, limit: int) -> tuple[list[Hit], dict[str, Any]]:
    hits, info = hybrid_search(db, query, SearchFilters(), limit=limit, rerank=False)
    if info.get("keyword_candidates"):
        return hits, info
    if relaxed := relaxed_keyword_query(db, query):
        extra, _ = hybrid_search(db, relaxed, SearchFilters(), limit=limit, rerank=False)
        second = sorted((h for h in extra if h.keyword_rank), key=lambda h: h.keyword_rank)
        key = "keyword_relaxed_candidates"
    elif (core := keywordise(query)) != query:
        # No content word occurs in any passage (e.g. a Hindi question over English text), so only the embedding
        # leg can find evidence, and a whole-question embedding is dominated by its framing words.
        second, _ = hybrid_search(db, core, SearchFilters(), limit=limit, rerank=False)
        key = "content_probe_candidates"
    else:
        return hits, info
    # Mirror a working keyword leg: up to half the pool from the second probe, the rest from the first pass.
    pool = second[: max(1, limit // 2)]
    seen = {h.passage_id for h in pool}
    pool += [h for h in hits if h.passage_id not in seen][: limit - len(pool)]
    return pool, {**info, key: len(second), "fused": len(pool)}


def retrieve_passages(db: Session, query: str, rerank: bool = True) -> tuple[list[dict[str, Any]], float, dict]:
    """Hybrid (keyword + vector, RRF) retrieval; the cross-encoder scores only the top rerank_candidate_k
    fused candidates, reading at most rerank_max_chars of each."""
    s = get_settings()
    hits, info = _fused_candidates(db, query, s.rerank_candidate_k if rerank else s.retrieval_top_k)
    if rerank and hits:
        rr = get_reranker()
        for h, sc in zip(hits, rr.score(query, [h.text[: s.rerank_max_chars] for h in hits]), strict=True):
            h.rerank_score = sc
        hits.sort(key=lambda h: h.rerank_score or 0.0, reverse=True)
        info = {**info, "reranker": rr.name, "reranked": len(hits)}
    summ = [_hit_summary(h) for h in hits[: s.retrieval_top_k]]
    return summ, max((h["rerank_score"] or 0.0 for h in summ), default=0.0), info


def _span(state: AskState, name: str, **data: Any) -> list[dict[str, Any]]:
    return [*state.get("trace_spans", []), {"name": name, **data}]


def _timed(fn):
    def node(state: AskState, runtime: Runtime[AskDeps]) -> AskState:
        t0 = time.perf_counter()
        out = fn(state, runtime.context)
        if out.get("trace_spans"):
            out["trace_spans"][-1]["ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return out
    node.__name__ = fn.__name__
    return node


# ------------------------------------------------------------------ nodes (each does one thing)

def check_input(state: AskState, deps: AskDeps) -> AskState:
    res = policy.check_input(state["question"], get_settings().question_max_chars)
    if not res.allowed:
        return {"outcome": "rejected_input", "reason": res.reason,
                "trace_spans": _span(state, "check_input", result=res.reason)}
    if policy.is_opinion_bait(state["question"]):
        return {"outcome": "refused", "reason": "opinion_on_current_affairs",
                "trace_spans": _span(state, "check_input", result="opinion_bait")}
    return {"trace_spans": _span(state, "check_input", result="ok")}


def detect(state: AskState, deps: AskDeps) -> AskState:
    """`query_language` is what the question is written in; `language` is the answer language. A Hindi or
    Marathi UI is the visitor's choice and wins (Lingua cannot tell hi from mr by spelling alone); "en" is
    also the API default, so an English UI answers in the question's language."""
    ui = state.get("ui_language", "en")
    try:
        detected = detect_language(state["question"], fallback=ui)
    except Exception as exc:  # language ID failing must not block the question
        log.warning("language detection failed: %s", exc)
        detected = ui
    lang = detected if ui == "en" else ui
    return {"language": lang, "query_language": detected,
            "trace_spans": _span(state, "detect_language", language=lang, detected=detected, model="lingua")}


def rewrite(state: AskState, deps: AskDeps) -> AskState:
    history = (state.get("history") or [])[-get_settings().session_turns:]
    q, changed = rewrite_query(state["question"], history, state["query_language"])
    return {"query": q, "rewritten": changed,
            "trace_spans": _span(state, "rewrite", rewritten=changed, method=REWRITE_VERSION)}


def _retrieval_failed(state: AskState, name: str, exc: Exception) -> AskState:
    log.warning("retrieval failed in %s", name, exc_info=True)
    return {"outcome": "error", "reason": "retrieval unavailable",
            "trace_spans": _span(state, name, error=type(exc).__name__)}


def retrieve(state: AskState, deps: AskDeps) -> AskState:
    try:
        hits, best, info = retrieve_passages(deps.db, state["query"])
    except Exception as exc:
        return _retrieval_failed(state, "retrieve", exc)
    return {"hits": hits, "best_score": best, "retrieval_info": info,
            "trace_spans": _span(state, "retrieve", passage_ids=[h["passage_id"] for h in hits],
                                 scores=[h["rerank_score"] for h in hits], **info)}


def retry_retrieve(state: AskState, deps: AskDeps) -> AskState:
    """The one reformulated retrieval: add the previous turn's topic if the first query ignored it, drop
    stop-words (or translate a non-English query when a translator is configured), merge with the first hits."""
    history = (state.get("history") or [])[-get_settings().session_turns:]
    base, method = state["query"], "keywordise"
    if history and not state.get("rewritten"):
        base, forced = rewrite_query(state["question"], history, state["query_language"], force=True)
        method = "history+keywordise" if forced else method
    query = keywordise(base)
    if deps.translate_query is not None and state["query_language"] != "en":
        try:
            query, method = deps.translate_query(base, state["query_language"]), "query_translation"
        except Exception as exc:  # translation is optional; fall back to keywordising
            log.info("query translation unavailable: %s", exc)
    try:
        hits, best, _info = retrieve_passages(deps.db, query)
    except Exception as exc:
        return {**_retrieval_failed(state, "retry_retrieve", exc), "retried": True}
    top_k = get_settings().retrieval_top_k
    merged = {h["passage_id"]: h for h in [*state.get("hits", []), *hits]}
    ordered = sorted(merged.values(), key=lambda h: h["rerank_score"] or 0.0, reverse=True)[:top_k]
    best = max(best, state.get("best_score", 0.0))
    return {"hits": ordered, "best_score": best, "retried": True,
            "trace_spans": _span(state, "retry_retrieve", method=method,
                                 passage_ids=[h["passage_id"] for h in ordered], best=best)}


def _generate(state: AskState, deps: AskDeps, paraphrase: bool, name: str) -> AskState:
    s = get_settings()
    attempt = state.get("attempt", 0) + 1
    if deps.llm is None:
        return {"outcome": "extractive", "attempt": attempt,
                "trace_spans": _span(state, name, skipped="no answer model configured")}
    strong = [h for h in state["hits"] if (h["rerank_score"] or 0) >= s.sufficiency_threshold * 0.5] or state["hits"]
    withheld: list[int] = []
    if s.llm_external:
        sendable = external_processing_item_ids(deps.db, {h["item_id"] for h in strong})
        withheld = [h["passage_id"] for h in strong if h["item_id"] not in sendable]
        strong = [h for h in strong if h["item_id"] in sendable]
        if not strong:
            return {"outcome": "extractive", "reason": "local_only", "attempt": attempt,
                    "trace_spans": _span(state, name, skipped="rights forbid external processing",
                                         withheld_passage_ids=withheld)}
    system = SYSTEM_PROMPT + (PARAPHRASE_SUFFIX if paraphrase else "")
    user = build_prompt(state["query"] if state.get("rewritten") else state["question"], state["language"],
                        strong, s.passage_max_chars)
    prompt_ids = [h["passage_id"] for h in strong]
    # Spans are emitted after the graph returns, so the model call's wall-clock times travel with the span.
    start_ns = time.time_ns()
    try:
        res = deps.llm.complete(system, user, s.llm_max_output_tokens)
    except Exception as exc:  # LLMUnavailable or a malformed provider response: never raise to the API
        return {"outcome": "error", "reason": f"answer model unavailable: {type(exc).__name__}", "attempt": attempt,
                "prompt_ids": prompt_ids, "paraphrase_only": paraphrase,
                "trace_spans": _span(state, name, error=str(exc)[:200], start_ns=start_ns, end_ns=time.time_ns())}
    end_ns = time.time_ns()
    cost = cost_usd(res.tokens_in, res.tokens_out)
    return {
        "raw_answer": res.content, "attempt": attempt, "model": res.model, "prompt_ids": prompt_ids,
        "withheld_ids": withheld, "paraphrase_only": paraphrase,
        "tokens_in": state.get("tokens_in", 0) + res.tokens_in,
        "tokens_out": state.get("tokens_out", 0) + res.tokens_out,
        "cached_tokens": state.get("cached_tokens", 0) + res.cached_tokens,
        "cost_usd": round(state.get("cost_usd", 0.0) + cost, 6),
        "provider_ms": state.get("provider_ms", 0) + res.latency_ms,
        "trace_spans": _span(state, name, model=res.model, tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                             cached_tokens=res.cached_tokens, cost_usd=cost, latency_ms=res.latency_ms,
                             prompt_version=s.prompt_version, attempt=attempt, passage_ids=prompt_ids,
                             start_ns=start_ns, end_ns=end_ns),
    }


def generate(state: AskState, deps: AskDeps) -> AskState:
    return _generate(state, deps, paraphrase=False, name="generate")


def generate_paraphrase(state: AskState, deps: AskDeps) -> AskState:
    return _generate(state, deps, paraphrase=True, name="generate_paraphrase")


def _validate(state: AskState, name: str) -> AskState:
    """Citations may only name passages that were in this prompt (not merely retrieved)."""
    given = set(state.get("prompt_ids", []))
    res = validate(state["raw_answer"], {h["passage_id"]: h for h in state["hits"] if h["passage_id"] in given})
    out: AskState = {"validation": res.as_dict(), "trace_spans": _span(state, name, ok=res.ok, errors=res.errors[:5])}
    if res.ok:
        out["sentences"] = [{"text": x.text, "citations": x.citations} for x in res.sentences]
        out["outcome"] = "answered"
    elif not res.sentences and res.errors == ["no sentences"]:
        out["outcome"] = "insufficient"
        out["reason"] = NO_SUPPORT
    return out


def do_validate(state: AskState, deps: AskDeps) -> AskState:
    return _validate(state, "validate")


def validate_paraphrase(state: AskState, deps: AskDeps) -> AskState:
    return _validate(state, "validate_paraphrase")


def abstain(state: AskState, deps: AskDeps) -> AskState:
    if state.get("reason") == NO_SUPPORT and state.get("withheld_ids"):
        # The model saw no support, but relevant passages were kept from it by their rights terms: show them.
        return {"outcome": "extractive", "reason": "local_only",
                "trace_spans": _span(state, "abstain", withheld_passage_ids=state["withheld_ids"])}
    return {"outcome": "insufficient", "reason": state.get("reason") or "weak evidence or failed validation",
            "trace_spans": _span(state, "abstain")}


def refusal_browse(state: AskState, deps: AskDeps) -> AskState:
    """Related material for a refused question: fused hybrid order is enough to browse, so no rerank."""
    try:
        hits, _best, _info = retrieve_passages(deps.db, keywordise(state["question"]), rerank=False)
    except Exception as exc:
        log.warning("refusal browse retrieval failed: %s", exc)
        hits = []
    return {"hits": hits, "trace_spans": _span(state, "refusal_browse", passage_ids=[h["passage_id"] for h in hits])}


def finalize(state: AskState, deps: AskDeps) -> AskState:
    return {"trace_spans": _span(state, "finalize", outcome=state.get("outcome"))}


# ------------------------------------------------------------------ routing (conditional edges)

def route_after_input(state: AskState) -> str:
    return {"rejected_input": "finalize", "refused": "refusal_browse"}.get(state.get("outcome", ""), "detect_language")


def route_after_retrieve(state: AskState) -> str:
    if state.get("outcome") == "error":
        return "finalize"
    return "generate" if state["best_score"] >= get_settings().sufficiency_threshold else "retry_retrieve"


def route_after_retry(state: AskState) -> str:
    if state.get("outcome") == "error":
        return "finalize"
    return "generate" if state["best_score"] >= get_settings().sufficiency_threshold else "abstain"


def route_after_generate(state: AskState) -> str:
    return "finalize" if state.get("outcome") in ("extractive", "error") else "validate"


def route_after_paraphrase(state: AskState) -> str:
    return "finalize" if state.get("outcome") in ("extractive", "error") else "validate_paraphrase"


def route_after_validate(state: AskState) -> str:
    return {"answered": "finalize", "insufficient": "abstain"}.get(state.get("outcome", ""), "generate_paraphrase")


def route_after_validate_paraphrase(state: AskState) -> str:
    return "finalize" if state.get("outcome") == "answered" else "abstain"


@lru_cache
def build_ask_graph():
    g = StateGraph(AskState, context_schema=AskDeps)
    for fn in (check_input, detect, rewrite, retrieve, retry_retrieve, generate, do_validate, generate_paraphrase,
               validate_paraphrase, abstain, refusal_browse, finalize):
        name = {"detect": "detect_language", "do_validate": "validate"}.get(fn.__name__, fn.__name__)
        g.add_node(name, _timed(fn))
    g.add_edge(START, "check_input")
    g.add_conditional_edges("check_input", route_after_input, ["finalize", "refusal_browse", "detect_language"])
    g.add_edge("detect_language", "rewrite")
    g.add_edge("rewrite", "retrieve")
    g.add_conditional_edges("retrieve", route_after_retrieve, ["generate", "retry_retrieve", "finalize"])
    g.add_conditional_edges("retry_retrieve", route_after_retry, ["generate", "abstain", "finalize"])
    g.add_conditional_edges("generate", route_after_generate, ["finalize", "validate"])
    g.add_conditional_edges("validate", route_after_validate, ["finalize", "abstain", "generate_paraphrase"])
    g.add_conditional_edges("generate_paraphrase", route_after_paraphrase, ["finalize", "validate_paraphrase"])
    g.add_conditional_edges("validate_paraphrase", route_after_validate_paraphrase, ["finalize", "abstain"])
    g.add_edge("abstain", "finalize")
    g.add_edge("refusal_browse", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


def cache_key(question: str, language: str, index_version: int, prompt_version: str) -> str:
    norm = re.sub(r"\s+", " ", question.strip().lower())
    norm = re.sub(r"[?.!।]+$", "", norm)
    return hashlib.sha256(json.dumps([norm, language, index_version, prompt_version]).encode()).hexdigest()


def run_graph(graph, question: str, history: list[dict[str, str]], ui_language: str,
              deps: AskDeps) -> tuple[AskState, int]:
    t0 = time.perf_counter()
    state = graph.invoke({"question": question, "history": history, "ui_language": ui_language,
                          "trace_spans": []}, {"recursion_limit": RECURSION_LIMIT}, context=deps)
    return state, int((time.perf_counter() - t0) * 1000)
