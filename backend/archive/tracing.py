"""Redacted AI tracing.

- With LANGFUSE keys: traces go to a (self-hosted) Langfuse via its OTel-based SDK.
- Without keys: the same redacted records go to a local JSONL sink (data/traces), clearly not Langfuse.

Redaction rules (spec 6.6): visitor questions are PII-scrubbed or hashed; archival passage text is
never traced (passage IDs only). Langfuse is neither the archive database nor the audit log.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import threading
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from archive.config import get_settings

log = logging.getLogger(__name__)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)|(?<!\d)\d{3}[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_FORBIDDEN_KEYS = {"text", "passage_text", "passages_text", "content", "document", "documents", "context"}


def scrub_pii(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _AADHAAR.sub("[id-number]", text)
    text = _PAN.sub("[id-number]", text)
    text = _PHONE.sub("[phone]", text)
    return text


def question_ref(question: str) -> str:
    s = get_settings()
    if s.trace_question_mode == "hash":
        return "sha256:" + hashlib.sha256(question.encode()).hexdigest()
    return scrub_pii(question)


def redact(payload: Any) -> Any:
    """Drop any key that could carry archival text; scrub strings."""
    if isinstance(payload, dict):
        return {k: ("[redacted]" if k in _FORBIDDEN_KEYS else redact(v)) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact(v) for v in payload]
    if isinstance(payload, str):
        return scrub_pii(payload)[:500]
    return payload


class _LocalSink:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"traces-{dt.date.today().isoformat()}.jsonl"
        with self._lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")


@lru_cache
def _langfuse():
    s = get_settings()
    if not s.langfuse_enabled:
        return None
    from langfuse import Langfuse

    return Langfuse(public_key=s.langfuse_public_key, secret_key=s.langfuse_secret_key, host=s.langfuse_host,
                    environment=s.environment, mask=lambda data, **_: redact(data))


@lru_cache
def _sink() -> _LocalSink:
    return _LocalSink(Path(get_settings().trace_root))


def backend_name() -> str:
    return "langfuse" if _langfuse() is not None else "local-jsonl (Langfuse keys not configured)"


class Trace:
    def __init__(self, name: str, meta: dict[str, Any]) -> None:
        self.id = uuid.uuid4().hex
        self.name = name
        self.meta = redact(meta)
        self.started = dt.datetime.now(dt.UTC)
        self.spans: list[dict[str, Any]] = []
        self.output: dict[str, Any] = {}
        self._lf_span = None

    def span(self, name: str, **data: Any) -> None:
        rec = {"name": name, "at": dt.datetime.now(dt.UTC).isoformat(), **redact(data)}
        self.spans.append(rec)
        if self._lf_span is not None:
            try:
                ev_type = "generation" if name == "generate" else "span"
                with self._lf_span.start_as_current_observation(
                    name=name, as_type=ev_type, metadata=redact(data),
                    model=data.get("model") if ev_type == "generation" else None,
                    usage_details={"input": data.get("tokens_in", 0), "output": data.get("tokens_out", 0)}
                    if ev_type == "generation" else None,
                    cost_details={"total": data.get("cost_usd", 0.0)} if ev_type == "generation" else None,
                ):
                    pass
            except Exception:  # tracing must never break the request
                log.warning("langfuse span failed", exc_info=True)

    def update(self, **data: Any) -> None:
        self.output.update(redact(data))


@contextmanager
def trace(name: str, meta: dict[str, Any] | None = None):
    t = Trace(name, meta or {})
    lf = _langfuse()
    cm = None
    if lf is not None:
        try:
            cm = lf.start_as_current_observation(name=name, as_type="span", metadata=t.meta)
            t._lf_span = cm.__enter__()
            t.id = lf.get_current_trace_id() or t.id
        except Exception:
            log.warning("langfuse trace start failed", exc_info=True)
            cm = None
    error = None
    try:
        yield t
    except Exception as exc:
        error = repr(exc)[:300]
        raise
    finally:
        record = {"trace_id": t.id, "name": name, "backend": backend_name(), "meta": t.meta,
                  "started": t.started.isoformat(),
                  "duration_ms": int((dt.datetime.now(dt.UTC) - t.started).total_seconds() * 1000),
                  "spans": t.spans, "output": t.output, "error": error}
        if cm is not None:
            try:
                t._lf_span.update(output=t.output)
                cm.__exit__(None, None, None)
                lf.flush()
            except Exception:
                log.warning("langfuse trace end failed", exc_info=True)
        else:
            _sink().write(record)
