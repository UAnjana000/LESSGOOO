#!/bin/sh
# Disaster recovery onto an EMPTY installation. Runs inside the ops container:
#   docker compose --env-file .env -f compose.yaml run --rm ops sh /opt/ops/dr-restore.sh <backup-folder-name>
# Refuses to run if the live database exists or any file store holds data, so it cannot overwrite a
# working archive. Steps: restore to staging with checksum verification (archive.cli restore), copy the
# verified files into the live stores, then fixity (every file_version re-hashed in place) and audit-verify.
set -eu

backup="$1"
stage="/restore/dr-${backup}"
admin="${ARCHIVE_DATABASE_URL%/*}/postgres"
admin="postgresql://${admin#*://}"

if [ -n "$(psql "$admin" -Atc "SELECT 1 FROM pg_database WHERE datname = 'archive'")" ]; then
  echo "dr-restore: database 'archive' exists. Drop it deliberately first (docs/ops/backup-and-restore.md)." >&2
  exit 1
fi
for d in /data/preservation /data/delivery /data/derivatives; do
  if [ -n "$(find "$d" -mindepth 1 ! -name .archive-preservation-volume ! -name .ready -print -quit)" ]; then
    echo "dr-restore: $d is not empty; refusing to overwrite." >&2
    exit 1
  fi
done

python -m archive.cli restore "/backups/${backup}" --target-db "${ARCHIVE_DATABASE_URL}" --target-root "${stage}"
python -c "import json,sys; log=json.load(open('${stage}/RESTORE_LOG.json')); sys.exit(0 if log['success'] else 1)" \
  || { echo "dr-restore: restore verification FAILED; see ${stage}/RESTORE_LOG.json" >&2; exit 1; }

# Plain recursive copy: timestamps and ownership cannot be set on Windows-backed bind mounts, and the
# checksums, not the metadata, are what fixity verifies. Dot entries (the disk marker, .ready) are skipped.
for r in preservation delivery derivatives; do
  for entry in "${stage}/${r}"/*; do
    [ -e "$entry" ] || continue
    cp -R "$entry" "/data/${r}/"
  done
done

python -m archive.cli fixity
python -m archive.cli audit-verify
echo "dr-restore ${backup}: OK. Start the stack with: docker compose ... up -d"
