"""Sarvam Document AI (Sarvam Vision) client - OCR FALLBACK ONLY, for pages that failed the local gate.

Wire protocol (docs.sarvam.ai, Document Intelligence overview, checked 2026-09-26):
  POST {base}/doc-ai/v1/job/digitise   multipart: file, language (e.g. hi-IN), output_format=md
  GET  {base}/doc-ai/v1/job/{id}/status   -> status in pending|running|completed|partially_completed|failed|rejected
  GET  {base}/doc-ai/v1/job/{id}/download-url -> {"method": "GET", "url": ...}  (ZIP with the .md output)
Header: api-subscription-key.

A Sarvam result is never auto-accepted; callers must route it to full archivist review.

The downloaded Markdown can contain inline data-URI images and model-written image descriptions
instead of (or alongside) a transcription. Only the remaining text is offered as OCR text; the raw
Markdown is returned separately so it can be kept for the reviewer.
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from archive.config import get_settings

LANG = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}
TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class SarvamUnavailable(RuntimeError):
    """No key configured, network failure, or retries exhausted. The page stays pending review."""


class SarvamRejected(RuntimeError):
    """Non-retryable API rejection (4xx other than 429)."""


@dataclass
class SarvamOcrOutput:
    text: str  # transcription candidate only; "" when the output held no transcription
    engine_version: str
    job_id: str
    raw_status: str
    raw_markdown: str | None = None
    not_transcription: str | None = None  # reason the output is not usable as OCR text
    stripped: dict[str, int] = field(default_factory=dict)


class OcrFallback(Protocol):
    def digitise_page(self, image_png: bytes, language: str) -> SarvamOcrOutput: ...


class SarvamDocAI:
    engine = "sarvam-doc-ai"

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 client: httpx.Client | None = None, sleep=time.sleep) -> None:
        s = get_settings()
        self.api_key = api_key if api_key is not None else s.sarvam_api_key
        self.base_url = (base_url or s.sarvam_base_url).rstrip("/")
        self.max_retries = s.sarvam_max_retries
        self.poll_seconds = s.sarvam_poll_seconds
        self.poll_timeout = s.sarvam_poll_timeout_seconds
        self._client = client or httpx.Client(timeout=60)
        self._sleep = sleep

    def _headers(self) -> dict[str, str]:
        return {"api-subscription-key": self.api_key}

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        delay = 2.0
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.request(method, url, headers=self._headers(), **kwargs)
            except httpx.HTTPError as exc:
                last_exc = exc
            else:
                if resp.status_code < 400:
                    return resp
                if resp.status_code not in RETRYABLE_STATUS:
                    raise SarvamRejected(f"{resp.status_code}: {resp.text[:300]}")
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
            if attempt < self.max_retries - 1:
                self._sleep(delay)
                delay *= 2
        raise SarvamUnavailable(f"retries exhausted: {last_exc}")

    def digitise_page(self, image_png: bytes, language: str) -> SarvamOcrOutput:
        if not self.api_key:
            raise SarvamUnavailable("SARVAM API key not configured")
        created = self._request(
            "POST",
            f"{self.base_url}/doc-ai/v1/job/digitise",
            files={"file": ("page.png", image_png, "image/png")},
            data={"language": LANG.get(language, "en-IN"), "output_format": "md"},
        ).json()
        job_id = created["job_id"]
        waited = 0.0
        status = created.get("status", "pending")
        while status.lower() not in TERMINAL:
            if waited >= self.poll_timeout:
                raise SarvamUnavailable(f"job {job_id} did not finish within {self.poll_timeout}s")
            self._sleep(self.poll_seconds)
            waited += self.poll_seconds
            status = self._request("GET", f"{self.base_url}/doc-ai/v1/job/{job_id}/status").json()["status"]
        if status.lower() in {"failed", "rejected"}:
            raise SarvamRejected(f"job {job_id} ended {status}")
        dl = self._request("GET", f"{self.base_url}/doc-ai/v1/job/{job_id}/download-url").json()
        blob = self._client.get(dl["url"], timeout=60)
        blob.raise_for_status()
        raw = extract_markdown(blob.content)
        cleaned = transcription_from_markdown(raw)
        return SarvamOcrOutput(text=cleaned.text, engine_version="sarvam-vision (doc-ai v1)", job_id=job_id,
                               raw_status=status, raw_markdown=raw, not_transcription=cleaned.not_transcription,
                               stripped=cleaned.stripped)


def extract_markdown(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = sorted(n for n in zf.namelist() if n.lower().endswith(".md"))
        if not names:
            raise SarvamRejected("download contained no markdown output")
        return "\n\n".join(zf.read(n).decode("utf-8") for n in names).strip()


_IMAGE_PATTERNS = (
    re.compile(r"<figure\b.*?</figure>", re.IGNORECASE | re.DOTALL),
    re.compile(r"!\[[^\]]*\]\([^)]*\)"),
    re.compile(r"<img\b[^>]*>", re.IGNORECASE),
    re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=\s]*", re.IGNORECASE),
    re.compile(r"[A-Za-z0-9+/]{200,}={0,2}"),
)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_DESCRIPTION_LEAD = re.compile(
    r"^(?:"
    r"(?:image|figure|photo|picture|illustration)\s*(?:description|caption)?\s*[:\-\u2013\u2014]"
    r"|(?:the|this)\s+(?:(?:scanned|page|document)\s+)?(?:image|photo(?:graph)?|picture|figure|illustration|scan)\b"
    r"|(?:the|this)\s+(?:page|document)\s+(?:appears|seems)\s+to\b"
    r")",
    re.IGNORECASE,
)
_DESCRIPTION_CUES = re.compile(
    r"grayscale|greyscale|low[- ]resolution|blurr(?:y|ed)|pixelated|noisy|illegible|legible|depicts"
    r"|appears to (?:be|show|depict|contain)|photograph|the image",
    re.IGNORECASE,
)
_MD_DECORATION = re.compile(r"^[\s>*_#\-]+|[\s*_]+$")
_IMAGE_SLOT = "\x00"
_ITALIC_OPEN = re.compile(r"^([*_])(?![*_])")
_ITALIC_CLOSE = re.compile(r"(?<![*_])[*_]$")


@dataclass
class CleanedMarkdown:
    text: str
    not_transcription: str | None
    stripped: dict[str, int]


def _is_description(block: str) -> bool:
    plain = _MD_DECORATION.sub("", block)
    if _DESCRIPTION_LEAD.match(plain):
        return True
    return len({m.group(0).lower() for m in _DESCRIPTION_CUES.finditer(plain)}) >= 2


def transcription_from_markdown(markdown: str) -> CleanedMarkdown:
    """Drop embedded images and image-description paragraphs; decide whether any transcription remains.

    Sarvam captions each detected image region with one italic span that may run over many paragraphs
    (headings, lists, Q&A); the whole span after an image is treated as description.
    """
    images = 0
    text = _HTML_COMMENT.sub("", markdown)
    for pattern in _IMAGE_PATTERNS:
        text, n = pattern.subn(f"\n\n{_IMAGE_SLOT}\n\n", text)
        images += n
    kept, descriptions = [], 0
    after_image = in_caption = False
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if block == _IMAGE_SLOT:
            after_image = True
            continue
        if after_image and _ITALIC_OPEN.match(block):
            in_caption = True
        after_image = False
        if in_caption:
            descriptions += 1
            in_caption = not _ITALIC_CLOSE.search(block)
            continue
        if _is_description(block):
            descriptions += 1
            continue
        kept.append(block)
    cleaned = "\n\n".join(kept).strip()
    stripped = {"images_removed": images, "description_blocks_removed": descriptions,
                "raw_chars": len(markdown), "text_chars": len(cleaned)}
    if not any(c.isalpha() for c in cleaned):
        return CleanedMarkdown("", f"Sarvam output held no transcription text ({images} embedded images, "
                                   f"{descriptions} image-description blocks removed)", stripped)
    return CleanedMarkdown(cleaned, None, stripped)
