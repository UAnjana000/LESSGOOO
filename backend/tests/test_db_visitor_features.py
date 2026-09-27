"""Visitor-facing features from the problem statement: reviewed summaries, video with timestamped
transcripts, captioned photographs, manuscripts, Constitution-article links, metadata tagging, and the
compile + QR take-away. All content is synthetic."""

from __future__ import annotations

import datetime as dt
import shutil
import subprocess

import pytest
from sqlalchemy import select

from archive import storage
from archive.ingest import intake, processing, publish, review
from archive.models import (
    ArchivalItem,
    AuditEvent,
    Derivative,
    FileVersion,
    MediaSegment,
    OcrResult,
    PhotoMetadata,
    QrCollection,
    StaffUser,
)

from .conftest import png_page
from .factories import make_item, make_rights, publish_item

pytestmark = pytest.mark.db


# ------------------------------------------------------------------ helpers

def _login(client, db, roles: list[str], email: str = "staff@test") -> dict[str, str]:
    from archive.security import hash_password

    db.add(StaffUser(email=email, display_name=email, password_hash=hash_password("pw-123456"), roles=roles,
                     languages=[]))
    db.commit()
    token = client.post("/api/staff/login", json={"email": email, "password": "pw-123456"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _recording(db, rights, *, item_type="video", fmt="video/mp4", title="Synthetic interview",
               texts=("Synthetic interviewer asks about the evening reading classes.",
                      "Synthetic speaker says the lamps were lit at seven for the mill workers.")):
    item = ArchivalItem(title=title, item_type=item_type, collection="audio_video",
                        source_institution="Synthetic test source", original_languages=["en"], scripts=["Latn"],
                        rights_record_id=rights.id, access_level="public", created_by="tester", is_fixture=True,
                        capture_details={"item_key": title.lower().replace(" ", "-")})
    db.add(item)
    db.flush()
    stored = storage.put_bytes(b"\x00\x00\x00\x18ftypisom synthetic video bytes", "delivery", ".mp4")
    db.add(FileVersion(item_id=item.id, role="delivery", kind="media", format=fmt, byte_size=stored.byte_size,
                       sha256=stored.sha256, storage_uri=stored.uri, generator="test"))
    segs = [MediaSegment(item_id=item.id, start_ms=i * 4000, end_ms=(i + 1) * 4000, language="en",
                         speaker=f"Speaker {i}", transcript_text=t) for i, t in enumerate(texts)]
    db.add_all(segs)
    db.flush()
    for s in segs:
        review.review_segment(db, s, "approve", "archivist@test")
    return item, segs


def _photo_item(db, rights, *, caption="Synthetic evening readers at long tables under two lamps",
                approve=True):
    meta = {"item_key": "photo-1", "rights_source_key": rights.source_key, "title": "Synthetic reading room photo",
            "item_type": "photograph", "collection": "photographs", "doc_class": "photograph", "languages": ["en"],
            "photo": {"caption": caption, "photographer": "Test Photographer (synthetic)",
                      "source_reference": "Synthetic negative no. 7", "place": "Samarpur (fictional)"}}
    res = intake.intake_item(db, meta, [("photo.png", png_page("synthetic photograph"), None)], "tester")
    item = db.get(ArchivalItem, res.item_id)
    for p in item.pages:
        processing.process_page(db, p, None)
    if approve:
        review.review_photo(db, db.get(PhotoMetadata, item.id), "approve", "archivist@test")
    db.flush()
    return item


# ------------------------------------------------------------------ 1. reviewed summaries

class TestReviewedSummaries:
    def test_visitor_sees_only_reviewed_summary_and_viewing_makes_no_llm_call(self, db, client, monkeypatch):
        item = make_item(db, make_rights(db), ["Synthetic essay about night schools for mill workers."])
        publish_item(db, item)
        draft = Derivative(kind="summary", item_id=item.id, language="en", content="Unreviewed AI draft.",
                           generator="test-llm", status="draft", label_shown="AI-generated summary")
        db.add(draft)
        db.commit()
        calls = []
        import archive.api.staff as staff_api
        import archive.ask.llm as llm_mod
        monkeypatch.setattr(llm_mod, "get_llm", lambda *a, **k: calls.append("llm") or None)
        monkeypatch.setattr(staff_api, "get_llm", lambda *a, **k: calls.append("llm") or None)

        assert client.get(f"/api/visitor/items/{item.id}").json()["summaries"] == []

        review.review_derivative(db, draft, "approve", "archivist@test")
        db.commit()
        body = client.get(f"/api/visitor/items/{item.id}").json()
        assert body["summaries"] == [{"language": "en", "text": "Unreviewed AI draft.", "label": "Reviewed summary"}]
        assert calls == []

    def test_staff_draft_from_approved_text_is_hidden_until_approved(self, db, client):
        item = make_item(db, make_rights(db), ["Synthetic lecture text on public reading rooms."])
        publish_item(db, item)
        empty = make_item(db, make_rights(db, key="r2"), ["unapproved"], title="Empty", approve=False)
        db.commit()
        h = _login(client, db, ["archivist"])

        assert client.post(f"/api/staff/items/{empty.id}/summary", json={"text": "x"}, headers=h).status_code == 409
        assert client.post(f"/api/staff/items/{item.id}/summary", json={}, headers=h).status_code == 503  # no LLM
        r = client.post(f"/api/staff/items/{item.id}/summary", json={"text": "A human-written summary."}, headers=h)
        assert r.status_code == 200 and r.json()["status"] == "draft"
        assert client.get(f"/api/visitor/items/{item.id}").json()["summaries"] == []

        rv = client.post(f"/api/staff/derivatives/{r.json()['id']}/review",
                         json={"action": "correct", "text": "A reviewed summary."}, headers=h)
        assert rv.json()["label"] == "Reviewed summary"
        assert client.get(f"/api/visitor/items/{item.id}").json()["summaries"][0]["text"] == "A reviewed summary."
        assert client.post(f"/api/staff/derivatives/{r.json()['id']}/review", json={"action": "correct"},
                           headers=h).status_code == 409

    def test_summary_draft_can_use_approved_recording_transcript(self, db, client):
        item, _ = _recording(db, make_rights(db))
        db.commit()
        h = _login(client, db, ["archivist"])
        r = client.post(f"/api/staff/items/{item.id}/summary", json={"text": "Interview summary."}, headers=h)
        assert r.status_code == 200


# ------------------------------------------------------------------ 2. video with timestamped transcripts

class TestVideo:
    def test_mp4_upload_is_recognised_as_video(self):
        assert intake.sniff_format(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00")[0] == "video/mp4"

    def test_video_item_plays_with_transcript_captions_and_timestamped_search(self, db, client):
        item, segs = _recording(db, make_rights(db))
        review.verify_segment_quotes(db, segs[1], "archivist@test", True)
        publish_item(db, item)

        body = client.get(f"/api/visitor/items/{item.id}").json()
        assert body["item_type"] == "video" and body["media"]["format"] == "video/mp4"
        assert [s["start_ms"] for s in body["media"]["segments"]] == [0, 4000]
        vtt = client.get(f"/api/visitor/items/{item.id}/captions.vtt").text
        assert "00:00:04.000 --> 00:00:08.000" in vtt
        hits = client.get("/api/visitor/search", params={"q": "lamps lit seven mill workers"}).json()["results"]
        hit = next(h for h in hits if h["item_id"] == item.id)
        assert hit["start_ms"] == 4000 and hit["deep_link"].startswith(f"/item/{item.id}?t=4000&passage=")
        assert hit["kind_label"] == "Reviewed transcript" and "at 0:04" in hit["citation"]
        assert hit["quote_verified"] is True
        first = next(p for s in body["media"]["segments"] if s["start_ms"] == 0 for p in s["passages"])
        assert first["quote_verified"] is False

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
    def test_ffmpeg_makes_h264_delivery_copy_for_video_master(self, db, tmp_path):
        src = tmp_path / "synthetic.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-c:v", "libx264", "-c:a", "aac",
                        "-shortest", str(src)], check=True, timeout=120)
        rights = make_rights(db)
        meta = {"item_key": "vid", "rights_source_key": rights.source_key, "title": "Synthetic clip",
                "item_type": "video", "collection": "audio_video", "doc_class": "audio_video", "languages": ["en"],
                "transcript_draft": [{"start_ms": 0, "end_ms": 1000, "text": "Synthetic tone."}]}
        res = intake.intake_item(db, meta, [("synthetic.mp4", src.read_bytes(), None)], "tester")
        item = db.get(ArchivalItem, res.item_id)
        assert db.get(FileVersion, res.files[0].file_id).format == "video/mp4"

        fv = processing.make_media_delivery(db, item)

        assert fv.format == "video/mp4" and fv.generator == "ffmpeg h264 crf26"
        assert storage.verify(fv.storage_uri, fv.sha256)

    def test_staff_can_correct_a_transcript_segment(self, db, client):
        rights = make_rights(db)
        item = ArchivalItem(title="Draft video", item_type="video", collection="audio_video",
                            source_institution="s", original_languages=["en"], scripts=["Latn"],
                            rights_record_id=rights.id, created_by="t", is_fixture=True)
        db.add(item)
        db.flush()
        seg = MediaSegment(item_id=item.id, start_ms=0, end_ms=1000, language="en", transcript_text="draft txt")
        db.add(seg)
        db.commit()
        h = _login(client, db, ["archivist"])
        r = client.post(f"/api/staff/segments/{seg.id}/review", json={"action": "correct", "text": "Corrected."},
                        headers=h)
        assert r.json() == {"id": seg.id, "status": "approved"}
        db.refresh(seg)
        assert seg.transcript_text == "Corrected."


# ------------------------------------------------------------------ 3. captioned photographs

class TestPhotographs:
    def test_unreviewed_caption_is_never_shown_to_visitors(self, db, client):
        item = _photo_item(db, make_rights(db), approve=False)
        with pytest.raises(publish.PublicationError, match="caption"):
            publish_item(db, item)
        db.commit()
        assert client.get(f"/api/visitor/items/{item.id}").status_code == 404
        assert client.get("/api/visitor/items", params={"collection": "photographs"}).json() == []
        assert client.get("/api/visitor/search", params={"q": "evening readers lamps"}).json()["results"] == []

    def test_reviewed_photo_in_browse_and_search_with_caption_credit_and_rights(self, db, client):
        item = _photo_item(db, make_rights(db))
        publish_item(db, item)

        cards = client.get("/api/visitor/items", params={"collection": "photographs"}).json()
        assert cards[0]["photo"]["caption"].startswith("Synthetic evening readers")
        assert cards[0]["photo"]["credit"] == "Test Photographer (synthetic); Synthetic negative no. 7"
        assert cards[0]["photo"]["image_file_id"] == item.pages[0].delivery_file_id
        hit = client.get("/api/visitor/search", params={"q": "evening readers lamps"}).json()["results"][0]
        assert hit["kind_label"] == "Reviewed caption" and hit["item_id"] == item.id
        assert hit["extra"]["credit"] == "Test Photographer (synthetic); Synthetic negative no. 7"
        assert hit["extra"]["rights_line"] == "Synthetic"
        detail = client.get(f"/api/visitor/items/{item.id}").json()
        assert detail["photo"]["credit"] == "Test Photographer (synthetic); Synthetic negative no. 7"

    def test_staff_caption_review_records_decision_with_corrected_caption(self, db, client):
        item = _photo_item(db, make_rights(db), approve=False)
        db.commit()
        h = _login(client, db, ["archivist"])
        r = client.post(f"/api/staff/photos/{item.id}/review",
                        json={"action": "correct", "updates": {"caption": "Corrected synthetic caption."}}, headers=h)
        assert r.json()["status"] == "approved"
        assert client.post(f"/api/staff/photos/{item.id}/review", json={"action": "bogus"},
                           headers=h).status_code == 409
        db.expire_all()
        assert db.get(PhotoMetadata, item.id).caption == "Corrected synthetic caption."


# ------------------------------------------------------------------ 4. manuscripts

class TestManuscripts:
    def _manuscript(self, db, rights):
        meta = {"item_key": "ms-1", "rights_source_key": rights.source_key, "title": "Synthetic handwritten note",
                "item_type": "manuscript", "collection": "manuscripts", "doc_class": "handwritten",
                "languages": ["en"]}
        res = intake.intake_item(db, meta, [("ms.png", png_page("synthetic handwriting"), None)], "tester")
        return db.get(ArchivalItem, res.item_id)

    def test_handwriting_is_human_transcription_and_not_counted_as_ocr_fallback(self, db, monkeypatch):
        from .test_db_pipeline import BAD, FakeFallback, _fake_local

        monkeypatch.setattr(processing, "_run_local", _fake_local(BAD, "rough ocr draft"))
        fb = FakeFallback()
        item = self._manuscript(db, make_rights(db))

        out = processing.process_page(db, item.pages[0], fb)

        assert out.route == "manual" and fb.calls == 0 and item.pages[0].ocr_route == "manual"
        draft = db.execute(select(OcrResult).where(OcrResult.page_id == item.pages[0].id)).scalar_one()
        assert draft.raw_meta["counted_in_fallback_rate"] is False and not draft.selected

    def test_published_manuscript_shows_scan_beside_reviewed_transcription(self, db, client):
        item = self._manuscript(db, make_rights(db))
        page = item.pages[0]
        processing.process_page(db, page, None)
        review.review_page(db, page, "correct", "archivist@test", "archivist",
                           text="Please keep the rooms open until ten in the harvest months.")
        publish_item(db, item)

        body = client.get(f"/api/visitor/items/{item.id}").json()
        pg = body["pages"][0]
        assert pg["image_file_id"] == page.delivery_file_id and pg["derivative_label"] == "Reviewed transcription"
        assert pg["passages"][0]["kind_label"] == "Reviewed transcription"
        assert body["collection"] == "manuscripts"


# ------------------------------------------------------------------ 5. Constitution-article links

class TestConstitutionLinks:
    def _setup(self, db, client):
        item = make_item(db, make_rights(db), ["Member Rao said untouchability must end in every public place."],
                         title="Synthetic debate", collection="debates")
        publish_item(db, item)
        passage_id = client.get("/api/visitor/items/" + str(item.id)).json()["pages"][0]["passages"][0]["id"]
        h = _login(client, db, ["curator"], "curator@test")
        a = client.post("/api/staff/constitution/articles",
                        json={"number": "17", "titles": {"en": "Abolition of Untouchability"}, "part": "III"},
                        headers=h)
        assert a.status_code == 200
        return item, passage_id, h

    def test_curated_link_shows_in_reader_search_and_article_view(self, db, client):
        item, pid, h = self._setup(db, client)
        r = client.post("/api/staff/constitution/links", json={"passage_id": pid, "article_number": "17",
                                                               "note": "synthetic test link"}, headers=h)
        assert r.status_code == 200
        want = [{"number": "17", "title": "Abolition of Untouchability"}]

        assert client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["articles"] == want
        hit = client.get("/api/visitor/search", params={"q": "untouchability public place"}).json()["results"][0]
        assert hit["extra"]["articles"] == want
        index = client.get("/api/visitor/constitution").json()
        assert [(a["number"], a["debates"]) for a in index] == [("17", 1)]
        art = client.get("/api/visitor/constitution/17").json()
        assert art["entries"][0]["passage"]["passage_id"] == pid and art["entries"][0]["item"]["id"] == item.id
        assert "curated" in art["note"].lower()

    def test_link_survives_republication_with_new_passage_ids(self, db, client):
        item, pid, h = self._setup(db, client)
        client.post("/api/staff/constitution/links", json={"passage_id": pid, "article_number": "17"}, headers=h)
        publish.publish_item(db, db.get(ArchivalItem, item.id), "tester")
        db.commit()
        new_pid = client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]["id"]
        assert new_pid != pid
        assert client.get("/api/visitor/constitution/17").json()["entries"][0]["passage"]["passage_id"] == new_pid

    def test_removal_is_audited_and_hides_the_link(self, db, client):
        item, pid, h = self._setup(db, client)
        link_id = client.post("/api/staff/constitution/links", json={"passage_id": pid, "article_number": "17"},
                              headers=h).json()["id"]
        assert client.post(f"/api/staff/constitution/links/{link_id}/remove", json={"reason": "x"},
                           headers=h).status_code == 422
        r = client.post(f"/api/staff/constitution/links/{link_id}/remove", json={"reason": "wrong article"},
                        headers=h)
        assert r.json() == {"id": link_id, "removed": True}
        assert client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["articles"] == []
        assert client.get("/api/visitor/constitution").json() == []
        actions = set(db.execute(select(AuditEvent.action).where(AuditEvent.entity == "constitution_link")).scalars())
        assert actions == {"constitution.link.add", "constitution.link.remove"}

    def test_links_need_curator_role_known_passage_and_visible_item(self, db, client):
        item, pid, h = self._setup(db, client)
        archivist = _login(client, db, ["archivist"], "archivist@test")
        body = {"passage_id": pid, "article_number": "17"}
        assert client.post("/api/staff/constitution/links", json=body, headers=archivist).status_code == 403
        assert client.post("/api/staff/constitution/links", json={**body, "passage_id": 999999},
                           headers=h).status_code == 422
        assert client.post("/api/staff/constitution/links", json={**body, "article_number": "999"},
                           headers=h).status_code == 422
        client.post("/api/staff/constitution/links", json=body, headers=h)
        publish.withdraw(db, db.get(ArchivalItem, item.id), "archivist", "test withdrawal")
        db.commit()
        assert client.get("/api/visitor/constitution").json() == []
        assert client.get("/api/visitor/constitution/17").json()["entries"] == []


    def test_fixture_seed_adds_labelled_demo_link_and_tags_once(self, db, client):
        from archive import cli

        item = make_item(db, make_rights(db), ["Member Rao moved that reading stay free of any fee."],
                         title="Synthetic proceedings", collection="debates", item_key="fx-proceedings-1")
        publish_item(db, item)

        first = cli._seed_tags_and_links(db)
        db.commit()

        assert first == {"tagged": ["fx-proceedings-1"], "links": ["fx-proceedings-1 p1 -> Article 41"]}
        assert cli._seed_tags_and_links(db) == {"tagged": [], "links": []}
        art = client.get("/api/visitor/constitution/41").json()
        assert "synthetic demonstration" in art["entries"][0]["note"].lower()
        assert client.get("/api/visitor/items", params={"person": "Member Rao (fictional)"}).json()[0]["id"] == item.id


# ------------------------------------------------------------------ 6. metadata tagging

class TestMetadataTagging:
    def test_edit_is_versioned_audited_and_filterable_by_visitors(self, db, client):
        item = make_item(db, make_rights(db), ["Synthetic speech on night schools and libraries."],
                         title="Tagged speech")
        other = make_item(db, make_rights(db, key="r2"), ["Unrelated synthetic page on water."], title="Other")
        publish_item(db, item)
        publish_item(db, other)
        h = _login(client, db, ["archivist"])
        body = {"subjects": ["Education", " Libraries ", "Education"], "people": ["Member Rao (fictional)"],
                "places": ["Samarpur (fictional)"], "date_text": "c. 1929", "date_start": "1929-01-01",
                "date_certainty": "approximate", "languages": ["en", "hi"], "edition": "Synthetic 1st ed.",
                "volume": "2", "reason": "catalogued subjects"}

        r = client.put(f"/api/staff/items/{item.id}/metadata", json=body, headers=h)

        assert r.status_code == 200 and r.json()["metadata_version"] == 2
        assert r.json()["metadata"]["subjects"] == ["Education", "Libraries"]
        hist = client.get(f"/api/staff/items/{item.id}/metadata/history", headers=h).json()
        assert hist[0]["version"] == 2 and hist[0]["before"]["subjects"] == []
        assert hist[0]["after"]["volume"] == "2" and hist[0]["reason"] == "catalogued subjects"
        ev = db.execute(select(AuditEvent).where(AuditEvent.action == "item.metadata.update")).scalar_one()
        assert ev.entity_id == str(item.id) and ev.entity_version == 2
        assert [c["id"] for c in client.get("/api/visitor/items", params={"subject": "Education"}).json()] == [item.id]
        assert [c["id"] for c in client.get("/api/visitor/items", params={"place": "Samarpur (fictional)"}).json()] \
            == [item.id]
        res = client.get("/api/visitor/search", params={"q": "synthetic", "subject": "Libraries"}).json()["results"]
        assert {h_["item_id"] for h_ in res} == {item.id}
        facets = client.get("/api/visitor/facets").json()
        assert facets == {"subjects": ["Education", "Libraries"], "people": ["Member Rao (fictional)"],
                          "places": ["Samarpur (fictional)"]}
        card = client.get(f"/api/visitor/items/{item.id}").json()
        assert card["volume"] == "2" and card["date_certainty"] == "approximate" and card["languages"] == ["en", "hi"]

    def test_search_date_range_filters_by_item_dates(self, db, client):
        in_range = make_item(db, make_rights(db), ["Synthetic library board minutes on reading rooms."],
                             title="Board minutes 1927")
        span = make_item(db, make_rights(db, key="r2"), ["Synthetic library board report spanning years."],
                         title="Board report 1925-1928")
        later = make_item(db, make_rights(db, key="r3"), ["Synthetic library board circular from later."],
                          title="Board circular 1931")
        in_range.date_start = dt.date(1927, 3, 1)
        span.date_start, span.date_end = dt.date(1925, 1, 1), dt.date(1928, 6, 30)
        later.date_start = dt.date(1931, 2, 1)
        for it in (in_range, span, later):
            publish_item(db, it)
        db.commit()

        r = client.get("/api/visitor/search",
                       params={"q": "library board", "date_from": "1927-01-01", "date_to": "1927-12-31"})

        assert r.status_code == 200
        assert {h_["item_id"] for h_ in r.json()["results"]} == {in_range.id, span.id}
        only_from = client.get("/api/visitor/search", params={"q": "library board", "date_from": "1930-01-01"})
        assert {h_["item_id"] for h_ in only_from.json()["results"]} == {later.id}

    def test_search_rejects_malformed_date_filter(self, db, client):
        r = client.get("/api/visitor/search", params={"q": "library", "date_from": "1927-13-45"})
        assert r.status_code == 422

    @pytest.mark.parametrize("bad", [{"date_certainty": "maybe"}, {"date_start": "1929-13-01"},
                                     {"languages": ["english"]}, {"date_start": "1930-01-01",
                                                                  "date_end": "1929-01-01"},
                                     {"subjects": ["x" * 121]}])
    def test_invalid_metadata_is_rejected(self, db, client, bad):
        item = make_item(db, make_rights(db), ["text"])
        db.commit()
        h = _login(client, db, ["archivist"])
        r = client.put(f"/api/staff/items/{item.id}/metadata", json={**bad, "reason": "testing"}, headers=h)
        assert r.status_code == 422
        db.refresh(item)
        assert item.metadata_version == 1

    def test_unpublished_item_tags_are_not_exposed(self, db, client):
        item = make_item(db, make_rights(db), ["text"])
        db.commit()
        h = _login(client, db, ["archivist"])
        client.put(f"/api/staff/items/{item.id}/metadata", json={"subjects": ["Secret"], "reason": "tagging"},
                   headers=h)
        assert client.get("/api/visitor/facets").json()["subjects"] == []
        assert client.put(f"/api/staff/items/{item.id}/metadata", json={"subjects": ["x"]},
                          headers=h).status_code == 422  # reason required


# ------------------------------------------------------------------ 7. compile + QR take-away

class TestCompileAndQr:
    def _two_items(self, db):
        text = make_item(db, make_rights(db), ["Synthetic essay page about reading rooms."], title="Essay")
        publish_item(db, text)
        video, _ = _recording(db, make_rights(db, key="r2"))
        publish_item(db, video)
        return text, video

    def test_basket_of_item_passage_and_segment_gives_expiring_qr_read_only_page(self, db, client):
        text, video = self._two_items(db)
        pid = client.get(f"/api/visitor/items/{text.id}").json()["pages"][0]["passages"][0]["id"]
        entries = [{"item_id": text.id}, {"item_id": text.id, "passage_id": pid, "page": 1},
                   {"item_id": video.id, "start_ms": 4000}]
        before = dt.datetime.now(dt.UTC)

        r = client.post("/api/visitor/collections", json={"entries": entries, "language": "en"}).json()

        assert r["count"] == 3 and "<svg" in r["qr_svg"] and r["url"].endswith(f"/c/{r['token']}")
        expires = dt.datetime.fromisoformat(r["expires_at"])
        assert dt.timedelta(hours=23) < expires - before <= dt.timedelta(hours=24, minutes=1)
        shared = client.get(f"/api/visitor/collections/{r['token']}").json()
        assert len(shared["entries"]) == 3 and shared["removed_count"] == 0
        assert shared["entries"][1]["passage"]["passage_id"] == pid
        assert shared["entries"][2]["deep_link"] == f"/item/{video.id}?t=4000"
        assert all(e["rights_line"] == "Synthetic" for e in shared["entries"])

    def test_withdrawn_item_disappears_from_shared_list(self, db, client):
        text, video = self._two_items(db)
        token = client.post("/api/visitor/collections",
                            json={"entries": [{"item_id": text.id}, {"item_id": video.id}]}).json()["token"]
        publish.withdraw(db, db.get(ArchivalItem, video.id), "archivist", "rights holder request")
        db.commit()
        shared = client.get(f"/api/visitor/collections/{token}").json()
        assert [e["item"]["id"] for e in shared["entries"]] == [text.id] and shared["removed_count"] == 1

    def test_expired_link_is_gone_and_unpublished_items_are_refused(self, db, client):
        text, _ = self._two_items(db)
        draft = make_item(db, make_rights(db, key="r3"), ["draft"], title="Draft", approve=False)
        db.commit()
        assert client.post("/api/visitor/collections", json={"entries": [{"item_id": draft.id}]}).status_code == 400
        token = client.post("/api/visitor/collections", json={"entries": [{"item_id": text.id}]}).json()["token"]
        col = db.get(QrCollection, token)
        col.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        db.commit()
        assert client.get(f"/api/visitor/collections/{token}").status_code == 410

    def test_collection_body_accepts_no_personal_fields(self, db, client):
        text, _ = self._two_items(db)
        r = client.post("/api/visitor/collections",
                        json={"entries": [{"item_id": text.id}], "email": "a@b.c", "phone": "123"})
        assert r.status_code == 200
        stored = db.get(QrCollection, r.json()["token"])
        assert "a@b.c" not in str(stored.entries) and set(stored.entries[0]) <= {
            "item_id", "passage_id", "page", "start_ms", "note"}
