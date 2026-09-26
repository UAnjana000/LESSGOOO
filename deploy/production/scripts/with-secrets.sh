#!/bin/sh
# Entrypoint for migrate, api, worker and ops. The backend reads plain ARCHIVE_* environment variables
# (backend/archive/config.py); this maps Docker secrets mounted under /run/secrets onto those names and
# then execs the real command. Secret values never appear in compose files, env files or `docker inspect`.
# A secret that is not granted to a service is left unset, so the backend default applies.
set -eu

load() {
  if [ -f "/run/secrets/$1" ]; then
    value="$(tr -d '\r\n' < "/run/secrets/$1")"
    export "$2=$value"
  fi
}

if [ ! -s /run/secrets/postgres_password ]; then
  echo "with-secrets: secret postgres_password is missing or empty" >&2
  exit 1
fi
ARCHIVE_DATABASE_URL="postgresql+psycopg://archive:$(tr -d '\r\n' < /run/secrets/postgres_password)@db:5432/archive"
export ARCHIVE_DATABASE_URL

load jwt_secret ARCHIVE_JWT_SECRET
load bootstrap_admin_password ARCHIVE_BOOTSTRAP_ADMIN_PASSWORD
load sarvam_api_key ARCHIVE_SARVAM_API_KEY
load llm_api_key ARCHIVE_LLM_API_KEY
load langfuse_secret_key ARCHIVE_LANGFUSE_SECRET_KEY

exec "$@"
