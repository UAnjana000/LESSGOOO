"""Local embedding model and reranker (run on the edge server, never on the tablet).

Live models (ONNX via fastembed, no PyTorch):
  embedder: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384-d, 50+ languages incl. hi, mr)
  reranker: jinaai/jina-reranker-v2-base-multilingual (cross-encoder, multilingual)

Test doubles (deterministic, NOT semantic) are used only in automated tests or when
ARCHIVE_EMBEDDING_BACKEND=hash / ARCHIVE_RERANKER_BACKEND=lexical; they are reported as such by /api/health.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from functools import lru_cache
from typing import Protocol

import numpy as np

from archive.config import get_settings

log = logging.getLogger(__name__)
_TOKEN = re.compile(r"\w+", re.UNICODE)
_FILLER = {"what", "which", "who", "whom", "whose", "when", "where", "why", "how", "did", "does", "do", "is", "are",
           "was", "were", "be", "been", "the", "a", "an", "of", "in", "on", "at", "to", "for", "from", "by", "with",
           "and", "or", "about", "tell", "me", "please", "say", "said", "can", "you", "there", "this", "that"}


class Embedder(Protocol):
    name: str
    is_test_double: bool

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    name: str
    is_test_double: bool

    def score(self, query: str, docs: list[str]) -> list[float]: ...


class HashEmbedder:
    """Deterministic bag-of-hashed-tokens embedding. Test double only: not cross-lingual, not semantic."""

    is_test_double = True

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.name = f"hash-embedder-{dim}"

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in _TOKEN.findall(text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
        n = np.linalg.norm(v)
        return (v / n if n else v).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class LexicalReranker:
    """Share of the query's content words found in each passage (0..1). Test double only. Question framing
    words ("what", "the", "of") occur in almost every passage, so they are left out unless nothing else is left."""

    is_test_double = True
    name = "lexical-overlap-reranker"

    def score(self, query: str, docs: list[str]) -> list[float]:
        words = set(_TOKEN.findall(query.lower()))
        q = (words - _FILLER) or words
        out = []
        for d in docs:
            dt = set(_TOKEN.findall(d.lower()))
            overlap = len(q & dt) / (len(q) or 1)
            out.append(round(overlap, 4))
        return out


class FastEmbedEmbedder:
    is_test_double = False

    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed import TextEmbedding

        self.name = model
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)
        self._lock = threading.Lock()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            return [v.tolist() for v in self._model.embed(texts, batch_size=16)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class FastEmbedReranker:
    is_test_double = False

    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.name = model
        self._model = TextCrossEncoder(model_name=model, cache_dir=cache_dir)
        self._lock = threading.Lock()

    def score(self, query: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        with self._lock:
            raw = list(self._model.rerank(query, docs, batch_size=16))
        # Logits -> 0..1 so the sufficiency threshold is interpretable.
        return [round(1 / (1 + math.exp(-float(s))), 4) for s in raw]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_backend == "hash":
        return HashEmbedder(s.embedding_dim)
    return FastEmbedEmbedder(s.embedding_model, str(s.model_cache))


@lru_cache
def get_reranker() -> Reranker:
    s = get_settings()
    if s.reranker_backend == "lexical":
        return LexicalReranker()
    return FastEmbedReranker(s.reranker_model, str(s.model_cache))


def model_status() -> dict[str, object]:
    s = get_settings()
    return {
        "embedding_backend": s.embedding_backend,
        "embedding_model": s.embedding_model if s.embedding_backend == "fastembed" else "hash test double",
        "reranker_backend": s.reranker_backend,
        "reranker_model": s.reranker_model if s.reranker_backend == "fastembed" else "lexical test double",
    }
