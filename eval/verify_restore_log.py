"""Turn a RESTORE_LOG.json (written by `python -m archive.cli restore ...`) into the backup_restore
results block (spec 6.5, 8.3 "one full restore to a clean machine with checksum match, shown from its
recorded log", 10.2 Backup).

    python eval/verify_restore_log.py /restore-target/RESTORE_LOG.json \
        --source-host edge-mini-pc --target-host spare-laptop

restore_success is MEASURED pass only when the dump checksum matched, every file matched the backup
manifest, at least one file_version row was checked, and none failed. target_was_clean_machine stays
UNMEASURED unless both host names are given and differ.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from evalkit import MEASURED, UNMEASURED, load_json


def _m(value: Any, evidence: str, measured_at: str | None, n: int = 1) -> dict[str, Any]:
    return {"status": MEASURED, "value": value, "n": n, "measured_at": measured_at, "evidence": evidence,
            "method": "archive.cli restore -> RESTORE_LOG.json"}


def _u(reason: str) -> dict[str, Any]:
    return {"status": UNMEASURED, "value": None, "n": 0, "notes": reason}


def summarise(log: dict[str, Any], evidence: str, source_host: str | None, target_host: str | None) -> dict[str, Any]:
    at = log.get("finished") or log.get("started")
    mismatches = log.get("manifest_mismatches", [])
    failed = log.get("db_file_rows_failed", [])
    checked = int(log.get("db_file_rows_checked", 0))
    passed = bool(log.get("success")) and bool(log.get("database_dump_checksum_ok")) and not mismatches \
        and not failed and checked > 0
    out = {
        "restore_success": _m("pass" if passed else "fail", evidence, at),
        "restore_time_seconds": _m(log.get("seconds"), evidence, at) if log.get("seconds") is not None else _u("no timing"),
        "files_restored": _m(int(log.get("files_restored", 0)), evidence, at),
        "manifest_checksum_mismatches": _m(len(mismatches), evidence, at, n=max(1, int(log.get("files_restored", 0)))),
        "db_file_rows_checked": _m(checked, evidence, at),
        "db_file_rows_failed": _m(len(failed), evidence, at, n=max(1, checked)),
    }
    if source_host and target_host:
        out["target_was_clean_machine"] = _m("yes" if source_host != target_host else "no", evidence, at)
    else:
        out["target_was_clean_machine"] = _u("source and target host names not recorded")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("restore_log")
    ap.add_argument("--source-host")
    ap.add_argument("--target-host")
    args = ap.parse_args()
    block = summarise(load_json(args.restore_log), args.restore_log, args.source_host, args.target_host)
    print(json.dumps({"backup_restore": block}, indent=2))
    sys.exit(0 if block["restore_success"]["value"] == "pass" else 1)


if __name__ == "__main__":
    main()
