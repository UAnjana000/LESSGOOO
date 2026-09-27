"""Agent-drafted visitor summaries of published items.

The answer model summarises the item's own published source passages in one call. The draft is a
Derivative(kind="summary") like any staff draft; an agent approval makes it visible but keeps an
"AI summary" label, so it never reads as archivist-reviewed. A summary is never quote-verified.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive import audit
from archive.ask.llm import AnswerLLM, LLMUnavailable
from archive.ingest import review
from archive.models import ArchivalItem, Derivative, Page, Passage, PublicationState
from archive.rights import external_processing_allowed

SOURCE_KINDS = ("source_text", "reviewed_transcription", "reviewed_transcript")
AI_SUMMARY_LABEL = "AI summary — not a quotation"
AI_DEBATE_SUMMARY_LABEL = "AI summary of the debate sitting — not a quotation"
AGENT_APPROVAL_REASON = "agent-drafted summary from the item's published text, not archivist review"
AGENT_CORRECTION_NOTE = "the agent corrected the model draft against the same published text"
PROMPT_VERSION = "summary-published-v1"
MAX_SOURCE_CHARS = 250_000
MAX_SUMMARY_CHARS = 1500

_KIND_HINT = {
    "debates": ("The text is the official report of one sitting of the Constituent Assembly. Summarise what "
                "happened at the sitting as a whole and name speakers only as the text names them. Describe it "
                "as a debate sitting, not as one person's speech."),
    "speeches": "The text is a speech. Summarise what the speaker argues, in the order the text gives it.",
    "writings": "The text is a written paper. Summarise its argument, in the order the text gives it.",
}


class SummaryError(RuntimeError):
    pass


def label_for(item: ArchivalItem) -> str:
    return AI_DEBATE_SUMMARY_LABEL if item.collection == "debates" else AI_SUMMARY_LABEL


def published_source_passages(db: Session, item: ArchivalItem) -> list[Passage]:
    """The published version's own text in reading order; reviewed translations are left out."""
    return list(db.execute(select(Passage).outerjoin(Page, Passage.page_id == Page.id).where(
        Passage.item_version_id == item.published_version_id, Passage.indexed.is_(True),
        Passage.kind.in_(SOURCE_KINDS)).order_by(Page.sequence.nulls_last(), Passage.char_start, Passage.id)).scalars())


def draft_from_published_text(db: Session, item: ArchivalItem, llm: AnswerLLM, actor: str) -> Derivative:
    """One model call. Returns a draft, which visitors do not see until approved."""
    if item.publication_state != PublicationState.published.value or not item.published_version_id:
        raise SummaryError(f"item {item.id} is not published")
    if not external_processing_allowed(item):
        raise SummaryError(f"item {item.id} does not permit external processing")
    if db.execute(select(Derivative.id).where(Derivative.item_id == item.id, Derivative.kind == "summary",
                                              Derivative.status.in_(("draft", "approved")))).first():
        raise SummaryError(f"item {item.id} already has a summary draft or approved summary")
    passages = published_source_passages(db, item)
    text = "\n\n".join(p.text for p in passages)
    if not text.strip():
        raise SummaryError(f"item {item.id} has no published source text")
    if len(text) > MAX_SOURCE_CHARS:
        raise SummaryError(f"item {item.id} text is {len(text)} characters; over {MAX_SOURCE_CHARS}")
    system = ("You summarise one archive item for museum visitors. Use only the text supplied. Do not add "
              "facts, names, dates, places or biographical details that the text does not state. Paraphrase; "
              "do not quote sentences from the text. Write 3-5 neutral sentences in English. "
              f"{_KIND_HINT.get(item.collection, '')} "
              'Return JSON {"summary": "..."}')
    user = f"Title: {item.title}\n\nText:\n{text}"
    try:
        res = llm.complete(system, user, 400)
        content = json.loads(res.content[res.content.find("{"):res.content.rfind("}") + 1])["summary"].strip()
    except (LLMUnavailable, ValueError, KeyError, AttributeError) as exc:
        raise SummaryError(f"summary draft failed for item {item.id}: {exc}") from exc
    if not content or len(content) > MAX_SUMMARY_CHARS:
        raise SummaryError(f"summary for item {item.id} is empty or longer than {MAX_SUMMARY_CHARS} characters")
    d = Derivative(kind="summary", item_id=item.id, source_ids=[p.id for p in passages], language="en",
                   content=content, generator=res.model, prompt_version=PROMPT_VERSION, status="draft",
                   label_shown=label_for(item))
    db.add(d)
    db.flush()
    audit.record(db, actor, "summary.draft", "derivative", d.id,
                 detail={"item_id": item.id, "passages": len(passages), "source_chars": len(text),
                         "tokens_in": res.tokens_in, "tokens_out": res.tokens_out})
    return d


def approve_as_agent(db: Session, d: Derivative, actor: str, corrected_text: str | None = None) -> Derivative:
    """Make an agent-drafted summary visible without claiming archivist review. `corrected_text` replaces
    model sentences the published text does not support; the decision keeps the draft as `before`."""
    if d.kind != "summary" or d.status != "draft":
        raise SummaryError(f"derivative {d.id} is not a summary draft")
    item = db.get(ArchivalItem, d.item_id)
    if corrected_text:
        return review.review_derivative(db, d, "correct", actor, text=corrected_text.strip(), role="agent",
                                        reason=f"{AGENT_APPROVAL_REASON}; {AGENT_CORRECTION_NOTE}",
                                        label=label_for(item))
    return review.review_derivative(db, d, "approve", actor, role="agent", reason=AGENT_APPROVAL_REASON,
                                    label=label_for(item))
