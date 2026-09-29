"""Staff can follow one queued job (e.g. a Sarvam retry) until the worker settles it."""

from __future__ import annotations

import pytest

from archive.jobs import enqueue
from archive.models import StaffUser
from archive.security import hash_password

pytestmark = pytest.mark.db


def _login(client, db) -> dict[str, str]:
    db.add(StaffUser(email="archivist@test", display_name="archivist@test", password_hash=hash_password("pw-123456"),
                     roles=["archivist"], languages=[]))
    db.commit()
    token = client.post("/api/staff/login", json={"email": "archivist@test", "password": "pw-123456"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


class TestStaffJobDetail:
    def test_returns_the_job_status_and_result(self, db, client):
        job = enqueue(db, "sarvam_retry", {"page_id": 1, "actor": "archivist@test"}, priority=30)
        db.commit()
        h = _login(client, db)
        body = client.get(f"/api/staff/jobs/{job.id}", headers=h).json()
        assert body["id"] == job.id
        assert body["kind"] == "sarvam_retry"
        assert body["status"] == "queued"

        job.status = "done"
        job.result = {"status": "needs_full_review"}
        db.commit()
        body = client.get(f"/api/staff/jobs/{job.id}", headers=h).json()
        assert body["status"] == "done"
        assert body["result"] == {"status": "needs_full_review"}

    def test_unknown_job_is_404(self, db, client):
        assert client.get("/api/staff/jobs/999999", headers=_login(client, db)).status_code == 404

    def test_needs_a_staff_token(self, db, client):
        job = enqueue(db, "sarvam_retry", {"page_id": 1}, priority=30)
        db.commit()
        assert client.get(f"/api/staff/jobs/{job.id}").status_code == 401
