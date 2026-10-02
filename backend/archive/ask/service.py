"""Ask endpoint orchestration: version-aware answer cache, the bounded graph, rights-checked
delivery, answer log + citations, redacted trace."""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive import tracing
from archive.ask import policy
from archive.ask.graph import ANAPHORA, AskDeps, build_ask_graph, cache_key, rewrite_query, run_graph
from archive.ask.llm import AnswerLLM, get_llm
from archive.config import get_settings
from archive.ingest.publish import current_index_version
from archive.models import AnswerCache, AnswerLog, Citation
from archive.rights import visible_passage_ids
from archive.services import sarvam_text


def _translate_query(text: str, lang: str) -> str:
    return sarvam_text.translate(text, lang, "en")[0]


def _deliverable(db: Session, passage_ids: list[int]) -> set[int]:
    """Re-check rights at delivery time (an item may have been withdrawn since retrieval/caching)."""
    return visible_passage_ids(db, passage_ids)


def _citation_payload(hit: dict[str, Any], quoted: list[str]) -> dict[str, Any]:
    return {"passage_id": hit["passage_id"], "item_id": hit["item_id"], "label": hit["citation"],
            "deep_link": hit["deep_link"], "kind_label": hit["kind_label"], "quote_verified": hit["quote_verified"],
            "title": hit["title"], "excerpt": hit["text"][:320], "is_fixture": hit.get("is_fixture"),
            "quoted_spans": quoted}


def _standalone(question: str, history: list[dict[str, str]]) -> bool:
    """True when the history rewrite leaves the question as it is (in any language the question may be detected
    as), so its answer is the same one a first question would get and the answer cache applies."""
    return not history or not any(rewrite_query(question, history, lang)[1] for lang in ANAPHORA)


def daily_cost(db: Session) -> float:
    today = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return float(db.execute(select(func.coalesce(func.sum(AnswerLog.cost_usd), 0.0))
                            .where(AnswerLog.created_at >= today)).scalar() or 0.0)


def ask(db: Session, question: str, history: list[dict[str, str]], ui_language: str, session_id: str,
        llm: AnswerLLM | None = None, use_default_llm: bool = True) -> dict[str, Any]:
    s = get_settings()
    llm = llm if llm is not None else (get_llm() if use_default_llm else None)
    history = [{"q": str(h.get("q", ""))[:300], "a": str(h.get("a", ""))[:300]} for h in history][-s.session_turns:]
    index_version = current_index_version(db)
    session_hash = hashlib.sha256(session_id.encode()).hexdigest()
    qref = tracing.question_ref(question)
    with tracing.trace("ask", {"session": session_hash[:16], "question": qref, "index_version": index_version,
                               "prompt_version": s.prompt_version}) as tr:
        key = cache_key(question, ui_language, index_version, s.prompt_version)
        cached = db.get(AnswerCache, key) if _standalone(question, history) else None
        if cached and cached.index_version == index_version and cached.prompt_version == s.prompt_version:
            payload = dict(cached.payload)
            ok_ids = _deliverable(db, [c["passage_id"] for c in payload.get("citations", [])])
            if all(c["passage_id"] in ok_ids for c in payload.get("citations", [])):
                cached.hits += 1
                log = AnswerLog(session_hash=session_hash, language=payload["language"], question_ref=qref,
                                passages_retrieved=[c["passage_id"] for c in payload.get("citations", [])],
                                outcome=payload["outcome"], model=payload.get("model"),
                                prompt_version=s.prompt_version, index_version=index_version, cache_hit=True,
                                trace_id=tr.id)
                db.add(log)
                db.commit()
                tr.span("cache", hit=True)
                tr.update(outcome=payload["outcome"], cache_hit=True)
                payload.update({"cache_hit": True, "answer_id": log.id, "trace_id": tr.id})
                return payload
        deps = AskDeps(db=db, llm=llm, translate_query=_translate_query if s.sarvam_available else None)
        state, latency = run_graph(build_ask_graph(), question, history, ui_language, deps)
        for sp in state.get("trace_spans", []):
            tr.span(sp.pop("name"), **sp)
        outcome = state.get("outcome") or "error"
        lang = state.get("language", ui_language)
        hits = state.get("hits", [])
        ok_ids = _deliverable(db, [h["passage_id"] for h in hits])
        hits = [h for h in hits if h["passage_id"] in ok_ids]
        by_id = {h["passage_id"]: h for h in hits if h["passage_id"] in state.get("prompt_ids", ())}
        sentences, citations = [], []
        if outcome == "answered":
            if not all(c in by_id for sent in state["sentences"] for c in sent["citations"]):
                outcome = "insufficient"
            else:
                quotes_by_pid: dict[int, list[str]] = {}
                from archive.ask.validate import extract_quotes
                for sent in state["sentences"]:
                    for q in extract_quotes(sent["text"]):
                        for c in sent["citations"]:
                            quotes_by_pid.setdefault(c, []).append(q)
                    sentences.append(sent)
                used = []
                for sent in sentences:
                    for c in sent["citations"]:
                        if c not in used:
                            used.append(c)
                citations = [_citation_payload(by_id[c], quotes_by_pid.get(c, [])) for c in used]
        if outcome in ("extractive", "insufficient", "refused", "error", "background"):
            # Closest items to browse; for "background" they are suggestions, never sources of its sentences.
            citations = [_citation_payload(h, []) for h in hits[:3]]
        if outcome == "background":
            sentences = [{"text": sent["text"], "citations": []} for sent in state.get("sentences", [])]
        msg_key = outcome if outcome in policy.MESSAGES else None
        if outcome == "extractive" and state.get("reason") == "local_only":
            msg_key = "local_only"
        if outcome == "rejected_input" and state.get("reason") == "too_long":
            msg_key = "too_long"
        message = policy.MESSAGES[msg_key].get(ui_language, policy.MESSAGES[msg_key]["en"]) if msg_key else None
        # What the validator actually checked for this answer; the visitor note claims no more than this.
        v = state.get("validation") or {}
        checks = ({"citations_ok": True, "quotes": len(v.get("quotes", [])),
                   "quotes_verified": sum(1 for q in v.get("quotes", []) if q.get("verified_in"))}
                  if outcome == "answered" and v.get("ok") else None)
        labels = {"answered": policy.ANSWER_LABEL, "background": policy.BACKGROUND_LABEL}.get(outcome)
        payload: dict[str, Any] = {
            "outcome": outcome,
            "language": lang,
            "label": labels.get(lang, labels["en"]) if labels else None,
            "message": message.format(max_chars=s.question_max_chars) if msg_key == "too_long" else message,
            "reason": state.get("reason") if outcome == "rejected_input" else None,
            "sentences": sentences,
            "citations": citations,
            "paraphrase_only": bool(state.get("paraphrase_only")),
            "retried_retrieval": bool(state.get("retried")),
            "rewritten_query": state.get("query") if state.get("rewritten") else None,
            "model": state.get("model"),
            "checks": checks,
            "claim_support_note": "Citations were checked to exist and quotes to match verbatim; whether each "
                                  "paraphrased sentence is fully supported is measured by human grading, not guaranteed.",
        }
        log = AnswerLog(session_hash=session_hash, language=lang, question_ref=qref,
                        passages_retrieved=[h["passage_id"] for h in hits], outcome=outcome,
                        model=state.get("model"), prompt_version=s.prompt_version, index_version=index_version,
                        tokens_in=state.get("tokens_in", 0), tokens_out=state.get("tokens_out", 0),
                        cost_usd=state.get("cost_usd", 0.0), latency_ms=latency,
                        provider_latency_ms=state.get("provider_ms", 0), retried_retrieval=bool(state.get("retried")),
                        validation=state.get("validation", {}), trace_id=tr.id)
        db.add(log)
        db.flush()
        for c in citations if outcome == "answered" else []:
            db.add(Citation(answer_id=log.id, passage_id=c["passage_id"],
                            quoted_span=" | ".join(c["quoted_spans"]) or None, span_verified=bool(c["quoted_spans"]),
                            display_label=c["label"], deep_link=c["deep_link"]))
        # A follow-up is cached only when neither pass used the history, i.e. it was answered as a first question.
        if outcome == "answered" and (not history or not (state.get("rewritten") or state.get("retried"))):
            db.merge(AnswerCache(key=key, index_version=index_version, prompt_version=s.prompt_version,
                                 payload=payload))
        db.commit()
        tr.update(outcome=outcome, tokens_in=log.tokens_in, tokens_out=log.tokens_out, cost_usd=log.cost_usd,
                  latency_ms=latency, cache_hit=False, passage_ids=[h["passage_id"] for h in hits])
        if log.cost_usd and (spent := daily_cost(db)) > s.daily_cost_alert_usd:
            import logging
            logging.getLogger(__name__).warning("daily answer cost alert", extra={"cost_usd": spent})
        payload.update({"cache_hit": False, "answer_id": log.id, "trace_id": tr.id, "latency_ms": latency,
                        "tokens_in": log.tokens_in, "tokens_out": log.tokens_out, "cost_usd": log.cost_usd,
                        "trace_backend": tracing.backend_name()})
        return payload
