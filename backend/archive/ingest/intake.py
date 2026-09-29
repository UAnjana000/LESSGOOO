"""Intake (spec 4.1): metadata capture, format validation, SHA-256, exact-duplicate check,
near-duplicate flagging, preservation storage of the unchanged original, quarantine on rejection.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import imagehash
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from archive import audit, storage
from archive.ingest.preprocess import find_spread_gutter, load_gray
from archive.models import (
    AccessLevel,
    ArchivalItem,
    Collection,
    DocClass,
    FileVersion,
    ItemType,
    MediaSegment,
    Page,
    PageStatus,
    Permission,
    PhotoMetadata,
    RightsRecord,
)

log = logging.getLogger(__name__)

MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"II*\x00", "image/tiff", ".tif"),
    (b"MM\x00*", "image/tiff", ".tif"),
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"fLaC", "audio/flac", ".flac"),
    (b"OggS", "audio/ogg", ".ogg"),
    (b"ID3", "audio/mpeg", ".mp3"),
]
NEAR_DUP_HAMMING = 6

RIGHTS_REQUIRED = ("source_key", "title", "source_institution", "rights_holder", "basis_for_use",
                   "display_permission", "training_permission", "external_processing", "evidence",
                   "attribution", "date_checked", "checked_by")
ITEM_REQUIRED = ("item_key", "rights_source_key", "title", "item_type", "collection", "doc_class", "languages")


class IntakeRejected(ValueError):
    pass


def sniff_format(data: bytes) -> tuple[str, str]:
    for magic, mime, ext in MAGIC:
        if data.startswith(magic):
            return mime, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav", ".wav"
    # Untagged MP3: MPEG audio frame sync with a non-zero layer (ADTS AAC has layer 00).
    if len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0 and data[1] & 0x06:
        return "audio/mpeg", ".mp3"
    if data[4:8] == b"ftyp":
        return ("audio/mp4", ".m4a") if data[8:11] in (b"M4A", b"M4B") else ("video/mp4", ".mp4")
    if data[:4] == b"\x1aE\xdf\xa3":
        return "video/webm", ".webm"
    raise IntakeRejected("unsupported or unrecognised file format")


def validate_rights_entry(entry: dict[str, Any]) -> list[str]:
    errors = [f"rights.{k} missing" for k in RIGHTS_REQUIRED if entry.get(k) in (None, "")]
    for key in ("display_permission", "training_permission", "external_processing"):
        if entry.get(key) not in {p.value for p in Permission}:
            errors.append(f"rights.{key} must be allowed|not_allowed|unknown")
    try:
        dt.date.fromisoformat(str(entry.get("date_checked")))
    except ValueError:
        errors.append("rights.date_checked must be YYYY-MM-DD")
    return errors


def validate_item_entry(entry: dict[str, Any], rights: dict[str, dict[str, Any]]) -> list[str]:
    errors = [f"item.{k} missing" for k in ITEM_REQUIRED if not entry.get(k)]
    if entry.get("item_type") not in {t.value for t in ItemType}:
        errors.append("item.item_type invalid")
    if entry.get("collection") not in {c.value for c in Collection}:
        errors.append("item.collection invalid")
    if entry.get("doc_class") not in {d.value for d in DocClass}:
        errors.append("item.doc_class invalid")
    if entry.get("access_level", "public") not in {a.value for a in AccessLevel}:
        errors.append("item.access_level invalid")
    r = rights.get(entry.get("rights_source_key", ""))
    if r is None:
        errors.append("item.rights_source_key not in rights register")
    else:
        if r.get("discovery_only"):
            errors.append("source is discovery/linking only (e.g. NDLI); content may not be ingested")
        for f in entry.get("files", []):
            if f.get("url") and not entry.get("download_permitted"):
                errors.append("URL import requires download_permitted=true backed by the rights evidence")
    return errors


RIGHTS_FIELDS = ("title", "source_url", "source_institution", "edition", "volume", "pages", "rights_holder",
                 "basis_for_use", "display_permission", "training_permission", "training_basis",
                 "external_processing", "evidence", "attribution", "checked_by", "notes")


def _audit_value(v: Any) -> Any:
    return v.isoformat() if isinstance(v, dt.date) else v


def upsert_rights(db: Session, entry: dict[str, Any], actor: str, partial: bool = False) -> RightsRecord:
    """Create or update a rights entry. With `partial`, an existing entry changes only the keys in `entry`
    (a staff edit); otherwise every field is written (a manifest import restates the whole entry)."""
    rec = db.execute(select(RightsRecord).where(RightsRecord.source_key == entry["source_key"])).scalar_one_or_none()
    partial = partial and rec is not None
    fields = {k: entry.get(k) for k in RIGHTS_FIELDS if not partial or k in entry}
    if not partial or "date_checked" in entry:
        fields["date_checked"] = dt.date.fromisoformat(str(entry["date_checked"]))
    for flag in ("discovery_only", "is_fixture"):
        if not partial or flag in entry:
            fields[flag] = bool(entry.get(flag, False))
    if rec is None:
        rec = RightsRecord(source_key=entry["source_key"], **fields)
        db.add(rec)
        db.flush()
        audit.record(db, actor, "rights.create", "rights_record", rec.id, detail={"source_key": rec.source_key})
    else:
        changed = {k: v for k, v in fields.items() if getattr(rec, k) != v}
        before = {k: _audit_value(getattr(rec, k)) for k in changed}
        for k, v in changed.items():
            setattr(rec, k, v)
        db.flush()
        audit.record(db, actor, "rights.update", "rights_record", rec.id,
                     detail={"source_key": rec.source_key, "before": before,
                             "after": {k: _audit_value(v) for k, v in changed.items()}})
    return rec


@dataclass
class IntakeFileResult:
    name: str
    status: str  # stored | duplicate | quarantined
    sha256: str | None = None
    detail: str = ""
    file_id: int | None = None


@dataclass
class IntakeResult:
    item_id: int | None
    files: list[IntakeFileResult] = field(default_factory=list)
    pages_created: int = 0
    near_duplicates: list[dict[str, Any]] = field(default_factory=list)


def _phash(data: bytes) -> str | None:
    try:
        return str(imagehash.phash(Image.open(io.BytesIO(data))))
    except Exception:
        return None


def find_near_duplicates(db: Session, phash: str | None, exclude_item: int | None) -> list[dict[str, Any]]:
    if not phash:
        return []
    target = imagehash.hex_to_hash(phash)
    out = []
    for pid, item_id, ph in db.execute(select(Page.id, Page.item_id, Page.phash).where(Page.phash.is_not(None))):
        if item_id == exclude_item:
            continue
        dist = target - imagehash.hex_to_hash(ph)
        if dist <= NEAR_DUP_HAMMING:
            out.append({"page_id": pid, "item_id": item_id, "hamming": int(dist)})
    return out


def create_item(db: Session, meta: dict[str, Any], rights: RightsRecord, actor: str) -> ArchivalItem:
    item = ArchivalItem(
        title=meta["title"],
        item_type=meta["item_type"],
        collection=meta["collection"],
        source_institution=meta.get("source_institution") or rights.source_institution,
        creator=meta.get("creator"),
        date_text=meta.get("date_text"),
        date_start=dt.date.fromisoformat(meta["date_start"]) if meta.get("date_start") else None,
        date_end=dt.date.fromisoformat(meta["date_end"]) if meta.get("date_end") else None,
        date_certainty=meta.get("date_certainty", "unknown"),
        original_languages=meta["languages"],
        scripts=meta.get("scripts") or ["Latn"],
        edition=meta.get("edition") or rights.edition,
        volume=meta.get("volume") or rights.volume,
        publisher=meta.get("publisher"),
        rights_record_id=rights.id,
        access_level=meta.get("access_level", AccessLevel.public.value),
        capture_details=meta.get("capture", {}),
        ndli_links=meta.get("ndli_links", []),
        is_fixture=bool(meta.get("is_fixture", rights.is_fixture)),
        created_by=actor,
    )
    db.add(item)
    db.flush()
    audit.record(db, actor, "item.intake", "archival_item", item.id,
                 detail={"title": item.title, "rights_source_key": rights.source_key})
    return item


def store_original(db: Session, item: ArchivalItem, data: bytes, name: str, actor: str,
                   expected_sha256: str | None = None) -> IntakeFileResult:
    digest = storage.sha256_bytes(data)
    if expected_sha256 and expected_sha256.lower() != digest:
        folder = storage.quarantine(data, name, f"checksum mismatch: expected {expected_sha256}, got {digest}")
        log.info("quarantined %s at %s", name, folder)
        audit.record(db, actor, "file.quarantine", "archival_item", item.id, detail={"name": name, "reason": "checksum"})
        # The quarantine folder is a server path; it stays in the log, not in the client-facing note.
        return IntakeFileResult(name, "quarantined", digest, "checksum mismatch; the file was quarantined")
    try:
        mime, ext = sniff_format(data)
    except IntakeRejected as exc:
        folder = storage.quarantine(data, name, str(exc))
        log.info("quarantined %s at %s", name, folder)
        audit.record(db, actor, "file.quarantine", "archival_item", item.id, detail={"name": name, "reason": str(exc)})
        return IntakeFileResult(name, "quarantined", digest, f"{exc}; the file was quarantined")
    existing = db.execute(
        select(FileVersion).where(FileVersion.sha256 == digest, FileVersion.role == "preservation_master")
    ).scalars().first()
    if existing is not None:
        audit.record(db, actor, "file.duplicate", "archival_item", item.id,
                     detail={"name": name, "sha256": digest, "existing_item": existing.item_id})
        return IntakeFileResult(name, "duplicate", digest,
                                f"exact duplicate of file {existing.id} (item {existing.item_id})", existing.id)
    stored = storage.put_bytes(data, "preservation_master", ext)
    fv = FileVersion(item_id=item.id, role="preservation_master", kind="original", format=mime,
                     byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri,
                     generator="intake", original_filename=name)
    db.add(fv)
    db.flush()
    audit.record(db, actor, "file.store_master", "file_version", fv.id, checksum_after=digest,
                 detail={"name": name, "format": mime, "bytes": stored.byte_size})
    return IntakeFileResult(name, "stored", digest, mime, fv.id)


def create_pages_for_file(db: Session, item: ArchivalItem, fv: FileVersion, data: bytes, doc_class: str,
                          language: str, start_seq: int, page_labels: list[str] | None) -> tuple[int, list[dict]]:
    """Create Page rows for an image or PDF master. Returns (count, near_duplicates)."""
    near: list[dict] = []
    created = 0
    labels = page_labels or []
    if fv.format == "application/pdf":
        n = len(PdfReader(io.BytesIO(data)).pages)
        for i in range(n):
            db.add(Page(item_id=item.id, sequence=start_seq + i, image_file_id=fv.id, doc_class=doc_class,
                        language=language, printed_page_label=labels[i] if i < len(labels) else None,
                        preprocessing_params={"pdf_page_index": i}, status=PageStatus.pending.value))
            created += 1
        db.flush()
        return created, near
    if not fv.format.startswith("image/"):
        return 0, near
    gray = load_gray(data)
    gutter = find_spread_gutter(gray) if doc_class == DocClass.printed.value else None
    halves = [None] if gutter is None else [0, 1]
    ph = _phash(data)
    dups = find_near_duplicates(db, ph, item.id)
    for h in halves:
        page = Page(item_id=item.id, sequence=start_seq + created, image_file_id=fv.id, doc_class=doc_class,
                    language=language, printed_page_label=labels[created] if created < len(labels) else None,
                    preprocessing_params={"spread_half": h, "split_at_x": gutter} if h is not None else {},
                    status=PageStatus.pending.value, phash=ph)
        if dups:
            page.quality_signals = {"near_duplicates": dups}
        db.add(page)
        created += 1
    if dups:
        near.extend(dups)
    db.flush()
    return created, near


def intake_item(db: Session, meta: dict[str, Any], files: list[tuple[str, bytes, str | None]], actor: str,
                page_labels: list[str] | None = None) -> IntakeResult:
    """Create an item from in-memory files: list of (name, bytes, expected_sha256|None)."""
    rights = db.execute(select(RightsRecord).where(RightsRecord.source_key == meta["rights_source_key"])).scalar_one_or_none()
    if rights is None:
        raise IntakeRejected("rights_source_key is not in the rights register; register rights before ingest")
    if rights.discovery_only:
        raise IntakeRejected("source is discovery/linking only; content may not be ingested")
    item = create_item(db, meta, rights, actor)
    result = IntakeResult(item_id=item.id)
    seq = 1
    language = meta["languages"][0]
    for name, data, expected in files:
        fr = store_original(db, item, data, name, actor, expected)
        result.files.append(fr)
        if fr.status != "stored":
            continue
        fv = db.get(FileVersion, fr.file_id)
        if meta["doc_class"] in (DocClass.printed.value, DocClass.handwritten.value, DocClass.born_digital.value):
            n, near = create_pages_for_file(db, item, fv, data, meta["doc_class"], language, seq, page_labels)
            seq += n
            result.pages_created += n
            result.near_duplicates.extend(near)
        elif meta["doc_class"] == DocClass.photograph.value:
            page = Page(item_id=item.id, sequence=seq, image_file_id=fv.id, doc_class=DocClass.photograph.value,
                        language=language, status=PageStatus.pending.value, review_mode="full",
                        phash=_phash(data))
            db.add(page)
            seq += 1
            result.pages_created += 1
    if meta["doc_class"] == DocClass.photograph.value:
        # Always a draft caption record: photo review (and so publication) needs one, even when the upload
        # form sent no caption. An empty caption cannot be approved.
        p = meta.get("photo") or {}
        db.add(PhotoMetadata(item_id=item.id, caption=p.get("caption") or "", people=p.get("people") or [],
                             place=p.get("place"), event=p.get("event"), date_text=p.get("date_text"),
                             date_certainty=p.get("date_certainty", "unknown"), photographer=p.get("photographer"),
                             source_reference=p.get("source_reference"), visible_text=p.get("visible_text"),
                             review_status="draft"))
    if meta["doc_class"] == DocClass.audio_video.value:
        for seg in meta.get("transcript_draft", []):
            db.add(MediaSegment(item_id=item.id, start_ms=int(seg["start_ms"]), end_ms=int(seg["end_ms"]),
                                speaker=seg.get("speaker"), transcript_text=seg["text"],
                                language=seg.get("language", language), review_status="draft"))
    db.flush()
    if all(f.status != "stored" for f in result.files) and files:
        item.publication_state = "draft"
    return result


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rights = {r.get("source_key"): r for r in manifest.get("rights", [])}
    for r in manifest.get("rights", []):
        errors += [f"{r.get('source_key')}: {e}" for e in validate_rights_entry(r)]
    for it in manifest.get("items", []):
        errors += [f"{it.get('item_key')}: {e}" for e in validate_item_entry(it, rights)]
    return errors


def fetch_permitted_url(url: str) -> bytes:
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def import_manifest(db: Session, manifest: dict[str, Any], base_dir: Path, actor: str,
                    only_items: set[str] | None = None) -> dict[str, Any]:
    """Validate the whole manifest, register rights, then ingest each item. Invalid items are rejected
    individually (reported), never partially imported."""
    report: dict[str, Any] = {"rights": [], "items": [], "rejected": []}
    rights = {r.get("source_key"): r for r in manifest.get("rights", [])}
    for r in manifest.get("rights", []):
        errs = validate_rights_entry(r)
        if errs:
            report["rejected"].append({"rights": r.get("source_key"), "errors": errs})
            continue
        rec = upsert_rights(db, r, actor)
        report["rights"].append({"source_key": rec.source_key, "display": rec.display_permission,
                                 "training": rec.training_permission})
    for it in manifest.get("items", []):
        if only_items and it["item_key"] not in only_items:
            continue
        errs = validate_item_entry(it, rights)
        if errs:
            report["rejected"].append({"item": it.get("item_key"), "errors": errs})
            continue
        already = db.execute(select(ArchivalItem.id).where(
            ArchivalItem.capture_details["item_key"].astext == it["item_key"])).scalar()
        if already:
            report["items"].append({"item_key": it["item_key"], "status": "already_imported", "item_id": already})
            continue
        files: list[tuple[str, bytes, str | None]] = []
        try:
            for f in it.get("files", []):
                if f.get("path"):
                    p = (base_dir / f["path"]).resolve()
                    files.append((p.name, p.read_bytes(), f.get("sha256")))
                elif f.get("url"):
                    files.append((f["url"].rsplit("/", 1)[-1], fetch_permitted_url(f["url"]), f.get("sha256")))
        except (OSError, httpx.HTTPError) as exc:
            report["rejected"].append({"item": it["item_key"], "errors": [f"file unavailable: {exc}"]})
            continue
        meta = dict(it)
        meta["capture"] = {**it.get("capture", {}), "item_key": it["item_key"]}
        res = intake_item(db, meta, files, actor, it.get("page_labels"))
        report["items"].append({"item_key": it["item_key"], "item_id": res.item_id, "pages": res.pages_created,
                                "files": [f.__dict__ for f in res.files], "near_duplicates": res.near_duplicates})
    return report
