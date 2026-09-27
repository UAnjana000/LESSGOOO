"""Recordings: transcript segment review drives item state; quote verification needs a person and the audio."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from archive import storage
from archive.ingest import publish, review
from archive.models import ArchivalItem, FileVersion, MediaSegment, Passage

from .factories import make_rights

pytestmark = pytest.mark.db


def _audio_item(db, rights) -> tuple[ArchivalItem, list[MediaSegment]]:
    item = ArchivalItem(title="Synthetic talk", item_type="audio", collection="audio_video",
                        source_institution="Synthetic test source", original_languages=["en"], scripts=["Latn"],
                        rights_record_id=rights.id, access_level="public", created_by="tester", is_fixture=True,
                        capture_details={"item_key": "synthetic-talk", "work_key": "synthetic-talk"})
    db.add(item)
    db.flush()
    stored = storage.put_bytes(b"fLaC synthetic audio bytes", "delivery", ".flac")
    db.add(FileVersion(item_id=item.id, role="delivery", kind="media", format="audio/flac",
                       byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri))
    segs = [MediaSegment(item_id=item.id, start_ms=i * 4000, end_ms=(i + 1) * 4000, language="en",
                         transcript_text=f"Synthetic segment {i} about the reading room.") for i in range(2)]
    db.add_all(segs)
    db.flush()
    review._update_item_state(db, item)
    return item, segs


def test_item_becomes_approved_only_after_every_segment_is_approved(db):
    # Arrange
    item, segs = _audio_item(db, make_rights(db))
    assert item.publication_state == "in_review"

    # Act / Assert
    review.review_segment(db, segs[0], "approve", "archivist@test")
    assert item.publication_state == "in_review"
    review.review_segment(db, segs[1], "correct", "archivist@test", text="Corrected synthetic segment one.")
    assert item.publication_state == "approved"
    assert review.item_ready_for_publication(db, item) == (True, [])


def test_rejected_segment_blocks_publication(db):
    item, segs = _audio_item(db, make_rights(db))
    review.review_segment(db, segs[0], "approve", "archivist@test")
    review.review_segment(db, segs[1], "reject", "archivist@test", reason="inaudible")

    ok, problems = review.item_ready_for_publication(db, item)

    assert not ok
    assert any("rejected" in p for p in problems)
    assert item.publication_state == "in_review"


def test_segment_quote_verification_needs_confirmation_and_approval(db):
    _, segs = _audio_item(db, make_rights(db))

    with pytest.raises(review.ReviewError):
        review.verify_segment_quotes(db, segs[0], "archivist@test", True)  # still draft
    review.review_segment(db, segs[0], "approve", "archivist@test")
    with pytest.raises(review.ReviewError):
        review.verify_segment_quotes(db, segs[0], "archivist@test", False)  # no confirmation

    review.verify_segment_quotes(db, segs[0], "archivist@test", True)
    assert segs[0].quote_verified and segs[0].quote_verified_by == "archivist@test"


def test_publication_verification_requires_the_media_delivery_copy(db):
    item, segs = _audio_item(db, make_rights(db))
    for s in segs:
        review.review_segment(db, s, "approve", "archivist@test")
    media = db.execute(select(FileVersion).where(FileVersion.item_id == item.id)).scalar_one()
    media.sha256 = "0" * 64

    with pytest.raises(publish.PublicationError, match="media delivery copy"):
        publish.publish_item(db, item, "archivist@test")
    assert item.published_version_id is None


def test_published_transcript_passages_carry_segment_quote_status(db):
    item, segs = _audio_item(db, make_rights(db))
    for s in segs:
        review.review_segment(db, s, "approve", "archivist@test")
    review.verify_segment_quotes(db, segs[0], "archivist@test", True)

    publish.publish_item(db, item, "archivist@test")

    passages = db.execute(select(Passage).where(Passage.item_version_id == item.published_version_id)).scalars().all()
    by_seg = {p.media_segment_id: p for p in passages}
    assert set(by_seg) == {segs[0].id, segs[1].id}
    assert by_seg[segs[0].id].quote_verified is True
    assert by_seg[segs[1].id].quote_verified is False
    assert all(p.kind == "reviewed_transcript" for p in passages)


def test_seed_media_delivery_replaces_a_bad_copy_but_publication_still_waits_for_review(db):
    from archive.cli import SEED, _seed_media_delivery

    item, segs = _audio_item(db, make_rights(db))
    master = storage.put_bytes(b"fLaC synthetic master bytes", "preservation_master", ".flac")
    db.add(FileVersion(item_id=item.id, role="preservation_master", kind="original", format="audio/flac",
                       byte_size=master.byte_size, sha256=master.sha256, storage_uri=master.uri))
    bad = db.execute(select(FileVersion).where(FileVersion.item_id == item.id,
                                               FileVersion.role == "delivery")).scalar_one()
    bad.sha256 = "0" * 64
    review.review_segment(db, segs[0], "approve", SEED, seeded=True)

    assert _seed_media_delivery(db) == {"synthetic-talk": "stored"}
    live = db.execute(select(FileVersion).where(
        FileVersion.item_id == item.id, FileVersion.role == "delivery",
        FileVersion.deleted_at.is_(None))).scalar_one()
    assert live.sha256 == master.sha256 and storage.verify(live.storage_uri, live.sha256)
    assert bad.deleted_at is not None
    with pytest.raises(publish.PublicationError, match="segment"):
        publish.publish_item(db, item, SEED)

    review.review_segment(db, segs[1], "approve", SEED, seeded=True)
    publish.publish_item(db, item, SEED)
    assert item.publication_state == "published"
