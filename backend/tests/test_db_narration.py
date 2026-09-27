"""Cached synthetic narration through the staff and visitor APIs (spec 1.1, 4.10, 5.5, 6.1).

Speech engines are test doubles: Sarvam TTS and espeak-ng are replaced at the narration service boundary and
ffmpeg by a byte wrapper. All content is synthetic."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from archive import exhibit
from archive.config import get_settings
from archive.datasets import corpus
from archive.ingest import publish, review
from archive.models import ArchivalItem, Derivative, FileVersion, Page, StaffUser
from archive.services import narration, sarvam_text

from .factories import make_item, make_rights, publish_item

pytestmark = pytest.mark.db

EN = "The synthetic reading room is open to everyone."
HI = "कृत्रिम परीक्षण अनुवाद: वाचनालय सबके लिए खुला है।"
SARVAM_GEN = "sarvam-tts bulbul:v3 speaker=ritu"
ESPEAK_GEN = "espeak-ng 1.51 voice=en-gb"


class FakeEngines:
    def __init__(self, monkeypatch):
        self.sarvam_up, self.espeak_up = True, True
        self.sarvam: list[tuple[str, str]] = []
        self.espeak: list[tuple[str, str]] = []
        monkeypatch.setattr(sarvam_text, "tts_configured", lambda: True)
        monkeypatch.setattr(sarvam_text, "synthesize", self._sarvam)
        monkeypatch.setattr(narration, "espeak", self._espeak)
        monkeypatch.setattr(narration, "_to_aac", lambda wav: b"AAC:" + wav)

    def _sarvam(self, text, language, client=None):
        self.sarvam.append((text, language))
        if not self.sarvam_up:
            raise sarvam_text.ServiceUnavailable("503 from text-to-speech")
        return f"sarvam:{language}:{text}".encode(), SARVAM_GEN

    def _espeak(self, text, language):
        self.espeak.append((text, language))
        if not self.espeak_up:
            raise narration.NarrationUnavailable("espeak-ng not installed")
        return f"espeak:{language}:{text}".encode(), ESPEAK_GEN


@pytest.fixture
def engines(monkeypatch):
    return FakeEngines(monkeypatch)


@pytest.fixture
def no_llm(monkeypatch):
    import archive.api.staff as staff_api
    import archive.ask.llm as llm_mod
    import archive.ask.service as ask_service

    calls = []
    for mod in (llm_mod, staff_api, ask_service):
        monkeypatch.setattr(mod, "get_llm", lambda *a, **k: calls.append("llm"))
    return calls


def _login(client, db, email="archivist@test", roles=("archivist",), languages=()) -> dict[str, str]:
    from archive.security import hash_password

    db.add(StaffUser(email=email, display_name=email, password_hash=hash_password("pw-123456"), roles=list(roles),
                     languages=list(languages)))
    db.commit()
    token = client.post("/api/staff/login", json={"email": email, "password": "pw-123456"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _published(db, client, text=EN, external="allowed"):
    item = make_item(db, make_rights(db, external=external), [text], title="Essay")
    publish_item(db, item)
    db.commit()
    pid = client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]["id"]
    return item, pid


def _narrate(client, h, pid, language="en", **kw):
    return client.post("/api/staff/narration", json={"passage_id": pid, "language": language, **kw}, headers=h)


def _narration_files(db) -> int:
    return db.execute(select(func.count()).select_from(FileVersion).where(FileVersion.kind == "narration")).scalar()


class TestCachedLabelledNarration:
    def test_created_once_then_served_from_cache_with_label_and_generator_and_no_llm(self, db, client, engines,
                                                                                    no_llm):
        item, pid = _published(db, client)
        h = _login(client, db)

        first = _narrate(client, h, pid)
        second = _narrate(client, h, pid)

        assert first.status_code == 200 and second.status_code == 200
        assert engines.sarvam == [(EN, "en")]  # one TTS call; the second request is a cache hit
        assert first.json()["cached"] is False and second.json()["cached"] is True
        assert second.json()["file_id"] == first.json()["file_id"] and _narration_files(db) == 1
        assert first.json()["label"] == "Synthetic narration" and first.json()["generator"] == SARVAM_GEN

        served = client.get(f"/api/visitor/narration/{pid}", params={"lang": "en"}).json()
        assert served == {"file_id": first.json()["file_id"], "label": "Synthetic narration", "generator": SARVAM_GEN}
        audio = client.get(f"/api/visitor/files/{served['file_id']}")
        assert audio.status_code == 200 and audio.content == f"AAC:sarvam:en:{EN}".encode()
        listed = client.get(f"/api/visitor/items/{item.id}").json()["narrations"]
        assert [(n["language"], n["file_id"], n["label"]) for n in listed] == [
            ("en", served["file_id"], "Synthetic narration")]
        assert engines.sarvam == [(EN, "en")] and no_llm == []  # playback: no TTS and no LLM call

    def test_edited_text_or_another_voice_regenerates_but_an_unchanged_republish_reuses_the_audio(
            self, db, client, engines):
        item, pid = _published(db, client)
        h = _login(client, db)
        first = _narrate(client, h, pid).json()

        publish.publish_item(db, db.get(ArchivalItem, item.id), "tester")  # same approved text, new passage id
        db.commit()
        same_pid = client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]["id"]
        reused = _narrate(client, h, same_pid).json()
        assert same_pid != pid and reused["file_id"] == first["file_id"] and len(engines.sarvam) == 1
        assert client.get(f"/api/visitor/narration/{same_pid}").json()["file_id"] == first["file_id"]

        page = db.get(Page, db.get(ArchivalItem, item.id).pages[0].id)
        review.reopen_page(db, page, "reviewer", "typo")
        review.review_page(db, page, "correct", "reviewer", "archivist", text=EN.replace("everyone", "all readers"))
        db.commit()
        publish.publish_item(db, db.get(ArchivalItem, item.id), "tester")
        db.commit()
        edited_pid = client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]["id"]
        edited = _narrate(client, h, edited_pid).json()
        assert edited["cached"] is False and edited["file_id"] != first["file_id"]
        assert engines.sarvam[-1] == (EN.replace("everyone", "all readers"), "en") and len(engines.sarvam) == 2

        local = _narrate(client, h, edited_pid, prefer_local=True).json()
        assert local["cached"] is False and local["generator"] == ESPEAK_GEN and len(engines.espeak) == 1
        assert _narrate(client, h, edited_pid, prefer_local=True).json()["cached"] is True
        assert len(engines.espeak) == 1 and len(engines.sarvam) == 2

    def test_a_cached_file_removed_from_storage_is_regenerated_not_served(self, db, client, engines):
        _item, pid = _published(db, client)
        h = _login(client, db)
        first = _narrate(client, h, pid).json()
        fv = db.get(FileVersion, first["file_id"])
        fv.deleted_at = fv.created_at
        db.commit()

        again = _narrate(client, h, pid).json()

        assert again["cached"] is False and again["file_id"] != first["file_id"] and len(engines.sarvam) == 2
        assert client.get(f"/api/visitor/narration/{pid}").json()["file_id"] == again["file_id"]


    def test_narration_audio_counts_against_the_kiosk_cache_budget(self, db, client, engines, monkeypatch):
        item, pid = _published(db, client)
        h = _login(client, db)
        file_id = _narrate(client, h, pid).json()["file_id"]

        payload = exhibit.build_manifest(db)["payload"]
        entry = next(e for e in payload["items"] if e["item_id"] == item.id)
        assert f"/api/visitor/files/{file_id}" in entry["urls"] and payload["total_bytes"] <= payload["budget_bytes"]
        monkeypatch.setattr(get_settings(), "exhibit_cache_budget_bytes", entry["bytes"] - 1)
        assert item.id in exhibit.build_manifest(db)["payload"]["skipped_over_budget"]


class TestOnlyApprovedTextOrReviewedTranslation:
    def test_reviewed_translation_is_narrated_and_reaches_the_reader_under_its_source_passage(self, db, client,
                                                                                               engines):
        item, pid = _published(db, client)
        h = _login(client, db)
        tr_id = client.post("/api/staff/translations", json={"source_passage_id": pid, "target_language": "hi",
                                                             "text": HI}, headers=h).json()["id"]
        # Unreviewed translation: there is no approved Hindi text for this passage yet.
        assert _narrate(client, h, pid, language="hi").status_code == 409
        hindi = _login(client, db, "hi@test", ["translation_reviewer"], ["hi"])
        client.post(f"/api/staff/translations/{tr_id}/review", json={"action": "approve"}, headers=hindi)
        publish.publish_item(db, db.get(ArchivalItem, item.id), "tester")
        db.commit()
        passage = client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]
        hi_pid = passage["translations"]["hi"]["passage_id"]

        r = _narrate(client, h, hi_pid, language="hi")

        assert r.status_code == 200 and engines.sarvam == [(HI, "hi")]
        listed = client.get(f"/api/visitor/items/{item.id}").json()["narrations"]
        # web/src/pages/Item.tsx plays the narration whose source_ids include the passage shown and whose
        # language is the visitor's language.
        assert any(n["language"] == "hi" and passage["id"] in n["source_ids"] for n in listed)
        assert client.get(f"/api/visitor/narration/{passage['id']}", params={"lang": "hi"}).status_code == 200

    def test_unapproved_page_text_has_no_passage_to_narrate(self, db, client, engines):
        item = make_item(db, make_rights(db), ["Draft OCR text awaiting review."], title="Draft", approve=False)
        db.commit()
        h = _login(client, db)
        assert client.get(f"/api/visitor/items/{item.id}").status_code == 404
        assert _narrate(client, h, 999_999).status_code == 404
        assert engines.sarvam == [] and engines.espeak == []


class TestEngineFallbackAndRights:
    def test_sarvam_failure_falls_back_to_espeak_ng_with_the_same_label(self, db, client, engines):
        _item, pid = _published(db, client)
        h = _login(client, db)
        engines.sarvam_up = False

        r = _narrate(client, h, pid).json()

        assert r["generator"] == ESPEAK_GEN and r["label"] == "Synthetic narration"
        assert len(engines.sarvam) == 1 and engines.espeak == [(EN, "en")]
        assert client.get(f"/api/visitor/narration/{pid}").json()["generator"] == ESPEAK_GEN

    def test_no_engine_gives_a_clear_unavailable_state_and_the_reader_still_works(self, db, client, engines):
        item, pid = _published(db, client)
        h = _login(client, db)
        engines.sarvam_up = engines.espeak_up = False

        r = _narrate(client, h, pid)

        assert r.status_code == 503 and "unavailable" in r.json()["detail"]
        reader = client.get(f"/api/visitor/items/{item.id}")
        assert reader.status_code == 200 and reader.json()["narrations"] == []
        assert reader.json()["pages"][0]["passages"][0]["text"] == EN
        assert client.get(f"/api/visitor/narration/{pid}").status_code == 404
        assert _narration_files(db) == 0

    def test_text_that_may_not_leave_the_premises_is_narrated_locally_only(self, db, client, engines):
        _item, pid = _published(db, client, external="not_allowed")
        h = _login(client, db)

        r = _narrate(client, h, pid).json()

        assert engines.sarvam == [] and engines.espeak == [(EN, "en")] and r["generator"] == ESPEAK_GEN


class TestWithdrawalAndTrainingCorpus:
    def test_withdrawn_item_narration_is_not_served_or_generated(self, db, client, engines):
        item, pid = _published(db, client)
        h = _login(client, db)
        file_id = _narrate(client, h, pid).json()["file_id"]

        assert client.post(f"/api/staff/items/{item.id}/withdraw", json={"reason": "rights holder request"},
                           headers=h).status_code == 200

        assert client.get(f"/api/visitor/narration/{pid}").status_code == 410
        assert client.get(f"/api/visitor/files/{file_id}").status_code == 410
        assert client.get(f"/api/visitor/items/{item.id}").status_code == 410
        assert _narrate(client, h, pid).status_code == 409
        assert len(engines.sarvam) == 1
        db.expire_all()
        publish.withdraw_cleanup(db, item.id)
        db.commit()
        assert db.get(FileVersion, file_id).deleted_at is not None

    def test_narration_never_enters_the_training_eligible_corpus(self, db, client, engines):
        _item, pid = _published(db, client)
        h = _login(client, db)
        before = corpus.preview_dataset(db)

        file_id = _narrate(client, h, pid).json()["file_id"]
        db.expire_all()
        after = corpus.preview_dataset(db)

        narration_sha = db.get(FileVersion, file_id).sha256
        assert after["entries"] == before["entries"] and after["passages"] == before["passages"] == 1
        assert narration_sha not in {e["text_sha256"] for e in after["entries"]}
        dv = corpus.freeze_dataset(db, "narration-check", "tester")
        assert all(e["passage_id"] == pid for e in dv.manifest["entries"])
        assert db.execute(select(func.count()).select_from(Derivative)
                          .where(Derivative.kind == "narration")).scalar() == 1
