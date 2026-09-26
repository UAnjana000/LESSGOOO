"""Staged, versioned publication and withdrawal (spec 4.7).

stage   -> write passages + embeddings under a new item_version (not visible)
verify  -> delivery checksums, passage/embedding counts, every passage anchored to a page or timestamp
switch  -> one PostgreSQL transaction sets published_version + state=published (+ index_version bump)
propagate -> kiosks pick up the new version on next sync; old versions cleaned after a grace period

withdraw -> one write sets state=withdrawn (visitor API blocks immediately), then background cleanup
            removes index entries and delivery copies and verifies the removal.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from archive import audit, storage
from archive.config import get_settings
from archive.ingest.review import item_ready_for_publication
from archive.models import (
    AnswerCache,
    ArchivalItem,
    FileVersion,
    ItemVersion,
    Job,
    MediaSegment,
    Page,
    Passage,
    PhotoMetadata,
    PublicationState,
    SystemState,
    Translation,
    utcnow,
)
from archive.search.models import get_embedder

log = logging.getLogger(__name__)


class PublicationError(RuntimeError):
    pass


def current_index_version(db: Session) -> int:
    row = db.get(SystemState, "index_version")
    return int(row.value.get("value", 0)) if row else 0


def bump_index_version(db: Session) -> int:
    row = db.execute(select(SystemState).where(SystemState.key == "index_version").with_for_update()).scalar_one_or_none()
    if row is None:
        row = SystemState(key="index_version", value={"value": 1})
        db.add(row)
        db.flush()
        return 1
    new = int(row.value.get("value", 0)) + 1
    row.value = {"value": new}
    db.flush()
    return new


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=get_settings().passage_max_chars, chunk_overlap=0, add_start_index=True,
        separators=["\n\n", "\n", "। ", ". ", " ", ""],
    )


def _bboxes_for(page: Page, start: int, end: int) -> list[list[int]]:
    """Word boxes for a character range, when the approved text still equals the selected OCR text."""
    sel = [r for r in page.ocr_results if r.selected and r.status == "ok" and r.words]
    if not sel or sel[-1].text != page.approved_text:
        return []
    boxes, cursor = [], 0
    text = page.approved_text or ""
    for w in sel[-1].words:
        idx = text.find(w["t"], cursor)
        if idx < 0:
            continue
        cursor = idx + len(w["t"])
        if idx >= start and cursor <= end:
            boxes.append(w["bbox"])
    return boxes


def _kind_for_page(page: Page) -> str:
    if page.doc_class == "photograph":
        return "reviewed_caption"
    if page.ocr_route == "text_layer":
        return "source_text"
    return "reviewed_transcription"


def stage(db: Session, item: ArchivalItem, actor: str) -> ItemVersion:
    ok, problems = item_ready_for_publication(db, item)
    if not ok:
        raise PublicationError("; ".join(problems))
    last = db.execute(select(ItemVersion.version_no).where(ItemVersion.item_id == item.id)
                      .order_by(ItemVersion.version_no.desc()).limit(1)).scalar() or 0
    version = ItemVersion(item_id=item.id, version_no=last + 1, state="staging")
    db.add(version)
    db.flush()
    passages: list[Passage] = []
    splitter = _splitter()
    for page in item.pages:
        text = page.approved_text or ""
        basis = page.quality_signals.get("review_basis", "full_review")
        for doc in splitter.create_documents([text]):
            start = int(doc.metadata["start_index"])
            chunk = doc.page_content
            passages.append(Passage(
                item_id=item.id, item_version_id=version.id, page_id=page.id, kind=_kind_for_page(page),
                char_start=start, char_end=start + len(chunk), bboxes=_bboxes_for(page, start, start + len(chunk)),
                text=chunk, text_hash=_text_hash(chunk), text_version=page.approved_text_version,
                language=page.language, quote_verified=page.quote_verified, quote_verifier=page.quote_verified_by,
                quote_verified_at=page.quote_verified_at, review_basis=basis, approved_by=page.approved_by or actor,
                approved_at=page.approved_at or utcnow()))
    segs = db.execute(select(MediaSegment).where(MediaSegment.item_id == item.id,
                                                 MediaSegment.review_status == "approved")
                      .order_by(MediaSegment.start_ms)).scalars().all()
    for seg in segs:
        passages.append(Passage(
            item_id=item.id, item_version_id=version.id, media_segment_id=seg.id, kind="reviewed_transcript",
            char_start=0, char_end=len(seg.transcript_text), text=seg.transcript_text,
            text_hash=_text_hash(seg.transcript_text), language=seg.language, quote_verified=seg.quote_verified,
            quote_verifier=seg.quote_verified_by, quote_verified_at=seg.quote_verified_at, review_basis="full_review",
            approved_by=seg.reviewed_by or actor, approved_at=utcnow()))
    db.add_all(passages)
    db.flush()
    # Reviewed translations follow their source passage into the new version (same text hash).
    by_hash = {p.text_hash: p for p in passages}
    old_ids = select(Passage.id).where(Passage.item_id == item.id, Passage.item_version_id != version.id)
    trs = db.execute(select(Translation, Passage).join(Passage, Translation.source_passage_id == Passage.id)
                     .where(Translation.status == "approved", Passage.id.in_(old_ids.union(
                         select(Passage.id).where(Passage.item_version_id == version.id))))).all()
    for tr, src in trs:
        target = by_hash.get(src.text_hash)
        if target is None:
            continue
        tp = Passage(item_id=item.id, item_version_id=version.id, page_id=target.page_id,
                     media_segment_id=target.media_segment_id, kind="reviewed_translation",
                     translation_of_id=target.id, char_start=target.char_start, char_end=target.char_end,
                     text=tr.text, text_hash=_text_hash(tr.text), text_version=tr.version,
                     language=tr.target_language, quote_verified=False, review_basis="full_review",
                     approved_by=tr.reviewer or actor, approved_at=utcnow())
        db.add(tp)
        passages.append(tp)
    db.flush()
    embedder = get_embedder()
    vectors = embedder.embed_documents([p.text for p in passages]) if passages else []
    for p, v in zip(passages, vectors, strict=True):
        p.embedding = v
        p.embedding_model = embedder.name
    version.state = "staged"
    item.publication_state = PublicationState.staged.value
    db.flush()
    audit.record(db, actor, "publish.stage", "item_version", version.id, entity_version=version.version_no,
                 detail={"item_id": item.id, "passages": len(passages)})
    return version


def verify(db: Session, item: ArchivalItem, version: ItemVersion) -> dict[str, Any]:
    report: dict[str, Any] = {"checks": {}, "errors": []}
    passages = db.execute(select(Passage).where(Passage.item_version_id == version.id)).scalars().all()
    report["checks"]["passage_count"] = len(passages)
    if not passages:
        report["errors"].append("no passages staged")
    missing_anchor = [p.id for p in passages if p.page_id is None and p.media_segment_id is None]
    if missing_anchor:
        report["errors"].append(f"passages without page/timestamp anchor: {missing_anchor}")
    no_vec = [p.id for p in passages if p.embedding is None]
    report["checks"]["embedded"] = len(passages) - len(no_vec)
    if no_vec:
        report["errors"].append(f"passages missing embeddings: {no_vec}")
    pages = {pg.id: pg for pg in item.pages}
    for p in passages:
        if p.page_id and p.kind != "reviewed_translation":
            src = pages[p.page_id].approved_text or ""
            if src[p.char_start:p.char_end] != p.text:
                report["errors"].append(f"passage {p.id} does not match approved text of page {p.page_id}")
    for pg in item.pages:
        fv = db.get(FileVersion, pg.delivery_file_id) if pg.delivery_file_id else None
        if fv is None or not storage.verify(fv.storage_uri, fv.sha256):
            report["errors"].append(f"delivery copy missing or checksum mismatch for page {pg.sequence}")
    if item.item_type in ("audio", "video"):
        media = db.query(FileVersion).filter_by(item_id=item.id, role="delivery", kind="media",
                                                 deleted_at=None).first()
        if media is None or not storage.verify(media.storage_uri, media.sha256):
            report["errors"].append("media delivery copy missing or checksum mismatch")
    report["ok"] = not report["errors"]
    version.verification = report
    version.state = "staged" if report["ok"] else "failed"
    db.flush()
    audit.record(db, "ingestion-graph", "publish.verify", "item_version", version.id,
                 entity_version=version.version_no, detail={"ok": report["ok"], "errors": report["errors"][:10]})
    return report


def switch(db: Session, item: ArchivalItem, version: ItemVersion, actor: str) -> int:
    """Atomic visibility switch. Caller commits; nothing else in this transaction."""
    db.execute(select(ArchivalItem.id).where(ArchivalItem.id == item.id).with_for_update())
    if version.state != "staged" or not version.verification.get("ok"):
        raise PublicationError("version not verified")
    if item.published_version_id:
        db.execute(update(ItemVersion).where(ItemVersion.id == item.published_version_id)
                   .values(state="superseded"))
    item.published_version_id = version.id
    item.publication_state = PublicationState.published.value
    item.version = version.version_no
    version.state = "published"
    version.published_at = utcnow()
    idx = bump_index_version(db)
    audit.record(db, actor, "publish.switch", "archival_item", item.id, entity_version=version.version_no,
                 detail={"item_version_id": version.id, "index_version": idx})
    return idx


def publish_item(db: Session, item: ArchivalItem, actor: str) -> dict[str, Any]:
    """Run stage -> verify -> switch with commits between steps so a failure never exposes partial state."""
    version = stage(db, item, actor)
    db.commit()
    report = verify(db, item, version)
    if not report["ok"]:
        item.publication_state = PublicationState.approved.value
        db.commit()
        raise PublicationError("verification failed: " + "; ".join(report["errors"]))
    db.commit()
    idx = switch(db, item, version, actor)
    db.commit()
    return {"item_id": item.id, "version": version.version_no, "index_version": idx, "verification": report}


def withdraw(db: Session, item: ArchivalItem, actor: str, reason: str) -> int:
    """Single write that blocks the item at the visitor API immediately; cleanup is queued."""
    item.publication_state = PublicationState.withdrawn.value
    item.withdrawn_at = utcnow()
    item.withdrawal_reason = reason
    idx = bump_index_version(db)
    audit.record(db, actor, "item.withdraw", "archival_item", item.id, detail={"reason": reason, "index_version": idx})
    db.add(Job(kind="withdraw_cleanup", payload={"item_id": item.id, "actor": actor}, priority=10))
    return idx


def withdraw_cleanup(db: Session, item_id: int, actor: str = "worker") -> dict[str, Any]:
    item = db.get(ArchivalItem, item_id)
    if item is None or item.publication_state != PublicationState.withdrawn.value:
        return {"skipped": True}
    db.execute(update(Passage).where(Passage.item_id == item_id).values(indexed=False, embedding=None))
    removed = 0
    for fv in db.query(FileVersion).filter_by(item_id=item_id, role="delivery", deleted_at=None):
        storage.delete_delivery(fv.storage_uri)
        fv.deleted_at = utcnow()
        removed += 1
    for pg in item.pages:
        pg.delivery_file_id = None
    db.execute(delete(AnswerCache))
    db.flush()
    still_indexed = db.query(Passage).filter_by(item_id=item_id, indexed=True).count()
    live_files = [fv.id for fv in db.query(FileVersion).filter_by(item_id=item_id, role="delivery", deleted_at=None)]
    verified = still_indexed == 0 and not live_files
    audit.record(db, actor, "item.withdraw_verified" if verified else "item.withdraw_incomplete", "archival_item",
                 item_id, detail={"delivery_removed": removed, "still_indexed": still_indexed,
                                  "live_delivery_files": live_files})
    return {"verified": verified, "delivery_removed": removed, "still_indexed": still_indexed}


def withdrawn_item_ids(db: Session) -> list[int]:
    return list(db.execute(select(ArchivalItem.id).where(
        ArchivalItem.publication_state == PublicationState.withdrawn.value)).scalars())


def photo_caption(db: Session, item_id: int) -> PhotoMetadata | None:
    return db.get(PhotoMetadata, item_id)
