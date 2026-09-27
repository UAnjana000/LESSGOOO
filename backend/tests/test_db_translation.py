"""Reviewed translations (named reviewer per language) and on-demand machine translation (labelled, not
stored, not citable, switchable per collection). All content is synthetic."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from archive.ingest import publish
from archive.models import ArchivalItem, StaffUser, Translation

from .factories import make_item, make_rights, publish_item

pytestmark = pytest.mark.db

HI_TEXT = "कृत्रिम परीक्षण अनुवाद: वाचनालय सबके लिए खुला है।"


def _login(client, db, email: str, roles: list[str], languages: list[str]) -> dict[str, str]:
    from archive.security import hash_password

    db.add(StaffUser(email=email, display_name=email, password_hash=hash_password("pw-123456"), roles=roles,
                     languages=languages))
    db.commit()
    token = client.post("/api/staff/login", json={"email": email, "password": "pw-123456"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _published(db, client):
    item = make_item(db, make_rights(db), ["The synthetic reading room is open to everyone."], title="Essay")
    publish_item(db, item)
    db.commit()
    pid = client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]["id"]
    return item, pid


class TestReviewedTranslation:
    def test_only_a_named_reviewer_for_the_language_can_approve_and_it_reaches_reader_and_search(self, db, client):
        item, pid = _published(db, client)
        archivist = _login(client, db, "archivist@test", ["archivist"], [])
        tr_id = client.post("/api/staff/translations", json={"source_passage_id": pid, "target_language": "hi",
                                                             "text": HI_TEXT}, headers=archivist).json()["id"]
        marathi = _login(client, db, "mr@test", ["translation_reviewer"], ["mr"])
        hindi = _login(client, db, "hi@test", ["translation_reviewer"], ["hi"])

        assert client.post(f"/api/staff/translations/{tr_id}/review", json={"action": "approve"},
                           headers=marathi).status_code == 409
        assert client.post(f"/api/staff/translations/{tr_id}/review", json={"action": "bogus"},
                           headers=hindi).status_code == 409
        assert client.post(f"/api/staff/translations/{tr_id}/review", json={"action": "approve"},
                           headers=hindi).json()["status"] == "approved"
        assert client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]["translations"] == {}

        publish.publish_item(db, db.get(ArchivalItem, item.id), "tester")
        db.commit()

        page = client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]
        assert page["passages"][0]["translations"]["hi"]["text"] == HI_TEXT
        hits = client.get("/api/visitor/search", params={"q": "वाचनालय", "lang": "hi"}).json()["results"]
        assert hits and hits[0]["kind_label"] == "Reviewed translation" and hits[0]["language"] == "hi"


class TestMachineTranslation:
    def test_labelled_not_stored_not_citable_and_switchable_per_collection(self, db, client, monkeypatch):
        import archive.api.visitor as visitor_api

        item, pid = _published(db, client)
        monkeypatch.setattr(visitor_api.sarvam_text, "translate", lambda text, src, tgt: ("मशीन अनुवाद", "test-mt"))

        r = client.get(f"/api/visitor/translate/{pid}", params={"lang": "hi"}).json()

        assert r["label"] == "Machine translation — not reviewed" and r["stored"] is False and r["citable"] is False
        assert db.execute(select(func.count()).select_from(Translation)).scalar() == 0
        archivist = _login(client, db, "archivist@test", ["archivist"], [])
        client.put(f"/api/staff/collections/{item.collection}", params={"machine_translation_enabled": False},
                   headers=archivist)
        assert client.get(f"/api/visitor/translate/{pid}", params={"lang": "hi"}).status_code == 403
        assert client.get(f"/api/visitor/translate/{pid}", params={"lang": "fr"}).status_code == 400
