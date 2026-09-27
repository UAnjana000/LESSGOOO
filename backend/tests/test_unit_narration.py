"""Narration rules that need no database (spec 1.1, 5.5): what may be narrated, the Sarvam TTS wire contract
(generic stock voice, separate switch from OCR fallback) and the espeak-ng offline engine. Sarvam is reached
through httpx.MockTransport and espeak-ng through a fake process: test doubles, not live engines."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from archive.config import Settings
from archive.models import AnswerCache, Derivative, Passage, Translation
from archive.services import narration, sarvam_text

# bulbul:v3 stock speakers, docs.sarvam.ai/api-reference-docs/text-to-speech/convert (checked 2026-09-27).
SARVAM_V3_STOCK_SPEAKERS = {
    "shubh", "aditya", "ritu", "priya", "neha", "rahul", "pooja", "rohan", "simran", "kavya", "amit", "dev",
    "ishita", "shreya", "ratan", "varun", "manan", "sumit", "roopa", "kabir", "aayan", "ashutosh", "advait",
    "anand", "tanya", "tarun", "sunny", "mani", "gokul", "vijay", "shruti", "suhani", "mohit", "kavitha", "rehan",
    "soham", "rupali",
}
DOCUMENTED_TTS_FIELDS = {"text", "language_code", "speaker", "pitch", "pace", "loudness", "speech_sample_rate",
                         "enable_preprocessing", "model", "output_audio_codec", "temperature", "dict_id",
                         "enable_cached_responses"}
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "


def _passage(kind: str, language: str = "en", text: str = "The reading room is open to everyone.") -> Passage:
    return Passage(id=7, item_id=1, item_version_id=1, page_id=1, kind=kind, text=text, text_hash="a" * 64,
                   text_version=1, language=language, review_basis="full_review", approved_by="reviewer",
                   indexed=True)


@pytest.fixture
def tts_calls(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_synthesize(text, language, client=None):
        calls.append((text, language))
        return WAV, "sarvam-tts bulbul:v3 speaker=ritu"

    monkeypatch.setattr(sarvam_text, "synthesize", fake_synthesize)
    monkeypatch.setattr(narration, "espeak", lambda text, language: calls.append((text, language)) or (WAV, "e"))
    return calls


class TestOnlyApprovedTextOrReviewedTranslationIsNarrated:
    @pytest.mark.parametrize("source", [
        pytest.param(Translation(id=3, source_passage_id=7, target_language="hi", text="मशीन अनुवाद",
                                 method="machine", provider="sarvam", status="unreviewed"),
                     id="unreviewed-machine-translation"),
        pytest.param(Derivative(id=4, kind="summary", item_id=1, language="en", content="A summary.",
                                generator="llm", status="draft", label_shown="AI-generated summary"),
                     id="summary-not-yet-reviewed"),
        pytest.param(AnswerCache(key="k" * 64, index_version=1, prompt_version="ask-v1",
                                 payload={"answer": "An AI answer.", "language": "en"}),
                     id="ai-answer"),
        pytest.param("An AI-generated answer from archive sources.", id="ai-answer-text"),
        pytest.param(_passage("reviewed_caption"), id="photo-caption"),
        pytest.param(_passage("machine_translation", "hi"), id="machine-translation-kind"),
    ])
    def test_refused_before_any_speech_engine_runs(self, source, tts_calls):
        with pytest.raises(narration.NarrationError):
            narration.narrate_passage(None, source, "hi" if isinstance(source, Translation) else "en", "tester")
        assert tts_calls == []

    def test_language_must_match_the_approved_text(self, tts_calls):
        with pytest.raises(narration.NarrationError, match="language"):
            narration.narrate_passage(None, _passage("source_text", "en"), "hi", "tester")
        assert tts_calls == []


def _settings(**kw) -> Settings:
    return Settings(sarvam_api_key="k", sarvam_base_url="https://api.test", **kw)


def _sarvam(monkeypatch, handler, **settings) -> httpx.Client:
    monkeypatch.setattr(sarvam_text, "get_settings", lambda: _settings(**settings))
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestSarvamTTSWireContract:
    def test_generic_stock_voice_no_cloning_inputs_and_engine_version_in_generator(self, monkeypatch):
        seen = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen.append((req.url.path, req.headers.get("api-subscription-key"), json.loads(req.content)))
            return httpx.Response(200, json={"request_id": "r1", "audios": [base64.b64encode(WAV).decode()]})

        audio, generator = sarvam_text.synthesize("वाचनालय सबके लिए खुला है।", "hi", _sarvam(monkeypatch, handler))

        path, key, body = seen[0]
        assert path == "/text-to-speech" and key == "k" and audio == WAV
        assert body["speaker"] in SARVAM_V3_STOCK_SPEAKERS
        assert set(body) <= DOCUMENTED_TTS_FIELDS  # no reference audio / voice sample: nothing to clone from
        assert body["language_code"] == "hi-IN" and body["model"] == "bulbul:v3"
        assert "sarvam" in generator and "bulbul:v3" in generator and body["speaker"] in generator

    def test_tts_is_its_own_switch_not_gated_by_ocr_fallback_settings(self, monkeypatch):
        def ok(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"request_id": "r", "audios": [base64.b64encode(WAV).decode()]})

        assert sarvam_text.synthesize("Text.", "en", _sarvam(monkeypatch, ok, sarvam_ocr_enabled=False))[0] == WAV
        with pytest.raises(sarvam_text.ServiceUnavailable):
            sarvam_text.synthesize("Text.", "en", _sarvam(monkeypatch, ok, sarvam_tts_enabled=False))

    @pytest.mark.parametrize("response", [
        httpx.Response(500, json={"error": {"message": "internal", "code": "internal_server_error"}}),
        httpx.Response(429, json={"error": {"message": "quota", "code": "insufficient_quota_error"}}),
        httpx.Response(200, json={"request_id": "r", "error": "unexpected shape"}),
        httpx.Response(200, json={"request_id": "r", "audios": []}),
        httpx.Response(200, json={"request_id": "r", "audios": ["not base64 !!"]}),
        httpx.Response(200, text="<html>gateway</html>"),
    ], ids=["500", "429", "no-audios-key", "empty-audios", "bad-base64", "not-json"])
    def test_any_failure_is_service_unavailable_so_the_caller_can_fall_back(self, monkeypatch, response):
        with pytest.raises(sarvam_text.ServiceUnavailable):
            sarvam_text.synthesize("Text.", "en", _sarvam(monkeypatch, lambda req: response))


class _FakeEspeak:
    """Stands in for the espeak-ng binary: answers --version and writes a WAV to the -w path."""

    def __init__(self, fail: bool = False):
        self.fail, self.calls = fail, []

    def __call__(self, args, **kw):
        self.calls.append((list(args), kw.get("input")))
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="eSpeak NG text-to-speech: 1.51  Data at: /usr/share\n")
        if self.fail:
            raise subprocess.CalledProcessError(1, args)
        Path(args[args.index("-w") + 1]).write_bytes(WAV)
        return subprocess.CompletedProcess(args, 0)


class TestEspeakOfflineEngine:
    def test_generator_names_engine_version_and_generic_language_voice(self, monkeypatch):
        fake = _FakeEspeak()
        monkeypatch.setattr(narration.shutil, "which", lambda name: "/usr/bin/espeak-ng")
        monkeypatch.setattr(narration.subprocess, "run", fake)

        wav, generator = narration.espeak("सार्वजनिक वाचनालय", "mr")

        assert wav == WAV
        assert generator == "espeak-ng 1.51 voice=mr"

    def test_text_goes_on_stdin_so_a_leading_dash_is_spoken_not_parsed_as_an_option(self, monkeypatch):
        fake = _FakeEspeak()
        monkeypatch.setattr(narration.shutil, "which", lambda name: "/usr/bin/espeak-ng")
        monkeypatch.setattr(narration.subprocess, "run", fake)
        text = "-v Article 17 abolishes untouchability."

        narration.espeak(text, "en")

        speak_args, stdin = next(c for c in fake.calls if "-w" in c[0])
        assert text not in speak_args and stdin == text.encode("utf-8")

    def test_missing_binary_is_a_clear_unavailable_state(self, monkeypatch):
        monkeypatch.setattr(narration.shutil, "which", lambda name: None)
        with pytest.raises(narration.NarrationUnavailable):
            narration.espeak("Text.", "en")

    def test_engine_crash_is_unavailable_not_an_unhandled_error(self, monkeypatch):
        monkeypatch.setattr(narration.shutil, "which", lambda name: "/usr/bin/espeak-ng")
        monkeypatch.setattr(narration.subprocess, "run", _FakeEspeak(fail=True))
        with pytest.raises(narration.NarrationUnavailable):
            narration.espeak("Text.", "en")
