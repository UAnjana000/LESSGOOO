# Changelog

State of the Dr. B. R. Ambedkar Digital Heritage Archive software. Each entry cites the record it comes from. Nothing here is a production go-live, human quote verification, archivist review, native-speaker review or a measured evaluation, unless an entry says so.

## 2026-09-27

### Local demo stack

- The local demo runs as Docker Compose project `ambedkar-archive`: `db` (`pgvector/pgvector:0.8.1-pg17`), `api` and `worker` (the backend image `ambedkar-archive/api:local`) and `proxy` (Caddy with the web app built in). The site is served at https://localhost:8443 with Caddy's internal CA. HTTP is on host port 8088, because 8080 is taken on the demo machine (`HTTP_PORT=8088`). Source: `docker-compose.yml`, `docs/BUILD_LOG.md`.
- After the Docker engine degraded overnight, the api and proxy images were rebuilt and `api`, `worker` and `proxy` recreated at about 11:09-11:30 IST, without touching the database or volumes. The worker healthcheck is applied, and readiness returns 200. The live database is at Alembic revision `0001`. Source: `docs/LIVE_TEST.md`, "Docker recovery and rebuild".
- At 21:23 IST every `ambedkar-archive` volume was found recreated empty, so the home page showed 0 items. The live DB was restored from the verified `backup-20260927T072419Z` (dump checksum OK, 604 files, 602/602 file rows, fixity and audit chain OK), migrated to `0004`, and the 14:50 fixture purge re-applied with `purge_fixtures.py`. Visitors see Writings 1, Speeches 1, Debates 2. Work after 12:54 IST is not in that backup: the Sarvam Hindi candidates (saved in `data/logs/e2e/74_all_sarvam.jsonl`), later Hindi review decisions, dataset v2 and item 17 v3. Source: `data/logs/e2e/90_*`, `91_*`.
- After the restore, the timeline, story and connections were recreated through the staff curation API as the demo curator. They are agent-drafted from the items' own manifest dates, not a human curator judgment. There are 3 timeline events (1916-05-09 item 17; 1948-11-04 item 20; 1949-11-25 items 18 and 12), the story "The Draft Constitution in the Constituent Assembly, 1948–1949" (items 20, 12 and 18), and 4 connection nodes with 3 links: item 18's speech is linked to item 12's debate of the same day, and items 20 and 12 are each linked to "Constituent Assembly of India". A headless browser confirmed that `/timeline`, `/stories`, the story page and `/map` render this content. The Hindi items are not attached. Source: `data/logs/e2e/timeline_fix/recreate_curation.py`, `40_curation_recreated.json`, `rendered_*.png`.
- Live Ask through the running stack answered with the label "AI-generated answer from archive sources" and a citation, using `gpt-4o-mini`. The overnight Ask failures were DNS resolution failing inside the degraded Docker VM, not the code or the key. `web/scripts/smoke_test.py --ask` passed 33 of 33 checks. Source: `docs/LIVE_TEST.md`.

### Ingestion of real source excerpts

- Excerpts from *Dr. Babasaheb Ambedkar: Writings and Speeches* (BAWS, Dr. Ambedkar Foundation / MEA) and the Constituent Assembly Debates (CAD, Lok Sabha Secretariat) were imported from the manifests in `intake/` as items 12, 13, 14, 17, 18, 19 and 20. Rights are recorded on the user's academic permission stated on 2026-09-27; no written document is on file, and access is `public_online_only`. Source: `docs/E2E_REAL_DATA.md`, `docs/DATA_SOURCES.md`.
- Four English items are published: item 12 (CAD, 25 Nov 1949, 62 pages), item 17 (BAWS Vol. 1, *Castes in India*, 20 pages), item 18 (BAWS Vol. 13, speech of 25 Nov 1949, 13 pages) and item 20 (CAD, 4 Nov 1948, 45 pages). Review decisions in these runs were made by an AI test agent through the staff API and are labelled as agent review, not archivist review. Source: `docs/E2E_REAL_DATA.md`, "Results".
- Item 17 was withdrawn and brought back as a test: it disappeared from search, reader, files and IIIF at once and from Ask after cleanup, and is published again as version 3. That restore used a one-off operator script, and its old passage and file IDs now return 404. Source: `docs/E2E_REAL_DATA.md`.
- Dataset version 2 (`e2e-real-2026-09-27-v2`, 641 passages, 11 items) was frozen. The training-data gate is not met (0 reviewed pairs), and no model was fine-tuned. Source: `docs/E2E_REAL_DATA.md`, `docs/DATASETS_AND_BACKUP.md`.

### Hindi items: Sarvam OCR, still in review

- Local Tesseract (`hin`) output on the Hindi items 13 (CAD vol. 7), 14 (CAD vol. 11) and 19 (BAWS Hindi Khand 1) passed the gate but carried systematic errors: digit 1 read as `॥` or `।`, embedded English turned into Devanagari junk, and dropped anusvara. The sampled review batches failed. Source: `docs/E2E_REAL_DATA.md`, bug 2.
- With the user's approval, the 210 Hindi pages were sent to Sarvam Document AI through the product's own retry path. 209 now have a Sarvam candidate; the remaining page was already approved. The first key ran out of credit on 15 pages (HTTP 402), which were retried once with a new key. Source: `docs/E2E_REAL_DATA.md`, "Sarvam Hindi OCR".
- Agent review compared a sample of pages with the scans. 6 of the first 30 were not exact matches, 3 of them with content errors, so the rest cannot be bulk-approved. At the last recorded count, item 13 had 13 of 96 pages approved, item 14 had 9 of 92, and item 19 had 17 of 22. **No Hindi item is published.** Hindi search and Ask still find only English text. Source: `docs/E2E_REAL_DATA.md`.

### Fixture purge from the live database

- The 14 synthetic fixture and smoke-test items (1-11, 15, 16, 22) and all their dependent rows were deleted from the live demo database in one transaction, and 36 unreferenced blobs were unlinked. The real items, the audit log (the purge is audit event 701), the rights records for real items, the staff accounts and the frozen dataset versions were kept. Visitor pages now show only the real items. Source: `docs/E2E_REAL_DATA.md`, "Fixture purge".
- Frozen dataset versions 1 and 2 still list 12 fixture entries each; they were not edited. Repo fixtures and the `seed-fixtures` command are unchanged.

### Visitor features on the live stack

- **Search:** English queries find the expected passages with no model call. Hindi queries return English passages through the semantic leg only, because no Hindi text is published.
- **Ask:** answerable English questions are answered with resolving citations, and an unanswerable question correctly returns "insufficient" with no model call. A long Hindi question that the English corpus can answer returns "insufficient", and an explicit Hindi request can be answered as Marathi (bugs 5 and 6). A 4 Nov 1948 question also missed passages that search ranks first (bug 1).
- **Reader:** the scan renders beside the text with the cited passage highlighted; 11 of 12 checked citation links resolve end to end (the twelfth is an expected 404 after re-publication).
- **Reader page arrows:** the item reader has "Previous page" and "Next page" buttons (56 px) at either end of the page-number row, plus left and right arrow keys. They are disabled on the item's first and last pages and update `?page=`. Names are in English, Hindi and Marathi; the Hindi and Marathi wording is agent-drafted and awaits native review. Checked live on item 17 after rebuilding the proxy on 2026-09-27. Source: `web/src/pages/Item.tsx`, `web/src/a11y.test.tsx`.
- **Ask is labelled as AI-powered:** the menu says "Ask (AI)", the home and Ask-page buttons say "Ask with AI", the Ask page is titled "Ask the archive with AI" and explains that an AI model writes answers from archive passages, can be wrong, and that quotes are exact only where marked quote-verified; staff status labels say "Ask with AI" too. Hindi and Marathi wording is agent-drafted and awaits native review. Checked live after rebuilding the proxy on 2026-09-27. Source: `web/src/i18n.ts`, `web/src/i18n.staff.ts`, `web/src/askAi.test.tsx`.
- **Ask voice input (AI transcription):** under the Ask question box, "Speak your question (AI transcription)" records up to 2 minutes in the browser. `POST /api/visitor/ask/transcribe` sends the audio with the existing answer-model key to OpenAI `whisper-1`, with the interface language as a hint, and returns text for the visitor to edit; nothing is auto-asked, and the audio is not stored or traced. Over 2 minutes or 10 MB is refused before the call; without the key the page says voice is off and typing still works. The proxy now allows `microphone=(self)`. Hindi and Marathi wording is agent-drafted and awaits native review. Checked live on 2026-09-27 with a synthetic spoken question after rebuilding api and proxy. Source: `backend/archive/ask/voice.py`, `backend/tests/test_unit_ask_voice.py`, `web/src/components/VoiceQuestion.tsx`.
- **Ask voice input, file picker removed:** the "Use an audio file" button is gone from the Ask page at the user's request; only the microphone button remains (and the control is hidden in browsers that cannot record), and the transcribe endpoint is unchanged. Source: `web/src/components/VoiceQuestion.tsx`, `web/src/i18n.ts`.
- **AI summaries on published items:** items 17 and 18 show an English summary labelled "AI summary — not a quotation", and items 12 and 20 one labelled "AI summary of the debate sitting — not a quotation", near the top of the reader with a note that no archivist has checked it; each came from one `gpt-4o-mini` call on that item's own published text, three were corrected by the agent against the same text, and all were approved by `summary-agent` (role `agent`, reason "agent-drafted summary from the item's published text, not archivist review"); summaries are never quote-verified, and Hindi and Marathi labels are agent-drafted and await native review. Source: `backend/archive/services/summaries.py`, `backend/tests/test_db_visitor_features.py`.
- **Narration:** one live Sarvam text-to-speech call produced audio labelled "Synthetic narration" for an item 18 passage. Nobody has listened to it for quality.
- **Timeline, Stories and Connections:** checked live on 2026-09-27. `/api/visitor/timeline` has 3 events on the manifest dates of the published English items (1916-05-09 item 17; 1948-11-04 item 20; 1949-11-25 items 18 and 12). `/api/visitor/stories` has 1 story, "The Draft Constitution in the Constituent Assembly, 1948–1949". `/api/visitor/map` has 6 nodes and 6 edges, including item 18 (speech) linked to item 12 (the same day's debate). The in-review Hindi items 13, 14 and 19 do not appear. All of this is agent-drafted from each item's own manifest dates, not a human curator's judgment.
- **Not working on the live stack:** the Constitution page and API are missing from the running images; `/display` was empty after the purge (not rechecked); date-range search returns HTTP 500.

Source for this section: `docs/E2E_REAL_DATA.md`, "Live feature check after fixture purge" and "Timeline and archive fit".

### Interface languages (EN / HI / MR)

- Every visitor and staff interface string comes from `web/src/i18n.ts` and `web/src/i18n.staff.ts`: 490 keys per language. The staff workspace now follows the chosen language instead of forcing English. Tests fail on a missing key, placeholder or untranslated string. Source: `docs/A11Y_I18N.md`.
- All Hindi and Marathi copy was drafted by AI agents. **Native-speaker review is pending**, and the code flags both languages as `agent_drafted_pending_native_review`.
- Automated accessibility checks (axe in jsdom on every route in all three languages, and Playwright axe on 21 visitor surfaces) report no violations. There has been no manual screen-reader test and no test on the tablet or smart display. Source: `docs/A11Y_I18N.md`, `docs/E2E_UI_TESTS.md`.

### Local OCR decision

- Tesseract stays the local OCR engine. PaddleOCR regressed Hindi and exceeded the CPU budget, and EasyOCR was far over the budget. Source: `docs/OCR_ENGINE_EVAL.md`.
- For Hindi, the tessdata_best **Devanagari** model with automatic page segmentation cut degraded-set error by 24% (relative) and fixed the digit-1 and embedded-English errors. It lives on the separate image `ambedkar-archive/api:ocr-deva` (`backend/Dockerfile.ocr-deva`). `api:local`, which the running stack uses, is unchanged. Hindi references were converted legacy-font text layers, not hand transcriptions, and no Marathi pages were scored.

### Quality gate

- The gate now fails Hindi and Marathi pages with a danda inside a number or with destroyed English quotations, and counts known weak substitutions (for example `कौ` for `की`) to raise review priority without failing the page. Thresholds are still uncalibrated (`gate-v0-uncalibrated`). Source: `docs/OCR_ENGINE_EVAL.md`, `docs/REQUIREMENTS.md` (LP-03).

### Restore of withdrawn items

- A staff restore action (`POST /api/staff/items/{id}/restore`) brings back the last published version of a withdrawn item with the same passage, file and IIIF IDs, after re-checking rights, and writes an audit event. Visitor links to a withdrawn item return 410 until then. Review decisions now record the acting user's role instead of always `archivist`. Tests are in `backend/tests/test_db_restore.py`. Source: `backend/archive/ingest/publish.py`, `docs/E2E_UI_TESTS.md`.

### Backup and restore drill

- `backend/Dockerfile` now installs the PostgreSQL 17 client, because the image's `pg_dump` 15 cannot dump the PostgreSQL 17 server; `ops.backup` refuses a client/server version mismatch before writing anything. The worker schedules one backup per night. Source: `docs/DATASETS_AND_BACKUP.md`.
- One backup made with the worker's own code and a PG17 client was restored into a throwaway container: 604 of 604 files, all key-table counts equal, audit chain verified, 41.5 s. This was on the same host (n = 1); a restore to a clean machine is still needed.

### Langfuse tracing: paused

- A self-hosted Langfuse stack (`docker-compose.langfuse.yml`) was set up and one real Ask trace was verified as redacted. The redaction in `backend/archive/tracing.py` was hardened (IP addresses, secret-shaped tokens). Source: `docs/LANGFUSE.md`.
- The Langfuse containers are stopped, and the running `api` and `worker` were never switched to it; they still trace to the local redacted JSONL file.

### Code changes waiting for a rebuild

The running `api`, `worker` and `proxy` containers use images built at about 11:17-11:19 IST on 2026-09-27. The following changes are in the working tree but are **not live** until `docker compose build api proxy` and a recreate:

- Database migrations `0002` onward (visitor features, hard-negative review). The api applies them on its next start.
- The Constitution page and API, subject/person/place facets, item metadata editing, and the date-range search fix.
- The staff restore action and review-role recording.
- The Hindi quality-gate checks, the PostgreSQL 17 client for backups (so the nightly backup schedule), and backup retention in the worker job (`ops.prune_backups`).
- The hardened Langfuse redaction.
- The staff interface translations and the "Constituent Assembly Debates" collection label.
- The Ask fixes from `docs/ARCHITECTURE_REVIEW.md` (citations checked only against passages in the prompt, no passages from local-only sources sent to the hosted model, bounded retries) and the ingestion fix that makes PDF text extraction linear instead of quadratic in page count.
- The narration fixes from `docs/NARRATION.md` (caching, rights check before Sarvam, espeak-ng fallback).

### Known open issues

- Sarvam HTTP 402 (out of credit) moves a page to manual transcription instead of keeping it retryable, and the worker uses a rotated Sarvam key only after it is recreated. Source: `docs/E2E_REAL_DATA.md`, "Sarvam Hindi OCR", bugs 1 and 2.
- Ask records a cost of 0 while `ARCHIVE_LLM_*_COST_PER_MTOK` are unset.
- Offline reload of a saved item address fails (no service-worker navigation fallback), and the service worker may not register under Caddy's untrusted certificate. Source: `docs/E2E_UI_TESTS.md`, `docs/E2E_REAL_DATA.md`.
- Backups sit on the same disk as the live data. Source: `docs/DATASETS_AND_BACKUP.md`.

### 2026-09-27: Staff speech-to-text (not live until rebuild)

Staff speech-to-text is implemented in the working tree but is **not on the running site** until the `api` and `worker` images are rebuilt and recreated.

- An archivist or reviewer can upload audio on an audio or video item (`POST /api/staff/items/{item_id}/speech-to-text`).
- Sarvam `saaras:v3` drafts a transcript only. The draft is never quote-verified or published by this action.
- Restricted items and items that forbid external processing are not sent to Sarvam.
- Recordings longer than 30 seconds are split into parts of about 25 seconds.
- Adds database migration `0004_media_segment_draft_source`.
- Tests: 47 new tests; the full backend suite has 355 passed and 1 skipped; the web suite has 172 passed.

Source: `docs/SPEECH_TO_TEXT.md`.
