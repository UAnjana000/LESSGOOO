"""Database tests: OCR routing, review gates, staged publication, rights filtering, withdrawal, audit."""

from __future__ import annotations

import importlib.util
import random

import pytest
from sqlalchemy import select, text

from archive import audit, exhibit, storage
from archive.ingest import intake, processing, publish, review
from archive.ingest.quality import QualitySignals
from archive.ingest.sarvam_ocr import SarvamOcrOutput, SarvamRejected, transcription_from_markdown
from archive.models import AnswerCache, FileVersion, OcrResult, Page, Passage, StaffUser

from .conftest import FIXTURES, png_page, sarvam_image_dump_markdown
from .factories import make_item, make_rights, publish_item

pytestmark = pytest.mark.db

GOOD = QualitySignals(word_count=150, mean_confidence=93, p10_confidence=75, coverage=0.97, script_share=0.99,
                      lexicon_ratio=0.6, garbage_rate=0.01)
BAD = QualitySignals(word_count=150, mean_confidence=41, p10_confidence=8, coverage=0.5, script_share=0.8,
                     lexicon_ratio=0.1, garbage_rate=0.3)


def _fake_local(signals: QualitySignals, text: str = "local ocr text of the synthetic page"):
    """Test double for Tesseract (real Tesseract is covered by test_tesseract_real.py)."""
    def run(db, page, gray):
        res = OcrResult(page_id=page.id, engine="tesseract", engine_version="test-double", text=text, words=[],
                        mean_confidence=signals.mean_confidence)
        db.add(res)
        db.flush()
        return res, signals, None
    return run


class FakeFallback:
    def __init__(self, text="sarvam text of the synthetic page", exc: Exception | None = None):
        self.calls = 0
        self.text, self.exc = text, exc

    def digitise_page(self, image_png, language):
        self.calls += 1
        if self.exc:
            raise self.exc
        return SarvamOcrOutput(text=self.text, engine_version="fake-sarvam", job_id="fake-1", raw_status="completed")


def _intake_printed(db, rights, doc_class="printed", name="page.png", data=None):
    meta = {"item_key": f"k-{random.random()}", "rights_source_key": rights.source_key, "title": "Synthetic",
            "item_type": "printed_scan", "collection": "writings", "doc_class": doc_class, "languages": ["en"]}
    res = intake.intake_item(db, meta, [(name, data or png_page("Synthetic page"), None)], "tester")
    db.flush()
    return db.execute(select(Page).where(Page.item_id == res.item_id)).scalars().all(), res


class TestOcrRouting:
    def test_gate_pass_goes_to_sampled_batch_review(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(GOOD))
        pages, _ = _intake_printed(db, make_rights(db))
        out = processing.process_page(db, pages[0], FakeFallback())
        assert out.gate_passed and pages[0].status == "in_batch_review" and pages[0].review_mode == "sampled"
        assert pages[0].approved_text is None  # nothing is ever auto-approved

    def test_gate_fail_calls_sarvam_only_for_failed_page_and_requires_full_review(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(BAD))
        fb = FakeFallback()
        pages, _ = _intake_printed(db, make_rights(db))
        processing.process_page(db, pages[0], fb)
        assert fb.calls == 1
        assert pages[0].status == "needs_full_review" and pages[0].ocr_route == "sarvam"
        assert pages[0].approved_text is None
        engines = sorted(r.engine for r in db.execute(select(OcrResult).where(OcrResult.page_id == pages[0].id)).scalars())
        assert engines == ["sarvam-doc-ai", "tesseract"]

    def test_audit_chain_lock_is_released_during_sarvam_call(self, db, monkeypatch):
        # Arrange: a fallback that checks, from a second connection, whether the audit advisory lock is free
        from sqlalchemy import text

        from archive.db import get_engine

        monkeypatch.setattr(processing, "_run_local", _fake_local(BAD))
        seen = {}

        class ProbingFallback(FakeFallback):
            def digitise_page(self, image_png, language):
                with get_engine().connect() as other:
                    seen["lock_free"] = other.execute(text("SELECT pg_try_advisory_xact_lock(424242)")).scalar()
                    other.rollback()
                return super().digitise_page(image_png, language)

        pages, _ = _intake_printed(db, make_rights(db))

        # Act
        processing.process_page(db, pages[0], ProbingFallback())

        # Assert: staff actions that write audit rows are not blocked behind the external call
        assert seen["lock_free"] is True

    def test_gate_pass_never_calls_sarvam(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(GOOD))
        fb = FakeFallback()
        pages, _ = _intake_printed(db, make_rights(db))
        processing.process_page(db, pages[0], fb)
        assert fb.calls == 0

    def test_sarvam_unavailable_leaves_page_pending(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(BAD))
        pages, _ = _intake_printed(db, make_rights(db))
        processing.process_page(db, pages[0], None)
        assert pages[0].status == "sarvam_pending" and pages[0].approved_text is None

    def test_external_processing_not_permitted_skips_sarvam(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(BAD))
        fb = FakeFallback()
        pages, _ = _intake_printed(db, make_rights(db, external="not_allowed"))
        processing.process_page(db, pages[0], fb)
        assert fb.calls == 0 and pages[0].status == "needs_full_review"

    @staticmethod
    def _fallback_returning(raw: str) -> FakeFallback:
        cleaned = transcription_from_markdown(raw)
        fb = FakeFallback()
        fb.digitise_page = lambda image_png, language: SarvamOcrOutput(
            text=cleaned.text, engine_version="fake-sarvam", job_id="fake-2", raw_status="completed",
            raw_markdown=raw, not_transcription=cleaned.not_transcription, stripped=cleaned.stripped)
        return fb

    def test_sarvam_image_dump_is_not_stored_as_transcription(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(BAD))
        raw = sarvam_image_dump_markdown()
        fb = self._fallback_returning(raw)
        pages, _ = _intake_printed(db, make_rights(db))
        processing.process_page(db, pages[0], fb)
        page = pages[0]
        assert page.status == "needs_full_review" and page.review_mode == "full" and page.ocr_route == "local"
        assert page.approved_text is None and "no transcription" in page.sarvam_last_error
        sarvam = db.execute(select(OcrResult).where(OcrResult.page_id == page.id,
                                                    OcrResult.engine == "sarvam-doc-ai")).scalar_one()
        assert sarvam.status == "failed" and sarvam.text == "" and not sarvam.selected
        raw_file = db.get(FileVersion, sarvam.raw_meta["raw_file_id"])
        assert raw_file.role == "derivative" and raw_file.kind == "sarvam_raw"
        assert storage.read_bytes(raw_file.storage_uri).decode("utf-8") == raw
        assert review.candidate_text(page) == "local ocr text of the synthetic page"

    def test_sarvam_text_between_captions_is_kept_for_full_review(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(BAD))
        real = ("Lecture on Water and the Common Tank", "The common tank was dug by the labour of all its families.")
        raw = sarvam_image_dump_markdown(transcription=real)
        pages, _ = _intake_printed(db, make_rights(db))
        processing.process_page(db, pages[0], self._fallback_returning(raw))
        page = pages[0]
        assert page.status == "needs_full_review" and page.ocr_route == "sarvam" and page.approved_text is None
        sarvam = db.execute(select(OcrResult).where(OcrResult.page_id == page.id,
                                                    OcrResult.engine == "sarvam-doc-ai")).scalar_one()
        assert sarvam.status == "ok" and sarvam.text == "\n\n".join(real) and not sarvam.selected
        assert "disagreement" in sarvam.raw_meta and sarvam.raw_meta["images_removed"] == 7
        raw_file = db.get(FileVersion, sarvam.raw_meta["raw_file_id"])
        assert storage.read_bytes(raw_file.storage_uri).decode("utf-8") == raw

    def test_sarvam_rejection_routes_to_manual_transcription(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(BAD))
        pages, _ = _intake_printed(db, make_rights(db))
        processing.process_page(db, pages[0], FakeFallback(exc=SarvamRejected("400")))
        assert pages[0].status == "manual_transcription"

    def test_handwriting_goes_to_human_transcription(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(BAD))
        fb = FakeFallback()
        pages, _ = _intake_printed(db, make_rights(db), doc_class="handwritten")
        processing.process_page(db, pages[0], fb)
        assert pages[0].status == "manual_transcription" and fb.calls == 0

    def test_born_digital_uses_text_layer(self, db):
        spec = importlib.util.spec_from_file_location("genfx", FIXTURES / "generate_fixtures.py")
        genfx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(genfx)
        pdf = genfx.make_pdf(["Synthetic born digital page with a real text layer about reading rooms. " * 3])
        pages, _ = _intake_printed(db, make_rights(db), doc_class="born_digital", name="x.pdf", data=pdf)
        out = processing.process_page(db, pages[0], None)
        assert out.route == "text_layer" and pages[0].status == "in_batch_review"
        assert "reading rooms" in review.candidate_text(pages[0])


class TestIntakeGovernance:
    def test_exact_duplicate_detected_and_checksum_mismatch_quarantined(self, db):
        rights = make_rights(db)
        data = png_page("dup page")
        _, first = _intake_printed(db, rights, data=data)
        _, second = _intake_printed(db, rights, data=data)
        assert first.files[0].status == "stored" and second.files[0].status == "duplicate"
        meta = {"item_key": "bad", "rights_source_key": rights.source_key, "title": "x", "item_type": "printed_scan",
                "collection": "writings", "doc_class": "printed", "languages": ["en"]}
        res = intake.intake_item(db, meta, [("p.png", png_page("other"), "0" * 64)], "tester")
        assert res.files[0].status == "quarantined"

    def test_discovery_only_source_cannot_be_ingested(self, db):
        rights = make_rights(db, key="ndli", display="not_allowed", discovery=True)
        with pytest.raises(intake.IntakeRejected):
            _intake_printed(db, rights)

    def test_preservation_master_is_unchanged_and_readonly(self, db):
        data = png_page("master")
        _, res = _intake_printed(db, make_rights(db), data=data)
        fv = db.get(FileVersion, res.files[0].file_id)
        assert storage.read_bytes(fv.storage_uri) == data and storage.sha256_bytes(data) == fv.sha256
        with pytest.raises(PermissionError):
            storage.delete_delivery(fv.storage_uri)


class TestReviewAndPublicationGates:
    def test_unapproved_page_blocks_publication(self, db):
        item = make_item(db, make_rights(db), ["approved page one text", "second"], approve=False)
        review.review_page(db, item.pages[0], "approve", "r", "archivist", text="approved page one text")
        with pytest.raises(publish.PublicationError):
            publish.stage(db, item, "tester")

    def test_batch_pass_requires_every_sample_page_checked(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(GOOD))
        rights = make_rights(db)
        meta = {"item_key": "batch", "rights_source_key": rights.source_key, "title": "b", "item_type": "printed_scan",
                "collection": "writings", "doc_class": "printed", "languages": ["en"]}
        res = intake.intake_item(db, meta, [(f"p{i}.png", png_page(f"batch page {i}"), None) for i in range(6)], "t")
        pages = db.execute(select(Page).where(Page.item_id == res.item_id)).scalars().all()
        for p in pages:
            processing.process_page(db, p, None)
        batch = review.open_batch(db, pages[0].item, random.Random(1))
        assert len(batch.sample_page_ids) == 2  # ceil(6 * 0.2)
        with pytest.raises(review.ReviewError):
            review.decide_batch(db, batch, True, "archivist")
        review.decide_batch(db, batch, True, "archivist", sample_checks={pid: {} for pid in batch.sample_page_ids})
        assert all(p.status == "approved" and p.quality_signals["review_basis"] == "sampled_batch" for p in pages)

    def test_failed_batch_sends_every_page_to_full_review(self, db, monkeypatch):
        monkeypatch.setattr(processing, "_run_local", _fake_local(GOOD))
        pages, _ = _intake_printed(db, make_rights(db))
        processing.process_page(db, pages[0], None)
        batch = review.open_batch(db, pages[0].item)
        review.decide_batch(db, batch, False, "archivist", reason="too many errors")
        assert pages[0].status == "needs_full_review"

    def test_quote_verification_requires_explicit_confirmation(self, db):
        item = make_item(db, make_rights(db), ["approved page text"])
        with pytest.raises(review.ReviewError):
            review.verify_page_quotes(db, item.pages[0], "r", confirm_compared_with_scan=False)

    def test_staged_version_is_invisible_until_switch(self, db, client):
        item = make_item(db, make_rights(db), ["The reading room charged no fee for reading."], title="Staged")
        version = publish.stage(db, item, "tester")
        db.commit()
        assert client.get("/api/visitor/search", params={"q": "reading fee"}).json()["results"] == []
        assert client.get(f"/api/visitor/items/{item.id}").status_code == 404
        publish.verify(db, item, version)
        publish.switch(db, item, version, "tester")
        db.commit()
        hits = client.get("/api/visitor/search", params={"q": "reading fee"}).json()["results"]
        assert hits and hits[0]["item_id"] == item.id
        assert client.get(f"/api/visitor/items/{item.id}").status_code == 200

    def test_failed_verification_does_not_publish(self, db, client):
        item = make_item(db, make_rights(db), ["text that will not be published"])
        fv = db.get(FileVersion, item.pages[0].delivery_file_id)
        storage.resolve(fv.storage_uri).unlink()
        with pytest.raises(publish.PublicationError):
            publish_item(db, item)
        db.refresh(item)
        assert item.publication_state == "approved" and item.published_version_id is None

    def test_passages_carry_page_anchor_and_review_basis(self, db):
        item = make_item(db, make_rights(db), ["First page text.", "Second page text."])
        publish_item(db, item)
        ps = db.execute(select(Passage).where(Passage.item_id == item.id)).scalars().all()
        assert {p.page_id for p in ps} == {pg.id for pg in item.pages}
        assert all(p.review_basis == "full_review" and p.embedding is not None for p in ps)


class TestRightsFiltering:
    def test_unknown_display_rights_block_publication(self, db):
        item = make_item(db, make_rights(db, key="unk", display="unknown"), ["secret memo text"])
        with pytest.raises(publish.PublicationError):
            publish_item(db, item)

    def test_restricted_items_hidden_even_when_published(self, db, client):
        item = make_item(db, make_rights(db), ["restricted budget figures forty rupees"], access="restricted")
        publish_item(db, item)
        assert client.get(f"/api/visitor/items/{item.id}").status_code == 404
        assert client.get("/api/visitor/search", params={"q": "budget rupees"}).json()["results"] == []
        assert client.get(f"/api/visitor/files/{item.pages[0].delivery_file_id}").status_code == 404

    def test_online_only_item_visible_but_never_in_kiosk_cache(self, db, client):
        item = make_item(db, make_rights(db), ["online only gazette report"], access="public_online_only")
        publish_item(db, item)
        assert client.get(f"/api/visitor/items/{item.id}").status_code == 200
        manifest = exhibit.build_manifest(db)["payload"]
        assert item.id not in [e["item_id"] for e in manifest["items"]]

    def test_rights_register_change_withdraws_published_items(self, db, client):
        from archive.security import hash_password

        rights = make_rights(db, key="revocable")
        item = make_item(db, rights, ["text whose rights will be revoked"])
        publish_item(db, item)
        db.add(StaffUser(email="a@test", display_name="A", password_hash=hash_password("pw-123456"),
                         roles=["archivist"]))
        db.commit()
        token = client.post("/api/staff/login", json={"email": "a@test", "password": "pw-123456"}).json()["token"]
        body = {"source_key": "revocable", "title": "t", "source_institution": "s", "rights_holder": "h",
                "basis_for_use": "b", "display_permission": "not_allowed", "training_permission": "allowed",
                "external_processing": "allowed", "evidence": "letter", "attribution": "a",
                "date_checked": "2026-09-26", "checked_by": "a@test"}
        r = client.post("/api/staff/rights", json=body, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and r.json()["effects"]["withdrawn_items"] == [item.id]
        assert client.get(f"/api/visitor/items/{item.id}").status_code == 404

    def test_staff_endpoints_require_auth(self, client):
        assert client.get("/api/staff/items").status_code == 401


class TestWithdrawal:
    def test_withdrawal_blocks_immediately_then_cleanup_verifies(self, db, client):
        item = make_item(db, make_rights(db), ["withdrawable passage about lamps and oil"])
        publish_item(db, item)
        file_id = item.pages[0].delivery_file_id
        fv = db.get(FileVersion, file_id)
        db.add(AnswerCache(key="k", index_version=1, prompt_version="ask-v1", payload={}))
        db.commit()
        assert client.get(f"/api/visitor/files/{file_id}").status_code == 200

        publish.withdraw(db, item, "archivist", "rights holder request")
        db.commit()
        assert client.get(f"/api/visitor/items/{item.id}").status_code == 404
        assert client.get(f"/api/visitor/files/{file_id}").status_code == 404
        assert client.get("/api/visitor/search", params={"q": "lamps oil"}).json()["results"] == []
        assert item.id in client.get("/api/visitor/withdrawals").json()["withdrawn_item_ids"]
        assert item.id in exhibit.build_manifest(db)["payload"]["withdrawn_item_ids"]

        result = publish.withdraw_cleanup(db, item.id, "worker")
        db.commit()
        assert result["verified"]
        assert not storage.resolve(fv.storage_uri).exists()
        assert db.execute(select(Passage).where(Passage.item_id == item.id, Passage.indexed.is_(True))).first() is None
        assert db.get(AnswerCache, "k") is None
        # preservation master is kept
        master = db.execute(select(FileVersion).where(FileVersion.item_id == item.id,
                                                      FileVersion.role == "preservation_master")).scalars().first()
        assert storage.resolve(master.storage_uri).exists()


class TestAudit:
    def test_chain_verifies_and_rows_are_append_only(self, db):
        audit.record(db, "tester", "test.one", "x", 1)
        audit.record(db, "tester", "test.two", "x", 2)
        db.commit()
        ok, n = audit.verify_chain(db)
        assert ok and n >= 2
        with pytest.raises(Exception):
            db.execute(text("UPDATE audit_event SET actor='mallory'"))
            db.flush()
        db.rollback()
        with pytest.raises(Exception):
            db.execute(text("DELETE FROM audit_event"))
            db.flush()
        db.rollback()
