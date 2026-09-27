"""Relational schema refined from spec section 7.2.

The metadata database is the system of record for item, page, review and publication state.
LangGraph checkpoints only hold workflow position; Langfuse only holds redacted traces.
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 384


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _enum_check(column: str, values: type[enum.StrEnum]) -> CheckConstraint:
    allowed = ", ".join(f"'{v.value}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"ck_{column}_values")


class Permission(enum.StrEnum):
    allowed = "allowed"
    not_allowed = "not_allowed"
    unknown = "unknown"


class AccessLevel(enum.StrEnum):
    public = "public"  # may be shown and cached on kiosks
    public_online_only = "public_online_only"  # rights-sensitive: shown online, never cached
    restricted = "restricted"  # staff only


class ItemType(enum.StrEnum):
    text = "text"
    printed_scan = "printed_scan"
    manuscript = "manuscript"
    photograph = "photograph"
    audio = "audio"
    video = "video"


class Collection(enum.StrEnum):
    writings = "writings"
    speeches = "speeches"
    debates = "debates"
    manuscripts = "manuscripts"
    photographs = "photographs"
    audio_video = "audio_video"


class PublicationState(enum.StrEnum):
    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    staged = "staged"
    published = "published"
    withdrawn = "withdrawn"


class DocClass(enum.StrEnum):
    born_digital = "born_digital"
    printed = "printed"
    handwritten = "handwritten"
    photograph = "photograph"
    audio_video = "audio_video"


class OcrRoute(enum.StrEnum):
    text_layer = "text_layer"
    local = "local"
    sarvam = "sarvam"
    manual = "manual"
    none = "none"


class PageStatus(enum.StrEnum):
    pending = "pending"
    ocr_done = "ocr_done"
    needs_full_review = "needs_full_review"
    sarvam_pending = "sarvam_pending"
    manual_transcription = "manual_transcription"
    in_batch_review = "in_batch_review"
    approved = "approved"
    rejected = "rejected"


class RightsRecord(Base):
    """Collection and rights register (spec 8.1). One row per source/edition relied on."""

    __tablename__ = "rights_record"
    __table_args__ = (
        _enum_check("display_permission", Permission),
        _enum_check("training_permission", Permission),
        _enum_check("external_processing", Permission),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_institution: Mapped[str] = mapped_column(Text)
    edition: Mapped[str | None] = mapped_column(Text)
    volume: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[str | None] = mapped_column(Text)
    rights_holder: Mapped[str] = mapped_column(Text)
    basis_for_use: Mapped[str] = mapped_column(Text)
    display_permission: Mapped[str] = mapped_column(String(20), default=Permission.unknown)
    training_permission: Mapped[str] = mapped_column(String(20), default=Permission.unknown)
    training_basis: Mapped[str | None] = mapped_column(Text)
    external_processing: Mapped[str] = mapped_column(String(20), default=Permission.unknown)
    evidence: Mapped[str] = mapped_column(Text)
    attribution: Mapped[str] = mapped_column(Text)
    date_checked: Mapped[dt.date] = mapped_column()
    checked_by: Mapped[str] = mapped_column(Text)
    discovery_only: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StaffUser(Base):
    __tablename__ = "staff_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(30)))
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(5)), default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ArchivalItem(Base):
    __tablename__ = "archival_item"
    __table_args__ = (
        _enum_check("item_type", ItemType),
        _enum_check("collection", Collection),
        _enum_check("access_level", AccessLevel),
        _enum_check("publication_state", PublicationState),
        Index("ix_archival_item_subjects", "subjects", postgresql_using="gin"),
        Index("ix_archival_item_people", "people", postgresql_using="gin"),
        Index("ix_archival_item_places", "places", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    item_type: Mapped[str] = mapped_column(String(20))
    collection: Mapped[str] = mapped_column(String(20))
    source_institution: Mapped[str] = mapped_column(Text)
    creator: Mapped[str | None] = mapped_column(Text)
    date_text: Mapped[str | None] = mapped_column(Text)
    date_start: Mapped[dt.date | None] = mapped_column()
    date_end: Mapped[dt.date | None] = mapped_column()
    date_certainty: Mapped[str] = mapped_column(String(20), default="unknown")
    original_languages: Mapped[list[str]] = mapped_column(ARRAY(String(5)))
    scripts: Mapped[list[str]] = mapped_column(ARRAY(String(10)))
    edition: Mapped[str | None] = mapped_column(Text)
    volume: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    rights_record_id: Mapped[int] = mapped_column(ForeignKey("rights_record.id"))
    access_level: Mapped[str] = mapped_column(String(30), default=AccessLevel.public)
    publication_state: Mapped[str] = mapped_column(String(20), default=PublicationState.draft)
    published_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("item_version.id", use_alter=True, name="fk_item_published_version")
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    capture_details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ndli_links: Mapped[list[Any]] = mapped_column(default=list)
    subjects: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    people: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    places: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    metadata_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)

    rights: Mapped[RightsRecord] = relationship(lazy="joined")
    pages: Mapped[list[Page]] = relationship(
        back_populates="item", order_by="Page.sequence", foreign_keys="Page.item_id"
    )


class MetadataRevision(Base):
    """One row per descriptive-metadata edit; before/after snapshots make every version recoverable."""

    __tablename__ = "metadata_revision"
    __table_args__ = (UniqueConstraint("item_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("archival_item.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    before: Mapped[dict[str, Any]] = mapped_column()
    after: Mapped[dict[str, Any]] = mapped_column()
    actor: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemVersion(Base):
    __tablename__ = "item_version"
    __table_args__ = (UniqueConstraint("item_id", "version_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("archival_item.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="staging")  # staging|staged|published|superseded|failed|withdrawn
    verification: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cleaned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class FileVersion(Base):
    __tablename__ = "file_version"
    __table_args__ = (Index("ix_file_sha_role", "sha256", "role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("archival_item.id", ondelete="SET NULL"))
    page_id: Mapped[int | None] = mapped_column(ForeignKey("page.id", ondelete="SET NULL"))
    role: Mapped[str] = mapped_column(String(30))  # preservation_master | delivery | derivative
    kind: Mapped[str] = mapped_column(String(40), default="file")  # page_image, hocr, audio, narration, ...
    format: Mapped[str] = mapped_column(String(80))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_uri: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    derived_from_id: Mapped[int | None] = mapped_column(ForeignKey("file_version.id"))
    generator: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewBatch(Base):
    """Sampled review of pages that passed the local OCR gate (spec 4.5)."""

    __tablename__ = "review_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("archival_item.id", ondelete="CASCADE"))
    page_ids: Mapped[list[Any]] = mapped_column(default=list)
    sample_page_ids: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | passed | failed
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Page(Base):
    __tablename__ = "page"
    __table_args__ = (
        UniqueConstraint("item_id", "sequence"),
        _enum_check("doc_class", DocClass),
        _enum_check("ocr_route", OcrRoute),
        _enum_check("status", PageStatus),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("archival_item.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    printed_page_label: Mapped[str | None] = mapped_column(String(40))
    image_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_version.id", use_alter=True, name="fk_page_image_file")
    )
    delivery_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_version.id", use_alter=True, name="fk_page_delivery_file")
    )
    doc_class: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(5), default="en")
    preprocessing_params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ocr_route: Mapped[str] = mapped_column(String(20), default=OcrRoute.none)
    gate_version: Mapped[str | None] = mapped_column(String(40))
    quality_signals: Mapped[dict[str, Any]] = mapped_column(default=dict)
    gate_passed: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(30), default=PageStatus.pending)
    review_mode: Mapped[str | None] = mapped_column(String(10))  # full | sampled
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("review_batch.id"))
    review_priority: Mapped[float] = mapped_column(Float, default=0.0)
    phash: Mapped[str | None] = mapped_column(String(32))
    approved_text: Mapped[str | None] = mapped_column(Text)
    approved_text_version: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    quote_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    quote_verified_by: Mapped[str | None] = mapped_column(Text)
    quote_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    sarvam_attempts: Mapped[int] = mapped_column(Integer, default=0)
    sarvam_last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[ArchivalItem] = relationship(back_populates="pages", foreign_keys=[item_id])
    ocr_results: Mapped[list[OcrResult]] = relationship(back_populates="page", order_by="OcrResult.id")


class OcrResult(Base):
    __tablename__ = "ocr_result"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("page.id", ondelete="CASCADE"))
    engine: Mapped[str] = mapped_column(String(40))  # tesseract | sarvam-doc-ai | text_layer | manual
    engine_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | failed
    text: Mapped[str] = mapped_column(Text, default="")
    hocr_file_id: Mapped[int | None] = mapped_column(ForeignKey("file_version.id"))
    words: Mapped[list[Any]] = mapped_column(default=list)  # [{t, c, bbox:[x0,y0,x1,y1]}]
    mean_confidence: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    raw_meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    page: Mapped[Page] = relationship(back_populates="ocr_results")


class MediaSegment(Base):
    __tablename__ = "media_segment"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("archival_item.id", ondelete="CASCADE"))
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str | None] = mapped_column(Text)
    transcript_text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(5))
    review_status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|rejected
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    quote_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    quote_verified_by: Mapped[str | None] = mapped_column(Text)
    quote_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    draft_engine: Mapped[str | None] = mapped_column(Text)  # machine speech-to-text that drafted it; None = person
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("file_version.id", ondelete="SET NULL"))


class PhotoMetadata(Base):
    __tablename__ = "photo_metadata"

    item_id: Mapped[int] = mapped_column(ForeignKey("archival_item.id", ondelete="CASCADE"), primary_key=True)
    caption: Mapped[str] = mapped_column(Text)
    people: Mapped[list[Any]] = mapped_column(default=list)
    place: Mapped[str | None] = mapped_column(Text)
    event: Mapped[str | None] = mapped_column(Text)
    date_text: Mapped[str | None] = mapped_column(Text)
    date_certainty: Mapped[str] = mapped_column(String(20), default="unknown")
    photographer: Mapped[str | None] = mapped_column(Text)
    source_reference: Mapped[str | None] = mapped_column(Text)
    visible_text: Mapped[str | None] = mapped_column(Text)  # banner OCR, stored separately from caption
    review_status: Mapped[str] = mapped_column(String(20), default="draft")
    reviewed_by: Mapped[str | None] = mapped_column(Text)


class Passage(Base):
    """Approved, citable text unit. Immutable once approved; corrections create new versions."""

    __tablename__ = "passage"
    __table_args__ = (
        Index("ix_passage_tsv", "tsv", postgresql_using="gin"),
        Index("ix_passage_item_version", "item_id", "item_version_id"),
        CheckConstraint("(page_id IS NOT NULL) OR (media_segment_id IS NOT NULL) OR kind = 'reviewed_caption'",
                        name="ck_passage_anchor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("archival_item.id", ondelete="CASCADE"))
    item_version_id: Mapped[int] = mapped_column(ForeignKey("item_version.id", ondelete="CASCADE"))
    page_id: Mapped[int | None] = mapped_column(ForeignKey("page.id"))
    media_segment_id: Mapped[int | None] = mapped_column(ForeignKey("media_segment.id"))
    kind: Mapped[str] = mapped_column(String(30))  # source_text | reviewed_transcription | reviewed_transcript | reviewed_caption | reviewed_translation
    translation_of_id: Mapped[int | None] = mapped_column(ForeignKey("passage.id"))
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    bboxes: Mapped[list[Any]] = mapped_column(default=list)
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64))
    text_version: Mapped[int] = mapped_column(Integer, default=1)
    language: Mapped[str] = mapped_column(String(5))
    quote_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    quote_verifier: Mapped[str | None] = mapped_column(Text)
    quote_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    review_basis: Mapped[str] = mapped_column(String(30))  # full_review | sampled_batch | spot_check
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    indexed: Mapped[bool] = mapped_column(Boolean, default=True)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector(CASE WHEN language = 'en' THEN 'english'::regconfig ELSE 'simple'::regconfig END, text)",
            persisted=True,
        ),
    )


class Translation(Base):
    __tablename__ = "translation"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_passage_id: Mapped[int | None] = mapped_column(ForeignKey("passage.id"))
    source_field: Mapped[str | None] = mapped_column(Text)  # e.g. story:1:title
    target_language: Mapped[str] = mapped_column(String(5))
    text: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(10))  # machine | human
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="unreviewed")  # unreviewed|approved|rejected
    reviewer: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Derivative(Base):
    __tablename__ = "derivative"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # summary | narration | caption_draft | entity_proposal
    item_id: Mapped[int | None] = mapped_column(ForeignKey("archival_item.id", ondelete="CASCADE"))
    source_ids: Mapped[list[Any]] = mapped_column(default=list)
    language: Mapped[str] = mapped_column(String(5))
    content: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("file_version.id"))
    generator: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved | rejected
    label_shown: Mapped[str] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewDecision(Base):
    __tablename__ = "review_decision"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))  # approve | correct | reject | escalate | verify_quote
    before: Mapped[str | None] = mapped_column(Text)
    after: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30))
    is_seeded_fixture: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnswerLog(Base):
    __tablename__ = "answer_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_hash: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(5))
    question_ref: Mapped[str] = mapped_column(Text)  # hash or PII-scrubbed text
    passages_retrieved: Mapped[list[Any]] = mapped_column(default=list)
    outcome: Mapped[str] = mapped_column(String(20))  # answered | extractive | insufficient | refused | error
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    index_version: Mapped[int] = mapped_column(Integer)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    provider_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    retried_retrieval: Mapped[bool] = mapped_column(Boolean, default=False)
    validation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    trace_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Citation(Base):
    __tablename__ = "citation"

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("answer_log.id", ondelete="CASCADE"))
    passage_id: Mapped[int] = mapped_column(ForeignKey("passage.id"))
    quoted_span: Mapped[str | None] = mapped_column(Text)
    span_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    display_label: Mapped[str] = mapped_column(Text)
    deep_link: Mapped[str] = mapped_column(Text)


class AnswerCache(Base):
    __tablename__ = "answer_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    index_version: Mapped[int] = mapped_column(Integer)
    prompt_version: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column()
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeNode(Base):
    __tablename__ = "knowledge_node"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_type: Mapped[str] = mapped_column(String(30))
    labels: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"en": .., "hi": .., "mr": ..}
    description: Mapped[str | None] = mapped_column(Text)
    item_ids: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | approved | rejected
    approved_by: Mapped[str | None] = mapped_column(Text)


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edge"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_node: Mapped[int] = mapped_column(ForeignKey("knowledge_node.id", ondelete="CASCADE"))
    to_node: Mapped[int] = mapped_column(ForeignKey("knowledge_node.id", ondelete="CASCADE"))
    relation: Mapped[str] = mapped_column(String(40))
    evidence_passage_ids: Mapped[list[Any]] = mapped_column(default=list)
    evidence_item_ids: Mapped[list[Any]] = mapped_column(default=list)
    proposed_by: Mapped[str] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="proposed")


class TimelineEvent(Base):
    __tablename__ = "timeline_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    date_text: Mapped[str] = mapped_column(Text)
    sort_date: Mapped[dt.date] = mapped_column()
    date_certainty: Mapped[str] = mapped_column(String(20), default="exact")
    titles: Mapped[dict[str, Any]] = mapped_column(default=dict)
    descriptions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    item_ids: Mapped[list[Any]] = mapped_column(default=list)
    node_ids: Mapped[list[Any]] = mapped_column(default=list)
    curator: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved


class Story(Base):
    __tablename__ = "story"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    titles: Mapped[dict[str, Any]] = mapped_column(default=dict)
    blocks: Mapped[list[Any]] = mapped_column(default=list)  # [{item_id, passage_id?, captions:{lang:..}}]
    narration_file_ids: Mapped[dict[str, Any]] = mapped_column(default=dict)
    curator: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")


class ConstitutionArticle(Base):
    """Curated list of Constitution articles that debate passages can be linked to."""

    __tablename__ = "constitution_article"

    number: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. "17", "15(4)", "21A"
    titles: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"en": .., "hi": .., "mr": ..}
    part: Mapped[str | None] = mapped_column(String(20))
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConstitutionLink(Base):
    """Curator-made link from an approved passage to a Constitution article. Anchored to the page or media
    segment (plus the passage's text hash) so it survives republication, which creates new passage ids.
    Removal is a soft delete so the curation history stays auditable."""

    __tablename__ = "constitution_link"
    __table_args__ = (
        CheckConstraint("(page_id IS NOT NULL) OR (media_segment_id IS NOT NULL)", name="ck_constitution_link_anchor"),
        Index("ix_constitution_link_article", "article_number"),
        Index("ix_constitution_link_item", "item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    article_number: Mapped[str] = mapped_column(ForeignKey("constitution_article.number"))
    item_id: Mapped[int] = mapped_column(ForeignKey("archival_item.id", ondelete="CASCADE"))
    page_id: Mapped[int | None] = mapped_column(ForeignKey("page.id", ondelete="CASCADE"))
    media_segment_id: Mapped[int | None] = mapped_column(ForeignKey("media_segment.id", ondelete="CASCADE"))
    passage_id: Mapped[int | None] = mapped_column(ForeignKey("passage.id", ondelete="SET NULL"))
    text_hash: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[str | None] = mapped_column(Text)
    removal_reason: Mapped[str | None] = mapped_column(Text)


class CollectionSetting(Base):
    __tablename__ = "collection_setting"

    collection: Mapped[str] = mapped_column(String(20), primary_key=True)
    machine_translation_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditEvent(Base):
    """Append-only (enforced by trigger) and hash-chained audit log."""

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(Text)
    entity_version: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    checksum_before: Mapped[str | None] = mapped_column(String(64))
    checksum_after: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    row_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DatasetVersion(Base):
    __tablename__ = "dataset_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    manifest: Mapped[dict[str, Any]] = mapped_column()
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(5)))
    item_count: Mapped[int] = mapped_column(Integer)
    passage_count: Mapped[int] = mapped_column(Integer)
    permission_summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    split_definition: Mapped[dict[str, Any]] = mapped_column(default=dict)
    gate_report: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="frozen")  # frozen | superseded | flagged
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrainingExample(Base):
    __tablename__ = "training_example"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_version.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(5))
    origin: Mapped[str] = mapped_column(String(30))  # human | synthetic_reviewed
    positive_passage_ids: Mapped[list[Any]] = mapped_column(default=list)
    hard_negative_passage_ids: Mapped[list[Any]] = mapped_column(default=list)
    hard_negative_status: Mapped[str] = mapped_column(String(20), default="unreviewed")
    split: Mapped[str | None] = mapped_column(String(10))
    group_key: Mapped[str] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HardNegativeCandidate(Base):
    """A passage the base retriever ranked high for a labelled question but that is not labelled relevant.
    It becomes a hard negative only after a person confirms it (spec 7.3 step 2)."""

    __tablename__ = "hard_negative_candidate"
    __table_args__ = (
        UniqueConstraint("training_example_id", "passage_id"),
        CheckConstraint("status IN ('candidate', 'confirmed', 'false_negative', 'rejected')",
                        name="ck_hard_negative_status"),
        Index("ix_hard_negative_candidate_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    training_example_id: Mapped[int] = mapped_column(ForeignKey("training_example.id", ondelete="CASCADE"))
    passage_id: Mapped[int] = mapped_column(ForeignKey("passage.id", ondelete="CASCADE"))
    text_sha256: Mapped[str] = mapped_column(String(64))
    relation: Mapped[str] = mapped_column(String(20))  # same_item | same_work | other_work
    retriever: Mapped[str] = mapped_column(Text)
    rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    provenance: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    mined_by: Mapped[str] = mapped_column(Text)
    mined_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)


class ModelVersion(Base):
    __tablename__ = "model_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(20))  # retriever | reranker
    name: Mapped[str] = mapped_column(Text)
    base_model: Mapped[str] = mapped_column(Text)
    dataset_version_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_version.id"))
    training_config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    code_commit: Mapped[str | None] = mapped_column(Text)
    evaluation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    size: Mapped[dict[str, Any]] = mapped_column(default=dict)
    weights_uri: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # candidate|active|retired|flagged
    index_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    """Postgres-backed work queue (SELECT ... FOR UPDATE SKIP LOCKED); no extra broker service."""

    __tablename__ = "job"
    __table_args__ = (Index("ix_job_ready", "status", "run_after"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    priority: Mapped[int] = mapped_column(Integer, default=100)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class QrCollection(Base):
    __tablename__ = "qr_collection"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    entries: Mapped[list[Any]] = mapped_column(default=list)
    language: Mapped[str] = mapped_column(String(5), default="en")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class SystemState(Base):
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KioskSync(Base):
    __tablename__ = "kiosk_sync"

    device_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_sync_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    manifest_version: Mapped[int | None] = mapped_column(Integer)
    user_agent: Mapped[str | None] = mapped_column(Text)
