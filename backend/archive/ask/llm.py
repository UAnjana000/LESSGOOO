"""Answer-model interface. One provider behind one interface (spec 11: provider outage/price change).

OpenAICompatibleLLM speaks the /chat/completions protocol used by OpenAI, Sarvam-M, vLLM, Ollama and
most hosted providers, so the institution can choose a provider without code changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from archive.config import get_settings


@dataclass
class LLMResult:
    content: str
    tokens_in: int
    tokens_out: int
    cached_tokens: int
    model: str
    latency_ms: int
    raw: dict = field(default_factory=dict)


class LLMUnavailable(RuntimeError):
    pass


class AnswerLLM(Protocol):
    model: str

    def complete(self, system: str, user: str, max_tokens: int) -> LLMResult: ...


class OpenAICompatibleLLM:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None,
                 client: httpx.Client | None = None) -> None:
        s = get_settings()
        self.base_url = (base_url or s.llm_base_url).rstrip("/")
        self.api_key = api_key or s.llm_api_key
        self.model = model or s.llm_model
        self._client = client or httpx.Client(timeout=45)

    def complete(self, system: str, user: str, max_tokens: int) -> LLMResult:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        t0 = time.perf_counter()
        try:
            resp = self._client.post(f"{self.base_url}/chat/completions", json=body,
                                     headers={"Authorization": f"Bearer {self.api_key}"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(str(exc)) from exc
        data = resp.json()
        usage = data.get("usage") or {}
        return LLMResult(
            content=data["choices"][0]["message"]["content"] or "",
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            cached_tokens=int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)),
            model=data.get("model", self.model),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )


def get_llm() -> AnswerLLM | None:
    s = get_settings()
    if not s.llm_available:
        return None
    return OpenAICompatibleLLM()


def cost_usd(tokens_in: int, tokens_out: int) -> float:
    s = get_settings()
    return round(tokens_in / 1e6 * s.llm_input_cost_per_mtok + tokens_out / 1e6 * s.llm_output_cost_per_mtok, 6)
