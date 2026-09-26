#!/bin/sh
# Runs inside the ops container (mounted at /opt/ops). Called by Invoke-RestoreDrill.ps1.
# Restores /backups/<backup> into a scratch database and /restore/drill-<tag>, which `archive.cli restore`
# verifies file by file against MANIFEST.json and the restored file_version rows. Then verifies the
# audit hash chain in the restored database and drops the scratch copy unless "keep" is given.
# The live database and volumes are never touched.
set -eu

backup="$1"
tag="$2"
keep="${3:-drop}"

base="${ARCHIVE_DATABASE_URL%/*}"
db="archive_drill_${tag}"
target="/restore/drill-${tag}"

python -m archive.cli restore "/backups/${backup}" --target-db "${base}/${db}" --target-root "${target}"
python -c "import json,sys; log=json.load(open('${target}/RESTORE_LOG.json')); sys.exit(0 if log['success'] else 1)" \
  || { echo "restore verification FAILED; scratch database ${db} and ${target} kept for inspection" >&2; exit 1; }

ARCHIVE_DATABASE_URL="${base}/${db}" python -m archive.cli audit-verify

if [ "$keep" != "keep" ]; then
  psql "postgresql://${base#*://}/postgres" -v ON_ERROR_STOP=1 -q -c "DROP DATABASE \"${db}\""
  # RESTORE_LOG.json stays as the drill record; restored copies are removed.
  find "${target}" -mindepth 1 -maxdepth 1 ! -name RESTORE_LOG.json -exec rm -rf {} +
fi
echo "restore drill ${tag}: OK"
