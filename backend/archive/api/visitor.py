"""Visitor API: anonymous, read-only, published + rights-cleared only. Zero LLM calls except /ask."""

from __future__ import annotations

import datetime as dt
import io
import secrets
from typing import Annotated, Any

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import any_, func, literal, select
from sqlalchemy.orm import Session

from archive import constitution, exhibit, storage
from archive.ask.service import ask as run_ask
from archive.config import get_settings
from archive.db import get_db
from archive.ingest.publish import current_index_version, withdrawn_item_ids
from archive.models import (
    ArchivalItem,
    CollectionSetting,
    ConstitutionArticle,
    Derivative,
    FileVersion,
    KioskSync,
    KnowledgeEdge,
    KnowledgeNode,
    MediaSegment,
    Page,
    Passage,
    PhotoMetadata,
    QrCollection,
    RightsRecord,
    Story,
    SystemState,
    TimelineEvent,
    utcnow,
)
from archive.rights import (
    item_visible, passage_visible, visible_item, visible_item_ids, withdrawn_item,
    withdrawn_reason_category,
)
from archive.search.hybrid import (
    KIND_LABELS,
    SearchFilters,
    citation_label,
    hybrid_search,
    load_hits,
    photo_credit,
)
from archive.services import sarvam_text

router = APIRouter(prefix="/api/visitor", tags=["visitor"])
DB = Annotated[Session, Depends(get_db)]
LANGS = ("en", "hi", "mr")

PAGE_LABELS = {
    "text_layer": "Source text",
    "local": "Reviewed transcription",
    "sarvam": "Reviewed transcription",
    "manual": "Reviewed transcription",
    "none": "Reviewed caption",
}


def _rights_line(item: ArchivalItem) -> str:
    return item.rights.attribution


def _photo_card(item: ArchivalItem, photo: PhotoMetadata | None) -> dict[str, Any] | None:
    if photo is None or photo.review_status != "approved":
        return None
    first = item.pages[0] if item.pages else None
    return {"caption": photo.caption, "credit": photo_credit(photo),
            "image_file_id": first.delivery_file_id if first else None}


def _item_card(item: ArchivalItem, photo: PhotoMetadata | None = None) -> dict[str, Any]:
    return {"id": item.id, "title": item.title, "item_type": item.item_type, "collection": item.collection,
            "date_text": item.date_text, "date_certainty": item.date_certainty, "creator": item.creator,
            "languages": item.original_languages, "edition": item.edition, "volume": item.volume,
            "subjects": item.subjects or [], "people": item.people or [], "places": item.places or [],
            "is_fixture": item.is_fixture, "online_only": item.access_level == "public_online_only",
            "photo": _photo_card(item, photo)}


def _withdrawn_detail(item: ArchivalItem) -> dict[str, str]:
    return {"code": "item_withdrawn", "reason_category": withdrawn_reason_category(item),
            "message": "This item has been withdrawn."}


def _raise_if_withdrawn(db: Session, item_id: int | None) -> None:
    if item_id is None:
        return
    item = withdrawn_item(db, item_id)
    if item is not None:
        raise HTTPException(410, _withdrawn_detail(item))


def _file_visible(db: Session, file_id: int) -> FileVersion:
    fv = db.get(FileVersion, file_id)
    if fv is None or fv.role != "delivery" or fv.item_id is None:
        raise HTTPException(404, "not available")
    _raise_if_withdrawn(db, fv.item_id)
    if fv.deleted_at is not None:
        raise HTTPException(404, "not available")
    if visible_item(db, fv.item_id) is None:
        raise HTTPException(404, "not available")
    return fv


@router.get("/config")
def config(db: DB) -> dict[str, Any]:
    s = get_settings()
    mt = {c.collection: c.machine_translation_enabled for c in db.execute(select(CollectionSetting)).scalars()}
    fixtures = db.execute(select(func.count()).select_from(ArchivalItem).join(RightsRecord)
                          .where(item_visible(), ArchivalItem.is_fixture.is_(True))).scalar()
    return {"languages": list(LANGS), "ask_model_connected": s.llm_available,
            "machine_translation": {"available": s.sarvam_available and s.sarvam_translate_enabled, "collections": mt},
            "narration_live_available": s.sarvam_available and s.sarvam_tts_enabled,
            "fixture_items_visible": int(fixtures or 0), "index_version": current_index_version(db),
            "session_idle_seconds": 120, "lease_hours": s.exhibit_lease_hours}


@router.get("/home")
def home(db: DB) -> dict[str, Any]:
    counts = dict(db.execute(select(ArchivalItem.collection, func.count()).join(RightsRecord).where(item_visible())
                             .group_by(ArchivalItem.collection)).all())
    stories = db.execute(select(Story).where(Story.status == "approved")).scalars().all()
    return {"collections": [{"key": c, "count": counts.get(c, 0)} for c in
                            ("writings", "speeches", "debates", "manuscripts", "photographs", "audio_video")],
            "stories": [{"slug": st.slug, "titles": st.titles} for st in stories]}


@router.get("/items")
def list_items(db: DB, collection: str | None = None, item_type: str | None = None, subject: str | None = None,
               person: str | None = None, place: str | None = None,
               language: str | None = None) -> list[dict[str, Any]]:
    stmt = select(ArchivalItem).join(RightsRecord).where(item_visible()).order_by(ArchivalItem.date_start, ArchivalItem.id)
    if collection:
        stmt = stmt.where(ArchivalItem.collection == collection)
    if item_type:
        stmt = stmt.where(ArchivalItem.item_type == item_type)
    for value, column in ((subject, ArchivalItem.subjects), (person, ArchivalItem.people),
                          (place, ArchivalItem.places), (language, ArchivalItem.original_languages)):
        if value:
            stmt = stmt.where(literal(value) == any_(column))
    items = db.execute(stmt).scalars().all()
    photos = {p.item_id: p for p in db.execute(
        select(PhotoMetadata).where(PhotoMetadata.item_id.in_([i.id for i in items]))).scalars()} if items else {}
    return [_item_card(i, photos.get(i.id)) for i in items]


@router.get("/facets")
def facets(db: DB) -> dict[str, list[str]]:
    """Distinct staff-assigned tags on visible items only, for the browse and search filters."""
    out: dict[str, list[str]] = {}
    for name, col in (("subjects", ArchivalItem.subjects), ("people", ArchivalItem.people),
                      ("places", ArchivalItem.places)):
        tag = func.unnest(col).label("tag")
        sub = select(tag).select_from(ArchivalItem).join(RightsRecord).where(item_visible()).subquery()
        out[name] = sorted(set(db.execute(select(sub.c.tag).distinct()).scalars()))
    return out


@router.get("/items/{item_id}")
def item_detail(item_id: int, db: DB, lang: str = "en") -> dict[str, Any]:
    _raise_if_withdrawn(db, item_id)
    item = visible_item(db, item_id)
    if item is None:
        raise HTTPException(404, "This item is not available.")
    passages = db.execute(select(Passage).where(Passage.item_version_id == item.published_version_id,
                                                Passage.indexed.is_(True)).order_by(Passage.id)).scalars().all()
    by_page: dict[int, list[Passage]] = {}
    by_seg: dict[int, list[Passage]] = {}
    translations: dict[int, dict[str, dict[str, Any]]] = {}
    for p in passages:
        if p.kind == "reviewed_translation" and p.translation_of_id:
            translations.setdefault(p.translation_of_id, {})[p.language] = {"passage_id": p.id, "text": p.text}
        elif p.page_id:
            by_page.setdefault(p.page_id, []).append(p)
        elif p.media_segment_id:
            by_seg.setdefault(p.media_segment_id, []).append(p)

    def pdict(p: Passage) -> dict[str, Any]:
        return {"id": p.id, "text": p.text, "language": p.language, "kind": p.kind,
                "kind_label": KIND_LABELS.get(p.kind, p.kind), "quote_verified": p.quote_verified,
                "char_start": p.char_start, "bboxes": p.bboxes, "translations": translations.get(p.id, {})}

    page_articles, seg_articles = constitution.articles_by_anchor(db, item.id, lang if lang in LANGS else "en")
    pages = []
    for pg in item.pages:
        pages.append({"id": pg.id, "sequence": pg.sequence, "label": pg.printed_page_label or str(pg.sequence),
                      "image_file_id": pg.delivery_file_id,
                      "iiif": f"/iiif/{pg.delivery_file_id}/info.json" if pg.delivery_file_id else None,
                      "derivative_label": PAGE_LABELS.get(pg.ocr_route, "Reviewed transcription"),
                      "quote_verified": pg.quote_verified,
                      "citation": citation_label(item, pg, None),
                      "articles": page_articles.get(pg.id, []),
                      "passages": [pdict(p) for p in by_page.get(pg.id, [])]})
    segs = db.execute(select(MediaSegment).where(MediaSegment.item_id == item.id,
                                                 MediaSegment.review_status == "approved")
                      .order_by(MediaSegment.start_ms)).scalars().all()
    media = db.execute(select(FileVersion).where(FileVersion.item_id == item.id, FileVersion.role == "delivery",
                                                 FileVersion.kind == "media", FileVersion.deleted_at.is_(None))).scalar()
    summaries = db.execute(select(Derivative).where(Derivative.item_id == item.id, Derivative.kind == "summary",
                                                    Derivative.status == "approved")).scalars().all()
    narrations = db.execute(select(Derivative).where(Derivative.item_id == item.id, Derivative.kind == "narration",
                                                     Derivative.status == "approved")).scalars().all()
    photo = db.get(PhotoMetadata, item.id)
    related = _related(db, item.id)
    mt_enabled = db.get(CollectionSetting, item.collection)
    return {
        **_item_card(item),
        "source_institution": item.source_institution, "publisher": item.publisher,
        "date_certainty": item.date_certainty, "rights_line": _rights_line(item),
        "rights_holder": item.rights.rights_holder, "version": item.version,
        "provenance": {"source_institution": item.source_institution, "edition": item.edition,
                       "volume": item.volume, "publisher": item.publisher, "rights": _rights_line(item),
                       "capture": {k: v for k, v in (item.capture_details or {}).items() if k != "item_key"}},
        "pages": pages,
        "media": ({"file_id": media.id, "format": media.format, "captions": f"/api/visitor/items/{item.id}/captions.vtt",
                   "segments": [{"id": s.id, "start_ms": s.start_ms, "end_ms": s.end_ms, "speaker": s.speaker,
                                 "text": s.transcript_text, "quote_verified": s.quote_verified,
                                 "articles": seg_articles.get(s.id, []),
                                 "passages": [pdict(p) for p in by_seg.get(s.id, [])]} for s in segs],
                   "label": "Reviewed transcript"} if media else None),
        "photo": ({"caption": photo.caption, "people": photo.people, "place": photo.place, "event": photo.event,
                   "date_text": photo.date_text, "date_certainty": photo.date_certainty,
                   "photographer": photo.photographer, "source_reference": photo.source_reference,
                   "credit": photo_credit(photo), "label": "Reviewed caption"}
                  if photo and photo.review_status == "approved" else None),
        "summaries": [{"language": d.language, "text": d.content, "label": d.label_shown} for d in summaries],
        "narrations": [{"language": d.language, "file_id": d.file_id, "source_ids": d.source_ids,
                        "label": d.label_shown} for d in narrations],
        "related": related,
        "ndli_links": item.ndli_links,
        "machine_translation_enabled": mt_enabled.machine_translation_enabled if mt_enabled else True,
    }


def _related(db: Session, item_id: int) -> list[dict[str, Any]]:
    nodes = db.execute(select(KnowledgeNode).where(KnowledgeNode.status == "approved")).scalars().all()
    mine = {n.id for n in nodes if item_id in (n.item_ids or [])}
    if not mine:
        return []
    edges = db.execute(select(KnowledgeEdge).where(KnowledgeEdge.status == "approved")).scalars().all()
    neighbour_nodes = {e.to_node for e in edges if e.from_node in mine} | {e.from_node for e in edges if e.to_node in mine}
    ids: set[int] = set()
    for n in nodes:
        if n.id in neighbour_nodes | mine:
            ids.update(n.item_ids or [])
    ids.discard(item_id)
    vis = visible_item_ids(db, list(ids))
    items = db.execute(select(ArchivalItem).where(ArchivalItem.id.in_(vis))).scalars().all()
    return [_item_card(i) for i in items]


@router.get("/items/{item_id}/captions.vtt")
def captions(item_id: int, db: DB) -> Response:
    _raise_if_withdrawn(db, item_id)
    if visible_item(db, item_id) is None:
        raise HTTPException(404, "not available")
    segs = db.execute(select(MediaSegment).where(MediaSegment.item_id == item_id, MediaSegment.review_status == "approved")
                      .order_by(MediaSegment.start_ms)).scalars().all()

    def ts(ms: int) -> str:
        return f"{ms // 3600000:02d}:{(ms % 3600000) // 60000:02d}:{(ms % 60000) // 1000:02d}.{ms % 1000:03d}"

    body = "WEBVTT\n\n" + "\n".join(f"{ts(s.start_ms)} --> {ts(s.end_ms)}\n{s.transcript_text}\n" for s in segs)
    return Response(body, media_type="text/vtt")


@router.get("/files/{file_id}")
def file_download(file_id: int, db: DB) -> FileResponse:
    fv = _file_visible(db, file_id)
    return FileResponse(storage.resolve(fv.storage_uri), media_type=fv.format,
                        headers={"Cache-Control": "public, max-age=3600", "ETag": fv.sha256})


@router.get("/search")
def search(db: DB, q: Annotated[str, Query(min_length=1, max_length=300)], collection: str | None = None,
           item_type: str | None = None, lang: str | None = None, date_from: dt.date | None = None,
           date_to: dt.date | None = None, subject: str | None = None, person: str | None = None,
           place: str | None = None) -> dict[str, Any]:
    filters = SearchFilters(item_type=item_type, collection=collection, language=lang, date_from=date_from,
                            date_to=date_to, subject=subject, person=person, place=place)
    hits, info = hybrid_search(db, q, filters, limit=20)
    return {"query": q, "results": [h.as_dict() for h in hits], "info": info, "llm_calls": 0}


class AskBody(BaseModel):
    question: str = Field(max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)
    language: str = "en"
    session_id: str = Field(min_length=8, max_length=80)


@router.post("/ask")
def ask(body: AskBody, db: DB) -> dict[str, Any]:
    return run_ask(db, body.question, body.history, body.language if body.language in LANGS else "en",
                   body.session_id)


@router.get("/translate/{passage_id}")
def machine_translate(passage_id: int, lang: str, db: DB) -> dict[str, Any]:
    """On-demand machine translation: approved text of a published item only; not stored, not indexed,
    not citable; can be switched off per collection."""
    if lang not in LANGS:
        raise HTTPException(400, "unsupported language")
    hits = load_hits(db, [passage_id])
    if passage_id not in hits:
        raise HTTPException(404, "not available")
    hit = hits[passage_id]
    setting = db.get(CollectionSetting, hit.collection)
    if setting is not None and not setting.machine_translation_enabled:
        raise HTTPException(403, "Machine translation is switched off for this collection.")
    try:
        text, model = sarvam_text.translate(hit.text, hit.language, lang)
    except sarvam_text.ServiceUnavailable as exc:
        raise HTTPException(503, "Machine translation needs a connection to the translation service.") from exc
    row = db.get(SystemState, "mt_requests") or SystemState(key="mt_requests", value={})
    counts = dict(row.value)
    counts[f"{passage_id}:{lang}"] = counts.get(f"{passage_id}:{lang}", 0) + 1
    row.value = counts
    db.merge(row)
    db.commit()
    return {"passage_id": passage_id, "language": lang, "text": text, "provider": model,
            "label": "Machine translation — not reviewed", "stored": False, "citable": False}


@router.get("/timeline")
def timeline(db: DB) -> list[dict[str, Any]]:
    events = db.execute(select(TimelineEvent).where(TimelineEvent.status == "approved")
                        .order_by(TimelineEvent.sort_date)).scalars().all()
    out = []
    for e in events:
        vis = visible_item_ids(db, list(e.item_ids or []))
        if not vis:
            continue
        items = db.execute(select(ArchivalItem).where(ArchivalItem.id.in_(vis))).scalars().all()
        out.append({"id": e.id, "date_text": e.date_text, "sort_date": e.sort_date.isoformat(),
                    "date_certainty": e.date_certainty, "titles": e.titles, "descriptions": e.descriptions,
                    "items": [_item_card(i) for i in items]})
    return out


@router.get("/stories")
def stories(db: DB) -> list[dict[str, Any]]:
    return [{"slug": s.slug, "titles": s.titles, "blocks": len(s.blocks)}
            for s in db.execute(select(Story).where(Story.status == "approved")).scalars()]


@router.get("/stories/{slug}")
def story(slug: str, db: DB) -> dict[str, Any]:
    st = db.execute(select(Story).where(Story.slug == slug, Story.status == "approved")).scalar()
    if st is None:
        raise HTTPException(404, "not available")
    vis = visible_item_ids(db, [b["item_id"] for b in st.blocks])
    passage_ids = [b["passage_id"] for b in st.blocks if b.get("passage_id")]
    hits = load_hits(db, passage_ids)
    blocks = []
    for b in st.blocks:
        if b["item_id"] not in vis:
            continue
        item = db.get(ArchivalItem, b["item_id"])
        h = hits.get(b.get("passage_id")) if b.get("passage_id") else None
        first_page = item.pages[0] if item.pages else None
        blocks.append({"item": _item_card(item), "captions": b.get("captions", {}),
                       "image_file_id": first_page.delivery_file_id if first_page else None,
                       "passage": h.as_dict() if h else None,
                       "citation": h.citation if h else citation_label(item, first_page, None),
                       "deep_link": h.deep_link if h else f"/item/{item.id}"})
    narration = {}
    for lang_code, fid in (st.narration_file_ids or {}).items():
        try:
            _file_visible(db, fid)
            narration[lang_code] = fid
        except HTTPException:
            continue
    return {"slug": st.slug, "titles": st.titles, "blocks": blocks, "narration_file_ids": narration,
            "narration_label": "Synthetic narration"}


@router.get("/map")
def knowledge_map(db: DB) -> dict[str, Any]:
    nodes = db.execute(select(KnowledgeNode).where(KnowledgeNode.status == "approved")).scalars().all()
    all_items = {i for n in nodes for i in (n.item_ids or [])}
    vis = visible_item_ids(db, list(all_items))
    keep = [n for n in nodes if set(n.item_ids or []) & vis]
    keep_ids = {n.id for n in keep}
    edges = db.execute(select(KnowledgeEdge).where(KnowledgeEdge.status == "approved")).scalars().all()
    return {"nodes": [{"id": n.id, "type": n.node_type, "labels": n.labels, "description": n.description,
                       "item_ids": [i for i in (n.item_ids or []) if i in vis]} for n in keep],
            "edges": [{"id": e.id, "from": e.from_node, "to": e.to_node, "relation": e.relation}
                      for e in edges if e.from_node in keep_ids and e.to_node in keep_ids]}


@router.get("/constitution")
def constitution_index(db: DB) -> list[dict[str, Any]]:
    return constitution.article_index(db)


@router.get("/constitution/{number}")
def constitution_article(number: str, db: DB, lang: str = "en") -> dict[str, Any]:
    article = db.get(ConstitutionArticle, number)
    if article is None:
        raise HTTPException(404, "This article is not in the archive's curated list.")
    resolved = [(lk, p) for lk, p in constitution.resolved_links(db, constitution.active_links(db, article_number=number))
                if p is not None]
    hits = load_hits(db, [p.id for _, p in resolved])
    entries = []
    for lk, p in resolved:
        h = hits.get(p.id)
        if h is None:
            continue
        entries.append({"link_id": lk.id, "note": lk.note, "item": _item_card(db.get(ArchivalItem, lk.item_id)),
                        "passage": h.as_dict(), "citation": h.citation, "deep_link": h.deep_link})
    return {"number": article.number, "titles": article.titles, "part": article.part,
            "title": constitution.article_title(article, lang), "note": constitution.ARTICLE_NOTE,
            "entries": entries}


@router.get("/signage")
def signage(db: DB) -> dict[str, Any]:
    tl = timeline(db)
    sts = db.execute(select(Story).where(Story.status == "approved")).scalars().all()
    return {"timeline": tl, "story": story(sts[0].slug, db) if sts else None, "slide_seconds": 12}


class CollectionEntry(BaseModel):
    item_id: int
    passage_id: int | None = None
    page: int | None = None
    start_ms: int | None = None
    note: str | None = Field(default=None, max_length=200)


class CollectionBody(BaseModel):
    entries: list[CollectionEntry] = Field(min_length=1, max_length=30)
    language: str = "en"


def _qr_svg(url: str) -> str:
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


@router.post("/collections")
def create_collection(body: CollectionBody, db: DB) -> dict[str, Any]:
    s = get_settings()
    vis = visible_item_ids(db, [e.item_id for e in body.entries])
    entries = [e.model_dump() for e in body.entries if e.item_id in vis]
    if not entries:
        raise HTTPException(400, "none of these items are available")
    token = secrets.token_urlsafe(18)
    expires = utcnow() + dt.timedelta(hours=s.qr_link_ttl_hours)
    db.add(QrCollection(token=token, entries=entries, language=body.language, expires_at=expires))
    db.commit()
    url = f"{s.public_base_url.rstrip('/')}/c/{token}"
    return {"token": token, "url": url, "expires_at": expires.isoformat(), "qr_svg": _qr_svg(url),
            "count": len(entries)}


@router.get("/collections/{token}")
def get_collection(token: str, db: DB) -> dict[str, Any]:
    col = db.get(QrCollection, token)
    if col is None:
        raise HTTPException(404, "This collection link does not exist.")
    if col.expires_at < utcnow():
        raise HTTPException(410, "This collection link has expired.")
    vis = visible_item_ids(db, [e["item_id"] for e in col.entries])
    hits = load_hits(db, [e["passage_id"] for e in col.entries if e.get("passage_id")])
    out = []
    for e in col.entries:
        if e["item_id"] not in vis:
            continue  # withdrawn since the collection was made
        item = db.get(ArchivalItem, e["item_id"])
        h = hits.get(e.get("passage_id")) if e.get("passage_id") else None
        page = next((p for p in item.pages if p.sequence == e.get("page")), None) if e.get("page") else None
        start_ms = e.get("start_ms")
        seg = db.execute(select(MediaSegment).where(
            MediaSegment.item_id == item.id, MediaSegment.review_status == "approved",
            MediaSegment.start_ms == start_ms)).scalars().first() if start_ms is not None else None
        if h:
            link = h.deep_link
        elif start_ms is not None:
            link = f"/item/{item.id}?t={start_ms}"
        elif page is not None:
            link = f"/item/{item.id}?page={page.sequence}"
        else:
            link = f"/item/{item.id}"
        out.append({"item": _item_card(item), "rights_line": _rights_line(item),
                    "passage": h.as_dict() if h else None,
                    "citation": h.citation if h else citation_label(item, page, seg),
                    "deep_link": link, "start_ms": start_ms, "note": e.get("note")})
    return {"token": token, "expires_at": col.expires_at.isoformat(), "language": col.language, "entries": out,
            "removed_count": len(col.entries) - len(out)}


@router.get("/exhibit/manifest")
def exhibit_manifest(db: DB, request: Request, device_id: str = "unregistered") -> dict[str, Any]:
    rec = db.get(KioskSync, device_id) or KioskSync(device_id=device_id)
    manifest = exhibit.build_manifest(db, device_id)
    rec.last_sync_at = utcnow()
    rec.manifest_version = manifest["payload"]["manifest_version"]
    rec.user_agent = request.headers.get("user-agent", "")[:200]
    db.merge(rec)
    db.commit()
    return manifest


@router.get("/exhibit/public-key")
def exhibit_public_key() -> dict[str, str]:
    return {"alg": "ECDSA-P256-SHA256", "spki_b64": exhibit.public_key_spki_b64()}


@router.get("/withdrawals")
def withdrawals(db: DB) -> dict[str, Any]:
    return {"withdrawn_item_ids": withdrawn_item_ids(db), "index_version": current_index_version(db)}


@router.get("/passages/{passage_id}")
def passage(passage_id: int, db: DB) -> dict[str, Any]:
    row = db.get(Passage, passage_id)
    if row is not None:
        _raise_if_withdrawn(db, row.item_id)
    hits = load_hits(db, [passage_id])
    if passage_id not in hits:
        raise HTTPException(404, "not available")
    return hits[passage_id].as_dict()


@router.get("/narration/{passage_id}")
def narration_for(passage_id: int, db: DB, lang: str = "en") -> dict[str, Any]:
    row = db.get(Passage, passage_id)
    if row is not None:
        _raise_if_withdrawn(db, row.item_id)
    if passage_id not in load_hits(db, [passage_id]):
        raise HTTPException(404, "not available")
    rows = db.execute(select(Derivative).join(FileVersion, Derivative.file_id == FileVersion.id)
                      .where(Derivative.kind == "narration", Derivative.status == "approved",
                             Derivative.language == lang, FileVersion.deleted_at.is_(None))
                      .order_by(Derivative.id.desc())).scalars().all()
    for d in rows:
        if passage_id in (d.source_ids or []) and d.file_id:
            return {"file_id": d.file_id, "label": d.label_shown, "generator": d.generator}
    raise HTTPException(404, "No cached narration for this passage.")


def visible_passage_ids(db: Session) -> list[int]:
    return list(db.execute(select(Passage.id).join(ArchivalItem, Passage.item_id == ArchivalItem.id)
                           .join(RightsRecord, ArchivalItem.rights_record_id == RightsRecord.id)
                           .where(passage_visible())).scalars())


__all__ = ["router", "Page"]
