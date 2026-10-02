"""Demo open access: the staff login is removed and visitors are signed in as the administrator, only when enabled."""

from __future__ import annotations

import pytest

from archive.config import get_settings
from archive.models import AuditEvent, StaffUser

pytestmark = pytest.mark.db


@pytest.fixture
def open_access(monkeypatch):
    monkeypatch.setenv("ARCHIVE_OPEN_STAFF_ACCESS", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("ARCHIVE_OPEN_STAFF_ACCESS")
    get_settings.cache_clear()


class TestOpenAccessOff:
    def test_is_off_by_default(self, db, client):
        assert client.get("/api/staff/open-access").json() == {"enabled": False}
        assert client.post("/api/staff/login/open").status_code == 404


class TestOpenAccessOn:
    def test_signs_in_the_administrator_and_audits_it(self, db, client, open_access):
        assert client.get("/api/staff/open-access").json() == {"enabled": True}
        body = client.post("/api/staff/login/open").json()
        assert body["user"]["email"] == get_settings().bootstrap_admin_email.lower()
        assert "admin" in body["user"]["roles"]
        assert db.query(AuditEvent).filter_by(action="staff.login_open").count() == 1
        client.post("/api/staff/login/open")
        assert db.query(StaffUser).filter_by(email=body["user"]["email"]).count() == 1

    def test_the_session_can_act_as_admin(self, db, client, open_access):
        token = client.post("/api/staff/login/open").json()["token"]
        assert client.get("/api/staff/audit/verify", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    def test_a_disabled_administrator_is_refused(self, db, client, open_access):
        client.post("/api/staff/login/open")
        user = db.query(StaffUser).filter_by(email=get_settings().bootstrap_admin_email.lower()).one()
        user.active = False
        db.commit()
        assert client.post("/api/staff/login/open").status_code == 403
