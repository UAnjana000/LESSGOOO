"""Trace redaction, checked at the OpenTelemetry export boundary (what the Langfuse SDK would send)."""

from __future__ import annotations

import hashlib
import json
import time
import uuid

import pytest

from archive import tracing
from archive.config import get_settings
from archive.tracing import redact, scrub_pii


class TestScrub:
    @pytest.mark.parametrize("raw,leak", [
        ("from 192.168.1.23 today", "192.168.1.23"),
        ("I asked from 192.168.1.50.", "192.168.1.50"),
        ("(10.0.0.7), then", "10.0.0.7"),
        ("v6 2001:db8:85a3::8a2e:370:7334 here", "2001:db8"),
        ("loopback ::1 and fe80::1", "fe80::1"),
        ("key sk-proj-AbCdEf0123456789xyz leaked", "sk-proj-AbCdEf"),
        ("langfuse sk-lf-1a2b3c4d-5e6f-7a8b-9c0d-e1f2a3b4c5d6", "sk-lf-1a2b"),
        ("Authorization: Bearer abc.def-ghi_jkl012", "abc.def-ghi"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJlMTIz", "eyJhbGci"),
        ("password=hunter2hunter2", "hunter2"),
        ("mail a.b@example.org", "example.org"),
    ])
    def test_scrubs_ips_and_secrets(self, raw, leak):
        assert leak not in scrub_pii(raw)

    def test_keeps_clock_times_and_archive_references(self):
        s = "Lecture at 11:35:20 on 1936-05-15, passage 3:16, index v2, section 1.2.3.4.5"
        assert scrub_pii(s) == s

    def test_question_hash_survives_redaction(self):
        ref = "sha256:" + hashlib.sha256(b"q").hexdigest()
        assert redact({"question": ref}) == {"question": ref}


class TestRedactKeys:
    def test_drops_answers_prompts_identifiers_and_secrets(self):
        payload = {"sentences": [{"text": "SENTENCE"}], "raw_answer": "GEN", "excerpt": "PASSAGE", "prompt": "SYS",
                   "history": [{"q": "prev"}], "session_id": "raw-session", "IP": "10.0.0.1",
                   "Authorization": "Bearer x", "api_key": "k", "passage_ids": [1, 2], "tokens_in": 10}
        out = redact(payload)
        wire = json.dumps(out)
        for leak in ("SENTENCE", "GEN", "PASSAGE", "SYS", "prev", "raw-session", "10.0.0.1", "Bearer"):
            assert leak not in wire
        assert out["passage_ids"] == [1, 2] and out["tokens_in"] == 10


@pytest.fixture
def exported(monkeypatch, tmp_path):
    """Route the archive's real Langfuse client to an in-memory exporter; nothing leaves the process."""
    import langfuse
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    real = langfuse.Langfuse
    monkeypatch.setattr(langfuse, "Langfuse", lambda **kw: real(**kw, span_exporter=exporter))
    # The SDK keeps one resource manager per public key; a fresh key avoids reusing a shut-down one.
    monkeypatch.setenv("ARCHIVE_LANGFUSE_PUBLIC_KEY", f"pk-lf-unit-{uuid.uuid4().hex}")
    monkeypatch.setenv("ARCHIVE_LANGFUSE_SECRET_KEY", "sk-lf-unit-redaction")
    monkeypatch.setenv("ARCHIVE_LANGFUSE_HOST", "http://127.0.0.1:9")
    monkeypatch.setenv("ARCHIVE_TRACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    tracing._langfuse.cache_clear()
    yield exporter
    client = tracing._langfuse()
    if client is not None:
        client.shutdown()
    tracing._langfuse.cache_clear()
    monkeypatch.undo()
    get_settings.cache_clear()


def _wire(exporter) -> tuple[str, dict]:
    spans = exporter.get_finished_spans()
    return json.dumps([{"name": s.name, **dict(s.attributes)} for s in spans], default=str), {s.name: s for s in spans}


class TestGenerateNodeTiming:
    def test_generate_span_records_when_the_model_call_ran(self, monkeypatch):
        from archive.ask import graph
        from archive.ask.llm import LLMResult

        monkeypatch.setattr(get_settings(), "llm_external", False)

        class SlowLLM:
            model = "slow-test-double"

            def complete(self, system, user, max_tokens):
                time.sleep(0.05)
                return LLMResult('{"sentences": []}', 5, 1, 0, self.model, 50)

        hit = {"passage_id": 1, "item_id": 1, "text": "t", "quote_verified": False, "citation": "c",
               "rerank_score": 0.9}
        before = time.time_ns()
        out = graph.generate({"question": "q", "language": "en", "hits": [hit], "trace_spans": []},
                             graph.AskDeps(db=None, llm=SlowLLM()))
        after = time.time_ns()
        span = out["trace_spans"][-1]
        assert before <= span["start_ns"] < span["end_ns"] <= after
        assert span["end_ns"] - span["start_ns"] >= 50_000_000


class TestLangfuseExport:
    def test_ask_trace_is_redacted_and_carries_usage_and_prompt_version(self, exported):
        assert tracing.backend_name() == "langfuse"
        question = "I am a@b.org, phone 98765 43210, from 10.1.2.3. What did the assembly decide?"
        with tracing.trace("ask", {"session": "ab" * 8, "question": tracing.question_ref(question),
                                   "prompt_version": "ask-v1", "session_id": "raw-session-id"}) as tr:
            tr.span("retrieve", passage_ids=[7, 9], scores=[0.8, 0.4], text="FULL PASSAGE BODY")
            tr.span("generate", model="gpt-4o-mini", tokens_in=812, tokens_out=64, cost_usd=0.00016,
                    latency_ms=900, prompt_version="ask-v1")
            tr.update(outcome="answered", passage_ids=[7], sentences=[{"text": "GENERATED ANSWER"}])
        wire, by_name = _wire(exported)
        for leak in ("a@b.org", "10.1.2.3", "98765", "FULL PASSAGE BODY", "GENERATED ANSWER", "raw-session-id"):
            assert leak not in wire
        assert "What did the assembly decide?" in wire  # scrubbed question is allowed by spec 6.6
        gen = by_name["generate"].attributes
        assert gen["langfuse.observation.type"] == "generation"
        assert gen["langfuse.version"] == "ask-v1"
        assert json.loads(gen["langfuse.observation.usage_details"]) == {"input": 812, "output": 64}
        assert json.loads(gen["langfuse.observation.cost_details"]) == {"total": 0.00016}
        assert by_name["ask"].attributes["langfuse.version"] == "ask-v1"
        assert {s.instrumentation_scope.name for s in exported.get_finished_spans()} == {"langfuse-sdk"}

    def test_unpriced_generation_leaves_cost_to_langfuse(self, exported):
        with tracing.trace("ask", {"prompt_version": "ask-v1"}) as tr:
            tr.span("generate", model="gpt-4o-mini", tokens_in=10, tokens_out=2, cost_usd=0.0)
        _, by_name = _wire(exported)
        assert "langfuse.observation.cost_details" not in by_name["generate"].attributes

    def test_failure_is_marked_error_with_scrubbed_message(self, exported):
        with pytest.raises(RuntimeError), tracing.trace("ask", {"prompt_version": "ask-v1"}) as tr:
            tr.span("generate", error="provider said: Incorrect API key sk-proj-AbCdEf0123456789xyz")
            raise RuntimeError("boom for a@b.org")
        wire, by_name = _wire(exported)
        assert "sk-proj-AbCdEf" not in wire and "a@b.org" not in wire
        assert by_name["ask"].attributes["langfuse.observation.level"] == "ERROR"
        assert by_name["generate"].attributes["langfuse.observation.level"] == "ERROR"

    def test_generation_span_carries_the_model_call_start_and_end(self, exported):
        with tracing.trace("ask", {"prompt_version": "ask-v1"}) as tr:
            start = time.time_ns()
            end = start + 900_000_000
            tr.span("retrieve", passage_ids=[7])
            tr.span("generate", model="gpt-4o-mini", tokens_in=10, tokens_out=2, latency_ms=900,
                    start_ns=start, end_ns=end, text="PASSAGE")
        wire, by_name = _wire(exported)
        gen = by_name["generate"]
        assert (gen.start_time, gen.end_time) == (start, end)
        assert by_name["ask"].start_time <= start
        assert "start_ns" not in wire and "PASSAGE" not in wire
        assert gen.attributes["langfuse.observation.type"] == "generation"
        assert gen.parent.span_id == by_name["ask"].context.span_id

    def test_third_party_otel_spans_are_not_exported(self, exported):
        with tracing.trace("ask", {"prompt_version": "ask-v1"}):
            provider = tracing._langfuse()._resources.tracer_provider
            third_party = provider.get_tracer("opentelemetry.instrumentation.openai")
            with third_party.start_as_current_span("chat gpt", attributes={"gen_ai.prompt": "LEAK a@b.org"}):
                pass
        wire, by_name = _wire(exported)
        assert "ask" in by_name and "chat gpt" not in by_name and "LEAK" not in wire
