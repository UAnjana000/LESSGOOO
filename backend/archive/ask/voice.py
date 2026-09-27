"""Voice questions for Ask.

The visitor's recording is sent to the OpenAI-compatible /audio/transcriptions endpoint (Whisper) with the
answer model's key, and only the text comes back, to be edited in the question box before it is asked.
The audio is never stored, and neither the audio nor the transcript goes into traces.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import httpx

from archive import tracing
from archive.ask.llm import shared_client
from archive.config import get_settings

log = logging.getLogger(__name__)

LANGUAGE_HINTS = {"en", "hi", "mr"}
# Whisper picks the decoder from the file name, so the upload is renamed to one of its extensions.
EXTENSIONS = {"flac", "m4a", "mp3", "mp4", "mpeg", "mpga", "oga", "ogg", "wav", "webm"}
MIME_EXTENSIONS = {"audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4",
                   "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/mpeg": "mp3", "audio/mp3": "mp3",
                   "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/flac": "flac"}
_FFMPEG_TIME = re.compile(rb"time=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")


class VoiceError(Exception):
    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code, self.status, self.message = code, status, message


@dataclass
class Transcript:
    text: str
    model: str
    language: str | None
    duration_ms: int | None
    latency_ms: int


def _unavailable() -> VoiceError:
    return VoiceError("voice_unavailable", 503, "AI transcription is not available right now. Type your question instead.")


def upload_name(filename: str, content_type: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in EXTENSIONS:
        ext = MIME_EXTENSIONS.get(content_type.split(";")[0].strip().lower(), "")
    if not ext:
        raise VoiceError("unreadable", 400, "Use a common audio format (webm, ogg, mp3, m4a or wav).")
    return f"question.{ext}"


def duration_ms(data: bytes, limit_seconds: int) -> int | None:
    """Length of the recording; None when it cannot be measured here (a non-WAV file and no ffmpeg)."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getframerate() > 0:
                return int(w.getnframes() * 1000 / w.getframerate())
    except (wave.Error, EOFError):
        pass
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    # A temporary file, not a pipe: m4a/mp4 keep their index at the end and need a seekable input.
    with tempfile.TemporaryDirectory(prefix="ask-voice-") as tmp:
        path = Path(tmp) / "recording"
        path.write_bytes(data)
        try:
            proc = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path), "-vn",
                                   "-t", str(limit_seconds + 1), "-f", "null", "-"],
                                  capture_output=True, timeout=30, check=False)
        except subprocess.TimeoutExpired:
            proc = None
    times = _FFMPEG_TIME.findall(proc.stderr) if proc is not None and proc.returncode == 0 else []
    if not times:
        raise VoiceError("unreadable", 400, "The recording could not be read.")
    h, m, s = times[-1]
    return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)


def transcribe(data: bytes, filename: str, content_type: str, language: str) -> Transcript:
    s = get_settings()
    if not s.ask_voice_available:
        raise _unavailable()
    if not data:
        raise VoiceError("unreadable", 400, "The recording is empty.")
    if len(data) > s.ask_voice_max_bytes:
        raise VoiceError("too_large", 413, f"Recordings can be up to {s.ask_voice_max_bytes // (1024 * 1024)} MB.")
    name = upload_name(filename, content_type)
    duration = duration_ms(data, s.ask_voice_max_seconds)
    if duration is not None and duration > s.ask_voice_max_seconds * 1000:
        raise VoiceError("too_long", 413, f"Recordings can be up to {s.ask_voice_max_seconds} seconds.")

    hint = language if language in LANGUAGE_HINTS else None
    form = {"model": s.ask_voice_model, "response_format": "json", "temperature": "0"}
    if hint:
        form["language"] = hint
    with tracing.trace("ask_transcribe", {"model": s.ask_voice_model, "language": hint, "bytes": len(data),
                                          "duration_ms": duration}) as tr:
        start_ns = time.time_ns()
        try:
            resp = shared_client().post(f"{s.llm_base_url.rstrip('/')}/audio/transcriptions", data=form,
                                        files={"file": (name, data, content_type or "application/octet-stream")},
                                        headers={"Authorization": f"Bearer {s.llm_api_key}"})
            resp.raise_for_status()
            text = str(resp.json().get("text") or "").strip()
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            log.warning("ask transcription failed", extra={"status": status, "error": type(exc).__name__})
            tr.span("transcribe", model=s.ask_voice_model, start_ns=start_ns, end_ns=time.time_ns(),
                    error=f"HTTP {status}" if status else type(exc).__name__)
            raise _unavailable() from None
        end_ns = time.time_ns()
        tr.span("transcribe", model=s.ask_voice_model, start_ns=start_ns, end_ns=end_ns, chars=len(text))
    if not text:
        raise VoiceError("no_speech", 422, "No speech was heard in the recording.")
    return Transcript(text=text[: s.question_max_chars], model=s.ask_voice_model, language=hint,
                      duration_ms=duration, latency_ms=(end_ns - start_ns) // 1_000_000)
