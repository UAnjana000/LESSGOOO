"""Snapshot-consistent dump bookkeeping and restore verification (spec 6.5, 9, 10.2 Backup).
The real pg_dump is replaced by a small script that imports the exported snapshot, so this runs on any host.
Each test copies only the files referenced by the rows it created, so leftovers from other tests in the shared
storage roots cannot change the outcome."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from archive import ops
from archive.config import get_settings

from .factories import make_item, make_rights, publish_item

pytestmark = pytest.mark.db

FAKE_DUMP = r"""
import sys, psycopg
url, out, snap = sys.argv[1], sys.argv[2], sys.argv[-1]
assert snap.startswith("--snapshot=")
with psycopg.connect(url, autocommit=True) as c:   # a concurrent writer, like live ingestion
    c.execute("INSERT INTO rights_record (source_key, title, source_institution, rights_holder, basis_for_use, "
              "display_permission, training_permission, external_processing, evidence, attribution, date_checked, "
              "checked_by, discovery_only, is_fixture, created_at, updated_at) VALUES ('late', 't', 's', 'h', 'b', "
              "'allowed', 'allowed', 'allowed', 'e', 'a', '2026-09-27', 'x', false, true, now(), now())")
with psycopg.connect(url) as c:
    c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    c.execute("SET TRANSACTION SNAPSHOT '%s'" % snap.split("=", 1)[1])
    n = c.execute("SELECT count(*) FROM rights_record").fetchone()[0]
open(out, "w").write(str(n))
"""

# Stands in for pg_dump as ops.backup calls it: `--version`, or `-h H -p P -U U -Fc -f OUT DBNAME --snapshot=ID`
# with the password in PGPASSWORD. Writes the passage count it sees inside the exported snapshot.
FAKE_PG_DUMP = r"""
import os, sys, psycopg
a = sys.argv[1:]
if a == ["--version"]:
    print("pg_dump (PostgreSQL) 17.8 (fake)")
    sys.exit(0)
opt = lambda k: a[a.index(k) + 1]
with psycopg.connect(host=opt("-h"), port=opt("-p"), user=opt("-U"), dbname=a[-2],
                     password=os.environ["PGPASSWORD"]) as c:
    c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    c.execute("SET TRANSACTION SNAPSHOT '%s'" % a[-1].split("=", 1)[1])
    n = c.execute("SELECT count(*) FROM passage").fetchone()[0]
open(opt("-f"), "w").write(str(n))
"""

SCHEMES = {"pres": "preservation", "deliv": "delivery", "deriv": "derivatives"}


def _url() -> str:
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def stored(db):
    rights = make_rights(db, key="bk")
    item = make_item(db, rights, ["A page for the backup test."], title="Backup item", item_key="bk-item")
    publish_item(db, item)
    db.commit()
    return item


def _copy_live_files(db, dest: Path) -> int:
    """Restore-like copy of exactly the files the current (per-test) file_version rows point to."""
    s = get_settings()
    uris = db.execute(text("SELECT storage_uri FROM file_version WHERE deleted_at IS NULL")).scalars().all()
    for uri in uris:
        scheme, _, rel = uri.partition("://")
        name = SCHEMES[scheme]
        target = dest / name / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(getattr(s, ops.ROOTS[name])) / rel, target)
    return len(uris)


def test_snapshot_dump_counts_match_what_the_dump_sees(db, stored, tmp_path):
    script, out = tmp_path / "fake_dump.py", tmp_path / "seen.txt"
    script.write_text(FAKE_DUMP, encoding="utf-8")
    res = ops.snapshot_dump([sys.executable, str(script), _url(), str(out)])
    assert res["snapshot"] and res["counts"]["rights_record"] == int(out.read_text())
    live = db.execute(text("SELECT count(*) FROM rights_record")).scalar()
    assert live == res["counts"]["rights_record"] + 1  # the concurrent insert is not in the snapshot
    assert {"archival_item", "file_version", "passage", "audit_event"} <= set(res["counts"])


def test_snapshot_dump_propagates_a_failed_dump(db, stored):
    with pytest.raises(subprocess.CalledProcessError):
        ops.snapshot_dump([sys.executable, "-c", "import sys; sys.exit(3)"])


def test_verify_restore_passes_on_a_faithful_copy(db, stored, tmp_path):
    root = tmp_path / "restored"
    assert _copy_live_files(db, root) >= 2
    expected = ops.snapshot_dump([sys.executable, "-c", "pass"])["counts"]
    res = ops.verify_restore(get_settings().database_url, root, expected)
    assert res["success"], res
    assert res["db_file_rows_checked"] >= 2 and res["db_file_rows_failed"] == []
    assert res["audit_chain_ok"] and res["audit_events"] > 0
    assert res["row_count_mismatches"] == {}


def test_verify_restore_fails_on_a_tampered_file_or_wrong_counts(db, stored, tmp_path):
    root = tmp_path / "restored"
    _copy_live_files(db, root)
    uri = db.execute(text("SELECT storage_uri FROM file_version WHERE item_id = :i AND deleted_at IS NULL "
                          "AND storage_uri LIKE 'pres://%' ORDER BY id LIMIT 1"), {"i": stored.id}).scalar_one()
    victim = root / "preservation" / uri.partition("://")[2]
    victim.write_bytes(victim.read_bytes() + b"x")
    expected = ops.snapshot_dump([sys.executable, "-c", "pass"])["counts"]
    expected["passage"] += 5
    res = ops.verify_restore(get_settings().database_url, root, expected)
    assert not res["success"]
    assert res["db_file_rows_failed"] == [uri]
    assert res["row_count_mismatches"]["passage"] == {"expected": expected["passage"],
                                                      "restored": expected["passage"] - 5}
    json.dumps(res)  # the drill writes it as RESTORE_LOG.json


def test_backup_job_refuses_an_older_pg_dump_before_writing_anything(db, stored, tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "pg_dump_cmd", lambda: [
        sys.executable, "-c", "print('pg_dump (PostgreSQL) 15.19 (Debian 15.19-0+deb12u1)')"])
    with pytest.raises(RuntimeError, match=r"15\.19 .* cannot dump PostgreSQL .*postgresql-client-"):
        ops.backup(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_backup_job_output_is_snapshot_consistent_and_passes_restore_verification(db, stored, tmp_path,
                                                                                  monkeypatch):
    script = tmp_path / "pg_dump.py"
    script.write_text(FAKE_PG_DUMP, encoding="utf-8")
    monkeypatch.setattr(ops, "pg_dump_cmd", lambda: [sys.executable, str(script)])

    result = ops.backup(tmp_path / "backups")  # what the worker's nightly "backup" job runs

    dest = Path(result["path"])
    counts = json.loads((dest / "DB_COUNTS.json").read_text(encoding="utf-8"))
    assert counts == result["row_counts"] and counts["passage"] == int((dest / "database.dump").read_text())
    assert result["pg_client"].startswith("pg_dump (PostgreSQL) 17") and result["snapshot"]
    manifest = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["database_dump_sha256"] and manifest["files"]
    res = ops.verify_restore(get_settings().database_url, dest, counts)
    assert res["success"], res
