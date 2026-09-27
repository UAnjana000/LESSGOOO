"""Staff restore of a withdrawn item (same IDs) and review-role recording."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from archive import audit
from archive.ingest import publish, review
from archive.models import AuditEvent, FileVersion, Passage, ReviewDecision, StaffUser
from archive.security import hash_password

from .factories import make_item, make_rights, publish_item

pytestmark = pytest.mark.db


def _login(client, db, roles: list[str], email: str = "archivist@test") -> dict[str, str]:
    db.add(StaffUser(email=email, display_name=email, password_hash=hash_password("pw-123456"),
                     roles=roles, languages=[]))
    db.commit()
    token = client.post("/api/staff/login", json={"email": email, "password": "pw-123456"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _withdrawn_detail(response) -> dict:
    body = response.json()["detail"]
    assert isinstance(body, dict)
    return body


class TestRestore:
    def test_restore_keeps_passage_and_file_ids(self, db, client):
        item = make_item(db, make_rights(db), ["Restore keeps the same oil-lamp passage."], title="Restore IDs")
        publish_item(db, item)
        passage_ids = list(db.execute(select(Passage.id).where(
            Passage.item_id == item.id, Passage.item_version_id == item.published_version_id)).scalars())
        file_id = item.pages[0].delivery_file_id
        version_no = item.version
        h = _login(client, db, ["archivist"])

        assert client.post(f"/api/staff/items/{item.id}/withdraw",
                           json={"reason": "rights holder request"}, headers=h).status_code == 200
        db.expire_all()
        publish.withdraw_cleanup(db, item.id, "worker")
        db.commit()

        r = client.post(f"/api/staff/items/{item.id}/restore",
                        json={"reason": "rights holder withdrew the takedown"}, headers=h)
        assert r.status_code == 200
        body = r.json()
        db.refresh(item)
        assert body["state"] == "published"
        assert item.publication_state == "published"
        assert item.version == version_no
        assert item.pages[0].delivery_file_id == file_id
        restored_ids = list(db.execute(select(Passage.id).where(
            Passage.item_id == item.id, Passage.item_version_id == item.published_version_id,
            Passage.indexed.is_(True))).scalars())
        assert restored_ids == passage_ids
        fv = db.get(FileVersion, file_id)
        assert fv is not None and fv.deleted_at is None

    def test_restore_refused_when_rights_forbid(self, db, client):
        rights = make_rights(db, key="r-restore-block")
        item = make_item(db, rights, ["Text that must stay withdrawn after a rights change."])
        publish_item(db, item)
        h = _login(client, db, ["archivist"])
        client.post(f"/api/staff/items/{item.id}/withdraw", json={"reason": "takedown"}, headers=h)
        rights.display_permission = "not_allowed"
        db.commit()

        r = client.post(f"/api/staff/items/{item.id}/restore",
                        json={"reason": "please put it back"}, headers=h)
        assert r.status_code == 409
        db.refresh(item)
        assert item.publication_state == "withdrawn"
        assert client.get(f"/api/visitor/items/{item.id}").status_code == 410

    def test_restore_writes_hash_chained_audit(self, db, client):
        item = make_item(db, make_rights(db), ["Audit the restore of this withdrawn leaflet."])
        publish_item(db, item)
        h = _login(client, db, ["archivist"])
        client.post(f"/api/staff/items/{item.id}/withdraw", json={"reason": "error"}, headers=h)
        client.post(f"/api/staff/items/{item.id}/restore",
                    json={"reason": "withdrawal was a mistake"}, headers=h)

        events = list(db.execute(select(AuditEvent).where(AuditEvent.action == "item.restore",
                                                          AuditEvent.entity_id == str(item.id))).scalars())
        assert len(events) == 1
        assert events[0].actor == "archivist@test"
        assert "mistake" in (events[0].detail.get("reason") or "")
        ok, n = audit.verify_chain(db)
        assert ok and n >= 2

    def test_restore_is_idempotent(self, db, client):
        item = make_item(db, make_rights(db), ["Idempotent restore of the same mill-worker page."])
        publish_item(db, item)
        passage_ids = list(db.execute(select(Passage.id).where(Passage.item_id == item.id)).scalars())
        file_id = item.pages[0].delivery_file_id
        h = _login(client, db, ["archivist"])
        client.post(f"/api/staff/items/{item.id}/withdraw", json={"reason": "temporary"}, headers=h)
        first = client.post(f"/api/staff/items/{item.id}/restore", json={"reason": "put back"}, headers=h)
        second = client.post(f"/api/staff/items/{item.id}/restore", json={"reason": "put back again"}, headers=h)
        assert first.status_code == 200 and second.status_code == 200
        db.refresh(item)
        assert item.publication_state == "published"
        assert item.pages[0].delivery_file_id == file_id
        assert list(db.execute(select(Passage.id).where(Passage.item_id == item.id)).scalars()) == passage_ids
        restores = list(db.execute(select(AuditEvent).where(AuditEvent.action == "item.restore")).scalars())
        assert len(restores) == 1

    def test_visitor_links_are_410_while_withdrawn(self, db, client):
        item = make_item(db, make_rights(db), ["A withdrawn oil-lamp circular for 410 checks."])
        publish_item(db, item)
        file_id = item.pages[0].delivery_file_id
        pid = db.execute(select(Passage.id).where(Passage.item_id == item.id)).scalar_one()
        h = _login(client, db, ["archivist"])
        client.post(f"/api/staff/items/{item.id}/withdraw", json={"reason": "rights holder request"}, headers=h)

        item_r = client.get(f"/api/visitor/items/{item.id}")
        passage_r = client.get(f"/api/visitor/passages/{pid}")
        file_r = client.get(f"/api/visitor/files/{file_id}")
        iiif_r = client.get(f"/iiif/{file_id}/info.json")
        deep_r = client.get(f"/api/visitor/items/{item.id}", params={"page": 1, "passage": pid})
        assert {item_r.status_code, passage_r.status_code, file_r.status_code,
                iiif_r.status_code, deep_r.status_code} == {410}
        for r in (item_r, passage_r, file_r, iiif_r, deep_r):
            detail = _withdrawn_detail(r)
            assert detail["reason_category"] in {"withdrawn", "rights", "takedown"}
            assert detail["code"] == "item_withdrawn"
        assert client.get("/api/visitor/search", params={"q": "oil-lamp circular"}).json()["results"] == []

    def test_links_work_after_restore(self, db, client):
        item = make_item(db, make_rights(db), ["After restore the ferry-toll leaflet is readable again."])
        publish_item(db, item)
        file_id = item.pages[0].delivery_file_id
        pid = db.execute(select(Passage.id).where(Passage.item_id == item.id)).scalar_one()
        h = _login(client, db, ["archivist"])
        client.post(f"/api/staff/items/{item.id}/withdraw", json={"reason": "error"}, headers=h)
        db.expire_all()
        publish.withdraw_cleanup(db, item.id, "worker")
        db.commit()
        assert client.post(f"/api/staff/items/{item.id}/restore",
                           json={"reason": "error corrected"}, headers=h).status_code == 200

        assert client.get(f"/api/visitor/items/{item.id}").status_code == 200
        assert client.get(f"/api/visitor/passages/{pid}").status_code == 200
        assert client.get(f"/api/visitor/files/{file_id}").status_code == 200
        assert client.get(f"/iiif/{file_id}/info.json").status_code == 200
        hits = client.get("/api/visitor/search", params={"q": "ferry-toll leaflet"}).json()["results"]
        assert any(h["passage_id"] == pid and h["item_id"] == item.id for h in hits)
        ask = client.post("/api/visitor/ask", json={"question": "What does the ferry-toll leaflet say?",
                                                    "session_id": "restore-ask-session-1"}).json()
        assert ask["outcome"] != "error"
        cited = {c["item_id"] for c in ask.get("citations") or []}
        assert item.id in cited or ask["outcome"] in {"answered", "extractive", "insufficient"}


class TestReviewRole:
    def test_page_review_records_the_acting_users_role(self, db, client):
        item = make_item(db, make_rights(db), ["Role recording page."], approve=False)
        db.commit()
        h = _login(client, db, ["reviewer", "archivist"], "reviewer@test")
        page_id = item.pages[0].id
        r = client.post(f"/api/staff/pages/{page_id}/review",
                        json={"action": "approve", "text": "Role recording page."}, headers=h)
        assert r.status_code == 200
        decisions = list(db.execute(select(ReviewDecision).where(
            ReviewDecision.target_type == "page", ReviewDecision.target_id == page_id)).scalars())
        assert decisions
        assert decisions[-1].reviewer == "reviewer@test"
        assert decisions[-1].role == "reviewer"

    def test_review_page_stores_the_role_argument(self, db):
        item = make_item(db, make_rights(db), ["Direct role argument."], approve=False)
        review.review_page(db, item.pages[0], "approve", "agent@test", "reviewer",
                           text="Direct role argument.")
        db.commit()
        rd = db.execute(select(ReviewDecision).where(ReviewDecision.target_id == item.pages[0].id)
                        .order_by(ReviewDecision.id.desc())).scalars().first()
        assert rd.reviewer == "agent@test" and rd.role == "reviewer"
