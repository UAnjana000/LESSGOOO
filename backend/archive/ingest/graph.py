"""LangGraph ingestion state machine (spec 4, 4.9).

route/process pages -> open sampled batch -> [interrupt: human review, may last days]
-> resume with {"action": "publish"} -> stage -> verify -> switch

The metadata database is the source of truth for item/page/review state. The Postgres checkpointer
only stores the workflow position (thread id = ingest-item-<id>).
"""

from __future__ import annotations

import logging
import random
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from archive import tracing
from archive.config import get_settings
from archive.db import session_scope
from archive.ingest import processing, publish, review
from archive.ingest.sarvam_ocr import OcrFallback, SarvamDocAI
from archive.models import ArchivalItem, Page, PageStatus, PublicationState

log = logging.getLogger(__name__)


class IngestState(TypedDict, total=False):
    item_id: int
    actor: str
    page_outcomes: list[dict[str, Any]]
    batch_id: int | None
    review_problems: list[str]
    publish_actor: str
    result: dict[str, Any]
    error: str


def default_fallback() -> OcrFallback | None:
    s = get_settings()
    return SarvamDocAI() if (s.sarvam_available and s.sarvam_ocr_enabled) else None


def build_ingest_graph(fallback_factory=default_fallback, checkpointer=None, rng: random.Random | None = None):
    def process_pages(state: IngestState) -> IngestState:
        outcomes = []
        with session_scope() as db:
            item = db.get(ArchivalItem, state["item_id"])
            fallback = fallback_factory()
            for page in item.pages:
                if page.status == PageStatus.pending.value:
                    out = processing.process_page(db, page, fallback)
                elif page.status == PageStatus.sarvam_pending.value and fallback is not None:
                    out = processing.run_sarvam(db, page, fallback)
                else:
                    continue
                db.commit()
                outcomes.append(out.__dict__)
            if item.item_type in ("audio", "video"):
                processing.make_media_delivery(db, item)
            if item.publication_state == PublicationState.draft.value:
                item.publication_state = PublicationState.in_review.value
            review._update_item_state(db, item)
        return {"page_outcomes": outcomes}

    def open_review(state: IngestState) -> IngestState:
        with session_scope() as db:
            item = db.get(ArchivalItem, state["item_id"])
            batch = review.open_batch(db, item, rng)
            return {"batch_id": batch.id if batch else None}

    def await_review(state: IngestState) -> IngestState:
        decision = interrupt({"item_id": state["item_id"], "waiting_for": "archivist review and publish request"})
        if isinstance(decision, dict) and decision.get("action") == "reprocess":
            return {"review_problems": ["reprocess requested"], "publish_actor": ""}
        with session_scope() as db:
            item = db.get(ArchivalItem, state["item_id"])
            ok, problems = review.item_ready_for_publication(db, item)
        actor = (decision or {}).get("actor", "archivist") if isinstance(decision, dict) else "archivist"
        return {"review_problems": [] if ok else problems, "publish_actor": actor}

    def after_review(state: IngestState) -> str:
        if state.get("review_problems") == ["reprocess requested"]:
            return "process_pages"
        return "publish" if not state.get("review_problems") else "await_review"

    def do_publish(state: IngestState) -> IngestState:
        with session_scope() as db:
            item = db.get(ArchivalItem, state["item_id"])
            try:
                res = publish.publish_item(db, item, state.get("publish_actor") or "archivist")
            except publish.PublicationError as exc:
                return {"error": str(exc), "result": {"published": False}}
            return {"result": {"published": True, **{k: v for k, v in res.items() if k != "verification"}}}

    g = StateGraph(IngestState)
    g.add_node("process_pages", process_pages)
    g.add_node("open_review", open_review)
    g.add_node("await_review", await_review)
    g.add_node("publish", do_publish)
    g.add_edge(START, "process_pages")
    g.add_edge("process_pages", "open_review")
    g.add_edge("open_review", "await_review")
    g.add_conditional_edges("await_review", after_review, ["publish", "await_review", "process_pages"])
    g.add_edge("publish", END)
    return g.compile(checkpointer=checkpointer)


def thread_config(item_id: int) -> dict[str, Any]:
    return {"configurable": {"thread_id": f"ingest-item-{item_id}"}}


def run_ingest(graph, item_id: int, actor: str) -> dict[str, Any]:
    with tracing.trace("ingest.run", {"item_id": item_id}) as tr:
        state = graph.invoke({"item_id": item_id, "actor": actor}, thread_config(item_id))
        tr.update(output={"pages": len(state.get("page_outcomes", [])), "interrupted": "__interrupt__" in state})
    return state


def resume_publish(graph, item_id: int, actor: str) -> dict[str, Any]:
    with tracing.trace("ingest.publish", {"item_id": item_id}) as tr:
        state = graph.invoke(Command(resume={"action": "publish", "actor": actor}), thread_config(item_id))
        tr.update(output={"result": state.get("result"), "error": state.get("error")})
    return state


def resume_reprocess(graph, item_id: int, actor: str) -> dict[str, Any]:
    return graph.invoke(Command(resume={"action": "reprocess", "actor": actor}), thread_config(item_id))


def has_checkpoint(graph, item_id: int) -> bool:
    try:
        snap = graph.get_state(thread_config(item_id))
    except Exception:
        return False
    return bool(snap and snap.next)


def pending_page_count(item: ArchivalItem) -> int:
    return sum(1 for p in item.pages if p.status in (PageStatus.pending.value, PageStatus.sarvam_pending.value))


__all__ = ["build_ingest_graph", "run_ingest", "resume_publish", "resume_reprocess", "has_checkpoint", "Page"]
