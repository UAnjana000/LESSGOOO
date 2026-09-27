"""Backup retention: keep the newest N complete backups; never touch the newest one or one still being written."""

from __future__ import annotations

from pathlib import Path

from archive import ops


def _backup(root: Path, stamp: str, complete: bool = True) -> Path:
    d = root / f"backup-{stamp}"
    (d / "preservation").mkdir(parents=True)
    (d / "database.dump").write_bytes(b"dump")
    if complete:
        (d / "BACKUP_LOG.json").write_text("{}", encoding="utf-8")
    return d


def _names(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir())


def test_keeps_the_newest_n_complete_backups(tmp_path):
    for day in range(1, 6):
        _backup(tmp_path, f"2026092{day}T200000Z")
    out = ops.prune_backups(tmp_path, keep=3)
    assert _names(tmp_path) == ["backup-20260923T200000Z", "backup-20260924T200000Z", "backup-20260925T200000Z"]
    assert out["deleted"] == ["backup-20260921T200000Z", "backup-20260922T200000Z"]
    assert out["kept"] == 3


def test_a_backup_still_being_written_is_never_deleted_or_counted(tmp_path):
    _backup(tmp_path, "20260920T200000Z", complete=False)  # older, never finished: left for staff to inspect
    _backup(tmp_path, "20260921T200000Z")
    _backup(tmp_path, "20260922T200000Z")
    _backup(tmp_path, "20260923T200000Z", complete=False)  # in progress right now
    out = ops.prune_backups(tmp_path, keep=1)
    assert _names(tmp_path) == ["backup-20260920T200000Z", "backup-20260922T200000Z", "backup-20260923T200000Z"]
    assert out["deleted"] == ["backup-20260921T200000Z"]
    assert out["incomplete"] == ["backup-20260920T200000Z", "backup-20260923T200000Z"]


def test_the_newest_complete_backup_survives_a_keep_of_zero(tmp_path):
    _backup(tmp_path, "20260921T200000Z")
    _backup(tmp_path, "20260922T200000Z")
    ops.prune_backups(tmp_path, keep=0)
    assert _names(tmp_path) == ["backup-20260922T200000Z"]


def test_a_protected_backup_is_kept_beyond_the_limit(tmp_path):
    old = _backup(tmp_path, "20260921T200000Z")
    _backup(tmp_path, "20260922T200000Z")
    _backup(tmp_path, "20260923T200000Z")
    ops.prune_backups(tmp_path, keep=1, protect=[old])
    assert _names(tmp_path) == ["backup-20260921T200000Z", "backup-20260923T200000Z"]


def test_other_folders_and_files_are_left_alone(tmp_path):
    (tmp_path / "restore-drill").mkdir()
    (tmp_path / "backup-notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "backup-manual-copy").mkdir()
    _backup(tmp_path, "20260921T200000Z")
    _backup(tmp_path, "20260922T200000Z")
    ops.prune_backups(tmp_path, keep=1)
    assert _names(tmp_path) == ["backup-20260922T200000Z", "backup-manual-copy", "backup-notes.txt",
                                "restore-drill"]


def test_missing_root_is_a_no_op(tmp_path):
    assert ops.prune_backups(tmp_path / "absent", keep=3)["deleted"] == []
