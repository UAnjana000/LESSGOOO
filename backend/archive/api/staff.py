"""Authenticated archivist workspace API (ingest, review, curation, publication, audit)."""

from __future__ import annotations

import datetime as dt
import difflib
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive import audit, storage
from archive.ask.llm import LLMUnavailable, get_llm
from archive.config import get_settings
from archive.db import get_db
from archive.ingest import intake, publish, review
from archive.jobs import enqueue
from archive.models import (
    AnswerLog,
    ArchivalItem,
    AuditEvent,
    CollectionSetting,
    DatasetVersion,
    Derivative,
    FileVersion,
    Job,
    KnowledgeNode,
    MediaSegment,
    ModelVersion,
    Page,
    Passage,
    PhotoMetadata,
    ReviewBatch,
    ReviewDecision,
    RightsRecord,
    Story,
    SystemState,
    TimelineEvent,
    Translation,
)
from archive.rights import external_processing_allowed
from archive.security import Admin, Archivist, Curator, Staff, TranslationReviewer, authenticate, create_token
from archive.services import narration, sarvam_text

router = APIRouter(prefix="/api/staff", tags=["staff"])
DB = Annotated[Session, Depends(get_db)]


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginBody, db: DB) -> dict[str, Any]:
    user = authenticate(db, body.email, body.password)
    if user is None:
        raise HTTPException(401, "Email or password is incorrect.")
    audit.record(db, user.email, "staff.login", "staff_user", user.id)
    db.commit()
    return {"token": create_token(user), "user": {"email": user.email, "name": user.display_name,
                                                 "roles": user.roles, "languages": user.languages}}


@router.get("/me")
def me(user: Staff) -> dict[str, Any]:
    return {"email": user.email, "name": user.display_name, "roles": user.roles, "languages": user.languages}


# ---------------------------------------------------------------- rights register

class RightsBody(BaseModel):
    source_key: str
    title: str
    source_url: str | None = None
    source_institution: str
    edition: str | None = None
    volume: str | None = None
    pages: str | None = None
    rights_holder: str
    basis_for_use: str
    display_permission: str = "unknown"
    training_permission: str = "unknown"
    training_basis: str | None = None
    external_processing: str = "unknown"
    evidence: str
    attribution: str
    date_checked: str
    checked_by: str
    discovery_only: bool = False
    is_fixture: bool = False
    notes: str | None = None


def _rights_dict(r: RightsRecord) -> dict[str, Any]:
    return {c.name: getattr(r, c.name) for c in RightsRecord.__table__.columns}


@router.get("/rights")
def list_rights(db: DB, user: Staff) -> list[dict[str, Any]]:
    return [_rights_dict(r) for r in db.execute(select(RightsRecord).order_by(RightsRecord.id)).scalars()]


@router.post("/rights")
def upsert_rights(body: RightsBody, db: DB, user: Archivist) -> dict[str, Any]:
    errors = intake.validate_rights_entry(body.model_dump())
    if errors:
        raise HTTPException(422, errors)
    existing = db.execute(select(RightsRecord).where(RightsRecord.source_key == body.source_key)).scalar()
    before_display = existing.display_permission if existing else None
    before_training = existing.training_permission if existing else None
    rec = intake.upsert_rights(db, body.model_dump(), user.email)
    effects: dict[str, Any] = {}
    if before_display == "allowed" and rec.display_permission != "allowed":
        items = db.execute(select(ArchivalItem).where(ArchivalItem.rights_record_id == rec.id,
                                                      ArchivalItem.publication_state == "published")).scalars().all()
        for it in items:
            publish.withdraw(db, it, user.email, f"rights register changed for {rec.source_key}")
        effects["withdrawn_items"] = [i.id for i in items]
    if before_training == "allowed" and rec.training_permission != "allowed":
        from archive.datasets.corpus import flag_datasets_for_rights
        effects["flagged"] = flag_datasets_for_rights(db, rec.id, user.email)
    db.commit()
    return {"rights": _rights_dict(rec), "effects": effects}


# ---------------------------------------------------------------- intake

@router.post("/intake")
async def intake_upload(db: DB, user: Archivist, metadata: Annotated[str, Form()],
                        files: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
    """Live capture / upload. metadata: JSON with title, item_type, collection, doc_class, languages,
    rights_source_key, capture {device, operator, date}, optional page_labels, expected sha256 per file."""
    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "metadata must be JSON") from exc
    rights_entries = {r.source_key: {"discovery_only": r.discovery_only}
                      for r in db.execute(select(RightsRecord)).scalars()}
    meta.setdefault("item_key", f"upload-{dt.datetime.now(dt.UTC).strftime('%Y%m%d%H%M%S%f')}")
    errors = intake.validate_item_entry(meta, rights_entries)
    if errors:
        raise HTTPException(422, errors)
    expected = meta.get("sha256") or {}
    payload = [(f.filename or "upload.bin", await f.read(), expected.get(f.filename or "")) for f in files]
    meta["capture"] = {**meta.get("capture", {}), "item_key": meta["item_key"]}
    try:
        res = intake.intake_item(db, meta, payload, user.email, meta.get("page_labels"))
    except intake.IntakeRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    job = None
    if any(f.status == "stored" for f in res.files):
        job = enqueue(db, "ingest_item", {"item_id": res.item_id, "actor": user.email}, priority=20)
    db.commit()
    return {"item_id": res.item_id, "files": [f.__dict__ for f in res.files], "pages": res.pages_created,
            "near_duplicates": res.near_duplicates, "job_id": job.id if job else None}


# ---------------------------------------------------------------- items & review

def _page_summary(p: Page) -> dict[str, Any]:
    return {"id": p.id, "sequence": p.sequence, "label": p.printed_page_label, "status": p.status,
            "doc_class": p.doc_class, "ocr_route": p.ocr_route, "gate_passed": p.gate_passed,
            "gate_version": p.gate_version, "quality_signals": p.quality_signals, "review_mode": p.review_mode,
            "batch_id": p.batch_id, "priority": p.review_priority, "quote_verified": p.quote_verified,
            "approved_by": p.approved_by, "delivery_file_id": p.delivery_file_id, "language": p.language,
            "sarvam_last_error": p.sarvam_last_error}


@router.get("/items")
def staff_items(db: DB, user: Staff) -> list[dict[str, Any]]:
    items = db.execute(select(ArchivalItem).order_by(ArchivalItem.id.desc())).scalars().all()
    return [{"id": i.id, "title": i.title, "collection": i.collection, "item_type": i.item_type,
             "state": i.publication_state, "version": i.version, "is_fixture": i.is_fixture,
             "display_permission": i.rights.display_permission, "training_permission": i.rights.training_permission,
             "access_level": i.access_level, "pages": len(i.pages),
             "pages_approved": sum(1 for p in i.pages if p.status == "approved")} for i in items]


@router.get("/items/{item_id}")
def staff_item(item_id: int, db: DB, user: Staff) -> dict[str, Any]:
    item = db.get(ArchivalItem, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    ok, problems = review.item_ready_for_publication(db, item)
    files = db.execute(select(FileVersion).where(FileVersion.item_id == item_id)).scalars().all()
    segs = db.execute(select(MediaSegment).where(MediaSegment.item_id == item_id).order_by(MediaSegment.start_ms)).scalars()
    photo = db.get(PhotoMetadata, item_id)
    derivs = db.execute(select(Derivative).where(Derivative.item_id == item_id)).scalars().all()
    batches = db.execute(select(ReviewBatch).where(ReviewBatch.item_id == item_id)).scalars().all()
    return {
        "id": item.id, "title": item.title, "state": item.publication_state, "version": item.version,
        "published_version_id": item.published_version_id, "collection": item.collection,
        "item_type": item.item_type, "is_fixture": item.is_fixture, "access_level": item.access_level,
        "rights": _rights_dict(item.rights), "capture": item.capture_details, "edition": item.edition,
        "volume": item.volume, "ready": ok, "problems": problems,
        "pages": [_page_summary(p) for p in item.pages],
        "files": [{"id": f.id, "role": f.role, "kind": f.kind, "format": f.format, "bytes": f.byte_size,
                   "sha256": f.sha256, "generator": f.generator, "deleted": f.deleted_at is not None} for f in files],
        "segments": [{"id": s.id, "start_ms": s.start_ms, "end_ms": s.end_ms, "speaker": s.speaker,
                      "text": s.transcript_text, "status": s.review_status, "quote_verified": s.quote_verified}
                     for s in segs],
        "photo": ({"caption": photo.caption, "people": photo.people, "place": photo.place, "event": photo.event,
                   "date_text": photo.date_text, "photographer": photo.photographer,
                   "source_reference": photo.source_reference, "status": photo.review_status} if photo else None),
        "derivatives": [{"id": d.id, "kind": d.kind, "language": d.language, "status": d.status,
                         "content": d.content, "label": d.label_shown, "generator": d.generator} for d in derivs],
        "batches": [{"id": b.id, "status": b.status, "pages": b.page_ids, "sample": b.sample_page_ids} for b in batches],
    }


@router.get("/files/{file_id}")
def staff_file(file_id: int, db: DB, user: Staff) -> FileResponse:
    fv = db.get(FileVersion, file_id)
    if fv is None or fv.deleted_at is not None:
        raise HTTPException(404, "file not found")
    return FileResponse(storage.resolve(fv.storage_uri), media_type=fv.format)


@router.get("/review/queue")
def review_queue(db: DB, user: Staff) -> dict[str, Any]:
    pages = db.execute(select(Page).where(Page.status.in_(["needs_full_review", "sarvam_pending",
                                                            "manual_transcription"]))
                       .order_by(Page.review_priority.desc(), Page.id)).scalars().all()
    batches = db.execute(select(ReviewBatch).where(ReviewBatch.status == "open")).scalars().all()
    segs = db.execute(select(MediaSegment).where(MediaSegment.review_status == "draft")).scalars().all()
    photos = db.execute(select(PhotoMetadata).where(PhotoMetadata.review_status == "draft")).scalars().all()
    trs = db.execute(select(Translation).where(Translation.status == "unreviewed")).scalars().all()
    derivs = db.execute(select(Derivative).where(Derivative.status == "draft")).scalars().all()
    ready = db.execute(select(ArchivalItem).where(ArchivalItem.publication_state == "approved")).scalars().all()
    mt = db.get(SystemState, "mt_requests")
    return {
        "pages": [{**_page_summary(p), "item_id": p.item_id, "item_title": p.item.title} for p in pages],
        "batches": [{"id": b.id, "item_id": b.item_id, "pages": len(b.page_ids), "sample": b.sample_page_ids}
                    for b in batches],
        "segments": [{"id": s.id, "item_id": s.item_id, "start_ms": s.start_ms, "text": s.transcript_text}
                     for s in segs],
        "photos": [{"item_id": p.item_id, "caption": p.caption} for p in photos],
        "translations": [{"id": t.id, "target_language": t.target_language, "text": t.text,
                          "source_passage_id": t.source_passage_id, "method": t.method} for t in trs],
        "derivatives": [{"id": d.id, "kind": d.kind, "item_id": d.item_id, "content": d.content} for d in derivs],
        "ready_to_publish": [{"id": i.id, "title": i.title} for i in ready],
        "popular_machine_translations": sorted((mt.value if mt else {}).items(), key=lambda kv: -kv[1])[:10],
    }


@router.get("/pages/{page_id}")
def page_detail(page_id: int, db: DB, user: Staff) -> dict[str, Any]:
    page = db.get(Page, page_id)
    if page is None:
        raise HTTPException(404, "page not found")
    results = [{"id": r.id, "engine": r.engine, "engine_version": r.engine_version, "status": r.status,
                "text": r.text, "mean_confidence": r.mean_confidence, "error": r.error, "selected": r.selected,
                "meta": r.raw_meta, "created_at": r.created_at.isoformat()} for r in page.ocr_results]
    local = next((r for r in reversed(results) if r["engine"] in ("tesseract", "text_layer") and r["status"] == "ok"), None)
    sarvam = next((r for r in reversed(results) if r["engine"] == "sarvam-doc-ai" and r["status"] == "ok"), None)
    diff = None
    if local and sarvam:
        diff = list(difflib.unified_diff(local["text"].splitlines(), sarvam["text"].splitlines(),
                                         "local", "sarvam", lineterm=""))
    decisions = db.execute(select(ReviewDecision).where(ReviewDecision.target_type == "page",
                                                        ReviewDecision.target_id == page_id)
                           .order_by(ReviewDecision.id)).scalars().all()
    return {**_page_summary(page), "item_id": page.item_id, "item_title": page.item.title,
            "master_file_id": page.image_file_id, "approved_text": page.approved_text,
            "approved_text_version": page.approved_text_version, "results": results, "local": local,
            "sarvam": sarvam, "diff": diff, "preprocessing": page.preprocessing_params,
            "external_processing_allowed": external_processing_allowed(page.item),
            "decisions": [{"id": d.id, "action": d.action, "reviewer": d.reviewer, "reason": d.reason,
                           "before": d.before, "after": d.after, "seeded_fixture": d.is_seeded_fixture,
                           "at": d.created_at.isoformat()} for d in decisions]}


class PageReviewBody(BaseModel):
    action: str
    text: str | None = None
    reason: str | None = None
    source_result_id: int | None = None


@router.post("/pages/{page_id}/review")
def page_review(page_id: int, body: PageReviewBody, db: DB, user: Archivist) -> dict[str, Any]:
    page = db.get(Page, page_id)
    if page is None:
        raise HTTPException(404, "page not found")
    try:
        review.review_page(db, page, body.action, user.email, "archivist", text=body.text, reason=body.reason,
                           source_result_id=body.source_result_id)
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"page": _page_summary(page), "item_state": page.item.publication_state}


@router.post("/pages/{page_id}/reopen")
def page_reopen(page_id: int, db: DB, user: Archivist, reason: Annotated[str, Form()] = "correction") -> dict[str, Any]:
    page = db.get(Page, page_id)
    review.reopen_page(db, page, user.email, reason)
    db.commit()
    return _page_summary(page)


class ConfirmBody(BaseModel):
    confirm: bool


@router.post("/pages/{page_id}/verify-quotes")
def page_verify_quotes(page_id: int, body: ConfirmBody, db: DB, user: Archivist) -> dict[str, Any]:
    page = db.get(Page, page_id)
    try:
        review.verify_page_quotes(db, page, user.email, body.confirm)
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return _page_summary(page)


@router.post("/pages/{page_id}/retry-sarvam")
def page_retry_sarvam(page_id: int, db: DB, user: Archivist) -> dict[str, Any]:
    page = db.get(Page, page_id)
    if page is None or page.status not in ("sarvam_pending", "needs_full_review"):
        raise HTTPException(409, "page is not waiting for OCR fallback")
    if not external_processing_allowed(page.item):
        raise HTTPException(409, "this item may not be sent to external processing")
    job = enqueue(db, "sarvam_retry", {"page_id": page_id, "actor": user.email}, priority=30)
    db.commit()
    return {"job_id": job.id}


class BatchBody(BaseModel):
    passed: bool
    reason: str | None = None
    sample_checks: dict[str, dict[str, Any]] = Field(default_factory=dict)


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: int, db: DB, user: Staff) -> dict[str, Any]:
    b = db.get(ReviewBatch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    pages = db.execute(select(Page).where(Page.id.in_(b.sample_page_ids))).scalars().all()
    return {"id": b.id, "item_id": b.item_id, "status": b.status, "page_ids": b.page_ids,
            "sample": [{**_page_summary(p), "candidate_text": review.candidate_text(p)} for p in pages]}


@router.post("/batches/{batch_id}/decide")
def batch_decide(batch_id: int, body: BatchBody, db: DB, user: Archivist) -> dict[str, Any]:
    b = db.get(ReviewBatch, batch_id)
    try:
        review.decide_batch(db, b, body.passed, user.email, body.reason,
                            {int(k): v for k, v in body.sample_checks.items()})
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": b.id, "status": b.status}


class SegmentReviewBody(BaseModel):
    action: str
    text: str | None = None
    reason: str | None = None


@router.post("/segments/{seg_id}/review")
def segment_review(seg_id: int, body: SegmentReviewBody, db: DB, user: Archivist) -> dict[str, Any]:
    seg = db.get(MediaSegment, seg_id)
    try:
        review.review_segment(db, seg, body.action, user.email, body.text, body.reason)
        review._update_item_state(db, db.get(ArchivalItem, seg.item_id))
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": seg.id, "status": seg.review_status}


@router.post("/segments/{seg_id}/verify-quotes")
def segment_verify(seg_id: int, body: ConfirmBody, db: DB, user: Archivist) -> dict[str, Any]:
    seg = db.get(MediaSegment, seg_id)
    try:
        review.verify_segment_quotes(db, seg, user.email, body.confirm)
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": seg.id, "quote_verified": seg.quote_verified}


class PhotoBody(BaseModel):
    action: str = "approve"
    updates: dict[str, Any] = Field(default_factory=dict)


@router.post("/photos/{item_id}/review")
def photo_review(item_id: int, body: PhotoBody, db: DB, user: Archivist) -> dict[str, Any]:
    photo = db.get(PhotoMetadata, item_id)
    if photo is None:
        raise HTTPException(404, "no photo metadata")
    review.review_photo(db, photo, body.action, user.email, body.updates)
    db.commit()
    return {"item_id": item_id, "status": photo.review_status}


# ---------------------------------------------------------------- publication

@router.post("/items/{item_id}/publish")
def request_publish(item_id: int, db: DB, user: Archivist) -> dict[str, Any]:
    item = db.get(ArchivalItem, item_id)
    ok, problems = review.item_ready_for_publication(db, item)
    if not ok:
        raise HTTPException(409, {"message": "Item is not ready to publish.", "problems": problems})
    job = enqueue(db, "publish_item", {"item_id": item_id, "actor": user.email}, priority=10)
    db.commit()
    return {"job_id": job.id, "status": "queued"}


class WithdrawBody(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/items/{item_id}/withdraw")
def withdraw_item(item_id: int, body: WithdrawBody, db: DB, user: Archivist) -> dict[str, Any]:
    item = db.get(ArchivalItem, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    idx = publish.withdraw(db, item, user.email, body.reason)
    db.commit()
    return {"item_id": item_id, "state": item.publication_state, "index_version": idx}


# ---------------------------------------------------------------- translations, summaries, narration

class TranslationBody(BaseModel):
    source_passage_id: int
    target_language: str
    text: str | None = None  # human translation; omit to draft with Sarvam


@router.post("/translations")
def create_translation(body: TranslationBody, db: DB, user: Archivist) -> dict[str, Any]:
    src = db.get(Passage, body.source_passage_id)
    if src is None:
        raise HTTPException(404, "passage not found")
    if body.text:
        tr = Translation(source_passage_id=src.id, target_language=body.target_language, text=body.text,
                         method="human", provider=user.email)
    else:
        if not external_processing_allowed(db.get(ArchivalItem, src.item_id)):
            raise HTTPException(409, "external processing not permitted for this item")
        try:
            text, model = sarvam_text.translate(src.text, src.language, body.target_language)
        except sarvam_text.ServiceUnavailable as exc:
            raise HTTPException(503, f"translation service unavailable: {exc}") from exc
        tr = Translation(source_passage_id=src.id, target_language=body.target_language, text=text,
                         method="machine", provider="sarvam", model=model)
    db.add(tr)
    db.flush()
    audit.record(db, user.email, "translation.draft", "translation", tr.id, detail={"method": tr.method})
    db.commit()
    return {"id": tr.id, "status": tr.status}


class ReviewTextBody(BaseModel):
    action: str
    text: str | None = None


@router.post("/translations/{tr_id}/review")
def translation_review(tr_id: int, body: ReviewTextBody, db: DB, user: TranslationReviewer) -> dict[str, Any]:
    tr = db.get(Translation, tr_id)
    try:
        review.review_translation(db, tr, body.action, user.email, user.languages or [], body.text)
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": tr.id, "status": tr.status, "note": "Publish the item again to index the reviewed translation."}


class SummaryBody(BaseModel):
    language: str = "en"
    text: str | None = None  # archivist-written; omit to draft with the LLM from approved text


@router.post("/items/{item_id}/summary")
def draft_summary(item_id: int, body: SummaryBody, db: DB, user: Archivist) -> dict[str, Any]:
    item = db.get(ArchivalItem, item_id)
    approved = [p.approved_text for p in item.pages if p.status == "approved" and p.approved_text]
    if not approved:
        raise HTTPException(409, "summaries are drafted from approved text only")
    if body.text:
        d = Derivative(kind="summary", item_id=item_id, language=body.language, content=body.text,
                       generator=f"human:{user.email}", status="draft", label_shown="Summary draft")
    else:
        llm = get_llm()
        if llm is None or not external_processing_allowed(item):
            raise HTTPException(503, "no answer model configured or external processing not permitted")
        try:
            res = llm.complete("Summarise the archive text in 3-4 neutral sentences. Do not add facts. "
                               'Return JSON {"summary": "..."}', "\n\n".join(approved)[:6000], 300)
            content = json.loads(res.content[res.content.find("{"):res.content.rfind("}") + 1])["summary"]
        except (LLMUnavailable, ValueError, KeyError) as exc:
            raise HTTPException(503, f"summary draft failed: {exc}") from exc
        d = Derivative(kind="summary", item_id=item_id, language=body.language, content=content,
                       generator=res.model, prompt_version="summary-v1", status="draft",
                       label_shown="AI-generated summary")
    db.add(d)
    db.flush()
    audit.record(db, user.email, "summary.draft", "derivative", d.id)
    db.commit()
    return {"id": d.id, "status": d.status, "label": d.label_shown}


@router.post("/derivatives/{d_id}/review")
def derivative_review(d_id: int, body: ReviewTextBody, db: DB, user: Archivist) -> dict[str, Any]:
    d = db.get(Derivative, d_id)
    review.review_derivative(db, d, body.action, user.email, body.text)
    db.commit()
    return {"id": d.id, "status": d.status, "label": d.label_shown}


class NarrationBody(BaseModel):
    passage_id: int
    language: str
    prefer_local: bool = False


@router.post("/narration")
def make_narration(body: NarrationBody, db: DB, user: Archivist) -> dict[str, Any]:
    p = db.get(Passage, body.passage_id)
    if p is None:
        raise HTTPException(404, "passage not found")
    try:
        d = narration.narrate_passage(db, p, body.language, user.email, prefer_local=body.prefer_local)
    except narration.NarrationError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": d.id, "file_id": d.file_id, "generator": d.generator, "label": d.label_shown}


# ---------------------------------------------------------------- curation

class TimelineBody(BaseModel):
    date_text: str
    sort_date: dt.date
    date_certainty: str = "exact"
    titles: dict[str, str]
    descriptions: dict[str, str] = Field(default_factory=dict)
    item_ids: list[int] = Field(min_length=1)
    status: str = "draft"


@router.get("/timeline")
def staff_timeline(db: DB, user: Staff) -> list[dict[str, Any]]:
    return [{"id": e.id, "date_text": e.date_text, "titles": e.titles, "item_ids": e.item_ids, "status": e.status}
            for e in db.execute(select(TimelineEvent).order_by(TimelineEvent.sort_date)).scalars()]


@router.post("/timeline")
def create_timeline(body: TimelineBody, db: DB, user: Curator) -> dict[str, Any]:
    _check_items_exist(db, body.item_ids)
    e = TimelineEvent(**body.model_dump(), curator=user.email)
    db.add(e)
    db.flush()
    audit.record(db, user.email, f"timeline.{body.status}", "timeline_event", e.id)
    db.commit()
    return {"id": e.id}


@router.post("/timeline/{event_id}/approve")
def approve_timeline(event_id: int, db: DB, user: Curator) -> dict[str, Any]:
    e = db.get(TimelineEvent, event_id)
    e.status = "approved"
    audit.record(db, user.email, "timeline.approve", "timeline_event", e.id)
    db.commit()
    return {"id": e.id, "status": e.status}


class StoryBody(BaseModel):
    slug: str
    titles: dict[str, str]
    blocks: list[dict[str, Any]] = Field(min_length=1)
    status: str = "draft"


@router.post("/stories")
def create_story(body: StoryBody, db: DB, user: Curator) -> dict[str, Any]:
    for b in body.blocks:
        if not b.get("item_id"):
            raise HTTPException(422, "every story block must cite an archive item")
    _check_items_exist(db, [b["item_id"] for b in body.blocks])
    st = Story(**body.model_dump(), curator=user.email)
    db.add(st)
    db.flush()
    audit.record(db, user.email, f"story.{body.status}", "story", st.id)
    db.commit()
    return {"id": st.id}


class NodeBody(BaseModel):
    node_type: str
    labels: dict[str, str]
    description: str | None = None
    item_ids: list[int] = Field(min_length=1)


@router.post("/map/nodes")
def create_node(body: NodeBody, db: DB, user: Curator) -> dict[str, Any]:
    _check_items_exist(db, body.item_ids)
    n = KnowledgeNode(**body.model_dump(), status="proposed")
    db.add(n)
    db.flush()
    audit.record(db, user.email, "map.node.propose", "knowledge_node", n.id)
    db.commit()
    return {"id": n.id}


@router.post("/map/nodes/{node_id}/approve")
def approve_node(node_id: int, db: DB, user: Curator) -> dict[str, Any]:
    n = db.get(KnowledgeNode, node_id)
    n.status = "approved"
    n.approved_by = user.email
    audit.record(db, user.email, "map.node.approve", "knowledge_node", n.id)
    db.commit()
    return {"id": n.id, "status": n.status}


def _check_items_exist(db: Session, ids: list[int]) -> None:
    found = set(db.execute(select(ArchivalItem.id).where(ArchivalItem.id.in_(ids))).scalars())
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(422, f"unknown archive items: {missing}")


@router.put("/collections/{collection}")
def set_collection(collection: str, db: DB, user: Archivist, machine_translation_enabled: bool) -> dict[str, Any]:
    row = db.get(CollectionSetting, collection) or CollectionSetting(collection=collection)
    row.machine_translation_enabled = machine_translation_enabled
    db.merge(row)
    audit.record(db, user.email, "collection.settings", "collection_setting", collection,
                 detail={"machine_translation_enabled": machine_translation_enabled})
    db.commit()
    return {"collection": collection, "machine_translation_enabled": machine_translation_enabled}


# ---------------------------------------------------------------- audit, jobs, stats, datasets

@router.get("/audit")
def audit_log(db: DB, user: Staff, entity: str | None = None, entity_id: str | None = None,
              limit: int = 200) -> list[dict[str, Any]]:
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(min(limit, 1000))
    if entity:
        stmt = stmt.where(AuditEvent.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    return [{"id": a.id, "actor": a.actor, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
             "version": a.entity_version, "detail": a.detail, "checksum_after": a.checksum_after,
             "at": a.created_at.isoformat(), "row_hash": a.row_hash[:16]} for a in db.execute(stmt).scalars()]


@router.get("/audit/verify")
def audit_verify(db: DB, user: Admin) -> dict[str, Any]:
    ok, n = audit.verify_chain(db)
    return {"chain_ok": ok, "events_checked": n}


@router.get("/jobs")
def jobs(db: DB, user: Staff) -> list[dict[str, Any]]:
    return [{"id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "payload": j.payload,
             "error": j.last_error, "result": j.result, "updated_at": j.updated_at.isoformat()}
            for j in db.execute(select(Job).order_by(Job.id.desc()).limit(100)).scalars()]


@router.get("/stats")
def stats(db: DB, user: Staff) -> dict[str, Any]:
    rows = db.execute(
        select(AnswerLog.outcome, func.count(), func.coalesce(func.sum(AnswerLog.tokens_in), 0),
               func.coalesce(func.sum(AnswerLog.tokens_out), 0), func.coalesce(func.sum(AnswerLog.cost_usd), 0.0),
               func.coalesce(func.avg(AnswerLog.latency_ms), 0)).group_by(AnswerLog.outcome)).all()
    return {
        "items_by_state": dict(db.execute(select(ArchivalItem.publication_state, func.count())
                                          .group_by(ArchivalItem.publication_state)).all()),
        "pages_by_status": dict(db.execute(select(Page.status, func.count()).group_by(Page.status)).all()),
        "pages_by_route": dict(db.execute(select(Page.ocr_route, func.count()).group_by(Page.ocr_route)).all()),
        "answers": [{"outcome": r[0], "count": r[1], "tokens_in": int(r[2]), "tokens_out": int(r[3]),
                     "cost_usd": float(r[4]), "avg_latency_ms": float(r[5])} for r in rows],
        "cache_hits": db.execute(select(func.count()).where(AnswerLog.cache_hit.is_(True))).scalar(),
        "datasets": [{"name": d.name, "passages": d.passage_count, "status": d.status}
                     for d in db.execute(select(DatasetVersion)).scalars()],
        "models": [{"name": m.name, "role": m.role, "status": m.status}
                   for m in db.execute(select(ModelVersion)).scalars()],
    }


@router.post("/datasets")
def create_dataset(db: DB, user: Admin, name: Annotated[str, Form()]) -> dict[str, Any]:
    from archive.datasets.corpus import freeze_dataset
    dv = freeze_dataset(db, name, user.email)
    db.commit()
    return {"id": dv.id, "name": dv.name, "passages": dv.passage_count, "gate": dv.gate_report}


@router.get("/settings/status")
def settings_status(user: Staff) -> dict[str, Any]:
    from archive import tracing
    from archive.search.models import model_status
    s = get_settings()
    return {"environment": s.environment, "sarvam_configured": s.sarvam_available,
            "llm_configured": s.llm_available, "llm_model": s.llm_model or None,
            "trace_backend": tracing.backend_name(), "models": model_status(),
            "gate_config": str(s.gate_config_path), "sufficiency_threshold": s.sufficiency_threshold,
            "sufficiency_threshold_version": s.sufficiency_threshold_version}
