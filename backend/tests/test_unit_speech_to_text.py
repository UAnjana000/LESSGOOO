"""Sarvam speech-to-text client: wire contract through httpx.MockTransport (a test double, not the live
service), audio splitting for the REST endpoint's 30-second limit, and upload format sniffing."""

from __future__ import annotations

import io
import itertools
import math
import shutil
import struct
import wave

import httpx
import pytest

from archive.config import Settings
from archive.ingest import intake
from archive.services import speech_to_text as stt

DOCUMENTED_FIELDS = {"file", "model", "mode", "language_code", "with_timestamps", "input_audio_codec", "keyterms"}


def wav_bytes(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(n)))
    return buf.getvalue()


def _settings(**kw) -> Settings:
    return Settings(sarvam_api_key="test-key-not-real", sarvam_base_url="https://api.test", **kw)


def _client(monkeypatch, handler, **settings) -> httpx.Client:
    monkeypatch.setattr(stt, "get_settings", lambda: _settings(**settings))
    return httpx.Client(transport=httpx.MockTransport(handler))


def _fields(req: httpx.Request) -> dict[str, str]:
    """Form fields of a multipart request (file part reported as its filename)."""
    boundary = req.headers["content-type"].split("boundary=")[1].encode()
    out = {}
    for part in req.content.split(b"--" + boundary):
        head, _, body = part.partition(b"\r\n\r\n")
        if b'name="' not in head:
            continue
        name = head.split(b'name="')[1].split(b'"')[0].decode()
        if b"filename=" in head:
            out[name] = head.split(b'filename="')[1].split(b'"')[0].decode()
        else:
            out[name] = body.rstrip(b"\r\n").decode()
    return out


CHUNKS = [stt.AudioChunk(0, 25000, wav_bytes(0.1), "part00000.wav", "audio/wav"),
          stt.AudioChunk(25000, 31000, wav_bytes(0.1), "part00001.wav", "audio/wav")]


class TestWireContract:
    def test_posts_each_part_to_the_documented_endpoint_with_language_and_timestamps(self, monkeypatch):
        seen = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen.append((req.method, req.url.path, req.headers.get("api-subscription-key"), _fields(req)))
            return httpx.Response(200, json={"request_id": f"r{len(seen)}", "transcript": "नमस्ते सभा",
                                             "language_code": "hi-IN"})

        result = stt.transcribe_chunks(CHUNKS, "hi", client=_client(monkeypatch, handler), sleep=lambda s: None)

        assert [(m, p, k) for m, p, k, _ in seen] == [("POST", "/speech-to-text", "test-key-not-real")] * 2
        fields = seen[0][3]
        assert set(fields) <= DOCUMENTED_FIELDS
        assert fields["model"] == stt.STT_MODEL and fields["mode"] == stt.STT_MODE
        assert fields["language_code"] == "hi-IN" and fields["with_timestamps"] == "true"
        assert fields["file"] == "part00000.wav"
        assert result.request_ids == ["r1", "r2"] and result.language == "hi"

    def test_unknown_language_lets_sarvam_detect_it(self, monkeypatch):
        seen = []

        def handler(req):
            seen.append(_fields(req))
            return httpx.Response(200, json={"request_id": "r", "transcript": "hello", "language_code": "en-IN"})

        result = stt.transcribe_chunks(CHUNKS[:1], None, client=_client(monkeypatch, handler), sleep=lambda s: None)
        assert seen[0]["language_code"] == "unknown" and result.language == "en"

    def test_timestamps_become_segments_offset_by_the_part_start(self, monkeypatch):
        def handler(req):
            return httpx.Response(200, json={
                "request_id": "r", "transcript": "one two", "language_code": "en-IN",
                "timestamps": {"words": ["One.", " Two."], "start_time_seconds": [0.0, 2.5],
                               "end_time_seconds": [2.4, 5.0]}})

        result = stt.transcribe_chunks(CHUNKS, "en", client=_client(monkeypatch, handler), sleep=lambda s: None)

        assert [(s.start_ms, s.end_ms, s.text) for s in result.segments] == [
            (0, 2400, "One."), (2500, 5000, "Two."), (25000, 27400, "One."), (27500, 30000, "Two.")]

    def test_without_timestamps_each_part_is_one_segment(self, monkeypatch):
        def handler(req):
            return httpx.Response(200, json={"request_id": "r", "transcript": " spoken words ", "language_code": None})

        result = stt.transcribe_chunks(CHUNKS, "mr", client=_client(monkeypatch, handler), sleep=lambda s: None)

        assert [(s.start_ms, s.end_ms, s.text, s.language) for s in result.segments] == [
            (0, 25000, "spoken words", "mr"), (25000, 31000, "spoken words", "mr")]

    def test_silent_parts_make_no_segments(self, monkeypatch):
        def handler(req):
            return httpx.Response(200, json={"request_id": "r", "transcript": "", "language_code": None})

        result = stt.transcribe_chunks(CHUNKS, "en", client=_client(monkeypatch, handler), sleep=lambda s: None)
        assert result.segments == []


class TestFailures:
    def test_not_configured_makes_no_request(self, monkeypatch):
        calls = []
        monkeypatch.setattr(stt, "get_settings", lambda: Settings(sarvam_api_key=""))
        client = httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
        with pytest.raises(stt.SpeechToTextUnavailable):
            stt.transcribe_chunks(CHUNKS, "en", client=client)
        assert calls == []

    def test_switched_off_makes_no_request(self, monkeypatch):
        calls = []
        client = _client(monkeypatch, lambda r: calls.append(r) or httpx.Response(200), sarvam_stt_enabled=False)
        with pytest.raises(stt.SpeechToTextUnavailable):
            stt.transcribe_chunks(CHUNKS, "en", client=client)
        assert calls == []

    def test_client_error_is_a_rejection_and_not_retried(self, monkeypatch):
        calls = []

        def handler(req):
            calls.append(req)
            return httpx.Response(400, json={"error": {"message": "audio longer than 30 seconds",
                                                       "code": "invalid_request_error"}})

        with pytest.raises(stt.SpeechToTextRejected, match="longer than 30 seconds"):
            stt.transcribe_chunks(CHUNKS, "en", client=_client(monkeypatch, handler), sleep=lambda s: None)
        assert len(calls) == 1

    def test_overload_is_retried_then_unavailable(self, monkeypatch):
        calls = []

        def handler(req):
            calls.append(req)
            return httpx.Response(503, json={"error": {"message": "overloaded", "code": "internal_server_error"}})

        with pytest.raises(stt.SpeechToTextUnavailable):
            stt.transcribe_chunks(CHUNKS, "en", client=_client(monkeypatch, handler, sarvam_max_retries=3),
                                  sleep=lambda s: None)
        assert len(calls) == 3

    @pytest.mark.parametrize("response", [
        httpx.Response(200, json={"request_id": "r", "language_code": "en-IN"}),
        httpx.Response(200, json={"request_id": "r", "transcript": ["not", "text"]}),
        httpx.Response(200, text="<html>gateway</html>"),
        httpx.Response(200, json={"request_id": "r", "transcript": "x",
                                  "timestamps": {"words": ["x"], "start_time_seconds": ["soon"],
                                                 "end_time_seconds": [1.0]}}),
    ], ids=["no-transcript", "transcript-not-text", "not-json", "bad-timestamps"])
    def test_unexpected_response_is_an_error_not_a_transcript(self, monkeypatch, response):
        with pytest.raises(stt.SpeechToTextError, match="unexpected"):
            stt.transcribe_chunks(CHUNKS, "en", client=_client(monkeypatch, lambda r: response), sleep=lambda s: None)

    def test_error_text_never_contains_the_key(self, monkeypatch):
        def handler(req):
            return httpx.Response(403, json={"error": {"message": "invalid key", "code": "invalid_api_key_error"}})

        with pytest.raises(stt.SpeechToTextRejected) as exc:
            stt.transcribe_chunks(CHUNKS, "en", client=_client(monkeypatch, handler), sleep=lambda s: None)
        assert "test-key-not-real" not in str(exc.value)


class TestSplitting:
    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
    def test_long_recording_is_cut_into_parts_under_the_rest_limit(self):
        chunks = stt.split_audio(wav_bytes(60, rate=44100), ".wav")

        # FFmpeg cuts at packet boundaries, so parts are ~25 s; offsets come from each part's real length.
        assert len(chunks) == 3 and chunks[0].start_ms == 0
        assert all(b.start_ms == a.end_ms for a, b in itertools.pairwise(chunks))
        assert abs(chunks[0].end_ms - 25000) < 200 and abs(chunks[-1].end_ms - 60000) < 10
        for c in chunks:
            with wave.open(io.BytesIO(c.data)) as w:
                assert (w.getnchannels(), w.getframerate()) == (1, 16000)
            assert c.mime == "audio/wav" and c.end_ms - c.start_ms < stt.REST_LIMIT_SECONDS * 1000

    def test_without_ffmpeg_a_short_wav_is_sent_whole(self, monkeypatch):
        monkeypatch.setattr(stt.shutil, "which", lambda name: None)
        data = wav_bytes(2)
        assert [(c.start_ms, c.end_ms, c.data) for c in stt.split_audio(data, ".wav")] == [(0, 2000, data)]

    @pytest.mark.parametrize("data,ext", [(wav_bytes(31), ".wav"), (b"ID3" + b"\x00" * 100, ".mp3")],
                             ids=["long-wav", "mp3"])
    def test_without_ffmpeg_anything_else_is_refused_before_sarvam(self, monkeypatch, data, ext):
        monkeypatch.setattr(stt.shutil, "which", lambda name: None)
        with pytest.raises(stt.SpeechToTextUnavailable, match="ffmpeg"):
            stt.split_audio(data, ext)


class TestUploadFormats:
    @pytest.mark.parametrize("data,mime", [
        (wav_bytes(0.1), "audio/wav"),
        (b"ID3\x04\x00" + b"\x00" * 64, "audio/mpeg"),
        (b"\xff\xfb\x90\x64" + b"\x00" * 64, "audio/mpeg"),  # MPEG-1 Layer III frame, no ID3 tag
        (b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 64, "audio/mp4"),
    ], ids=["wav", "mp3-id3", "mp3-bare-frame", "m4a"])
    def test_common_audio_uploads_are_recognised(self, data, mime):
        assert intake.sniff_format(data)[0] == mime
        assert mime in stt.AUDIO_FORMATS

    def test_jpeg_is_not_mistaken_for_mp3(self):
        assert intake.sniff_format(b"\xff\xd8\xff\xe0" + b"\x00" * 64)[0] == "image/jpeg"

    def test_adts_aac_is_not_mistaken_for_mp3(self):
        with pytest.raises(intake.IntakeRejected):
            intake.sniff_format(b"\xff\xf1\x50\x80" + b"\x00" * 64)
