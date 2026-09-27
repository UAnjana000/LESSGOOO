"""Send ONE real Ask through the archive's own code path and confirm the redacted trace in Langfuse.

Run inside the api image (one-off container, no rebuild/recreate), e.g. docs/LANGFUSE.md "Verify".
Prints only non-secret evidence. Exit code 0 only if the trace arrived and every leak check passed.
Makes at most 2 LLM calls (one generation, plus one regeneration if citation validation fails).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
import uuid

import httpx

from archive import tracing
from archive.ask.service import ask
from archive.config import get_settings
from archive.db import new_session
from archive.models import AnswerLog

# Synthetic visitor PII that must never reach Langfuse. Kept short: the question must still clear the
# retrieval sufficiency threshold so a real generation happens (phones are covered by unit tests).
# A fresh email per run avoids an answer-cache hit.
EMAIL, IP = f"p{uuid.uuid4().hex[:6]}@x.in", "10.0.0.7"
QUESTION = f"Email {EMAIL}, IP {IP}. According to the lecture on education, why should mothers learn to read?"


def main() -> int:
    s = get_settings()
    if not s.langfuse_enabled:
        print(json.dumps({"ok": False, "reason": "ARCHIVE_LANGFUSE_* not configured"}))
        return 2
    session_id = f"lf-verify-session-{uuid.uuid4().hex}"
    started = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    db = new_session()
    try:
        payload = ask(db, QUESTION, [], "en", session_id)
        log = db.get(AnswerLog, payload["answer_id"])
        db_row = {"answer_id": log.id, "trace_id": log.trace_id, "tokens_in": log.tokens_in,
                  "tokens_out": log.tokens_out, "latency_ms": log.latency_ms, "prompt_version": log.prompt_version,
                  "question_ref": log.question_ref}
    finally:
        db.close()

    auth = (s.langfuse_public_key, s.langfuse_secret_key)
    url = s.langfuse_host.rstrip("/") + "/api/public/v2/observations"
    params = {"traceId": payload["trace_id"], "limit": 100, "fromStartTime": started.isoformat(),
              "fields": "core,basic,io,metadata,model,usage,metrics,prompt,trace_context"}
    rows: list[dict] = []
    for _ in range(40):  # ingestion is async (worker -> ClickHouse)
        r = httpx.get(url, params=params, auth=auth, timeout=10)
        r.raise_for_status()
        rows = r.json().get("data", [])
        names = {o.get("name") for o in rows}
        if "ask" in names and ("generate" in names or payload.get("tokens_in", 0) == 0):
            break
        time.sleep(3)

    wire = json.dumps(rows, ensure_ascii=False)
    excerpts = [c["excerpt"][:60] for c in payload.get("citations", []) if len(c.get("excerpt", "")) >= 40]
    sentences = [x["text"][:60] for x in payload.get("sentences", []) if len(x.get("text", "")) >= 30]
    leaks = {
        "visitor_email": EMAIL in wire or EMAIL.split("@")[0] in wire,
        "visitor_ip": IP in wire,
        "raw_session_id": session_id in wire,
        "passage_excerpt_text": any(e in wire for e in excerpts),
        "generated_answer_text": any(t in wire for t in sentences),
        "llm_api_key": bool(s.llm_api_key) and s.llm_api_key in wire,
        "langfuse_secret_key": s.langfuse_secret_key in wire,
        "jwt_secret": bool(s.jwt_secret) and s.jwt_secret in wire,
    }
    root = next((o for o in rows if o.get("name") == "ask"), {})
    gen = next((o for o in rows if o.get("name") == "generate" and o.get("type") == "GENERATION"), {})
    meta = root.get("metadata") or {}
    if isinstance(meta, str):
        meta = json.loads(meta or "{}")
    evidence = {
        "trace_backend": tracing.backend_name(),
        "trace_id": payload["trace_id"], "outcome": payload["outcome"], "cache_hit": payload.get("cache_hit"),
        "citations": [c["passage_id"] for c in payload.get("citations", [])],
        "answer_log": {k: v for k, v in db_row.items() if k != "question_ref"},
        "answer_log_question_ref_has_placeholders": all(p in db_row["question_ref"] for p in ("[email]", "[ip]")),
        "observations": sorted(f"{o.get('type')}:{o.get('name')}" for o in rows),
        "root": {"latency": root.get("latency"), "version": root.get("version"), "level": root.get("level"),
                 "environment": root.get("environment"), "metadata_keys": sorted(meta),
                 "metadata_question": meta.get("question"), "metadata_prompt_version": meta.get("prompt_version")},
        "generation": {"model": gen.get("model") or gen.get("providedModelName"), "version": gen.get("version"),
                       "provider_latency_ms": (gen.get("metadata") or {}).get("latency_ms")
                       if isinstance(gen.get("metadata"), dict) else None,
                       "usageDetails": gen.get("usageDetails"), "totalCost": gen.get("totalCost"),
                       "costDetails": gen.get("costDetails")},
        "leaks": leaks,
    }
    ok = (bool(root) and bool(gen) and not any(leaks.values()) and root.get("version") == s.prompt_version
          and (gen.get("usageDetails") or {}).get("input", 0) > 0 and root.get("latency") is not None
          and bool(evidence["generation"]["model"]))
    evidence["ok"] = ok
    print(json.dumps(evidence, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
