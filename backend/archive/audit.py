"""Append-only, hash-chained audit log (the audit record of the archive - never Langfuse)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from archive.models import AuditEvent, utcnow


def record(
    db: Session,
    actor: str,
    action: str,
    entity: str,
    entity_id: Any,
    *,
    entity_version: int | None = None,
    detail: dict[str, Any] | None = None,
    checksum_before: str | None = None,
    checksum_after: str | None = None,
) -> AuditEvent:
    # Serialise chain appends so two writers never share a prev_hash.
    db.execute(text("SELECT pg_advisory_xact_lock(424242)"))
    prev = db.execute(select(AuditEvent.row_hash).order_by(AuditEvent.id.desc()).limit(1)).scalar()
    created = utcnow()
    body = {
        "actor": actor,
        "action": action,
        "entity": entity,
        "entity_id": str(entity_id),
        "entity_version": entity_version,
        "detail": detail or {},
        "checksum_before": checksum_before,
        "checksum_after": checksum_after,
        "prev_hash": prev,
        "created_at": created.isoformat(),
    }
    row_hash = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    event = AuditEvent(
        actor=actor,
        action=action,
        entity=entity,
        entity_id=str(entity_id),
        entity_version=entity_version,
        detail=detail or {},
        checksum_before=checksum_before,
        checksum_after=checksum_after,
        prev_hash=prev,
        row_hash=row_hash,
        created_at=created,
    )
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session) -> tuple[bool, int]:
    """Recompute the hash chain. Returns (ok, events_checked)."""
    prev = None
    count = 0
    for ev in db.execute(select(AuditEvent).order_by(AuditEvent.id)).scalars():
        body = {
            "actor": ev.actor,
            "action": ev.action,
            "entity": ev.entity,
            "entity_id": ev.entity_id,
            "entity_version": ev.entity_version,
            "detail": ev.detail,
            "checksum_before": ev.checksum_before,
            "checksum_after": ev.checksum_after,
            "prev_hash": prev,
            "created_at": ev.created_at.isoformat(),
        }
        expected = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
        if ev.prev_hash != prev or ev.row_hash != expected:
            return False, count
        prev = ev.row_hash
        count += 1
    return True, count
