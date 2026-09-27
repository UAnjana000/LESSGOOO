# Synthetic narration

Narration (TR-20, MOD-01d) is now covered by 30 automated tests and one recorded live Sarvam run. The tests found six rule violations in `backend/archive/services/narration.py` and the narration endpoints, and each was fixed. Narration is made only from approved source text or a reviewed translation. It is cached, so the second request for the same passage makes no text-to-speech call. Every response carries the label "Synthetic narration" and the generator, meaning the engine and its version. The voice is a generic stock voice.

## Rules and where they are enforced

Spec §1.1 (derivative table), §4.10, §5.5 and §6.1.

| Rule | Enforced in | Test |
| --- | --- | --- |
| Only approved source text or a reviewed translation | `narration._check_source`: the source must be a `Passage` of kind `source_text`, `reviewed_transcription`, `reviewed_transcript` or `reviewed_translation`, in the requested language | `test_unit_narration.py::TestOnlyApprovedTextOrReviewedTranslationIsNarrated` (7 cases: unreviewed machine translation, unreviewed summary, AI answer row, AI answer text, photo caption, machine-translation kind, wrong language). `test_db_narration.py::TestOnlyApprovedTextOrReviewedTranslation` (Hindi refused while the translation is unreviewed, accepted after review; unapproved page text has no passage) |
| Cached; the key includes text version and voice | `narration.cache_key` is stored in `Derivative.prompt_version` as `<text sha256[:16]>:v<text_version>:<voice>`, for example `7a50f26328eed4d9:v1:sarvam/bulbul:v3/ritu`. The voice is `sarvam/<model>/<speaker>` or `espeak-ng/<voice>`. A hit needs an approved narration whose file is not deleted | `TestCachedLabelledNarration` (4 tests): second request is a cache hit with one TTS call; an edited text and a different voice each regenerate; republishing unchanged text reuses the audio; a deleted file is regenerated, not served |
| Labelled synthetic speech, with engine and version | `LABEL = "Synthetic narration"`. The generator is `sarvam-tts bulbul:v3 speaker=ritu` or `espeak-ng <version> voice=<voice>`. It is returned by `POST /api/staff/narration` and `GET /api/visitor/narration/{id}` | `test_created_once_then_served_from_cache_with_label_and_generator_and_no_llm`; `TestEspeakOfflineEngine::test_generator_names_engine_version_and_generic_language_voice`; `TestSarvamTTSWireContract::test_generic_stock_voice_...` |
| Never imitates Dr. Ambedkar's voice | Sarvam: fixed stock speaker `ritu`, and the request carries only documented fields. The Sarvam TTS API takes no reference audio, so there is nothing to clone from. espeak-ng: generic language voices `en-gb`, `hi`, `mr` | `test_generic_stock_voice_no_cloning_inputs_and_engine_version_in_generator` checks the speaker against the documented bulbul:v3 stock list and the request fields against the documented field list |
| Sarvam TTS is a separate service from OCR fallback | `sarvam_text.tts_configured()` checks only the key and `sarvam_tts_enabled` | `test_tts_is_its_own_switch_not_gated_by_ocr_fallback_settings` |
| Offline fallback is espeak-ng; failure does not break the reader | A Sarvam error (HTTP error, bad JSON, missing or empty `audios`, bad base64) raises `ServiceUnavailable`, and espeak-ng is used. If no engine works, `NarrationUnavailable` is raised and the staff API returns 503 | `test_any_failure_is_service_unavailable_so_the_caller_can_fall_back` (6 cases), `test_sarvam_failure_falls_back_to_espeak_ng_with_the_same_label`, `test_no_engine_gives_a_clear_unavailable_state_and_the_reader_still_works`, `test_missing_binary_is_a_clear_unavailable_state`, `test_engine_crash_is_unavailable_not_an_unhandled_error` |
| Text that may not leave the premises is narrated locally | Sarvam is used only when `external_processing_allowed(item)` | `test_text_that_may_not_leave_the_premises_is_narrated_locally_only` |
| Withdrawn items are not served or narrated | Visitor: `load_hits` hides the passage, and `/files/{id}` hides the file. Staff: `narrate` refuses a withdrawn item or an unindexed passage with 409 | `test_withdrawn_item_narration_is_not_served_or_generated` (also checks that withdrawal cleanup deletes the narration file) |
| Never training data | The corpus is built from `Passage` rows only (`datasets/corpus.py`, not edited) | `test_narration_never_enters_the_training_eligible_corpus`: the dataset preview is identical before and after narration, and a frozen manifest holds only the passage |
| Browsing and playback make zero LLM calls | Narration and playback call no LLM | `test_created_once_...` fails if `get_llm` is called during generation, visitor lookup, file download or item view |
| Storage and kiosk cache are bounded | One file per text version and voice; content-addressed storage; narration files count against `exhibit_cache_budget_bytes` | `TestCachedLabelledNarration`; `test_narration_audio_counts_against_the_kiosk_cache_budget` |

## Violations found and fixed

Each test below failed on the original code. The unit tests were run before the fix. The DB tests were run against a copy of `backend/` with the original service code restored; the copy had only the two hooks the test doubles need. Each test passes after the fix.

| Violation | Fix | Test that caught it |
| --- | --- | --- |
| No cache: every request synthesised again and stored a new file | `narrate` looks up the cache key first; the staff response adds `cached` | `test_created_once_...`, `test_edited_text_...` |
| Sarvam was called for items whose rights do not allow external processing | `use_sarvam` requires `external_processing_allowed(item)` | `test_text_that_may_not_leave_the_premises_is_narrated_locally_only` |
| A withdrawn item could still be narrated | Refuse a withdrawn item or an unindexed passage | `test_withdrawn_item_narration_is_not_served_or_generated` |
| A non-passage source (translation row, AI answer, text) crashed with `AttributeError` instead of a refusal | `_check_source` type check | `test_refused_before_any_speech_engine_runs` |
| Malformed Sarvam responses escaped as `KeyError`, `binascii.Error` or `JSONDecodeError`, and an empty `audios` list gave empty audio, so there was no fallback | Map them to `ServiceUnavailable` | `test_any_failure_is_service_unavailable_so_the_caller_can_fall_back` |
| No engine available, or an espeak-ng or ffmpeg crash, gave 409 or 500 | `NarrationUnavailable`, and the staff API returns 503 | `test_no_engine_gives_a_clear_unavailable_state_...`, `test_engine_crash_is_unavailable_...` |

Smaller defects fixed alongside:

- The espeak-ng generator had no version. It is now `espeak-ng 1.51 voice=...`, read from `espeak-ng --version`.
- The Sarvam generator did not name the engine. It is now `sarvam-tts bulbul:v3 speaker=ritu`.
- Text was passed to espeak-ng as a command-line argument, so a passage starting with `-` was parsed as an option. Text now goes on stdin (`--stdin`). This was checked against espeak-ng 1.51 in the running api container, read-only.
- A reviewed translation's narration listed only the translation passage id. `web/src/pages/Item.tsx` looks for the source passage id, so Hindi and Marathi narration never played in the reader. `source_ids` now also holds `translation_of_id`.
- `GET /api/visitor/narration/{id}` returned an arbitrary row and could return a deleted file. It now returns the newest narration whose file exists.

Files changed: `backend/archive/services/narration.py`, `backend/archive/services/sarvam_text.py`, `make_narration` in `backend/archive/api/staff.py`, `narration_for` in `backend/archive/api/visitor.py`. New tests: `backend/tests/test_unit_narration.py` (19), `backend/tests/test_db_narration.py` (11). No migration was needed.

## Live Sarvam TTS run

2026-09-27, about 13:15 IST, from the host venv. `ARCHIVE_SARVAM_API_KEY` was read from `.env` and not printed. The run called `narration.narrate` with the real `sarvam_text.synthesize` and the host ffmpeg. It used a scratch database (`archive_test_narration`) and a temporary storage root, so the demo data was not touched. There were exactly 3 live calls, one per language, and each language's second request was a cache hit with no call.

| Language | Approved fixture sentence (`fx-essay-reading-rooms`, page 1) | Generator | WAV from Sarvam | Stored AAC (m4a) | Second request |
| --- | --- | --- | --- | --- | --- |
| en | "A reading room is a promise made by a town to every person who walks through its door." (source text) | `sarvam-tts bulbul:v3 speaker=ritu` | 4.61 s, 203,256 B, 22,050 Hz | 4.61 s, 29,504 B | cache hit, same file |
| hi | "वाचनालय एक वादा है जो कोई शहर अपने दरवाज़े से आने वाले हर व्यक्ति से करता है।" (reviewed translation) | same | 7.25 s, 319,916 B | 7.25 s, 51,731 B | cache hit, same file |
| mr | "वाचनालय म्हणजे एखाद्या गावाने त्याच्या दारातून येणाऱ्या प्रत्येक व्यक्तीला दिलेले वचन." (reviewed translation) | same | 6.49 s, 286,048 B | 6.49 s, 42,992 B | cache hit, same file |

ffprobe reported codec `aac` in an MP4 container for all three files. The Hindi and Marathi narrations list both the translation passage and its English source passage in `source_ids`. The fixture translations were approved by `fixture-seed`, not by a named human reviewer. Nobody has listened to the audio for pronunciation quality. The running demo api still needs a restart to load the key. This run did not go through the containers.

## Test results

Run from the host on 2026-09-27 with `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` in `backend/`. `ARCHIVE_TEST_DATABASE_URL` pointed at a private `archive_test_narration` database, because two other engineers' runs had deadlocked on the shared `archive_test` database. Postgres cannot detect that cross-process wait.

| Run | Result |
| --- | --- |
| Narration tests only (`test_unit_narration.py`, `test_db_narration.py`) | 30 passed |
| DB narration tests against the original code (RED) | 8 failed, 2 passed. The 2 that passed cover rules the old code already met: unapproved text has no passage, and narration stays out of the corpus. The kiosk-budget test was added later as a check of existing behaviour. |
| Full backend suite (final) | 242 passed, 1 skipped (`test_tesseract_real.py`: Tesseract language data not installed on the host) |
| Earlier full run, same code | 9 failed, 31 errors, 194 passed, all in hard-negative, Ask, dataset, backup-verify and curation tests. Those files passed when rerun alone (51 passed, 1 Ask failure) and in the final full run. Other engineers were editing them during the run; none touch narration. |
| `ruff check` on the changed narration files and tests | clean |

## Remaining gaps

- The reader's narration player (`web/src/pages/Item.tsx`) has no UI test.
- Two staff requests at the same moment for an uncached passage can both synthesise, which stores two narrations. This is rare and staff-only.
- `sarvam_text.synthesize` cuts text at 2,400 characters (the bulbul:v3 limit is 2,500). Passages are capped at 900 characters (`passage_max_chars`), so this is not reached today.
- Story narration (`Story.narration_file_ids`) is set by curators and not generated by this service. It is served through `_file_visible`, which hides withdrawn items, but it has no dedicated test here.

## Skills used

| Skill | Source | Effect |
| --- | --- | --- |
| find-skills | `C:\Users\cvbal\.agents\skills\find-skills\SKILL.md` | Local skills matched every part of the task, so no marketplace skill was installed. Sarvam's official API reference (`docs.sarvam.ai/api-reference-docs/text-to-speech/convert`) was used for the wire contract, the stock speaker list and the 2,500-character limit. |
| test-driven-development, with `writing-good-tests.md` | `C:\Users\cvbal\.claude\plugins\cache\claude-plugins-official\superpowers\6.4.1\skills\test-driven-development\` | Tests were written first and watched failing, including the DB tests against the original code. Doubles sit only at the external boundaries (Sarvam HTTP, the espeak-ng process, ffmpeg). Assertions use hand-written literals. |
| python-testing-patterns | `C:\Users\cvbal\.claude\skills\python-testing-patterns\SKILL.md` | Parametrized refusal and failure cases, `monkeypatch` fixtures for the engines and the LLM tripwire, and `httpx.MockTransport` for the Sarvam wire. |
| senior-backend | `C:\Users\cvbal\.claude\plugins\cache\claude-code-skills\engineering-skills\2.2.0\senior-backend\SKILL.md` | Status codes: 409 for a refused source, 503 when no engine is available, 404 for hidden items. |
| code-reviewer | `C:\Users\cvbal\.claude\plugins\cache\claude-code-skills\engineering-skills\2.2.0\code-reviewer\SKILL.md` | Checklist review of the final diff (correctness, error handling, injection, caching). It found nothing blocking and produced the concurrency and 2,400-character notes listed under remaining gaps. |
| verification-before-completion | `C:\Users\cvbal\.claude\plugins\cache\claude-plugins-official\superpowers\6.4.1\skills\verification-before-completion\SKILL.md` | Every result here comes from a command run on 2026-09-27. The RED run on the original code was recorded. Failures outside narration are reported, not hidden. |
| technical-writing | `C:\Users\cvbal\.claude\skills\technical-writing\SKILL.md` | This document: conclusion first, and every claim traced to a test or a recorded run. |
