# deploy/production/secrets

Default location (`SECRETS_DIR`) of the Docker secret files. On a real server, point `SECRETS_DIR` at a folder outside the repository. Everything here except this README is git-ignored.

Each file holds one value, with no variable name and no trailing newline required. `scripts/with-secrets.sh` maps it onto the backend variable at container start:

| Secret file | Backend variable | Granted to |
| --- | --- | --- |
| `postgres_password` | `POSTGRES_PASSWORD_FILE` (db); part of `ARCHIVE_DATABASE_URL` (app) | db, migrate, api, worker, ops |
| `jwt_secret` | `ARCHIVE_JWT_SECRET` | migrate, api, worker |
| `bootstrap_admin_password` | `ARCHIVE_BOOTSTRAP_ADMIN_PASSWORD` | migrate |
| `sarvam_api_key` | `ARCHIVE_SARVAM_API_KEY` | api, worker |
| `llm_api_key` | `ARCHIVE_LLM_API_KEY` | api, worker |
| `langfuse_secret_key` | `ARCHIVE_LANGFUSE_SECRET_KEY` | api, worker |

Create them with `..\scripts\New-ProductionSecrets.ps1`, then fill the provider keys from the institution's secret store. An empty key file leaves that provider disabled.

Never copy values from the repository-root `.env` (local demo) into these files, and never put these values in `deploy/production/.env`, a ticket or chat. See `docs/ops/secrets.md`.
