"""Unit tests for provider clients (wire protocol via httpx.MockTransport - a test double, not a live
integration), exhibit signing, manifest governance and dataset splitting."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from archive import exhibit
from archive.datasets.corpus import assign_split, eligibility
from archive.ingest.intake import IntakeRejected, sniff_format, validate_manifest
from archive.ingest.sarvam_ocr import SarvamDocAI, SarvamRejected, SarvamUnavailable, transcription_from_markdown

from .conftest import FIXTURES, sarvam_image_dump_markdown


def _zip_md(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("output/page.md", text)
    return buf.getvalue()


class TestSarvamDocAIWireProtocol:
    def test_digitise_create_poll_download(self):
        calls = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append((req.method, req.url.path))
            if req.url.host == "api.test":
                assert req.headers.get("api-subscription-key") == "k"
            else:
                assert "api-subscription-key" not in req.headers  # never leak the key to the file host
            if req.url.path.endswith("/job/digitise"):
                body = req.content.decode("latin-1")
                assert 'name="language"' in body and "hi-IN" in body and 'name="output_format"' in body
                return httpx.Response(200, json={"job_id": "j1", "status": "pending"})
            if req.url.path.endswith("/status"):
                return httpx.Response(200, json={"status": "completed"})
            if req.url.path.endswith("/download-url"):
                return httpx.Response(200, json={"method": "GET", "url": "https://files.test/j1.zip"})
            if req.url.host == "files.test":
                return httpx.Response(200, content=_zip_md("सार्वजनिक वाचनालय"))
            return httpx.Response(404)

        client = SarvamDocAI(api_key="k", base_url="https://api.test",
                             client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
        out = client.digitise_page(b"\x89PNG....", "hi")
        assert out.text == "सार्वजनिक वाचनालय" and out.job_id == "j1"
        assert [c[1] for c in calls][:3] == ["/doc-ai/v1/job/digitise", "/doc-ai/v1/job/j1/status",
                                            "/doc-ai/v1/job/j1/download-url"]

    def test_no_key_means_unavailable(self):
        with pytest.raises(SarvamUnavailable):
            SarvamDocAI(api_key="").digitise_page(b"x", "en")

    def test_server_errors_exhaust_retries_as_unavailable(self):
        client = SarvamDocAI(api_key="k", base_url="https://api.test", sleep=lambda s: None,
                             client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
        with pytest.raises(SarvamUnavailable):
            client.digitise_page(b"x", "en")

    def test_client_error_is_rejection(self):
        client = SarvamDocAI(api_key="k", base_url="https://api.test", sleep=lambda s: None,
                             client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad"))))
        with pytest.raises(SarvamRejected):
            client.digitise_page(b"x", "en")

    def test_image_dump_is_not_returned_as_ocr_text(self):
        raw = sarvam_image_dump_markdown()
        assert len(raw) > 100_000

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/job/digitise"):
                return httpx.Response(200, json={"job_id": "j2", "status": "completed"})
            if req.url.path.endswith("/download-url"):
                return httpx.Response(200, json={"method": "GET", "url": "https://files.test/j2.zip"})
            if req.url.host == "files.test":
                return httpx.Response(200, content=_zip_md(raw))
            return httpx.Response(404)

        client = SarvamDocAI(api_key="k", base_url="https://api.test",
                             client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
        out = client.digitise_page(b"\x89PNG....", "en")
        assert out.text == ""
        assert out.not_transcription and "no transcription" in out.not_transcription
        assert out.raw_markdown == raw  # kept for the reviewer, separately from the OCR text
        assert out.stripped["images_removed"] == 7 and out.stripped["description_blocks_removed"] == 14


class TestSarvamTranscriptionCleaning:
    def test_images_and_descriptions_are_stripped_around_real_text(self):
        real = "Friends, education is not a gift that one class hands to another.\nIt is a right."
        cleaned = transcription_from_markdown(sarvam_image_dump_markdown(transcription=real))
        assert cleaned.not_transcription is None
        assert cleaned.text == real
        assert "base64" not in cleaned.text and "data:image" not in cleaned.text
        assert "appears to be" not in cleaned.text

    def test_html_images_and_bare_base64_runs_are_removed(self):
        md = ('<img src="data:image/png;base64,' + "QUJD" * 100 + '">\n\n' + "Zm9v" * 80
              + "\n\n# LECTURE\n\nThe tank belongs to all who live beside it.")
        cleaned = transcription_from_markdown(md)
        assert cleaned.text == "# LECTURE\n\nThe tank belongs to all who live beside it."

    def test_plain_transcription_is_unchanged(self):
        text = "सार्वजनिक वाचनालय सकाळी नऊ वाजता उघडते"
        assert transcription_from_markdown(text).text == text


class TestExhibitSignature:
    def test_sign_and_verify_roundtrip_and_tamper_detection(self):
        payload = {"version": 3, "items": [{"id": 1}], "withdrawn": [7]}
        sig = exhibit.sign(payload)
        assert exhibit.verify_signature(payload, sig)
        tampered = {**payload, "withdrawn": []}
        assert not exhibit.verify_signature(tampered, sig)

    def test_signature_is_p1363_raw_64_bytes_for_webcrypto(self):
        import base64

        assert len(base64.b64decode(exhibit.sign({"a": 1}))) == 64


class TestManifestGovernance:
    def test_format_sniffing_rejects_unknown(self):
        assert sniff_format(b"%PDF-1.4 ...")[0] == "application/pdf"
        with pytest.raises(IntakeRejected):
            sniff_format(b"MZ\x90\x00 not an archive format")

    def test_real_source_template_is_refused_until_rights_are_decided(self):
        manifest = json.loads((FIXTURES / "manifests" / "example_real_sources.manifest.json").read_text("utf-8"))
        errors = validate_manifest(manifest)
        assert any("download_permitted" in e for e in errors)
        assert any("discovery/linking only" in e for e in errors)

    def test_fixture_manifest_is_valid(self):
        path = FIXTURES / "manifests" / "fixture_manifest.json"
        if not path.exists():
            pytest.skip("fixtures not generated yet")
        assert validate_manifest(json.loads(path.read_text("utf-8"))) == []

    def test_missing_rights_fields_rejected(self):
        manifest = {"rights": [{"source_key": "x", "display_permission": "maybe"}], "items": []}
        errors = validate_manifest(manifest)
        assert any("display_permission" in e for e in errors) and any("evidence missing" in e for e in errors)


class TestDatasetRules:
    def test_split_is_deterministic_and_work_level(self):
        groups = sorted(f"work-{i}" for i in range(10))
        first = {g: assign_split(g, groups) for g in groups}
        again = {g: assign_split(g, groups) for g in groups}
        assert first == again
        assert set(first.values()) <= {"train", "dev", "test"}
        assert "test" in first.values() and "train" in first.values()

    @pytest.mark.parametrize("training,kind,basis,expected", [
        ("allowed", "source_text", "spot_check", True),
        ("allowed", "reviewed_transcription", "full_review", True),
        ("allowed", "reviewed_transcription", "sampled_batch", True),
        ("not_allowed", "source_text", "full_review", False),
        ("unknown", "source_text", "full_review", False),
        ("allowed", "reviewed_translation", "full_review", False),
        ("allowed", "reviewed_caption", "full_review", False),
    ])
    def test_eligibility(self, training, kind, basis, expected):
        item = SimpleNamespace(rights=SimpleNamespace(training_permission=training, display_permission="allowed",
                                                      discovery_only=False),
                               publication_state="published", published_version_id=1)
        passage = SimpleNamespace(kind=kind, review_basis=basis, indexed=True, item_version_id=1)
        ok, _reason = eligibility(passage, item)
        assert ok is expected
