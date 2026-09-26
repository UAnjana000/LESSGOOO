# Secrets [PROD]

Production secrets are **Docker secrets**: one file per value in `SECRETS_DIR`, populated from the institution's secret store, never committed and never placed in `.env`.

The repository-root `.env` configures the local demo only. Do not copy its values into `deploy/production`, these docs, tickets or git; production uses its own credentials and provider keys.

## Inventory

Names match `backend/archive/config.py`. This document lists names only, never values.

**Secret: Docker secret files**

| Secret file | Becomes | Granted to | Source |
| --- | --- | --- | --- |
| `postgres_password` | `POSTGRES_PASSWORD_FILE` (db); password inside `ARCHIVE_DATABASE_URL` (app) | db, migrate, api, worker, ops | Generated |
| `jwt_secret` | `ARCHIVE_JWT_SECRET` | migrate, api, worker | Generated |
| `bootstrap_admin_password` | `ARCHIVE_BOOTSTRAP_ADMIN_PASSWORD` | migrate | Generated; empty it after the first start |
| `sarvam_api_key` | `ARCHIVE_SARVAM_API_KEY` | api, worker | Secret store; empty = Sarvam disabled |
| `llm_api_key` | `ARCHIVE_LLM_API_KEY` | api, worker | Secret store; required when `ARCHIVE_LLM_PROVIDER=openai_compatible` |
| `langfuse_secret_key` | `ARCHIVE_LANGFUSE_SECRET_KEY` | api, worker | Secret store; optional |

**Not secret: `deploy/production/.env`**

- `ARCHIVE_LLM_PROVIDER`: `none` or `openai_compatible`.
- `ARCHIVE_LLM_BASE_URL`: the provider's OpenAI-compatible endpoint.
- `ARCHIVE_LLM_MODEL`: the answer model id chosen by the institution. The local demo's choice does not carry over automatically; record the production choice and its data-handling terms (spec 6.2).
- `ARCHIVE_LLM_INPUT_COST_PER_MTOK`, `ARCHIVE_LLM_OUTPUT_COST_PER_MTOK`, `ARCHIVE_DAILY_COST_ALERT_USD`.
- `ARCHIVE_LANGFUSE_PUBLIC_KEY`, `ARCHIVE_LANGFUSE_HOST`, `ARCHIVE_TRACE_QUESTION_MODE`.
- `ARCHIVE_BOOTSTRAP_ADMIN_EMAIL`, `ARCHIVE_JWT_TTL_MINUTES`, `ARCHIVE_PUBLIC_BASE_URL`, `ARCHIVE_CORS_ORIGINS`, `ARCHIVE_EXHIBIT_LEASE_HOURS`, `ARCHIVE_QR_LINK_TTL_HOURS`, `ARCHIVE_LOG_LEVEL`.

`ARCHIVE_ENVIRONMENT=production`, the storage paths and an empty `ARCHIVE_DEMO_STAFF_PASSWORD` are fixed in `compose.yaml`.

## How it works

1. `compose.yaml` declares each secret with `file: ${SECRETS_DIR}/<name>` and grants each service only the ones it needs.
2. Compose mounts them read-only at `/run/secrets/<name>`. PostgreSQL reads `POSTGRES_PASSWORD_FILE` natively.
3. The app containers start through `scripts/with-secrets.sh`. It builds `ARCHIVE_DATABASE_URL` and exports the other `ARCHIVE_*` names for the process, then execs the real command. The backend has no `_FILE` support, so this shim is the bridge.

Verified in the smoke test: none of the generated values appeared in `docker compose config` output or in `docker inspect` of api, worker or db.

Limits to know:

- **Values are plain files on the host.** Compose without Swarm does not encrypt them. Protect them with NTFS permissions (the generator restricts them to the operator, Administrators and SYSTEM) and BitLocker, and keep `SECRETS_DIR` outside the repository on a real server.
- **Values are visible inside a running container**, for example in `/proc/1/environ`, to anyone who can `docker exec`. Docker access is administrator access; limit `docker-users`.
- **Healthchecks and `docker exec` bypass the entrypoint.** The worker healthcheck calls the shim explicitly. For CLI tasks use `docker compose run --rm ops ...`.
- **Linux hosts:** Compose ignores `uid`/`gid`/`mode` for file secrets. The files must be readable by uid 10001 (app) and by the postgres entrypoint.

## Creating

```powershell
.\scripts\New-ProductionSecrets.ps1                           # or -SecretsDir E:\archive-secrets (set SECRETS_DIR to match)
```

The script generates `postgres_password`, `jwt_secret` and `bootstrap_admin_password` with a CSPRNG. The database password is URL-safe because it is embedded in the connection URL. The script also creates empty provider key files, refuses to overwrite, and never prints values.

To fill a provider key without it landing in shell history:

```powershell
$k = Read-Host 'LLM API key' -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($k))
[IO.File]::WriteAllText("$PWD\secrets\llm_api_key", $plain); Remove-Variable plain, k
```

Then run `.\scripts\Test-ProductionConfig.ps1`. It checks that every file exists, the password is long and URL-safe, the JWT secret is at least 32 characters, provider keys are present when the provider is enabled, `.env` contains no password/secret/key values, and git tracks nothing under `.env`, `secrets/` or `certs/`.

## Rotation

| Secret | Procedure | Effect |
| --- | --- | --- |
| Provider keys | Replace the file, then `docker compose --env-file .env -f compose.yaml up -d --force-recreate api worker` | None for visitors beyond a restart |
| `jwt_secret` | Replace the file with a new 64-character random value, then `up -d --force-recreate api worker` | All staff sessions end; staff sign in again |
| `postgres_password` | Run `docker compose --env-file .env -f compose.yaml exec db psql -U archive -d archive`, then `\password archive` and enter the new value. Write the same value to `secrets\postgres_password`. Then `up -d --force-recreate api worker` | The file is read by PostgreSQL only at first initialisation; changing only the file does nothing |
| `bootstrap_admin_password` | Empty after first start. It only creates a missing admin account | — |
| Staff passwords | The API has no password-change endpoint (gap for the backend owner). Until one exists, manage staff accounts through the admin role and plan SSO/MFA (spec 6.5) | — |

## Where else sensitive material lives

- **Backups** contain the database (staff password hashes, audit log) and `derivatives/keys/exhibit-signing.pem`, the private key that signs kiosk exhibit manifests. Treat backup disks and off-site copies as confidential: BitLocker or encrypted media, and access limited to operators.
- **TLS private keys** live in `certs/` (git-ignored).
- **`docker compose config`** prints only secret file paths, not values. Still, don't paste full logs into tickets without reading them first.
