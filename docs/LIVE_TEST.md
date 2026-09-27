# Live test record — 2026-09-26

This file records one run of the backend test suite and a small set of live provider calls. **A successful API call is not human quote verification, not translation review, and not a production go-live.** Everything sent to providers was synthetic fixture content or a short made-up sentence. No real archive material was sent.

No secrets are recorded here. API keys are reported only as present or absent.

## 1. Configuration checked (`.env`, re-read before the live calls)

| Setting | Value at test time |
|---|---|
| `ARCHIVE_SARVAM_API_KEY` | non-empty |
| `ARCHIVE_LLM_PROVIDER` | `openai_compatible` |
| `ARCHIVE_LLM_BASE_URL` | `https://api.openai.com/v1` |
| `ARCHIVE_LLM_API_KEY` | non-empty (different key from the Sarvam key) |
| `ARCHIVE_LLM_MODEL` | `gpt-4o-mini` |
| Sarvam base URL | `https://api.sarvam.ai` (code default, not set in `.env`) |

**Answer model.** The user confirmed that answers use OpenAI `gpt-4o-mini` with the settings above. `.env` was last written at 21:41 IST. All live calls ran after that, from the host, so they read this exact file. Sarvam chat models (`sarvam-m`, `sarvam-105b-conversations`) were deliberately not called.

**Running containers.** The compose `api` and `worker` containers were started about 21:07 IST, before the last `.env` edits. They were not restarted during this test, so they may still hold the older answer-model settings. Restart only those two services (no `down`) before relying on live Ask in the demo UI.

`ARCHIVE_SARVAM_API_KEY` is used only for OCR, translation and TTS, through the `api-subscription-key` header. `ARCHIVE_LLM_API_KEY` is used only for the answer call, through `Authorization: Bearer` on `POST {base}/chat/completions`.

## 2. Backend automated tests

Command, run from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

- Environment: Python 3.12.11, pytest 9.1.1, project venv at `backend/.venv`.
- Database: the suite's own `archive_test` database on the local compose Postgres (`localhost:55432`), created and migrated by `backend/tests/conftest.py`. The demo `archive` database was not touched by the tests.
- `conftest.py` disables Sarvam, the LLM and Langfuse, and uses a hash embedder and a lexical reranker. So these tests check behaviour against test doubles, not the live providers.

**Result: 88 passed, 0 failed, 0 skipped** (280 s). No test setup changes were needed. The later `.env` edits do not affect this result, because `conftest.py` overrides the provider settings.

## 3. Live provider smoke

These are one-off scripts outside the repo. They call the existing clients in `backend/archive` and redact configured secrets from any error text. They were run from the repo root so `.env` loads:

```powershell
.\backend\.venv\Scripts\python.exe <temp>\archive_live_smoke.py translate chat
.\backend\.venv\Scripts\python.exe <temp>\archive_live_smoke.py translate chat ocr tts
.\backend\.venv\Scripts\python.exe <temp>\archive_ocr_measure.py
```

The second run repeated the translation and chat calls, because the TTS step only runs after both succeed in the same run. The OCR page was therefore sent to Sarvam twice: once in the smoke run and once in the measurement run.

### 3.1 Translation — `archive.services.sarvam_text.translate` — PASS

- Input: "The library opens at nine in the morning." (English to Hindi)
- HTTP: 2xx; model `sarvam-translate:v1`; about 2.5 s.
- Output: `पुस्तकालय सुबह नौ बजे खुलता है।` This output is reasonable, but it is not reviewed.
- Labelling in the code (checked by reading the code, not by an end-to-end API call):
  - The visitor route `GET /translate/{passage_id}` returns `label: "Machine translation — not reviewed"`, `stored: false` and `citable: false`.
  - The staff route `POST /translations` stores `method="machine", provider="sarvam"` as a draft.
  - Neither path marks a machine translation as reviewed.

### 3.2 Answer model — `archive.ask.llm.OpenAICompatibleLLM` — PASS (OpenAI `gpt-4o-mini`)

- Provider/model requested: `https://api.openai.com/v1`, `gpt-4o-mini`. The response reported `gpt-4o-mini-2024-07-18`.
- The request was sent exactly as the client builds it: `max_tokens=60`, `temperature=0`, `response_format={"type":"json_object"}`.
- HTTP: 2xx; content `{"status": "ok"}`, which parses as a JSON object; 36 tokens in, 6 out; about 2.9 s.
- Sarvam chat models were not called, as instructed.

### 3.3 OCR fallback — `archive.ingest.sarvam_ocr.SarvamDocAI.digitise_page` — API PASS, output unusable as-is

- Page used: `fixtures/files/fx-lecture-tank-degraded.png`. This is a synthetic fixture, not a real document. In the demo database it is page 4 (item 3). That page has `gate_passed = false` and failed all 7 gate checks (`min_words`, `min_mean_confidence`, `min_p10_confidence`, `min_coverage`, `min_script_share`, `min_lexicon_ratio`, `max_garbage_rate`).
- One page only, language `en`. No volume was sent and nothing new was downloaded.
- The client was called directly, not through `run_sarvam`. **Nothing was written to any database, and the Sarvam text was not stored, indexed or published.** Page 4 in the demo database is unchanged.
- HTTP: job created, polled and downloaded successfully; status `completed`; engine `sarvam-vision (doc-ai v1)`; about 21 s.
- **Output finding (product issue, not fixed):**
  - The returned Markdown was about 139–142k characters.
  - It contained **7 inline `data:image/jpeg;base64` images** plus model-written image descriptions ("*The image appears to be a grayscale, low-resolution photograph…*"), not a transcription.
  - After removing the data-URI images, about 15.9k characters were left, against 510 characters of ground truth. Similarity to the ground truth (rapidfuzz ratio): 0.062 with images removed, 0.007 raw.
  - `extract_markdown()` does not strip inline images or descriptive captions. So `run_sarvam()` would store this whole blob as `OcrResult.text`, and the local-versus-Sarvam `disagreement` value it computes would mean little.
  - The page still goes to full archivist review (`needs_full_review`), so nothing is auto-accepted. But the reviewer would see image data and descriptions, not candidate text.
  - This page is deliberately heavily degraded. Behaviour on realistic low-confidence pages is **unmeasured**.

### 3.4 TTS — `archive.services.sarvam_text.synthesize` — PASS

- Text: "Friends, education is not a gift that one class hands to another." This comes from the approved synthetic fixture `fx-lecture-education`, which is a seeded approval, not a human one.
- HTTP: 2xx; generator `bulbul:v3/ritu`; 169,388 bytes of audio with a valid `RIFF` WAV header. Nobody listened to the audio.

## 4. What this run does and does not show

Verified live:

- The Sarvam key authenticates for translation, Document AI OCR and TTS.
- The OpenAI key authenticates for chat completions with a JSON-object response through the existing client.
- The request formats in the existing clients are accepted by those endpoints.

Still unmeasured or open:

- Live Ask through the running API container. The container predates the last `.env` edit, and these calls were made from the host.
- End-to-end Ask quality, citation validity, refusal behaviour and cost with a live model. The pytest suite runs with `ARCHIVE_LLM_PROVIDER=none`.
- Translation quality on real archival text, and Hindi/Marathi TTS.
- Sarvam OCR on realistic gate-failing pages, and the image/description stripping issue in 3.3.
- Nothing here is human quote verification, translation review, OCR review or a production go-live decision.

## Audio publish checksum

Recorded failure (`docs/REQUIREMENTS.md`, backend run at about 21:29 IST): `tests/test_db_media.py::test_published_transcript_passages_carry_segment_quote_status` raised `PublicationError: verification failed: media delivery copy missing or checksum mismatch`.

- Root cause: a test-fixture defect, not a publish-code defect. In the 21:29 version of `backend/tests/test_db_media.py`, the `_audio_item` fixture created the audio item and its transcript segments but no `FileVersion` with `role="delivery", kind="media"`. `archive/ingest/publish.py::verify` requires that copy for `audio`/`video` items and checks its SHA-256, so publishing failed. Verification behaved correctly.
- Fix: `_audio_item` now stores synthetic bytes with `storage.put_bytes(..., "delivery", ".flac")` and records a delivery media `FileVersion` using the returned `sha256`, `byte_size` and `storage_uri`. The backend team made this change at 21:40 IST, and this check made no further code change. `publish.py` and `storage.py` are unchanged.
- Quote status: the test's `quote_verified=True` on segment 0 comes from the existing `review.verify_segment_quotes` call on a synthetic fixture item (`is_fixture=True`, "Synthetic test source"). It is a seeded test record, not a person checking a real recording.

Commands and results (2026-09-26, about 21:53 IST):

```powershell
# from backend/
$env:PGHOSTADDR="127.0.0.1"
.\.venv\Scripts\python.exe -m pytest "tests/test_db_media.py::test_published_transcript_passages_carry_segment_quote_status" -p no:cacheprovider -q -rA
```

**Result: 1 passed in 2.85 s.**

```powershell
# from backend/
.\.venv\Scripts\python.exe -m pytest tests/test_db_media.py -p no:cacheprovider -q -rA
```

**Result: 5 passed in 4.81 s**, including `test_publication_verification_requires_the_media_delivery_copy`, which still fails publication when the checksum is wrong.

The same file was also run with the recorded container command (one-off container; no services restarted):

```powershell
# from the repository root
docker compose run --rm --no-deps -v "${PWD}/backend:/app:ro" -e PYTHONDONTWRITEBYTECODE=1 api python -m pytest tests/test_db_media.py -p no:cacheprovider -q -rA
```

**Result: 5 passed in 4.57 s.**

- Host note: `PGHOSTADDR=127.0.0.1` is only a workaround for connecting from this machine. `localhost` resolves to `::1` first, and connecting to `[::1]:55432` stalls. The Alembic engine in `conftest.py` has no connect timeout, so it hangs instead of falling back to IPv4. No credentials were passed on the command line.
- Not fixed here: the live seeded `fx-talk-audio` item is still `in_review`. `seed.log` shows four segments approved "(seeded)" and an empty processing route list, which suggests media processing (the step that creates the delivery copy) did not run for it. This was not checked against the live database. It is a separate seed/processing issue in the running archive, and it was not touched.

## Sarvam OCR image/description stripping (fix for 3.3)

Retry on 2026-09-26 at about 21:57 IST, after the parser fix. No commits were made and no services were restarted.

- Root cause: `extract_markdown()` returned the whole Doc AI Markdown, and `run_sarvam()` stored it as `OcrResult.text`. For this page, the Markdown has 7 inline `![Image](data:image/jpeg;base64,...)` images. After each image comes one italic caption span that runs over many paragraphs (headings, analysis lists, "Possible Questions and Answers", conclusion). Sarvam did transcribe the page, but the three transcribed paragraphs sit between those caption spans.
- Fix (`backend/archive/ingest/sarvam_ocr.py`): the new `transcription_from_markdown()` removes images (Markdown and HTML images, data URIs, long base64 runs), each whole italic caption span that follows an image, and any other paragraph that reads as an image description. If no letters remain, the output is marked as not a transcription, with a reason. `SarvamOcrOutput.text` now holds only the cleaned text. The raw Markdown is returned separately as `raw_markdown`.
- Storage (`backend/archive/ingest/processing.py::run_sarvam`):
  - The raw Markdown is saved as a staff-only derivative `FileVersion` (`kind="sarvam_raw"`, `text/markdown`). Its id is in `OcrResult.raw_meta.raw_file_id`, along with strip counts. No schema change.
  - If no transcription remains, the Sarvam `OcrResult` is `status="failed"` with `text=""` and the reason in `error`. The page stays `needs_full_review` (`review_mode="full"`, route stays `local`, reason in `sarvam_last_error`), and the local draft stays the candidate.
  - If text remains, it is stored as the Sarvam candidate. It is still never selected or auto-accepted, and the page still goes to full review.
- Tests: new cases in `tests/test_unit_integrations.py` and `tests/test_db_pipeline.py` use a synthetic payload shaped like this live output (`conftest.sarvam_image_dump_markdown`). Sarvam is not called.

One live call, on the same synthetic fixture only (`fixtures/files/fx-lecture-tank-degraded.png`, language `en`). The client was called directly from the host. **Nothing was written to the demo database, and page 4 is unchanged and unpublished.** No other page was sent.

| | Value |
|---|---|
| Job status | `completed`, about 12 s |
| Raw Markdown | 140,814 chars, 7 data-URI images (still kept, now only as the raw payload) |
| Text selected by the parser as first shipped | 10,281 chars; ratio 0.094 against the 510-char ground truth. The italic caption spans were not yet recognised. |
| Text selected by the final parser (re-run offline on the same saved response; no second call) | 511 chars; **ratio 0.995**; no base64 and no mention of "image" |

- The final selected text is the page's disclaimer line, its title and its paragraph, as Sarvam transcribed them. Through `run_sarvam` this would be stored as the Sarvam candidate for **full archivist review**. It would not be auto-accepted or published.
- This is one deliberately degraded synthetic page. The caption-span rule matches the output format observed here. Behaviour on real gate-failing archive pages is still **unmeasured**.

## Seeded audio delivery

Checked against the live demo database on 2026-09-26. No commits were made, no services were restarted and nothing was taken down.

- The earlier guess in "Audio publish checksum" was wrong: media processing did run for `fx-talk-audio` (item 9). The delivery copy `file_version` 12 (`ffmpeg aac64k`, `audio/mp4`) was created at ingest. It is on the delivery volume, and its SHA-256 matches. The processing route list in `seed.log` is empty only because recordings have no pages.
- Why the item stayed `in_review`: the seed ran at about 21:08 IST, and `archive/cli.py` and `archive/ingest/review.py` were changed about a minute later. The old files were not kept, so their exact behaviour is unknown. With the current code, the same four seeded segment approvals leave the item `approved`. This was replayed in a transaction that was then rolled back. Because the item never reached `approved`, the seed's publish step never picked it up.
- Seed change (`archive/cli.py`):
  - Before publishing, `seed-fixtures` now makes sure every fixture recording has a delivery copy whose checksum matches the file on disk.
  - If the copy is missing or its checksum fails, the synthetic master bytes are stored as the delivery copy and recorded with their SHA-256. A copy that fails its checksum is marked deleted.
  - A new command, `seed-fixture-media`, repairs already-seeded recordings in place. It re-checks the delivery copy, recomputes the review state, and then runs the existing publish step. It approves nothing, so a recording whose transcript review is incomplete stays unpublished. It imports nothing, so no items are duplicated.
- Test: `tests/test_db_media.py::test_seed_media_delivery_replaces_a_bad_copy_but_publication_still_waits_for_review` (host run, 6 passed in that file). `tests/conftest.py` now connects to `127.0.0.1:55432` by default instead of `localhost`, so the `PGHOSTADDR` workaround described above is no longer needed. No credentials were put on the command line.

Command, run from the repository root (one-off container, no services restarted):

```powershell
docker compose run --rm --no-deps -v "${PWD}/backend:/app:ro" -e PYTHONDONTWRITEBYTECODE=1 api python -m archive.cli seed-fixture-media
```

- About 22:07 IST: the existing FFmpeg copy was kept (`present (ffmpeg aac64k)`). Publish ran stage, then verify (`ok: true`, 4 passages, 4 embedded, no errors), then switch.
- Later, Docker could not start new containers. The same command was run again by piping the updated `cli.py` into `docker compose exec -T api python - seed-fixture-media`. It found the item already published and changed nothing.

**Publication state afterwards: `fx-talk-audio` is `published`** (`published_version_id` 11, item version 1, index version 11, actor `fixture-seed`). There are no duplicate item keys. There are 10 published fixture items, plus `fx-restricted-memo`, which is `approved` but blocked by its rights.

- The 4 `reviewed_transcript` passages have `quote_verified = false`. The segment approvals are seeded fixture records, not a person checking the recording. No quote verification was seeded for this item.

## Continuation run — 2026-09-26/27, about 23:40–00:30 IST

### Sarvam OCR parse — live retry with the current parser

The parser fix above was already on disk, so it was not rewritten. The tests covering it were run first, from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -k "sarvam" tests/test_unit_integrations.py tests/test_db_pipeline.py -rA
```

**Result: 17 passed.** These include `test_image_dump_is_not_returned_as_ocr_text`, `test_images_and_captions_are_stripped_around_real_text`, `test_sarvam_image_dump_is_not_stored_as_transcription` and `test_sarvam_text_between_captions_is_kept_for_full_review`.

One live call was then made on the same synthetic page only (`fixtures/files/fx-lecture-tank-degraded.png`, language `en`). The client was called directly from the host through a temporary script outside the repo. The key was read from `.env` and never printed. **Nothing was written to any database, and no other page or file was sent.** The Constituent Assembly PDFs were not sent.

| | Value |
|---|---|
| Job status | `completed`, 14.1 s, engine `sarvam-vision (doc-ai v1)` |
| Raw Markdown | 141,525 chars; 7 `data:image` URIs |
| Parser strip counts | 7 images removed, 63 description blocks removed |
| `not_transcription` | none (text remained) |
| Selected text | 511 chars against 510 chars of ground truth; **rapidfuzz ratio 0.995**; no `base64`; no mention of "image" |

This time the current parser produced the 0.995 result live, not only in the offline re-parse. Through `run_sarvam` the text would still only be a Sarvam candidate for **full archivist review**. It is never auto-selected or published. This is one synthetic page; behaviour on real gate-failing pages is still unmeasured.
### Live visitor Ask through the running API — outcome `error` (answer model call failed inside the container)

The Ask was sent through the running stack (`POST https://localhost:8443/api/visitor/ask`, Caddy to the compose `api` container) by a temporary host script outside the repo. No secrets were read by the script.

- Question (English UI): "According to the lecture on education, why should mothers learn to read?" This targets the published synthetic fixture `fx-lecture-education` (item 2).
- Container configuration, checked through `GET /api/staff/settings/status` after archivist login: `llm_configured: true`, `llm_model: gpt-4o-mini`, `sarvam_configured: true`, trace backend `local-jsonl (Langfuse keys not configured)`. The api container was recreated after `.env` was last written (21:41 IST).
- Retrieval (visitor search, same question): the top three results were passage 18 (item 9, audio transcript, `quote_verified` false), passage 3 (item 5, Hindi pamphlet, false) and passage 7 (item 2, p. 1, `quote_verified` true). All are published synthetic fixtures.

| | Attempt 1 (`answer_id` 6) | Attempt 2 (`answer_id` 7) |
|---|---|---|
| HTTP | 200 | 200 |
| `outcome` | `error` | `error` |
| Language detected | `en` | `en` |
| `model` / tokens / cost | none / 0 in, 0 out / $0 | none / 0 in, 0 out / $0 |
| `label` ("AI-generated answer…") | none (no answer) | none (no answer) |
| Sentences / citations returned | 0 / 0 | 0 / 0 |
| Latency | 26.6 s | 10.5 s |

- What this shows: language detection, retrieval and sufficiency ran. The sufficiency check passed, because the graph reached `generate`, which is the only node that sets `outcome = "error"`. The answer-model call then raised `LLMUnavailable`: zero tokens and no model name came back. The visitor got the abstention message, and no AI-generated text was shown.
- Why the model call failed: **not determined**. The reason is written only to the container's local JSONL trace, and Docker could no longer run `docker exec` (the engine returned HTTP 500), so the trace could not be read. The same key and model had returned a JSON object from the host earlier (§3.2). The most likely cause is the degraded Docker VM (see below), but this is not proven.
- Citation check: nothing to check, because no answer and no citations came back.
- Bug found and fixed in code, **not yet deployed or run against a database**:
  - For `outcome = "error"`, the API returned the message "These are the closest items to browse" with an empty citation list, and the web Ask page showed only a generic error.
  - `archive/ask/service.py` now returns the closest passages for `error` too, and `web/src/pages/Ask.tsx` shows them under "Related".
  - New test: `tests/test_db_ask_datasets.py::test_answer_model_failure_offers_closest_passages_without_an_answer`. It could not run: all 18 tests in that file were skipped with "PostgreSQL test database not reachable", because host connections to port 55432 were taking longer than 3 s. `tsc` passes on the web change.

### Docker engine degraded during this run (blocker)

From about 00:05 IST, the Docker Desktop engine stopped answering management commands:

- `docker ps` timed out after 45–60 s every time.
- `docker compose build api` and `docker build` never started; buildx reported "context deadline exceeded: driver not connecting".
- `docker exec` returned HTTP 500.
- Host connections to the proxy (8443) and database (55432) alternated between working, TLS resets, 502 from Caddy and connect timeouts.
- About 20 client processes were left hanging, including other engineers' runs: a CAD ingestion attached since 21:42 IST, and seed and remove commands. Host free memory was 2.4 of 15.6 GB.

Effects:

- **api and worker were not restarted** and the api image was **not rebuilt**. The running image predates the current `sarvam_ocr.py` and `cli.py`, and today's `service.py` fix.
- The worker healthcheck change in `docker-compose.yml` is written but not applied.
- `web/scripts/smoke_test.py` could not complete: its first request got a TLS connection reset.

The database was not taken down, and Docker Desktop was not restarted, because a restart would stop the database and other engineers' running jobs. Next step: restart Docker Desktop at a moment agreed with the other engineers, then run `docker compose build api` and `docker compose up -d --force-recreate --no-deps api worker`, re-run the Ask, run `pytest tests/test_db_ask_datasets.py`, and run `smoke_test.py --ask`.

## Docker recovery and rebuild — 2026-09-27

Run from about 11:09 to 11:30 IST. The user authorised a Docker recovery; no other jobs were running. No volumes were deleted, `docker compose down -v` was not run, nothing was committed, no secrets were printed, and nothing new was ingested. `data/incoming/`, `intake/` and `docs/DATA_SOURCES.md` were not touched.

### 1. Engine state

- `docker ps -a` (wrapped in a 40 s job timeout) answered in about 8 s. `docker info` reported server 29.1.5.
- Every container had been up for about 3 minutes, so the engine had already been restarted before this run started. Docker Desktop was **not** restarted by this run, and `wsl --shutdown` was not needed.

### 2. Leftover containers and the stuck session

- `docker ps -a --filter name=api-run` returned nothing. `api-run-23e4307f5c70`, `api-run-9bf33807883c`, `api-run-790be2b0087a` and the hung ingest container `api-run-b5f59bd37081` were already gone, most likely cleaned up by the engine restart because they were `--rm` one-offs. Nothing needed removing, and the item-14 ingest cannot resume.
- `pg_stat_activity` on `archive` showed 3 sessions, all `idle`, none `idle in transaction`. Nothing needed terminating: the database restart had already rolled back the uncommitted item-14 transaction.
- Items 12 and 13 are `in_review` with 62 and 96 pages. Item 14 is `draft` with 92 pages. All three are `restricted`, and they were left as they were.

### 3. Rebuild and recreate

| Command | Result |
|---|---|
| `docker compose build api` | Built in about 6.5 min, including a model prefetch of about 287 s. No build failure. |
| `docker compose build proxy` | Built. The proxy image contains the web bundle, so this deploys the `Ask.tsx` change. |
| `docker compose up -d --force-recreate --no-deps api worker proxy` | api and worker recreated. The proxy failed with `bind 0.0.0.0:8080: Only one usage of each socket address`, because host port 8080 is taken (known issue). |
| `$env:HTTP_PORT="8088"; docker compose up -d --no-deps proxy` | Proxy up on `8088->80` and `8443->443`. |

The database container was not recreated. The compose file has no separate `web` service.

Health after the recreate:

- `api`: healthy.
- `worker`: **healthy**. The new check (`kill -0 1 && … db_healthy()`) is applied; before the recreate the old image check `curl localhost:8000` was failing.
- `db`: healthy.
- `proxy`: running. It has no healthcheck in `docker-compose.yml`; it was checked through the ready endpoint.

### 4. Migrations and readiness

- `alembic current` and `alembic heads` in the api container both report `0001 (head)`. The api command's `alembic upgrade head` had nothing to apply.
- `curl -k https://localhost:8443/api/health/ready` returned **200** in 0.09 s: `status: ready`, database true, storage true, `llm_configured: true`, `sarvam_configured: true`, trace backend `local-jsonl`.

### 5. Tests

| Command | Result |
|---|---|
| `backend> .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -rs` (about 11:21 IST, tree at `6d88ffd`) | **103 passed**, 23 s, 0 skipped |
| `pytest tests/test_db_ask_datasets.py` | 18 passed |
| `pytest tests/test_db_ask_datasets.py -k model_failure_offers_closest -rA` | `TestAskGraph::test_answer_model_failure_offers_closest_passages_without_an_answer` **PASSED**. Red-green check: with `"error"` removed from the closest-passages branch in `archive/ask/service.py` it FAILED; with the line restored it passed. `service.py` is unchanged from the commit. |
| `web> npx tsc -p . --noEmit` | clean (exit 0) |
| `web> npx vitest run` | **5 files, 33 tests passed** |

Parallel work: between 11:24 and 11:26 IST another engineer added, without committing, `backend/alembic/versions/0002_visitor_features.py`, `backend/archive/constitution.py`, `backend/tests/test_db_visitor_features.py`, three `web/src/**.test.ts` files and an `intake/` manifest. They also modified `backend/archive/models.py` and `backend/archive/search/hybrid.py`. These are not in the rebuilt image, and migration `0002` is not applied to the live database. The 103-test backend run happened before they appeared. The vitest count includes their three new test files; the earlier committed count was 2 files and 15 tests.

### 6. Live visitor Ask

Root cause of the earlier `outcome: error` (answers 6 and 7): the container trace `/data/traces/traces-2026-09-26.jsonl` has a `generate` span for both, with `error: "[Errno -3] Temporary failure in name resolution"`. The container could not resolve `api.openai.com` while the Docker VM was degraded. The key, `response_format` and httpx timeout were never reached. After the engine restart, the api container resolved `api.openai.com` in 0.09 s, and an unauthenticated `GET /v1/models` returned the expected 401. `get_settings()` in the container shows the provider `openai_compatible`, the base URL, the model `gpt-4o-mini`, and the key present. The client already turns any `httpx` error into `LLMUnavailable` and outcome `error`, so no code change was needed.

The Asks were sent through `POST https://localhost:8443/api/visitor/ask` by a temporary script outside the repo:

| | Answer 8 | Answer 9 |
|---|---|---|
| Question | "According to the lecture on education, why should mothers learn to read?" | "Quote the exact words the lecture on education uses about mothers learning to read." |
| HTTP / outcome | 200 / `answered` | 200 / `answered` |
| Label | "AI-generated answer from archive sources" | same |
| Model | `gpt-4o-mini-2024-07-18` | same |
| Tokens in / out | 368 / 45 | 369 / 37 |
| Latency (total / provider) | 5537 / 2569 ms | 3747 / 1319 ms |
| Citations | passage 7 (item 2, p. 1) | passage 7 |
| Validation | ok, no errors, no quoted spans | ok, no errors, no quoted spans |

- Passage 7 was checked in the database. It is in item 2's live published version (`item_version_id = published_version_id`, `published`), `quote_verified = true` (verifier `fixture-seed`), and `is_fixture = true`.
- Answer 9 reproduces a sentence from passage 7 verbatim but without quotation marks, so the validator did not treat it as a quote. That text still comes from a `quote_verified` passage.
- `cost_usd` is 0 because `ARCHIVE_LLM_*_COST_PER_MTOK` are not set.

TR-25 was marked **verified** in `docs/REQUIREMENTS.md` (status and evidence cell only). Limits: the quote status is a seeded fixture record, and the live quote-rejection path was not triggered.

### 7. Smoke test

`backend\.venv\Scripts\python web\scripts\smoke_test.py --ask` returned **33 passed, 0 failed**, exit 0, smoke item 15.

- Capture through intake, the worker (`local` route, gate passed), batch review, publish, reader, IIIF, hybrid search and QR list all passed.
- The live Ask was `answered` with `gpt-4o-mini-2024-07-18`, citing passage 20, in 4.0 s. Every sentence cites a delivered passage.
- The prompt injection got `rejected_input`.
- After withdrawal, the item returns 404 and is gone from search, the QR list and the kiosk manifest. Audit actions were recorded.
- The smoke item used the synthetic `fixtures/capture-demo-page.png` and ends withdrawn.

### Still open

- Proxy has no compose healthcheck, and host port 8080 is occupied, so the proxy needs `HTTP_PORT=8088` in the shell or in `.env`.
- Quote verification is seeded fixture data. No human quote verification, Langfuse or cost pricing was set up.
- The other engineer's uncommitted migration `0002` and model changes will need a rebuild and migration once they land.