"""Voice questions on Ask: the visitor's recording is transcribed by the OpenAI-compatible
/audio/transcriptions endpoint (Whisper) through our API. The Whisper call is faked here."""

from __future__ import annotations

import io
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

import archive.ask.voice as voice_mod
from archive.api.main import app
from archive.config import get_settings

KEY = "test-key-not-real"
URL = "/api/visitor/ask/transcribe"


def wav(seconds: float, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(rate)
        w.writeframes(b"\x80" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def whisper(monkeypatch):
    """Configured key + a fake Whisper endpoint that records every request it receives."""
    calls: list[httpx.Request] = []
    reply = {"status": 200, "json": {"text": "  What did Ambedkar say about hero-worship?  "}}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(reply["status"], json=reply["json"])

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(voice_mod, "shared_client", lambda: fake)
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "openai_compatible")
    monkeypatch.setattr(s, "llm_base_url", "https://llm.test/v1")
    monkeypatch.setattr(s, "llm_api_key", KEY)
    yield calls, reply
    fake.close()


@pytest.fixture
def api():
    return TestClient(app)


def post(api: TestClient, data: bytes, language: str = "hi", name: str = "question.wav", mime: str = "audio/wav"):
    return api.post(URL, files={"file": (name, data, mime)}, data={"language": language})


def test_recording_is_transcribed_by_whisper_and_the_text_returned(whisper, api):
    calls, _ = whisper
    r = post(api, wav(3), language="hi")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "What did Ambedkar say about hero-worship?"
    assert body["model"] == "whisper-1" and body["stored"] is False
    assert len(calls) == 1
    req = calls[0]
    assert str(req.url) == "https://llm.test/v1/audio/transcriptions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    form = req.content.decode("latin-1")
    assert 'name="model"\r\n\r\nwhisper-1' in form
    assert 'name="language"\r\n\r\nhi' in form
    assert KEY not in r.text


def test_unsupported_language_is_not_sent_as_a_hint(whisper, api):
    calls, _ = whisper
    assert post(api, wav(1), language="fr").status_code == 200
    assert 'name="language"' not in calls[0].content.decode("latin-1")


def test_missing_key_is_a_clear_503_without_calling_whisper(whisper, api, monkeypatch):
    calls, _ = whisper
    monkeypatch.setattr(get_settings(), "llm_api_key", "")
    r = post(api, wav(1))
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "voice_unavailable"
    assert calls == []


def test_recording_over_the_time_limit_is_rejected_before_the_call(whisper, api):
    calls, _ = whisper
    r = post(api, wav(get_settings().ask_voice_max_seconds + 1))
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "too_long"
    assert calls == []


def test_oversized_upload_is_rejected_before_the_call(whisper, api, monkeypatch):
    calls, _ = whisper
    monkeypatch.setattr(get_settings(), "ask_voice_max_bytes", 4096)
    r = post(api, wav(1))  # 8 kB
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "too_large"
    assert calls == []


def test_whisper_failure_is_a_503_that_does_not_echo_the_provider_error(whisper, api):
    calls, reply = whisper
    reply.update(status=401, json={"error": {"message": f"Incorrect API key provided: {KEY}"}})
    r = post(api, wav(1))
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "voice_unavailable"
    assert KEY not in r.text and len(calls) == 1


def test_silence_that_transcribes_to_nothing_is_reported(whisper, api):
    _, reply = whisper
    reply.update(json={"text": "   "})
    r = post(api, wav(1))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "no_speech"
