"""Cached synthetic narration from approved source text or a reviewed translation (spec 5.5).

Primary: Sarvam bulbul TTS (generic voice). Offline fallback: espeak-ng on the edge server.
Both are labelled "Synthetic narration"; neither imitates Dr. Ambedkar's voice.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from archive import audit, storage
from archive.models import Derivative, FileVersion, Passage
from archive.services import sarvam_text

ESPEAK_VOICES = {"en": "en-gb", "hi": "hi", "mr": "mr"}
LABEL = "Synthetic narration"


class NarrationError(RuntimeError):
    pass


def _to_aac(wav: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / "out.m4a"
        src.write_bytes(wav)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c:a", "aac", "-b:a", "48k", str(dst)],
                       check=True, timeout=120)
        return dst.read_bytes()


def espeak(text: str, language: str) -> bytes:
    exe = shutil.which("espeak-ng")
    if exe is None:
        raise NarrationError("espeak-ng not installed")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "n.wav"
        subprocess.run([exe, "-v", ESPEAK_VOICES.get(language, "en-gb"), "-s", "150", "-w", str(out), text],
                       check=True, timeout=120)
        return out.read_bytes()


def narrate_passage(db: Session, passage: Passage, language: str, actor: str, prefer_local: bool = False) -> Derivative:
    """passage must be approved source text or a reviewed translation in `language`."""
    if passage.kind not in ("source_text", "reviewed_transcription", "reviewed_translation", "reviewed_transcript"):
        raise NarrationError("narration only from approved source text or a reviewed translation")
    if passage.language != language:
        raise NarrationError("passage language does not match narration language")
    generator = None
    wav = None
    if not prefer_local:
        try:
            wav, generator = sarvam_text.synthesize(passage.text, language)
        except sarvam_text.ServiceUnavailable:
            wav = None
    if wav is None:
        wav = espeak(passage.text, language)
        generator = f"espeak-ng voice={ESPEAK_VOICES.get(language)}"
    audio = _to_aac(wav)
    stored = storage.put_bytes(audio, "delivery", ".m4a")
    fv = FileVersion(item_id=passage.item_id, role="delivery", kind="narration", format="audio/mp4",
                     byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri, generator=generator)
    db.add(fv)
    db.flush()
    d = Derivative(kind="narration", item_id=passage.item_id, source_ids=[passage.id], language=language,
                   file_id=fv.id, generator=generator, status="approved", label_shown=LABEL)
    db.add(d)
    db.flush()
    audit.record(db, actor, "narration.generate", "derivative", d.id,
                 detail={"passage_id": passage.id, "generator": generator})
    return d
