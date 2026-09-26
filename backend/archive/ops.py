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


def backup(dest_root: Path | None = None) -> dict[str, Any]:
    s = get_settings()
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = Path(dest_root or s.backup_root) / f"backup-{stamp}"
    dest.mkdir(parents=True, exist_ok=False)
    t0 = time.time()
    args, env = _pg_env(s.database_url)
    subprocess.run(["pg_dump", *args, "-Fc", "-f", str(dest / "database.dump"), _dbname(s.database_url)],
                   check=True, env=env, timeout=3600)
    manifest: dict[str, Any] = {"created_at": stamp, "files": {}, "database_dump_sha256": storage.sha256_file(dest / "database.dump")}
    for name, attr in ROOTS.items():
        src = Path(getattr(s, attr))
        if src.exists():
            shutil.copytree(src, dest / name, dirs_exist_ok=True)
        for f in sorted((dest / name).rglob("*")) if (dest / name).exists() else []:
            if f.is_file() and not f.name.endswith(".tmp"):
                manifest["files"][str(f.relative_to(dest)).replace("\\", "/")] = storage.sha256_file(f)
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    result = {"path": str(dest), "files": len(manifest["files"]), "seconds": round(time.time() - t0, 2)}
    (dest / "BACKUP_LOG.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


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
    # Cross-check restored file_version rows against restored files.
    teng = create_engine(target_db_url)
    db_checked, db_missing = 0, []
    with teng.connect() as c:
        rows = c.execute(text("SELECT storage_uri, sha256 FROM file_version WHERE deleted_at IS NULL")).all()
    folder = {"pres": "preservation", "deliv": "delivery", "deriv": "derivatives"}
    for uri, sha in rows:
        scheme, _, rel = uri.partition("://")
        path = target_root / folder[scheme] / rel
        db_checked += 1
        if not path.exists() or storage.sha256_file(path) != sha:
            db_missing.append(uri)
    teng.dispose()
    log.update({"files_restored": copied, "manifest_mismatches": mismatches, "db_file_rows_checked": db_checked,
                "db_file_rows_failed": db_missing, "seconds": round(time.time() - t0, 2),
                "success": not mismatches and not db_missing,
                "finished": dt.datetime.now(dt.UTC).isoformat()})
    (target_root / "RESTORE_LOG.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    return log


def fixity(db: Session, actor: str = "fixity-check") -> dict[str, Any]:
    bad, checked = [], 0
    for fv in db.execute(select(FileVersion).where(FileVersion.deleted_at.is_(None))).scalars():
        checked += 1
        if not storage.verify(fv.storage_uri, fv.sha256):
            bad.append({"file_id": fv.id, "uri": fv.storage_uri, "role": fv.role})
    audit.record(db, actor, "fixity.check", "file_version", "*", detail={"checked": checked, "failed": bad[:50]})
    return {"checked": checked, "failed": bad}
