"""Attach the essay PDF that seed-fixtures quarantined (stale manifest SHA). Throwaway e2e data only."""
from pathlib import Path

from archive.db import session_scope
from archive.ingest.intake import create_pages_for_file, store_original
from archive.models import ArchivalItem, FileVersion

pdf = Path("/fixtures/files/fx-essay-reading-rooms.pdf").read_bytes()
with session_scope() as db:
    item = db.get(ArchivalItem, 1)
    if item is None:
        raise SystemExit("item 1 missing")
    if item.pages:
        print({"skipped": True, "pages": len(item.pages), "state": item.publication_state})
    else:
        fr = store_original(db, item, pdf, "fx-essay-reading-rooms.pdf", "e2e-repair")
        if fr.status != "stored" or fr.file_id is None:
            raise SystemExit(f"store failed: {fr}")
        fv = db.get(FileVersion, fr.file_id)
        n, _ = create_pages_for_file(db, item, fv, pdf, "born_digital", "en", 1, ["1", "2"])
        print({"status": fr.status, "file_id": fr.file_id, "pages": n, "state": item.publication_state})
