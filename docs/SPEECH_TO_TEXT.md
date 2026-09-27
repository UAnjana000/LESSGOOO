# Speech to text (Sarvam) in the archivist workspace

Staff can turn a recording into a **machine draft transcript** at any time. The draft is never accepted
automatically, never published by this action, and never quote-verified. It goes to the same full review
as any audio/video transcript (spec §1.1, §4.5).

## How an archivist uploads

1. Sign in to the archivist workspace with the **archivist** or **reviewer** role (admin also works;
   curator and translation reviewer do not).
2. Open **Items** and choose an audio or video item. For a new recording, first create the item on
   **Intake** (item type Audio, document class Audio/video) with its rights entry.
3. In the **Speech to text (Sarvam)** panel:
   - choose a recording file (WAV, MP3, M4A, FLAC or OGG) and click **Upload and draft transcript**, or
   - click **Draft from stored recording** to transcribe the item's latest stored recording.
   - **Spoken language**: leave it on "Item language" or pick English, Hindi or Marathi.
4. The panel shows the job while Sarvam works. When it finishes, the draft segments appear under
   **Transcript segments** and in the **Review queue**, each labelled "Machine draft (sarvam-stt …): check
   against the recording".
5. A person listens to the recording and approves, corrects or rejects each segment. Quote verification is a
   separate step that still asks the reviewer to confirm they compared the transcript with the recording.

API: `POST /api/staff/items/{item_id}/speech-to-text`, multipart form with optional `file` and optional
`language` (`en`, `hi`, `mr`, or empty for the item language). It returns `{job_id, file_id, language,
status: "queued", label}`. The worker runs job kind `speech_to_text`. Jobs are not retried automatically
(`max_attempts = 1`), so a rejected recording does not cost repeated calls. Staff can start it again.

Errors that staff see:

| Status | When |
| --- | --- |
| 409 | Rights forbid external processing or the item is restricted. **The audio is not sent and nothing is stored.** |
| 409 | Not an audio/video item, no stored recording, or the upload is already stored with another item |
| 422 | The upload is not WAV/MP3/M4A/FLAC/OGG, or the language is not en/hi/mr |
| 503 | Sarvam key missing or `ARCHIVE_SARVAM_STT_ENABLED=false` |
| 401 / 403 | Not signed in / role not allowed |

## What is stored

- The uploaded file is stored unchanged as a **preservation master** in content-addressed storage
  (`intake.store_original`: SHA-256, exact-duplicate check, read-only file). This happens only after the
  rights check passes.
- Each transcript chunk becomes a `media_segment` row with `review_status = "draft"`, `quote_verified = false`,
  `draft_engine = "sarvam-stt saaras:v3 mode=verbatim"` and `source_file_id` pointing at the recording.
  Migration `0004_segment_draft_source` adds these two nullable columns. Without them the UI could not tell a
  machine draft from a human one.
- Running it again on the same recording replaces that recording's **unreviewed machine drafts** only.
  Approved or rejected segments are never touched.
- The item moves to `in_review` if it was not already published, staged or withdrawn. No passage is created
  and nothing is indexed. Passages come only from approved segments at the next publication.
- Audit events: `media.stt_requested` (who, which file, language) and `media.stt_draft` (segment count,
  engine, detected language, Sarvam request ids, number of parts, duration).

## What Sarvam is sent

Only this, per request, to `POST https://api.sarvam.ai/speech-to-text` (Sarvam REST speech-to-text,
[API reference](https://docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe), checked 2026-09-27):

- `file`: a **16 kHz mono WAV part of about 25 seconds**, cut from the recording with FFmpeg. The REST
  endpoint only accepts audio under 30 seconds, and Sarvam recommends 16 kHz. A long recording becomes several
  requests, and each part's timestamps are shifted by that part's real start time.
- `model=saaras:v3`, `mode=verbatim` (word-for-word, no number normalisation, which is closest to what the
  reviewer hears), `with_timestamps=true`.
- `language_code`: `en-IN`, `hi-IN` or `mr-IN`, or `unknown` so Sarvam detects the language.
- Header `api-subscription-key` from `ARCHIVE_SARVAM_API_KEY`. The key is never logged, returned or put in
  error text.

Sarvam never receives the title, metadata, rights data, staff identity or the original file. One job may send
at most `ARCHIVE_SARVAM_STT_MAX_SECONDS` of audio (default 3 hours).

Limits: the REST API has no speaker diarization, so segments have no speaker. A word that falls on a
25-second cut can be split or dropped, which is one more reason the reviewer checks every line. Without
FFmpeg, only WAV files under 30 seconds can be sent. The API and worker images include FFmpeg.

## Why the transcript is not quote-verified

Spec §1.1 puts audio/video transcripts under **full review**. The direct-quotation rule allows a quotation only
after a person has compared the approved text with the original, word for word. For recordings,
`verify_segment_quotes` requires an approved segment and an explicit confirmation that the reviewer checked
it against the recording. Speech recognition mishears names, Marathi/Hindi/English code-switching and old
recordings. A machine draft is a starting point for that human check, not a substitute for it. So this
action only ever writes `draft` segments. The UI says so above the upload control and on every draft segment.
Approval, quote verification and publication stay separate, human, audited steps.

## Tests run

Sarvam is faked at the HTTP boundary with `httpx.MockTransport`. No live Sarvam call was made.

- `backend/tests/test_unit_speech_to_text.py` (24 tests): wire contract (documented endpoint and fields,
  language code, `unknown` for detection, timestamp offsets per part), no request when unconfigured or
  switched off, 4xx is rejected without retry, 503 is retried then reported as unavailable, malformed
  200 responses are errors (not transcripts), the key never appears in error text, FFmpeg splitting
  into parts under 30 s at 16 kHz mono, behaviour without FFmpeg, and MP3/WAV/M4A sniffing (including untagged
  MP3 without misreading JPEG or AAC).
- `backend/tests/test_db_speech_to_text.py` (23 tests): upload stores the original and the job stores
  **unverified draft** segments (no passage, item `in_review`); item language used by default; draft from
  stored recording; re-run keeps reviewed segments; **rights refusal** (external processing not allowed or
  unknown, restricted item) returns 409 with **no Sarvam call, no job, no file**; rights withdrawn after
  queueing stop the job before Sarvam; **bad responses** (no transcript, not JSON, 422) store nothing and
  verify nothing; the job is not auto-retried; **roles** (archivist, reviewer and admin allowed; curator and
  translation reviewer get 403; anonymous gets 401); non-audio upload, non-audio item, bad language, no
  recording, Sarvam not configured.
- Mutation check: marking drafts quote-verified, or removing the endpoint rights check, makes the success
  test and the refusal tests fail.
- Full backend suite on a private database (`archive_test_stt`, dropped afterwards): 355 passed, 1 skipped
  (real-Tesseract test; language data not installed on this machine).
- Web: `tsc -p tsconfig.json --noEmit` clean; `vitest run` 172 passed. This includes the i18n checks for
  key parity, Devanagari, placeholders and no hard-coded English. The new Hindi and Marathi strings were
  drafted by an agent and remain under the `agent_drafted_pending_native_review` flag.

## After the API image is rebuilt (not done here)

1. Rebuild and restart `api` and `worker`. The api command runs `alembic upgrade head`, which applies `0004`.
2. Make sure `ARCHIVE_SARVAM_API_KEY` is set in `.env` for both services.
3. Upload one short, rights-cleared test recording (the rights entry must have external processing
   `allowed`, and the item must not be restricted). Check that the segments arrive as drafts labelled
   "Machine draft", that `media.stt_draft` is in the audit log, and that nothing is quote-verified.
