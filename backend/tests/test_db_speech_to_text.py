"""Staff speech-to-text: an uploaded recording is stored as a preservation master and Sarvam's transcript
lands as an unreviewed, never quote-verified draft. Sarvam is faked at the HTTP boundary
(httpx.MockTransport); no live call is made. All content is synthetic."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select

from archive import storage
from archive.config import get_settings
from archive.ingest import review
from archive.models import ArchivalItem, AuditEvent, FileVersion, Job, MediaSegment, Passage, StaffUser
from archive.services import speech_to_text as stt

from .factories import make_item, make_rights
from .test_unit_speech_to_text import wav_bytes

pytestmark = pytest.mark.db

REPLY = {"request_id": "req-1", "transcript": "सभा में स्वागत है। आज का विषय शिक्षा है।", "language_code": "hi-IN",
         "timestamps": {"words": ["सभा में स्वागत है।", "आज का विषय शिक्षा है।"],
                        "start_time_seconds": [0.0, 0.9], "end_time_seconds": [0.8, 1.9]}}


@pytest.fixture
def sarvam(monkeypatch):
    """Fake Sarvam REST endpoint. `calls` holds each request; set `reply` to change the response."""

    class Fake:
        def __init__(self) -> None:
            self.calls: list[httpx.Request] = []
            self.reply = httpx.Response(200, json=REPLY)

        def handler(self, req: httpx.Request) -> httpx.Response:
            self.calls.append(req)
            return self.reply

    fake = Fake()
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "test-key-not-real")
    monkeypatch.setattr(stt, "_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    return fake


def _login(client, db, email: str, roles: list[str]) -> dict[str, str]:
    from archive.security import hash_password

    db.add(StaffUser(email=email, display_name=email, password_hash=hash_password("pw-123456"), roles=roles,
                     languages=[]))
    db.commit()
    token = client.post("/api/staff/login", json={"email": email, "password": "pw-123456"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _audio_item(db, external="allowed", access="public", language="hi", item_type="audio") -> ArchivalItem:
    item = make_item(db, make_rights(db, key=f"r-{external}-{access}", external=external), [],
                     title="Synthetic lecture recording", access=access, collection="audio_video",
                     language=language, item_type=item_type)
    db.commit()
    return item


def _upload(client, item_id: int, headers, data: bytes | None = None, language: str | None = None,
            name: str = "lecture.wav"):
    form = {"language": language} if language else {}
    files = {"file": (name, data, "application/octet-stream")} if data is not None else None
    return client.post(f"/api/staff/items/{item_id}/speech-to-text", data=form, files=files, headers=headers)


def _run_job(db, job_id: int) -> dict:
    from archive import worker

    job = db.get(Job, job_id)
    result = worker.handle(job.kind, job.payload, None)
    db.expire_all()
    return result


def _field(req: httpx.Request, name: str) -> str:
    marker = f'name="{name}"\r\n\r\n'.encode()
    return req.content.split(marker)[1].split(b"\r\n")[0].decode()


class TestDraftTranscript:
    def test_upload_stores_the_original_and_sarvam_text_lands_as_an_unverified_draft(self, db, client, sarvam):
        item = _audio_item(db)
        archivist = _login(client, db, "archivist@test", ["archivist"])
        audio = wav_bytes(2)

        r = _upload(client, item.id, archivist, audio, language="hi")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "queued" and "not quote-verified" in body["label"]
        master = db.get(FileVersion, body["file_id"])
        assert master.role == "preservation_master" and master.item_id == item.id
        assert master.sha256 == storage.sha256_bytes(audio) and storage.read_bytes(master.storage_uri) == audio
        assert sarvam.calls == []  # nothing is sent until the worker runs the job

        result = _run_job(db, body["job_id"])

        assert result["segments"] == 2 and len(sarvam.calls) == 1
        assert _field(sarvam.calls[0], "language_code") == "hi-IN"
        segs = db.execute(select(MediaSegment).where(MediaSegment.item_id == item.id)
                          .order_by(MediaSegment.start_ms)).scalars().all()
        assert [(s.start_ms, s.end_ms, s.transcript_text) for s in segs] == [
            (0, 800, "सभा में स्वागत है।"), (900, 1900, "आज का विषय शिक्षा है।")]
        for s in segs:
            assert s.review_status == "draft" and s.quote_verified is False and s.quote_verified_by is None
            assert s.reviewed_by is None and s.language == "hi"
            assert s.draft_engine.startswith("sarvam-stt") and s.source_file_id == master.id
        db.refresh(item)
        assert item.publication_state == "in_review" and item.published_version_id is None
        assert db.execute(select(func.count()).select_from(Passage)).scalar() == 0
        assert db.execute(select(AuditEvent).where(AuditEvent.action == "media.stt_draft")).scalars().one()

        queue = client.get("/api/staff/review/queue", headers=archivist).json()["segments"]
        assert {q["draft_engine"] for q in queue} == {segs[0].draft_engine}
        detail = client.get(f"/api/staff/items/{item.id}", headers=archivist).json()["segments"]
        assert all(d["status"] == "draft" and not d["quote_verified"] and d["draft_engine"] for d in detail)

    def test_item_language_is_used_when_staff_do_not_choose_one(self, db, client, sarvam):
        item = _audio_item(db, language="mr")
        archivist = _login(client, db, "archivist@test", ["archivist"])

        _run_job(db, _upload(client, item.id, archivist, wav_bytes(1)).json()["job_id"])

        assert _field(sarvam.calls[0], "language_code") == "mr-IN"

    def test_stored_recording_can_be_transcribed_without_a_new_upload(self, db, client, sarvam):
        item = _audio_item(db)
        archivist = _login(client, db, "archivist@test", ["archivist"])
        first = _upload(client, item.id, archivist, wav_bytes(1), language="hi").json()

        again = _upload(client, item.id, archivist)

        assert again.status_code == 200 and again.json()["file_id"] == first["file_id"]

    def test_a_new_run_replaces_earlier_unreviewed_drafts_but_keeps_reviewed_segments(self, db, client, sarvam):
        item = _audio_item(db)
        archivist = _login(client, db, "archivist@test", ["archivist"])
        first = _upload(client, item.id, archivist, wav_bytes(1), language="hi").json()
        _run_job(db, first["job_id"])
        kept = db.execute(select(MediaSegment).where(MediaSegment.item_id == item.id)
                          .order_by(MediaSegment.start_ms)).scalars().first()
        review.review_segment(db, kept, "approve", "archivist@test")
        db.commit()

        _run_job(db, _upload(client, item.id, archivist).json()["job_id"])

        segs = db.execute(select(MediaSegment).where(MediaSegment.item_id == item.id)).scalars().all()
        assert sorted(s.review_status for s in segs) == ["approved", "draft", "draft"]
        assert kept.id in {s.id for s in segs}


class TestRightsRefusal:
    @pytest.mark.parametrize("external,access", [("not_allowed", "public"), ("unknown", "public"),
                                                 ("allowed", "restricted")])
    def test_refused_with_a_clear_error_and_nothing_is_sent_or_stored(self, db, client, sarvam, external, access):
        item = _audio_item(db, external=external, access=access)
        archivist = _login(client, db, "archivist@test", ["archivist"])

        r = _upload(client, item.id, archivist, wav_bytes(1), language="hi")

        assert r.status_code == 409 and "not sent to Sarvam" in r.json()["detail"]
        assert sarvam.calls == []
        assert db.execute(select(func.count()).select_from(Job)).scalar() == 0
        assert db.execute(select(func.count()).select_from(FileVersion)).scalar() == 0

    def test_rights_withdrawn_after_queueing_stops_the_job_before_sarvam(self, db, client, sarvam):
        item = _audio_item(db)
        archivist = _login(client, db, "archivist@test", ["archivist"])
        job_id = _upload(client, item.id, archivist, wav_bytes(1), language="hi").json()["job_id"]
        item.rights.external_processing = "not_allowed"
        db.commit()

        with pytest.raises(stt.SpeechToTextRefused):
            _run_job(db, job_id)

        assert sarvam.calls == []
        assert db.execute(select(func.count()).select_from(MediaSegment)).scalar() == 0


class TestBadResponse:
    @pytest.mark.parametrize("reply", [
        httpx.Response(200, json={"request_id": "r", "language_code": "hi-IN"}),
        httpx.Response(200, text="not json"),
        httpx.Response(422, json={"error": {"message": "unreadable audio", "code": "unprocessable_entity_error"}}),
    ], ids=["no-transcript", "not-json", "rejected"])
    def test_nothing_is_stored_as_transcript_and_nothing_is_quote_verified(self, db, client, sarvam, reply):
        item = _audio_item(db)
        archivist = _login(client, db, "archivist@test", ["archivist"])
        sarvam.reply = reply
        job_id = _upload(client, item.id, archivist, wav_bytes(1), language="hi").json()["job_id"]

        with pytest.raises(stt.SpeechToTextError):
            _run_job(db, job_id)

        assert db.execute(select(func.count()).select_from(MediaSegment)).scalar() == 0
        assert db.execute(select(func.count()).select_from(MediaSegment)
                          .where(MediaSegment.quote_verified.is_(True))).scalar() == 0
        assert db.execute(select(func.count()).select_from(Passage)
                          .where(Passage.quote_verified.is_(True))).scalar() == 0
        db.refresh(item)
        assert item.publication_state != "published"

    def test_jobs_are_not_retried_automatically(self, db, client, sarvam):
        item = _audio_item(db)
        archivist = _login(client, db, "archivist@test", ["archivist"])
        job = db.get(Job, _upload(client, item.id, archivist, wav_bytes(1), language="hi").json()["job_id"])
        assert job.max_attempts == 1


class TestEndpointGuards:
    @pytest.mark.parametrize("roles,status", [
        (["archivist"], 200), (["reviewer"], 200), (["admin"], 200),
        (["curator"], 403), (["translation_reviewer"], 403),
    ])
    def test_only_roles_that_ingest_or_review_may_start_it(self, db, client, sarvam, roles, status):
        item = _audio_item(db)
        headers = _login(client, db, f"{roles[0]}@test", roles)
        assert _upload(client, item.id, headers, wav_bytes(1), language="hi").status_code == status

    def test_anonymous_request_is_refused(self, db, client, sarvam):
        item = _audio_item(db)
        assert _upload(client, item.id, {}, wav_bytes(1), language="hi").status_code == 401
        assert db.execute(select(func.count()).select_from(FileVersion)).scalar() == 0

    def test_non_audio_upload_is_refused_without_storing(self, db, client, sarvam):
        from .conftest import png_page

        item = _audio_item(db)
        archivist = _login(client, db, "archivist@test", ["archivist"])
        r = _upload(client, item.id, archivist, png_page(), name="scan.png")
        assert r.status_code == 422
        assert db.execute(select(func.count()).select_from(FileVersion)).scalar() == 0

    def test_only_audio_or_video_items(self, db, client, sarvam):
        item = make_item(db, make_rights(db), [], title="Printed essay")
        db.commit()
        archivist = _login(client, db, "archivist@test", ["archivist"])
        assert _upload(client, item.id, archivist, wav_bytes(1), language="hi").status_code == 409

    def test_unsupported_language_is_refused(self, db, client, sarvam):
        item = _audio_item(db)
        archivist = _login(client, db, "archivist@test", ["archivist"])
        assert _upload(client, item.id, archivist, wav_bytes(1), language="fr").status_code == 422

    def test_no_recording_to_transcribe(self, db, client, sarvam):
        item = _audio_item(db)
        archivist = _login(client, db, "archivist@test", ["archivist"])
        assert _upload(client, item.id, archivist).status_code == 409

    def test_sarvam_not_configured(self, db, client, monkeypatch):
        item = _audio_item(db)
        archivist = _login(client, db, "archivist@test", ["archivist"])
        monkeypatch.setattr(get_settings(), "sarvam_api_key", "")
        r = _upload(client, item.id, archivist, wav_bytes(1), language="hi")
        assert r.status_code == 503
        assert db.execute(select(func.count()).select_from(FileVersion)).scalar() == 0
