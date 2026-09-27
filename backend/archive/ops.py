"""Backup, restore and fixity (spec 6.5, 9).

backup  : pg_dump (custom format) + copy of preservation/delivery/derivative roots + SHA-256 manifest
restore : into a CLEAN target database and CLEAN file roots, then verify every file checksum against the
          manifest and against file_version rows in the restored database; writes a restore log.
fixity  : recompute SHA-256 for every live file_version and record the result in the audit log.
Indexes are rebuildable and are not part of preservation backups; the DB dump includes them for speed.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from archive import audit, storage
from archive.config import get_settings
from archive.models import FileVersion

ROOTS = {"preservation": "preservation_root", "delivery": "delivery_root", "derivatives": "derivative_root"}


def _pg_env(url: str) -> tuple[list[str], dict[str, str]]:
    u = urlparse(url.replace("postgresql+psycopg://", "postgresql://"))
    env = {**os.environ, "PGPASSWORD": u.password or ""}
    return ["-h", u.hostname or "localhost", "-p", str(u.port or 5432), "-U", u.username or "postgres"], env


def _dbname(url: str) -> str:
    return urlparse(url.replace("postgresql+psycopg://", "postgresql://")).path.lstrip("/")


def pg_dump_cmd() -> list[str]:
    return ["pg_dump"]


def _major(version: str) -> int:
    m = re.search(r"\(PostgreSQL\)\s+(\d+)", version) or re.match(r"\s*(\d+)", version)
    if not m:
        raise RuntimeError(f"cannot read a PostgreSQL version from {version!r}")
    return int(m.group(1))


def check_pg_client(database_url: str) -> dict[str, str]:
    """pg_dump refuses to dump a server with a newer major version (the api image's Debian client is 15, the demo
    server is 17), so check before a backup folder is created rather than failing halfway through the night."""
    import psycopg

    client = subprocess.run([*pg_dump_cmd(), "--version"], capture_output=True, text=True, check=True,
                            timeout=60).stdout.strip()
    with psycopg.connect(_libpq(database_url), connect_timeout=10) as conn:
        server = conn.execute("SHOW server_version").fetchone()[0]
    if _major(client) < _major(server):
        raise RuntimeError(f"{client} cannot dump PostgreSQL {server}; install postgresql-client-{_major(server)} "
                           "(backend/Dockerfile) or run the backup from the ops image")
    return {"pg_client": client, "server_version": server}


def backup(dest_root: Path | None = None) -> dict[str, Any]:
    s = get_settings()
    client = check_pg_client(s.database_url)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = Path(dest_root or s.backup_root) / f"backup-{stamp}"
    dest.mkdir(parents=True, exist_ok=False)
    t0 = time.time()
    args, env = _pg_env(s.database_url)
    snap = snapshot_dump([*pg_dump_cmd(), *args, "-Fc", "-f", str(dest / "database.dump"), _dbname(s.database_url)],
                         s.database_url, env=env)
    (dest / "DB_COUNTS.json").write_text(json.dumps(snap["counts"], indent=1), encoding="utf-8")
    manifest: dict[str, Any] = {"created_at": stamp, "files": {}, "database_dump_sha256": storage.sha256_file(dest / "database.dump")}
    for name, attr in ROOTS.items():
        src = Path(getattr(s, attr))
        if src.exists():
            shutil.copytree(src, dest / name, dirs_exist_ok=True)
        for f in sorted((dest / name).rglob("*")) if (dest / name).exists() else []:
            if f.is_file() and not f.name.endswith(".tmp"):
                manifest["files"][str(f.relative_to(dest)).replace("\\", "/")] = storage.sha256_file(f)
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    result = {"path": str(dest), "files": len(manifest["files"]), "seconds": round(time.time() - t0, 2),
              "pg_client": client["pg_client"], "server_version": snap["server_version"],
              "snapshot": snap["snapshot"], "row_counts": snap["counts"], "dump_seconds": snap["dump_seconds"]}
    (dest / "BACKUP_LOG.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


_BACKUP_DIR = re.compile(r"backup-\d{8}T\d{6}Z")


def prune_backups(root: Path, keep: int, protect: list[Path | str] = ()) -> dict[str, Any]:
    """Delete complete backups older than the newest `keep` (at least 1) in `root`. A backup is complete once
    BACKUP_LOG.json exists, which backup() writes last; a folder without it is still being written (or was
    interrupted) and is never deleted or counted. Paths in `protect` are always kept."""
    root = Path(root)
    if not root.is_dir():
        return {"deleted": [], "kept": 0, "incomplete": []}
    dirs = sorted(d for d in root.iterdir() if d.is_dir() and _BACKUP_DIR.fullmatch(d.name))
    complete = [d for d in dirs if (d / "BACKUP_LOG.json").is_file()]
    incomplete = [d.name for d in dirs if d not in complete]
    protected = {Path(p).resolve() for p in protect}
    keep_set = set(complete[-max(keep, 1):])
    deleted = []
    for d in complete:
        if d in keep_set or d.resolve() in protected:
            continue
        shutil.rmtree(d)
        deleted.append(d.name)
    return {"deleted": deleted, "kept": len(complete) - len(deleted), "incomplete": incomplete}


def restore(backup_dir: Path, target_db_url: str, target_root: Path) -> dict[str, Any]:
    """Restore into a clean database (must be empty or absent) and an empty directory, then verify."""
    t0 = time.time()
    backup_dir = Path(backup_dir)
    manifest = json.loads((backup_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    log: dict[str, Any] = {"backup": str(backup_dir), "target_db": _dbname(target_db_url),
                           "target_root": str(target_root), "started": dt.datetime.now(dt.UTC).isoformat()}
    if target_root.exists() and any(target_root.iterdir()):
        raise RuntimeError("target_root must be empty (clean restore)")
    target_root.mkdir(parents=True, exist_ok=True)
    dump_ok = storage.sha256_file(backup_dir / "database.dump") == manifest["database_dump_sha256"]
    log["database_dump_checksum_ok"] = dump_ok
    if not dump_ok:
        raise RuntimeError("database dump checksum mismatch")
    admin_url = target_db_url.rsplit("/", 1)[0] + "/postgres"
    dbname = _dbname(target_db_url)
    eng = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": dbname}).scalar()
        if exists:
            raise RuntimeError(f"target database {dbname} already exists; restore requires a clean target")
        c.execute(text(f'CREATE DATABASE "{dbname}"'))
    args, env = _pg_env(target_db_url)
    subprocess.run(["pg_restore", *args, "-d", dbname, "--no-owner", str(backup_dir / "database.dump")],
                   check=True, env=env, timeout=3600)
    mismatches, copied = [], 0
    for rel, digest in manifest["files"].items():
        src = backup_dir / rel
        dst = target_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
        if storage.sha256_file(dst) != digest:
            mismatches.append(rel)
    db_checked, db_missing = verify_file_rows(target_db_url, target_root)
    log.update({"files_restored": copied, "manifest_mismatches": mismatches, "db_file_rows_checked": db_checked,
                "db_file_rows_failed": db_missing, "seconds": round(time.time() - t0, 2),
                "success": not mismatches and not db_missing,
                "finished": dt.datetime.now(dt.UTC).isoformat()})
    (target_root / "RESTORE_LOG.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    return log


def verify_file_rows(target_db_url: str, target_root: Path) -> tuple[int, list[str]]:
    """Cross-check every live file_version row of a restored database against the restored files."""
    teng = create_engine(target_db_url)
    checked, failed = 0, []
    with teng.connect() as c:
        rows = c.execute(text("SELECT storage_uri, sha256 FROM file_version WHERE deleted_at IS NULL")).all()
    teng.dispose()
    folder = {"pres": "preservation", "deliv": "delivery", "deriv": "derivatives"}
    for uri, sha in rows:
        scheme, _, rel = uri.partition("://")
        path = Path(target_root) / folder[scheme] / rel
        checked += 1
        if not path.exists() or storage.sha256_file(path) != sha:
            failed.append(uri)
    return checked, failed


KEY_TABLES = ("rights_record", "staff_user", "archival_item", "item_version", "file_version", "page", "passage",
              "review_decision", "audit_event", "translation", "training_example", "dataset_version")


def _libpq(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def table_counts(conn) -> dict[str, int]:
    """Row counts of the key tables that exist, on a psycopg connection."""
    out = {}
    for t in KEY_TABLES:
        if conn.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0]:
            out[t] = int(conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0])
    return out


def snapshot_dump(dump_cmd: list[str], database_url: str | None = None, timeout: int = 3600,
                  env: dict[str, str] | None = None) -> dict[str, Any]:
    """Export a read-only REPEATABLE READ snapshot, count the key tables in it, then run `dump_cmd` with
    `--snapshot=<id>` appended (pg_dump option) so the dump and the counts describe the same instant. The exporting
    transaction takes no locks of its own and is held only while the dump runs; it never writes."""
    import psycopg

    t0 = time.time()
    with psycopg.connect(_libpq(database_url or get_settings().database_url), connect_timeout=10) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        snap = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
        server = conn.execute("SHOW server_version").fetchone()[0]
        counts = table_counts(conn)
        t1 = time.time()
        subprocess.run([*dump_cmd, f"--snapshot={snap}"], check=True, timeout=timeout, env=env)
        conn.rollback()
    return {"snapshot": snap, "server_version": server, "counts": counts,
            "count_seconds": round(t1 - t0, 2), "dump_seconds": round(time.time() - t1, 2)}


def verify_restore(target_db_url: str, target_root: Path, expected_counts: dict[str, int] | None) -> dict[str, Any]:
    """Checks on a restored copy: file_version rows vs restored files, key-table row counts vs the counts taken in
    the dump's snapshot, and the audit hash chain."""
    import psycopg

    checked, failed = verify_file_rows(target_db_url, target_root)
    with psycopg.connect(_libpq(target_db_url), connect_timeout=10) as conn:
        restored = table_counts(conn)
    eng = create_engine(target_db_url)
    with Session(eng) as s:
        chain_ok, events = audit.verify_chain(s)
    eng.dispose()
    mismatches = {t: {"expected": n, "restored": restored.get(t)} for t, n in (expected_counts or {}).items()
                  if restored.get(t) != n}
    return {"db_file_rows_checked": checked, "db_file_rows_failed": failed, "restored_counts": restored,
            "expected_counts": expected_counts, "row_count_mismatches": mismatches,
            "audit_chain_ok": chain_ok, "audit_events": events,
            "success": checked > 0 and not failed and not mismatches and chain_ok and expected_counts is not None}


def fixity(db: Session, actor: str = "fixity-check") -> dict[str, Any]:
    bad, checked = [], 0
    for fv in db.execute(select(FileVersion).where(FileVersion.deleted_at.is_(None))).scalars():
        checked += 1
        if not storage.verify(fv.storage_uri, fv.sha256):
            bad.append({"file_id": fv.id, "uri": fv.storage_uri, "role": fv.role})
    audit.record(db, actor, "fixity.check", "file_version", "*", detail={"checked": checked, "failed": bad[:50]})
    return {"checked": checked, "failed": bad}
