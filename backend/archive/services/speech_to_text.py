"""Sarvam speech-to-text (Saaras) - DRAFT transcripts for staff review only.

Wire protocol (docs.sarvam.ai API reference, Speech to Text > REST, checked 2026-09-27):
  POST {base}/speech-to-text   multipart: file, model, mode, language_code (BCP-47 or "unknown"),
                               with_timestamps=true
  -> {"request_id", "transcript", "language_code",
      "timestamps": {"words": [...], "start_time_seconds": [...], "end_time_seconds": [...]}}
  The timestamps are phrase-level chunks, not single words. Header: api-subscription-key.
The REST endpoint takes audio under 30 seconds and has no speaker diarization, so a recording is cut
with FFmpeg into 16 kHz mono WAV parts and each part is one request.

Nothing here approves, publishes or quote-verifies a transcript: segments are stored as review_status
"draft" and go through the full review every audio/video transcript needs (spec 1.1).
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archive import audit, storage
from archive.config import get_settings
from archive.ingest import review
from archive.models import ArchivalItem, FileVersion, MediaSegment
from archive.rights import external_processing_allowed

LANG = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}
STT_MODEL = "saaras:v3"
STT_MODE = "verbatim"  # word for word, no number normalisation: closest to what the reviewer hears
REST_LIMIT_SECONDS = 30
CHUNK_SECONDS = 25
AUDIO_FORMATS = {"audio/wav": ".wav", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/flac": ".flac",
                 "audio/ogg": ".ogg"}
STORED_MEDIA_FORMATS = {**AUDIO_FORMATS, "video/mp4": ".mp4", "video/webm": ".webm"}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
DRAFT_LABEL = ("Machine transcript draft (Sarvam): not reviewed and not quote-verified. A person must check "
               "every line against the recording before approving it or verifying any quote.")
REFUSAL = ("Speech-to-text refused: the rights register does not allow external processing for this item, "
           "or the item is restricted. The recording was not sent to Sarvam.")


class SpeechToTextError(RuntimeError):
    """The recording could not be turned into a draft; nothing was stored as transcript."""


class SpeechToTextUnavailable(SpeechToTextError):
    """Not configured, FFmpeg missing, network failure or retries exhausted."""


class SpeechToTextRejected(SpeechToTextError):
    """Non-retryable API rejection (4xx other than 429)."""


class SpeechToTextRefused(SpeechToTextError):
    """Rights forbid sending this item's audio to an external service."""


@dataclass(frozen=True)
class AudioChunk:
    start_ms: int
    end_ms: int
    data: bytes
    filename: str
    mime: str


@dataclass(frozen=True)
class DraftSegment:
    start_ms: int
    end_ms: int
    text: str
    language: str | None


@dataclass
class Transcription:
    segments: list[DraftSegment] = field(default_factory=list)
    language: str | None = None
    request_ids: list[str] = field(default_factory=list)


def configured() -> bool:
    s = get_settings()
    return s.sarvam_available and s.sarvam_stt_enabled


def engine() -> str:
    return f"sarvam-stt {STT_MODEL} mode={STT_MODE}"


def _client() -> httpx.Client:
    return httpx.Client(timeout=120)


def _short_lang(code: Any) -> str | None:
    if not isinstance(code, str) or not code or code == "unknown":
        return None
    return code.split("-")[0].lower()[:5]


def _error_message(resp: httpx.Response) -> str:
    try:
        return str(resp.json()["error"]["message"])[:300]
    except (ValueError, KeyError, TypeError):
        return resp.text[:300]


def _post(client: httpx.Client, chunk: AudioChunk, language_code: str, sleep: Callable[[float], None]) -> Any:
    s = get_settings()
    form = {"model": STT_MODEL, "mode": STT_MODE, "language_code": language_code, "with_timestamps": "true"}
    attempts = max(1, s.sarvam_max_retries)
    delay, last = 2.0, ""
    for attempt in range(attempts):
        try:
            resp = client.post(f"{s.sarvam_base_url.rstrip('/')}/speech-to-text",
                               headers={"api-subscription-key": s.sarvam_api_key},
                               files={"file": (chunk.filename, chunk.data, chunk.mime)}, data=form)
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        else:
            if resp.status_code < 400:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise SpeechToTextError("unexpected speech-to-text response: not JSON") from exc
            if resp.status_code not in RETRYABLE_STATUS:
                raise SpeechToTextRejected(f"Sarvam rejected the audio (HTTP {resp.status_code}): "
                                           f"{_error_message(resp)}")
            last = f"HTTP {resp.status_code}"
        if attempt < attempts - 1:
            sleep(delay)
            delay *= 2
    raise SpeechToTextUnavailable(f"Sarvam speech-to-text unavailable after {attempts} attempts ({last})")


def _parse(body: Any, chunk: AudioChunk, language: str | None) -> tuple[list[DraftSegment], str | None]:
    if not isinstance(body, dict) or not isinstance(body.get("transcript"), str):
        raise SpeechToTextError("unexpected speech-to-text response: no transcript text")
    lang = _short_lang(body.get("language_code")) or language
    stamps = body.get("timestamps")
    if not stamps:
        text = body["transcript"].strip()
        return ([DraftSegment(chunk.start_ms, chunk.end_ms, text, lang)] if text else []), lang
    try:
        words, starts, ends = stamps["words"], stamps["start_time_seconds"], stamps["end_time_seconds"]
        if not len(words) == len(starts) == len(ends):
            raise ValueError("timestamp lists differ in length")
        out = []
        for word, start, end in zip(words, starts, ends, strict=True):
            if not isinstance(word, str):
                raise TypeError("timestamp text is not a string")
            begin = chunk.start_ms + round(float(start) * 1000)
            if word.strip():
                out.append(DraftSegment(begin, max(begin, chunk.start_ms + round(float(end) * 1000)), word.strip(),
                                        lang))
    except (KeyError, TypeError, ValueError) as exc:
        raise SpeechToTextError(f"unexpected speech-to-text timestamps: {exc!r}"[:200]) from exc
    return out, lang


def transcribe_chunks(chunks: list[AudioChunk], language: str | None, client: httpx.Client | None = None,
                      sleep: Callable[[float], None] = time.sleep) -> Transcription:
    """One REST request per part; timestamps are shifted by each part's start in the recording."""
    if not configured():
        raise SpeechToTextUnavailable("Sarvam speech-to-text is not configured")
    code = LANG.get(language or "", "unknown")
    own = client is None
    c = client or _client()
    result = Transcription()
    try:
        for chunk in chunks:
            body = _post(c, chunk, code, sleep)
            segments, lang = _parse(body, chunk, language)
            result.segments += segments
            result.language = result.language or lang
            if body.get("request_id"):
                result.request_ids.append(str(body["request_id"]))
    finally:
        if own:
            c.close()
    return result


def wav_duration_ms(data: bytes) -> int | None:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return round(w.getnframes() * 1000 / w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError):
        return None


def split_audio(data: bytes, ext: str) -> list[AudioChunk]:
    """16 kHz mono WAV parts of CHUNK_SECONDS (Sarvam's recommended rate, under the REST limit)."""
    exe = shutil.which("ffmpeg")
    if exe is None:
        duration = wav_duration_ms(data) if ext == ".wav" else None
        if duration is not None and duration < REST_LIMIT_SECONDS * 1000:
            return [AudioChunk(0, duration, data, "recording.wav", "audio/wav")]
        raise SpeechToTextUnavailable("ffmpeg is needed to cut this recording into parts under 30 seconds")
    chunks: list[AudioChunk] = []
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"source{ext}"
        src.write_bytes(data)
        try:
            subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                            "-c:a", "pcm_s16le", "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
                            "-reset_timestamps", "1", str(Path(tmp) / "part%05d.wav")],
                           check=True, capture_output=True, timeout=1800)
        except subprocess.CalledProcessError as exc:
            raise SpeechToTextError("ffmpeg could not read the recording: "
                                    f"{exc.stderr.decode('utf-8', 'replace').strip()[:200]}") from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SpeechToTextUnavailable(f"ffmpeg failed: {exc}"[:200]) from exc
        start = 0
        for part in sorted(Path(tmp).glob("part*.wav")):
            blob = part.read_bytes()
            duration = wav_duration_ms(blob) or 0
            if duration:
                chunks.append(AudioChunk(start, start + duration, blob, part.name, "audio/wav"))
                start += duration
    if not chunks:
        raise SpeechToTextError("the recording holds no audio")
    return chunks


def draft_transcript(db: Session, item: ArchivalItem, recording: FileVersion, language: str | None, actor: str,
                     client: httpx.Client | None = None) -> dict[str, Any]:
    """Store Sarvam's transcript of `recording` as draft segments. Earlier unreviewed machine drafts of the
    same recording are replaced; reviewed segments are never touched."""
    if not external_processing_allowed(item):
        raise SpeechToTextRefused(REFUSAL)
    if recording.item_id != item.id or recording.deleted_at is not None \
            or recording.format not in STORED_MEDIA_FORMATS:
        raise SpeechToTextError("this file is not a stored recording of the item")
    chunks = split_audio(storage.read_bytes(recording.storage_uri), STORED_MEDIA_FORMATS[recording.format])
    duration = chunks[-1].end_ms
    limit = get_settings().sarvam_stt_max_seconds
    if duration > limit * 1000:
        raise SpeechToTextError(f"recording is {duration // 1000} s long; the limit for one job is {limit} s")
    result = transcribe_chunks(chunks, language, client)
    if not result.segments:
        raise SpeechToTextError("Sarvam returned no transcript text for this recording")
    fallback = language or result.language or (item.original_languages or ["en"])[0]
    replaced = db.execute(select(MediaSegment.id).where(
        MediaSegment.item_id == item.id, MediaSegment.source_file_id == recording.id,
        MediaSegment.draft_engine.is_not(None), MediaSegment.review_status == "draft")).scalars().all()
    if replaced:
        db.execute(delete(MediaSegment).where(MediaSegment.id.in_(replaced)))
    for seg in result.segments:
        db.add(MediaSegment(item_id=item.id, start_ms=seg.start_ms, end_ms=seg.end_ms, transcript_text=seg.text,
                            language=seg.language or fallback, review_status="draft", quote_verified=False,
                            draft_engine=engine(), source_file_id=recording.id))
    db.flush()
    review._update_item_state(db, item)
    detail = {"file_id": recording.id, "segments": len(result.segments), "replaced_drafts": len(replaced),
              "engine": engine(), "language_requested": language or "unknown",
              "language_detected": result.language, "parts": len(chunks), "duration_ms": duration,
              "request_ids": result.request_ids[:50]}
    audit.record(db, actor, "media.stt_draft", "archival_item", item.id, detail=detail)
    return {**detail, "label": DRAFT_LABEL, "review_status": "draft", "quote_verified": False}
