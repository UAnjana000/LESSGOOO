"""Cached synthetic narration from approved source text or a reviewed translation (spec 5.5).

Primary: Sarvam bulbul TTS (generic voice). Offline fallback: espeak-ng on the edge server.
Both are labelled "Synthetic narration"; neither imitates Dr. Ambedkar's voice.

Cache key (Derivative.prompt_version): text hash + text version + voice, per item and language. An edited
text or another voice/model is a new narration; republishing unchanged text reuses the audio.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive import audit, storage
from archive.models import ArchivalItem, Derivative, FileVersion, Passage, PublicationState
from archive.rights import external_processing_allowed
from archive.services import sarvam_text

ESPEAK_VOICES = {"en": "en-gb", "hi": "hi", "mr": "mr"}
LABEL = "Synthetic narration"
NARRATABLE_KINDS = ("source_text", "reviewed_transcription", "reviewed_transcript", "reviewed_translation")


class NarrationError(RuntimeError):
    pass


class NarrationUnavailable(NarrationError):
    """No speech engine could produce audio; the reader works without narration."""


def _to_aac(wav: bytes) -> bytes:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.wav", Path(tmp) / "out.m4a"
            src.write_bytes(wav)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c:a", "aac", "-b:a", "48k",
                            str(dst)], check=True, timeout=120)
            return dst.read_bytes()
    except (OSError, subprocess.SubprocessError) as exc:
        raise NarrationUnavailable(f"audio encoding failed: {exc}") from exc


def espeak(text: str, language: str) -> tuple[bytes, str]:
    exe = shutil.which("espeak-ng")
    if exe is None:
        raise NarrationUnavailable("espeak-ng not installed")
    voice = ESPEAK_VOICES.get(language, "en-gb")
    try:
        banner = subprocess.run([exe, "--version"], capture_output=True, text=True, check=True, timeout=30).stdout
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "n.wav"
            subprocess.run([exe, "-v", voice, "-s", "150", "-w", str(out), "--stdin"], input=text.encode("utf-8"),
                           check=True, timeout=120)
            wav = out.read_bytes()
    except (OSError, subprocess.SubprocessError) as exc:
        raise NarrationUnavailable(f"espeak-ng failed: {exc}") from exc
    version = re.search(r"\d+\.\d+(?:\.\d+)?", banner or "")
    return wav, f"espeak-ng {version.group(0) if version else 'unknown'} voice={voice}"


def espeak_voice(language: str) -> str:
    return f"espeak-ng/{ESPEAK_VOICES.get(language, 'en-gb')}"


def cache_key(passage: Passage, voice: str) -> str:
    return f"{passage.text_hash[:16]}:v{passage.text_version}:{voice}"


def _source_ids(passage: Passage) -> list[int]:
    """A translation's narration is also listed under the source passage the reader shows it beside."""
    return [passage.id] + ([passage.translation_of_id] if passage.translation_of_id else [])


def _cached(db: Session, passage: Passage, language: str, voice: str) -> Derivative | None:
    d = db.execute(select(Derivative).join(FileVersion, Derivative.file_id == FileVersion.id).where(
        Derivative.kind == "narration", Derivative.status == "approved", Derivative.item_id == passage.item_id,
        Derivative.language == language, Derivative.prompt_version == cache_key(passage, voice),
        FileVersion.deleted_at.is_(None)).order_by(Derivative.id.desc())).scalars().first()
    if d is not None and not set(_source_ids(passage)) <= set(d.source_ids or []):
        d.source_ids = [*(d.source_ids or []), *(i for i in _source_ids(passage) if i not in (d.source_ids or []))]
        db.flush()
    return d


def _check_source(passage: object, language: str) -> Passage:
    if not isinstance(passage, Passage) or passage.kind not in NARRATABLE_KINDS:
        raise NarrationError("narration only from approved source text or a reviewed translation")
    if passage.language != language:
        raise NarrationError("passage language does not match narration language")
    return passage


def narrate(db: Session, passage: Passage, language: str, actor: str,
            prefer_local: bool = False) -> tuple[Derivative, bool]:
    """Returns (narration, served_from_cache)."""
    passage = _check_source(passage, language)
    item = db.get(ArchivalItem, passage.item_id)
    if item is None or item.publication_state == PublicationState.withdrawn.value or not passage.indexed:
        raise NarrationError("item is withdrawn; narration is not generated or served")
    use_sarvam = not prefer_local and sarvam_text.tts_configured() and external_processing_allowed(item)
    if use_sarvam and (hit := _cached(db, passage, language, sarvam_text.tts_voice())):
        return hit, True
    wav = generator = voice = None
    if use_sarvam:
        try:
            wav, generator = sarvam_text.synthesize(passage.text, language)
            voice = sarvam_text.tts_voice()
        except sarvam_text.ServiceUnavailable:
            wav = None
    if wav is None:
        voice = espeak_voice(language)
        if hit := _cached(db, passage, language, voice):
            return hit, True
        wav, generator = espeak(passage.text, language)
    audio = _to_aac(wav)
    stored = storage.put_bytes(audio, "delivery", ".m4a")
    fv = FileVersion(item_id=passage.item_id, role="delivery", kind="narration", format="audio/mp4",
                     byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri, generator=generator)
    db.add(fv)
    db.flush()
    d = Derivative(kind="narration", item_id=passage.item_id, source_ids=_source_ids(passage), language=language,
                   file_id=fv.id, generator=generator, prompt_version=cache_key(passage, voice), status="approved",
                   label_shown=LABEL)
    db.add(d)
    db.flush()
    audit.record(db, actor, "narration.generate", "derivative", d.id,
                 detail={"passage_id": passage.id, "generator": generator})
    return d, False


def narrate_passage(db: Session, passage: Passage, language: str, actor: str, prefer_local: bool = False) -> Derivative:
    """passage must be approved source text or a reviewed translation in `language`."""
    return narrate(db, passage, language, actor, prefer_local)[0]
