"""Redacted AI tracing.

- With LANGFUSE keys: traces go to a (self-hosted) Langfuse via its OTel-based SDK.
- Without keys: the same redacted records go to a local JSONL sink (data/traces), clearly not Langfuse.

Redaction rules (spec 6.6): visitor questions are PII-scrubbed (emails, phones, ID numbers, IPs,
secret-shaped tokens) or hashed; archival passage text, generated answers and prompts are never traced
(passage IDs only). Langfuse is neither the archive database nor the audit log.
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
_IPV4 = re.compile(r"(?<!\d)(?<!\d\.)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\.?\d)")
# Candidates only; _ipv6 keeps a match when it has 3+ colons or "::", so clock times like 11:35:20 survive.
_IPV6 = re.compile(r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
_SECRET = re.compile(
    r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"
    r"|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|(?i:\b(?:api[_-]?key|password|passwd|secret|token)\b\s*[:=]\s*)\S+"
)
# Archival text, generated answers and prompts never go to traces (passage IDs only).
_ARCHIVE_TEXT_KEYS = {"text", "passage_text", "passages_text", "content", "document", "documents", "context",
                      "excerpt", "sentences", "answer", "raw_answer", "quoted_spans", "quotes", "prompt",
                      "system_prompt", "messages", "history"}
_SENSITIVE_KEYS = {"session_id", "ip", "client_ip", "remote_addr", "x_forwarded_for", "user_agent", "email",
                   "authorization", "cookie", "api_key", "password", "secret", "token", "jwt"}
_FORBIDDEN_KEYS = _ARCHIVE_TEXT_KEYS | _SENSITIVE_KEYS


def _ipv6(m: re.Match[str]) -> str:
    s = m.group(0)
    return "[ip]" if s.count(":") >= 3 or "::" in s else s


def scrub_pii(text: str) -> str:
    text = _SECRET.sub("[secret]", text)
    text = _EMAIL.sub("[email]", text)
    text = _IPV4.sub("[ip]", text)
    text = _IPV6.sub(_ipv6, text)
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
    """Drop any key that could carry archival text, answers, identifiers or secrets; scrub strings."""
    if isinstance(payload, dict):
        return {k: ("[redacted]" if str(k).lower() in _FORBIDDEN_KEYS else redact(v)) for k, v in payload.items()}
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
    from langfuse.span_filter import is_langfuse_span

    # Only the archive's own (masked) observations are exported; third-party OTel spans bypass `mask`.
    return Langfuse(public_key=s.langfuse_public_key, secret_key=s.langfuse_secret_key, host=s.langfuse_host,
                    environment=s.environment, mask=lambda data, **_: redact(data),
                    should_export_span=is_langfuse_span)


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
        """`start_ns`/`end_ns` (time.time_ns) give the span its measured start and end; without them the span
        is recorded as an instant at emit time."""
        start_ns, end_ns = data.pop("start_ns", None), data.pop("end_ns", None)
        timed = isinstance(start_ns, int) and isinstance(end_ns, int) and start_ns <= end_ns
        rec = {"name": name, "at": dt.datetime.now(dt.UTC).isoformat(), **redact(data)}
        if timed:
            rec["started"] = dt.datetime.fromtimestamp(start_ns / 1e9, dt.UTC).isoformat()
            rec["ended"] = dt.datetime.fromtimestamp(end_ns / 1e9, dt.UTC).isoformat()
        self.spans.append(rec)
        if self._lf_span is not None:
            try:
                ev_type = "generation" if name == "generate" else "span"
                kwargs: dict[str, Any] = {
                    "metadata": redact(data),
                    "level": "ERROR" if data.get("error") else None,
                    "status_message": scrub_pii(str(data["error"]))[:300] if data.get("error") else None,
                }
                if ev_type == "generation":
                    kwargs.update(
                        version=data.get("prompt_version"), model=data.get("model"),
                        usage_details={"input": data.get("tokens_in", 0), "output": data.get("tokens_out", 0)},
                        # Unpriced (0) cost is omitted so Langfuse infers it from its model price table.
                        cost_details={"total": data["cost_usd"]} if data.get("cost_usd") else None,
                    )
                if not (timed and self._lf_timed_observation(name, ev_type, start_ns, end_ns, kwargs)):
                    with self._lf_span.start_as_current_observation(name=name, as_type=ev_type, **kwargs):
                        pass
            except Exception:  # tracing must never break the request
                log.warning("langfuse span failed", exc_info=True)

    def _lf_timed_observation(self, name: str, ev_type: str, start_ns: int, end_ns: int,
                              kwargs: dict[str, Any]) -> bool:
        """Child observation with explicit OTel start/end times. The SDK's start_observation cannot backdate a
        span, so this mirrors its own event path (tracer.start_span(start_time=...) wrapped in the observation
        class, which applies `mask`). Returns False if those SDK internals are missing."""
        try:
            from langfuse._client.span import LangfuseGeneration, LangfuseSpan
            from opentelemetry import trace as otel_trace

            parent = self._lf_span
            client = parent._langfuse_client
            with otel_trace.use_span(parent._otel_span):
                otel_span = client._otel_tracer.start_span(name=name, start_time=start_ns)
        except (ImportError, AttributeError):
            log.warning("langfuse SDK internals changed; span %s recorded without measured times", name)
            return False
        cls = LangfuseGeneration if ev_type == "generation" else LangfuseSpan
        cls(otel_span=otel_span, langfuse_client=client, environment=parent._environment,
            release=parent._release, **kwargs).end(end_time=end_ns)
        return True

    def update(self, **data: Any) -> None:
        self.output.update(redact(data))


@contextmanager
def trace(name: str, meta: dict[str, Any] | None = None):
    t = Trace(name, meta or {})
    lf = _langfuse()
    cm = None
    if lf is not None:
        try:
            cm = lf.start_as_current_observation(name=name, as_type="span", metadata=t.meta,
                                                 version=t.meta.get("prompt_version"))
            t._lf_span = cm.__enter__()
            t.id = lf.get_current_trace_id() or t.id
        except Exception:
            log.warning("langfuse trace start failed", exc_info=True)
            cm = None
    error = None
    try:
        yield t
    except Exception as exc:
        error = scrub_pii(repr(exc))[:300]
        raise
    finally:
        record = {"trace_id": t.id, "name": name, "backend": backend_name(), "meta": t.meta,
                  "started": t.started.isoformat(),
                  "duration_ms": int((dt.datetime.now(dt.UTC) - t.started).total_seconds() * 1000),
                  "spans": t.spans, "output": t.output, "error": error}
        if cm is not None:
            try:
                if error:
                    t._lf_span.update(output=t.output, level="ERROR", status_message=error)
                else:
                    t._lf_span.update(output=t.output)
                cm.__exit__(None, None, None)
                lf.flush()
            except Exception:
                log.warning("langfuse trace end failed", exc_info=True)
        else:
            _sink().write(record)
