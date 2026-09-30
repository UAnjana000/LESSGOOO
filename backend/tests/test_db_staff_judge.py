"""Demo judge access: a read-only staff session without a password, only when the installation enables it."""

from __future__ import annotations

import pytest

from archive.config import get_settings
from archive.models import AuditEvent, StaffUser
from archive.security import JUDGE_EMAIL

pytestmark = pytest.mark.db


@pytest.fixture
def judge_access(monkeypatch):
    monkeypatch.setenv("ARCHIVE_JUDGE_ACCESS", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("ARCHIVE_JUDGE_ACCESS")
    get_settings.cache_clear()


def _judge(client) -> dict[str, str]:
    r = client.post("/api/staff/login/judge")
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestJudgeAccessOff:
    def test_is_off_by_default(self, db, client):
        assert client.get("/api/staff/judge-access").json() == {"enabled": False}
        assert client.post("/api/staff/login/judge").status_code == 404
        assert db.query(StaffUser).filter_by(email=JUDGE_EMAIL).count() == 0


class TestJudgeAccessOn:
    def test_signs_in_a_viewer_and_audits_it(self, db, client, judge_access):
        assert client.get("/api/staff/judge-access").json() == {"enabled": True}
        body = client.post("/api/staff/login/judge").json()
        assert body["user"]["email"] == JUDGE_EMAIL
        assert body["user"]["roles"] == ["viewer"]
        assert db.query(AuditEvent).filter_by(action="staff.login_judge").count() == 1
        client.post("/api/staff/login/judge")
        assert db.query(StaffUser).filter_by(email=JUDGE_EMAIL).count() == 1

    def test_can_read_the_workspace(self, db, client, judge_access):
        h = _judge(client)
        for path in ("/api/staff/me", "/api/staff/items", "/api/staff/review/queue", "/api/staff/rights",
                     "/api/staff/jobs", "/api/staff/settings/status"):
            assert client.get(path, headers=h).status_code == 200, path

    @pytest.mark.parametrize(("method", "path", "body"), [
        ("post", "/api/staff/rights", {"source_key": "x", "title": "x", "source_institution": "x"}),
        ("post", "/api/staff/pages/1/review", {"action": "approve"}),
        ("post", "/api/staff/pages/1/retry-sarvam", {}),
        ("post", "/api/staff/items/1/publish", {}),
        ("post", "/api/staff/items/1/withdraw", {"reason": "judge must not withdraw"}),
        ("put", "/api/staff/items/1/metadata", {}),
        ("post", "/api/staff/timeline", {}),
        ("post", "/api/staff/datasets", {}),
    ])
    def test_cannot_change_anything(self, db, client, judge_access, method, path, body):
        r = getattr(client, method)(path, json=body, headers=_judge(client))
        assert r.status_code == 403
        assert r.json()["detail"] == "Read-only judge access: this action is disabled."

    def test_admin_only_reads_stay_closed(self, db, client, judge_access):
        assert client.get("/api/staff/audit/verify", headers=_judge(client)).status_code == 403

    def test_the_account_has_no_usable_password(self, db, client, judge_access):
        _judge(client)
        for password in ("", "judge", "password"):
            r = client.post("/api/staff/login", json={"email": JUDGE_EMAIL, "password": password})
            assert r.status_code == 401

    def test_a_promoted_or_disabled_judge_account_is_refused(self, db, client, judge_access):
        _judge(client)
        user = db.query(StaffUser).filter_by(email=JUDGE_EMAIL).one()
        user.roles = ["viewer", "admin"]
        db.commit()
        assert client.post("/api/staff/login/judge").status_code == 403
        user.roles = ["viewer"]
        user.active = False
        db.commit()
        assert client.post("/api/staff/login/judge").status_code == 403
