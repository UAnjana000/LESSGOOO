# End-to-end run on real downloaded source excerpts

Running log of the live-path verification against the running `ambedkar-archive` stack
(image not rebuilt or restarted). Every entry is dated; the E2E test agent is not a human archivist.

Rights (recorded, unchanged): display, external processing and training allowed on the user's
academic permission stated 2026-09-27; no written document on file; NDLI links only; new items are
`public_online_only`.

## Progress log

- 2026-09-27 12:50 IST: State check. One-off container `ambedkar-archive-api-run-86bbc9cdec4d` (started 11:37 IST) is already resuming LangGraph thread `ingest-item-14` (item 14 `cad-1949-11-25-hi`, draft, 92 pages, access already `public_online_only`); left running, not duplicated. `busy_hofstadter` is another engineer's OCR engine eval (not touched). Docker CLI calls take about 60 s each on this host.
- 2026-09-27 13:10 IST: Found an earlier run's logs in `data/logs/e2e/` (steps 01-32, 11:34-12:49 IST). Verified live DB state (`data/logs/e2e/33_status.log`, read-only script `status2.py`): items 17-20 imported from `intake/baws_mea_cad1948.manifest.json` (jobs 4-7 done); items 12, 17, 18, 20 `published`; item 19 (Hindi, Kruti Dev) `in_review`, batch 12 failed so all 22 pages are in full review; item 13 `in_review` (batch 8 open, 18 full-review pages); item 14 `draft`, 90 of 92 pages processed, resume still running; dataset version 1 `e2e-real-2026-09-27` frozen 12:50 IST.
- 2026-09-27 13:06 IST: Resume of `ingest-item-14` had completed (`04_item14_resume.log`: 4920.6 s, 92 page outcomes, 90 `local|in_batch_review|gate=True`, 2 `sarvam|needs_full_review`, thread now at `await_review`); its `--rm` container is gone. Status re-checked (`37_status.log`): item 14 `in_review`, batch 14 open (90 pages, 18 sampled). Items 13 and 19 unchanged. `fervent_kepler` / `mystifying_carson` belong to other agents (not touched).
- 2026-09-27 13:20 IST: Review round 2 prep. `summarize_prep.py` over `38_review_prep.log`: Tesseract output for items 13, 14 and 19 is Devanagari on every page (no Kruti Dev mojibake in OCR; the legacy font only affects item 19's PDF text layer, which the pipeline did not select). Fetching images + candidates of the 54 pages to check for items 13/14 (`39_fetch_pages.log`, `pages/`).
- 2026-09-27 13:24 IST: Review round 2 through the staff API as `e2e-agent@demo.local`, every decision labelled "E2E test agent (agent review, not archivist review)" (`review_round2.py`, `41_review_round2.log`). All 34 sampled pages of batches 8 (item 13) and 14 (item 14) compared with their page images: every sampled page carries recurring local-Tesseract (hin) errors that also appear on unsampled pages (`40_junk_scan.log`): digit 1 read as '॥'/'।' (years, header page numbers), 'कौ' for 'की', 'सांविधान' for 'संविधान', embedded English quotations rendered as Devanagari junk. Batches 8 and 14 failed -> 78 + 90 pages to full review. Full-review pages approved after comparison with the scan: 171 (item 14 title page, Sarvam text corrected), 194 (item 14, Sarvam text verbatim), 297 (item 19 chapter title, Sarvam text corrected), 298 (item 19 blank verso, '[Blank page]'). Item 19's local OCR is Devanagari (the Kruti Dev problem is only in its PDF text layer, not selected), but at ~7% WER it is not accepted; its 20 other pages stay in full review.
- 2026-09-27 13:26 IST: Publication settled (`42_status.log`): items 12, 17, 18, 20 `published` (`public_online_only`); items 13 (96 pages in full review), 14 (90 in full review, 2 approved) and 19 (20 in full review, 2 approved) stay `in_review` and are not published, because publication needs every page approved. No publish job pending.

INGESTION COMPLETE 2026-09-27T13:26:54+05:30

- 2026-09-27 13:30 IST: Visitor search (`43_search.log`, raw JSON in `search/`): 6 queries (3 English, 3 Hindi), all HTTP 200, 20 results each, 0 LLM calls. English queries hit the expected passages (hero-worship -> item 18 p.60/item 12 passage 640; Castes in India endogamy -> item 17). Hindi queries have 0 keyword candidates (no Hindi text is published) and return English passages through the semantic leg only ('संविधान सभा' and 'लोकतंत्र में भक्ति' relevant; 'जातिप्रथा' weak, item 17 only at rank 3).
- 2026-09-27 13:40 IST: Ask (live gpt-4o-mini, `44`-`47_ask_*.log`, raw JSON in `ask/r2_*.json`). The first hero-worship request was answered by the api (200, 27.6 s) but the `proxy` container restarted at 13:31 IST mid-request (not caused by this agent) and the reply was lost; the retry was a cache hit (answered, cites passage 640, resolves). Hindi question: answered in Hindi, cites 642 (resolves), 1436/96 tokens. Unsupported question (1951 Hindu Code Bill resignation): `insufficient`, no model output, closest-item links resolve. 4 Nov 1948 'village' question: `insufficient` although item 20 passages 315-318 hold the answer (search `48_search_village.log` ranks them first): Ask retrieval defect (reported, not fixed). Live LLM calls so far: at most 4.
- 2026-09-27 13:36-13:45 IST: Withdrawal test round 2 on item 17 (`withdraw2.py`, `49`-`54_*.log`). Before: published version 2, 16/20 search hits, reader/passages/files/IIIF 200, Ask answered citing item 17 (passage 663; live call 5). Withdraw via staff API (agent action, labelled): immediately 0 search hits, reader/passages/files/IIIF 404, `/api/visitor/withdrawals` lists 17 (index version 20). After cleanup: Ask `insufficient`, cites only items 12/18 (cache miss, live call 6); cleanup job 15 verified `still_indexed=0`, `delivery_removed=20`. Restored with the operator script `restore_item.py` (the product has no restore endpoint; audit event `item.restore`, 20 delivery copies regenerated), republished via staff API (job 16) -> version 3. Restored: 16/20 search hits, reader 200, Ask answered citing item 17 passages 728/736 (live call 7). Old passage IDs 650-652 and file IDs 586-588 stay 404 after re-publication (IDs are not stable across versions). Final state: item 17 published, version 3. Live LLM calls in total: at most 7 of 8.
- 2026-09-27 14:18 IST: Citation / passage link check (`link_check.py`, `55_link_check.log`): 12 passage IDs (all 8 cited by round-2 Ask answers, item 17 v3 passages 728/736, item 20 passage 318, old item 17 passage 650). 11/12 pass (passage API 200, deep link `/item/<id>?page=<seq>&passage=<id>` matches the passage's item and page, SPA route 200, cited page image 200); 650 is 404 as expected after re-publication.
- 2026-09-27 14:20 IST: Item 17 re-publication changed the published passage set (new passage IDs, version 3), so dataset version 2 `e2e-real-2026-09-27-v2` was frozen with `archive.cli freeze-dataset` (`56_freeze_dataset_v2.log`): 641 passages, 11 items, same work-level splits as v1, sha256 `dc28fafc…cf827` (v1 `c4516587…8abd`). Training gate `training-gate-v1` not met (0 labelled pairs). No fine-tuning.
- 2026-09-27 14:27 IST: Sarvam Hindi OCR run started on the user's approval (14:17 IST; academic permission covers external processing). Rights re-checked per item through the staff API: items 13 (`lok-sabha-cad-hi-vol7`), 14 (`lok-sabha-cad-hi-vol11`) and 19 (`mea-baws-hi-khand01-2020`) all have `external_processing=allowed`, access `public_online_only`. Product path used: staff action `POST /api/staff/pages/{id}/retry-sarvam` -> worker job `sarvam_retry` -> `processing.run_sarvam` (Sarvam client `sarvam_ocr.SarvamDocAI`, raw Markdown kept as staff-only `sarvam_raw`, page stays `needs_full_review`). Driver `sarvam_run.py` (one page in flight, skips pages with an ok Sarvam candidate, up to 3 attempts on transient failure). 2-page trial (`57_sarvam_trial.log`): page 75 (item 13 title page, 20.2 s) and page 299 (item 19 p.3, 8.1 s) both ok; compared with the scans, both are faithful Devanagari (numerals correct, anusvara restored); only `##` heading markup and quote/dash normalisation differ.
- 2026-09-27 14:33 IST: Existing Sarvam batch left running (pid 31756, started 14:28:54 IST, `python sarvam_run.py --items 13 14 19` -> `58_sarvam_batch.log`). No second batch launched. At poll: 206 pages queued, page 75 skipped (trial candidate already present), pages 76-94 ok (~12 s each); still in flight. Review/approve held until this process finishes.
- 2026-09-27 14:51 IST: Same pid 31756 still running; no second batch. Item 13 (pages 75-170) all have an ok Sarvam candidate; item 14 in flight through page 185. Early visual checks (title 75, members 76, English-quote pages 79/85/94): Sarvam Devanagari and Latin quotations match the scans; Tesseract had ॥/। in years and English-as-Devanagari junk. `##` heading markup is the main systematic extra.
- 2026-09-27 14:56 IST: New agent took over (previous one timed out; not resumed). Same pid 31756 still alive, at page 208 (item 14), all `ok` so far, no failures in `58_sarvam_batch.log`; no second batch started. Starting agent review of item 13 (complete) with the existing `sarvam_check.py` / `sarvam_fetch.py` / `sarvam_review.py`.
- 2026-09-27 14:50 IST: Fixture purge on the live DB (separate agent; items 13, 14 and 19 and the Sarvam batch not touched). Keep-vs-delete plan written first (`purge_plan.md`, from the read-only inventory `61_purge_inventory.json` and the dry run `62_purge_dryrun.json`). Then `purge_fixtures.py --apply` ran in one transaction (`64_purge_apply.json`). It deleted the 14 `is_fixture` items (1-11 seed, 15/16/22 smoke uploads) and all their dependent rows, and unlinked 36 storage blobs (1 was already absent). A re-run was a no-op (`65_purge_rerun.json`). Deleted ids are in `purge_deleted.json`; the purge is recorded in audit event 701. Results are in "Live feature check after fixture purge" below.
- 2026-09-27 15:20 IST: The Sarvam Hindi batch (`sarvam_run.py`, pid 31756) has finished; the process is gone. Last log line 15:09:24 IST: 189 ok, 15 failed, 2 skipped (already had a candidate). All 15 failures are HTTP 402 "Insufficient credit balance" (pages 304-318, item 19, from 15:08:23). No Sarvam call was made on the old key after that.
- 2026-09-27 15:23 IST: The user replaced the Sarvam key in `.env` (~15:20). The running worker still holds the old key, and the 402 pages had been moved to `manual_transcription`, which `retry-sarvam` refuses. So `sarvam_retry_newkey.py` ran once in a one-off `docker compose run --rm --no-deps worker` container, with the key passed at start from `.env` (never printed). It mirrors the worker job (`default_fallback()` -> `processing.run_sarvam`) and only touches pages on items 13/14/19 that have no ok Sarvam candidate. 15 pages retried (304-318), 15 ok on the first attempt, 0 failures, no HTTP errors (`71_sarvam_newkey.log`). The api/worker/db/proxy were not restarted. Review results are in "Sarvam Hindi OCR" below.

## Results (E2E test agent, 2026-09-27)

All review decisions below are agent review by the E2E test agent (account `e2e-agent@demo.local`), not archivist review. No human quote verification was done in this round. Earlier rounds did record `verify-quotes` on 2 pages of item 18 (pages 293/294), and that was also agent-performed. No fine-tuning. No measured eval fields are claimed.

| Item | Final state | Pages |
|---|---|---|
| 12 CAD 25 Nov 1949 (en) | published, version 1, `public_online_only` | 62 approved |
| 13 CAD 4 Nov 1948 (hi) | in_review, not published | 96 in full review (batch 8 failed) |
| 14 CAD 25 Nov 1949 (hi) | in_review, not published | 90 in full review (batch 14 failed), 2 approved (171, 194) |
| 17 BAWS Vol. 1 Castes in India (en) | published, version 3 (withdrawn and restored in this round) | 20 approved |
| 18 BAWS Vol. 13 speech (en) | published, version 1 | 13 approved |
| 19 BAWS Hindi Khand 1 (Kruti Dev PDF) | in_review, not published | 20 in full review (batch 12 failed), 2 approved (297, 298) |
| 20 CAD 4 Nov 1948 (en) | published, version 1 | 45 approved |

Visitor checks on https://localhost:8443:
- Search: 6 queries (3 English, 3 Hindi), all 200 with 20 results and 0 LLM calls. English queries find the expected passages. Hindi queries get no keyword candidates (no Hindi text is published) and return English passages through the semantic leg only.
- Ask: at most 7 live gpt-4o-mini calls (1 lost reply after a `proxy` restart, not caused by this agent). Results: hero-worship question answered with a citation (cache hit); Hindi question answered in Hindi with a citation; unsupported question (1951 Hindu Code Bill) correctly `insufficient`; 4 Nov 1948 'village' question wrongly `insufficient` (see bugs). Item 17 answers: before withdrawal answered, citing item 17; during withdrawal `insufficient` with no item 17 citation; after restore answered, citing item 17 again. Paraphrase support was not human-graded.
- Links: 11/12 cited passages resolve end to end; the 1 failure is an expected 404 for a pre-withdrawal passage ID.
- Withdrawal: item 17 was gone from search, reader, passages, files and IIIF immediately and from Ask after cleanup. It was restored via the operator script and republished (version 3). Final state: published.
- Dataset: v2 frozen (641 passages, 11 items). Training gate not met.

Bugs found (reported, not fixed):
1. Ask retrieval recall. "When introducing the Draft Constitution on 4 November 1948, what did Dr. Ambedkar say about the Indian village?" returns `insufficient`. The hybrid + cross-encoder rerank in `ask/graph.py::retrieve_passages` puts item 12 passages (566, 393, 614) first, although visitor search ranks item 20 passages 315-318 first for 'sink of localism' and passage 318 contains the answer (`47_ask_village.log`, `48_search_village.log`).
2. Local Tesseract Hindi (`hin`) on CAD Hindi and BAWS Hindi scans shows error patterns that pass the local gate, so sampled batches cannot be accepted (`40_junk_scan.log`, `41_review_round2.log`):
   - the digit 1 is read as '॥' or '।' ('॥948', '॥949', '॥935', and header page numbers such as '478' for 4178);
   - 'की' is read as 'कौ';
   - 'संविधान' is read as 'सांविधान' in running headers;
   - embedded English quotations are rendered as Devanagari junk (for example pages 85, 166, 181, 194, 248);
   - item 19 drops anusvara systematically (~7% WER, round 1).

   The gate did not flag most of these pages (78 of 96 in item 13, 90 of 92 in item 14). Sarvam read pages 171, 194 and 297 correctly.
3. Review decisions are recorded with role `archivist` whatever the caller is (`ingest/review.py::_approve_text`, `decide_batch`, `verify_page_quotes` hard-code it), so agent review is only distinguishable from archivist review by the reason text.
4. No restore endpoint for withdrawn items, and passage and file IDs change on re-publication, so citations and deep links saved before a withdrawal break permanently (passage 650, files 586-588 now 404).
Not finished: items 13, 14 and 19 need a full human (or Sarvam-assisted) review of 206 pages before they can be published. The Sarvam fallback was not run over them in this round, to avoid unapproved external spend. Hindi search and Ask can't be tested against Hindi text until then.

2026-09-27 15:06 IST, Sarvam batch progress: `sarvam_run.py --items 13 14 19` (PID 31756, started 14:28 IST) is still running. It has done 181 of 206 pages (all `ok`, no failures; page 75 skipped because it already had a candidate). The last page logged was page id 253 at 15:05:49 IST, about 12 s per page, so it should finish near 15:11 IST. Review and publication have not started.

2026-09-27 15:10 IST, batch finished at 15:09:24 IST (2428.7 s): 189 `ok`, 2 skipped because they already had a candidate (pages 75, 299), 15 `failed`. The failures are pages 304-318, which all returned Sarvam HTTP 402 `insufficient_quota_error` ("Insufficient credit balance") from 15:08 IST. The Sarvam account is out of credit. The product moved those 15 pages to `manual_transcription`, so a later retry has to re-queue them by hand.

## Live feature check after fixture purge

2026-09-27, 14:50-15:15 IST, on https://localhost:8443 (live `ambedkar-archive`, no rebuild or restart). The E2E test
agent (AI) did these checks; they are agent checks, not archivist review. There was no human quote verification and no
native-speaker review. Evidence files are in `data/logs/e2e/feature_check/` (summary in `results.json`). The purge files
are in `data/logs/e2e/` (`purge_plan.md`, `purge_deleted.json`).

### Fixture purge

The product has no hard-delete path (withdraw keeps rows and lists the item publicly), so a one-off transactional
script, `purge_fixtures.py`, ran in the api container. It defaults to a dry run. With `--apply` it refuses to run if
any real item is flagged as a fixture or if a real item's page, passage or file counts change inside the
transaction. It unlinks only blobs that no surviving `file_version` row references.

- **Deleted** (all `archival_item.is_fixture = true`):
  - Items 1-11: the `seed-fixtures` items (`fx-essay-reading-rooms`, `fx-lecture-education`, `fx-lecture-tank`,
    `fx-proceedings-1`, `fx-pamphlet-hi`, `fx-petition-mr`, `fx-manuscript-note`, `fx-photo-reading-room`,
    `fx-talk-audio`, `fx-restricted-memo`, `fx-online-only-report`).
  - Items 15, 16 and 22: smoke-test uploads under the fixture rights record.
  - Dependent rows: 13 pages, 12 OCR results, 20 passages with embeddings, 7 review batches, 4 media segments,
    6 derivatives (3 summaries and 3 espeak narrations), 2 translations, 37 file versions, 32 review decisions,
    11 timeline events, 1 story, 24 knowledge nodes, 22 knowledge edges, 1 QR list, 3 jobs, LangGraph checkpoints for
    the 14 fixture threads, fixture rights records 1-3, 12 Ask logs built only on fixture passages (ids 1-10, 20, 24),
    and the answer cache.
  - Storage: 36 blobs unlinked; 1 was already absent after item 15's earlier withdrawal cleanup.
- **Kept:**
  - Real items 12, 17, 18 and 20 (published) and 13, 14 and 19 (Hindi, `in_review`).
  - Item 21: the E2E duplicate-check draft with real rights, `restricted`, and no pages. It is ambiguous, so it was kept.
  - Rights records 4-10.
  - The whole audit log: it is append-only, so the 81 `fixture-seed` events stay, and the purge itself is event 701.
  - Dataset versions 1 and 2.
  - Ask log 18.
  - The `debates` machine-translation setting.
  - Staff accounts.
  - Repo fixtures, tests and seed commands, and the source PDFs in `data/incoming/`.
- **Verified after the purge** (`feature_check/purge_verify.json`, `probe_before/`, `probe_after/`):
  - Zero fixture items, fixture rights records, seeded review decisions or fixture curation rows remain.
  - No citation points at a missing passage, and there are no orphan files.
  - Before the purge, fixture ids appeared in the catalogue, both searches, the timeline, stories, map, signage, the
    exhibit manifest and the reader. After it, all of those show only items 12, 17, 18 and 20, and
    `/api/visitor/config` reports `fixture_items_visible: 0`. Fixture reader, passage, file and story URLs return 404.
- **Caveat:** dataset versions 1 and 2 are frozen, checksummed manifests. Each one still lists 12 fixture entries next
  to 629 real entries. They were not edited. A clean dataset needs a new freeze (not done).

### Feature results

| Feature | Result | Evidence (`feature_check/`) |
|---|---|---|
| Home and catalogue (only real items) | pass | `catalogue.json`, `ui/01-home.png` |
| English search | pass | `search.json`, `ui/02-search-en.png` |
| Hindi search | pass, limited | `search.json`, `ui/03-search-hi.png` |
| Ask: answerable English question | pass | `ask_answerable.json`, `citation_60.json` |
| Ask: unanswerable question | pass | `ask_unanswerable.json` |
| Ask: Hindi question | **fail** | `ask_hindi.json`, `search_hindi_ask_question.json` |
| Ask cites no deleted fixture ids | pass | `ask_*.json`, `purge_verify.json` |
| Ask UI, and its citation opens the reader | pass (cache hit) | `ui_ask.jsonl`, `ui/11-ask-ui.png`, `ui/12-ask-citation-reader.png` |
| Citation, passage, page image and IIIF | pass | `citation_60.json` |
| Item reader | pass | `reader.json`, `ui/04-reader-item18-p11.png` |
| Explore: Timeline, Stories, Connections | pass, empty | `routes.json`, `ui/05-timeline.png`, `ui/06-stories.png`, `ui/07-map.png` |
| Constitution | **fail** | `constitution_diagnosis.json`, `ui/08-constitution.png` |
| Signage (`/display`) | pass, empty | `routes.json`, `ui/09-signage-display.png` |
| Language switch EN/HI/MR | pass (UI loads) | `ui_lang.jsonl`, `ui/10-lang-*.png` |
| Staff login and review queue | pass | `staff.json`, `ui_staff.jsonl`, `ui/14-staff-review-queue.png` |
| Narration | pass | `narration.json` |
| Rights: restricted item not in visitor search | pass, limited | `catalogue.json` |

Notes on the results:
- **Home and catalogue:** the home page shows Writings 1, Speeches 1 and Debates 2, with no stories.
  `/api/visitor/items` returns exactly items 12, 17, 18 and 20.
- **English search:** "hero-worship" puts item 12 passage 640 and item 18 passage 59 first. "endogamy is the essence of
  caste" returns only item 17 (passages 738 and 740). Both used 0 LLM calls.
- **Hindi search:** "संविधान सभा" and "जाति प्रथा" each return 200 with 20 real results and 0 LLM calls. They are English
  passages from the semantic leg only, because no Hindi text is published yet.
- **Ask, answerable** (live gpt-4o-mini, 1449/46 tokens, `answered`): "Dr. Ambedkar warned that in politics,
  hero-worship or bhakti is a sure road to degradation and to eventual dictatorship." It cites passages 60 and 59 (item
  18, pp. 11 and 10), which both resolve. Passage 60 reads "But in politics, Bhakti or hero-worship is a sure road to
  degradation and to eventual dictatorship". This is an agent comparison, not human grading.
- **Ask, unanswerable** ("…Poona Pact negotiations with Gandhi in 1932?"): `insufficient` with no model call (0
  tokens), no answer text and no invented quote. The message reads "The archive does not contain enough to answer this.
  These are the closest items to browse." The closest-source links (588, 335, 391) resolve to real items.
- **Ask, Hindi** (live, 890/6 tokens): `insufficient`, although the English corpus answers it (see bugs 5 and 6).
- **Ask UI:** the UI question returned the saved answer (a cache hit, no LLM call), and its citation opened
  `/item/18?page=11&passage=60`.
- **Citation chain for passage 60:** the passage API returns 200. The deep link `/item/18?page=11&passage=60` matches
  the passage's item and page, and the SPA serves it. The page image (file 344) is a JPEG, and IIIF `info.json`
  (882×1332) and the IIIF image both return 200.
- **Reader:** the scan for printed page 1216 renders, with passage 60 highlighted beside it. The "Quote-verified
  against the original" chip there comes from an earlier agent-performed check, not a human one.
- **Explore and Signage:** these pages load and show no fixtures. Their APIs return empty lists (`[]`, `{"nodes": [],
  "edges": []}`, `{"timeline": [], "story": null}`). The pages show only a heading, with no empty-state message.
- **Language switch:** clicking HI, MR and EN changes `<html lang>` and the navigation labels.
- **Staff:** `e2e-agent@demo.local` signed in (roles archivist and reviewer). The review queue lists item 13 (96
  pages), item 14 (90) and item 19 (20), with no fixtures. Nothing was approved or published.
- **Narration:** one Sarvam TTS call at about 15:00 IST, which was before the account ran out of credit at 15:08. It
  used staff `POST /api/staff/narration` for passage 63 (item 18 p. 11, 264 characters, `public_online_only`,
  external processing allowed). The result is generator `bulbul:v3/ritu`, labelled "Synthetic narration", as
  `audio/mp4` file 817 (113 KB). The visitor narration endpoint for that passage went from 404 to 200, and the reader
  shows the "Synthetic narration" label.
- **Rights:** item 21 (`restricted`, draft) is not in the catalogue or search, and its reader returns 404. It has no
  text, and the only restricted item with text (fixture item 10) was deleted, so text leakage from a restricted item
  could not be tested. The in-review Hindi items 13, 14 and 19 also return 404 in the visitor reader.

Totals: live gpt-4o-mini calls were 2 (answer logs 35 and 37). Log 36 made no model call, and logs 38-40 were UI cache
hits. There was 1 Sarvam TTS call.

### Bugs found in this check (reported, not fixed)

5. **Hindi Ask misses an answer the corpus holds.** Repro: POST `/api/visitor/ask` with "डॉ. आंबेडकर ने राजनीति में
   भक्ति या नायक-पूजा के बारे में क्या चेतावनी दी?" (`hi`). It returns `insufficient`, citing passages 588, 31 and
   485, while the English version of the question is answered from passages 59 and 60. Visitor search on the same
   Hindi text (no LLM) doesn't rank 59, 60 or 640 in its top 20. The short phrase "राजनीति में भक्ति" ranks 640 third
   and 60 sixth. The earlier Hindi question that succeeded included "25 नवम्बर 1949". This is cross-language
   retrieval recall for long Hindi questions against an English-only corpus, and is related to bug 1.
6. **Ask overrides the visitor's language.** The same request with `language: "hi"` is logged and answered as `mr`
   (answer log 37 has `language = mr`). `search/langid.py::detect_language` (Lingua, en/hi/mr) most likely picks
   Marathi because of the Marathi-style spelling "आंबेडकर", and the result replaces the explicit choice.
7. **Constitution is not deployed on the live stack.** Repro: open https://localhost:8443/constitution. The page shows
   React Router's developer screen, "Unexpected Application Error! 404 Not Found".
   - `/api/visitor/constitution` returns 404.
   - The served bundle `/assets/index-yji_3htR.js` has 0 mentions of "constitution".
   - The live DB is at alembic `0001`, with no `constitution_article` or `constitution_link` tables.
   - The repo has the route (`web/src/App.tsx`), so the live images are older than the repo.
   - The router has no fallback `errorElement`, so any unknown route shows the developer screen.
8. **Ask cost:** the response and answer log report `cost_usd: 0.0` for a live answered call (1449 in / 46 out tokens).
9. **Cache-hit analytics:** Ask logs for cache hits (38-40) have no citation rows.
10. **Empty pages:** Timeline, Stories and `/display` show a blank page instead of an empty-state message.
11. **Narration reads the running header aloud.** Approved passage text keeps the printed running header (passage 63
    ends "1216 DR. BABASAHEB AMBEDKAR : WRITINGS AND SPEECHES"), so the synthetic narration speaks it.
12. **Service-worker console error.** Every page logs "An unknown error occurred when fetching the script.". `/sw.js`
    returns 200, but no service worker registers (`console_error_trace.json`). This is most likely Chromium refusing
    service workers under the untrusted Caddy internal CA, so it's environmental, but that isn't confirmed. The
    offline exhibit mode could not be exercised.
13. **Review queue row count:** the staff review table rendered 200 rows while the API lists 206 queued pages. Not
    investigated.

## Timeline and archive fit

Checked 2026-09-27 (timeline-fit agent) against the live stack. Evidence is in `data/logs/e2e/timeline_fit/`:
`01_items_live_sql.txt` (read-only SQL), `02_visitor_*.json`, `probe_live.json` (from `probe.py`),
`03_live_search_date_filter_500.txt` and `proposed_timeline_events.json`.

**Item metadata is already right. No live item was edited.** Manifest import copied every date and collection onto the
item rows. The source is the `date_start` field in `intake/baws_mea_cad1948.manifest.json` or
`intake/cad_lok_sabha.manifest.json`.

| Item | Manifest key | Lang | State | Collection (archive) | Source | Date | Pages |
|---|---|---|---|---|---|---|---|
| 12 | `cad-1949-11-25-en` | en | published | debates (CAD) | Lok Sabha Secretariat, Vol. XI | 1949-11-25 | 62 |
| 13 | `cad-1948-11-04-hi` | hi | in review | debates (CAD) | Lok Sabha Secretariat, Vol. 7 | 1948-11-04 | 96 |
| 14 | `cad-1949-11-25-hi` | hi | in review | debates (CAD) | Lok Sabha Secretariat, Vol. 11 | 1949-11-25 | 92 |
| 17 | `baws-en-vol01-castes-in-india` | en | published | writings (BAWS) | Dr. Ambedkar Foundation / MEA, Vol. 1 | 1916-05-09 | 20 |
| 18 | `baws-en-vol13-speech-1949-11-25` | en | published | speeches (BAWS) | Dr. Ambedkar Foundation / MEA, Vol. 13 | 1949-11-25 | 13 |
| 19 | `baws-hi-khand01-bharat-mein-jatipratha` | hi | in review | writings (BAWS) | Dr. Ambedkar Foundation / MEA, Khand 1 | 1916-05-09 | 22 |
| 20 | `cad-1948-11-04-en` | en | published | debates (CAD) | Lok Sabha Secretariat (Digital Sansad), Vol. VII | 1948-11-04 | 45 |

The Castes in India date comes from the manifest's `date_text`: "Paper read 9 May 1916 at Columbia University; published
in Indian Antiquary, May 1917". Item 12's date is `date_start` in `cad_lok_sabha.manifest.json`.

**Visitor API (live), all checks in `probe_live.json`:**
- The catalogue lists 17, 20, 12, 18 in date order.
- Collection browse gives debates = {12, 20}, writings = {17}, speeches = {18}, and Home counts match.
- The in-review items 13, 14 and 19 return 404 in the reader.
- None of the 13 searches returned 13, 14 or 19. The searches were 4 English, 5 Hindi, 3 date-filtered and 1
  collection-filtered.

**Gaps found:**
1. **The timeline is empty.** The visitor timeline shows only curator-approved `timeline_event` rows (spec §5.3, and
   §8 says it is curated, not AI-built). The fixture purge left none. The agent staff account has no `curator` role,
   so no event was created. `proposed_timeline_events.json` holds three draft bodies for a curator to check, POST and
   approve:
   - 1916-05-09: items 17 and 19
   - 1948-11-04: items 20 and 13
   - 1949-11-25: items 12, 18 and 14

   The in-review items are included on purpose, because the timeline hides them until they are published.
2. **Date-range search returns 500 on the live image.** `visitor.search` passed `date_from` and `date_to` as strings,
   so Postgres fails with `date >= character varying`. The repo already types them as `dt.date` and tests it in
   `test_db_visitor_features.py`. It needs an api rebuild.
3. **The live image is older than the repo.** DB is at alembic `0001`, so there are no subjects, people or places,
   and no metadata revisions. `/api/visitor/facets` returns 404, `/items?language=` is ignored, and
   `PUT /api/staff/items/{id}/metadata` doesn't exist. Facets will stay empty for real items until they are tagged
   after the upgrade.

**Changes made:**
- New test `backend/tests/test_db_intake_manifest_dates.py`. It imports both real manifests (metadata only) through
  `intake.import_manifest` and checks each item's collection, date fields, languages, volume and source institution.
  Red/green check: 3 passed; with `create_item` made to drop `date_start`, it failed; restored, 3 passed, plus
  `test_db_curation.py` for 8 in total.
- `web/src/i18n.ts`: the `debates` collection label is now "Constituent Assembly Debates" (hi "संविधान सभा की
  बहसें", mr "संविधान सभा चर्चा"), as spec §5 names it on Home. Vitest: 172 passed. It needs a web rebuild.
- 2026-09-27 15:28 IST: `ARCHIVE_SARVAM_API_KEY` in `.env` was replaced around 15:20 IST. Status check: no
  `sarvam_run.py` process is running, and `58_sarvam_batch.log` still ends at the 15:09:24 `done` line. The
  running worker container was started earlier and still has the old key, so the retry of the 15 failed pages
  (304-318) will run in a fresh process that reads the current `.env`. Pages that already have an ok Sarvam
  candidate are skipped. Log: `data/logs/e2e/59_sarvam_retry.log`.
- 2026-09-27 15:37 IST: no Sarvam process is running and none was started. The retry of pages 304-318 with the new
  key already finished at 15:23-15:24 IST (15 ok, 0 failed; `71_sarvam_newkey.log`). The idempotency check in
  `59_sarvam_retry.log` (15:29:47 IST) finds 0 pages left to retry on items 13, 14 and 19, so no Sarvam calls were
  made. Page review has not been done yet.
- 2026-09-27 15:52 IST: Sarvam review (E2E test agent, agent review, not archivist review), batch 1. Live status (`77_status.log`): item 13 6 approved / 90 in review, item 14 2 / 90, item 19 2 / 20; every unapproved page has an ok Sarvam candidate. Offline checks (`sarvam_flags2.py` -> `78_flags.log`): 0 pages with danda inside digits; low Devanagari share on item 13 pages 78-80, 82, 101, 102, 104 (member lists, English quotations, tables); Bengali digit U+09EA in headers of pages 83 and 302; Devanagari English loanwords to check on 36 pages. Item 13 stratified sample compared with the scans: pages 77, 84, 95, 100, 110, 118, 130, 140, 150, 158, 170 all faithful; only defects are one extra ']' in page 84's header, stray `##` heading markers and HTML table markup (page 100). No decisions submitted yet.
- 2026-09-27 16:00 IST: Sarvam review batch 2 (agent review). Item 14 stratified sample compared with the scans: pages 173, 180, 190, 198, 205, 215, 225, 232, 245, 262 all faithful, printed typos kept (e.g. 'संधोधन' on 190), only stray `##` markers. Page 245's English-quote flag is a false positive: the Hindi edition prints the Bryce and Franklin quotations in Hindi. No decisions submitted yet.

## Sarvam Hindi OCR

Recorded 2026-09-27 15:58 IST by the E2E test agent (agent review, not archivist review). Items 13 (CAD Hindi vol. 7,
96 pages), 14 (CAD Hindi vol. 11, 92 pages) and 19 (BAWS Hindi khand 1, 22 pages): 210 pages in total.

**Batch and credit.**

| Run | Pages sent | ok | failed | Notes |
| --- | --- | --- | --- | --- |
| `sarvam_run.py`, old key (14:28-15:09 IST, `58_sarvam_batch.log`) | 204 | 189 | 15 | 2 more skipped (candidate already present). All 15 failures HTTP 402 "Insufficient credit balance", pages 304-318, from 15:08:23. |
| `sarvam_retry_newkey.py`, new key (15:23-15:24 IST, `71_sarvam_newkey.log`) | 15 | 15 | 0 | Only pages without an ok candidate; first attempt each; no HTTP errors. |

After both runs, 209 of 210 pages have an ok Sarvam candidate. The remaining page, 298, was already approved from
another engine. No page is left without a Sarvam candidate because of the credit stop.

**Automated flags** (`sarvam_script_flags.py` -> `74_script_flags.log`, over all 209 stored texts):
- 0 pages with a danda inside a number.
- 2 pages with a non-Devanagari Indic character: the Bengali digit '৪' in place of the page number 8, on page 83
  (item 13) and page 302 (item 19).
- 60 pages carry Markdown/HTML markup (`##` headings, `[^n]` footnote markers, `<table>`).

**Visual review.** A stratified sample of 30 pages was compared with the delivery images: 10 from item 19, 9 from
item 13 and 9 from item 14, plus the flagged pages 83, 104, 107, 182 and 183. Decisions went through
`POST /api/staff/pages/{id}/review` with the label "E2E test agent (agent review, not archivist review), Sarvam OCR
candidate" (`76_decisions.jsonl`, `76_escalations.jsonl`, results in `76_review_apply.log`).
- **Approved: 24.** Item 19: 299, 300, 301, 303, 304, 305, 307, 310, 314, 318. Item 13: 89, 94, 107, 121, 141, 153,
  170. Item 14: 172, 182, 192, 200, 220, 245, 262. 18 were approved verbatim. The other 6 were `correct` actions on
  299, 300, 314, 121, 172 and 245, and the only change was removing the `##` heading markers and `[^n]` footnote
  markers. Sarvam turns the scans' curly quotes and en-dashes into straight ones; that is accepted.
- **Left in review with a note: 6.**
  - 302 and 83: the Bengali digit '৪' in place of the page number 8.
  - 306: "विधुओं के लिए", where the scan prints "विधुरों के लिए". This is a real word error.
  - 104: the HTML table's row and column structure doesn't match the scan (the 40 and 89 totals are attached to the
    wrong rows).
  - 183: the scan's "सी 63।)" became "सी 63 1)", and the printed misprint "खड 2" was silently changed to "खंड 2".
  - 230: the delivery image can't show for certain whether the print reads 'आपति' or 'आपत्ति'.
- Not destroyed: page 107's "व्हेन दी बिल इज सो ओथेन्टिकेटेड" and page 182's "(52 और 53 वीआईसीटी, सी 63।)" are
  printed that way in the scan. Latin English quotations (for example pages 83, 89, 94, 104 and 107) come through as
  Latin.
- Error rate in the sample: 6 of 30 pages (20%) are not exact matches; 3 of the 30 have content errors (104, 183 and
  306). The rest of the pages have not been compared individually, so they cannot be bulk-approved on this evidence.

**Page status after review** (`77_final_counts.log`, 15:55 IST):

| Item | Pages | Approved | In review |
| --- | --- | --- | --- |
| 13 | 96 | 13 | 83 |
| 14 | 92 | 9 | 83 |
| 19 | 22 | 12 | 10 (302, 306, 308, 309, 311, 312, 313, 315, 316, 317) |

**Page status update** (`84_decisions_snapshot.log`, 16:12 IST, after batches 3 and 4b below):

| Item | Pages | Approved | Left in review |
| --- | --- | --- | --- |
| 13 | 96 | 21 | 75 (83 and 104 escalated; 73 not yet decided) |
| 14 | 92 | 17 | 75 (183 and 230 escalated; 73 not yet decided) |
| 19 | 22 | 20 | 2 (302 Bengali-digit page number, 306 word error; both escalated for an archivist) |

Every item 19 page except 302 and 306 was compared with its scan. Items 13 and 14 were not bulk-approved,
because their samples contain real errors: item 13 page 104 (table structure) and item 14 page 183 (a danda read as
'1', and a misprint silently corrected). Their undecided pages stay in review. Still unchecked are the flagged pages:
item 13 low Devanagari share 78-80, 82, 101, 102, plus loanword-flag pages; item 14 pages 240, 241, 247 and 256.

**Publication.** None. No item has every page approved, so nothing was published as `public_online_only`. No Hindi
search or Ask checks were run, no dataset version was frozen, and there was no fine-tuning.

**Warning (concurrent agent).** At 15:54 IST another agent wrote `80_decisions_item19.jsonl`. It would bulk-approve
item 19 pages "not individually compared". That includes page 306, which has a verified word error, and page 302,
where its fix of the page number would itself be fine. Do not apply that file as written. Page 306 needs
"विधुओं" corrected to "विधुरों", and pages 308, 309, 311, 312, 313, 315, 316 and 317 need an actual comparison with
the scans before item 19 can be published.

**Bugs found.**
1. `sarvam_ocr.SarvamDocAI._request` treats every 4xx except 429 as `SarvamRejected`. So an HTTP 402 (out of
   credit) sends the page to `manual_transcription` with `ocr_route=manual`, when it should stay retryable in
   `sarvam_pending`. `retry-sarvam` then refuses those pages with a 409 ("page is not waiting for OCR fallback"). The
   15 pages needed the one-off retry script. 401, 402 and 403 should be treated as unavailable or retryable, not as
   content rejection.
2. The worker reads the Sarvam key only when the container starts. A key rotated in `.env` is not used until the
   worker is recreated, and nothing reports that the key in use is stale.
3. Sarvam's output leaks other scripts and markup into Devanagari text: the Bengali '৪' for 8, `##` and `[^n]`
   Markdown, and HTML `<table>` with wrong spans. None of this is stripped before review. Reviewers need a
   script-mix check and a markup view.
- 2026-09-27 16:09 IST: Sarvam review batch 3 (E2E test agent, agent review, not archivist review). Another reviewer applied 24 approvals and 6 escalations at 15:55 IST (`76_review_apply.log`): escalated item 13 pages 83 and 104, item 14 pages 183 and 230, and item 19 pages 302 and 306. Page 306 has a wording mismatch against the scan, so the item 19 sample is not clean and no item 19 page was bulk-approved. The escalated pages were not re-approved. This agent compared item 19 pages 302, 305, 308, 309, 311, 312, 314 and 317 with the scans. All are faithful apart from page 302's Bengali-digit page number, which was already escalated. Submitted via `sarvam_review_safe.py`, which skips approved pages and pages that already have an agent decision (`82_review_apply.log`): 308 correct (footnote markers removed), 309, 311, 312 and 317 approved. Snapshot `81_decisions_snapshot.jsonl`. Item 19 is now 17/22 approved; 313, 315 and 316 are still to compare, and 302 and 306 wait for an archivist. Not published.
- 2026-09-27 16:10 IST: Item 19 only, Sarvam review batch 4 (E2E test agent, agent review, not archivist review). Live read-only status (`82_item19_status.log`): item 19 is 17/22 approved; in review: 302 and 306 (escalated earlier for the Bengali-digit page number and the word error, wait for an archivist), 313, 315 and 316 (no decision yet, no automated flags; 313 and 316 carry Markdown markers). Earlier batches already compared 17 item 19 pages with the scans (299-312, 314, 317, 318), so this pass reuses them and compares only 313, 315 and 316. Items 13 (13/96) and 14 (9/92) counts read only; not reviewed in this pass. No Sarvam calls.
- 2026-09-27 16:13 IST: Sarvam review batch 4b (E2E test agent, agent review, not archivist review; this is a different agent from the one that wrote the 16:10 line). Item 19 pages 313, 315 and 316 were compared with the scans. All three are faithful, and printed typos such as 'ब्राह्मणें' on 315 are kept. They were submitted at 16:11 IST (`83_review_apply.log`): 313 and 316 as correct (only the footnote markers removed), 315 approved. The next agent must not re-decide them. The previous agent's recorded, unsubmitted sample checks were also applied: item 13 pages 77, 95, 110, 118, 130, 140, 150 and 158, and item 14 pages 173, 180, 190, 198, 205, 215, 225 and 232 (`83_review_apply.log` and `83_review_apply_b.log`). Page 84 (extra ']' in the header) and page 100 (HTML table not checked) were not submitted. `80_decisions_item19.jsonl` was never applied and is superseded by `82_` and `83_decisions_*`. Live counts (`84_decisions_snapshot.log`): item 13 21/96, item 14 17/92, item 19 20/22 (only escalated 302 and 306 remain). Nothing published.
- 2026-09-27 16:23 IST: Item 13 sample review (E2E test agent (agent review, not archivist review), Sarvam OCR candidate). The counts come from the 16:12 IST snapshot in `84_decisions_snapshot.log`. Item 13 has 21 approved, 2 escalated (83 and 104) and 73 undecided. Item 14 has 17 approved, 2 escalated (183 and 230) and 73 undecided. This agent compared 8 undecided item 13 pages, already fetched read-only in `85_item13_fetch.log` and `pages13/`, with their scans. Pages 78, 79, 80 and 120 match; page 80 keeps the printed typo 'notificaton'. Pages 82, 101, 102 and 145 do not match. On page 82, the printed misprint 'Asembly' was silently corrected to 'Assembly'. Page 101 has 'पुदूकोटाई' where the scan prints 'पुद्दूकोटाई', and its table covers 10 rows where the scan groups 15 states. Page 102 has 'जम्बूधोडा' where the scan prints 'जम्बूघोडा', an extra ']' in the header, and a table with the section heading and the '4' in the wrong cells. Page 145 has 'प्रतिनिधिधान' where the scan prints 'प्रतिनिधान'. Half of this sample, mostly the table and English-heavy pages that were flagged, fails, so item 13 must not be bulk-approved. No decisions were submitted, no Sarvam calls were made, item 19 was not touched, and nothing was published. Record: `data/logs/e2e/item13_review_sample.json`.
- 2026-09-27 16:28 IST: The 16:23 IST item 13 judgments were written to the database through the staff review API as `e2e-agent@demo.local`. Each decision is labelled "E2E test agent (agent review, not archivist review), Sarvam OCR candidate" and carries its page-specific note. Before each write, `item13_apply.py` re-read the page and would have skipped it if it was not in item 13, was already approved, already had a decision, or had a different Sarvam candidate id. None was skipped. Pages 78, 79, 80 and 120 are approved with the Sarvam text verbatim (decisions 251-254). Pages 82, 101, 102 and 145 are escalated and stay in `needs_full_review` for an archivist (decisions 255-258). A read-back confirmed these results. Logs: `86_decisions_item13.jsonl`, `86_item13_dryrun.log`, `86_item13_apply.log` and `86_item13_verify.log`. No other pages were reviewed, items 14 and 19 were not touched, no Sarvam calls were made, nothing was bulk-approved and nothing was published.
