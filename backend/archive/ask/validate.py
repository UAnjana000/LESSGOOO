"""Code-checkable answer validation (spec 5.7 step 7).

Checks: every cited passage exists and was retrieved; every sentence carries a citation; every quoted
span appears verbatim in a cited passage AND that passage is quote-verified.

This does NOT prove a paraphrased claim is supported by its citation. Claim support is measured by
human grading on the evaluation question set, never asserted by this module.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

QUOTE_RE = re.compile(r"[\"“”„«»](.+?)[\"“”„«»]")
MIN_QUOTE_CHARS = 12


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass
class Sentence:
    text: str
    citations: list[int]


@dataclass
class ValidationResult:
    ok: bool
    sentences: list[Sentence] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    quotes: list[dict[str, Any]] = field(default_factory=list)
    has_quote_errors: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "quotes": self.quotes,
                "sentences": len(self.sentences), "has_quote_errors": self.has_quote_errors}


def parse_answer(raw: str) -> list[Sentence]:
    """Expect {"sentences": [{"text": "...", "citations": [12, 15]}]}; citations may be 'P12' strings."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("answer is not JSON")
    data = json.loads(raw[start:end + 1])
    out = []
    for s in data.get("sentences", []):
        cites = []
        for c in s.get("citations", []):
            m = re.search(r"\d+", str(c))
            if m:
                cites.append(int(m.group()))
        out.append(Sentence(text=str(s.get("text", "")).strip(), citations=cites))
    return out


def extract_quotes(text: str) -> list[str]:
    return [q.strip() for q in QUOTE_RE.findall(text) if len(q.strip()) >= MIN_QUOTE_CHARS]


def validate(raw: str, retrieved: dict[int, dict[str, Any]]) -> ValidationResult:
    """retrieved: passage_id -> {"text": str, "quote_verified": bool}"""
    try:
        sentences = parse_answer(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        return ValidationResult(ok=False, errors=[f"unparseable: {exc}"])
    res = ValidationResult(ok=True, sentences=sentences)
    if not sentences:
        res.ok = False
        res.errors.append("no sentences")
    for i, s in enumerate(sentences):
        if not s.text:
            res.errors.append(f"sentence {i} empty")
        if not s.citations:
            res.errors.append(f"sentence {i} has no citation")
        unknown = [c for c in s.citations if c not in retrieved]
        if unknown:
            res.errors.append(f"sentence {i} cites passages not in the retrieved set: {unknown}")
        for q in extract_quotes(s.text):
            nq = normalise(q)
            hits = [c for c in s.citations if c in retrieved and nq in normalise(retrieved[c]["text"])]
            verified = [c for c in hits if retrieved[c].get("quote_verified")]
            entry = {"sentence": i, "span_chars": len(q), "found_in": hits, "verified_in": verified}
            res.quotes.append(entry)
            if not hits:
                res.errors.append(f"sentence {i} quote not found verbatim in its cited passages")
                res.has_quote_errors = True
            elif not verified:
                res.errors.append(f"sentence {i} quotes a passage that is not quote-verified")
                res.has_quote_errors = True
    res.ok = not res.errors
    return res
