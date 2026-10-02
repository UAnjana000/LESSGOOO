"""Human review (spec 4.5): full review, sampled batch review, quote verification.

Every decision creates a ReviewDecision with reviewer, action, before/after text and reason.
Only approved text is ever staged for publication or indexed.
"""

from __future__ import annotations

import math
import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive import audit
from archive.models import (
    ArchivalItem,
    Derivative,
    MediaSegment,
    OcrResult,
    Page,
    PageStatus,
    Passage,
    PhotoMetadata,
    PublicationState,
    ReviewBatch,
    ReviewDecision,
    Translation,
    utcnow,
)

SAMPLE_FRACTION = 0.2


class ReviewError(ValueError):
    pass


REVIEW_ACTIONS = frozenset({"approve", "correct", "reject"})
AI_REVIEWED_SUMMARY_LABEL = "AI-drafted summary, reviewed by archive staff"


def _decision(db: Session, target_type: str, target_id: int, action: str, reviewer: str, role: str,
              before: str | None = None, after: str | None = None, reason: str | None = None,
              seeded: bool = False) -> ReviewDecision:
    rd = ReviewDecision(target_type=target_type, target_id=target_id, action=action, before=before, after=after,
                        reason=reason, reviewer=reviewer, role=role, is_seeded_fixture=seeded)
    db.add(rd)
    db.flush()
    audit.record(db, reviewer, f"review.{action}", target_type, target_id,
                 detail={"decision_id": rd.id, "reason": reason, "seeded_fixture": seeded})
    return rd


def candidate_text(page: Page) -> str:
    selected = [r for r in page.ocr_results if r.selected and r.status == "ok"]
    if selected:
        return selected[-1].text
    ok = [r for r in page.ocr_results if r.status == "ok"]
    return ok[-1].text if ok else ""


def review_page(db: Session, page: Page, action: str, reviewer: str, role: str, *, text: str | None = None,
                reason: str | None = None, source_result_id: int | None = None, seeded: bool = False) -> Page:
    """Full review of one page. action: approve | correct | reject | escalate."""
    if action not in {"approve", "correct", "reject", "escalate"}:
        raise ReviewError("unknown action")
    if page.status == PageStatus.approved.value and action in {"approve", "correct"}:
        raise ReviewError("page already approved; corrections create a new text version via 'reopen'")
    base = candidate_text(page)
    if source_result_id is not None:
        chosen = db.get(OcrResult, source_result_id)
        if chosen is None or chosen.page_id != page.id or chosen.status != "ok":
            raise ReviewError("source OCR result not found for this page")
        base = chosen.text
    if action == "approve":
        if page.doc_class == "handwritten" and not text and not base:
            raise ReviewError("handwritten pages need a transcription")
        final = text if text is not None else base
        if not final.strip():
            raise ReviewError("cannot approve empty text")
        _approve_text(db, page, final, reviewer, "approve", role, before=base, reason=reason, seeded=seeded,
                      basis="full_review")
    elif action == "correct":
        if not text or not text.strip():
            raise ReviewError("correction needs the corrected text")
        _approve_text(db, page, text, reviewer, "correct", role, before=base, reason=reason, seeded=seeded,
                      basis="full_review")
    elif action == "reject":
        page.status = PageStatus.rejected.value
        _decision(db, "page", page.id, "reject", reviewer, role, before=base, reason=reason, seeded=seeded)
    else:
        page.status = PageStatus.needs_full_review.value
        page.review_mode = "full"
        _decision(db, "page", page.id, "escalate", reviewer, role, before=base, reason=reason, seeded=seeded)
    _update_item_state(db, page.item)
    return page


def _approve_text(db: Session, page: Page, final: str, reviewer: str, action: str, role: str, *, before: str,
                  reason: str | None, seeded: bool, basis: str) -> None:
    page.approved_text = final
    page.approved_text_version += 1
    page.approved_by = reviewer
    page.approved_at = utcnow()
    page.status = PageStatus.approved.value
    page.quality_signals = {**page.quality_signals, "review_basis": basis}
    _decision(db, "page", page.id, action, reviewer, role, before=before, after=final, reason=reason,
              seeded=seeded)


def reopen_page(db: Session, page: Page, reviewer: str, reason: str, role: str = "archivist") -> Page:
    """Start a correction of an approved page; the published passage stays until a new version is published."""
    page.status = PageStatus.needs_full_review.value
    page.review_mode = "full"
    page.quote_verified = False
    _decision(db, "page", page.id, "escalate", reviewer, role, before=page.approved_text, reason=reason)
    _update_item_state(db, page.item)
    return page


def open_batch(db: Session, item: ArchivalItem, rng: random.Random | None = None) -> ReviewBatch | None:
    pages = [p for p in item.pages if p.status == PageStatus.in_batch_review.value and p.batch_id is None]
    if not pages:
        return None
    rng = rng or random.Random()
    k = max(1, math.ceil(len(pages) * SAMPLE_FRACTION))
    sample = rng.sample(pages, k)
    batch = ReviewBatch(item_id=item.id, page_ids=[p.id for p in pages], sample_page_ids=[p.id for p in sample])
    db.add(batch)
    db.flush()
    for p in pages:
        p.batch_id = batch.id
    audit.record(db, "ingestion-graph", "batch.open", "review_batch", batch.id,
                 detail={"pages": batch.page_ids, "sample": batch.sample_page_ids})
    return batch


def decide_batch(db: Session, batch: ReviewBatch, passed: bool, reviewer: str, reason: str | None = None,
                 sample_checks: dict[int, dict[str, Any]] | None = None, seeded: bool = False,
                 role: str = "archivist") -> ReviewBatch:
    """The archivist checks the random sample. Pass -> batch approved (sampled basis).
    Fail -> every page in the batch goes to full review."""
    if batch.status != "open":
        raise ReviewError("batch already decided")
    sample_checks = sample_checks or {}
    missing = [pid for pid in batch.sample_page_ids if str(pid) not in {str(k) for k in sample_checks}]
    if passed and missing:
        raise ReviewError(f"sample pages not checked: {missing}")
    pages = db.execute(select(Page).where(Page.id.in_(batch.page_ids))).scalars().all()
    if passed:
        for p in pages:
            chk = sample_checks.get(p.id) or sample_checks.get(str(p.id)) or {}
            corrected = chk.get("text")
            base = candidate_text(p)
            final = corrected if corrected else base
            basis = "spot_check" if p.ocr_route == "text_layer" else "sampled_batch"
            if p.id in batch.sample_page_ids:
                _approve_text(db, p, final, reviewer, "correct" if corrected else "approve", role, before=base,
                              reason=f"batch {batch.id} sample check", seeded=seeded, basis=basis)
            else:
                _approve_text(db, p, final, reviewer, "approve", role, before=base,
                              reason=f"batch {batch.id} passed sample", seeded=seeded, basis=basis)
        batch.status = "passed"
    else:
        for p in pages:
            p.status = PageStatus.needs_full_review.value
            p.review_mode = "full"
            p.batch_id = None
        batch.status = "failed"
    batch.decided_by = reviewer
    batch.decided_at = utcnow()
    _decision(db, "review_batch", batch.id, "approve" if passed else "reject", reviewer, role,
              reason=reason, seeded=seeded)
    if pages:
        _update_item_state(db, pages[0].item)
    return batch


def verify_page_quotes(db: Session, page: Page, reviewer: str, confirm_compared_with_scan: bool,
                       seeded: bool = False, role: str = "archivist") -> Page:
    """Record that a person compared the approved text with the original scan word for word."""
    if not confirm_compared_with_scan:
        raise ReviewError("quote verification requires confirming a word-for-word comparison with the scan")
    if page.status != PageStatus.approved.value:
        raise ReviewError("only approved pages can be quote-verified")
    page.quote_verified = True
    page.quote_verified_by = reviewer
    page.quote_verified_at = utcnow()
    for passage in db.execute(select(Passage).where(Passage.page_id == page.id,
                                                     Passage.text_version == page.approved_text_version)).scalars():
        passage.quote_verified = True
        passage.quote_verifier = reviewer
        passage.quote_verified_at = page.quote_verified_at
    _decision(db, "page", page.id, "verify_quote", reviewer, role,
              reason="approved text compared with original scan word for word", seeded=seeded)
    return page


def review_segment(db: Session, seg: MediaSegment, action: str, reviewer: str, text: str | None = None,
                   reason: str | None = None, seeded: bool = False, role: str = "archivist") -> MediaSegment:
    before = seg.transcript_text
    if action in {"approve", "correct"}:
        if action == "correct":
            if not text:
                raise ReviewError("correction needs text")
            seg.transcript_text = text
        seg.review_status = "approved"
        seg.reviewed_by = reviewer
    elif action == "reject":
        seg.review_status = "rejected"
    else:
        raise ReviewError("unknown action")
    _decision(db, "media_segment", seg.id, action, reviewer, role, before=before,
              after=seg.transcript_text, reason=reason, seeded=seeded)
    db.flush()
    _update_item_state(db, db.get(ArchivalItem, seg.item_id))
    return seg


def verify_segment_quotes(db: Session, seg: MediaSegment, reviewer: str, confirm_compared_with_recording: bool,
                          seeded: bool = False, role: str = "archivist") -> MediaSegment:
    """Record that a person checked the transcript against the original audio/video."""
    if not confirm_compared_with_recording:
        raise ReviewError("quote verification requires confirming the transcript was checked against the recording")
    if seg.review_status != "approved":
        raise ReviewError("only approved segments can be quote-verified")
    seg.quote_verified = True
    seg.quote_verified_by = reviewer
    seg.quote_verified_at = utcnow()
    for passage in db.execute(select(Passage).where(Passage.media_segment_id == seg.id)).scalars():
        passage.quote_verified = True
        passage.quote_verifier = reviewer
        passage.quote_verified_at = seg.quote_verified_at
    _decision(db, "media_segment", seg.id, "verify_quote", reviewer, role,
              reason="transcript checked against original recording", seeded=seeded)
    return seg


def review_photo(db: Session, photo: PhotoMetadata, action: str, reviewer: str, updates: dict[str, Any] | None = None,
                 seeded: bool = False, role: str = "archivist") -> PhotoMetadata:
    if action not in REVIEW_ACTIONS:
        raise ReviewError(f"unknown action '{action}'")
    if action == "correct" and not updates:
        raise ReviewError("correction needs the corrected fields")
    if updates and "caption" in updates and not str(updates["caption"] or "").strip():
        raise ReviewError("a caption cannot be empty")
    before = photo.caption
    if updates:
        for k in ("caption", "people", "place", "event", "date_text", "date_certainty", "photographer",
                  "source_reference"):
            if k in updates:
                setattr(photo, k, updates[k])
    if action in {"approve", "correct"} and not (photo.caption or "").strip():
        raise ReviewError("a caption cannot be empty; write one before approving")
    photo.review_status = "approved" if action in {"approve", "correct"} else "rejected"
    photo.reviewed_by = reviewer
    _decision(db, "photo_metadata", photo.item_id, action, reviewer, role, before=before, after=photo.caption,
              seeded=seeded)
    item = db.get(ArchivalItem, photo.item_id)
    for p in item.pages:
        if p.doc_class == "photograph" and photo.review_status == "approved":
            p.status = PageStatus.approved.value
            p.approved_text = photo.caption
            p.approved_text_version += 1
            p.approved_by = reviewer
            p.approved_at = utcnow()
    _update_item_state(db, item)
    return photo


# Archivists and admins review any language; a translation reviewer only the languages they are named for.
ANY_LANGUAGE_ROLES = frozenset({"archivist", "admin"})


def _check_review_transition(status: str, action: str, pending: str) -> None:
    """Approve/correct only a pending item; reject a pending one or retract an approved one. Anything else
    (approving twice, reviving a rejection) is a repeat decision."""
    if status == pending or (action == "reject" and status == "approved"):
        return
    raise ReviewError(f"already reviewed ({status})")


def review_translation(db: Session, tr: Translation, action: str, reviewer: str, reviewer_languages: list[str],
                       text: str | None = None, seeded: bool = False,
                       role: str = "translation_reviewer") -> Translation:
    if action not in REVIEW_ACTIONS:
        raise ReviewError(f"unknown action '{action}'")
    if role not in ANY_LANGUAGE_ROLES and tr.target_language not in reviewer_languages:
        raise ReviewError(f"reviewer is not a named reviewer for '{tr.target_language}'")
    _check_review_transition(tr.status, action, "unreviewed")
    was_approved = tr.status == "approved"
    before = tr.text
    if action == "correct":
        if not text:
            raise ReviewError("correction needs text")
        tr.text = text
        tr.version += 1
    tr.status = "approved" if action in {"approve", "correct"} else "rejected"
    tr.reviewer = reviewer
    _decision(db, "translation", tr.id, action, reviewer, role, before=before, after=tr.text, seeded=seeded)
    if was_approved:
        from archive.ingest.publish import retract_translation  # publish imports this module

        retract_translation(db, tr, reviewer)
    return tr


def review_derivative(db: Session, d: Derivative, action: str, reviewer: str, text: str | None = None,
                      seeded: bool = False, role: str = "archivist", reason: str | None = None,
                      label: str | None = None) -> Derivative:
    """`label` replaces "Reviewed summary" on approval when the approver is not an archivist
    (an agent-drafted summary must not claim human review). A model-drafted summary approved by staff says so.
    Approving a summary supersedes the item's earlier approved summary in the same language."""
    if action not in REVIEW_ACTIONS:
        raise ReviewError(f"unknown action '{action}'")
    _check_review_transition(d.status, action, "draft")
    before = d.content
    if action == "correct":
        if not text:
            raise ReviewError("correction needs text")
        d.content = text
    d.status = "approved" if action in {"approve", "correct"} else "rejected"
    d.reviewed_by = reviewer
    if d.kind == "summary" and d.status == "approved":
        d.label_shown = label or ("Reviewed summary" if d.generator.startswith("human:") else AI_REVIEWED_SUMMARY_LABEL)
        for old in db.execute(select(Derivative).where(
                Derivative.kind == "summary", Derivative.item_id == d.item_id, Derivative.language == d.language,
                Derivative.status == "approved", Derivative.id != d.id)).scalars():
            old.status = "superseded"
            audit.record(db, reviewer, "summary.supersede", "derivative", old.id, detail={"superseded_by": d.id})
    _decision(db, "derivative", d.id, action, reviewer, role, before=before, after=d.content, reason=reason,
              seeded=seeded)
    return d


def item_ready_for_publication(db: Session, item: ArchivalItem) -> tuple[bool, list[str]]:
    problems = []
    if item.rights.display_permission != "allowed":
        problems.append("rights register does not allow display")
    if item.rights.discovery_only:
        problems.append("discovery-only source")
    if item.publication_state == PublicationState.withdrawn.value:
        problems.append("item is withdrawn; re-publication needs a rights decision and new review")
    for p in item.pages:
        if p.status != PageStatus.approved.value:
            problems.append(f"page {p.sequence} is {p.status}")
    segs = db.execute(select(MediaSegment).where(MediaSegment.item_id == item.id)).scalars().all()
    if item.item_type in ("audio", "video"):
        if not segs:
            problems.append("recording has no transcript")
        problems += [f"segment {s.id} is {s.review_status}" for s in segs if s.review_status != "approved"]
    if item.item_type == "photograph":
        photo = db.get(PhotoMetadata, item.id)
        if photo is None or photo.review_status != "approved":
            problems.append("photo caption not approved")
    if not item.pages and item.item_type not in ("audio", "video"):
        problems.append("no pages")
    return (not problems, problems)


def _update_item_state(db: Session, item: ArchivalItem) -> None:
    if item.publication_state in (PublicationState.published.value, PublicationState.withdrawn.value,
                                  PublicationState.staged.value):
        return
    _, problems = item_ready_for_publication(db, item)
    review_open = [p for p in problems if not p.startswith(("rights register", "discovery-only"))]
    item.publication_state = PublicationState.in_review.value if review_open else PublicationState.approved.value
