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
