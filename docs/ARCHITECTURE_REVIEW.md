# Architecture review: AI workflows (LangGraph / LangChain / Langfuse) — 2026-09-27

Scope: `backend/archive/ask/**`, `backend/archive/ingest/graph.py`, `processing.py`, `textlayer.py`,
`backend/archive/search/**`, `backend/archive/tracing.py`, `backend/archive/config.py`, `pyproject.toml`,
checked against the Revised Architecture Spec §4.9, §5.7, §6.1, §6.6 and §10.

Every number below is measured on this machine (Windows, Python 3.12.11, local Postgres 16 + pgvector in
Docker) unless it is labelled *extrapolated* or *UNMEASURED*. Raw outputs are in `eval/results/`.

## Skills used

| Skill | Source | What it changed |
| --- | --- | --- |
| find-skills | `C:\Users\cvbal\.agents\skills\find-skills` | Used to pick local skills first; every need below was covered locally, so no marketplace install. |
| senior-architect | `~/.claude/plugins/cache/claude-code-skills/engineering-skills/2.2.0/senior-architect` | Findings are framed as architecture decisions against the spec (framework roles, system of record), with severity. |
| agent-workflow-designer | `~/.claude/plugins/cache/claude-code-skills/engineering-advanced-skills/2.2.0/agent-workflow-designer` | "Smallest pattern that satisfies requirements", explicit bounded handoffs, and validation gates. This is why the Ask graph was made a DAG (structural bound) rather than a loop with a counter. |
| rag-architect | `~/.claude/plugins/cache/claude-code-skills/engineering-advanced-skills/2.2.0/rag-architect` | Retrieval metrics (Recall@k, MRR) and context-window budgeting (fixed top-k, per-passage cap) used in the benchmark. |
| llm-cost-optimizer | `~/.claude/plugins/cache/claude-code-skills/engineering-advanced-skills/2.2.0/llm-cost-optimizer` | "Measure before optimising": instrument per-request tokens first; per-endpoint `max_tokens`; stable prefix for provider caching; cache-key design. |
| performance-profiler | `~/.claude/plugins/cache/claude-code-skills/engineering-advanced-skills/2.2.0/performance-profiler` | Baseline → fix → re-measure with the same harness; before/after tables with sample sizes. The text-layer benchmark counts renders and opens to confirm the root cause, not just wall time. |
| code-reviewer | `~/.claude/plugins/cache/claude-code-skills/engineering-skills/2.2.0/code-reviewer` | Severity-ranked findings with file:line. |
| python-testing-patterns | `~/.claude/skills/python-testing-patterns` | AAA tests, monkeypatch-based counters, parametrised document lengths, test doubles instead of live providers. |
| verification-before-completion | `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.4.1/skills/verification-before-completion` | No claim without a fresh run. The regression tests were checked red-green: they fail against the original code and pass with the fix. |

---

## Ingestion finding (priority, on the critical path for the real-excerpt ingestion)

### I-1 [Critical] Born-digital text-layer extraction was quadratic in PDF page count — FIXED

Reported by the data engineer. Confirmed and root-caused:

- `processing._page_image` (was `processing.py:64`) called `extract_pdf(data)[idx]`. `extract_pdf` opens the
  whole PDF, extracts text from **every** page and renders **every** page to PNG, and then the caller keeps one page.
- `process_page`'s born-digital branch (was `processing.py:139`) called `extract_pdf(...)` **again** for the same page.
- The PDF bytes were also re-read from storage on each call.

So each page cost 2 opens, 2×N renders and 2×N text extractions. An N-page item therefore cost 2N² renders.
Scanned PDFs routed to printed OCR paid N renders per page through `_page_image`. The Sarvam retry path paid
another N.

**Fix**

- `textlayer.py`: new `PdfPages` class. It parses the PDF once (pypdf + pypdfium2, still imported lazily) and
  gives `text(i)` and `render_png(i)` for one page at a time. The page and bitmap handles are closed after each
  render, and `close()` or the context manager releases the pdfium document.
- `extract_pdf` is kept for whole-document callers and is now built on `PdfPages`.
- `text_layer_reliable`, including the Devanagari share rule, is unchanged.
- `processing.py`: the context manager `pdf_documents()` holds one parsed `PdfPages` per preservation-master
  file for the duration of an item run and closes them all on exit.
- `_page_image` renders only its page. The born-digital branch extracts only its page's text.
- Outside the scope (for example the worker's single-page `sarvam_retry`), a call opens, uses and closes its
  own document, so it still costs one page.
- `ingest/graph.py` `process_pages`: the page loop runs inside `processing.pdf_documents()`.

**Tests**

- `tests/test_unit_textlayer.py::TestPdfPerPageCost`, no DB. It uses synthetic PDFs from `make_pdf` in
  `fixtures/generate_fixtures.py`, generated inside the test, and counts real pdfium opens/closes, page renders,
  pypdf text extractions and storage reads:
  - single-page access costs exactly 1 open, 1 render, 1 text extraction and 1 close for both 3- and 24-page PDFs
  - an item run over all pages of a 3- and 12-page PDF does 1 storage read, 1 open, 1 close, N renders and N extractions
  - one page outside an item run costs 1 render and 1 extraction, with nothing left open
  - `extract_pdf` still returns every page
- `tests/test_db_pipeline.py::test_ingest_graph_parses_a_multi_page_pdf_once_per_item`: the real LangGraph
  ingestion graph (in-memory checkpointer) on an 8-page born-digital item does `{"opens": 1, "renders": 8}`.
- Red-green: with the original `processing.py` restored, the three process-page tests fail: 24 renders for one
  page of a 12-page PDF, and 6 storage reads for a 3-page item. They pass with the fix.

**Before / after** (`eval/bench/bench_textlayer.py`)

The benchmark runs the real `process_page` born-digital route: delivery render, JPEG delivery copy and text layer.
The DB is replaced by an in-memory stand-in and storage goes to a temp dir. The synthetic pages are light
(Helvetica text only), so absolute times on real scans are higher, but the scaling is the same.

| PDF pages | Before: per page (n=5 sampled pages) | Before: item total | After: per page (all pages) | After: item total (measured) | Renders per page before → after | Opens per item before → after |
| --- | --- | --- | --- | --- | --- | --- |
| 50 | 1,888 ms | 94 s (*extrapolated* 5 pages × 50) | 57.5 ms (n=50) | 2.9 s | 100 → 1 | 100 → 1 |
| 200 | 7,678 ms | 1,536 s ≈ 26 min (*extrapolated*) | 72.8 ms (n=200) | 14.6 s | 400 → 1 | 400 → 1 |
| 516 | ≈19.8 s (*extrapolated*, linear in N from the 200-page row) | ≈2.8 h (*extrapolated*) | 70.5 ms (n=516) | 36.4 s | ≈1,032 → 1 | ≈1,032 → 1 |

Before, per-page cost grew linearly with N, so the item total grew with N². After, per-page cost is flat
(57–73 ms for 50–516 pages), so the item total is linear. The data engineer's 9-hour estimate for a real
516-page volume is consistent with this: real scanned pages render slower than these synthetic text pages.

Remaining cost notes:

- A page that fails the gate and goes to Sarvam is rendered one more time, by `run_sarvam` → `_page_image`. That
  is one extra render, not N.
- Intake (`intake.create_pages_for_file`) parses each PDF once to count pages. That is unchanged and linear.

### I-2 [Medium] One failing page aborted the whole ingestion node — FIXED

`ingest/graph.py` `process_pages` (was line 51) called `processing.process_page` for every pending page with
no error handling. One corrupt page stream raised out of the node, the run stopped, and the pages after it were
never processed. The graph had no defined state for a page-level failure.

- Fix (`ingest/graph.py:52-70`): each page is processed inside its own `try`. On failure the page's session
  work is rolled back, a `page.process_failed` audit event (actor, page id, exception type and a short message)
  is committed, and the outcome is `route="error"`. The page stays `pending`, so a staff member or a rerun can
  retry it. The rest of the item continues and still reaches the review interrupt.
- Test: `tests/test_db_pipeline.py::test_one_failing_page_is_audited_and_does_not_abort_the_item`. A 3-page
  synthetic PDF in which page 2 raises gives routes `text_layer, error, text_layer`, statuses
  `in_batch_review, pending, in_batch_review`, one audit event and an interrupt. Red-green: it fails on the
  original `ingest/graph.py` (the `RuntimeError` escapes `process_pages`) and passes with the fix.

---

## Ask (visitor question answering) findings

Line numbers marked *was* refer to `HEAD` before this review; the others refer to the working tree.

### High

**A-1 Citations were validated against every retrieved passage, not against the passages in the prompt — FIXED**

- *Was* `ask/graph.py:217` (`retrieved = {h["passage_id"]: h for h in state["hits"]}`) and `ask/service.py:83`
  (`by_id` built from all hits). The generate node put only the *strong* hits (score ≥ half the threshold) in the
  prompt, but validation and the delivered citations accepted any retrieved id. The model could cite a passage it
  had never seen, and the answer would pass as cited.
- Fix: the generate node records `prompt_ids` (`ask/graph.py:263`). `_validate` checks citations and quotes only
  against those passages (`ask/graph.py:293-305`), and the service builds citations only from them
  (`ask/service.py:83`).
- Test: `test_db_ask_datasets.py::TestAskRightsAndCitations::test_citing_a_retrieved_but_unprompted_passage_is_rejected`.

**A-2 No external-processing rights check before the hosted answer model — FIXED**

- *Was* `ask/graph.py:185-199`. Every strong passage went to the hosted model (OpenAI). The rights register has a
  per-source `external_processing` field, and `rights.external_processing_allowed()` existed, but Ask never
  called it. In the working data, 3 `cad_lok_sabha` sources are `external_processing: not_allowed`. In the
  benchmark corpus the baseline sent **36 local-only passages** to the model over 81 question runs.
- Fix: `rights.external_processing_item_ids()` (`rights.py:67`) is used by `_generate` (`ask/graph.py:245-262`)
  whenever `ARCHIVE_LLM_EXTERNAL` is true (the default). Passages whose item does not allow external processing,
  or whose item is restricted, are withheld from the prompt. If nothing sendable remains, there is no model call.
  The outcome is `extractive` with reason `local_only`, and the visitor sees the new `local_only` message
  (`ask/policy.py`, in en/hi/mr) with the closest approved passages. A local answer model
  (`ARCHIVE_LLM_EXTERNAL=false`) may read them.
- Tests: `TestAskRightsAndCitations` covers the local-only passage never reaching the external model, local-only
  evidence alone giving extractive passages with no model call, and a local model being allowed to read them.
- Follow-up found with the live model: when some strong passages were withheld and gpt-4o-mini found no support
  in the rest (live `en-08`, `en-14`), the visitor got a bare "insufficient" message although the archive held a
  readable answer. `_generate` now records `withheld_ids`, and `abstain` turns *no support + withheld passages*
  into `extractive` / `local_only`: the closest approved passages are shown with the rights message. Test:
  `test_no_support_after_withholding_says_so_and_shows_the_withheld_passage`, red on the previous code and green
  now. Re-checked live: both questions now give `extractive` with the `local_only` message (2 calls).
- Measured: local-only passages sent to the model went from 36 to **0** (tables below).

### Medium

**A-3 The retry bound was a flag or counter inside a cycle, not structure — FIXED**

- *Was* `ask/graph.py:165-168` (`retried` flag), `:230-236` (regenerate while `attempt < 2`) and `:259-263`
  (back edges to `retrieve` and `generate`). The bound held only as long as every node set its flag correctly.
- Fix: the graph is now a DAG. `retrieve → retry_retrieve` happens at most once, because `retry_retrieve` has no
  edge back. `generate → validate → generate_paraphrase → validate_paraphrase` happens at most once, because
  the paraphrase path has its own nodes and ends in `finalize` or `abstain`. `RECURSION_LIMIT = 12` is passed on
  every invoke (`ask/graph.py:44`, `run_graph`).
- Test: `test_unit_gate_and_validation.py::TestAskGraphShape` checks that the compiled graph is acyclic, that the
  longest path has 11 nodes (under the limit), and that there is exactly one retry node.

**A-4 Node failures raised to the API instead of reaching a defined state — FIXED**

- *Was* `ask/graph.py:153-157`: retrieval (Postgres, embedder, reranker) had no error handling.
- *Was* `ask/graph.py:195-199`: only `LLMUnavailable` was caught. `llm.py:63-66` (`resp.json()`,
  `data["choices"][0]`) can raise `ValueError` or `KeyError` on a malformed provider response.
- Fix: retrieval, retry retrieval and the refusal browse catch failures and set `outcome="error"` with reason
  `retrieval unavailable`. Generation catches any `Exception` and sets `outcome="error"`. Language detection falls
  back to the UI language. The service already maps `error` to the "answer service unavailable" message and logs it.
- Tests: `TestAskNodeFailures` covers a retrieval failure and a malformed provider response (`KeyError`).

**A-5 Follow-up retry ignored the conversation history — FIXED**

- *Was* `ask/graph.py:92-93` and `:170-171`. The history rewrite fired only for short questions or questions
  with pronouns, and the retry just keywordised the question. The baseline failed `fu-03` ("Why was no charge
  made, and so on?") on every run.
- Fix: when there is history and the first pass did not rewrite, `retry_retrieve` forces the history rewrite
  (`rewrite_query(..., force=True)`) before keywordising and merges the results.
- Test: `test_weak_long_follow_up_retries_once_with_history_context`. In the benchmark, follow-up behaviour went
  from 6/9 to 9/9.

**A-6 Short multi-word quotes skipped the verbatim check — FIXED**

- *Was* `ask/validate.py:19` and `:64-65`. Only quotes of 12 characters or more were checked, so `"no fee"` or
  `"six lamps"` could be wrapped in quote marks without being an exact substring of a quote-verified passage.
- Fix: a quote is checked if it has at least 12 characters **or** at least 2 words. Single-word term mentions are
  still ignored, as the existing test requires.
- Test: `test_short_multi_word_quote_must_still_be_verbatim`.

**A-7 Spans carried no node timings (§6.6) — FIXED**

Every node is wrapped by `_timed` (`ask/graph.py:161`), which adds `ms` to the node's span. The spans go into the
trace through the existing redacting `tracing.py`, which was not edited.

**A-8 The cross-encoder scored 30 candidates per question and dominated latency — TUNED**

In the baseline with real models, reranking was p50 3.8 s out of a 4.0 s end to end (95%). The pool is now a
setting (`ARCHIVE_RERANK_CANDIDATE_K`), reranking happens in the Ask graph, and the default is 15. The evidence is
in "Optimisation" below.

**A-9 `load_hits` runs extra queries per passage — HANDED OFF**

`search/hybrid.py:153-182`. `articles_by_passage` runs its own query, `item.rights.attribution` lazy-loads per
item, and the photo metadata join adds another query. `load_hits` was p50 93–156 ms in the benchmark, the largest
non-model cost after reranking. This file is under active edit by the visitor-features engineer, so it was not
changed here.

### Low

| # | Finding | Where | Status |
| --- | --- | --- | --- |
| A-10 | Ask graph compiled on every request (7.15 ms measured per compile) | *was* `ask/service.py:74` | FIXED: `build_ask_graph()` is `@lru_cache` and compiled once. Per-request dependencies (db, llm, translator) go in through LangGraph `context_schema=AskDeps` / `Runtime` instead of closures. |
| A-11 | The delivery rights check loaded full hits (joins, labels) only to read their ids | *was* `ask/service.py:28-30` | FIXED: `rights.visible_passage_ids()` is an id-only query using the same `passage_visible()` predicate. |
| A-12 | `daily_cost()` queried twice per answer | *was* `ask/service.py:138-140` | FIXED: queried once, and only when this answer had a cost. |
| A-13 | The answer cache key uses `ui_language`, not the detected question language | `ask/service.py:56` | RECORDED. The same Hindi question asked from the English UI misses the cache. Harmless for correctness. |
| A-14 | `get_llm()` builds a new `httpx.Client` per request (no keep-alive, TLS handshake every answer) | `ask/llm.py:46`, `:75-79` | HANDED OFF to the engineer fixing the live OpenAI call. |
| A-15 | The worker's `ingest_item` does not check `has_checkpoint` before invoking | `worker.py:38` | RECORDED. The DB page statuses make a rerun idempotent. |
| A-16 | `pyproject.toml` has lower bounds only for langgraph / langchain / langfuse | `pyproject.toml:16-19` | RECORDED. Add upper bounds below the next major version. |
| A-17 | The ingestion graph uses LangGraph's default `recursion_limit` | `ingest/graph.py:125-141` | Info. The graph is linear plus one interrupt, so the default is enough. |

### Checked and compliant

- **LangGraph state and nodes.** `AskState` and `IngestState` are `TypedDict`s. Each Ask node does one thing.
  The spec branches (input policy, sufficiency, validation, paraphrase fallback) are conditional edges.
- **Checkpointing.** Ingestion uses `PostgresSaver` with the stable thread id `ingest-item-<id>`. Review is an
  `interrupt()` resumed with `Command(resume=...)`. Ask has no checkpointer by design: each question is
  stateless, and history comes from the client (§5.8).
- **System of record.** PostgreSQL is the system of record. Checkpoints hold ids only. Answer logs, audit events
  and page statuses are rows.
- **LangChain.** The only LangChain package is `langchain-text-splitters` (`RecursiveCharacterTextSplitter` in
  `ingest/publish.py`). It saves real code, and langchain-core 1.6.5 arrives transitively, compatible with
  langgraph 1.2.12. There is no `AgentExecutor`, no tool-calling agent and no hidden prompt template.
  `SYSTEM_PROMPT` and `build_prompt` are plain strings in `ask/graph.py`.
- **Langfuse.** `Langfuse(mask=redact)` redacts before send. Passage bodies, questions and PII are not sent.
  With no keys, traces go to a local JSONL sink. Langfuse is never the audit log (`AuditEvent` rows are).
  `tracing.py` was hardened concurrently by another engineer (IP and secret scrubbing, `should_export_span`),
  so it was not edited here.
- **Rights at both layers.** Retrieval filters with `passage_visible()` in SQL (`search/hybrid.py:_base`).
  Delivery re-checks the cited ids (`ask/service.py:_deliverable`). A-2 adds the external-processing layer for
  the prompt.
- **Quotes.** Direct quotes must be exact normalised substrings of a quote-verified passage in the prompt.
  Paraphrase answers are flagged `paraphrase_only=True`, and quote verification applies only to direct quotes.
  The web UI must not show a "verified" chip on a paraphrase (handoff below).

---

## Optimisation: Ask benchmark (`eval/bench/`)

### Harness

- `eval/bench/bench_ask.py` creates and migrates its own database `archive_bench`, truncates it, and seeds 40
  items: the synthetic fixture texts, 30 distractors, two local-only items (`fx-petition-mr`,
  `fx-online-only`), a restricted item and a withdrawn item. It then runs the 27 questions in
  `eval/bench/ask_questions.json` through the real `archive.ask.service.ask`: 13 en + 2 hi answerable,
  3 local-only, 3 follow-up, 2 not-in-archive, 2 rights probes, 1 refusal and 1 rejected input. It does `--repeat`
  cold passes (answer cache cleared) and one warm pass.
- Two model modes. `--models doubles` uses the hash embedder and the lexical reranker. `--models live` uses the
  real local fastembed models: the MiniLM-L12 multilingual embedder and the Jina v2 multilingual cross-encoder.
- The answer model is a deterministic double. Its input and output tokens are tiktoken `o200k_base` counts of the
  exact system and user text, plus 7 chat-format tokens. `--live-llm N` uses the real model from `.env` instead,
  behind a ledger capped at 20 calls (`eval/results/live-llm-calls.json`).
- Node latency comes from wrapping the functions the graph calls. "other" is the rest of `ask()`: cache lookup,
  graph overhead, answer-log writes and the trace sink. Recall@5 and MRR use the ordered retrieved passages.
  Cost uses gpt-4o-mini list prices ($0.15 per 1M input tokens, $0.60 per 1M output), because `.env` sets no
  prices.
- `eval/bench/bench_rerank.py` times the cross-encoder in **paired** rounds. Every round scores the same fused
  candidates for all 25 retrieval questions under every configuration, in shuffled order, so machine-load drift
  cancels out.

**Load caveat.** During these runs another engineer was rebuilding Docker, and the CPU sat at 100% with about
2 GB of RAM free. Nodes whose code did not change slowed by about 2× between the baseline and the final run
(`load_hits` 93 → 184 ms p50, `keyword` 11 → 28 ms). Compare end-to-end milliseconds *between* runs with that in
mind. The paired rerank benchmark is the reliable latency comparison.

### Before / after, real local models (n = 81 cold question runs each, 27 questions × 3 repeats, answer-model double)

| Metric | Before (HEAD) | After (fixes + rerank pool 15) |
| --- | --- | --- |
| Behaviour accuracy | 0.963 | **1.000** |
| Follow-up | 6/9 | **9/9** |
| Not in archive / rights probes | 6/6, 6/6 | 6/6, 6/6 |
| Recall@5 (n = 63) | 1.000 | 1.000 |
| MRR (n = 63) | 0.905 | **0.929** |
| Cited ids that were in the prompt | 1.000 | 1.000 |
| Answers citing a correct passage, excluding local-only questions | 45/51 (0.882) | 48/54 (0.889) |
| Answers citing a correct passage, all | 0.850 | 0.762 (see note) |
| **Local-only passages sent to the external model** | **36** | **0** |
| Forbidden (restricted or withdrawn) passages in the prompt or citations | 0 | 0 |
| Input tokens per LLM call, mean / p95 | 532 / 800 | **465 / 727** |
| Output tokens, mean / p95 (double) | 25.1 / 50 | 24.8 / 34 |
| Passages per prompt, mean | 2.85 | 2.19 |
| Estimated cost per LLM question | $0.000095 | $0.000085 |
| LLM calls per question | 0.741 | 0.778 (fu-03 now answered) |
| Cache hit rate, warm pass (all / answerable) | 0.667 / 1.0 | 0.667 / 1.0 |
| Provider cached-token share | 0 | 0 (prompt < 1,024 tokens) |
| End to end p50 / p95 (load caveat) | 4,037 / 8,352 ms | 4,116 / 7,939 ms |
| Rerank node p50 / p95 (load caveat) | 3,802 / 8,087 ms | 3,558 / 7,090 ms |
| `load_hits` p50 (unchanged code, load indicator) | 93 ms | 184 ms |
| Warm cache hit p50 | 25 ms | 48 ms |

Note on "citing a correct passage": for the three local-only questions, the correct passage belongs to an item
whose rights forbid external processing, so the hosted model can no longer see or cite it. That is the intended
effect of A-2. Excluding that category the score is unchanged or better, and all of the drop is in that category
(checked row by row).

With the test doubles (n = 81 each): behaviour accuracy stayed 0.852. The lexical double cannot abstain, so
not-in-archive and rights probes are 0/6 in both runs. Recall@5 stayed 1.0, MRR 0.917, cited ids in prompt 1.0.
Input tokens went from 657.6 to 589.9 mean, passages per prompt from 4.32 to 3.80, and local-only sends from 36
to 0. Excluding local-only questions, answers citing a correct passage stayed at 45/54.

### Rerank candidate pool: sweep and decision

Accuracy, with real models, n = 27 question runs per configuration (the models are deterministic):

| Pool / char cap | Behaviour | Recall@5 | MRR | Cited ids in prompt | Rights leaks |
| --- | --- | --- | --- | --- | --- |
| 30 / 900 (before) | 1.0 | 1.0 | 0.929 | 1.0 | 0 |
| 15 / 900 | 1.0 | 1.0 | 0.929 | 1.0 | 0 |
| 10 / 900 | 1.0 | 1.0 | 0.929 | 1.0 | 0 |
| 30 / 512 | 1.0 | 1.0 | 0.952 | 1.0 | 0 |

Latency, paired (`eval/results/bench-rerank.json`, 25 questions × 3 rounds = 75 samples per configuration):

| Pool / char cap | Rerank p50 | Rerank p95 | Median time vs 30/900, same round |
| --- | --- | --- | --- |
| 30 / 900 | 4,931 ms | 7,030 ms | 1.00 |
| **15 / 900 (adopted)** | 3,159 ms | 4,279 ms | **0.63** |
| 10 / 900 | 2,090 ms | 3,461 ms | 0.43 |
| 30 / 512 | 4,732 ms | 7,454 ms | 0.94 |
| 10 / 512 | 1,831 ms | 2,787 ms | 0.37 |

Decision: `rerank_candidate_k` default changed 30 → **15** (`config.py`), which cuts cross-encoder time by 37%
with no accuracy change on the benchmark.

- Why not 10: on this corpus every correct passage is already at fused rank ≤ 4 before reranking, so the
  benchmark cannot tell 10 from 30. The spec (§10) requires first-stage Recall@candidate-k on the reviewed
  question set, which does not exist yet. A pool of 15 keeps margin for the real corpus, where the reranker
  matters more.
- Lower it only after measuring Recall@10 and Recall@15 on that set. It is an environment setting
  (`ARCHIVE_RERANK_CANDIDATE_K`), so this needs no code change.
- The 512-character cap was **not** adopted. It saves only 6% here, because the fixture passages are short, and
  the MRR gain is one question. The benchmark cannot show whether cutting real 900-character Devanagari passages
  loses the answer.

### Live gpt-4o-mini (after only; 12 of the 20 allowed calls used)

`eval/results/bench-ask-after-live-llm.json` covers 10 questions (en-01/03/05/06/08/11/12, hi-01, en-14,
fu-01), one call each. The recheck file `-recheck.json` covers en-08 and en-14 after the follow-up fix.

| Metric | Value |
| --- | --- |
| Input tokens (provider usage), mean / p95 | 568 / 804 |
| Output tokens, mean / p95 | 35.6 / 59 (max 59, against `max_tokens` = 350) |
| Cached tokens | 0 (every prompt is under OpenAI's 1,024-token caching minimum) |
| Provider call latency p50 / p95 | 1,209 / 2,313 ms (measured around `complete()`, includes the new-client handshake) |
| End to end p50 / p95 | 5,221 / 6,618 ms |
| Answered: cited ids in prompt / cites a correct passage | 8/8 / 8/8 |
| Local-only passages sent | 0 |
| Cost per call (list price, estimate) | $0.000107 |

"Before" live numbers are **UNMEASURED**. Swapping back the original `ask/graph.py` and `service.py` would have
disturbed the engineer working on the live LLM path. The prompt text (`SYSTEM_PROMPT`, `build_prompt`) and
`max_tokens` are unchanged, so the tiktoken input counts in the tables above are the before/after input comparison.

Levers considered and **not** applied:

- Lowering `max_tokens` from 350: the longest real output was 59 tokens, but a cap only limits runaway outputs
  and does not change cost. Keep 350 until the §10 answer set shows the length distribution.
- Prompt caching: the stable prefix is only about 260 tokens, and padding it to 1,024 would raise cost.
- Fewer passages in the prompt: the strong filter already limits it (2.2 mean), and recall must not drop.

### Connection reuse to the answer model (measured, handed off)

Six unauthenticated `GET /v1/models` requests (401, no model call) with a new `httpx.Client` each took a median of
**1,740 ms**. Six on one reused client took **335 ms**. `ask/llm.py` builds a new client per request (A-14), so
each answer pays about 1.4 s of TLS and connection setup on this machine under load. Reusing a module-level
client is the largest remaining latency lever outside reranking.

---

## Tests

Full backend suite, run from the host against a separate test database `archive_test_review`, because a stuck
session in the shared `archive_test` held a lock that blocked TRUNCATE:

- `ARCHIVE_TEST_DATABASE_URL=.../archive_test_review python -m pytest -q -p no:cacheprovider` in `backend/`:
  **242 passed, 1 skipped** (Tesseract language data not installed on the host).
- New or changed tests from this review:
  - `test_unit_textlayer.py`: `TestPdfPerPageCost` (6 cases).
  - `test_db_pipeline.py`: the multi-page parse-once test and the failing-page test.
  - `test_db_ask_datasets.py`: the follow-up retry test; `TestAskRightsAndCitations` (5 cases);
    `TestAskNodeFailures` (2 cases).
  - `test_unit_gate_and_validation.py`: the short multi-word quote test; `TestAskGraphShape`.
- Red-green: the text-layer tests, the failing-page test, 10 of the 11 original new Ask tests and the
  withheld-passage test all fail on the previous code and pass now.

## Left for other engineers

| Owner | Item |
| --- | --- |
| LLM / Docker engineer | Reuse one `httpx.Client` in `ask/llm.py` (A-14; about 1.4 s per answer measured). Catching malformed responses inside `llm.py` is optional now, because the graph routes any exception to `error`. |
| Visitor-features engineer | `load_hits` extra queries in `search/hybrid.py` (A-9): batch the article, rights-attribution and photo lookups (`selectinload` or one joined query). |
| Web | Show the new `local_only` message (the outcome is `extractive`, and `message` is already in the payload). Never show a "verified" chip on `paraphrase_only` answers: `quote_verified` is a passage flag, not a sentence claim. |
| Evaluation owners | Reviewed §10.1 question set, then first-stage Recall@candidate-k to confirm or lower `ARCHIVE_RERANK_CANDIDATE_K`; set the latency targets in `eval/templates/latency_targets.json`. |
| Maintainers | Upper bounds for langgraph, langchain-text-splitters and langfuse in `pyproject.toml` (A-16); decide whether the cache key should use the detected language (A-13). |
| Deploy | For a local (on-premises) answer model set `ARCHIVE_LLM_EXTERNAL=false`. The default `true` is right for the hosted OpenAI setup. |

No migration was needed. Not edited: `web/**`, `backend/archive/api/**`, `tracing.py`, `llm.py`, `docker-compose.yml`,
`deploy/`, `data/incoming/`, `intake/`, `docs/DATA_SOURCES.md`. No containers were restarted and nothing was committed.
