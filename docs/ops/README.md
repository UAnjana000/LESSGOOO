# Operations: production deployment [PROD]

These runbooks cover the institution deployment in `deploy/production/`. They apply spec section 9 (institution-scale deployment) and the production column of section 6.5 to the existing FastAPI + PostgreSQL/pgvector + PWA stack. Nothing here changes the application.

## Prototype vs production

The repository-root `docker-compose.yml` is the section 3 SIH prototype: one mini PC runs everything. It is a demo and is **not institution-ready**. Do not put it in a gallery.

| Concern | Local demo (`docker-compose.yml`) | Production (`deploy/production/compose.yaml`) |
| --- | --- | --- |
| Purpose | SIH round-one demo on one edge server | One institution site, spec section 9 |
| Secrets | Root `.env` (demo values, includes `ARCHIVE_DEMO_STAFF_PASSWORD`) | Docker secrets, one file each, outside git; `.env` holds non-secret settings only |
| Staff accounts | Admin + four demo accounts | Admin only; demo accounts forced off |
| Content | `fixtures/`, `eval/`, `intake/` bind-mounted | No fixtures or eval data mounted; intake share read-only to `ops` only |
| HTTPS | Caddy internal CA on `localhost` | Institution or public certificates; separate visitor and staff listeners |
| Access boundary | One site serves everything | Gallery listener serves only the visitor API, IIIF and the PWA; staff API only on the staff listener |
| Preservation masters | Docker volume on the same disk as everything else | Bind mount to a dedicated disk that must be mounted (start-up fails otherwise) |
| Backups | Docker volume on the same disk | Separate backup disk, SHA-256 verified, verified off-site copy, scheduled restore drill |
| Database | Port published on localhost | No published port, internal network only, data checksums on |
| Migrations | `alembic upgrade head` inside every api start | One-shot `migrate` service runs before any api/worker replica |
| Worker health | Inherits the api HTTP check, so shows `unhealthy` | Process + database check |
| Scaling | Single container per service | `--scale api=N` behind the proxy, `--scale worker=N`, CPU caps favour visitors |
| Logs | Default Docker logging | JSON logs, rotated (20 MB x 10 per container) |
| Images | Dev dependencies included | `INSTALL_DEV=0`; built only by the release script |

## Runbooks

| Topic | Document |
| --- | --- |
| Topology, networks, access boundary, storage, scaling path | [topology.md](topology.md) |
| Host preparation, first start, migrations, upgrades, rollback | [startup-and-migrations.md](startup-and-migrations.md) |
| Secrets inventory, Docker secrets, rotation | [secrets.md](secrets.md) |
| Certificates, kiosk trust, firewall, boundary checks | [https-and-access.md](https-and-access.md) |
| Healthchecks, readiness, structured logs, monitoring | [health-and-logs.md](health-and-logs.md) |
| Backup, off-site copy, fixity, restore drill, disaster recovery | [backup-and-restore.md](backup-and-restore.md) |

## What has and has not been run

**Run (smoke test on a developer workstation, 26 Sep 2026).** The production compose file was run under a separate project name, with localhost-only ports, temp folders standing in for the disks, generated test secrets and a throwaway certificate. Lightweight embedding backends were used to save RAM. The following worked:

- **Build and start.** `Invoke-ReleaseBuild.ps1` built the api, web and ops images. All six services came up healthy. `migrate` ran once, and the admin account was created from its Docker secret.
- **Gallery listener.** It served the PWA and visitor API, and returned 404 for the staff API, readiness details and the API docs. Oversized visitor bodies got 413.
- **Staff listener.** It accepted login, a rights entry and a synthetic page upload. The worker ingested the page, and the preservation master landed on the separate preservation mount.
- **Secrets.** No secret value appeared in `docker compose config` or `docker inspect`.
- **Scaling.** `--scale api=2` split 12 visitor requests 6/6 across the two replicas.
- **Backup.** The backup script produced a backup, verified it, copied it off-site and verified the copy. A deliberately corrupted off-site file was detected.
- **Restore drill.** It passed: dump checksum, 6 of 6 files, 3 of 3 `file_version` rows, and the audit hash chain. The scratch copy was then dropped.
- **Disaster recovery.** After destroying all volumes and the preservation folder, `dr-restore.sh` restored the backup. In-place fixity reported 3 of 3 files and 0 failures, the audit chain verified, the stack returned healthy, and the admin could sign in.

These test results are recorded in the smoke-test section of each runbook. **This was not a production deployment.** No institution server, certificate, preservation disk or network was involved.

**Cannot be executed from the repository.** These steps need the real site:

- Obtaining and installing real certificates and trusting them on kiosks.
- Provisioning the preservation, backup and off-site disks.
- Gallery/staff VLANs, switch ACLs and Windows Firewall rules.
- Lenovo tablet kiosk mode, the smart display player and the digitisation station hardware.
- The spec 3.4 capacity benchmark that sets the CPU/memory numbers.
- Provider contracts and data-location checks (spec 6.2).
- Uptime/disk alerting.
- The quarterly restore test on the real backup set.

## Findings for other owners (not changed here)

- **Backup/restore tool version mismatch (backend image).** `backend/Dockerfile` installs Debian bookworm `postgresql-client` (15), but the database is PostgreSQL 17. `pg_dump` aborts with "server version mismatch", so `archive.cli backup` fails in the local demo too. Production works around this with `deploy/production/ops/Dockerfile` (PostgreSQL 17 client). The proper fix is to install `postgresql-client-17` from the PGDG repository in the backend image.
- **Local worker shows `unhealthy`.** It inherits the image's HTTP healthcheck on port 8000, which the worker does not serve.
- **Root `.env.example` points to `docs/DEPLOYMENT.md`, which does not exist.** These runbooks are the production reference.
- **No `_FILE` or secrets-directory support in `backend/archive/config.py`.** Production bridges this with `deploy/production/scripts/with-secrets.sh`. Adding `secrets_dir="/run/secrets"` to the settings would remove the shim.
- **No staff password-change endpoint and no worker heartbeat.** See [secrets.md](secrets.md) and [health-and-logs.md](health-and-logs.md).
