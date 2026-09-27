"""Nightly backup schedule (spec 6.5, prototype: nightly backup to a second disk). The real pg_dump run is
not exercised here; `ops.backup` is replaced so the schedule and job handling can be tested on any host."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from archive import worker
from archive.models import AuditEvent, Job, SystemState

pytestmark = pytest.mark.db

UTC = dt.UTC


@pytest.mark.parametrize(("now", "last", "due"), [
    (dt.datetime(2026, 9, 27, 21, 0, tzinfo=UTC), None, True),
    (dt.datetime(2026, 9, 27, 21, 0, tzinfo=UTC), dt.datetime(2026, 9, 27, 20, 5, tzinfo=UTC), False),
    (dt.datetime(2026, 9, 27, 19, 0, tzinfo=UTC), dt.datetime(2026, 9, 26, 20, 5, tzinfo=UTC), False),
    (dt.datetime(2026, 9, 27, 20, 0, tzinfo=UTC), dt.datetime(2026, 9, 26, 20, 5, tzinfo=UTC), True),
    (dt.datetime(2026, 9, 28, 3, 0, tzinfo=UTC), dt.datetime(2026, 9, 26, 20, 5, tzinfo=UTC), True),
])
def test_backup_is_due_once_per_nightly_slot(now, last, due):
    assert worker.nightly_backup_due(now, last, hour_utc=20) is due


def test_schedule_enqueues_one_backup_per_night_and_records_the_run(db, monkeypatch):
    runs = []
    monkeypatch.setattr(worker.ops, "backup", lambda: runs.append(1) or {"path": "/backups/backup-x", "files": 3,
                                                                          "seconds": 0.1})
    night = dt.datetime(2026, 9, 27, 20, 30, tzinfo=UTC)

    job = worker.schedule_nightly_backup(db, now=night)
    assert job is not None and job.kind == "backup"
    assert worker.schedule_nightly_backup(db, now=night + dt.timedelta(minutes=10)) is None  # already queued
    db.commit()  # the handler writes through its own session

    result = worker.handle("backup", job.payload, graph=None)
    db.expire_all()

    assert runs == [1] and result["path"] == "/backups/backup-x"
    state = db.get(SystemState, worker.BACKUP_STATE_KEY).value
    assert state["last_success"]["path"] == "/backups/backup-x"
    assert db.execute(select(AuditEvent).where(AuditEvent.action == "backup.run")).scalar_one().actor == \
        "nightly-schedule"
    db.execute(select(Job).where(Job.id == job.id)).scalar_one().status = "done"
    db.flush()
    assert worker.schedule_nightly_backup(db, now=night + dt.timedelta(hours=3)) is None  # same night
    assert worker.schedule_nightly_backup(db, now=night + dt.timedelta(days=1)) is not None


def test_backup_job_prunes_to_the_retention_setting_and_audits_it(db, monkeypatch, tmp_path):
    root = tmp_path / "backups"
    for day in range(1, 5):
        d = root / f"backup-2026092{day}T200000Z"
        d.mkdir(parents=True)
        (d / "BACKUP_LOG.json").write_text("{}", encoding="utf-8")
    newest = str(root / "backup-20260924T200000Z")
    monkeypatch.setattr(worker.ops, "backup", lambda: {"path": newest, "files": 0, "seconds": 0.1})
    monkeypatch.setattr(worker.get_settings(), "backup_root", root)
    monkeypatch.setattr(worker.get_settings(), "backup_keep", 2)

    worker.handle("backup", {"actor": worker.BACKUP_ACTOR}, graph=None)
    db.expire_all()

    assert sorted(p.name for p in root.iterdir()) == ["backup-20260923T200000Z", "backup-20260924T200000Z"]
    event = db.execute(select(AuditEvent).where(AuditEvent.action == "backup.prune")).scalar_one()
    assert event.detail["deleted"] == ["backup-20260921T200000Z", "backup-20260922T200000Z"]
    assert db.get(SystemState, worker.BACKUP_STATE_KEY).value["last_success"]["path"] == newest


def test_retention_default_is_fourteen():
    from archive.config import Settings

    assert Settings.model_fields["backup_keep"].default == 14


def test_schedule_can_be_switched_off(db, monkeypatch):
    monkeypatch.setattr(worker.get_settings(), "nightly_backup_enabled", False)
    assert worker.schedule_nightly_backup(db, now=dt.datetime(2026, 9, 27, 21, 0, tzinfo=UTC)) is None
