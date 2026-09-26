# Health checks, logs and monitoring [PROD]

## Container healthchecks

| Service | Check | Interval | Gate |
| --- | --- | --- | --- |
| `db` | `pg_isready -U archive -d archive` | 10 s | `migrate`, `api`, `worker` and `ops` wait for it |
| `migrate` | One-shot; must exit 0 | — | `api` and `worker` wait for successful completion |
| `api` | `GET /api/health/ready` returns 200: database reachable, Alembic revision present, derivatives store writable | 15 s, 90 s start period | `proxy` waits for it |
| `worker` | PID 1 alive and the database reachable. This overrides the image's HTTP check, which the worker cannot pass | 30 s | — |
| `web` | `GET http://127.0.0.1:8080/healthz` | 15 s | `proxy` waits for it |
| `proxy` | `GET http://127.0.0.1:8081/healthz`, a container-internal listener that is not published | 15 s | — |

All long-running services use `restart: unless-stopped`.

```powershell
docker compose --env-file .env -f compose.yaml ps
docker inspect --format '{{json .State.Health}}' ambedkar-archive-prod-api-1 | ConvertFrom-Json | Select-Object Status, FailingStreak
```

## HTTP endpoints

| Endpoint | Gallery listener | Staff listener | Returns |
| --- | --- | --- | --- |
| `/api/health` | yes | yes | Liveness: `status`, `version` |
| `/api/health/ready` | **404** | yes | `database`, `migration` (Alembic revision), `storage`, `models`, `trace_backend`, `sarvam_configured`, `llm_configured`; 503 when not ready |

`models` reports the embedding and reranker backends. In production they must be the fastembed models baked into the image, not `hash`/`lexical`.

## Structured logs

| Source | Format | Notes |
| --- | --- | --- |
| api | JSON (`ts`, `level`, `logger`, `message`, extras) | uvicorn's own lines also go through the JSON formatter (`deploy/production/logging/uvicorn-log.json`). One `request` line per call with `request_id`, `method`, `path`, `status`, `ms`. `x-request-id` is returned to clients |
| worker | JSON | `job start` / `job done` / `job failed` with `job_id`, `kind` |
| proxy | JSON (Caddy) | Access log per request (`remote_ip`, `host`, `uri`, `status`, `duration`). Caddy redacts `Authorization` and `Cookie`. Search query strings appear in URIs |
| web | JSON (Caddy) | Start-up only; access is logged at the proxy |
| db | PostgreSQL text | JSON logging would need `logging_collector` writing to files, which bypasses Docker logs |
| migrate, ops | JSON logs plus a pretty-printed JSON report | One-shot command output |

Docker's `json-file` driver rotates at `LOG_MAX_SIZE` x `LOG_MAX_FILE` per container (default 20 MB x 10). To forward logs to the institution's log platform, change the `x-logging` anchor in `compose.yaml` (for example to `fluentd`, or `local` plus a collector).

```powershell
# Errors from the api in the last hour
docker compose --env-file .env -f compose.yaml logs --no-log-prefix --since 1h api |
    Where-Object { $_ -like '{*' } | ConvertFrom-Json | Where-Object level -in 'ERROR','CRITICAL' |
    Select-Object ts, logger, message, path

# Failed jobs
docker compose --env-file .env -f compose.yaml logs --no-log-prefix --since 24h worker |
    Where-Object { $_ -like '{*' } | ConvertFrom-Json | Where-Object message -eq 'job failed'

# Trace one request across proxy and api
docker compose --env-file .env -f compose.yaml logs --no-log-prefix api | Select-String '<request_id>'
```

The api access log records `path` but not query strings or request bodies. Ask questions follow the tracing redaction rules (spec 6.6).

## Monitoring checklist (spec 6.5 "uptime, disk, queue and kiosk heartbeat alerting")

None of this is shipped as a running service. The institution wires these checks into its own monitoring.

| Signal | How to read it |
| --- | --- |
| Uptime | Poll `https://<VISITOR_SITE>/api/health` from the gallery network and `https://<STAFF_SITE>:8443/api/health/ready` from the staff network |
| Container health | `docker compose ... ps --format json` and alert on any status other than `healthy` |
| Disk | Free space on the preservation disk, the backup disk and the Docker disk image: `Get-PSDrive P, B` |
| Queue | Staff API `GET /api/staff/jobs` (queued/running/failed counts), or `failed` entries in worker logs |
| Backups, fixity, restore drill | Task Scheduler "Last Run Result" for the three tasks in [backup-and-restore.md](backup-and-restore.md) |
| Certificates | Expiry of `certs/*.crt` ([https-and-access.md](https-and-access.md)) |
| LLM cost | `ARCHIVE_DAILY_COST_ALERT_USD` and Langfuse (separate machine) |
| Kiosk heartbeat | **Not implemented in the application.** Kiosks call `/api/visitor/exhibit/manifest` and `/api/visitor/withdrawals` on sync; proxy access logs by client IP are the interim signal (only where real IPs are visible). Device management (MDM) is [PROD] |

Known gap: the worker has no heartbeat, so its healthcheck proves the process and database connection, not that jobs are progressing. Watch the job queue for jobs stuck in `running`. A worker heartbeat is a backend change.
