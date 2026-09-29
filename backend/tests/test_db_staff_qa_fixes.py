"""Staff workspace API fixes from QA: photo intake, empty uploads, withdraw/restore, partial rights edits,
translation and summary review rules, 404/409/422 instead of 500, and the role recorded on decisions.
All content is synthetic."""

from __future__ import annotations

import io
import json
import os

import pytest
from PIL import Image
from sqlalchemy import func, select

from archive import storage
from archive.ingest import processing, publish, review
from archive.models import (
    ArchivalItem,
    AuditEvent,
    DatasetVersion,
    Derivative,
    FileVersion,
    OcrResult,
    Page,
    PageStatus,
    Passage,
    PhotoMetadata,
    ReviewDecision,
    RightsRecord,
    StaffUser,
    Translation,
)
from archive.security import hash_password

from .conftest import png_page
from .factories import make_item, make_rights, publish_item

pytestmark = pytest.mark.db

HI_TEXT = "कृत्रिम परीक्षण अनुवाद: वाचनालय सबके लिए खुला है।"


def _login(client, db, roles: list[str], email: str = "archivist@test", languages: list[str] | None = None):
    db.add(StaffUser(email=email, display_name=email, password_hash=hash_password("pw-123456"), roles=roles,
                     languages=languages or []))
    db.commit()
    token = client.post("/api/staff/login", json={"email": email, "password": "pw-123456"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client, h, files: list[tuple[str, bytes]], **meta):
    meta = {"title": "Synthetic upload", "item_type": "printed_scan", "collection": "writings",
            "doc_class": "printed", "languages": ["en"], "rights_source_key": "r-open", **meta}
    return client.post("/api/staff/intake", data={"metadata": json.dumps(meta)},
                       files=[("files", (name, data, "application/octet-stream")) for name, data in files],
                       headers=h)


def _published(db, client, text="The synthetic reading room is open to everyone."):
    item = make_item(db, make_rights(db), [text], title="Essay")
    publish_item(db, item)
    db.commit()
    pid = client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]["id"]
    return item, pid


class TestPhotoIntake:
    def test_photo_uploaded_without_caption_gets_a_draft_record_that_needs_a_caption(self, db, client):
        make_rights(db)
        h = _login(client, db, ["archivist"])
        r = _upload(client, h, [("photo.png", png_page("synthetic photograph"))], item_type="photograph",
                    collection="photographs", doc_class="photograph")
        assert r.status_code == 200
        item_id = r.json()["item_id"]
        photo = db.get(PhotoMetadata, item_id)
        assert photo is not None and photo.review_status == "draft" and photo.caption == ""

        assert client.post(f"/api/staff/photos/{item_id}/review", json={"action": "approve"},
                           headers=h).status_code == 409
        r = client.post(f"/api/staff/photos/{item_id}/review",
                        json={"action": "correct", "updates": {"caption": "Readers in a synthetic room."}}, headers=h)
        assert r.status_code == 200 and r.json()["status"] == "approved"


class TestEmptyUpload:
    def test_duplicate_upload_is_422_and_leaves_no_item(self, db, client):
        make_rights(db)
        h = _login(client, db, ["archivist"])
        data = png_page("duplicate me")
        assert _upload(client, h, [("a.png", data)]).status_code == 200
        items_before = db.execute(select(func.count()).select_from(ArchivalItem)).scalar()

        r = _upload(client, h, [("again.png", data)], item_key="dup-upload")
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["message"] == "No file was stored."
        assert [(f["name"], f["status"]) for f in detail["files"]] == [("again.png", "duplicate")]
        assert "exact duplicate" in detail["files"][0]["notes"]
        db.expire_all()
        assert db.execute(select(func.count()).select_from(ArchivalItem)).scalar() == items_before
        ev = db.execute(select(AuditEvent).where(AuditEvent.action == "file.duplicate")).scalars().all()
        assert [(e.entity, e.entity_id) for e in ev] == [("intake_upload", "dup-upload")]

    def test_quarantined_upload_is_422_without_server_paths(self, db, client):
        make_rights(db)
        h = _login(client, db, ["archivist"])
        r = _upload(client, h, [("notes.txt", b"plain text is not an archive format")])
        assert r.status_code == 422
        f = r.json()["detail"]["files"][0]
        assert f["status"] == "quarantined" and "quarantined" in f["notes"]
        assert "/" not in f["notes"] and os.environ["ARCHIVE_QUARANTINE_ROOT"] not in json.dumps(r.json())
        assert db.execute(select(func.count()).select_from(ArchivalItem)).scalar() == 0
        assert db.execute(select(AuditEvent.entity).where(AuditEvent.action == "file.quarantine")).scalar() \
            == "intake_upload"


class TestWithdrawRestore:
    def test_never_published_item_cannot_be_withdrawn(self, db, client):
        item = make_item(db, make_rights(db), ["Draft text."], approve=False)
        db.commit()
        h = _login(client, db, ["archivist"])
        r = client.post(f"/api/staff/items/{item.id}/withdraw", json={"reason": "mistake"}, headers=h)
        assert r.status_code == 409 and "only published items" in r.json()["detail"]
        db.refresh(item)
        assert item.publication_state != "withdrawn"

    def test_pdf_backed_item_withdraws_and_restores(self, db, client):
        rights = make_rights(db)
        item = make_item(db, rights, [], title="PDF item", approve=False)
        buf = io.BytesIO()
        pages = [Image.new("L", (400, 500), 250), Image.new("L", (300, 450), 200)]
        pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
        stored = storage.put_bytes(buf.getvalue(), "preservation_master", ".pdf")
        master = FileVersion(item_id=item.id, role="preservation_master", kind="original", format="application/pdf",
                             byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri)
        db.add(master)
        db.flush()
        for i in range(2):
            page = Page(item_id=item.id, sequence=i + 1, image_file_id=master.id, doc_class="printed", language="en",
                        status=PageStatus.needs_full_review.value, ocr_route="local",
                        preprocessing_params={"pdf_page_index": i})
            db.add(page)
            db.flush()
            processing._store_delivery(db, page, processing._page_image(db, page)[0], master.id)
            review.review_page(db, page, "approve", "tester", "archivist", text=f"Synthetic PDF page {i + 1}.")
        db.refresh(item)
        publish_item(db, item)
        db.commit()
        file_ids = [p.delivery_file_id for p in item.pages]
        h = _login(client, db, ["archivist"])

        assert client.post(f"/api/staff/items/{item.id}/withdraw", json={"reason": "check"}, headers=h).status_code \
            == 200
        db.expire_all()
        publish.withdraw_cleanup(db, item.id, "worker")
        db.commit()
        r = client.post(f"/api/staff/items/{item.id}/restore", json={"reason": "checked"}, headers=h)
        assert r.status_code == 200 and r.json()["state"] == "published"
        db.expire_all()
        for fid, size in zip(file_ids, [(800, 1000), (600, 900)], strict=True):
            fv = db.get(FileVersion, fid)
            assert fv.deleted_at is None
            assert Image.open(io.BytesIO(storage.read_bytes(fv.storage_uri))).size == size  # one page, rendered
            assert client.get(f"/api/visitor/files/{fid}").status_code == 200


class TestRightsPartialEdit:
    def test_edit_changes_only_sent_fields_and_audits_before_after(self, db, client):
        h = _login(client, db, ["archivist"])
        full = {"source_key": "r-edit", "title": "Synthetic source", "source_institution": "Test library",
                "rights_holder": "Test", "basis_for_use": "test", "display_permission": "allowed",
                "training_permission": "not_allowed", "external_processing": "allowed", "evidence": "letter",
                "attribution": "Courtesy test", "date_checked": "2026-09-01", "checked_by": "tester",
                "notes": "keep me", "source_url": "https://example.test/src"}
        assert client.post("/api/staff/rights", json=full, headers=h).status_code == 200

        r = client.post("/api/staff/rights", json={"source_key": "r-edit", "attribution": "Courtesy test 2"},
                        headers=h)
        assert r.status_code == 200
        rights = r.json()["rights"]
        assert rights["attribution"] == "Courtesy test 2"
        assert rights["notes"] == "keep me" and rights["source_url"] == "https://example.test/src"
        assert rights["display_permission"] == "allowed" and rights["external_processing"] == "allowed"
        ev = db.execute(select(AuditEvent).where(AuditEvent.action == "rights.update")).scalar_one()
        assert ev.detail["before"] == {"attribution": "Courtesy test"}
        assert ev.detail["after"] == {"attribution": "Courtesy test 2"}

        assert client.post("/api/staff/rights", json={"source_key": "r-edit", "title": None},
                           headers=h).status_code == 422
        assert client.post("/api/staff/rights", json={"source_key": "r-new", "title": "Only a title"},
                           headers=h).status_code == 422
        assert db.execute(select(RightsRecord).where(RightsRecord.source_key == "r-new")).scalar() is None


class TestTranslationReview:
    def test_target_language_is_checked(self, db, client):
        _, pid = _published(db, client)
        h = _login(client, db, ["archivist"])
        for lang in ("en", "fr", "hindi-long"):
            r = client.post("/api/staff/translations", json={"source_passage_id": pid, "target_language": lang,
                                                            "text": "x"}, headers=h)
            assert r.status_code == 422, lang

    @pytest.mark.parametrize("roles,expected", [(["archivist"], "archivist"), (["admin"], "admin")])
    def test_archivist_and_admin_review_any_language_under_their_role(self, db, client, roles, expected):
        _, pid = _published(db, client)
        h = _login(client, db, roles)
        tr = client.post("/api/staff/translations", json={"source_passage_id": pid, "target_language": "hi",
                                                          "text": HI_TEXT}, headers=h).json()["id"]
        r = client.post(f"/api/staff/translations/{tr}/review", json={"action": "approve"}, headers=h)
        assert r.status_code == 200 and r.json()["status"] == "approved"
        rd = db.execute(select(ReviewDecision).where(ReviewDecision.target_type == "translation")).scalar_one()
        assert rd.role == expected
        assert client.post(f"/api/staff/translations/{tr}/review", json={"action": "approve"},
                           headers=h).status_code == 409

    def test_rejecting_a_published_translation_takes_it_down(self, db, client):
        item, pid = _published(db, client)
        archivist = _login(client, db, ["archivist"])
        hindi = _login(client, db, ["translation_reviewer"], "hi@test", ["hi"])
        tr = client.post("/api/staff/translations", json={"source_passage_id": pid, "target_language": "hi",
                                                          "text": HI_TEXT}, headers=archivist).json()["id"]
        assert client.post(f"/api/staff/translations/{tr}/review", json={"action": "approve"},
                           headers=hindi).status_code == 200
        publish.publish_item(db, db.get(ArchivalItem, item.id), "tester")
        db.commit()
        assert client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]["translations"]["hi"]
        idx = publish.current_index_version(db)

        assert client.post(f"/api/staff/translations/{tr}/review", json={"action": "reject"},
                           headers=hindi).status_code == 200
        assert client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]["translations"] == {}
        hits = client.get("/api/visitor/search", params={"q": "वाचनालय", "lang": "hi"}).json()["results"]
        assert not any(h["kind_label"] == "Reviewed translation" for h in hits)
        db.expire_all()
        assert publish.current_index_version(db) == idx + 1
        for action in ("approve", "reject"):
            assert client.post(f"/api/staff/translations/{tr}/review", json={"action": action},
                               headers=hindi).status_code == 409

        # A withdraw/restore cycle does not bring the rejected translation back.
        client.post(f"/api/staff/items/{item.id}/withdraw", json={"reason": "check"}, headers=archivist)
        db.expire_all()
        publish.withdraw_cleanup(db, item.id, "worker")
        db.commit()
        assert client.post(f"/api/staff/items/{item.id}/restore", json={"reason": "checked"},
                           headers=archivist).status_code == 200
        assert client.get(f"/api/visitor/items/{item.id}").json()["pages"][0]["passages"][0]["translations"] == {}


class TestSummaries:
    def test_ai_draft_keeps_honest_label_and_newer_approval_supersedes(self, db, client):
        item, _ = _published(db, client)
        h = _login(client, db, ["archivist"])
        ai = Derivative(kind="summary", item_id=item.id, language="en", content="Model draft.", generator="test-llm",
                        status="draft", label_shown="AI-generated summary")
        db.add(ai)
        db.commit()
        r = client.post(f"/api/staff/derivatives/{ai.id}/review", json={"action": "approve"}, headers=h)
        assert r.json()["label"] == "AI-drafted summary, reviewed by archive staff"
        assert client.post(f"/api/staff/derivatives/{ai.id}/review", json={"action": "approve"},
                           headers=h).status_code == 409

        human = client.post(f"/api/staff/items/{item.id}/summary", json={"text": "Staff summary."}, headers=h).json()
        r = client.post(f"/api/staff/derivatives/{human['id']}/review", json={"action": "approve"}, headers=h)
        assert r.json()["label"] == "Reviewed summary"
        db.expire_all()
        assert db.get(Derivative, ai.id).status == "superseded"
        assert client.get(f"/api/visitor/items/{item.id}").json()["summaries"] == [
            {"language": "en", "text": "Staff summary.", "label": "Reviewed summary", "quote_verified": False}]

        # reject -> approve is a repeat decision
        d = client.post(f"/api/staff/items/{item.id}/summary", json={"text": "Another."}, headers=h).json()["id"]
        assert client.post(f"/api/staff/derivatives/{d}/review", json={"action": "reject"}, headers=h).status_code \
            == 200
        assert client.post(f"/api/staff/derivatives/{d}/review", json={"action": "approve"}, headers=h).status_code \
            == 409

    def test_draft_with_ai_separates_rights_refusal_from_missing_model(self, db, client):
        blocked = make_item(db, make_rights(db, key="r-closed", external="not_allowed"), ["Approved text."],
                            title="Closed")
        open_item = make_item(db, make_rights(db), ["Approved text."], title="Open")
        db.commit()
        h = _login(client, db, ["archivist"])
        r = client.post(f"/api/staff/items/{blocked.id}/summary", json={}, headers=h)
        assert r.status_code == 409
        assert r.json()["detail"] == "External processing is not permitted for this item's rights entry."
        r = client.post(f"/api/staff/items/{open_item.id}/summary", json={}, headers=h)
        assert r.status_code == 503 and "No answer model" in r.json()["detail"]


class TestNarrationVersion:
    def test_superseded_passage_is_refused(self, db, client):
        item, pid = _published(db, client)
        page = item.pages[0]
        review.reopen_page(db, page, "tester", "correction")
        review.review_page(db, page, "approve", "tester", "archivist", text="A corrected synthetic reading room.")
        publish_item(db, db.get(ArchivalItem, item.id))
        db.commit()
        assert db.get(Passage, pid).item_version_id != db.get(ArchivalItem, item.id).published_version_id
        h = _login(client, db, ["archivist"])
        r = client.post("/api/staff/narration", json={"passage_id": pid, "language": "en"}, headers=h)
        assert r.status_code == 409 and "superseded" in r.json()["detail"]


class TestSarvamSelection:
    def test_sarvam_result_is_the_review_baseline(self, db, monkeypatch):
        from archive.ingest.sarvam_ocr import SarvamOcrOutput

        item = make_item(db, make_rights(db), [], title="Sarvam item", approve=False)
        data = png_page("sarvam page")
        stored = storage.put_bytes(data, "preservation_master", ".png")
        fv = FileVersion(item_id=item.id, role="preservation_master", kind="original", format="image/png",
                         byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri)
        db.add(fv)
        db.flush()
        page = Page(item_id=item.id, sequence=1, image_file_id=fv.id, doc_class="printed", language="en",
                    status=PageStatus.sarvam_pending.value, ocr_route="local")
        db.add(page)
        db.flush()
        db.add(OcrResult(page_id=page.id, engine="tesseract", engine_version="t", text="local draft", selected=True))
        db.commit()

        class Fallback:
            def digitise_page(self, image_png, language):
                return SarvamOcrOutput(text="sarvam text", engine_version="fake-sarvam", job_id="j1",
                                       raw_status="completed")

        processing.run_sarvam(db, page, Fallback())
        db.commit()
        db.refresh(page)
        assert [(r.engine, r.selected) for r in page.ocr_results] == [("tesseract", False), ("sarvam-doc-ai", True)]
        review.review_page(db, page, "correct", "tester", "archivist", text="final text")
        rd = db.execute(select(ReviewDecision).where(ReviewDecision.target_id == page.id)).scalar_one()
        assert rd.before == "sarvam text"


class TestErrorCodes:
    @pytest.mark.parametrize("path,body", [
        ("/api/staff/timeline/999999/approve", None),
        ("/api/staff/map/nodes/999999/approve", None),
        ("/api/staff/map/edges/999999/approve", None),
        ("/api/staff/translations/999999/review", {"action": "approve"}),
        ("/api/staff/segments/999999/review", {"action": "approve"}),
        ("/api/staff/segments/999999/verify-quotes", {"confirm": True}),
        ("/api/staff/batches/999999/decide", {"passed": True}),
        ("/api/staff/pages/999999/reopen", None),
        ("/api/staff/pages/999999/verify-quotes", {"confirm": True}),
        ("/api/staff/items/999999/publish", None),
        ("/api/staff/derivatives/999999/review", {"action": "approve"}),
        ("/api/staff/translations", {"source_passage_id": 999999, "target_language": "hi", "text": "x"}),
    ])
    def test_missing_ids_are_404(self, db, client, path, body):
        h = _login(client, db, ["admin"])
        r = client.post(path, json=body, headers=h) if body is not None else client.post(path, headers=h)
        assert r.status_code == 404

    def test_validation_and_conflicts(self, db, client):
        item = make_item(db, make_rights(db), ["Curated text."])
        db.commit()
        h = _login(client, db, ["admin"])
        ev = {"date_text": "1921", "sort_date": "1921-01-01", "titles": {"en": "E"}, "item_ids": [item.id]}
        story = {"slug": "s1", "titles": {"en": "S"}, "blocks": [{"item_id": item.id}]}
        node = {"node_type": "concept", "labels": {"en": "n"}, "item_ids": [item.id]}
        for path, body in [("/api/staff/timeline", {**ev, "status": "banana"}),
                           ("/api/staff/timeline", {**ev, "date_certainty": "maybe"}),
                           ("/api/staff/stories", {**story, "status": "published"}),
                           ("/api/staff/stories", {**story, "slug": "s" * 81}),
                           ("/api/staff/stories", {**story, "blocks": [{"item_id": str(item.id)}]}),
                           ("/api/staff/stories", {**story, "blocks": [{"captions": {"en": "no item"}}]}),
                           ("/api/staff/map/nodes", {**node, "node_type": "x" * 31})]:
            assert client.post(path, json=body, headers=h).status_code == 422, body
        assert client.put("/api/staff/collections/novels", params={"machine_translation_enabled": False},
                          headers=h).status_code == 422
        assert client.put("/api/staff/collections/" + "w" * 21, params={"machine_translation_enabled": False},
                          headers=h).status_code == 422
        assert client.put("/api/staff/collections/writings", params={"machine_translation_enabled": False},
                          headers=h).status_code == 200

        assert client.post("/api/staff/stories", json=story, headers=h).status_code == 200
        assert client.post("/api/staff/stories", json=story, headers=h).status_code == 409
        e = client.post("/api/staff/timeline", json=ev, headers=h).json()["id"]
        assert client.post(f"/api/staff/timeline/{e}/approve", headers=h).status_code == 200
        assert client.post(f"/api/staff/timeline/{e}/approve", headers=h).status_code == 409
        n = client.post("/api/staff/map/nodes", json=node, headers=h).json()["id"]
        assert client.post(f"/api/staff/map/nodes/{n}/approve", headers=h).status_code == 200
        assert client.post(f"/api/staff/map/nodes/{n}/approve", headers=h).status_code == 409

        db.add(DatasetVersion(name="frozen-1", manifest={}, manifest_sha256="0" * 64, languages=["en"],
                              item_count=0, passage_count=0, created_by="tester"))
        db.commit()
        assert client.post("/api/staff/datasets", data={"name": "frozen-1"}, headers=h).status_code == 409
        assert client.post("/api/staff/datasets", data={"name": "d" * 81}, headers=h).status_code == 422


class TestDecisionRole:
    @pytest.mark.parametrize("roles,expected", [(["reviewer", "archivist"], "archivist"),
                                                (["admin", "archivist", "curator", "reviewer"], "admin")])
    def test_archivist_gated_decisions_record_the_admitting_role(self, db, client, roles, expected):
        item = make_item(db, make_rights(db), ["Role page."], approve=False)
        db.commit()
        h = _login(client, db, roles)
        assert client.post(f"/api/staff/pages/{item.pages[0].id}/review",
                           json={"action": "approve", "text": "Role page."}, headers=h).status_code == 200
        rd = db.execute(select(ReviewDecision).where(ReviewDecision.reviewer == "archivist@test")).scalar_one()
        assert rd.role == expected
