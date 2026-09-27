# End-to-end UI tests (Playwright)

The suite under `web/e2e/` drives the real visitor and staff screens in branded Chrome against a throwaway Docker stack built from the working tree. It has 63 tests: 62 in project `kiosk-chrome` and 1 in project `model-down`. It type-checks (`npx tsc -p e2e/tsconfig.json --noEmit`, exit 0) and lists (`npx playwright test -c e2e/playwright.config.ts --list`).

**Run status: 2026-09-27 (IST).** Isolated stack `ambedkar-e2e` (ports 9443 / 9088 / 56432). Retries 0. Project `ambedkar-archive` was left running and was not rebuilt or restarted. Langfuse stayed stopped. Live Ask POSTs counted toward the budget: 3 (one answerable, two from the off-topic test); model-down and offline Ask are excluded from that ledger. Artifacts: `web/e2e/artifacts/playwright-kiosk.log`, `playwright-staff-rerun3.log`, `playwright-model-down.log`, `suite-summary.json`, `html-report/`, `a11y/summary.json`, traces under `test-results/`.

## How to run

From the repo root, in PowerShell. Each `stack.ps1` action logs to `web/e2e/artifacts/stack-<action>.log`.

```powershell
powershell -File web/e2e/stack.ps1 build      # images ambedkar-e2e/api:local and ambedkar-e2e/proxy:local
powershell -File web/e2e/stack.ps1 up         # start; the api entrypoint runs alembic upgrade head and bootstrap
powershell -File web/e2e/stack.ps1 seed       # python -m archive.cli seed-fixtures (synthetic fixtures only)
cd web
npm run test:e2e                              # 62 tests, project kiosk-chrome
cd ..
powershell -File web/e2e/stack.ps1 llm-down   # api restarted with an unreachable answer model
cd web; npm run test:e2e:model-down; cd ..    # 1 test, project model-down
powershell -File web/e2e/stack.ps1 llm-up     # answer model restored from .env
powershell -File web/e2e/stack.ps1 down       # docker compose -p ambedkar-e2e down -v
powershell -File web/e2e/stack.ps1 rmi        # optional: remove the two ambedkar-e2e images
```

Artifacts (gitignored through `web/.gitignore`): `web/e2e/artifacts/test-results/` (traces and screenshots of failures), `html-report/`, `results.json`, `a11y/summary.json`, `ask-budget.json`.

## Isolated stack

The stack is the root `docker-compose.yml` plus `web/e2e/docker-compose.e2e.yml`, run as project `ambedkar-e2e` with `--project-directory` at the repo root.

| Concern | How the e2e stack differs from the demo stack (`ambedkar-archive`, 8443) |
|---|---|
| Project, volumes, network | `-p ambedkar-e2e`, and `name: ambedkar-e2e` in the override; volumes are `ambedkar-e2e_*` |
| Images | `ambedkar-e2e/api:local`, `ambedkar-e2e/proxy:local`, so the demo images are not retagged |
| Ports | HTTPS 9443, HTTP 9088, Postgres 127.0.0.1:56432, set as shell variables by `stack.ps1` (override `ports:` lists would be appended, not replaced) |
| Secrets | Database password `e2e-throwaway-db`; admin `admin@archive.local` / `e2e-admin-password`; demo staff `e2e-demo-password`. These are fixed test values, not the `.env` values |
| Sarvam | `ARCHIVE_SARVAM_API_KEY=""`: no live Sarvam calls from tests |
| Langfuse | Keys and host blank: traces stay in the stack's own volume |
| Nightly backup | `ARCHIVE_NIGHTLY_BACKUP_ENABLED=false` |
| Answer model | `ARCHIVE_LLM_*` from `.env` (`gpt-4o-mini`). Keys are never printed |
| Worker | `WORKER_CPUS=1`, `WORKER_MEM=2g` |
| Public URL | `ARCHIVE_PUBLIC_BASE_URL=https://localhost:9443`, `PUBLIC_HTTPS_PORT=9443` for the Caddy redirect |

Safety checks:

- `stack.ps1` refuses to run unless the project name is `ambedkar-e2e`, the override declares `name: ambedkar-e2e`, and every container labelled with the project carries its prefix.
- `global-setup.ts` refuses any base URL or database URL on the demo ports (8443, 8088, 55432).
- The only direct database write, expiring one QR list, refuses any URL that is not port 56432.

**Models.** The stack keeps the real fastembed embedder and reranker (`PREFETCH_MODELS=1`, the compose default). The lighter settings in `backend/archive/search/models.py` (`ARCHIVE_EMBEDDING_BACKEND=hash`, `ARCHIVE_RERANKER_BACKEND=lexical`) are test doubles. The hash embedder cannot match a Hindi query to Hindi text by meaning, and the lexical reranker changes the sufficiency scores that decide whether Ask answers or abstains. With them, the Hindi-search and Ask tests would check the doubles instead of the product.

**Live Ask budget.** The task allows at most 5 live answer-model calls. Two kiosk tests can reach the live model (one answerable question, one off-topic question). The model-down test and the offline Ask test send requests that cannot reach the model and are not counted. A fixture records live visitor Ask POSTs in `artifacts/ask-budget.json` and fails the test that pushes the count past 5. Delete that file to reset the budget. This run recorded 3 live POSTs.

## Coverage by area

| Area | Spec | Tests | What is exercised |
|---|---|---|---|
| 1. Visitor kiosk | `01-visitor-kiosk.e2e.ts` | 8 | Home, keyword search, result, reader with scan beside text and the cited passage marked; cited region outlined on the scan; Hindi query; label chips (reviewed transcription, reviewed translation tab); machine-translation chip; EN/HI/MR switch; text size 100/115/130 %; high contrast; kiosk idle warning, attract screen, Finish |
| 2. Ask | `02-ask.e2e.ts`, `ask-model-down.e2e.ts` | 2 + 1 | Answer label "AI-generated answer from archive sources", a citation on every sentence, the source opens the reader at the cited page and passage; off-topic abstains; answer-model failure shows the error and "Related material you can read" |
| 3. Media | `03-media.e2e.ts` | 3 | Audio and video decode and play; tapping a transcript line seeks and plays; the WebVTT captions track exists and carries the transcript; `?t=` deep link |
| 4. Content types | `04-content-types.e2e.ts` | 3 | Photographs with reviewed captions and credits; manuscript with a reviewed transcription; reviewed summary shown, a staff draft summary not shown |
| 5. Constitution | `05-constitution.e2e.ts` | 1 | Article 41 lists the linked debate passage with the curator's note; "Open original" opens the reader at the passage |
| 6. Facets | `06-facets.e2e.ts` | 4 | Subject, person and place filters; tag chip in the reader; date range; collection, type and language combined |
| 7. Compile | `07-compile.e2e.ts` | 1 | Add items, QR code, share link opened in a Pixel 7 context, read-only check, staff withdrawal removes the item from the shared list, expired link refused (HTTP 410 and the visitor notice) |
| 8. Explore | `08-explore-signage.e2e.ts` | 4 | Timeline, story, connections (name list, links, supporting items), `/display` rotation with a controlled clock |
| 9. Offline | `09-offline.e2e.ts` | 3 | Service worker and signed exhibit cache; offline reading from the cache; Ask needs-connection state; offline reload of an item address; lease expiry notice |
| 10. Staff | `10-staff.e2e.ts` | 12 | Login; intake of a unique two-page synthetic capture; fail the sample batch; approve page 1 and correct page 2; quote verification; Sarvam-vs-local diff (skips when no fixture has one); publish with staged version and atomic switch; metadata tags; new Constitution article and link; summary draft then approval; withdraw; audit log and hash-chain check; restore |
| Accessibility | `a11y.e2e.ts` | 21 | axe (WCAG 2.0/2.1/2.2 A and AA tags) on every visitor route, plus high contrast at 130 %, Hindi, a chosen map name, the QR panel and the phone list. Serious and critical violations fail the test; all violations are annotated and written to `artifacts/a11y/summary.json` |

Design notes:

- **Serial staff workflow.** `10-staff.e2e.ts` runs in serial mode on one capture, because each step needs the previous state (review before publish, publish before linking). Audit runs before restore, so a missing restore path cannot hide the audit result.
- **Test setup through the API.** The worker-scoped `boxed` fixture finds a published passage with word boxes. Boxes exist only where the approved text still equals the OCR text; the seeded fixtures were corrected to ground truth, so the fixture may publish one fresh capture first. The compile test publishes its own capture to withdraw. Setup uses the staff API, the same calls as `web/scripts/smoke_test.py`; nothing in the UI is stubbed.
- **Unique captures.** `uniquePng()` adds a PNG `tEXt` chunk to `fixtures/capture-demo-page.png`. The pixels, and so the OCR route, are unchanged, but the SHA-256 differs, so intake does not reject a rerun as a duplicate.
- **Clocks.** The idle reset (120 s), signage rotation (12 s) and exhibit lease (72 h) use `page.clock`, not real waiting.
- **Chrome.** `channel: "chrome"`, because bundled Chromium lacks the AAC and H.264 decoders the fixture recordings need. Chrome runs with `--ignore-certificate-errors`, because Chrome will not register a service worker over Caddy's untrusted `tls internal` certificate.
- **File names.** Specs are `*.e2e.ts` so Vitest (`npm test`) does not collect them.
- **Pinned versions.** `@playwright/test` and `playwright-core` are pinned to 1.62.1, matching the cached browser build; `@axe-core/playwright` otherwise pulled in a second `playwright-core` (1.63.0) and broke type-checking.

## Changes outside `web/e2e/`

- `web/package.json`: scripts `test:e2e` and `test:e2e:model-down`; dev dependencies `@playwright/test` 1.62.1, `playwright-core` 1.62.1, `@axe-core/playwright` 4.13.0, `axe-core` 4.13.0, `@types/node` 24.
- `web/.gitignore`: `e2e/artifacts/`.
- `web/src/**`: no changes. No `data-testid` was added; every locator uses roles, labels, visible text or existing structure.

## Results

Visitor, Ask, media, facets (except date), compile, explore, offline (except item reload), and all 21 axe routes are from the first `npm run test:e2e` (4.7 min, 50 passed / 3 failed / 1 skipped / 8 staff tests not run). Staff numbers are from a later serial rerun after test-only locator fixes (`playwright-staff-rerun3.log`, exit 0). Model-down is a separate project after `stack.ps1 llm-down` (`playwright-model-down.log`, 1 passed).

| Spec | Tests | Passed | Failed | Skipped | Expected fail |
|---|---:|---:|---:|---:|---:|
| `01-visitor-kiosk.e2e.ts` | 8 | 7 | 0 | 1 | 0 |
| `02-ask.e2e.ts` | 2 | 2 | 0 | 0 | 0 |
| `03-media.e2e.ts` | 3 | 3 | 0 | 0 | 0 |
| `04-content-types.e2e.ts` | 3 | 3 | 0 | 0 | 0 |
| `05-constitution.e2e.ts` | 1 | 1 | 0 | 0 | 0 |
| `06-facets.e2e.ts` | 4 | 3 | 1 | 0 | 0 |
| `07-compile.e2e.ts` | 1 | 1 | 0 | 0 | 0 |
| `08-explore-signage.e2e.ts` | 4 | 4 | 0 | 0 | 0 |
| `09-offline.e2e.ts` | 3 | 2 | 1 | 0 | 0 |
| `10-staff.e2e.ts` | 12 | 10 | 0 | 1 | 1 |
| `a11y.e2e.ts` | 21 | 21 | 0 | 0 | 0 |
| `ask-model-down.e2e.ts` | 1 | 1 | 0 | 0 | 0 |
| **Total** | **63** | **58** | **2** | **2** | **1** |

Skipped: machine-translation chip (no Sarvam key on this stack); Sarvam-vs-local OCR diff (same). Expected fail: restore a withdrawn item (`test.fail`, restore is not landed).

### Test-only fixes (`web/e2e/` only)

- `10-staff.e2e.ts`: page-review status is now `Page decision recorded: Approve.` / `Page decision recorded: Correct.` (i18n `stPageDecision`), not `Page approved.` / `Page correctd.`.
- `10-staff.e2e.ts`: Constitution submit button is `Add a link` (`stAddLink`), not `Add link`.
- `10-staff.e2e.ts`: Sarvam-diff test skips when `/api/health/ready` reports `sarvam_configured: false`, so the serial workflow is not aborted by a catalog scan.
- `fixtures.ts`: `askGuard` counts only Ask POSTs that can reach a live model (excludes project `model-down` and offline specs).

### Gaps

- Date-range search is still asserted and still fails (product 500; see below).
- Offline reload of `/item/{id}` is still asserted and still fails (no service-worker navigation fallback).
- Restore remains `test.fail` until a restore path ships.
- 2026-09-27: the restore test (and the withdraw test's 410 / withdrawn-notice assertions) now asserts the real restore behaviour without `test.fail`; it still needs a rerun on a rebuilt e2e image.
- Machine translation and Sarvam OCR diff are untested on this stack by design (no Sarvam key).

## Product bugs

1. **High — date-range search returns HTTP 500.** `backend/archive/search/hybrid.py` lines 111–114 compare `ArchivalItem.date_start` / `date_end` (`date`) to query strings without a cast. Postgres: `operator does not exist: date >= character varying`. Repro: `GET https://localhost:9443/api/visitor/search?q=library%20board&date_from=1927-01-01&date_to=1927-12-31`. The UI keeps the unfiltered hits. Test: `06-facets` › date range. Screenshot and trace in `artifacts/test-results/06-facets.e2e.ts-Facets-an-6ac6f-arch-results-to-that-period-kiosk-chrome/`.
2. **Medium — reloading a saved item address while offline fails.** `web/src/sw.ts` precaches the app shell but has no navigation fallback, so `page.reload()` on `/item/{id}` throws `net::ERR_INTERNET_DISCONNECTED`. In-session client-side navigation to a cached item still works. Test: `09-offline` › reloading a saved item's address. Trace: `artifacts/test-results/09-offline.e2e.ts-Offline--26d2e-hile-offline-still-opens-it-kiosk-chrome/`.
3. **Medium — no restore for a withdrawn item.** The staff item page has no restore control. `item_ready_for_publication` in `backend/archive/ingest/review.py` blocks republication with "item is withdrawn; re-publication needs a rights decision and new review". Test: `10-staff` › restore a withdrawn item (marked `test.fail` on 2026-09-27; not deleted). Product decision still needed.
4. **High for a fresh seed — essay fixture checksum is stale.** `fixtures/manifests/fixture_manifest.json` lists sha256 `84c8bb9f…` for `fx-essay-reading-rooms.pdf`; the file on disk/in the container is `f1f8f689…` (2117 bytes). `store_original` quarantines it, so `seed-fixtures` imports item 1 with 0 pages and never publishes "On Public Reading Rooms". Repro: `stack.ps1 seed` then `GET /api/staff/items/1` → `ready: false`, `problems: ["no pages"]`. This run attached the PDF in the throwaway stack only; product/fixture files were not changed.

The earlier write-time note that correction confirmations read "Page correctd." is **not** what the running UI does. `Staff.tsx` now uses `t("stPageDecision", { action })`, which reads "Page decision recorded: Approve." / "Page decision recorded: Correct." The staff test was updated to that copy.

## Accessibility findings

axe-core 4.13.0 with tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa` on 21 visitor surfaces (home, high-contrast 130 %, Hindi home, search, photographs, essay/debate/photo/audio/video readers, Ask, timeline, stories, story, connections, connections with a name chosen, constitution index and article, QR list, phone list, signage). **0 violations** on every route. Serious and critical would have failed the test. Full per-route file: `web/e2e/artifacts/a11y/summary.json`.

## Skills used

| Skill | Source | Effect on this suite |
|---|---|---|
| find-skills | `C:\Users\cvbal\.agents\skills\find-skills\SKILL.md` | Local skills were searched first; local skills covered every part, so no marketplace skill was installed |
| playwright-pro | `C:\Users\cvbal\.claude\plugins\cache\claude-code-skills\engineering-skills\2.2.0\playwright-pro\SKILL.md`, `reference\golden-rules.md`, `skills\review\anti-patterns.md` | Role and label locators; web-first assertions with no fixed sleeps; `baseURL` in config; `test.extend` fixtures (`api`, `fx`, `boxed`, `askGuard`); retries 0 and traces kept on failure. The anti-pattern review led to per-test catalog reads and to the documented serial exception for the staff workflow |
| senior-qa | `...\engineering-skills\2.2.0\senior-qa\SKILL.md` | Coverage mapped to the ten areas in the task plus accessibility; failure paths included (off-topic, model down, expired link, offline, withdrawn) |
| tdd-guide | `...\engineering-skills\2.2.0\tdd-guide\SKILL.md` | Tests assert the specified behaviour (spec 5.7 answer label, withdrawal reach, lease) rather than current output, so a real product gap fails |
| a11y-audit | `...\engineering-skills\2.2.0\a11y-audit\SKILL.md` | axe with WCAG 2.2 AA tags on every visitor route and on the high-contrast, Hindi and phone variants; serious and critical violations fail the test |
| browser-automation | `...\engineering-advanced-skills\2.2.0\browser-automation\SKILL.md` | Separate browser contexts for kiosk, phone and staff; offline emulation; clock control |
| docker-development | `...\engineering-advanced-skills\2.2.0\docker-development\SKILL.md` | Compose override with separate project, images, volumes and ports; shell-variable ports because override `ports:` lists are appended |
| verification-before-completion | `C:\Users\cvbal\.claude\plugins\cache\claude-plugins-official\superpowers\6.4.1\skills\verification-before-completion\SKILL.md` | Counts and product bugs below are taken from this run's Playwright logs and API responses, not from earlier leftover `results.json` |
| technical-writing | `C:\Users\cvbal\.claude\skills\technical-writing\SKILL.md` | This document: conclusion first, sourced claims, no unverified results |
