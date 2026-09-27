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
| §2 traceability | 21 | 10 | 6 | 3 | 4 | 44 |
| §8.2 core live path | 5 | 2 | 0 | 3 | 1 | 11 |
| §8.3 required modules | 1 | 3 | 0 | 0 | 5 | 9 |
| §8.1 collection and rights register | 1 | 1 | 0 | 6 | 0 | 8 |
| Direct-quotation rule (§1.1) | 1 | 0 | 0 | 1 | 0 | 2 |
| §4.10 and §7.3 training-data gate | 4 | 3 | 0 | 0 | 0 | 7 |
| **All rows** | **33** | **19** | **6** | **13** | **10** | **81** |
| P1 rows only | 33 | 17 | 1 | 12 | 10 | 73 |

On 2026-09-27 the counts were recomputed from the rows below. They include the TR-25 change and the rows re-evidenced by the host test run described in `docs/PROBLEM_STATEMENT_CONFORMANCE.md` (backend 197 passed and 1 failed in another engineer's order-dependent backup-verify test; web `tsc` clean and vitest 34 passed). Rows marked verified on 2026-09-27 cite that run.

On 2026-09-26 at 21:42 IST, `.env` was re-read after the user added Sarvam and LLM settings. Values were not copied. TR-19, TR-25 and LP-06 moved from blocked to implemented-unverified: they are configured locally, but this checklist has not verified a live call, and `docs/LIVE_TEST.md` does not exist. Langfuse keys are still absent, so LP-12 stays blocked. No quote-verification, fine-tuning, production or eval-field status changed.

On 2026-09-26 at 21:46 IST, the answer provider was changed to OpenAI-compatible `gpt-4o-mini` at `https://api.openai.com/v1` (key present, not recorded); only TR-25 was updated, and it stays implemented-unverified.

Of the 6 missing rows, 3 are PROD and 2 are P2; none of those are claimed for round one. The 1 missing P1 row is Android lock-task setup (TR-02).

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
| TR-04 | Smart-display signage loop of the timeline and one story, served by the edge server | P1 | verified | API level, 2026-09-27 host run: `test_db_curation.py::TestTimelineAndStory::test_signage_loop_serves_the_timeline_and_first_story` (`GET /api/visitor/signage`). The `/display` page (`web/src/pages/Signage.tsx`) has no UI test. |
| TR-05 | "Send to big screen" from a kiosk | P2 | missing | Not built (P2). |
| TR-06 | Edge server: a single-box stack (Postgres + pgvector, API, worker, proxy) | P1 | implemented-unverified | `docker-compose.yml`, `backend/Dockerfile`. The stack runs. The worker's healthcheck is wrong (see above). |
| TR-07 | Preservation and central tiers (§9) | PROD | missing | `docker-compose.yml` refers to `deploy/production/`, which does not exist. |
| TR-08 | Hybrid search (Postgres full-text + pgvector, rank fusion) over approved, published, rights-cleared passages, with filters | P1 | verified | `test_staged_version_is_invisible_until_switch`, `test_restricted_items_hidden_even_when_published`, `test_withdrawal_blocks_immediately_then_cleanup_verifies`. Uses the hash-embedder test double; semantic quality is UNMEASURED. |
| TR-09 | Cross-lingual search: multilingual embeddings vs query translation, evaluated on the §10 set and the choice recorded | P1 | unmeasured | UNMEASURED: `eval/RESULTS.md`, `retrieval.cross_lingual_choice`. |
| TR-10 | Curated knowledge map of approved nodes and edges, each approved by an archivist or curator | P1 | verified | 2026-09-27 host run: `test_db_curation.py::TestKnowledgeMap::test_only_approved_nodes_and_edges_between_visible_items_are_shown`, `test_map_curation_needs_curator_role_and_valid_nodes`. Edges now have curator endpoints (`POST /api/staff/map/edges`, `/map/edges/{id}/approve`). The live data (24 nodes, 22 edges) was seeded by `fixture-seed`, not curated by a person. |
| TR-11 | Reader showing approved text beside the original scan (IIIF deep zoom); a tapped citation opens the cited page | P1 | implemented-unverified | `web/src/pages/Item.tsx`, `web/src/components/ScanViewer.tsx`, `backend/archive/api/iiif.py`. The deep-link format `/item/{id}?page=N` is asserted in `test_valid_answer_is_cited_and_logged` (passed); the reader UI has no test. |
| TR-12 | Highlight the exact region from word coordinates | P2 | implemented-unverified | `Item.tsx` passes `highlight={targetBoxes}` from passage `bboxes`. P2, untested. |
| TR-13 | Reviewed summaries for 2–3 items; viewing one costs zero LLM calls | P1 | verified | Workflow, 2026-09-27 host run: `test_db_visitor_features.py::TestReviewedSummaries` (`test_visitor_sees_only_reviewed_summary_and_viewing_makes_no_llm_call`, `test_staff_draft_from_approved_text_is_hidden_until_approved`, `test_summary_draft_can_use_approved_recording_transcript`). The 3 live demo summaries were written by the build agent and approved by `fixture-seed`, so they are not human reviews. |
| TR-14 | OCR routing: text layer for born-digital; local OCR plus gate for print; Sarvam only for failed pages; manual transcription for handwriting; honours the external-processing permission | P1 | verified | `TestOcrRouting` (8 tests), e.g. `test_gate_fail_calls_sarvam_only_for_failed_page_and_requires_full_review`, `test_gate_pass_never_calls_sarvam`, `test_external_processing_not_permitted_skips_sarvam`, `test_handwriting_goes_to_human_transcription`, `test_born_digital_uses_text_layer`. Local OCR and Sarvam are test doubles. |
| TR-15 | Real Tesseract with `eng`, `hin` and `mar` models, storing word boxes and hOCR | P1 | implemented-unverified | `backend/archive/ingest/ocr_local.py`, `processing.py:_store_hocr`. `seed.log` shows the local route ran on fixtures. The referenced `test_tesseract_real.py` is missing. |
| TR-16 | Gate thresholds calibrated on hand-transcribed pages, with the threshold version recorded per page | P1 | unmeasured | `backend/archive/ingest/gate_thresholds.json` is still `gate-v0-uncalibrated`. Tool: `eval/calibrate_gate.py`. UNMEASURED. |
| TR-17 | Visitor UI in English, Hindi and Marathi | P1 | implemented-unverified | `web/src/i18n.ts`; `web/src/i18n.test.ts` was not run. |
| TR-18 | Reviewed translation approved by a named reviewer for that language | P1 | verified | 2026-09-27 host run: `test_db_translation.py::TestReviewedTranslation::test_only_a_named_reviewer_for_the_language_can_approve_and_it_reaches_reader_and_search`. The test found that an unknown review action was treated as a rejection; `review.py` now rejects it (`REVIEW_ACTIONS`). |
| TR-19 | On-demand machine translation: labelled, not stored, not citable, switchable per collection | P1 | verified | Rule logic, 2026-09-27 host run with a stubbed provider: `test_db_translation.py::TestMachineTranslation::test_labelled_not_stored_not_citable_and_switchable_per_collection`. A live Sarvam call is not verified by this checklist. `ARCHIVE_SARVAM_API_KEY` is non-empty in `.env` (re-read at 21:42 IST; value not recorded). The demo stack observed earlier reported `machine_translation.available: false`, so the API has to be restarted to load the key. Code: `GET /api/visitor/translate/{id}` in `visitor.py`. |
| TR-20 | Cached narration, labelled "Synthetic narration", made only from approved source text or a reviewed translation | P1 | verified | 2026-09-27 host run: `tests/test_unit_narration.py` (19) and `tests/test_db_narration.py` (11) cover the rules: approved or reviewed source only; one TTS call, then served from cache; cache key = text hash + text version + voice; label and engine+version generator; Sarvam failure falls back to espeak-ng, and no engine gives 503 while the reader still works; local-only text never goes to Sarvam; withdrawn items are not served; never in the training corpus; no LLM calls on playback; generic stock voice. Six violations were found and fixed in `services/narration.py`, `services/sarvam_text.py`, `staff.py` `make_narration` and `visitor.py` `narration_for`. Live: one Sarvam `bulbul:v3` call each for en, hi and mr through `narration.narrate` on the host, giving valid AAC files of 4.61, 7.25 and 6.49 s; each second request was a cache hit. Details are in `docs/NARRATION.md`. The fixture translations are `fixture-seed` approvals, and the player UI has no test. |
| TR-21 | One recording with a reviewed, timestamped transcript, captions, and tap-to-seek | P1 | verified | API and pipeline level, 2026-09-27 host run: `test_db_visitor_features.py::TestVideo` (`test_video_item_plays_with_transcript_captions_and_timestamped_search`, `test_ffmpeg_makes_h264_delivery_copy_for_video_master` with real ffmpeg, `test_staff_can_correct_a_transcript_segment`). A labelled synthetic video `fx-talk-video` (`fixtures/files/fx-talk-video-synthetic.mp4`) is in the fixture manifest; it is live only after a rebuild and `seed-fixtures`. The tap-to-seek UI has no test. Earlier: `test_published_transcript_passages_carry_segment_quote_status` now **passes** (1 passed; `tests/test_db_media.py` 5 passed, host and container; see `docs/LIVE_TEST.md` "Audio publish checksum"). The earlier failure was a test fixture with no delivery media copy, not a publish defect. The quote status is a seeded fixture record, not human verification. Still open: the live `audio_video` count was 0 and `fx-talk-audio` was `in_review` (not re-checked). The UI seek code is in `Item.tsx`. |
| TR-22 | Curated timeline; each event links to at least one archive item | P1 | verified | 2026-09-27 host run: `test_db_curation.py::TestTimelineAndStory::test_timeline_shows_approved_events_with_visible_items_only` (an event with no item is refused with 422; events with no visible item are dropped). The 11 live events were seeded by `fixture-seed`. |
| TR-23 | Memorial story whose every block cites an archive item, plus a curator editor | P1 | verified | API level, 2026-09-27 host run: `test_db_curation.py::TestTimelineAndStory::test_story_blocks_must_cite_items_and_unpublished_blocks_are_hidden` (`POST /api/staff/stories` refuses an uncited block; `GET /api/visitor/stories/{slug}` hides unpublished blocks). The editor UI has no test. The 1 live story was seeded. |
| TR-24 | Bounded Ask graph: input checks; language ID without an LLM; short-history rewrite; hybrid search plus reranker; sufficiency check with exactly one retry; abstention; per-sentence citations; verbatim-quote check; quotes only from quote-verified passages; opinion-bait refusal; answer cache invalidated by withdrawal | P1 | verified | `TestAskGraph` (13), `TestAnswerValidation` (8), `TestAskPolicy` (5), all with the scripted FakeLLM. Language ID uses Lingua instead of IndicLID; the reason is recorded in `backend/archive/search/langid.py`. |
| TR-25 | Live answer generation with the chosen LLM provider, labelled "AI-generated answer from archive sources" | P1 | verified | 2026-09-27 about 11:25 IST, after the Docker recovery and api rebuild (`docs/LIVE_TEST.md`, "Docker recovery and rebuild — 2026-09-27"). Three live visitor Asks went through `POST https://localhost:8443/api/visitor/ask` to the running api container. The provider is OpenAI-compatible `gpt-4o-mini` at `https://api.openai.com/v1`; the key was present and not recorded, and the model reported was `gpt-4o-mini-2024-07-18`. Answer ids 8 and 9 targeted the published synthetic fixture `fx-lecture-education`. Both were `answered` with the label "AI-generated answer from archive sources". Each had one sentence citing passage 7 (item 2), which the database confirmed is in the item's live published version, with `quote_verified = true`. Validation reported `ok`, no errors and no quoted spans. The third Ask, from `smoke_test.py --ask`, was `answered` citing passage 20 of the smoke item, and the check "every answer sentence cites a delivered passage" passed. Limits: passage 7's `quote_verified` is a `fixture-seed` record on synthetic content, not human verification. No answer contained a quoted span, so the quote-rejection path is covered only by `TestAskGraph` with the FakeLLM. Answer 9 reused passage wording without quotation marks; the validator does not treat that as a quote, and the text came from a `quote_verified` passage. `cost_usd` is 0 because no per-token prices are configured. The earlier `outcome: error` (answers 6 and 7) was DNS failure inside the degraded Docker VM (`[Errno -3] Temporary failure in name resolution` in the container trace), not app code or the key. |
| TR-26 | Sufficiency threshold calibrated on the §10 question set | P1 | unmeasured | `backend/archive/config.py` has `sufficiency_threshold_version = "uncalibrated-v0"`. UNMEASURED. |
| TR-27 | Integrity and audit: SHA-256 on arrival, preservation master stored unchanged and read-only, append-only hash-chained audit log | P1 | verified | `test_exact_duplicate_detected_and_checksum_mismatch_quarantined`, `test_preservation_master_is_unchanged_and_readonly`, `test_chain_verifies_and_rows_are_append_only`. |
| TR-28 | Backup (pg_dump + file roots + SHA-256 manifest) and restore into a clean database with checksum verification | P1 | verified | 2026-09-27. Tests: `tests/test_db_backup_verify.py`, 6 tests, which pass in the full host suite. They cover the snapshot-consistent dump, a refused older `pg_dump`, `ops.backup` output passing restore verification, and a tampered file or wrong counts failing it. Recorded run: the worker job's `ops.backup` (pg_dump 17.11) was run once read-only against the live demo. The resulting backup was restored into a throwaway PG17 container and a temp folder: dump checksum ok, 604/604 files, 602/602 `file_version` rows, 12 key-table counts equal, audit chain ok (556 events), 41.5 s. Evidence: `eval/results/backup-restore-2026-09-27/worker-job/RESTORE_LOG.json`; details in `docs/DATASETS_AND_BACKUP.md`. The in-container `archive.cli restore` path was not run: the drill uses `deploy/local-demo/Invoke-DemoRestoreDrill.ps1`. |
| TR-29 | Nightly backup of originals, database and derivatives to a second disk | P1 | verified | Schedule only, 2026-09-27 host run: `test_db_backup_schedule.py` (7 tests: `test_backup_is_due_once_per_nightly_slot` x5, `test_schedule_enqueues_one_backup_per_night_and_records_the_run`, `test_schedule_can_be_switched_off`). The worker maintenance loop enqueues one `backup` job per night at `nightly_backup_hour_utc` (default 20, which is 01:30 IST), audits `backup.run` and records `nightly_backup` in system state (`backend/archive/worker.py`, `config.py`). The test stubs `ops.backup`; the backup itself is TR-28. Whether `backup_root` is a second disk is a deployment choice, not checked here. **2026-09-27, not yet effective in the running stack.** The api/worker image's `pg_dump` is 15.19 and the server is 17.8, so every nightly run would fail. Two fixes: `ops.backup` now refuses a client/server version mismatch before writing anything, and `backend/Dockerfile` installs `postgresql-client-17`, which takes effect on the next image rebuild. The running worker also predates the schedule, which additionally needs migration 0002. The job code was run once with a PG17 client and its output passed a restore drill (TR-28). On the demo, `backups` sits on the same C: disk as the live data, so it is not a second disk. No Windows Task Scheduler job is used. **Retention (2026-09-27, code and tests only, not in the running stack):** after each backup job the worker keeps the newest `ARCHIVE_BACKUP_KEEP` (default 14) complete backups in `backup_root` and audits `backup.prune`; a folder without `BACKUP_LOG.json` (still being written) and the backup just written are never deleted (`ops.prune_backups`; `tests/test_unit_backup_retention.py`, `test_backup_job_prunes_to_the_retention_setting_and_audits_it`). |
| TR-30 | Scheduled fixity with alerts, 3-2-1 copies, restore tests on a schedule | PROD | missing | Only a manual `archive.cli fixity` exists. A manual restore drill now exists for the local demo (`deploy/local-demo/Invoke-DemoRestoreDrill.ps1`, 2026-09-27), but it is not scheduled. |
| TR-31 | Intake metadata: institution, title, type, languages, scripts, date and certainty, edition, volume, publisher, rights, access level, capture details | P1 | implemented-unverified | `backend/archive/ingest/intake.py`, `backend/archive/models.py`, and the intake form in `web/src/staff/Staff.tsx`. Intake tests send only partial metadata. Post-intake editing of title, type, languages, date and certainty, subjects, people and places is verified (2026-09-27, `test_db_visitor_features.py::TestMetadataTagging`, 7 tests: versioned, audited, validated, filterable by visitors), but edition, volume, publisher and capture details are not covered by a test. |
| TR-32 | Staff authentication and roles on the archivist API | P1 | verified | `test_staff_endpoints_require_auth`, `test_rights_register_change_withdraws_published_items` (login plus role-gated write). |
| TR-33 | Archivist workspace UI: intake, review queue, batch review, rights register, audit, jobs | P1 | implemented-unverified | `web/src/staff/Staff.tsx`, routes in `web/src/App.tsx`. No UI test. |
| TR-34 | "My collection" plus a QR take-away: temporary read-only page, expiring link, no personal data | P1 | verified | API level, 2026-09-27 host run: `test_db_visitor_features.py::TestCompileAndQr` (4 tests: item, passage and recording-segment entries with a QR and a read-only page; withdrawn items disappear; expired links are gone; personal fields are refused), plus `web/src/basket.test.ts`. The `Basket` and `SharedList` UI has no interaction test. |
| TR-35 | Researcher web view | P2 | missing | Not built (P2). |
| TR-36 | Constitutional awareness: debates linked to the Constitution articles they discuss | P1 | blocked | The linking software is verified (2026-09-27, `test_db_visitor_features.py::TestConstitutionLinks`, 5 tests): curators link a published passage to an article, links survive republication, removal is audited, and links show in the reader, search and `/api/visitor/constitution/{number}`. The only link is a labelled synthetic demo (fictional debate to Article 41). Real debates stay blocked: the Constituent Assembly Debates source has `unknown` rights, so it cannot be ingested. |
| TR-37 | Accessibility: touch targets of at least 48 px, adjustable text size, high contrast, captions, transcripts, plain language | P1 | implemented-unverified | `web/src/styles.css`; the text-size and contrast toggles are in `Shell.tsx`; captions come from `/items/{id}/captions.vtt`. `.btn.small`, the transcript seek buttons (`.segment button.time`) and the linked chips (`.chip-link`) are 48 px; `.chip` (28 px) is a non-interactive label. The answer citation links (`.answer sup a`, `min-width: 26px`) are still under 48 px. No full audit. |
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
| LP-03 | Local OCR per-page quality signals and a versioned gate decision | P1 | verified | `TestOcrGate` (7 tests) plus `TestHindiOcrPatterns` (18 tests). Existing rows: Devanagari-share and garbage-rate. New rows (2026-09-27): danda-inside-numerals and mixed-script junk fail the gate (`max_danda_in_numerals`, `max_mixed_script_junk`); कौ / सांविधान / dropped anusvara are weak signals only (recorded, raise review priority, do not fail alone). Thresholds stay `gate-v0-uncalibrated`. |
| LP-04 | Gate calibrated | P1 | = TR-16 | unmeasured |
| LP-05 | Sarvam fallback for the failed page only, keeping both results | P1 | verified | `test_gate_fail_calls_sarvam_only_for_failed_page_and_requires_full_review` asserts that both the `tesseract` and `sarvam-doc-ai` results are stored. Also `TestSarvamDocAIWireProtocol` (a mocked HTTP transport). |
| LP-06 | Sarvam fallback run against the real Sarvam API | P1 | implemented-unverified | Configured locally, live call not yet verified by this checklist. `ARCHIVE_SARVAM_API_KEY` is non-empty in `.env` (re-read at 21:42 IST; value not recorded). `seed.log`, written before the key was added, shows the failed pages stuck at `sarvam_pending`; no page has been re-run through Sarvam since. |
| LP-07 | Archivist review UI: scan, local result, Sarvam result and diff side by side; approval record | P1 | implemented-unverified | The page review in `web/src/staff/Staff.tsx` renders `diff` and the signals. Review records are covered by `test_batch_pass_requires_every_sample_page_checked`; the UI has no test. |
| LP-08 | Staged publication and version switch; a failed verification never publishes | P1 | verified | `test_staged_version_is_invisible_until_switch`, `test_failed_verification_does_not_publish`, `test_unapproved_page_blocks_publication`. |
| LP-09 | Hybrid search (English) | P1 | = TR-08 | verified (API level) |
| LP-10 | Bounded question graph with sufficiency check, abstention, citation and quote checks | P1 | = TR-24 | verified (FakeLLM) |
| LP-11 | Reader opens the cited original page | P1 | = TR-11 | implemented-unverified |
| LP-12 | Langfuse trace for the question (tokens, cost, latency) | P1 | verified | 2026-09-27 12:32 IST (`docs/LANGFUSE.md`, "Verification evidence"). Self-hosted Langfuse 4.46.0 runs as its own compose project (`docker-compose.langfuse.yml`: own Postgres, ClickHouse, Redis and MinIO; UI on `127.0.0.1:3100`). One real Ask went through `archive.ask.service.ask` and `backend/archive/tracing.py` (working-tree copy mounted read-only) in a one-off `docker compose run --rm --no-deps api` container; that run used the lexical reranker to stay within free memory. Trace `5d050577bbeec6e77ecca05a27262805` (answer 24, `answered`, citing passage 7 of the synthetic fixture `fx-lecture-education`) was read back from Langfuse's Observations API v2. The root `ask` span had latency 11.92 s and version `ask-v1`. The `generate` generation had model `gpt-4o-mini-2024-07-18`, usage 1101 in / 44 out, cost $0.00019155 (Langfuse price table), and provider latency 2346 ms in its metadata. The returned JSON contained no visitor email, IP, raw session id, passage excerpt, generated answer text, LLM key, Langfuse secret key or JWT secret; the question read `Email [email], IP [ip]. …`. Unit tests: `backend/tests/test_unit_tracing.py` (18 passed). The running api and worker still write the local JSONL sink until they are recreated with the new `.env` (`docs/LANGFUSE.md`, "Apply to the running stack"). **2026-09-27 follow-up, code and tests only:** the `generate` generation now carries the model call's measured start and end times (it was emitted with ~0 s duration after the graph finished); checked with an in-memory exporter in `test_generation_span_carries_the_model_call_start_and_end`, not yet against the live Langfuse. |
| LP-13 | Trace redaction: visitor questions PII-scrubbed or hashed; passage IDs only, no archive text | P1 | verified | `TestRedaction::test_pii_scrubbed`, `TestRedaction::test_redact_drops_archive_text_fields`. |
| LP-14 | The whole path rehearsed end to end on the demo network, including the tablet | P1 | unmeasured | No recorded run. |
| LP-15 | Demo question (§8.5 step 6) about hero-worship cites the 25 Nov 1949 speech and opens its page | P1 | blocked | The Constituent Assembly Debates volumes are not ingestable (rights `unknown`). |

## §8.3 Required P1 modules

| ID | Minimum working example | Pri | Status | Evidence |
| --- | --- | --- | --- | --- |
| MOD-01a | One item with a reviewed Hindi and a reviewed Marathi translation | P1 | implemented-unverified | Both translations are seeded. They were written by the build agent ("AI-written fixture translation") and approved by `fixture-seed`, not by a named bilingual reviewer. |
| MOD-01b | One Hindi query finds English source text | P1 | unmeasured | A read-only probe returned Hindi-query hits that included English passages, but nothing was checked against expected passages. UNMEASURED: `multilingual.hindi_query_finds_english_source`. |
| MOD-01c | One labelled on-demand machine translation | P1 | = TR-19 | implemented-unverified (configured locally, live call not yet verified) |
| MOD-01d | Cached narration for one passage | P1 | = TR-20 | verified (tests and a live Sarvam run; see `docs/NARRATION.md`) |
| MOD-02 | Two widely circulated misattributed quotes return "not in the archive" | P1 | unmeasured | The validator rejects an invented quote (`test_misattributed_quote_not_in_passages_fails`), but no real misattributed quotes have been run against a real corpus. Template: `eval/questions/answers.template.json`. |
| MOD-03 | One recording with a reviewed timestamped transcript; tapping a line seeks the player | P1 | = TR-21 | verified (API and pipeline; tap-to-seek UI untested) |
| MOD-04 | One photograph with a reviewed caption and provenance | P1 | verified | Workflow, 2026-09-27 host run: `test_db_visitor_features.py::TestPhotographs` (`test_unreviewed_caption_is_never_shown_to_visitors`, `test_reviewed_photo_in_browse_and_search_with_caption_credit_and_rights`, `test_staff_caption_review_records_decision_with_corrected_caption`). The live item 8 is a synthetic illustration whose caption was approved by `fixture-seed`. |
| MOD-05 | 8–12 timeline events, one story, a map of about 20–30 nodes, each linked to items | P1 | implemented-unverified | Seeded 11 events, 1 story, and 24 nodes. All are synthetic and none cite real items 1–7 (see RR-08). |
| MOD-06 | Reviewed summaries for 2–3 items | P1 | = TR-13 | verified (workflow; live summaries are `fixture-seed` approvals) |
| MOD-07 | Add three items, scan the QR code on a phone, open the read-only page | P1 | unmeasured | Code = TR-34 (verified at API level). No recorded phone run. |
| MOD-08 | Signage loop driven by the edge server | P1 | = TR-04 | verified (API level) |
| MOD-09 | Network off: cached exhibits open and Ask shows "needs connection" | P1 | implemented-unverified | `web/src/sw.ts`, `web/src/exhibitVerify.ts`, and the `askOffline` string. Manifest signing and exclusion of online-only items are verified by `test_sign_and_verify_roundtrip_and_tamper_detection` and `test_online_only_item_visible_but_never_in_kiosk_cache`. The service worker and the web tests were not run. |
| MOD-10 | One full restore to a clean machine with a checksum match, shown from its recorded log | P1 | unmeasured | 2026-09-27: a same-host restore drill passed (n = 1, `eval/results/backup-restore-2026-09-27/worker-job/RESTORE_LOG.json`, filled into `eval/results/results-2026-09-27.json`). It ran on the edge host itself, so `target_was_clean_machine` = no. A restore on a different machine is still needed. Tool: `eval/verify_restore_log.py`. |
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
| RR-06 | Item 6: one recording with written permission, or a clearly labelled team-made recording | P1 | implemented-unverified | Labelled synthetic recordings `fx-talk-audio` and `fx-talk-video` are in `fixtures/manifests/fixture_manifest.json`, and the recording pipeline is verified (TR-21). Their live publication has not been re-checked since the rebuild; `fx-talk-video` needs a `seed-fixtures` run. |
| RR-07 | Item 7: a manuscript page, or the path demonstrated on a labelled test page | P1 | verified | Path on a labelled test page, 2026-09-27 host run: `test_db_visitor_features.py::TestManuscripts` (handwriting routes to human transcription with no Sarvam call and is not counted as OCR fallback; the published page shows the scan beside the archivist's "Reviewed transcription"). The live `fx-manuscript-note` transcription was seeded. A real page needs the holder's permission. |
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
| TG-04 | Hard negatives mined from the base model, each confirmed non-relevant by a person (another edition is not a negative) | P1 | verified | 2026-09-27. Tests: `tests/test_db_hard_negatives.py`, 15 tests, which pass in the full host suite. They cover exclusion of positives, reprints and ineligible passages; provenance; named-person review with a false-negative flip; `load-labels` importing only confirmed negatives; only confirmed negatives in the frozen manifest; cross-split negatives dropped; and `check_training_leakage`. Code: `backend/archive/datasets/hard_negatives.py`, table `hard_negative_candidate` (migration `0003_hard_negatives`, after 0002, not yet applied to the live DB), and CLI `mine-hard-negatives` / `list-hard-negatives` / `review-hard-negative(s)` / `export-labels`. There are no real reviewed questions, so nothing has been mined on real data, and there is no staff-API endpoint yet. See `docs/DATASETS_AND_BACKUP.md`. |
| TG-05 | A Hindi or Marathi result is claimed only if that language has its own test examples | P1 | verified | `eval/tests::test_language_without_its_own_test_examples_is_not_claimed`; the backend side is `gate_report.claimable_languages` in `backend/archive/datasets/corpus.py`. |
| TG-06 | Trained-vs-base results are shown only if the gate is met, and differences carry confidence intervals | P1 | verified | `eval/tests::test_comparison_refused_when_gate_not_met`, `test_trained_model_result_rejected_when_gate_not_met`, `test_difference_without_confidence_interval_rejected`. |
| TG-07 | ModelVersion registration: base model, dataset version, config, commit, results, size | P2 | implemented-unverified | The `ModelVersion` schema is in `backend/archive/models.py`; there is no registration code (P2). |

## Evaluation fields (§10)

Only the 7 `backup_restore` fields are measured: one same-host drill, n = 1, in `eval/results/results-2026-09-27.json` (2026-09-27). Its `target_was_clean_machine` is "no". Every other field in `eval/templates/results_template.json` (105 fields in 16 areas) and in `eval/RESULTS.md` is **UNMEASURED**, with a blank sample size:

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
- checksum-verified restore on a clean machine
- training baseline
- the two P2 trained-model areas

`python eval/check_results.py` rejects any filled results file that quotes a number without a sample size, method and evidence.

## Defects and gaps found (for the owning teams; not patched here)

1. **Backend:** a recording cannot publish. The media delivery copy is missing at verification: one failing test, and the live `fx-talk-audio` item is stuck `in_review`.
2. **Backend tests:** `test_tesseract_real.py` is referenced but does not exist, so real OCR is untested.
3. **Deploy:** the worker inherits the API's HTTP healthcheck, so it reports `unhealthy` permanently. `docker-compose.yml` also points to a `deploy/production/` folder that does not exist.
4. **Backend:** nothing schedules fixity. Backup is scheduled nightly (TR-29), but the api/worker image must be rebuilt before its `pg_dump` can dump the PostgreSQL 17 server. The worker backup job has no retention.
5. **Backend CLI:** `eval-answers` sends no conversation history, so follow-up questions cannot be evaluated. (`load-labels` now imports person-confirmed hard negatives, TG-04.)
6. **Web:** the answer citation links (`.answer sup a`) are below 48 px (TR-37).
7. **Curation data:** the only Constitution-article link is a labelled synthetic demo (TR-36), and one story block points at an unpublished item.
8. **Docs:** `docs/BUILD_LOG.md` does not exist yet, so this checklist does not cite it.
