"""Manifest import keeps each real BAWS/CAD item's date and collection: the timeline, date-range search and
collection browse all read them from the item row, so a dropped field hides the item from those surfaces."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from archive.ingest import intake
from archive.models import ArchivalItem

INTAKE = Path(__file__).resolve().parents[2] / "intake"
REAL_MANIFESTS = ("baws_mea_cad1948.manifest.json", "cad_lok_sabha.manifest.json")

EXPECTED = {
    "baws-en-vol01-castes-in-india": ("writings", dt.date(1916, 5, 9)),
    "baws-hi-khand01-bharat-mein-jatipratha": ("writings", dt.date(1916, 5, 9)),
    "baws-en-vol13-speech-1949-11-25": ("speeches", dt.date(1949, 11, 25)),
    "cad-1948-11-04-en": ("debates", dt.date(1948, 11, 4)),
    "cad-1948-11-04-hi": ("debates", dt.date(1948, 11, 4)),
    "cad-1949-11-25-en": ("debates", dt.date(1949, 11, 25)),
    "cad-1949-11-25-hi": ("debates", dt.date(1949, 11, 25)),
}


def _metadata_only(name: str) -> dict:
    manifest = json.loads((INTAKE / name).read_text(encoding="utf-8"))
    for it in manifest["items"]:
        it["files"] = []
    return manifest


@pytest.mark.parametrize("name", REAL_MANIFESTS)
def test_real_manifests_validate(name):
    assert intake.validate_manifest(_metadata_only(name)) == []


def test_import_copies_manifest_dates_and_collection_onto_items(db):
    entries = {}
    for name in REAL_MANIFESTS:
        manifest = _metadata_only(name)
        report = intake.import_manifest(db, manifest, INTAKE, "tester")
        assert report["rejected"] == []
        rights = {r["source_key"]: r for r in manifest["rights"]}
        for it in manifest["items"]:
            entries[it["item_key"]] = (it, rights[it["rights_source_key"]])
    db.commit()
    assert set(EXPECTED) <= set(entries)

    for key, (entry, rights) in entries.items():
        item = db.query(ArchivalItem).filter(ArchivalItem.capture_details["item_key"].astext == key).one()
        assert item.collection == entry["collection"]
        assert item.date_text == entry["date_text"]
        assert item.date_start == dt.date.fromisoformat(entry["date_start"])
        assert item.date_end == (dt.date.fromisoformat(entry["date_end"]) if entry.get("date_end") else None)
        assert item.date_certainty == entry["date_certainty"]
        assert item.original_languages == entry["languages"]
        assert item.volume == entry.get("volume", rights.get("volume"))
        assert item.source_institution == rights["source_institution"]
        if key in EXPECTED:
            assert (item.collection, item.date_start) == EXPECTED[key]
