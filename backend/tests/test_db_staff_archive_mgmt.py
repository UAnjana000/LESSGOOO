"""Staff archive management: editable item title, fixity re-verification, upload size limit, stats pricing flag."""

from __future__ import annotations

import json

import pytest

from archive import storage
from archive.config import get_settings
from archive.models import AuditEvent, FileVersion

from .conftest import png_page
from .factories import make_item, make_rights, publish_item
from .test_db_staff_qa_fixes import _login, _upload

pytestmark = pytest.mark.db


class TestTitleEdit:
    def test_title_is_editable_versioned_and_visible_to_visitors(self, db, client):
        item = make_item(db, make_rights(db), ["Synthetic reading room text."], title="Old title")
        publish_item(db, item)
        db.commit()
        h = _login(client, db, ["archivist"])
        r = client.put(f"/api/staff/items/{item.id}/metadata", json={"title": " New title ", "reason": "typo"},
                       headers=h)
        assert r.status_code == 200 and r.json()["metadata"]["title"] == "New title"
        assert client.get(f"/api/visitor/items/{item.id}").json()["title"] == "New title"
        hist = client.get(f"/api/staff/items/{item.id}/metadata/history", headers=h).json()
        assert hist[0]["before"]["title"] == "Old title" and hist[0]["after"]["title"] == "New title"
        assert db.query(AuditEvent).filter_by(action="item.metadata.update").count() == 1

    @pytest.mark.parametrize("bad", ["", "   ", None, "x" * 501])
    def test_empty_or_overlong_title_is_rejected(self, db, client, bad):
        item = make_item(db, make_rights(db), ["text"], title="Keep")
        db.commit()
        h = _login(client, db, ["archivist"])
        r = client.put(f"/api/staff/items/{item.id}/metadata", json={"title": bad, "reason": "testing"}, headers=h)
        assert r.status_code == 422
        db.refresh(item)
        assert item.title == "Keep"


class TestFixity:
    def test_reports_ok_mismatch_and_missing(self, db, client):
        h = _login(client, db, ["archivist"])
        make_rights(db)
        db.commit()
        r = _upload(client, h, [("a.png", png_page("fixity"))])
        assert r.status_code == 200
        item_id = r.json()["item_id"]
        body = client.post(f"/api/staff/items/{item_id}/fixity", headers=h).json()
        assert body["summary"]["ok"] >= 1 and body["summary"]["mismatch"] == 0 and body["summary"]["missing"] == 0
        fv = db.query(FileVersion).filter_by(item_id=item_id, role="preservation_master").first()
        path = storage.resolve(fv.storage_uri)
        path.chmod(0o644)
        path.write_bytes(b"tampered")
        body = client.post(f"/api/staff/items/{item_id}/fixity", headers=h).json()
        assert {f["id"]: f["status"] for f in body["files"]}[fv.id] == "mismatch"
        path.unlink()
        body = client.post(f"/api/staff/items/{item_id}/fixity", headers=h).json()
        assert {f["id"]: f["status"] for f in body["files"]}[fv.id] == "missing"
        assert db.query(AuditEvent).filter_by(action="item.fixity.check").count() == 3

    def test_needs_archivist(self, db, client):
        item = make_item(db, make_rights(db), ["text"])
        db.commit()
        h = _login(client, db, ["reviewer"])
        assert client.post(f"/api/staff/items/{item.id}/fixity", headers=h).status_code == 403
        assert client.post("/api/staff/items/9999/fixity",
                           headers=_login(client, db, ["archivist"], "a2@test")).status_code == 404


class TestUploadLimit:
    def test_oversized_upload_is_refused_with_413(self, db, client, monkeypatch):
        make_rights(db)
        db.commit()
        h = _login(client, db, ["archivist"])
        monkeypatch.setenv("ARCHIVE_INTAKE_MAX_UPLOAD_BYTES", "2048")
        get_settings.cache_clear()
        try:
            r = _upload(client, h, [("big.png", b"0" * 5000)])
        finally:
            monkeypatch.delenv("ARCHIVE_INTAKE_MAX_UPLOAD_BYTES")
            get_settings.cache_clear()
        assert r.status_code == 413 and "upload limit" in json.dumps(r.json())


def test_stats_flags_unpriced_answer_model(db, client):
    h = _login(client, db, ["archivist"])
    assert client.get("/api/staff/stats", headers=h).json()["answer_prices_configured"] is False
