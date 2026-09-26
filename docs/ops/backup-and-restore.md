# Backup, fixity and restore [PROD]

Implements spec 6.5 (production column) and spec 9: 3-2-1 copies, checksum verification, scheduled fixity and scheduled restore tests. All tools are in `deploy/production/scripts/`. Run commands from `deploy\production`.

## What a backup contains

`Invoke-ArchiveBackup.ps1` runs `archive.cli backup` in the `ops` container and writes `BACKUP_PATH\backup-<UTC stamp>\`:

| Item | Content |
| --- | --- |
| `database.dump` | `pg_dump -Fc` of the whole database: items, pages, passages, review decisions, audit log, staff accounts, search indexes |
| `preservation/` | Every preservation master (content-addressed) |
| `delivery/`, `derivatives/` | Delivery copies, hOCR, narration, exports, **and `derivatives/keys/exhibit-signing.pem`** (kiosk manifest signing key) |
| `MANIFEST.json` | SHA-256 of the dump and of every file |
| `BACKUP_LOG.json`, `VERIFY_LOG.json` | Timing, and the result of the independent re-hash after the copy |

Not included: quarantine, traces, the proxy's certificate store and container images. Indexes are rebuildable but ride along in the dump.

The `ops` image carries PostgreSQL 17 client tools. The api image's bundled client (15) cannot dump the 17 server.

**Sizing.** Each backup is a full copy, including every preservation master. For a large collection, size `BACKUP_PATH` from the spec 10 storage report (`docker compose ... run --rm ops python -m archive.cli storage-report`). Masters are write-once and content-addressed, so the off-site `robocopy /E` of each new backup is cheap only if older backups stay at the destination.

## 3-2-1 mapping

| Copy | Medium | Location |
| --- | --- | --- |
| 1. Live | Preservation disk (`PRESERVATION_PATH`) | Server |
| 2. Nightly backup | Separate physical backup disk (`BACKUP_PATH`) | Server room |
| 3. Off-site | NAS at a second site, or rotated encrypted removable disks / tape | Off-site |

Backups hold staff password hashes and the exhibit signing key. Encrypt the backup disk and off-site media (BitLocker, BitLocker To Go) and restrict access to operators.

## Commands

```powershell
# Nightly backup, verified, with a verified off-site copy (exit code non-zero on any failure)
.\scripts\Invoke-ArchiveBackup.ps1 -OffsiteRoot \\offsite-nas\archive-backups

# Verify any backup folder, including an off-site copy, with no Docker needed (Get-FileHash SHA-256)
.\scripts\Test-BackupManifest.ps1 -BackupDir B:\archive-backups\backup-20260926T020000Z

# Fixity: re-hash every live file_version against the database; records an audit event; exit 1 on failure
docker compose --env-file .env -f compose.yaml run --rm -T ops python -m archive.cli fixity

# Tamper-evident audit chain
docker compose --env-file .env -f compose.yaml run --rm -T ops python -m archive.cli audit-verify

# Restore drill: newest backup into a scratch database and folder, full verification, then cleanup
.\scripts\Invoke-RestoreDrill.ps1
```

## Schedule (Windows Task Scheduler)

Run the tasks as the operator account that runs Docker (a member of `docker-users`, with Docker Desktop running in its session).

```powershell
$dir  = 'C:\archive\deploy\production'          # your checkout
$cred = Get-Credential                           # the operator service account
function Add-ArchiveTask($name, $trigger, $arguments) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass $arguments" -WorkingDirectory $dir
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -RunLevel Highest `
        -User $cred.UserName -Password $cred.GetNetworkCredential().Password
}
Add-ArchiveTask 'Archive nightly backup' (New-ScheduledTaskTrigger -Daily -At 2am) `
    "-File `"$dir\scripts\Invoke-ArchiveBackup.ps1`" -OffsiteRoot \\offsite-nas\archive-backups"
Add-ArchiveTask 'Archive weekly fixity' (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 4am) `
    "-Command `"docker compose --env-file .env -f compose.yaml run --rm -T ops python -m archive.cli fixity; exit `$LASTEXITCODE`""
Add-ArchiveTask 'Archive monthly restore drill' (New-ScheduledTaskTrigger -Weekly -WeeksInterval 4 -DaysOfWeek Saturday -At 5am) `
    "-File `"$dir\scripts\Invoke-RestoreDrill.ps1`""
```

A non-zero "Last Run Result" means failure. Wire task failures into the institution's alerting; no alerting is shipped here. Spec 9 asks for a quarterly restore test on a clean machine (see "Disaster recovery"). The monthly drill does not replace it.

**Retention (local disk only, after the off-site copy has verified):**

```powershell
Get-ChildItem B:\archive-backups -Directory -Filter 'backup-*' | Sort-Object Name -Descending |
    Select-Object -Skip 14 | Remove-Item -Recurse -Force
```

Never prune the off-site copy automatically.

## Restore drill (non-destructive)

`Invoke-RestoreDrill.ps1` runs these steps and never touches the live database or volumes:

1. Verifies the backup on disk (`Test-BackupManifest.ps1`).
2. Runs `scripts/restore-drill.sh` in `ops`.
3. `archive.cli restore` creates `archive_drill_<stamp>` and restores into `RESTORE_STAGING_PATH\drill-<stamp>`. It checks the dump checksum, re-hashes every restored file against `MANIFEST.json`, and cross-checks every `file_version` row in the restored database against the restored files.
4. `archive.cli audit-verify` runs against the restored database.
5. The scratch database and files are dropped. `RESTORE_LOG.json` is kept as the drill record.

## Disaster recovery (clean machine or total loss)

Use this for a real restore. `dr-restore.sh` refuses to run if the `archive` database exists or any file store holds data, so it cannot overwrite a working archive.

1. Prepare the host and disks as in [startup-and-migrations.md](startup-and-migrations.md). This includes the preservation marker file, the same `RELEASE_TAG` as the backup (or newer), `.\scripts\Invoke-ReleaseBuild.ps1`, and new secrets.
2. Copy the backup folder into `BACKUP_PATH` and verify it:

   ```powershell
   .\scripts\Test-BackupManifest.ps1 -BackupDir B:\archive-backups\backup-<stamp>
   ```

3. Start only the database, and drop the empty database it creates. This is deliberate and manual:

   ```powershell
   docker compose --env-file .env -f compose.yaml up -d db
   docker compose --env-file .env -f compose.yaml exec -T db dropdb -U archive archive
   ```

4. Restore, verify, copy into place, then run fixity and audit-verify:

   ```powershell
   docker compose --env-file .env -f compose.yaml run --rm -T ops sh /opt/ops/dr-restore.sh backup-<stamp>
   ```

5. Start everything. `migrate` upgrades the schema if the release is newer.

   ```powershell
   docker compose --env-file .env -f compose.yaml up -d
   docker compose --env-file .env -f compose.yaml ps
   ```

6. Keep `RESTORE_STAGING_PATH\dr-backup-<stamp>\RESTORE_LOG.json` and the fixity output as the recovery record. Delete the staging copy once satisfied. Kiosks resync on reconnect; the exhibit signing key is restored, so their manifests stay verifiable.

If the new host uses new secrets, staff sessions from the old host are invalid; staff sign in again. The database password is the new host's, because the dump is restored with `--no-owner`.

## Smoke test record (developer workstation, not production)

- **Backup.** `Invoke-ArchiveBackup.ps1` produced a backup (database dump plus 6 files), verified it, robocopied it off-site and verified the copy; exit 0. The first attempt exposed the PostgreSQL 15-vs-17 client mismatch, which is why the ops image exists.
- **Tamper detection.** Appending one byte to a preservation master in the off-site copy made `Test-BackupManifest.ps1` report it as mismatched and exit 1.
- **Restore drill.** Dump checksum OK, 6 of 6 files restored with no mismatches, 3 of 3 `file_version` rows verified, audit chain OK (6 events). The scratch database was dropped and the record kept.
- **Disaster recovery.** All volumes were destroyed (`down -v`) and the preservation folder emptied.
  - `dr-restore.sh` refused while the database existed. After `dropdb` it restored with 0 mismatches and 3/3 rows, and in-place fixity checked 3 files with 0 failures. The audit chain verified.
  - The stack came back healthy and the restored admin could sign in.
  - An earlier ad-hoc copy using `cp -a` failed on the Windows-backed preservation mount and was caught by fixity, which is why `dr-restore.sh` uses a plain copy.
