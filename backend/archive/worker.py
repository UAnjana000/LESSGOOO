"""Background worker: runs LangGraph ingestion (Postgres checkpointer), publication, Sarvam retries,
speech-to-text drafts, withdrawal cleanup and old-version cleanup from the Postgres job queue."""

from __future__ import annotations

import datetime as dt
import logging
import signal
import time
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from archive import audit, jobs, ops
from archive.config import get_settings
from archive.db import new_session, psycopg_dsn, session_scope
from archive.ingest import graph as ingest_graph
from archive.ingest import processing, publish
from archive.logging_setup import configure_logging
from archive.models import ArchivalItem, FileVersion, ItemVersion, Job, Page, Passage, SystemState, utcnow
from archive.services import speech_to_text

log = logging.getLogger("archive.worker")
_running = True
BACKUP_STATE_KEY = "nightly_backup"
BACKUP_ACTOR = "nightly-schedule"


@contextmanager
def postgres_checkpointer():
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(psycopg_dsn()) as cp:
        cp.setup()
        yield cp


def handle(job_kind: str, payload: dict[str, Any], graph) -> dict[str, Any]:
    if job_kind == "ingest_item":
        state = ingest_graph.run_ingest(graph, payload["item_id"], payload.get("actor", "worker"))
        return {"pages_processed": len(state.get("page_outcomes", [])), "waiting_for_review": True}
    if job_kind == "publish_item":
        if ingest_graph.has_checkpoint(graph, payload["item_id"]):
            state = ingest_graph.resume_publish(graph, payload["item_id"], payload.get("actor", "worker"))
            if state.get("error"):
                raise publish.PublicationError(state["error"])
            if state.get("review_problems"):
                raise publish.PublicationError("not ready: " + "; ".join(state["review_problems"]))
            return state.get("result", {})
        with session_scope() as db:  # no workflow checkpoint (e.g. imported before the graph ran)
            return {k: v for k, v in publish.publish_item(db, db.get(ArchivalItem, payload["item_id"]),
                                                           payload.get("actor", "worker")).items()
                    if k != "verification"}
    if job_kind == "sarvam_retry":
        with session_scope() as db:
            page = db.get(Page, payload["page_id"])
            fb = ingest_graph.default_fallback()
            if fb is None:
                return {"status": "sarvam not configured; page stays pending review"}
            out = processing.run_sarvam(db, page, fb, actor=payload.get("actor", "worker"))
            return {"status": out.status}
    if job_kind == "speech_to_text":
        with session_scope() as db:
            return speech_to_text.draft_transcript(db, db.get(ArchivalItem, payload["item_id"]),
                                                   db.get(FileVersion, payload["file_id"]), payload.get("language"),
                                                   payload.get("actor", "worker"))
    if job_kind == "withdraw_cleanup":
        with session_scope() as db:
            return publish.withdraw_cleanup(db, payload["item_id"], payload.get("actor", "worker"))
    if job_kind == "backup":
        result = ops.backup()
        with session_scope() as db:
            actor = payload.get("actor", "worker")
            audit.record(db, actor, "backup.run", "backup", result["path"], detail=result)
            state = db.get(SystemState, BACKUP_STATE_KEY) or SystemState(key=BACKUP_STATE_KEY, value={})
            state.value = {**state.value, "last_success": {**result, "at": utcnow().isoformat()}}
            db.merge(state)
        s = get_settings()
        try:  # a retention failure must not turn a good backup into a failed job
            pruned = ops.prune_backups(s.backup_root, s.backup_keep, protect=[result["path"]])
        except OSError:
            log.exception("backup retention failed")
        else:
            if pruned["deleted"]:
                with session_scope() as db:
                    audit.record(db, payload.get("actor", "worker"), "backup.prune", "backup", str(s.backup_root),
                                 detail={**pruned, "keep": s.backup_keep})
        return result
    raise ValueError(f"unknown job kind {job_kind}")


def nightly_backup_due(now: dt.datetime, last_enqueued: dt.datetime | None, hour_utc: int) -> bool:
    """Due once per nightly slot: when no backup has been queued since the most recent `hour_utc`."""
    slot = now.astimezone(dt.UTC).replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if now < slot:
        slot -= dt.timedelta(days=1)
    return last_enqueued is None or last_enqueued < slot


def schedule_nightly_backup(db: Session, now: dt.datetime | None = None) -> Job | None:
    s = get_settings()
    if not s.nightly_backup_enabled:
        return None
    now = now or utcnow()
    state = db.get(SystemState, BACKUP_STATE_KEY)
    last = (state.value or {}).get("last_enqueued_at") if state else None
    if not nightly_backup_due(now, dt.datetime.fromisoformat(last) if last else None, s.nightly_backup_hour_utc):
        return None
    if db.execute(select(Job.id).where(Job.kind == "backup", Job.status.in_(("queued", "running")))).first():
        return None
    job = jobs.enqueue(db, "backup", {"actor": BACKUP_ACTOR}, priority=50)
    state = state or SystemState(key=BACKUP_STATE_KEY, value={})
    state.value = {**(state.value or {}), "last_enqueued_at": now.isoformat()}
    db.merge(state)
    db.flush()
    return job


def cleanup_old_versions() -> int:
    grace = dt.timedelta(hours=get_settings().old_version_grace_hours)
    with session_scope() as db:
        old = db.execute(select(ItemVersion).where(ItemVersion.state == "superseded", ItemVersion.cleaned_at.is_(None),
                                                   ItemVersion.published_at < utcnow() - grace)).scalars().all()
        for v in old:
            # Passages stay (old citations keep resolving) but leave the index.
            db.execute(update(Passage).where(Passage.item_version_id == v.id).values(indexed=False, embedding=None))
            v.cleaned_at = utcnow()
            audit.record(db, "worker", "version.cleanup", "item_version", v.id)
        return len(old)


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level)

    def stop(*_):
        global _running
        _running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_maintenance = 0.0
    with postgres_checkpointer() as cp:
        graph = ingest_graph.build_ingest_graph(checkpointer=cp)
        log.info("worker started")
        while _running:
            if time.time() - last_maintenance > 600:
                try:
                    n = cleanup_old_versions()
                    if n:
                        log.info("cleaned old versions", extra={"count": n})
                    with session_scope() as sdb:
                        if schedule_nightly_backup(sdb):
                            log.info("nightly backup queued")
                except Exception:
                    log.exception("maintenance failed")
                last_maintenance = time.time()
            db = new_session()
            try:
                job = jobs.claim(db)
                if job is None:
                    db.close()
                    time.sleep(s.worker_poll_seconds)
                    continue
                log.info("job start", extra={"job_id": job.id, "kind": job.kind})
                try:
                    result = handle(job.kind, job.payload, graph)
                    jobs.finish(db, job, result)
                    log.info("job done", extra={"job_id": job.id, "kind": job.kind})
                except Exception as exc:
                    log.exception("job failed", extra={"job_id": job.id, "kind": job.kind})
                    db.rollback()
                    jobs.fail(db, job, repr(exc))
            finally:
                db.close()


if __name__ == "__main__":
    main()
