#!/usr/bin/env bash
# Run on the machine with the local demo (Git Bash on Windows works), from the repository root.
# Writes the database dump and the stored files to a folder outside the repository.
set -euo pipefail

OUT="${1:-../archive-bundle}"
mkdir -p "$OUT"
# Docker Desktop needs a Windows path for the bind mount; `pwd -W` exists only in Git Bash.
OUT_ABS="$(cd "$OUT" && { pwd -W 2>/dev/null || pwd; })"

docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$OUT/archive.dump"
for v in preservation delivery derivatives; do
  MSYS_NO_PATHCONV=1 docker run --rm -v "ambedkar-archive_$v:/v:ro" -v "$OUT_ABS:/out" alpine \
    tar czf "/out/$v.tgz" -C /v .
done
ls -la "$OUT"
