"""Bounded LangGraph question workflow (spec 5.7).

check_input -> detect_language -> rewrite -> retrieve -> sufficiency
   weak (first time) -> retry_retrieve (exactly once) -> sufficiency
   still weak -> abstain
   strong -> generate -> validate -> (one regeneration as labelled paraphrase) -> finalize | abstain

No open-ended agent loop and no tool use beyond retrieval. Language ID, rewrite, retrieval,
reranking, sufficiency and validation make zero LLM calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from archive.ask import policy
from archive.ask.llm import AnswerLLM, LLMUnavailable, cost_usd
from archive.ask.validate import validate
from archive.config import get_settings
from archive.search.hybrid import Hit, SearchFilters, hybrid_search
from archive.search.langid import detect_language

log = logging.getLogger(__name__)

REWRITE_VERSION = "rule-rewrite-v1"
ANAPHORA = {
    "en": {"he", "him", "his", "she", "her", "it", "its", "they", "them", "their", "that", "this", "those",
           "these", "there", "then", "same"},
    "hi": {"वह", "वे", "उन्होंने", "उनका", "उनकी", "उनके", "उसने", "उसका", "यह", "इसका", "इसमें", "उसमें"},
    "mr": {"ते", "त्यांनी", "त्यांचा", "त्यांची", "त्यांचे", "तो", "ती", "हे", "याचा", "त्यात"},
}
STOP = {"what", "did", "does", "do", "say", "said", "about", "the", "a", "an", "of", "in", "on", "is", "was",
        "were", "how", "why", "when", "who", "which", "tell", "me", "and", "or", "to", "for", "dr", "dr.",
        "क्या", "के", "की", "का", "में", "बारे", "ने", "है", "था", "काय", "बद्दल", "च्या", "ला", "आहे", "होते"}
_TOK = re.compile(r"\w+", re.UNICODE)

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


class AskState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]
    ui_language: str
    language: str
    query: str
    rewritten: bool
    hits: list[dict[str, Any]]
    best_score: float
    retried: bool
    retrieval_info: dict[str, Any]
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


def rewrite_query(question: str, history: list[dict[str, str]], language: str) -> tuple[str, bool]:
    """Rule-based standalone-query rewrite from the last 2-3 turns (no LLM)."""
    if not history:
        return question, False
    toks = [t.lower() for t in _TOK.findall(question)]
    has_anaphora = any(t in ANAPHORA.get(language, set()) | ANAPHORA["en"] for t in toks)
    if not has_anaphora and len(toks) > 6:
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


def build_ask_graph(db: Session, llm: AnswerLLM | None, translate_query=None):
    s = get_settings()

    def span(state: AskState, name: str, **data: Any) -> list[dict[str, Any]]:
        return [*state.get("trace_spans", []), {"name": name, **data}]

    def check_input(state: AskState) -> AskState:
        res = policy.check_input(state["question"], s.question_max_chars)
        if not res.allowed:
            return {"outcome": "rejected_input", "reason": res.reason,
                    "trace_spans": span(state, "check_input", result=res.reason)}
        if policy.is_opinion_bait(state["question"]):
            return {"outcome": "refused", "reason": "opinion_on_current_affairs",
                    "trace_spans": span(state, "check_input", result="opinion_bait")}
        return {"trace_spans": span(state, "check_input", result="ok")}

    def route_after_input(state: AskState) -> str:
        if state.get("outcome") == "rejected_input":
            return "finalize"
        if state.get("outcome") == "refused":
            return "refusal_browse"
        return "detect_language"

    def detect(state: AskState) -> AskState:
        lang = detect_language(state["question"], fallback=state.get("ui_language", "en"))
        return {"language": lang, "trace_spans": span(state, "detect_language", language=lang, model="lingua")}

    def rewrite(state: AskState) -> AskState:
        history = (state.get("history") or [])[-s.session_turns:]
        q, changed = rewrite_query(state["question"], history, state["language"])
        return {"query": q, "rewritten": changed,
                "trace_spans": span(state, "rewrite", rewritten=changed, method=REWRITE_VERSION)}

    def _retrieve(query: str) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
        hits, info = hybrid_search(db, query, SearchFilters(), limit=s.retrieval_top_k, rerank=True)
        summ = [_hit_summary(h) for h in hits]
        best = max((h["rerank_score"] or 0.0 for h in summ), default=0.0)
        return summ, best, info

    def retrieve(state: AskState) -> AskState:
        hits, best, info = _retrieve(state["query"])
        return {"hits": hits, "best_score": best, "retrieval_info": info,
                "trace_spans": span(state, "retrieve", passage_ids=[h["passage_id"] for h in hits],
                                    scores=[h["rerank_score"] for h in hits], **info)}

    def sufficient(state: AskState) -> str:
        if state["best_score"] >= s.sufficiency_threshold:
            return "generate"
        return "abstain" if state.get("retried") else "retry_retrieve"

    def retry_retrieve(state: AskState) -> AskState:
        query = keywordise(state["query"])
        method = "keywordise"
        if translate_query is not None and state["language"] != "en":
            try:
                query, method = translate_query(state["query"], state["language"]), "query_translation"
            except Exception as exc:  # translation is optional; fall back to keywordising
                log.info("query translation unavailable: %s", exc)
        hits, best, info = _retrieve(query)
        merged = {h["passage_id"]: h for h in [*state["hits"], *hits]}
        ordered = sorted(merged.values(), key=lambda h: h["rerank_score"] or 0.0, reverse=True)[: s.retrieval_top_k]
        best = max(best, state["best_score"])
        return {"hits": ordered, "best_score": best, "retried": True,
                "trace_spans": span(state, "retry_retrieve", method=method,
                                    passage_ids=[h["passage_id"] for h in ordered], best=best)}

    def generate(state: AskState) -> AskState:
        attempt = state.get("attempt", 0) + 1
        if llm is None:
            return {"outcome": "extractive", "attempt": attempt,
                    "trace_spans": span(state, "generate", skipped="no answer model configured")}
        strong = [h for h in state["hits"] if (h["rerank_score"] or 0) >= s.sufficiency_threshold * 0.5] or state["hits"]
        system = SYSTEM_PROMPT + (PARAPHRASE_SUFFIX if state.get("paraphrase_only") else "")
        user = build_prompt(state["question"] if not state.get("rewritten") else state["query"], state["language"],
                            strong, s.passage_max_chars)
        try:
            res = llm.complete(system, user, s.llm_max_output_tokens)
        except LLMUnavailable as exc:
            return {"outcome": "error", "reason": f"answer model unavailable: {exc}", "attempt": attempt,
                    "trace_spans": span(state, "generate", error=str(exc)[:200])}
        cost = cost_usd(res.tokens_in, res.tokens_out)
        return {
            "raw_answer": res.content, "attempt": attempt, "model": res.model,
            "tokens_in": state.get("tokens_in", 0) + res.tokens_in,
            "tokens_out": state.get("tokens_out", 0) + res.tokens_out,
            "cached_tokens": state.get("cached_tokens", 0) + res.cached_tokens,
            "cost_usd": round(state.get("cost_usd", 0.0) + cost, 6),
            "provider_ms": state.get("provider_ms", 0) + res.latency_ms,
            "trace_spans": span(state, "generate", model=res.model, tokens_in=res.tokens_in,
                                tokens_out=res.tokens_out, cached_tokens=res.cached_tokens, cost_usd=cost,
                                latency_ms=res.latency_ms, prompt_version=s.prompt_version, attempt=attempt),
        }

    def route_after_generate(state: AskState) -> str:
        return "finalize" if state.get("outcome") in ("extractive", "error") else "validate"

    def do_validate(state: AskState) -> AskState:
        retrieved = {h["passage_id"]: h for h in state["hits"]}
        res = validate(state["raw_answer"], retrieved)
        empty = not res.sentences and res.errors == ["no sentences"]
        out: AskState = {"validation": res.as_dict(),
                         "trace_spans": span(state, "validate", ok=res.ok, errors=res.errors[:5])}
        if res.ok:
            out["sentences"] = [{"text": x.text, "citations": x.citations} for x in res.sentences]
            out["outcome"] = "answered"
        elif empty:
            out["outcome"] = "insufficient"
            out["reason"] = "model found no support in passages"
        return out

    def route_after_validate(state: AskState) -> str:
        if state.get("outcome") in ("answered", "insufficient"):
            return "finalize" if state["outcome"] == "answered" else "abstain"
        return "regenerate" if state.get("attempt", 1) < 2 else "abstain"

    def regenerate(state: AskState) -> AskState:
        return {"paraphrase_only": True, "trace_spans": span(state, "regenerate", reason="validation failed")}

    def abstain(state: AskState) -> AskState:
        return {"outcome": "insufficient", "reason": state.get("reason") or "weak evidence or failed validation",
                "trace_spans": span(state, "abstain")}

    def refusal_browse(state: AskState) -> AskState:
        hits, _best, _info = _retrieve(keywordise(state["question"]))
        return {"hits": hits, "trace_spans": span(state, "refusal_browse", passage_ids=[h["passage_id"] for h in hits])}

    def finalize(state: AskState) -> AskState:
        return {"trace_spans": span(state, "finalize", outcome=state.get("outcome"))}

    g = StateGraph(AskState)
    for name, fn in [("check_input", check_input), ("detect_language", detect), ("rewrite", rewrite),
                     ("retrieve", retrieve), ("retry_retrieve", retry_retrieve), ("generate", generate),
                     ("validate", do_validate), ("regenerate", regenerate), ("abstain", abstain),
                     ("refusal_browse", refusal_browse), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "check_input")
    g.add_conditional_edges("check_input", route_after_input, ["finalize", "refusal_browse", "detect_language"])
    g.add_edge("detect_language", "rewrite")
    g.add_edge("rewrite", "retrieve")
    g.add_conditional_edges("retrieve", sufficient, ["generate", "retry_retrieve", "abstain"])
    g.add_conditional_edges("retry_retrieve", sufficient, ["generate", "abstain"])
    g.add_conditional_edges("generate", route_after_generate, ["finalize", "validate"])
    g.add_conditional_edges("validate", route_after_validate, ["finalize", "regenerate", "abstain"])
    g.add_edge("regenerate", "generate")
    g.add_edge("abstain", "finalize")
    g.add_edge("refusal_browse", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


def cache_key(question: str, language: str, index_version: int, prompt_version: str) -> str:
    norm = re.sub(r"\s+", " ", question.strip().lower())
    norm = re.sub(r"[?.!।]+$", "", norm)
    return hashlib.sha256(json.dumps([norm, language, index_version, prompt_version]).encode()).hexdigest()


def run_graph(graph, question: str, history: list[dict[str, str]], ui_language: str) -> tuple[AskState, int]:
    t0 = time.perf_counter()
    state = graph.invoke({"question": question, "history": history, "ui_language": ui_language,
                          "trace_spans": []}, {"recursion_limit": 25})
    return state, int((time.perf_counter() - t0) * 1000)
