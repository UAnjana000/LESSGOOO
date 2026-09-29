#!/usr/bin/env bash
# Run once on the cloud VM from ~/archive, before the first full start, with the files written by
# export-local-data.sh in BUNDLE (default ~/archive-bundle). Refuses to overwrite a database that has data.
set -euo pipefail

BUNDLE="${1:-$HOME/archive-bundle}"
COMPOSE=(docker compose -f docker-compose.yml -f deploy/cloud/docker-compose.cloud.yml)

"${COMPOSE[@]}" up --no-start
"${COMPOSE[@]}" start db
until "${COMPOSE[@]}" exec -T db sh -c 'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; do sleep 2; done

tables=$("${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from pg_tables where schemaname = '"'"'public'"'"'"')
if [ "$tables" != "0" ]; then
  echo "The database already has $tables tables; not restoring over it." >&2
  exit 1
fi

"${COMPOSE[@]}" exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < "$BUNDLE/archive.dump"
for v in preservation delivery derivatives; do
  docker run --rm -v "ambedkar-archive_$v:/v" -v "$BUNDLE:/in:ro" alpine tar xzf "/in/$v.tgz" -C /v
done
echo "Restored. Start everything with: ${COMPOSE[*]} up -d"
