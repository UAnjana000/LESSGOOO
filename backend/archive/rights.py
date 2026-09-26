"""Server-side rights and publication filter.

Every visitor query, index lookup, citation, QR page and kiosk cache build goes through these
predicates. Rights live in the rights register; changing a register row takes effect immediately.
"""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from archive.models import AccessLevel, ArchivalItem, Passage, Permission, PublicationState, RightsRecord

VISITOR_ACCESS = (AccessLevel.public.value, AccessLevel.public_online_only.value)


def item_visible() -> ColumnElement[bool]:
    """Item is published, has a published version, is visitor-accessible and display-cleared."""
    return and_(
        ArchivalItem.publication_state == PublicationState.published.value,
        ArchivalItem.published_version_id.is_not(None),
        ArchivalItem.access_level.in_(VISITOR_ACCESS),
        ArchivalItem.rights_record_id == RightsRecord.id,
        RightsRecord.display_permission == Permission.allowed.value,
        RightsRecord.discovery_only.is_(False),
    )


def passage_visible() -> ColumnElement[bool]:
    """Passage belongs to the item's current published version and is indexed."""
    return and_(
        item_visible(),
        Passage.item_id == ArchivalItem.id,
        Passage.item_version_id == ArchivalItem.published_version_id,
        Passage.indexed.is_(True),
    )


def item_cacheable() -> ColumnElement[bool]:
    """Kiosk offline cache: only fully public items; rights-sensitive items stay online-only."""
    return and_(item_visible(), ArchivalItem.access_level == AccessLevel.public.value)


def visible_item(db: Session, item_id: int) -> ArchivalItem | None:
    stmt = select(ArchivalItem).join(RightsRecord).where(ArchivalItem.id == item_id, item_visible())
    return db.execute(stmt).scalars().first()


def visible_item_ids(db: Session, item_ids: list[int]) -> set[int]:
    if not item_ids:
        return set()
    stmt = select(ArchivalItem.id).join(RightsRecord).where(ArchivalItem.id.in_(item_ids), item_visible())
    return set(db.execute(stmt).scalars())


def external_processing_allowed(item: ArchivalItem) -> bool:
    """Sarvam / LLM may only see content whose register entry allows external processing
    and whose access level is not restricted."""
    return (
        item.rights.external_processing == Permission.allowed.value
        and item.access_level != AccessLevel.restricted.value
    )


def training_allowed(item: ArchivalItem) -> bool:
    """Training permission is separate from display rights; unknown counts as not allowed."""
    return item.rights.training_permission == Permission.allowed.value
