"""Descriptive-metadata versioning: every change bumps `metadata_version`, stores a before/after
revision, and writes an audit event. Used by the staff API and the fixture seeder."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from archive import audit
from archive.models import ArchivalItem, MetadataRevision

FIELDS = ("title", "subjects", "people", "places", "date_text", "date_start", "date_end", "date_certainty",
          "languages", "edition", "volume", "publisher", "creator")


def snapshot(item: ArchivalItem) -> dict[str, Any]:
    return {"title": item.title, "subjects": list(item.subjects or []), "people": list(item.people or []),
            "places": list(item.places or []), "date_text": item.date_text,
            "date_start": item.date_start.isoformat() if item.date_start else None,
            "date_end": item.date_end.isoformat() if item.date_end else None,
            "date_certainty": item.date_certainty, "languages": list(item.original_languages or []),
            "edition": item.edition, "volume": item.volume, "publisher": item.publisher, "creator": item.creator}


def record_revision(db: Session, item: ArchivalItem, before: dict[str, Any], actor: str, reason: str,
                    *, seeded: bool = False) -> MetadataRevision | None:
    """Call after changing the item; returns None when nothing changed."""
    after = snapshot(item)
    if after == before:
        return None
    item.metadata_version += 1
    rev = MetadataRevision(item_id=item.id, version=item.metadata_version, before=before, after=after,
                           actor=actor, reason=reason)
    db.add(rev)
    detail: dict[str, Any] = {"reason": reason, "fields": sorted(k for k in after if after[k] != before[k])}
    if seeded:
        detail["seeded_fixture"] = True
    audit.record(db, actor, "item.metadata.update", "archival_item", item.id, entity_version=item.metadata_version,
                 detail=detail)
    return rev
