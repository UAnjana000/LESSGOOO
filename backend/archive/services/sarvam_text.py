"""Sarvam translation and text-to-speech. Separate services from OCR fallback; the
'Sarvam only on low confidence' rule applies to OCR only (spec 5.5).

POST {base}/translate       {input, source_language_code, target_language_code, model}
POST {base}/text-to-speech  {text, language_code, model, speaker} -> {"audios": [base64 wav]}
(docs.sarvam.ai API reference, checked 2026-09-26)
"""

from __future__ import annotations

import base64

import httpx

from archive.config import get_settings

LANG = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}
TRANSLATE_MODEL = "sarvam-translate:v1"
TTS_MODEL = "bulbul:v3"
TTS_SPEAKER = "ritu"  # a generic synthetic voice; never a clone of Dr. Ambedkar's voice


class ServiceUnavailable(RuntimeError):
    pass


def _client() -> httpx.Client:
    return httpx.Client(timeout=45)


def translate(text: str, source: str, target: str, client: httpx.Client | None = None) -> tuple[str, str]:
    s = get_settings()
    if not (s.sarvam_available and s.sarvam_translate_enabled):
        raise ServiceUnavailable("Sarvam translation not configured")
    chunks, buf = [], ""
    for para in text.split("\n"):
        if len(buf) + len(para) > 1800 and buf:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    out = []
    c = client or _client()
    for chunk in chunks:
        try:
            resp = c.post(f"{s.sarvam_base_url}/translate", headers={"api-subscription-key": s.sarvam_api_key},
                          json={"input": chunk, "source_language_code": LANG[source],
                                "target_language_code": LANG[target], "model": TRANSLATE_MODEL})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ServiceUnavailable(str(exc)) from exc
        out.append(resp.json()["translated_text"])
    return "\n".join(out), TRANSLATE_MODEL


def tts_configured() -> bool:
    s = get_settings()
    return s.sarvam_available and s.sarvam_tts_enabled


def tts_voice() -> str:
    """Cache-key part: a different model or speaker is a different narration."""
    return f"sarvam/{TTS_MODEL}/{TTS_SPEAKER}"


def synthesize(text: str, language: str, client: httpx.Client | None = None) -> tuple[bytes, str]:
    s = get_settings()
    if not tts_configured():
        raise ServiceUnavailable("Sarvam TTS not configured")
    c = client or _client()
    try:
        resp = c.post(f"{s.sarvam_base_url}/text-to-speech", headers={"api-subscription-key": s.sarvam_api_key},
                      json={"text": text[:2400], "language_code": LANG[language], "model": TTS_MODEL,
                            "speaker": TTS_SPEAKER})
        resp.raise_for_status()
        audio = b"".join(base64.b64decode(a, validate=True) for a in resp.json()["audios"])
    except httpx.HTTPError as exc:
        raise ServiceUnavailable(str(exc)) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceUnavailable(f"unexpected text-to-speech response: {exc!r}"[:200]) from exc
    if not audio:
        raise ServiceUnavailable("text-to-speech returned no audio")
    return audio, f"sarvam-tts {TTS_MODEL} speaker={TTS_SPEAKER}"
