# Requirements checklist: Dr. B. R. Ambedkar Digital Heritage Archive

This checklist comes from the spec's §2 traceability table, §8 (round-one scope), and the §7.3 training-data gate. It was checked against the code in `backend/`, `web/`, `fixtures/` and `eval/` on **2026-09-26**. A file existing does not make a row done. A row is **verified** only when a test that exercises it was run on that date and passed.

## Status legend

| Status | Meaning |
| --- | --- |
| verified | A test covering this row was run on 2026-09-26 and passed (commands below). Backend tests use test doubles: a hash embedder, a lexical reranker, a scripted fake LLM, and fake Tesseract and Sarvam outputs. So "verified" covers workflow and rule logic only, not live providers, model quality, or the tablet. |
| implemented-unverified | The code was read and appears to meet the row, but no passing test covers it, or it was only observed read-only in the running demo. |
| missing | No code or artifact exists for it. |
| blocked | Cannot be finished or checked until an outside dependency is resolved (rights decision, hardware, provider key) or another team fixes a defect. |
| unmeasured | The row is a measurement or a recorded run that has not happened. Its sample size is zero. |

Rows written `= TR-xx` in §8 repeat a §2 row. They take that row's status and are not counted twice.

## Summary counts

| Section | verified | implemented-unverified | missing | blocked | unmeasured | Rows |
| --- | --- | --- | --- | --- | --- | --- |
| §2 traceability | 9 | 20 | 7 | 4 | 4 | 44 |
| §8.2 core live path | 5 | 2 | 0 | 3 | 1 | 11 |
| §8.3 required modules | 0 | 4 | 0 | 0 | 5 | 9 |
| §8.1 collection and rights register | 0 | 1 | 0 | 7 | 0 | 8 |
| Direct-quotation rule (§1.1) | 1 | 0 | 0 | 1 | 0 | 2 |
| §4.10 and §7.3 training-data gate | 3 | 3 | 1 | 0 | 0 | 7 |
| **All rows** | **18** | **30** | **8** | **15** | **10** | **81** |
| P1 rows only | 18 | 28 | 3 | 14 | 10 | 73 |

On 2026-09-26 at 21:42 IST, `.env` was re-read after the user added Sarvam and LLM settings. Values were not copied. TR-19, TR-25 and LP-06 moved from blocked to implemented-unverified: they are configured locally, but this checklist has not verified a live call, and `docs/LIVE_TEST.md` does not exist. Langfuse keys are still absent, so LP-12 stays blocked. No quote-verification, fine-tuning, production or eval-field status changed.

On 2026-09-26 at 21:46 IST, the answer provider was changed to OpenAI-compatible `gpt-4o-mini` at `https://api.openai.com/v1` (key present, not recorded); only TR-25 was updated, and it stays implemented-unverified.

Of the 8 missing rows, 3 are PROD and 2 are P2; none of those are claimed for round one. The 3 missing P1 rows are: Android lock-task setup (TR-02), a nightly backup schedule (TR-29), and hard-negative mining with human confirmation (TG-04).

## Test runs recorded for this checklist

**1. Backend pytest.** Run on 2026-09-26 at about 21:29 IST, from the repository root:

```powershell
docker compose run --rm --no-deps -v "${PWD}/backend:/app:ro" -e PYTHONDONTWRITEBYTECODE=1 api python -m pytest -p no:cacheprovider -q -rA
```

- **Result: 1 failed, 86 passed in 15.40 s.**
- The run used the `ambedkar-archive/api:local` image with the current `backend/` mounted read-only, so no application code was changed.
- The tests used the separate `archive_test` database on the compose `db` service. `conftest.py` creates and truncates it; the demo `archive` database was not touched.
- `conftest.py` forces the hash embedder, the lexical reranker, and no Sarvam, LLM, or Langfuse.
- Failure: `tests/test_db_media.py::test_published_transcript_passages_carry_segment_quote_status`. It raises `PublicationError: verification failed: media delivery copy missing or checksum mismatch` from `archive/ingest/publish.py:235`. It was recorded, not patched; `backend/` belongs to another team.
- No test uses real Tesseract. `tests/test_db_pipeline.py` refers to `test_tesseract_real.py`, which does not exist.

**2. Evaluation-script tests.** Run with host Python 3.12.1 and pytest 9.0.2:

```powershell
python -m pytest eval/tests -q -p no:cacheprovider
```

- **Result: 32 passed.**
- These cover only the eval tooling in `eval/`, not the application.

**3. Web tests (`npm test`, which runs vitest on `web/src/exhibitVerify.test.ts` and `web/src/i18n.test.ts`).** Not run, because Node and npm are not on the host PATH. That makes them BLOCKED; no web row is marked verified.

**Read-only observations of the running demo stack** (containers `db`, `api`, `worker`). These are supporting context only, never grounds for "verified":

- **Providers:** the settings flags report Sarvam, LLM, and Langfuse all *not configured*. The embedder and reranker run through `fastembed`. This was observed before `.env` gained Sarvam and LLM settings (re-read at 21:42 IST), and the running containers have not been re-checked since.
- **Visitor API:**
  - 9 published fixture items. The `audio_video` collection count is 0.
  - 11 timeline events, 1 story, and 24 map nodes with 22 edges.
  - `ask_model_connected: false` and `machine_translation.available: false` (observed before the `.env` update).
- **Worker:** reports `unhealthy`. It inherits the API image's `curl localhost:8000` healthcheck (`backend/Dockerfile`), but the worker serves no HTTP. This is a health-reporting defect, not proof the worker is down.
- **`seed.log`** (fixture seeding):
  - The degraded pages stopped at `sarvam_pending`; Sarvam never ran.
  - `fx-talk-audio` stayed `in_review`.
  - `fx-restricted-memo` was correctly blocked, with "rights register does not allow display".

## §2 Problem-statement traceability

| ID | Requirement | Pri | Status | Evidence |
| --- | --- | --- | --- | --- |
| TR-01 | Tablet kiosk PWA: touch UI, kiosk flag, idle reset, and "Finish" clears session state | P1 | implemented-unverified | `web/src/components/Shell.tsx`, `web/src/state.tsx`, `web/vite.config.ts`. Web tests not run. |
| TR-02 | Android pinned/lock-task mode or kiosk browser on the Lenovo tablet | P1 | missing | No device setup or runbook in the repo. Needs the physical tablet. |
| TR-03 | Installed commercial kiosks (§9) | PROD | missing | Not claimed for the prototype. |
| TR-04 | Smart-display signage loop of the timeline and one story, served by the edge server | P1 | implemented-unverified | `web/src/pages/Signage.tsx` (`/display`); `GET /api/visitor/signage` in `backend/archive/api/visitor.py`. No test. |
| TR-05 | "Send to big screen" from a kiosk | P2 | missing | Not built (P2). |
| TR-06 | Edge server: a single-box stack (Postgres + pgvector, API, worker, proxy) | P1 | implemented-unverified | `docker-compose.yml`, `backend/Dockerfile`. The stack runs. The worker's healthcheck is wrong (see above). |
| TR-07 | Preservation and central tiers (§9) | PROD | missing | `docker-compose.yml` refers to `deploy/production/`, which does not exist. |
| TR-08 | Hybrid search (Postgres full-text + pgvector, rank fusion) over approved, published, rights-cleared passages, with filters | P1 | verified | `test_staged_version_is_invisible_until_switch`, `test_restricted_items_hidden_even_when_published`, `test_withdrawal_blocks_immediately_then_cleanup_verifies`. Uses the hash-embedder test double; semantic quality is UNMEASURED. |
| TR-09 | Cross-lingual search: multilingual embeddings vs query translation, evaluated on the §10 set and the choice recorded | P1 | unmeasured | UNMEASURED: `eval/RESULTS.md`, `retrieval.cross_lingual_choice`. |
| TR-10 | Curated knowledge map of approved nodes and edges, each approved by an archivist or curator | P1 | implemented-unverified | `POST /api/staff/map/nodes` and `/approve`, `GET /api/visitor/map`. The live data (24 nodes, 22 edges) was seeded by `fixture-seed`. No test. |
| TR-11 | Reader showing approved text beside the original scan (IIIF deep zoom); a tapped citation opens the cited page | P1 | implemented-unverified | `web/src/pages/Item.tsx`, `web/src/components/ScanViewer.tsx`, `backend/archive/api/iiif.py`. The deep-link format `/item/{id}?page=N` is asserted in `test_valid_answer_is_cited_and_logged` (passed); the reader UI has no test. |
| TR-12 | Highlight the exact region from word coordinates | P2 | implemented-unverified | `Item.tsx` passes `highlight={targetBoxes}` from passage `bboxes`. P2, untested. |
| TR-13 | Reviewed summaries for 2–3 items; viewing one costs zero LLM calls | P1 | implemented-unverified | 3 summaries seeded by `archive.cli seed-fixtures`. They were written by the build agent and approved by `fixture-seed`, so they are not human reviews. Served from `Derivative` rows in `visitor.py`. |
| TR-14 | OCR routing: text layer for born-digital; local OCR plus gate for print; Sarvam only for failed pages; manual transcription for handwriting; honours the external-processing permission | P1 | verified | `TestOcrRouting` (8 tests), e.g. `test_gate_fail_calls_sarvam_only_for_failed_page_and_requires_full_review`, `test_gate_pass_never_calls_sarvam`, `test_external_processing_not_permitted_skips_sarvam`, `test_handwriting_goes_to_human_transcription`, `test_born_digital_uses_text_layer`. Local OCR and Sarvam are test doubles. |
| TR-15 | Real Tesseract with `eng`, `hin` and `mar` models, storing word boxes and hOCR | P1 | implemented-unverified | `backend/archive/ingest/ocr_local.py`, `processing.py:_store_hocr`. `seed.log` shows the local route ran on fixtures. The referenced `test_tesseract_real.py` is missing. |
| TR-16 | Gate thresholds calibrated on hand-transcribed pages, with the threshold version recorded per page | P1 | unmeasured | `backend/archive/ingest/gate_thresholds.json` is still `gate-v0-uncalibrated`. Tool: `eval/calibrate_gate.py`. UNMEASURED. |
| TR-17 | Visitor UI in English, Hindi and Marathi | P1 | implemented-unverified | `web/src/i18n.ts`; `web/src/i18n.test.ts` was not run. |
| TR-18 | Reviewed translation approved by a named reviewer for that language | P1 | implemented-unverified | `backend/archive/ingest/review.py` lines 260–263 reject reviewers without that language. No test exercises the rejection. |
| TR-19 | On-demand machine translation: labelled, not stored, not citable, switchable per collection | P1 | implemented-unverified | Configured locally, live call not yet verified by this checklist. `ARCHIVE_SARVAM_API_KEY` is non-empty in `.env` (re-read at 21:42 IST; value not recorded). The demo stack observed earlier reported `machine_translation.available: false`, so the API has to be restarted to load the key. Code: `GET /api/visitor/translate/{id}` in `visitor.py`. |
| TR-20 | Cached narration, labelled "Synthetic narration", made only from approved source text or a reviewed translation | P1 | implemented-unverified | `backend/archive/services/narration.py`. `seed.log` shows espeak-ng narration for en/hi/mr. A Sarvam key is now set in `.env`, but no Sarvam TTS call has been made or verified by this checklist. No test. |
| TR-21 | One recording with a reviewed, timestamped transcript, captions, and tap-to-seek | P1 | blocked | `test_published_transcript_passages_carry_segment_quote_status` now **passes** (1 passed; `tests/test_db_media.py` 5 passed, host and container; see `docs/LIVE_TEST.md` "Audio publish checksum"). The earlier failure was a test fixture with no delivery media copy, not a publish defect. The quote status is a seeded fixture record, not human verification. Still open: the live `audio_video` count was 0 and `fx-talk-audio` was `in_review` (not re-checked). The UI seek code is in `Item.tsx`. |
| TR-22 | Curated timeline; each event links to at least one archive item | P1 | implemented-unverified | 11 events seeded by `fixture-seed`; `GET /api/visitor/timeline` drops events with no visible item. No test. |
| TR-23 | Memorial story whose every block cites an archive item, plus a curator editor | P1 | implemented-unverified | `POST /api/staff/stories`, `GET /api/visitor/stories/{slug}`. There is 1 seeded story. 1 of its 4 blocks points at the unpublished audio item and is hidden. |
| TR-24 | Bounded Ask graph: input checks; language ID without an LLM; short-history rewrite; hybrid search plus reranker; sufficiency check with exactly one retry; abstention; per-sentence citations; verbatim-quote check; quotes only from quote-verified passages; opinion-bait refusal; answer cache invalidated by withdrawal | P1 | verified | `TestAskGraph` (13), `TestAnswerValidation` (8), `TestAskPolicy` (5), all with the scripted FakeLLM. Language ID uses Lingua instead of IndicLID; the reason is recorded in `backend/archive/search/langid.py`. |
| TR-25 | Live answer generation with the chosen LLM provider, labelled "AI-generated answer from archive sources" | P1 | implemented-unverified | The answer model is OpenAI-compatible: `ARCHIVE_LLM_PROVIDER=openai_compatible`, `ARCHIVE_LLM_BASE_URL=https://api.openai.com/v1`, `ARCHIVE_LLM_MODEL=gpt-4o-mini`, and `ARCHIVE_LLM_API_KEY` is present (`.env` re-read at 21:46 IST; key not recorded). `ARCHIVE_SARVAM_API_KEY` is only the OCR, translation and TTS credential, not the answer model. `docs/LIVE_TEST.md` §3.2 records one successful provider smoke call: `OpenAICompatibleLLM` sent a "status ok" prompt and got back a JSON object. That shows the key and request format work, but it is not a live Ask answer. Not yet checked: an end-to-end Ask answer through the API, the "AI-generated answer from archive sources" label, citation validity and cited-answer support. The pytest suite runs with `ARCHIVE_LLM_PROVIDER=none`, and Sarvam chat as the answer model was not tested. |
| TR-26 | Sufficiency threshold calibrated on the §10 question set | P1 | unmeasured | `backend/archive/config.py` has `sufficiency_threshold_version = "uncalibrated-v0"`. UNMEASURED. |
| TR-27 | Integrity and audit: SHA-256 on arrival, preservation master stored unchanged and read-only, append-only hash-chained audit log | P1 | verified | `test_exact_duplicate_detected_and_checksum_mismatch_quarantined`, `test_preservation_master_is_unchanged_and_readonly`, `test_chain_verifies_and_rows_are_append_only`. |
| TR-28 | Backup (pg_dump + file roots + SHA-256 manifest) and restore into a clean database with checksum verification | P1 | implemented-unverified | `backend/archive/ops.py`, `archive.cli backup` and `restore`. Never run; no test. |
| TR-29 | Nightly backup of originals, database and derivatives to a second disk | P1 | missing | Nothing schedules `backup`; the worker loop only cleans up old versions (`backend/archive/worker.py`). |
| TR-30 | Scheduled fixity with alerts, 3-2-1 copies, restore tests on a schedule | PROD | missing | Only a manual `archive.cli fixity` exists. |
| TR-31 | Intake metadata: institution, title, type, languages, scripts, date and certainty, edition, volume, publisher, rights, access level, capture details | P1 | implemented-unverified | `backend/archive/ingest/intake.py`, `backend/archive/models.py`, and the intake form in `web/src/staff/Staff.tsx`. Tests send only partial metadata. |
| TR-32 | Staff authentication and roles on the archivist API | P1 | verified | `test_staff_endpoints_require_auth`, `test_rights_register_change_withdraws_published_items` (login plus role-gated write). |
| TR-33 | Archivist workspace UI: intake, review queue, batch review, rights register, audit, jobs | P1 | implemented-unverified | `web/src/staff/Staff.tsx`, routes in `web/src/App.tsx`. No UI test. |
| TR-34 | "My collection" plus a QR take-away: temporary read-only page, expiring link, no personal data | P1 | implemented-unverified | `POST/GET /api/visitor/collections` in `visitor.py`; `Basket` and `SharedList` in `web/src/pages/Explore.tsx`. No test. |
| TR-35 | Researcher web view | P2 | missing | Not built (P2). |
| TR-36 | Constitutional awareness: debates linked to the Constitution articles they discuss | P1 | blocked | No `ConstitutionArticle` or `DebateSession` nodes exist; the seeded map uses a fictional assembly. The real Constituent Assembly Debates source has `unknown` rights, so it cannot be ingested. |
| TR-37 | Accessibility: touch targets of at least 48 px, adjustable text size, high contrast, captions, transcripts, plain language | P1 | implemented-unverified | `web/src/styles.css`; the text-size and contrast toggles are in `Shell.tsx`; captions come from `/items/{id}/captions.vtt`. Some targets are under 48 px: `.btn.small` is 40 px (line 144), with 44 px and 28 px elements at lines 452 and 374. No audit. |
| TR-38 | Rights register entry before ingestion; permissions never inferred; unknown means not allowed; training permission kept separate from display | P1 | verified | `test_missing_rights_fields_rejected`, `test_real_source_template_is_refused_until_rights_are_decided`, `test_unknown_display_rights_block_publication`, `test_eligibility[unknown-...]`. |
| TR-39 | NDLI is discovery and linking only: never downloaded, ingested, indexed, or used for training | P1 | verified | `test_discovery_only_source_cannot_be_ingested`, `test_real_source_template_is_refused_until_rights_are_decided`. A downloadable NDLI file is not treated as licensed. |
| TR-40 | Real datasets ingested (Dr. Ambedkar Foundation *Writings and Speeches*, Constituent Assembly Debates) | P1 | blocked | `fixtures/manifests/example_real_sources.manifest.json`: every permission is `unknown` and `download_permitted: false`. All demo content is synthetic (`fixtures/README.md`). |
| TR-41 | Training-eligible corpus (§4.10): training permission `allowed`; approved text from a full review or a passed sample; source text or reviewed transcript only; revocation flags affected datasets | P1 | verified | `test_eligibility` (7 cases), `test_freeze_includes_only_training_eligible_passages`, `test_translations_are_not_training_eligible`, `test_training_revocation_flags_dataset`. |
| TR-42 | Dataset preparation: reviewed labels only, deterministic split by work and edition, versioned manifest with hashes | P1 | verified | `test_reviewed_labels_required_and_split_by_work`, `test_split_is_deterministic_and_work_level`. |
| TR-43 | Base-model baseline on held-out questions | P1 | unmeasured | Harness: `archive.cli eval-retrieval`, `eval/paired_bootstrap.py --baseline-only`. No question set and no result. UNMEASURED. |
| TR-44 | Trained reranker or retriever | P2 | blocked | The §7.3 minimum-data gate is not met (`training-gate-v1` requires 6 independent works and 300/60/60 pairs; the fixture corpus reports `met: false`). No fine-tuning was done and no improvement is claimed. |

## §8.2 Core live path (non-negotiable)

| ID | Step | Pri | Status | Evidence |
| --- | --- | --- | --- | --- |
| LP-01 | Live capture of a physical page at the digitisation station, sent into intake | P1 | blocked | Needs the camera rig. The code only accepts uploaded files (`POST /api/staff/intake`); `fixtures/capture-demo-page.png` is a stand-in. |
| LP-02 | Intake with metadata, checksum, and exact-duplicate check | P1 | verified | `test_exact_duplicate_detected_and_checksum_mismatch_quarantined`. |
| LP-03 | Local OCR per-page quality signals and a versioned gate decision | P1 | verified | `TestOcrGate` (7 tests), including `test_clean_page_passes_and_records_gate_version` and `test_devanagari_script_share_and_garbage`. |
| LP-04 | Gate calibrated | P1 | = TR-16 | unmeasured |
| LP-05 | Sarvam fallback for the failed page only, keeping both results | P1 | verified | `test_gate_fail_calls_sarvam_only_for_failed_page_and_requires_full_review` asserts that both the `tesseract` and `sarvam-doc-ai` results are stored. Also `TestSarvamDocAIWireProtocol` (a mocked HTTP transport). |
| LP-06 | Sarvam fallback run against the real Sarvam API | P1 | implemented-unverified | Configured locally, live call not yet verified by this checklist. `ARCHIVE_SARVAM_API_KEY` is non-empty in `.env` (re-read at 21:42 IST; value not recorded). `seed.log`, written before the key was added, shows the failed pages stuck at `sarvam_pending`; no page has been re-run through Sarvam since. |
| LP-07 | Archivist review UI: scan, local result, Sarvam result and diff side by side; approval record | P1 | implemented-unverified | The page review in `web/src/staff/Staff.tsx` renders `diff` and the signals. Review records are covered by `test_batch_pass_requires_every_sample_page_checked`; the UI has no test. |
| LP-08 | Staged publication and version switch; a failed verification never publishes | P1 | verified | `test_staged_version_is_invisible_until_switch`, `test_failed_verification_does_not_publish`, `test_unapproved_page_blocks_publication`. |
| LP-09 | Hybrid search (English) | P1 | = TR-08 | verified (API level) |
| LP-10 | Bounded question graph with sufficiency check, abstention, citation and quote checks | P1 | = TR-24 | verified (FakeLLM) |
| LP-11 | Reader opens the cited original page | P1 | = TR-11 | implemented-unverified |
| LP-12 | Langfuse trace for the question (tokens, cost, latency) | P1 | blocked | No Langfuse keys, so traces go to a local JSONL file (`backend/archive/tracing.py`, `backend_name()`). |
| LP-13 | Trace redaction: visitor questions PII-scrubbed or hashed; passage IDs only, no archive text | P1 | verified | `TestRedaction::test_pii_scrubbed`, `TestRedaction::test_redact_drops_archive_text_fields`. |
| LP-14 | The whole path rehearsed end to end on the demo network, including the tablet | P1 | unmeasured | No recorded run. |
| LP-15 | Demo question (§8.5 step 6) about hero-worship cites the 25 Nov 1949 speech and opens its page | P1 | blocked | The Constituent Assembly Debates volumes are not ingestable (rights `unknown`). |

## §8.3 Required P1 modules

| ID | Minimum working example | Pri | Status | Evidence |
| --- | --- | --- | --- | --- |
| MOD-01a | One item with a reviewed Hindi and a reviewed Marathi translation | P1 | implemented-unverified | Both translations are seeded. They were written by the build agent ("AI-written fixture translation") and approved by `fixture-seed`, not by a named bilingual reviewer. |
| MOD-01b | One Hindi query finds English source text | P1 | unmeasured | A read-only probe returned Hindi-query hits that included English passages, but nothing was checked against expected passages. UNMEASURED: `multilingual.hindi_query_finds_english_source`. |
| MOD-01c | One labelled on-demand machine translation | P1 | = TR-19 | implemented-unverified (configured locally, live call not yet verified) |
| MOD-01d | Cached narration for one passage | P1 | = TR-20 | implemented-unverified |
| MOD-02 | Two widely circulated misattributed quotes return "not in the archive" | P1 | unmeasured | The validator rejects an invented quote (`test_misattributed_quote_not_in_passages_fails`), but no real misattributed quotes have been run against a real corpus. Template: `eval/questions/answers.template.json`. |
| MOD-03 | One recording with a reviewed timestamped transcript; tapping a line seeks the player | P1 | = TR-21 | blocked |
| MOD-04 | One photograph with a reviewed caption and provenance | P1 | implemented-unverified | Item 8 (a synthetic illustration) is live; its caption was approved by `fixture-seed`. |
| MOD-05 | 8–12 timeline events, one story, a map of about 20–30 nodes, each linked to items | P1 | implemented-unverified | Seeded 11 events, 1 story, and 24 nodes. All are synthetic and none cite real items 1–7 (see RR-08). |
| MOD-06 | Reviewed summaries for 2–3 items | P1 | = TR-13 | implemented-unverified |
| MOD-07 | Add three items, scan the QR code on a phone, open the read-only page | P1 | unmeasured | Code = TR-34. No recorded phone run. |
| MOD-08 | Signage loop driven by the edge server | P1 | = TR-04 | implemented-unverified |
| MOD-09 | Network off: cached exhibits open and Ask shows "needs connection" | P1 | implemented-unverified | `web/src/sw.ts`, `web/src/exhibitVerify.ts`, and the `askOffline` string. Manifest signing and exclusion of online-only items are verified by `test_sign_and_verify_roundtrip_and_tamper_detection` and `test_online_only_item_visible_but_never_in_kiosk_cache`. The service worker and the web tests were not run. |
| MOD-10 | One full restore to a clean machine with a checksum match, shown from its recorded log | P1 | unmeasured | There is no `RESTORE_LOG.json`. Tool: `eval/verify_restore_log.py`. |
| MOD-11 | §10 results table with sample sizes | P1 | unmeasured | `eval/RESULTS.md` exists, but every field is UNMEASURED with a blank sample size. |
| MOD-12 | Training-eligible corpus manifest and base-model baseline | P1 | = TR-43 | unmeasured (manifest logic = TR-42, verified) |

## §8.1 Collection and rights register

| ID | Item | Pri | Status | Evidence |
| --- | --- | --- | --- | --- |
| RR-01 | Item 1: a chapter of *Writings and Speeches*, Vol. 1 (born-digital path) | P1 | blocked | `mea-writings-speeches-vol1`: display, training and external processing are all `unknown`. |
| RR-02 | Item 2: 10–20 scanned pages of the same volume (Digital Library of India scan) | P1 | blocked | `dli-scan-example` is `unknown`, with a placeholder URL. |
| RR-03 | Item 3: Constituent Assembly Debates speeches of 4 Nov 1948 and 25 Nov 1949 | P1 | blocked | `lok-sabha-cad` is `unknown`. |
| RR-04 | Item 4: Hindi and Marathi printed pages with a documented source | P1 | blocked | Only the synthetic `fx-pamphlet-hi` and `fx-petition-mr` exist. |
| RR-05 | Item 5: one photograph with documented public-domain status or written permission | P1 | blocked | Only the synthetic illustration `fx-photo-reading-room` exists. |
| RR-06 | Item 6: one recording with written permission, or a clearly labelled team-made recording | P1 | blocked | The labelled synthetic `fx-talk-audio` exists but cannot publish (TR-21). |
| RR-07 | Item 7: a manuscript page, or the path demonstrated on a labelled test page | P1 | implemented-unverified | The labelled synthetic `fx-manuscript-note` was published through the manual transcription path, but the transcription was seeded. A real page needs the holder's permission. |
| RR-08 | Item 8: timeline, story and map entries that cite items 1–7 | P1 | blocked | They cite synthetic fixtures, because items 1–7 are blocked. |
| RR-09 | NDLI: discovery and linking only | P1 | = TR-39 | verified |

## Direct-quotation rule (§1.1, §5.7 step 7)

| ID | Requirement | Pri | Status | Evidence |
| --- | --- | --- | --- | --- |
| QV-01 | Quoting is allowed only from quote-verified pages or segments, and quote verification needs explicit confirmation by a person | P1 | verified | `test_quote_verification_requires_explicit_confirmation`, `test_verbatim_quote_rejected_when_passage_not_quote_verified`, `test_verbatim_quote_allowed_after_quote_verification`, `test_segment_quote_verification_needs_confirmation_and_approval`. |
| QV-02 | A named person has compared, word for word, the pages used in stories, the timeline and the demo questions against the scan or recording | P1 | blocked | The only quote verifications are 3 seeded fixture pages by `fixture-seed` (`seed.log`, `quote_checks_seeded`). A seeded row is not evidence that a person checked a real source. Log: `eval/templates/quote_verification_log.csv`. |

## §4.10 and §7.3 training-data gate

| ID | Requirement | Pri | Status | Evidence |
| --- | --- | --- | --- | --- |
| TG-01 | Gate thresholds set before labelling starts, and recorded | P1 | implemented-unverified | `backend/archive/datasets/training_gate.json` (`training-gate-v1`, set 2026-09-26 "to be confirmed by the institution"). |
| TG-02 | The gate is evaluated when a dataset version is frozen; a small corpus reports not met | P1 | verified | `test_freeze_includes_only_training_eligible_passages` asserts `gate_report["met"] is False`. |
| TG-03 | Held-out §10 test questions never appear in training or tuning | P1 | implemented-unverified | `eval/check_training_leakage.py` (the `test_held_out_question_in_training_labels_is_an_error` test passes), but it is not wired into `freeze-dataset` and there is no real data. |
| TG-04 | Hard negatives mined from the base model, each confirmed non-relevant by a person (another edition is not a negative) | P1 | missing | `TrainingExample.hard_negative_passage_ids` exists, but `load_labels` ignores hard negatives and there is no mining code. |
| TG-05 | A Hindi or Marathi result is claimed only if that language has its own test examples | P1 | verified | `eval/tests::test_language_without_its_own_test_examples_is_not_claimed`; the backend side is `gate_report.claimable_languages` in `backend/archive/datasets/corpus.py`. |
| TG-06 | Trained-vs-base results are shown only if the gate is met, and differences carry confidence intervals | P1 | verified | `eval/tests::test_comparison_refused_when_gate_not_met`, `test_trained_model_result_rejected_when_gate_not_met`, `test_difference_without_confidence_interval_rejected`. |
| TG-07 | ModelVersion registration: base model, dataset version, config, commit, results, size | P2 | implemented-unverified | The `ModelVersion` schema is in `backend/archive/models.py`; there is no registration code (P2). |

## Evaluation fields (§10)

Every field in `eval/templates/results_template.json` (105 fields in 16 areas) and in `eval/RESULTS.md` is **UNMEASURED**, with a blank sample size:

- OCR and the fallback gate
- review load
- retrieval
- cited-answer support
- multilingual quality
- latency
- tokens and cost
- tablet battery and network
- storage
- offline access
- server capacity
- checksum-verified restore
- training baseline
- the two P2 trained-model areas

`python eval/check_results.py` rejects any filled results file that quotes a number without a sample size, method and evidence.

## Defects and gaps found (for the owning teams; not patched here)

1. **Backend:** a recording cannot publish. The media delivery copy is missing at verification: one failing test, and the live `fx-talk-audio` item is stuck `in_review`.
2. **Backend tests:** `test_tesseract_real.py` is referenced but does not exist, so real OCR is untested.
3. **Deploy:** the worker inherits the API's HTTP healthcheck, so it reports `unhealthy` permanently. `docker-compose.yml` also points to a `deploy/production/` folder that does not exist.
4. **Backend:** nothing schedules backup or fixity.
5. **Backend CLI:** `eval-answers` sends no conversation history, so follow-up questions cannot be evaluated. `load-labels` drops hard negatives.
6. **Web:** some touch targets are below 48 px.
7. **Curation data:** there are no Constitution-article nodes, and one story block points at an unpublished item.
8. **Docs:** `docs/BUILD_LOG.md` does not exist yet, so this checklist does not cite it.
