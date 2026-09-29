"""Authenticated archivist workspace API (ingest, review, curation, publication, audit)."""

from __future__ import annotations

import datetime as dt
import difflib
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive import audit, constitution, metadata, storage
from archive.ask.llm import LLMUnavailable, get_llm
from archive.config import get_settings
from archive.db import get_db
from archive.ingest import intake, publish, review
from archive.jobs import enqueue
from archive.models import (
    AnswerLog,
    ArchivalItem,
    AuditEvent,
    Collection,
    CollectionSetting,
    ConstitutionArticle,
    ConstitutionLink,
    DatasetVersion,
    Derivative,
    FileVersion,
    Job,
    KnowledgeEdge,
    KnowledgeNode,
    MediaSegment,
    MetadataRevision,
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
    utcnow,
)
from archive.rights import external_processing_allowed
from archive.search.hybrid import load_hits
from archive.security import (
    Admin,
    Archivist,
    Curator,
    IngestOrReview,
    Staff,
    TranslationReviewer,
    authenticate,
    create_token,
)
from archive.services import narration, sarvam_text, speech_to_text

router = APIRouter(prefix="/api/staff", tags=["staff"])
DB = Annotated[Session, Depends(get_db)]
BROWSER_IMAGE_FORMATS = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
Language = Literal["en", "hi", "mr"]


def _get_or_404[T](db: Session, model: type[T], ident: Any, what: str) -> T:
    obj = db.get(model, ident)
    if obj is None:
        raise HTTPException(404, f"{what} not found")
    return obj


def _decision_role(user: Any) -> str:
    """Role recorded on decisions at archivist-gated endpoints: the role that admitted the caller (a user who is
    also a reviewer still decides here as archivist or admin)."""
    return "admin" if "admin" in user.roles else "archivist"


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
    """A new entry needs every required field; editing an existing entry changes only the fields sent."""

    source_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    title: str | None = None
    source_url: str | None = None
    source_institution: str | None = None
    edition: str | None = None
    volume: str | None = None
    pages: str | None = None
    rights_holder: str | None = None
    basis_for_use: str | None = None
    display_permission: str = "unknown"
    training_permission: str = "unknown"
    training_basis: str | None = None
    external_processing: str = "unknown"
    evidence: str | None = None
    attribution: str | None = None
    date_checked: str | None = None
    checked_by: str | None = None
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
    existing = db.execute(select(RightsRecord).where(RightsRecord.source_key == body.source_key)).scalar()
    sent = body.model_dump(exclude_unset=True) | {"source_key": body.source_key}
    entry = body.model_dump() if existing is None else _rights_dict(existing) | sent
    errors = intake.validate_rights_entry(entry)
    if errors:
        raise HTTPException(422, errors)
    before_display = existing.display_permission if existing else None
    before_training = existing.training_permission if existing else None
    rec = intake.upsert_rights(db, entry if existing is None else sent, user.email, partial=True)
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
    if payload and not any(f.status == "stored" for f in res.files):
        # Nothing was kept, so no item either. The rollback drops the duplicate/quarantine audit events written
        # against the item; record them again, against the upload, in their own commit.
        db.rollback()
        for f in res.files:
            audit.record(db, user.email, "file.duplicate" if f.status == "duplicate" else "file.quarantine",
                         "intake_upload", meta["item_key"],
                         detail={"name": f.name, "sha256": f.sha256, "note": f.detail, "item_created": False,
                                 **({"existing_file_id": f.file_id} if f.file_id else {})})
        db.commit()
        raise HTTPException(422, {"message": "No file was stored.",
                                  "files": [{"name": f.name, "status": f.status, "notes": f.detail}
                                            for f in res.files]})
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
    published = db.execute(
        select(Passage, Page.sequence, MediaSegment.start_ms)
        .outerjoin(Page, Passage.page_id == Page.id).outerjoin(MediaSegment, Passage.media_segment_id == MediaSegment.id)
        .where(Passage.item_version_id == item.published_version_id, Passage.translation_of_id.is_(None))
        .order_by(Passage.id)).all() if item.published_version_id else []
    links = constitution.active_links(db, item_ids=[item_id], visible_only=False)
    arts = {a.number: a for a in db.execute(select(ConstitutionArticle)).scalars()} if links else {}
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
                      "text": s.transcript_text, "status": s.review_status, "quote_verified": s.quote_verified,
                      "language": s.language, "draft_engine": s.draft_engine, "source_file_id": s.source_file_id}
                     for s in segs],
        "photo": ({"caption": photo.caption, "people": photo.people, "place": photo.place, "event": photo.event,
                   "date_text": photo.date_text, "photographer": photo.photographer,
                   "source_reference": photo.source_reference, "status": photo.review_status} if photo else None),
        "derivatives": [{"id": d.id, "kind": d.kind, "language": d.language, "status": d.status,
                         "content": d.content, "label": d.label_shown, "generator": d.generator} for d in derivs],
        "batches": [{"id": b.id, "status": b.status, "pages": b.page_ids, "sample": b.sample_page_ids} for b in batches],
        "metadata": metadata.snapshot(item), "metadata_version": item.metadata_version,
        "published_passages": [{"id": p.id, "page_sequence": seq, "start_ms": start, "kind": p.kind,
                                "text": p.text[:200]} for p, seq, start in published],
        "constitution_links": [{"id": lk.id, "article_number": lk.article_number,
                                "article_title": constitution.article_title(arts[lk.article_number]),
                                "passage_id": lk.passage_id, "note": lk.note, "created_by": lk.created_by,
                                "created_at": lk.created_at.isoformat()} for lk in links],
    }


# ---------------------------------------------------------------- descriptive metadata (versioned)

Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LangCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z]{2,3}$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


class MetadataBody(BaseModel):
    """Partial update: only fields present in the request change. `reason` is kept with the revision."""

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    subjects: list[Tag] | None = Field(default=None, max_length=50)
    people: list[Tag] | None = Field(default=None, max_length=50)
    places: list[Tag] | None = Field(default=None, max_length=50)
    date_text: ShortText | None = None
    date_start: dt.date | None = None
    date_end: dt.date | None = None
    date_certainty: Literal["exact", "approximate", "unknown"] | None = None
    languages: list[LangCode] | None = Field(default=None, min_length=1, max_length=10)
    edition: ShortText | None = None
    volume: ShortText | None = None
    publisher: ShortText | None = None
    creator: ShortText | None = None


@router.put("/items/{item_id}/metadata")
def update_metadata(item_id: int, body: MetadataBody, db: DB, user: Archivist) -> dict[str, Any]:
    item = db.get(ArchivalItem, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    before = metadata.snapshot(item)
    changes = {k: getattr(body, k) for k in body.model_fields_set if k in metadata.FIELDS}
    for k in ("subjects", "people", "places", "languages"):
        if changes.get(k) is not None:
            changes[k] = _dedupe(changes[k])
    start = changes.get("date_start", item.date_start)
    end = changes.get("date_end", item.date_end)
    if start and end and end < start:
        raise HTTPException(422, "date_end is before date_start")
    for k, v in changes.items():
        if k in ("subjects", "people", "places"):
            setattr(item, k, v or [])
        elif k == "languages":
            if v:
                item.original_languages = v
        elif k == "date_certainty":
            item.date_certainty = v or "unknown"
        else:
            setattr(item, k, v or None)
    changed = metadata.record_revision(db, item, before, user.email, body.reason) is not None
    db.commit()
    return {"metadata_version": item.metadata_version, "metadata": metadata.snapshot(item), "changed": changed}


@router.get("/items/{item_id}/metadata/history")
def metadata_history(item_id: int, db: DB, user: Staff) -> list[dict[str, Any]]:
    rows = db.execute(select(MetadataRevision).where(MetadataRevision.item_id == item_id)
                      .order_by(MetadataRevision.version.desc())).scalars()
    return [{"version": r.version, "before": r.before, "after": r.after, "actor": r.actor, "reason": r.reason,
             "at": r.created_at.isoformat()} for r in rows]


# ---------------------------------------------------------------- Constitution article links (curated)

class ArticleBody(BaseModel):
    number: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{1,3}[A-Z]{0,2}(\(\d{1,2}\))?$")]
    titles: dict[Literal["en", "hi", "mr"], Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                                                             max_length=200)]]
    part: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None


@router.get("/constitution/articles")
def list_articles(db: DB, user: Staff) -> list[dict[str, Any]]:
    counts = dict(db.execute(select(ConstitutionLink.article_number, func.count())
                             .where(ConstitutionLink.removed_at.is_(None))
                             .group_by(ConstitutionLink.article_number)).all())
    arts = db.execute(select(ConstitutionArticle)).scalars().all()
    return [{"number": a.number, "titles": a.titles, "part": a.part, "links": counts.get(a.number, 0)}
            for a in sorted(arts, key=lambda a: constitution.article_sort_key(a.number))]


@router.post("/constitution/articles")
def upsert_article(body: ArticleBody, db: DB, user: Curator) -> dict[str, Any]:
    if "en" not in body.titles:
        raise HTTPException(422, "an English title is required")
    art = db.get(ConstitutionArticle, body.number)
    created = art is None
    if created:
        art = ConstitutionArticle(number=body.number, titles=dict(body.titles), part=body.part, created_by=user.email)
        db.add(art)
    else:
        art.titles, art.part = dict(body.titles), body.part
    db.flush()
    audit.record(db, user.email, "constitution.article.create" if created else "constitution.article.update",
                 "constitution_article", art.number, detail={"titles": art.titles, "part": art.part})
    db.commit()
    return {"number": art.number, "titles": art.titles, "part": art.part}


class LinkBody(BaseModel):
    passage_id: int
    article_number: str = Field(max_length=20)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


@router.post("/constitution/links")
def create_link(body: LinkBody, db: DB, user: Curator) -> dict[str, Any]:
    if db.get(ConstitutionArticle, body.article_number) is None:
        raise HTTPException(422, "unknown article; add it to the curated article list first")
    if body.passage_id not in load_hits(db, [body.passage_id]):
        raise HTTPException(422, "links can only be made on approved passages of published items")
    p = db.get(Passage, body.passage_id)
    if p.translation_of_id is not None:
        raise HTTPException(422, "link the source passage, not a translation")
    dup = db.execute(select(ConstitutionLink.id).where(
        ConstitutionLink.removed_at.is_(None), ConstitutionLink.article_number == body.article_number,
        ConstitutionLink.item_id == p.item_id, ConstitutionLink.page_id.is_not_distinct_from(p.page_id),
        ConstitutionLink.media_segment_id.is_not_distinct_from(p.media_segment_id),
        ConstitutionLink.text_hash == p.text_hash)).scalar()
    if dup:
        raise HTTPException(409, "this passage is already linked to that article")
    lk = ConstitutionLink(article_number=body.article_number, item_id=p.item_id, page_id=p.page_id,
                          media_segment_id=p.media_segment_id, passage_id=p.id, text_hash=p.text_hash,
                          note=body.note or None, created_by=user.email)
    db.add(lk)
    db.flush()
    audit.record(db, user.email, "constitution.link.add", "constitution_link", lk.id,
                 detail={"article": lk.article_number, "item_id": lk.item_id, "passage_id": p.id},
                 checksum_after=p.text_hash)
    db.commit()
    return {"id": lk.id}


class RemoveLinkBody(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


@router.post("/constitution/links/{link_id}/remove")
def remove_link(link_id: int, body: RemoveLinkBody, db: DB, user: Curator) -> dict[str, Any]:
    lk = db.get(ConstitutionLink, link_id)
    if lk is None:
        raise HTTPException(404, "link not found")
    if lk.removed_at is not None:
        raise HTTPException(409, "link already removed")
    lk.removed_at, lk.removed_by, lk.removal_reason = utcnow(), user.email, body.reason
    audit.record(db, user.email, "constitution.link.remove", "constitution_link", lk.id,
                 detail={"article": lk.article_number, "item_id": lk.item_id, "reason": body.reason})
    db.commit()
    return {"id": lk.id, "removed": True}


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
        "segments": [{"id": s.id, "item_id": s.item_id, "start_ms": s.start_ms, "text": s.transcript_text,
                      "language": s.language, "draft_engine": s.draft_engine} for s in segs],
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
    # PDF and TIFF masters cannot be shown in an <img> (a PDF master is the whole document); the per-page
    # delivery JPEG can.
    master = db.get(FileVersion, page.image_file_id) if page.image_file_id else None
    master_viewable = master is not None and master.deleted_at is None and master.format in BROWSER_IMAGE_FORMATS
    preview_file_id = page.delivery_file_id or (page.image_file_id if master_viewable else None)
    return {**_page_summary(page), "item_id": page.item_id, "item_title": page.item.title,
            "master_file_id": page.image_file_id, "preview_file_id": preview_file_id,
            "approved_text": page.approved_text,
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
    page = _get_or_404(db, Page, page_id, "page")
    try:
        review.review_page(db, page, body.action, user.email, _decision_role(user), text=body.text,
                           reason=body.reason, source_result_id=body.source_result_id)
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"page": _page_summary(page), "item_state": page.item.publication_state}


@router.post("/pages/{page_id}/reopen")
def page_reopen(page_id: int, db: DB, user: Archivist, reason: Annotated[str, Form()] = "correction") -> dict[str, Any]:
    page = _get_or_404(db, Page, page_id, "page")
    review.reopen_page(db, page, user.email, reason, _decision_role(user))
    db.commit()
    return _page_summary(page)


class ConfirmBody(BaseModel):
    confirm: bool


@router.post("/pages/{page_id}/verify-quotes")
def page_verify_quotes(page_id: int, body: ConfirmBody, db: DB, user: Archivist) -> dict[str, Any]:
    page = _get_or_404(db, Page, page_id, "page")
    try:
        review.verify_page_quotes(db, page, user.email, body.confirm, role=_decision_role(user))
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
    b = _get_or_404(db, ReviewBatch, batch_id, "batch")
    try:
        review.decide_batch(db, b, body.passed, user.email, body.reason,
                            {int(k): v for k, v in body.sample_checks.items()},
                            role=_decision_role(user))
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
    seg = _get_or_404(db, MediaSegment, seg_id, "segment")
    try:
        review.review_segment(db, seg, body.action, user.email, body.text, body.reason,
                             role=_decision_role(user))
        review._update_item_state(db, db.get(ArchivalItem, seg.item_id))
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": seg.id, "status": seg.review_status}


@router.post("/segments/{seg_id}/verify-quotes")
def segment_verify(seg_id: int, body: ConfirmBody, db: DB, user: Archivist) -> dict[str, Any]:
    seg = _get_or_404(db, MediaSegment, seg_id, "segment")
    try:
        review.verify_segment_quotes(db, seg, user.email, body.confirm, role=_decision_role(user))
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": seg.id, "quote_verified": seg.quote_verified}


@router.post("/items/{item_id}/speech-to-text")
async def item_speech_to_text(item_id: int, db: DB, user: IngestOrReview, language: Annotated[str, Form()] = "",
                              file: Annotated[UploadFile | None, File()] = None) -> dict[str, Any]:
    """Queue a Sarvam draft transcript of an uploaded recording (stored first as a preservation master) or,
    with no file, of the item's latest stored recording. The draft always goes to full staff review."""
    item = db.get(ArchivalItem, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if item.item_type not in ("audio", "video"):
        raise HTTPException(409, "speech-to-text drafts belong to audio or video items")
    if language and language not in speech_to_text.LANG:
        raise HTTPException(422, "language must be en, hi or mr (or empty to use the item language)")
    if not external_processing_allowed(item):
        raise HTTPException(409, speech_to_text.REFUSAL)
    if not speech_to_text.configured():
        raise HTTPException(503, "Sarvam speech-to-text is not configured on this installation")
    if file is not None:
        data = await file.read()
        try:
            mime = intake.sniff_format(data)[0] if data else None
        except intake.IntakeRejected:
            mime = None
        if mime not in speech_to_text.AUDIO_FORMATS:
            raise HTTPException(422, "upload a WAV, MP3, M4A, FLAC or OGG audio recording")
        stored = intake.store_original(db, item, data, file.filename or "recording", user.email)
        recording = db.get(FileVersion, stored.file_id)
        if recording.item_id != item.id:
            raise HTTPException(409, f"this recording is already stored with item {recording.item_id}")
    else:
        recording = db.execute(select(FileVersion).where(
            FileVersion.item_id == item.id, FileVersion.role == "preservation_master",
            FileVersion.deleted_at.is_(None), FileVersion.format.in_(list(speech_to_text.STORED_MEDIA_FORMATS)))
            .order_by(FileVersion.id.desc())).scalars().first()
        if recording is None:
            raise HTTPException(409, "this item has no stored recording; upload one")
    lang = language or next((code for code in item.original_languages if code in speech_to_text.LANG), None)
    job = enqueue(db, "speech_to_text", {"item_id": item.id, "file_id": recording.id, "language": lang,
                                         "actor": user.email}, priority=30)
    job.max_attempts = 1  # a rejected recording would be rejected again; staff re-run it after checking
    audit.record(db, user.email, "media.stt_requested", "archival_item", item.id,
                 detail={"file_id": recording.id, "language": lang or "unknown", "job_id": job.id})
    db.commit()
    return {"job_id": job.id, "file_id": recording.id, "language": lang, "status": "queued",
            "label": speech_to_text.DRAFT_LABEL}


class PhotoBody(BaseModel):
    action: str = "approve"
    updates: dict[str, Any] = Field(default_factory=dict)


@router.post("/photos/{item_id}/review")
def photo_review(item_id: int, body: PhotoBody, db: DB, user: Archivist) -> dict[str, Any]:
    photo = db.get(PhotoMetadata, item_id)
    if photo is None:
        raise HTTPException(404, "no photo metadata")
    try:
        review.review_photo(db, photo, body.action, user.email, body.updates, role=_decision_role(user))
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"item_id": item_id, "status": photo.review_status}


# ---------------------------------------------------------------- publication

@router.post("/items/{item_id}/publish")
def request_publish(item_id: int, db: DB, user: Archivist) -> dict[str, Any]:
    item = _get_or_404(db, ArchivalItem, item_id, "item")
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
    try:
        idx = publish.withdraw(db, item, user.email, body.reason)
    except publish.PublicationError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"item_id": item_id, "state": item.publication_state, "index_version": idx}


class RestoreBody(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/items/{item_id}/restore")
def restore_item(item_id: int, body: RestoreBody, db: DB, user: Archivist) -> dict[str, Any]:
    item = db.get(ArchivalItem, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    try:
        idx = publish.restore(db, item, user.email, body.reason)
    except publish.PublicationError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"item_id": item_id, "state": item.publication_state, "index_version": idx,
            "version": item.version}


# ---------------------------------------------------------------- translations, summaries, narration

class TranslationBody(BaseModel):
    source_passage_id: int
    target_language: Language
    text: str | None = None  # human translation; omit to draft with Sarvam


@router.post("/translations")
def create_translation(body: TranslationBody, db: DB, user: Archivist) -> dict[str, Any]:
    src = _get_or_404(db, Passage, body.source_passage_id, "passage")
    if body.target_language == src.language:
        raise HTTPException(422, f"the passage is already in '{src.language}'; choose another target language")
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


def _translation_role(user: Any, language: str) -> str:
    """A named reviewer for the language decides as translation_reviewer; otherwise an admin or archivist (the
    other roles TranslationReviewer admits) may review any language, recorded under that role."""
    if "translation_reviewer" in user.roles and language in (user.languages or []):
        return "translation_reviewer"
    if "admin" in user.roles or "archivist" in user.roles:
        return _decision_role(user)
    return "translation_reviewer"


@router.post("/translations/{tr_id}/review")
def translation_review(tr_id: int, body: ReviewTextBody, db: DB, user: TranslationReviewer) -> dict[str, Any]:
    tr = _get_or_404(db, Translation, tr_id, "translation")
    try:
        review.review_translation(db, tr, body.action, user.email, user.languages or [], body.text,
                                  role=_translation_role(user, tr.target_language))
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": tr.id, "status": tr.status, "note": "Publish the item again to index the reviewed translation."}


class SummaryBody(BaseModel):
    language: Language = "en"
    text: str | None = None  # archivist-written; omit to draft with the LLM from approved text


@router.post("/items/{item_id}/summary")
def draft_summary(item_id: int, body: SummaryBody, db: DB, user: Archivist) -> dict[str, Any]:
    item = db.get(ArchivalItem, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    approved = [p.approved_text for p in item.pages if p.status == "approved" and p.approved_text]
    approved += list(db.execute(select(MediaSegment.transcript_text).where(
        MediaSegment.item_id == item_id, MediaSegment.review_status == "approved").order_by(MediaSegment.start_ms)
    ).scalars())
    if not approved:
        raise HTTPException(409, "summaries are drafted from approved text only")
    if body.text:
        d = Derivative(kind="summary", item_id=item_id, language=body.language, content=body.text,
                       generator=f"human:{user.email}", status="draft", label_shown="Summary draft")
    else:
        if not external_processing_allowed(item):
            raise HTTPException(409, "External processing is not permitted for this item's rights entry.")
        llm = get_llm()
        if llm is None:
            raise HTTPException(503, "No answer model is configured on this installation.")
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
    d = _get_or_404(db, Derivative, d_id, "derivative")
    try:
        review.review_derivative(db, d, body.action, user.email, body.text, role=_decision_role(user))
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": d.id, "status": d.status, "label": d.label_shown}


class NarrationBody(BaseModel):
    passage_id: int
    language: Language
    prefer_local: bool = False


@router.post("/narration")
def make_narration(body: NarrationBody, db: DB, user: Archivist) -> dict[str, Any]:
    p = db.get(Passage, body.passage_id)
    if p is None:
        raise HTTPException(404, "passage not found")
    try:
        d, cached = narration.narrate(db, p, body.language, user.email, prefer_local=body.prefer_local)
    except narration.NarrationUnavailable as exc:
        raise HTTPException(503, f"narration unavailable: {exc}") from exc
    except narration.NarrationError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"id": d.id, "file_id": d.file_id, "generator": d.generator, "label": d.label_shown, "cached": cached}


# ---------------------------------------------------------------- curation

class CurationReason(BaseModel):
    """Optional free-text reason, written to the audit event (for example who drafted the entry and from what)."""
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None

    def audit_detail(self) -> dict[str, Any] | None:
        return {"reason": self.reason} if self.reason else None

    def fields(self) -> dict[str, Any]:
        return self.model_dump(exclude={"reason"})


def _reason(body: CurationReason | None) -> dict[str, Any] | None:
    return body.audit_detail() if body else None


# A curator may create an entry as a draft or already approved (stories have no separate approve step).
CurationStatus = Literal["draft", "approved"]


class TimelineBody(CurationReason):
    date_text: str
    sort_date: dt.date
    date_certainty: Literal["exact", "approximate", "unknown"] = "exact"
    titles: dict[str, str]
    descriptions: dict[str, str] = Field(default_factory=dict)
    item_ids: list[int] = Field(min_length=1)
    status: CurationStatus = "draft"


@router.get("/timeline")
def staff_timeline(db: DB, user: Staff) -> list[dict[str, Any]]:
    return [{"id": e.id, "date_text": e.date_text, "titles": e.titles, "item_ids": e.item_ids, "status": e.status}
            for e in db.execute(select(TimelineEvent).order_by(TimelineEvent.sort_date)).scalars()]


@router.post("/timeline")
def create_timeline(body: TimelineBody, db: DB, user: Curator) -> dict[str, Any]:
    _check_items_exist(db, body.item_ids)
    e = TimelineEvent(**body.fields(), curator=user.email)
    db.add(e)
    db.flush()
    audit.record(db, user.email, f"timeline.{body.status}", "timeline_event", e.id, detail=body.audit_detail())
    db.commit()
    return {"id": e.id}


@router.post("/timeline/{event_id}/approve")
def approve_timeline(event_id: int, db: DB, user: Curator, body: CurationReason | None = None) -> dict[str, Any]:
    e = _get_or_404(db, TimelineEvent, event_id, "timeline event")
    if e.status == "approved":
        raise HTTPException(409, "timeline event already approved")
    e.status = "approved"
    audit.record(db, user.email, "timeline.approve", "timeline_event", e.id, detail=_reason(body))
    db.commit()
    return {"id": e.id, "status": e.status}


class StoryBlock(BaseModel):
    """Every block cites an archive item; captions and other block fields pass through unchanged."""

    model_config = ConfigDict(extra="allow")

    item_id: Annotated[int, Field(strict=True)]


class StoryBody(CurationReason):
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    titles: dict[str, str]
    blocks: list[StoryBlock] = Field(min_length=1)
    status: CurationStatus = "draft"


@router.post("/stories")
def create_story(body: StoryBody, db: DB, user: Curator) -> dict[str, Any]:
    _check_items_exist(db, [b.item_id for b in body.blocks])
    if db.execute(select(Story.id).where(Story.slug == body.slug)).first():
        raise HTTPException(409, f"a story with slug '{body.slug}' already exists")
    st = Story(**body.fields(), curator=user.email)
    db.add(st)
    db.flush()
    audit.record(db, user.email, f"story.{body.status}", "story", st.id, detail=body.audit_detail())
    db.commit()
    return {"id": st.id}


class NodeBody(CurationReason):
    node_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
    labels: dict[str, str]
    description: str | None = None
    item_ids: list[int] = Field(min_length=1)


@router.post("/map/nodes")
def create_node(body: NodeBody, db: DB, user: Curator) -> dict[str, Any]:
    _check_items_exist(db, body.item_ids)
    n = KnowledgeNode(**body.fields(), status="proposed")
    db.add(n)
    db.flush()
    audit.record(db, user.email, "map.node.propose", "knowledge_node", n.id, detail=body.audit_detail())
    db.commit()
    return {"id": n.id}


@router.post("/map/nodes/{node_id}/approve")
def approve_node(node_id: int, db: DB, user: Curator, body: CurationReason | None = None) -> dict[str, Any]:
    n = _get_or_404(db, KnowledgeNode, node_id, "node")
    if n.status == "approved":
        raise HTTPException(409, "node already approved")
    n.status = "approved"
    n.approved_by = user.email
    audit.record(db, user.email, "map.node.approve", "knowledge_node", n.id, detail=_reason(body))
    db.commit()
    return {"id": n.id, "status": n.status}


class EdgeBody(CurationReason):
    from_node: int
    to_node: int
    relation: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)]
    evidence_item_ids: list[int] = Field(min_length=1)


@router.post("/map/edges")
def create_edge(body: EdgeBody, db: DB, user: Curator) -> dict[str, Any]:
    if body.from_node == body.to_node or db.get(KnowledgeNode, body.from_node) is None \
            or db.get(KnowledgeNode, body.to_node) is None:
        raise HTTPException(422, "an edge joins two different existing nodes")
    _check_items_exist(db, body.evidence_item_ids)
    e = KnowledgeEdge(**body.fields(), proposed_by=user.email, status="proposed")
    db.add(e)
    db.flush()
    audit.record(db, user.email, "map.edge.propose", "knowledge_edge", e.id, detail=body.audit_detail())
    db.commit()
    return {"id": e.id}


@router.post("/map/edges/{edge_id}/approve")
def approve_edge(edge_id: int, db: DB, user: Curator, body: CurationReason | None = None) -> dict[str, Any]:
    e = _get_or_404(db, KnowledgeEdge, edge_id, "edge")
    if e.status == "approved":
        raise HTTPException(409, "edge already approved")
    e.status, e.approved_by = "approved", user.email
    audit.record(db, user.email, "map.edge.approve", "knowledge_edge", e.id, detail=_reason(body))
    db.commit()
    return {"id": e.id, "status": e.status}


def _check_items_exist(db: Session, ids: list[int]) -> None:
    found = set(db.execute(select(ArchivalItem.id).where(ArchivalItem.id.in_(ids))).scalars())
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(422, f"unknown archive items: {missing}")


@router.put("/collections/{collection}")
def set_collection(collection: Collection, db: DB, user: Archivist,
                   machine_translation_enabled: bool) -> dict[str, Any]:
    collection = collection.value
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


def _job_summary(j: Job) -> dict[str, Any]:
    return {"id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "payload": j.payload,
            "error": j.last_error, "result": j.result, "updated_at": j.updated_at.isoformat()}


@router.get("/jobs")
def jobs(db: DB, user: Staff) -> list[dict[str, Any]]:
    return [_job_summary(j) for j in db.execute(select(Job).order_by(Job.id.desc()).limit(100)).scalars()]


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, db: DB, user: Staff) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _job_summary(job)


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
def create_dataset(db: DB, user: Admin,
                   name: Annotated[str, Form(min_length=1, max_length=80)]) -> dict[str, Any]:
    from archive.datasets.corpus import freeze_dataset
    if db.execute(select(DatasetVersion.id).where(DatasetVersion.name == name)).first():
        raise HTTPException(409, f"a dataset named '{name}' already exists")
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
