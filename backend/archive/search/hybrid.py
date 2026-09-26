"""Hybrid retrieval over approved, published, rights-cleared passages (spec 5.2).

Keyword: PostgreSQL full-text (english config for English passages, simple otherwise).
Semantic: pgvector cosine distance over local multilingual embeddings.
Merge: reciprocal rank fusion. Optional local cross-encoder rerank for the Ask workflow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import and_, func, literal, select
from sqlalchemy.orm import Session

from archive.config import get_settings
from archive.models import ArchivalItem, MediaSegment, Page, Passage, RightsRecord
from archive.rights import passage_visible
from archive.search.models import get_embedder, get_reranker

RRF_K = 60

KIND_LABELS = {
    "source_text": "Source text",
    "reviewed_transcription": "Reviewed transcription",
    "reviewed_transcript": "Reviewed transcript",
    "reviewed_caption": "Reviewed caption",
    "reviewed_translation": "Reviewed translation",
}


@dataclass
class SearchFilters:
    item_type: str | None = None
    collection: str | None = None
    language: str | None = None
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class Hit:
    passage_id: int
    item_id: int
    text: str
    language: str
    kind: str
    kind_label: str
    quote_verified: bool
    title: str
    collection: str
    citation: str
    deep_link: str
    page_sequence: int | None = None
    start_ms: int | None = None
    keyword_rank: int | None = None
    semantic_rank: int | None = None
    rrf: float = 0.0
    rerank_score: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fmt_ms(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:d}:{s % 60:02d}"


def citation_label(item: ArchivalItem, page: Page | None, seg: MediaSegment | None) -> str:
    parts = [item.title]
    if item.edition:
        parts.append(item.edition)
    if item.volume:
        parts.append(f"Vol. {item.volume}")
    if page is not None:
        parts.append(f"p. {page.printed_page_label or page.sequence}")
    if seg is not None:
        parts.append(f"at {_fmt_ms(seg.start_ms)}")
    return ", ".join(parts)


def deep_link(item: ArchivalItem, page: Page | None, seg: MediaSegment | None, passage_id: int) -> str:
    if seg is not None:
        return f"/item/{item.id}?t={seg.start_ms}&passage={passage_id}"
    if page is not None:
        return f"/item/{item.id}?page={page.sequence}&passage={passage_id}"
    return f"/item/{item.id}?passage={passage_id}"


def _filtered(stmt, filters: SearchFilters):
    conds = []
    if filters.item_type:
        conds.append(ArchivalItem.item_type == filters.item_type)
    if filters.collection:
        conds.append(ArchivalItem.collection == filters.collection)
    if filters.language:
        conds.append(Passage.language == filters.language)
    if filters.date_from:
        conds.append(func.coalesce(ArchivalItem.date_end, ArchivalItem.date_start) >= filters.date_from)
    if filters.date_to:
        conds.append(func.coalesce(ArchivalItem.date_start, ArchivalItem.date_end) <= filters.date_to)
    return stmt.where(and_(*conds)) if conds else stmt


def _base():
    return select(Passage.id).select_from(Passage).join(ArchivalItem, Passage.item_id == ArchivalItem.id).join(
        RightsRecord, ArchivalItem.rights_record_id == RightsRecord.id
    ).where(passage_visible())


def keyword_ids(db: Session, query: str, filters: SearchFilters, limit: int) -> list[int]:
    q_en = func.websearch_to_tsquery(_regconfig("english"), query)
    q_simple = func.websearch_to_tsquery(_regconfig("simple"), query)
    tsq = q_en.op("||")(q_simple)
    rank = func.ts_rank_cd(Passage.tsv, tsq)
    stmt = _filtered(_base().where(Passage.tsv.op("@@")(tsq)), filters).order_by(rank.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


def _regconfig(name: str):
    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import REGCONFIG

    return cast(literal(name), REGCONFIG)


def semantic_ids(db: Session, query_vec: list[float], filters: SearchFilters, limit: int) -> list[int]:
    stmt = _filtered(_base().where(Passage.embedding.is_not(None)), filters).order_by(
        Passage.embedding.cosine_distance(query_vec)
    ).limit(limit)
    return list(db.execute(stmt).scalars())


def load_hits(db: Session, ids: list[int]) -> dict[int, Hit]:
    if not ids:
        return {}
    rows = db.execute(
        select(Passage, ArchivalItem, Page, MediaSegment)
        .join(ArchivalItem, Passage.item_id == ArchivalItem.id)
        .join(RightsRecord, ArchivalItem.rights_record_id == RightsRecord.id)
        .outerjoin(Page, Passage.page_id == Page.id)
        .outerjoin(MediaSegment, Passage.media_segment_id == MediaSegment.id)
        .where(Passage.id.in_(ids), passage_visible())
    ).all()
    out = {}
    for p, item, page, seg in rows:
        out[p.id] = Hit(
            passage_id=p.id, item_id=item.id, text=p.text, language=p.language, kind=p.kind,
            kind_label=KIND_LABELS.get(p.kind, p.kind), quote_verified=p.quote_verified, title=item.title,
            collection=item.collection, citation=citation_label(item, page, seg),
            deep_link=deep_link(item, page, seg, p.id),
            page_sequence=page.sequence if page else None, start_ms=seg.start_ms if seg else None,
            extra={"edition": item.edition, "volume": item.volume, "is_fixture": item.is_fixture,
                   "translation_of_id": p.translation_of_id},
        )
    return out


def hybrid_search(db: Session, query: str, filters: SearchFilters | None = None, *, limit: int | None = None,
                  rerank: bool = False) -> tuple[list[Hit], dict[str, Any]]:
    s = get_settings()
    filters = filters or SearchFilters()
    pool = s.retrieval_candidate_k
    kw = keyword_ids(db, query, filters, pool)
    sem = semantic_ids(db, get_embedder().embed_query(query), filters, pool)
    scores: dict[int, float] = {}
    for rank, pid in enumerate(kw):
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, pid in enumerate(sem):
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + rank + 1)
    ordered = sorted(scores, key=lambda pid: scores[pid], reverse=True)[:pool]
    hits_by_id = load_hits(db, ordered)
    hits = []
    for pid in ordered:
        if pid not in hits_by_id:
            continue
        h = hits_by_id[pid]
        h.rrf = round(scores[pid], 6)
        h.keyword_rank = kw.index(pid) + 1 if pid in kw else None
        h.semantic_rank = sem.index(pid) + 1 if pid in sem else None
        hits.append(h)
    info: dict[str, Any] = {"keyword_candidates": len(kw), "semantic_candidates": len(sem), "fused": len(hits)}
    if rerank and hits:
        rr = get_reranker()
        rs = rr.score(query, [h.text[: s.passage_max_chars] for h in hits])
        for h, sc in zip(hits, rs, strict=True):
            h.rerank_score = sc
        hits.sort(key=lambda h: h.rerank_score or 0.0, reverse=True)
        info["reranker"] = rr.name
    default_limit = s.retrieval_top_k if rerank else 20
    return hits[: limit or default_limit], info
