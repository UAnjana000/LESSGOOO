"""Postgres job queue helpers (SELECT ... FOR UPDATE SKIP LOCKED)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive.models import Job, utcnow


def enqueue(db: Session, kind: str, payload: dict[str, Any], priority: int = 100) -> Job:
    job = Job(kind=kind, payload=payload, priority=priority)
    db.add(job)
    db.flush()
    return job


def claim(db: Session) -> Job | None:
    job = db.execute(
        select(Job).where(Job.status == "queued", Job.run_after <= utcnow())
        .order_by(Job.priority, Job.id).limit(1).with_for_update(skip_locked=True)
    ).scalar()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    db.commit()
    return job


def finish(db: Session, job: Job, result: dict[str, Any]) -> None:
    job.status = "done"
    job.result = result
    db.commit()


def fail(db: Session, job: Job, error: str) -> None:
    job.last_error = error[:2000]
    if job.attempts >= job.max_attempts:
        job.status = "failed"
    else:
        job.status = "queued"
        job.run_after = utcnow() + dt.timedelta(seconds=30 * 2 ** job.attempts)
    db.commit()
