# Hard-negative review and demo backups

This document covers two P1 checklist rows closed on 2026-09-27:

- hard negatives in the training-data labels (TG-04, spec §7.3);
- the nightly backup of the local demo, with a checksum-verified restore drill (TR-29, TR-28, MOD-10, spec §6.5, §9, §10.2).

No model was trained. Every number below was measured on 2026-09-27 and is given with its sample size.

## Skills used

| Skill | Source | Effect on this work |
| --- | --- | --- |
| find-skills | `C:\Users\cvbal\.agents\skills\find-skills\SKILL.md` | Used as the entry point for choosing skills. Local skills covered every part of the task, so nothing was installed from skills.sh or the marketplace. |
| python-testing-patterns | `C:\Users\cvbal\.claude\skills\python-testing-patterns\SKILL.md` | Test isolation. `test_db_backup_verify.py` copies only the files that its own rows reference, so leftovers in the shared storage roots cannot change a result. External tools (`pg_dump`) are replaced by small scripts, not mocks of our own code. |
| verification-before-completion | `C:\Users\cvbal\.claude\plugins\cache\claude-plugins-official\superpowers\6.4.1\skills\verification-before-completion\SKILL.md` | No claim without a fresh run. After every fix I re-ran the full suite, the restore drill (it failed twice before passing, see below), `check_results.py` and `alembic heads`. |
| data-quality-auditor | `C:\Users\cvbal\.claude\plugins\cache\claude-code-skills\engineering-advanced-skills\2.2.0\data-quality-auditor\SKILL.md` | Integrity checks on labels: exact-duplicate and reprint exclusion, eligibility checks when mining and when importing labels, and a manifest leakage detector that runs before a dataset is frozen. |
| senior-ml-engineer | `C:\Users\cvbal\.claude\plugins\cache\claude-code-skills\engineering-skills\2.2.0\senior-ml-engineer\SKILL.md` | Every mined candidate carries full retriever provenance (models, test-double flags, index version, candidate pool size, ranks, score). Only a base-model baseline was produced; no training. |
| runbook-generator | `C:\Users\cvbal\.claude\plugins\cache\claude-code-skills\engineering-advanced-skills\2.2.0\runbook-generator\SKILL.md` | The procedures below are copy-pasteable commands, each with the check that shows it worked. |

## Part A: hard negatives

### What a hard negative is here

A hard negative is a passage that the base retriever ranks highly for a reviewed question but that a named person confirms does not answer it.

- **Mining** (`backend/archive/datasets/hard_negatives.py`, `mine`) runs the same base ranking as `eval-retrieval`: keyword plus semantic search, fused by reciprocal rank fusion (RRF), then the base reranker (`evaluation.base_rankings`). It covers only examples that have `reviewed_by` set and are not yet frozen into a dataset version.
- **Candidates must be training-eligible passages** (spec §4.10, the same rule as `corpus.eligibility`):
  - training permission `allowed`;
  - part of the current published version and indexed;
  - source text or a reviewed transcription or transcript.
  So unpublished, withdrawn, `not_allowed`, machine-translated, summary and AI-answer text can never be mined.
- **Also excluded:**
  - labelled positives;
  - exact duplicates of a positive: the same `text_hash` or the same normalised text, for example the same text in another edition or a reprint (spec §7.3: that is not a negative);
  - passages already mined for that question (this makes mining idempotent).
- **Stored in the `hard_negative_candidate` table** with status `candidate`, plus:
  - the relation to the positive (`same_item`, `same_work` or `other_work`);
  - the retriever version string, rank, reranker score;
  - provenance: embedder and reranker names and whether they were test doubles, `index_version`, `candidate_k`, RRF, keyword and semantic ranks, item, work key, language, and maximum token overlap with a positive.
- **Review** (`review`) needs a named person. `fixture-seed`, `cli`, `system`, `worker` and similar names are refused. Each candidate is reviewed once, and never after its example is frozen. The decision is one of:
  - `confirm`: it becomes a confirmed hard negative;
  - `relevant`: a false negative; the passage is added to the example's positive labels, with a warning if it comes from a different work than the example's split group;
  - `reject`: not useful.
  The reviewer and date are stored, and every mine and review writes an audit event.
- **Labels files:** `load-labels` imports a `hard_negatives` entry only if it has `confirmed_by` set to a person and passes the same eligibility and duplicate checks. It is stored as confirmed with `retriever="label-import"`. Previously these entries were silently dropped.
- **Frozen dataset manifest** (`freeze-dataset`):
  - it includes only confirmed hard negatives;
  - negatives from a work in a different split are dropped (work-level train/dev/test grouping, so no work leaks across splits);
  - the counts of included and excluded negatives go into the manifest;
  - `manifest_leakage` refuses to freeze if any work, positive or negative crosses a split;
  - `export-labels` writes the manifest in the labels format, so `eval/check_training_leakage.py` can check it.

### Commands

Run from `backend\` with the venv. Inside the api container, use `python -m archive.cli`.

```powershell
.\.venv\Scripts\python.exe -m archive.cli mine-hard-negatives --per-question 5
.\.venv\Scripts\python.exe -m archive.cli list-hard-negatives --status candidate --out hn-sheet.json
# the reviewer fills "decision" (confirm | relevant | reject) and an optional "note" per row, then:
.\.venv\Scripts\python.exe -m archive.cli review-hard-negatives --file hn-sheet.json --reviewer "Full Name"
# or one at a time:
.\.venv\Scripts\python.exe -m archive.cli review-hard-negative 12 --decision confirm --reviewer "Full Name"
.\.venv\Scripts\python.exe -m archive.cli dataset-preview          # read-only: splits, negatives kept, gate report
.\.venv\Scripts\python.exe -m archive.cli freeze-dataset round1-v1 --actor "Full Name"
.\.venv\Scripts\python.exe -m archive.cli export-labels round1-v1 --out round1-v1.labels.json
python eval\check_training_leakage.py ...   # see eval/README.md
```

Check: `list-hard-negatives --status confirmed` shows each confirmed row with a reviewer and date. `dataset-preview` reports `cross_split_excluded` and `unreviewed_excluded`.

There is no staff-API or web screen for review yet, because `backend/archive/api/**` was out of scope for this work. See the follow-ups.

### Migration

The new table is created by `backend/alembic/versions/0003_hard_negative_review.py`, revision `0003_hard_negatives`, with `down_revision = "0002"` (the conformance engineer's `0002_visitor_features`). `alembic heads` shows one head: `0001 → 0002 → 0003_hard_negatives`.

On 2026-09-27 the live demo DB was still at `0001`. Neither migration was applied to it by this work. The api service runs `alembic upgrade head` when it starts, so the next api restart applies both, in order.

### Tests

`backend/tests/test_db_hard_negatives.py` has 15 tests:

- mining excludes positives, a reprint of a positive, and ineligible passages: not_allowed, withdrawn, unpublished, reviewed-translation, summary, and unreviewed machine translation;
- provenance is recorded;
- mining is idempotent, and unreviewed examples are not mined;
- confirm, relevant (flips to positive) and reject each work;
- review needs a named person and happens once only;
- the CLI worksheet round trip works;
- `load-labels` imports confirmed negatives;
- the manifest includes only confirmed negatives;
- cross-split negatives are dropped, and `manifest_leakage` catches a work in two splits;
- exported labels pass `eval/check_training_leakage.check`;
- the preview writes nothing.

As a mutation check, I disabled the eligibility filter and then the cross-split filter; each time a test failed.

### Base-model baseline (no fine-tuning)

The only question set with expected passages is `eval/questions/fixture_smoke.retrieval.json`. It has 12 **synthetic** questions (8 en, 2 hi, 2 mr) written by the build agent against the synthetic `fx-*` fixture items, and **no person has reviewed them**. It is a smoke test, not spec §10.1 evidence.

- 11 of the 12 resolved. `fx-en-04` did not resolve its anchor.
- Live models: `paraphrase-multilingual-MiniLM-L12-v2` and `jina-reranker-v2-base-multilingual`. k = 5, candidate_k = 30, index_version 15.
- Result file: `eval/results/retrieval-2026-09-27.json`.

| Mode (n = 11) | Recall@5 | Recall@30 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- |
| keyword | 0.18 | 0.18 | 0.27 | 0.20 |
| semantic | 0.91 | 1.00 | 0.93 | 0.85 |
| hybrid (RRF) | 0.91 | 1.00 | 0.93 | 0.85 |
| hybrid + rerank | 0.91 | 1.00 | 0.91 | 0.88 |

For hybrid + rerank, the 95% bootstrap CIs are MRR 0.77–1.00 and nDCG@5 0.74–1.00. MRR by language: en 0.86 (n = 7), hi 1.00 (n = 2), mr 1.00 (n = 2). These samples are far too small to support any claim. The numbers are deliberately **not** copied into `eval/results/results-2026-09-27.json`.

### §7.3 minimum-data gate: NOT met

I computed the gate read-only on the live corpus on 2026-09-27 (`training-gate-v1`). There are 352 training-eligible passages in 10 works; 7 of those works are synthetic fixtures and 3 are real (`mea-baws-en-vol01-2020`, `mea-baws-en-vol13-2020`, `lok-sabha-cad-en-vol7-sansad`).

| Check | Needed | Found | Result |
| --- | --- | --- | --- |
| Works | ≥ 6 | 10 | Passes, but only because the fixtures count |
| Works in test | ≥ 2 | 2 | Passes |
| Reviewed question–passage pairs, train / dev / test | 300 / 60 / 60 | 0 / 0 / 0 | **Fails** |
| Test pairs per claimed language | ≥ 30 | 0 | **Fails** |

With no reviewed training examples, the gate fails. Trained-model areas stay UNMEASURED.

## Part B: nightly backup and restore drill

### Which mechanism runs nightly

The **worker's `backup` job** is the only scheduler. The conformance engineer added it in `backend/archive/worker.py`: it queues one backup per night at 20:00 UTC (01:30 IST) into the `backups` volume and records `backup.run` in the audit log.

No Windows Task Scheduler job exists for this. The registration script I had drafted was deleted without ever being registered (`\AmbedkarArchive\` has 0 tasks).

### What was wrong with the worker job, and the fix

The job calls `ops.backup()`, which ran bare `pg_dump`. The api/worker image installs Debian bookworm's `postgresql-client`, version 15.19, and the demo server is PostgreSQL 17.8. `pg_dump` refuses to dump a newer server, so every nightly run would have failed. The image's `pg_restore` 15 also cannot read a version 17 archive.

- **`backend/Dockerfile`:** installs `postgresql-client-17` from the PostgreSQL (PGDG) apt repository and puts `/usr/lib/postgresql/17/bin` first on `PATH`. This is the same recipe as `deploy/production/ops/Dockerfile`, which I built on top of the current api image to check it. The result was `pg_dump (PostgreSQL) 17.11`. **It takes effect only when the api/worker image is next rebuilt.** I did not rebuild or restart anything.
- **`backend/archive/ops.py`, `backup()`:**
  - `check_pg_client` compares the client and server major versions before any backup folder is created. If they don't match, it fails with an instruction instead of a half-written folder.
  - The dump now runs inside a read-only REPEATABLE READ snapshot (`snapshot_dump`). It writes `DB_COUNTS.json` (key-table row counts taken inside the dump's own snapshot, so the restore drill has something exact to compare against).
  - `BACKUP_LOG.json` and the job result now include `pg_client`, `server_version`, `snapshot` and `row_counts`.
  - `pg_dump` takes ACCESS SHARE locks only, so it never blocks ingestion writes.
- **`archive.cli verify-restore`** accepts either counts format: bare counts from `ops.backup`, or the `snapshot-dump` result that wraps them.

The running worker still runs the old image code, which has no schedule and no fix. The schedule starts working after the image is rebuilt and migration 0002 (its `system_state` table) is applied.

### The real run (one backup, read-only)

To run the worker job's own code with a PG17 client without touching the running worker, I used a one-off container from the ops image:

```powershell
docker build --build-context base=docker-image://ambedkar-archive/api:local -t ambedkar-archive/ops:local deploy/production/ops
# ARCHIVE_DATABASE_URL set in the calling process from .env (never printed)
docker run --rm --network ambedkar-archive_backend -e ARCHIVE_DATABASE_URL -e ARCHIVE_ENVIRONMENT=demo `
  -e ARCHIVE_PRESERVATION_ROOT=/data/preservation -e ARCHIVE_DELIVERY_ROOT=/data/delivery `
  -e ARCHIVE_DERIVATIVE_ROOT=/data/derivatives -e ARCHIVE_BACKUP_ROOT=/backups `
  -v ambedkar-archive_preservation:/data/preservation:ro -v ambedkar-archive_delivery:/data/delivery:ro `
  -v ambedkar-archive_derivatives:/data/derivatives:ro -v ambedkar-archive_backups:/backups `
  -v "${PWD}\backend:/app:ro" -w /app ambedkar-archive/ops:local python -m archive.cli backup
```

This runs `ops.backup()`, which is exactly what the job handler calls. The handler's own bookkeeping (the audit event and `system_state`) was not run: the live DB has no `system_state` table yet, and the backup had to stay read-only.

Result: `backup-20260927T072419Z` in the `backups` volume.

- `pg_dump` 17.11 against server 17.8.
- 604 files plus a 3.6 MiB dump, 99.7 MiB in total.
- **6.3 s** inside Docker, of which `pg_dump` took 2.1 s. The one-off container took 21.3 s wall time.

### Restore drill on that backup (n = 1)

To drill it, I copied the backup out of the volume, read-only, to `data\backups\worker\`. That took 409 s, because Docker Desktop writes to Windows slowly. Then:

```powershell
docker run --rm -v ambedkar-archive_backups:/b:ro -v "${PWD}\data\backups\worker:/out" pgvector/pgvector:0.8.1-pg17 `
  sh -c "cp -r /b/backup-20260927T072419Z /out/"
.\deploy\local-demo\Invoke-DemoRestoreDrill.ps1 -BackupRoot data\backups\worker -Backup backup-20260927T072419Z
```

The drill restores into a **throwaway** `pgvector:0.8.1-pg17` container with its data on tmpfs and a random password, published on a free loopback port and not attached to the compose network, plus a new temporary folder. Both are removed afterwards. I confirmed that no scratch container or temp folder was left behind.

| Check | Result |
| --- | --- |
| Dump SHA-256 vs MANIFEST.json | match |
| Backup files on disk vs manifest | 604 / 604 match |
| Restored files vs manifest | 604 restored, 0 mismatches |
| Live `file_version` rows vs restored files | 602 / 602 match (623 rows, of which 602 are not soft-deleted) |
| Row counts, 12 key tables, vs the dump's snapshot | all equal |
| Audit hash chain in the restored DB | verified, 556 events |
| Drill time | **41.5 s**: verify on disk 8.6 s, DB restore 3.5 s, file restore 2.7 s, verification 26.7 s |

- Evidence is in `eval/results/backup-restore-2026-09-27/worker-job/`: `RESTORE_LOG.json`, `BACKUP_LOG.json`, `DB_COUNTS.json` and the verify logs.
- `eval/results/results-2026-09-27.json` fills **only** the seven `backup_restore` metrics, from `eval/verify_restore_log.py` (n = 1). `target_was_clean_machine` is **no** (same host). Every other area stays UNMEASURED, and `check_results.py` passes.
- The drill failed twice before passing, both times because of drill tooling:
  1. `DB_COUNTS.json` came in two different formats; `verify-restore` now accepts both.
  2. A relative `-BackupRoot` broke the CLI output path; the scripts now resolve it to an absolute path.

### Manual host tool (not scheduled)

`deploy\local-demo\Invoke-DemoBackup.ps1` stays as a **manual** tool, for a copy outside Docker's volumes, for example on an external disk or off-site. It dumps with the `pgvector:0.8.1-pg17` image inside a snapshot, copies the three volumes read-only, writes a SHA-256 manifest, re-hashes it, and prunes its own folder by retention.

It was run once on 2026-09-27, before the worker job was chosen:

- `backup-20260927T064651Z`: 93.9 MiB (3.4 MiB dump plus 565 files), in 287.4 s. Of that, the snapshot counts took 1.8 s, `pg_dump` 64.7 s, the file copy through the Windows bind mount 202.4 s, and hashing plus verification 13.6 s.
- Its drill passed in 114.3 s: 565 / 565 files, 562 / 562 rows, 12 tables equal, audit chain of 527 events OK.
- Evidence: `eval/results/backup-restore-2026-09-27/manual-host-script/`.

### Limitations

- **Not a second disk.** The `backups` volume is inside Docker Desktop's disk image on the same C: drive as the live data, and `data\backups\` is on C: too. Losing that disk loses both.
- **Not a clean machine.** The drill ran on the same host, so spec §8.3's clean-machine restore remains to be done.
- **No retention.** The worker job prunes nothing, so the `backups` volume grows by about 100 MiB per night.
- **Only while Docker runs.** Docker Desktop, and so the worker, runs only while a user is signed in.
- **Backups contain sensitive data.** They include staff password hashes (`staff_user`) and the kiosk exhibit signing private key (`derivatives/keys/exhibit-signing.pem`), so store them like secrets. `.env` is not included, so a restore also needs the secrets from their own store.

## Follow-ups for other engineers

1. **Image owner:** rebuild `ambedkar-archive/api:local` so the worker gets `pg_dump` 17 (the `backend/Dockerfile` change). Until then, every nightly backup will fail with the new clear error. After the rebuild, check with `docker exec ambedkar-archive-worker-1 pg_dump --version`.
2. **Next api restart:** it applies `0002` and then `0003_hard_negatives` (`alembic upgrade head`). The nightly schedule needs 0002's `system_state` table.
3. **Worker backup:**
   - add retention (keep N verified backups);
   - point `ARCHIVE_BACKUP_ROOT` at a real second disk, which needs a compose volume change;
   - run the restore drill weekly by hand until it is automated.
4. **API owner:** add staff endpoints for hard-negative review (list candidates, submit decisions), using the `datasets` freeze endpoint as the pattern, with a named reviewer from the session.
5. **Labelling:** write the real reviewed question set with EN/HI/MR labels, then mine and review hard negatives. Also fix the `fx-en-04` anchor in the smoke set.
6. **Operations:** do one restore to a clean machine (MOD-10) with `eval/verify_restore_log.py --source-host … --target-host …`.
7. **Ask owner:** `tests/test_db_ask_datasets.py::TestAskRightsAndCitations::test_no_support_after_withholding_says_so_and_shows_the_withheld_passage` fails. It returns `insufficient` where the test expects `extractive`. It reproduces on its own. The Ask code imports none of the files changed here, and the test file was last edited by someone else at 13:08 IST.
8. **Cleanup, when convenient:**
   - the scratch test DB: `docker exec ambedkar-archive-db-1 dropdb -U archive archive_test_hn`;
   - the local image tag `ambedkar-archive/ops:local`;
   - the one-off backup `backup-20260927T072419Z` in the `backups` volume and its host copy in `data\backups\worker\`.
