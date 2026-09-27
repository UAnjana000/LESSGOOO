# Build log — Ambedkar Digital Heritage Archive

## Docker recovery and rebuild — 2026-09-27, about 11:09–11:30 IST

Full record: `docs/LIVE_TEST.md`, "Docker recovery and rebuild — 2026-09-27".

**Results**

- **Docker is healthy.** `docker ps -a` answered in about 8 s, and `docker info` reports 29.1.5. The engine had already been restarted before this run. This run did not restart Docker Desktop.
- **Leftover containers were already gone.** The one-offs `api-run-23e4307f5c70`, `-9bf33807883c`, `-790be2b0087a` and the hung item-14 ingest `-b5f59bd37081` no longer existed, so nothing needed removing.
- **No stuck database session.** There were no `idle in transaction` sessions, so nothing needed terminating. Item 14 is still `draft` with 92 pages and was not resumed.
- **Images rebuilt and services recreated.**
  - `docker compose build api` and `docker compose build proxy` both succeeded.
  - `docker compose up -d --force-recreate --no-deps api worker proxy` recreated all three. The proxy needed `HTTP_PORT=8088` because host port 8080 is taken.
  - api, worker and db are healthy. The worker healthcheck is now applied. The proxy has no healthcheck defined.
- **Migrations and readiness.** Alembic is at `0001 (head)`, and `https://localhost:8443/api/health/ready` returns 200.
- **Backend tests: 103 passed, 0 skipped**, in 23 s. The Ask failure-path test now runs and passes, and a red-green check confirmed it catches the bug.
- **Web checks.** `tsc` is clean, and `vitest` passed 5 files with 33 tests.
- **Live Ask works.** Answers 8 and 9 came back `answered` with the AI-generated label, citing passage 7. That passage is published and `quote_verified` (a fixture-seed record).
  - Last night's failure was **DNS inside the degraded Docker VM**: the container trace shows `[Errno -3] Temporary failure in name resolution`. It was not the code or the key.
  - TR-25 is marked verified, with those limits.
- **`smoke_test.py --ask`: 33 passed, 0 failed.**

**Still open**

- No proxy healthcheck, and port 8080 is taken, so the proxy needs `HTTP_PORT=8088`.
- Quote verification is fixture-seeded only. There is no Langfuse and no LLM cost pricing.
- Another engineer's uncommitted `0002_visitor_features` migration and model and search changes appeared at 11:24–11:26. They are not in the image and not applied.

**Skills loaded in this run**

| Skill | Source | What it changed |
|---|---|---|
| `find-skills` | `~/.agents/skills` | Discovery only. The local skills covered this task, so nothing was installed. |
| `docker-development` | `~/.claude/plugins/cache/claude-code-skills/engineering-advanced-skills` | Confirmed the worker healthcheck is applied, and flagged that the proxy has no healthcheck (recorded, not changed). |
| `senior-devops` | `~/.claude/plugins/cache/claude-code-skills/engineering-skills` | Recreate behind a health gate (`--no-deps`, db left running), then check readiness through the proxy. |
| `systematic-debugging` | `~/.claude/plugins/cache/claude-plugins-official/superpowers` | Read the container trace before changing anything. That found the DNS cause, so the code was left alone. |
| `verification-before-completion` | same | Every claim is backed by a fresh command. Red-green check on the Ask failure test. Citations checked against the database. |
| `python-testing-patterns` | `~/.claude/skills` | Ran the failing-model test in isolation by node, then the file, then the full suite. |

## Continuation note — 2026-09-26/27, about 23:40–00:45 IST

**Finished**

1. **Sarvam OCR parse: done.** The fix in `backend/archive/ingest/sarvam_ocr.py` was already on disk and was not rewritten. It strips data-URI, Markdown and HTML images, long base64 runs and image-description spans. If no text remains, the output is marked as not a transcription. The 17 Sarvam tests pass. One live retry was made on `fixtures/files/fx-lecture-tank-degraded.png` only. It returned 141,525 raw characters with 7 images; the parser selected 511 characters, **rapidfuzz ratio 0.995** against the 510-character ground truth, with no base64. Nothing was written to the database. The text would only ever be a candidate for full archivist review.
2. **Seeded recording `fx-talk-audio`: already done before this run.** It is item 9, `published`. The delivery copy is `file_version` 12 (`ffmpeg aac64k`, `audio/mp4`), and its SHA-256 matches the file on disk (checked with `archive.storage.verify` in the api container). Publication is recorded in audit events 214 and 216, by `fixture-seed`. All 4 segments have `quote_verified = false`. Nothing here is human verification.
3. **Local demo health: written and committed by the user (`463bca4`), not applied to the running worker.** `docker-compose.yml` now gives the worker its own healthcheck: PID 1 is alive and `archive.db.db_healthy()` succeeds, matching `deploy/production`. The api healthcheck now has a 4 s `urlopen` timeout. The Postgres 17 `pg_dump` gap is covered by `deploy/production/ops`, which uses a PG17 client, so it does not block the demo. `backend/tests/conftest.py` already defaults to `127.0.0.1:55432`.
4. **Ask bug fix: code only, not deployed or run against a database.** When the answer model fails, the API said "closest items to browse" but returned none, and the web page showed only a generic error. `archive/ask/service.py` and `web/src/pages/Ask.tsx` now return and show the closest passages. A new test, `test_answer_model_failure_offers_closest_passages_without_an_answer`, is written but has **not run**: the database was unreachable.
5. **Staff-login timeout: cause is in the app and fixed in code (earlier session), confirmed live now.** A one-off ingestion container on the pre-fix image held the audit hash-chain advisory lock for a whole item. It was `api-run-b5f59bd37081`, ingesting the restricted Constituent Assembly items 12–14 with external processing off. The fixes are in `processing.run_sarvam` (commit before the Sarvam call) and `graph.process_pages` (commit per page), with the regression test `test_audit_chain_lock_is_released_during_sarvam_call`. No advisory lock is held now. Archivist login returned 200 in 1.4 s once the proxy connected.
6. **Small web and repo fixes.** The Vite dev proxy accepts Caddy's `tls internal` certificate (`secure: false`, dev only). `web/.gitignore` now ignores new files in `scripts/out/`. Three files there are already tracked by commit `9da4068` (`smoke-log.txt`, `smoke-result.json` and a blank `ui-home.png`) and were left as committed.

**Commands and results**

| Command | Result |
|---|---|
| `backend> .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` (before the `service.py` change) | **97 passed**, 292 s |
| `pytest -k sarvam tests/test_unit_integrations.py tests/test_db_pipeline.py -rA` | **17 passed** |
| `web> npx tsc -p . --noEmit` (before and after the `Ask.tsx` change) | clean |
| `web> npx vitest run` | **2 files, 15 tests passed** |
| Live Sarvam Doc AI, one synthetic page (temporary script, direct client) | `completed`, 14.1 s, ratio 0.995 |
| Live visitor Ask via `POST https://localhost:8443/api/visitor/ask`, twice (answer ids 6 and 7) | HTTP 200, **`outcome: error`**: model call failed in the container, 0 tokens, no label, no citations |
| `GET /api/staff/settings/status` (archivist) | `llm_model: gpt-4o-mini`, `llm_configured: true`, `sarvam_configured: true`, Langfuse not configured |
| `pytest tests/test_db_ask_datasets.py` (after the fix) | 18 skipped: test database not reachable |
| `backend\.venv\Scripts\python web\scripts\smoke_test.py` | failed on the first request (TLS connection reset by the proxy) |
| `docker compose build api` / `docker build … backend` | never started (buildx: "context deadline exceeded") |

**Still blocked**

- **Docker engine degraded from about 00:05 IST.**
  - `docker ps` times out, `docker exec` returns 500, and builds cannot start.
  - The proxy and database ports alternate between working, 502s and resets.
  - Consequences:
    - **api and worker were not restarted or rebuilt.** The running image predates the current `sarvam_ocr.py` and `cli.py` and today's `service.py` fix.
    - The worker healthcheck is not applied.
    - The smoke test did not run.
    - The new Ask test did not run.
  - I did not restart Docker Desktop or take down the database, because that would stop the database and other engineers' jobs.
  - Next step: restart Docker Desktop at an agreed moment. Then run `docker compose build api` and `docker compose up -d --force-recreate --no-deps api worker`. Then run `pytest tests/test_db_ask_datasets.py`, the live Ask, and `smoke_test.py --ask`.
- **TR-25 stays implemented-unverified.** No live answer has been observed with the AI label, citations resolving to published passages, and quotes limited to `quote_verified` passages. The model-call failure reason is in the container's JSONL trace, which could not be read.
- **UI not browser-verified.** The Home route (`/?kiosk=1`) rendered once in the IDE browser through the Vite dev server against the live API: navigation, language and text controls, and the fixture banner were visible. No other route was exercised, and Playwright screenshots failed.
- **Constituent Assembly items 12–14** are restricted, unpublished, and were not sent to Sarvam. They were not touched in this run. The ingestion container for item 14 still had a connection idle in a transaction for more than 1.5 h.

Not claimed: production go-live, human quote verification, translation or OCR review, a working live Ask answer, Langfuse, fine-tuning, or any measured eval field.

---

## Earlier sessions (summary)

- **Ownership.** I own `web/**`, `backend/**` (only for UI-blocking bugs), this log, and running tests. `deploy/`, `docs/ops/`, `docs/REQUIREMENTS.md` (except the TR-25 evidence cell requested in this run) and `eval/` belong to other engineers. I created `deploy/caddy/Caddyfile` before ownership was split; the deploy engineer owns it now.
- **Skills loaded, and their effect.** These were loaded in the earlier UI session; none were newly loaded in this run.
  - `frontend-design`, `ux-rules`, `web-design-guidelines`: token-based design system, 48 px touch targets, kiosk idle reset only in kiosk mode, labelled machine output.
  - `a11y-audit`: scanner run; all contrast pairs pass AA. Missing textarea and table labels and skipped headings were fixed.
  - `python-testing-patterns`: arrange-act-assert tests for media publication and the audit lock.
  - `docker-development`: lazy routes and subset fonts, which cut the main JS chunk from 771 kB to 374 kB.
  - `verification-before-completion`: this log records only commands that actually ran.
- **Local stack notes.** The proxy runs with `HTTP_PORT=8088`, because host port 8080 was taken. HTTPS is at `https://localhost:8443`.
- **Lint.** Pre-existing Ruff findings under a wider rule set (for example BLE001, RUF022, DTZ011) are left unfixed in files I do not own. Only my own findings were fixed.
