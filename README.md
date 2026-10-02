# Dr. B. R. Ambedkar Digital Heritage Archive

Software for a digital heritage archive of Dr. B. R. Ambedkar's writings, speeches and the Constituent Assembly Debates. Staff bring in scans and PDFs, local OCR reads them, a quality gate and human review decide what is accepted, and only approved text is published. Visitors search, read the text beside the original scan, ask questions that are answered only from cited archive passages, and listen to labelled synthetic narration, in English, Hindi and Marathi.

This repository is the **software only**. The gallery hardware (the edge mini PC, the tablet kiosks, the smart display and the digitisation station) is a later stage, and nothing here has run on it yet. The design is in [`Ambedkar Digital Heritage Archive — Revised Architecture Spec.md`](<Ambedkar Digital Heritage Archive — Revised Architecture Spec.md>).

The root `docker-compose.yml` is the local demo: one machine runs every service. It is a prototype and is **not institution-ready**. The production layout lives in `deploy/production/` and is described in [`docs/ops/README.md`](docs/ops/README.md).

## What runs in the local demo

Docker Compose project `ambedkar-archive`, defined in `docker-compose.yml`:

| Service | Image | Role |
| --- | --- | --- |
| `db` | `pgvector/pgvector:0.8.1-pg17` | PostgreSQL 17 with pgvector: the system of record |
| `api` | `ambedkar-archive/api:local` (built from `backend/`) | FastAPI. On every start it runs `alembic upgrade head`, then `archive.cli bootstrap` (creates staff accounts), then serves on port 8000 inside the network |
| `worker` | `ambedkar-archive/api:local` (same image as `api`) | Background jobs: ingestion, OCR, publishing, nightly backup |
| `proxy` | `ambedkar-archive/proxy:local` (built from `web/Dockerfile`) | Caddy. It contains the built web app, terminates HTTPS with Caddy's internal CA, and forwards `/api/*` and `/iiif/*` to `api` |

There is no separate web service: the web app is inside the proxy image.

## Prerequisites

- Windows with Docker Desktop (WSL2 backend) and PowerShell.
- Free host ports: `8443` (HTTPS), `8088` (HTTP, redirects to HTTPS) and `127.0.0.1:55432` (database).
- Time for the first build: the api image downloads the embedding and reranking models while it builds. On the demo machine `docker compose build api` took about 6.5 minutes.

## Start the website

Run every command from the repository root, in PowerShell.

1. **Create `.env` from the example.** Skip this step if `.env` already exists; copying over it would discard the keys already in it.

   ```powershell
   Copy-Item .env.example .env
   ```

2. **Fill in `.env`.** Open it in an editor and replace every `change-me-…` value with your own. Never commit `.env` (it is gitignored).

   | Setting | What to put there |
   | --- | --- |
   | `POSTGRES_PASSWORD` | A database password. Set it before the first start: the database volume keeps the password it was created with |
   | `ARCHIVE_JWT_SECRET` | A random string of at least 32 characters (signs staff sessions) |
   | `ARCHIVE_BOOTSTRAP_ADMIN_EMAIL`, `ARCHIVE_BOOTSTRAP_ADMIN_PASSWORD` | The first admin account |
   | `ARCHIVE_DEMO_STAFF_PASSWORD` | Password for the four demo staff accounts (see [Entry points](#entry-points)). Leave it empty to create no demo accounts |
   | `ARCHIVE_SARVAM_API_KEY` | Optional. Sarvam AI key for OCR fallback, translation and text-to-speech. Empty disables them: failed-gate pages wait for review, on-demand translation shows "needs connection", and narration uses offline espeak-ng |
   | `ARCHIVE_LLM_PROVIDER`, `ARCHIVE_LLM_BASE_URL`, `ARCHIVE_LLM_API_KEY`, `ARCHIVE_LLM_MODEL` | Optional. An OpenAI-compatible answer model for Ask. With `ARCHIVE_LLM_PROVIDER=none`, Ask returns labelled extractive passages instead of a generated answer |
   | `ARCHIVE_LLM_INPUT_COST_PER_MTOK`, `ARCHIVE_LLM_OUTPUT_COST_PER_MTOK` | Optional price per million tokens. At `0`, Ask records a cost of 0 |
   | `ARCHIVE_LANGFUSE_*` | Leave empty unless you run the optional Langfuse stack ([`docs/LANGFUSE.md`](docs/LANGFUSE.md)). Empty means traces go to a redacted local JSONL file in the `traces` volume |
   | `SITE_ADDRESS`, `ARCHIVE_PUBLIC_BASE_URL` | Keep `localhost` and `https://localhost:8443` for a local run |
   | `HTTP_PORT`, `HTTPS_PORT` | Keep `8088` and `8443`. The compose default HTTP port is 8080, which is taken on the demo machine; without `HTTP_PORT=8088` the proxy fails with `bind 0.0.0.0:8080` |

3. **Build the images.**

   ```powershell
   docker compose build api proxy
   ```

   The `worker` uses the `api` image, so it needs no separate build.

4. **Start the stack.**

   ```powershell
   docker compose up -d
   ```

   Compose starts `db` first, then `api` once the database is healthy, then `worker` and `proxy` once the api is healthy.

5. **Check that it is ready.**

   ```powershell
   docker compose ps
   curl.exe -k https://localhost:8443/api/health/ready
   ```

   All four services should show `healthy`, and the readiness call should return HTTP 200 with `"status": "ready"`. The api can take a minute or more after `up` before it reports healthy.

6. **Open the site at <https://localhost:8443>.** The browser warns about the certificate, because Caddy signs `localhost` with its own internal CA. Accept the warning for local use. Chrome does not register the service worker over an untrusted certificate, so offline exhibit mode does not work until the browser trusts Caddy's root certificate.

### After changing `.env` or the code

The `api` and `worker` containers read `.env` only when they are created. After editing `.env`, recreate them (the database and its data are left alone):

```powershell
docker compose up -d --force-recreate --no-deps api worker
```

After code changes, rebuild and recreate. The api applies any pending database migrations when it starts.

```powershell
docker compose build api proxy
docker compose up -d --force-recreate --no-deps api worker proxy
```

## Entry points

In the local demo, one HTTPS site serves both visitors and staff. Production splits them into separate listeners ([`docs/ops/https-and-access.md`](docs/ops/https-and-access.md)).

| Who | Address | What it is |
| --- | --- | --- |
| Visitor | `/` | Home: collections, search and navigation |
| Visitor (gallery tablet) | `/?kiosk=1` | Kiosk mode, remembered on that browser; `/?kiosk=0` turns it off. See [Kiosk mode](#kiosk-mode) |
| Visitor (gallery tablet, dock layout) | `/kiosk` | Dock-style kiosk with a virtual keyboard. Same idle policy; the Staff button goes to `/staff`, which has its own sign-in |
| Visitor | `/search`, `/ask`, `/item/<id>` | Search, Ask with citations, and the reader (text beside the scan) |
| Visitor | `/timeline`, `/stories`, `/map`, `/constitution`, `/list` | Curated timeline, stories, connections, Constitution articles, and the visitor's own list with a QR code |
| Visitor (phone) | `/c/<token>` | A shared list opened from a QR code |
| Smart display | `/display` | Signage rotation |
| Staff | `/staff/login` | Staff sign-in. After sign-in: dashboard `/staff`, intake `/staff/intake`, review queue `/staff/review`, items `/staff/items`, rights register `/staff/rights`, jobs `/staff/jobs`, audit log `/staff/audit` |
| Operator | `/api/health/ready` | Readiness: database, storage and provider configuration |

Staff accounts come from `.env` the first time the api starts: the admin from `ARCHIVE_BOOTSTRAP_ADMIN_*`, and, when `ARCHIVE_DEMO_STAFF_PASSWORD` is set, `archivist@demo.local`, `curator@demo.local`, `reviewer-hi@demo.local` and `reviewer-mr@demo.local`. Bootstrap skips accounts that already exist, so changing a password in `.env` later does not change an existing account.

### Kiosk mode

Open `/?kiosk=1` once on a gallery screen (`?kiosk=0` undoes it; a fullscreen-installed PWA also counts). Kiosk mode:

- warns 30 s before `session_idle_seconds` of inactivity, then ends the visit (list, Ask history, text size and contrast are cleared) and shows the attract screen;
- locks the screen down: fullscreen on the first touch, no context menu, no text selection outside inputs, and links stay inside the app. Pinch-zoom stays available;
- registers the service worker. Offline it keeps the app shell and serves the signed, leased exhibit cache (published, public items only). Ask and staff requests are never cached.

The public website never runs a service worker; any left over from an earlier load is removed. `/kiosk` is the dock-style variant of the same behaviour.

## Content

A fresh stack starts with an empty archive and the staff accounts only. Material enters through staff intake and review. The real source PDFs are not in git (`/data/` is gitignored); [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) lists them, and the manifests in `intake/` hold their metadata.

To try the site with synthetic demo items, load the fixtures. They are labelled synthetic, are not archive material, and must never be used in a gallery.

```powershell
docker compose exec -T api python -m archive.cli seed-fixtures
```

## Stop without losing data

```powershell
docker compose stop
```

Start again with `docker compose up -d`. All data lives in named Docker volumes: `pgdata` (the database), `preservation` (original files), `delivery`, `derivatives`, `quarantine`, `traces`, `backups`, and `caddy_data` / `caddy_config` (Caddy's certificate authority).

> **Never run `docker compose down -v`.** The `-v` flag deletes every named volume above: the database, the preservation masters, the backups and the certificates. `docker compose down` without `-v` keeps the volumes, but `stop` is the safer habit.

If the optional Langfuse stack is running, stop it separately with `docker compose -f docker-compose.langfuse.yml stop`.

## Logs and common problems

```powershell
docker compose logs -f --tail 100 api worker proxy
```

| Symptom | Cause and fix |
| --- | --- |
| Proxy fails with `bind 0.0.0.0:8080: Only one usage of each socket address` | Host port 8080 is taken. Set `HTTP_PORT=8088` in `.env` (or `$env:HTTP_PORT="8088"` in the shell) and run `docker compose up -d` again |
| Browser certificate warning on `https://localhost:8443` | Expected: Caddy's internal CA. See step 6 |
| A new key in `.env` has no effect | The containers still hold the old value. Recreate `api` and `worker` (see [After changing `.env` or the code](#after-changing-env-or-the-code)) |
| Host tools hang connecting to `localhost:55432` | `localhost` can resolve to IPv6 `::1` first, which stalls. Use `127.0.0.1:55432` |

## Tests

Backend, from `backend/`, with the project virtual environment at `backend/.venv`. The suite creates and migrates its own `archive_test` database on the compose Postgres and replaces Sarvam, the answer model and Langfuse with test doubles.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Web, from `web/`:

```powershell
npx tsc -p . --noEmit
npx vitest run
```

The Playwright end-to-end suite runs against its own throwaway stack (project `ambedkar-e2e`, ports 9443, 9088 and 56432), never against the demo; see [`docs/E2E_UI_TESTS.md`](docs/E2E_UI_TESTS.md).

## Documentation

| Topic | Document |
| --- | --- |
| Architecture and scope | [`Ambedkar Digital Heritage Archive — Revised Architecture Spec.md`](<Ambedkar Digital Heritage Archive — Revised Architecture Spec.md>) |
| Requirements checklist and status | [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) |
| Source files and rights | [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) |
| Run on real source excerpts | [`docs/E2E_REAL_DATA.md`](docs/E2E_REAL_DATA.md) |
| Live provider tests and Docker recovery | [`docs/LIVE_TEST.md`](docs/LIVE_TEST.md), [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md) |
| Local OCR engine decision | [`docs/OCR_ENGINE_EVAL.md`](docs/OCR_ENGINE_EVAL.md) |
| Ask and ingestion review | [`docs/ARCHITECTURE_REVIEW.md`](docs/ARCHITECTURE_REVIEW.md) |
| Accessibility and EN/HI/MR interface | [`docs/A11Y_I18N.md`](docs/A11Y_I18N.md) |
| Synthetic narration | [`docs/NARRATION.md`](docs/NARRATION.md) |
| Langfuse tracing | [`docs/LANGFUSE.md`](docs/LANGFUSE.md) |
| Hard negatives, backup and restore drill | [`docs/DATASETS_AND_BACKUP.md`](docs/DATASETS_AND_BACKUP.md) |
| Browser end-to-end tests | [`docs/E2E_UI_TESTS.md`](docs/E2E_UI_TESTS.md) |
| Production deployment runbooks | [`docs/ops/README.md`](docs/ops/README.md) |
| Evaluation | [`eval/README.md`](eval/README.md), [`eval/RESULTS.md`](eval/RESULTS.md) |

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI app, worker, ingestion and Ask graphs, Alembic migrations, tests |
| `web/` | React PWA (visitor, kiosk, signage and staff screens), unit and Playwright tests |
| `deploy/` | Local-demo Caddyfile and backup scripts, Langfuse helpers, production compose and scripts |
| `docs/` | Records and runbooks listed above |
| `eval/` | Evaluation harnesses, templates and results |
| `fixtures/` | Synthetic demo items and their manifest |
| `intake/` | Metadata manifests for the real source excerpts |
