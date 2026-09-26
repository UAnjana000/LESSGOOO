# deploy/production [PROD]

Institution deployment of the Dr. B. R. Ambedkar Digital Heritage Archive (spec section 9) on a single Windows host running Docker. The repository-root `docker-compose.yml` is the section 3 SIH prototype and is **not institution-ready**.

Runbooks: [docs/ops/README.md](../../docs/ops/README.md).

| Path | Purpose |
| --- | --- |
| `compose.yaml` | db (PostgreSQL 17 + pgvector), migrate (one-shot), api, worker, web, proxy; `ops` on demand |
| `.env.example` | Non-secret site settings. Copy to `.env` (git-ignored) |
| `secrets/` | Docker secret files, one value each (git-ignored; see `secrets/README.md`) |
| `certs/` | TLS certificates and keys (git-ignored) |
| `caddy/Caddyfile` | Edge proxy: HTTPS, gallery listener `:443`, staff listener `:8443` |
| `caddy/web.Caddyfile` | Static PWA server behind the proxy |
| `logging/uvicorn-log.json` | JSON logging for uvicorn |
| `ops/Dockerfile` | Ops image: api image plus PostgreSQL 17 client tools for backup/restore |
| `scripts/Invoke-ReleaseBuild.ps1` | Builds the api, web and ops images for `RELEASE_TAG` (the only build step) |
| `scripts/New-ProductionSecrets.ps1` | Generates secret files; never prints values |
| `scripts/Test-ProductionConfig.ps1` | Pre-flight checks |
| `scripts/Invoke-ArchiveBackup.ps1` | Backup, SHA-256 verification, verified off-site copy |
| `scripts/Test-BackupManifest.ps1` | Verify any backup folder against its manifest |
| `scripts/Invoke-RestoreDrill.ps1`, `scripts/restore-drill.sh` | Non-destructive scheduled restore test |
| `scripts/dr-restore.sh` | Disaster-recovery restore onto an empty installation |
| `scripts/with-secrets.sh` | Container entrypoint mapping `/run/secrets/*` to `ARCHIVE_*` variables |

## Quick start (PowerShell, in this folder)

```powershell
Copy-Item .env.example .env; notepad .env
.\scripts\New-ProductionSecrets.ps1
.\scripts\Test-ProductionConfig.ps1
.\scripts\Invoke-ReleaseBuild.ps1
docker compose --env-file .env -f compose.yaml up -d
docker compose --env-file .env -f compose.yaml ps
```

Before the first start, read `docs/ops/startup-and-migrations.md` (disks, certificates, firewall). Never run `docker compose down -v` here: it deletes the database volume.
