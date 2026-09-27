"""A-14: the answer model reuses one pooled HTTP client per process instead of one per request."""

from __future__ import annotations

import threading
import time

import httpx
import pytest

import archive.ask.llm as llm_mod
from archive.config import get_settings

REPLY = {"model": "test-model", "choices": [{"message": {"content": '{"sentences": []}'}}],
         "usage": {"prompt_tokens": 10, "completion_tokens": 2}}


@pytest.fixture
def counted_clients(monkeypatch):
    """Replace httpx.Client inside llm.py with one that counts constructions and answers locally."""
    real_client = httpx.Client
    made: list[httpx.Client] = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=REPLY)

    def factory(**kwargs):
        time.sleep(0.02)  # widen the race window for the concurrency test
        c = real_client(transport=httpx.MockTransport(handler), **kwargs)
        made.append(c)
        return c

    monkeypatch.setattr(llm_mod.httpx, "Client", factory)
    monkeypatch.setattr(llm_mod, "_shared", None, raising=False)
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "openai_compatible")
    monkeypatch.setattr(s, "llm_api_key", "test-key-not-real")
    monkeypatch.setattr(s, "llm_model", "test-model")
    yield made, requests, real_client
    for c in made:
        c.close()


def test_each_request_reuses_the_same_client(counted_clients):
    made, requests, _ = counted_clients
    first = llm_mod.get_llm().complete("sys", "user one", 50)
    second = llm_mod.get_llm().complete("sys", "user two", 50)
    assert first.content == second.content == '{"sentences": []}'
    assert len(requests) == 2 and len(made) == 1


def test_pooled_client_keeps_the_request_timeout(counted_clients):
    made, _, _ = counted_clients
    llm_mod.get_llm()
    assert made[0].timeout.read == 45 and made[0].timeout.connect is not None


def test_concurrent_first_use_builds_one_client(counted_clients):
    made, _, _ = counted_clients
    seen: list[httpx.Client] = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        seen.append(llm_mod.OpenAICompatibleLLM()._client)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(made) == 1 and all(c is made[0] for c in seen)


def test_an_injected_client_is_used_as_given(counted_clients):
    made, _, real_client = counted_clients
    own = real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=REPLY)))
    try:
        assert llm_mod.OpenAICompatibleLLM(client=own)._client is own and made == []
    finally:
        own.close()
