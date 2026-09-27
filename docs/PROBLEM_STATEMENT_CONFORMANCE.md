# Problem-statement conformance

Of the 13 software requirements in the problem statement, **5 are verified and 8 are partial**. None is missing, and none is purely hardware-deferred. The partial rows are held back by three kinds of gap: measurements that have not been run (search quality, OCR gate calibration), content that cannot be used until its rights are decided (the Dr. Ambedkar Foundation volumes, the Constituent Assembly Debates), and parts with no automated test (narration, the web UI's interactions, a real `pg_dump` backup run). Kiosk enclosures, tablets, lock-task mode, the camera station and smart-display hardware are out of scope; kiosk and signage software is in scope.

This document maps each requirement to the spec, the code and the evidence. The per-row detail for every spec ID lives in `docs/REQUIREMENTS.md`; this document routes to it and does not repeat it.

## Status legend

| Status | Meaning |
| --- | --- |
| verified | Every P1 part of the requirement is exercised by a test that was run from the host and passed. Backend tests use test doubles (hash embedder, lexical reranker, scripted fake LLM, fake Tesseract and Sarvam), so "verified" covers workflow and rule logic, not live providers or model quality. |
| implemented-unverified | Code exists and was read, but no passing test covers it. |
| partial | Some P1 parts are verified; others are implemented-unverified, unmeasured, or blocked on rights. |
| missing | No code exists. |
| hardware-deferred | Needs hardware that is out of scope for this software work. |

Seeded fixture approvals (actor `fixture-seed`) are never counted as human review. All demo content is synthetic and labelled as such (`fixtures/README.md`).

## Requirement table

Spec references are to the architecture spec's §2 traceability table unless stated. P1 is the prototype, P2 is a later prototype stretch, PROD is production only.

| # | Requirement | Spec | Pri | Implementing files | Evidence | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | AI-powered semantic search and intelligent knowledge mapping | TR-08, TR-09, TR-10 | P1 | `backend/archive/search/hybrid.py`, `backend/archive/api/visitor.py` (`/search`, `/map`), `backend/archive/api/staff.py` (`/map/nodes`, `/map/edges`) | Hybrid search: `test_staged_version_is_invisible_until_switch`, `test_restricted_items_hidden_even_when_published`. Map: `TestKnowledgeMap::test_only_approved_nodes_and_edges_between_visible_items_are_shown`, `test_map_curation_needs_curator_role_and_valid_nodes`. Semantic and cross-lingual quality are UNMEASURED (TR-09). | partial |
| 2 | Full-text and summarized access to writings and speeches | TR-11, TR-13 | P1 | `visitor.py` (`/items/{id}`), `web/src/pages/Item.tsx`, `staff.py` (`/summaries/draft`, derivative review) | `TestReviewedSummaries` (3 tests), `TestManuscripts::test_published_manuscript_shows_scan_beside_reviewed_transcription`. The 3 demo summaries are `fixture-seed` approvals, not human reviews. The reader UI has no interaction test. | verified |
| 3 | OCR-based digitization of old documents and manuscripts | TR-14, TR-15, TR-16, LP-01 | P1 | `backend/archive/ingest/` (`processing.py`, `ocr_local.py`, `quality.py`, `sarvam_ocr.py`, `graph.py`) | `TestOcrRouting` (8), `TestOcrGate` (7), `TestManuscripts::test_handwriting_is_human_transcription_and_not_counted_as_ocr_fallback`. No test runs real Tesseract (TR-15); the gate is `gate-v0-uncalibrated` (TR-16); live capture needs the camera (LP-01, hardware-deferred). | partial |
| 4 | Multilingual translation and audio narration | TR-17, TR-18, TR-19, TR-20 | P1 | `backend/archive/ingest/review.py`, `visitor.py` (`/translate/{id}`), `backend/archive/services/narration.py`, `web/src/i18n.ts` | `TestReviewedTranslation::test_only_a_named_reviewer_for_the_language_can_approve_and_it_reaches_reader_and_search`, `TestMachineTranslation::test_labelled_not_stored_not_citable_and_switchable_per_collection`, `web/src/i18n.test.ts`. Narration (TR-20): `tests/test_unit_narration.py` (19) and `tests/test_db_narration.py` (11), plus one live Sarvam TTS call each for en, hi and mr; see `docs/NARRATION.md`. The narration player UI has no test. | verified |
| 5 | Audio-video archival system for lectures, documentaries and interviews | TR-21, MOD-03 | P1 | `backend/archive/ingest/processing.py` (ffmpeg delivery copy, transcript segments), `visitor.py` (`/items/{id}/captions.vtt`, segments), `fixtures/files/fx-talk-video-synthetic.mp4` | `TestVideo` (4 tests, one runs real ffmpeg), `tests/test_db_media.py`. The live `fx-talk-video` item exists only after a rebuild and `seed-fixtures` run. | verified |
| 6 | Interactive timeline and memorial storytelling modules | TR-22, TR-23, MOD-05 | P1 | `visitor.py` (`/timeline`, `/stories/{slug}`), `staff.py` (`/stories`, timeline) | `TestTimelineAndStory::test_timeline_shows_approved_events_with_visible_items_only`, `test_story_blocks_must_cite_items_and_unpublished_blocks_are_hidden`. | verified |
| 7 | AI Research Assistant for Dr. Ambedkar's works and constitutional ideas | TR-24, TR-25 | P1 | `backend/archive/ask/` (not edited in this work) | `TestAskGraph` (13), `TestAnswerValidation` (8), `TestAskPolicy` (5) with the fake LLM; live check recorded under TR-25 in `docs/REQUIREMENTS.md`. No new Ask gap was found. | verified |
| 8 | Secure digital preservation, metadata tagging, institutional archival management | TR-27, TR-28, TR-29, TR-31, TR-32, TR-33 | P1 (TR-30 PROD) | `backend/archive/audit.py`, `backend/archive/ops.py`, `backend/archive/worker.py`, `backend/archive/metadata.py`, `staff.py` (`/items/{id}/metadata`) | Integrity: `test_preservation_master_is_unchanged_and_readonly`, `test_chain_verifies_and_rows_are_append_only`. Metadata: `TestMetadataTagging` (7 tests). Nightly schedule: `tests/test_db_backup_schedule.py` (7 tests). A real `pg_dump` backup and restore has not been run from this work; see TR-28. Scheduled fixity and 3-2-1 copies are PROD. | partial |
| 9 | Easy access to speeches, books, debates, manuscripts, photographs, documentaries and records | TR-11, TR-17, TR-33, MOD-04, RR-07 | P1 | `visitor.py` (`/items`, `/facets`, `/search`), `web/src/pages/Explore.tsx`, `Search.tsx`, `Item.tsx` | Every content type is served through the API: `TestPhotographs` (3), `TestManuscripts` (2), `TestVideo`, `TestReviewedSummaries`. The web UI type-checks and its helpers have unit tests (`filters.test.ts`, `basket.test.ts`), but no UI interaction test exists. Real debates and books are blocked on rights (row 13). | partial |
| 10 | Search, study, listen to and compile writings, speeches and records | TR-34, MOD-07 | P1 | `visitor.py` (`/collections`), `web/src/basket.ts`, `web/src/pages/Explore.tsx` | `TestCompileAndQr` (4 tests), `web/src/basket.test.ts`. No phone scan of the QR code has been recorded (MOD-07). | verified |
| 11 | Kiosk and smart-display software | TR-01, TR-02, TR-04, MOD-08, MOD-09 | P1 | `web/src/components/Shell.tsx`, `web/src/sw.ts`, `web/src/pages/Signage.tsx`, `visitor.py` (`/signage`) | Signage: `TestTimelineAndStory::test_signage_loop_serves_the_timeline_and_first_story`. Kiosk PWA, idle reset and offline cache are implemented-unverified (TR-01, MOD-09). Lock-task mode needs the tablet (TR-02, hardware-deferred). | partial |
| 12 | Constitutional awareness, accessible learning, immersive heritage experience | TR-36, TR-37 | P1 | `backend/archive/constitution.py`, `staff.py` (`/constitution/*`), `visitor.py` (`/constitution`), `web/src/pages/Constitution.tsx`, `web/src/styles.css` | `TestConstitutionLinks` (5 tests). Touch targets raised to 48 px in `styles.css`. No real debate is linked, because the Constituent Assembly Debates rights are `unknown`; no full accessibility audit has been done. | partial |
| 13 | Datasets: Dr. Ambedkar Foundation, Constituent Assembly Debates, NDLI (discovery only) | TR-38, TR-39, TR-40 | P1 | `backend/archive/rights.py`, `fixtures/manifests/example_real_sources.manifest.json` | NDLI discovery only: `test_discovery_only_source_cannot_be_ingested`. Rights gate: `test_real_source_template_is_refused_until_rights_are_decided`. Real ingestion is blocked until the rights register records permission (TR-40). | partial |

## The seven visitor features

All seven are built end to end: backend API, staff workspace, visitor UI and tests, with synthetic labelled fixtures. The backend and API behaviour of each is **verified** by the tests named below. The web screens for each are **implemented-unverified**: they pass `tsc`, and their form and filter helpers have unit tests, but no test drives the rendered UI.

| Feature | Backend status | Files changed | Tests that prove it |
| --- | --- | --- | --- |
| Reviewed summaries | verified | `staff.py` (draft 404 for missing items, uses approved transcript text, review returns 409 on a bad action), `ingest/review.py`, `web/src/staff/Staff.tsx`, `web/src/pages/Item.tsx` | `test_visitor_sees_only_reviewed_summary_and_viewing_makes_no_llm_call`, `test_staff_draft_from_approved_text_is_hidden_until_approved`, `test_summary_draft_can_use_approved_recording_transcript` |
| Video with timestamped transcripts | verified | `fixtures/generate_fixtures.py`, `fixtures/manifests/fixture_manifest.json`, `fixtures/files/fx-talk-video-synthetic.mp4` (synthetic test pattern), `fixtures/README.md`, `Item.tsx`, `Staff.tsx` | `test_mp4_upload_is_recognised_as_video`, `test_video_item_plays_with_transcript_captions_and_timestamped_search`, `test_ffmpeg_makes_h264_delivery_copy_for_video_master`, `test_staff_can_correct_a_transcript_segment` |
| Captioned photos | verified | `search/hybrid.py` (`photo_credit`, image file in hits), `visitor.py` (`_photo_card`, "Reviewed caption" label), `ingest/review.py`, `Search.tsx`, `Explore.tsx`, `Staff.tsx` | `test_unreviewed_caption_is_never_shown_to_visitors`, `test_reviewed_photo_in_browse_and_search_with_caption_credit_and_rights`, `test_staff_caption_review_records_decision_with_corrected_caption` |
| Manuscripts | verified | `visitor.py` (item detail), `Item.tsx` | `test_handwriting_is_human_transcription_and_not_counted_as_ocr_fallback`, `test_published_manuscript_shows_scan_beside_reviewed_transcription` |
| Debate passages linked to Constitution articles | verified (software); real debates blocked on rights | `models.py` (`ConstitutionArticle`, `ConstitutionLink`), `alembic/versions/0002_visitor_features.py`, `constitution.py`, `staff.py`, `visitor.py`, `search/hybrid.py`, `cli.py` (labelled Article 41 demo link), `web/src/pages/Constitution.tsx`, `Bits.tsx`, `App.tsx`, `Shell.tsx` | `test_curated_link_shows_in_reader_search_and_article_view`, `test_link_survives_republication_with_new_passage_ids`, `test_removal_is_audited_and_hides_the_link`, `test_links_need_curator_role_known_passage_and_visible_item`, `test_fixture_seed_adds_labelled_demo_link_and_tags_once` |
| Staff metadata tagging | verified | `models.py` (`subjects`, `people`, `places`, `metadata_version`, `MetadataRevision`), `0002_visitor_features.py`, `metadata.py`, `staff.py`, `visitor.py` (`/facets`, filters), `search/hybrid.py`, `web/src/staff/forms.ts`, `web/src/filters.ts`, `Staff.tsx`, `Search.tsx` | `test_edit_is_versioned_audited_and_filterable_by_visitors`, `test_invalid_metadata_is_rejected` (5 cases), `test_unpublished_item_tags_are_not_exposed`, plus `forms.test.ts` and `filters.test.ts` |
| Compile and QR | verified | `visitor.py` (segment entries deep-link to `?t=`), `web/src/basket.ts`, `Explore.tsx`, `Item.tsx` | `test_basket_of_item_passage_and_segment_gives_expiring_qr_read_only_page`, `test_withdrawn_item_disappears_from_shared_list`, `test_expired_link_is_gone_and_unpublished_items_are_refused`, `test_collection_body_accepts_no_personal_fields`, plus `basket.test.ts` |

The seven feature tests are in `backend/tests/test_db_visitor_features.py`.

## Other gaps closed in this work

| Gap | Files | Tests |
| --- | --- | --- |
| Curator endpoints for knowledge-map edges | `staff.py` (`POST /map/edges`, `/map/edges/{id}/approve`) | `tests/test_db_curation.py` (5 tests, map, timeline, story and signage) |
| Nightly backup schedule, 20:00 UTC (01:30 IST), one job per night, switchable | `worker.py`, `config.py` | `tests/test_db_backup_schedule.py` (7 tests) |
| Review endpoints treated an unknown action as a rejection | `ingest/review.py` (`REVIEW_ACTIONS`), `staff.py` (409 on `ReviewError`) | `tests/test_db_translation.py` (2 tests) |
| Touch targets under 48 px | `web/src/styles.css` (`.btn.small`, `.segment button.time`) | None automated |

## Test results

Run from the host on 2026-09-27.

| Suite | Command | Result |
| --- | --- | --- |
| Backend | `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` in `backend/` | 197 passed, 1 failed |
| Backend, backup files alone | same, with `tests/test_db_backup_verify.py tests/test_db_backup_schedule.py` | 11 passed |
| Web types | `npx tsc -p . --noEmit` in `web/` | exit 0 |
| Web unit tests | `npx vitest run` in `web/` | 5 files, 34 tests passed |

The one backend failure is `test_db_backup_verify.py::test_verify_restore_fails_on_a_tampered_file_or_wrong_counts`, in another engineer's in-progress backup-verification work. It passes when run alone. In the full run it tampers with the first file it finds under the shared preservation root. Those files outlive the per-test database truncation, so the chosen file may belong to no current database row, and `db_file_rows_failed` comes back empty. The test depends on test order; it was not edited here.

Two earlier vitest runs reported 5 worker start-up timeouts with no tests executed while the backend suite was loading the machine. A run on an idle machine passed.

## Remaining gaps

- **Search quality:** semantic and cross-lingual retrieval are unmeasured (TR-09, MOD-01b).
- **OCR:** real Tesseract is untested (TR-15) and the gate is uncalibrated (TR-16).
- **Narration:** the rules are tested and a live Sarvam run is recorded (TR-20, `docs/NARRATION.md`). Still open: the narration player UI has no test, and the running api needs a restart to load the Sarvam key.
- **Backup:** the schedule is tested, but no real `pg_dump` backup and restore has been run from this work (TR-28, MOD-10).
- **Web UI:** no UI interaction tests exist, and no full accessibility audit has been done (TR-33, TR-37). The Ask answer citation links (`.answer sup a`) are still under 48 px.
- **Web translation:** the Constitution page shows a translated notice instead of the backend `note`, the summary label chip is always in English, and article chip titles carry no `lang` attribute.
- **Rights:** the Dr. Ambedkar Foundation volumes and the Constituent Assembly Debates cannot be ingested until the rights register records permission (TR-40, TR-36 content, LP-15).
- **Hardware-deferred:** tablet lock-task mode (TR-02) and live capture at the camera station (LP-01).
- **Ask:** no gap found; `backend/archive/ask/` was not edited.

## Live verification after the containers are rebuilt

These containers were not restarted or rebuilt by this work, so nothing above is verified against the running stack. After the owning engineer rebuilds `api` and `worker`:

1. Confirm Alembic reaches head (`0002` adds the tags, metadata versions and Constitution tables; `0003_hard_negatives` follows it).
2. Run `archive.cli seed-fixtures` to add the `fx-talk-video` item, the fixture tags and the labelled Article 41 demo link.
3. Check `GET /api/visitor/constitution/41`, `GET /api/visitor/facets`, and that `fx-talk-video` plays with captions and tap-to-seek.
4. Check that the worker enqueues one `backup` job after 20:00 UTC and records `nightly_backup` in system state. The image includes `postgresql-client` (`backend/Dockerfile`).
5. Scan a compiled collection's QR code on a phone (MOD-07).

## Skills used

| Skill | Source | What it changed |
| --- | --- | --- |
| find-skills | `C:\Users\cvbal\.agents\skills\find-skills\SKILL.md` | Used to discover the local skills listed here; no external skill was needed. |
| test-driven-development, with its `writing-good-tests.md` | `C:\Users\cvbal\.claude\plugins\cache\claude-plugins-official\superpowers\6.4.1\skills\test-driven-development\` | Tests were written against behaviour through the public API. The translation test failed first and exposed the unknown-action bug, which was then fixed in `review.py`. |
| verification-before-completion | `...\superpowers\6.4.1\skills\verification-before-completion\SKILL.md` | Every status in this document comes from a command run on 2026-09-27; failures are reported, not hidden. |
| python-testing-patterns | `C:\Users\cvbal\.claude\skills\python-testing-patterns\SKILL.md` | Parametrized cases for invalid metadata and the backup slot logic; `monkeypatch` for the clock, the LLM and the backup call. |
| database-designer | `C:\Users\cvbal\.claude\plugins\cache\claude-code-skills\engineering-advanced-skills\2.2.0\database-designer\SKILL.md` | A new additive Alembic revision; GIN indexes on the tag arrays; a check constraint that each link has an anchor; soft delete with an audit trail for links. |
| frontend-design | `C:\Users\cvbal\.claude\plugins\cache\claude-plugins-official\frontend-design\fa59bc903774\skills\frontend-design\SKILL.md` | New screens reuse the existing visual system instead of adding a new one. |
| ux-rules | `C:\Users\cvbal\.agents\skills\ux-rules\SKILL.md` | Labels that separate reviewed content from synthetic or staff-curated content ("Reviewed caption", the curated-link notice), a "Clear filters" button in `Search.tsx`, and an `aria-pressed` add/remove toggle for the collection basket in `Bits.tsx`. |
| web-design-guidelines | `C:\Users\cvbal\.claude\skills\web-design-guidelines\SKILL.md`, with the rules fetched from `raw.githubusercontent.com/vercel-labs/web-interface-guidelines` | Form labels wrap their inputs, and URL state holds filters so searches can be shared and restored. |
| a11y-audit | `C:\Users\cvbal\.claude\plugins\cache\claude-code-skills\engineering-skills\2.2.0\a11y-audit\SKILL.md` | The scanner run found the targets under 48 px, which were fixed. Its unlabelled-input and missing-landmark findings were false positives (labels wrap the inputs; the landmark and skip link are in `Shell.tsx`). |
| technical-writing | `C:\Users\cvbal\.claude\skills\technical-writing\SKILL.md` | This document: conclusion first, sentence-case headings, no dash asides, every status traced to a test or a named gap. |

The web workspace changes were made by an internal subagent that received the skills rule verbatim and loaded frontend-design, ux-rules, web-design-guidelines, a11y-audit, test-driven-development, verification-before-completion and find-skills. Its output was checked with `tsc` and vitest before integration.
