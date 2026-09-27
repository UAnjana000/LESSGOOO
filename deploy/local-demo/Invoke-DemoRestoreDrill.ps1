<#
.SYNOPSIS
    Restore drill for a local-demo backup (spec 6.5, 9, 10.2 Backup): restores into a THROWAWAY PostgreSQL 17
    container and a temporary folder, verifies everything, records RESTORE_LOG.json, then removes the scratch copy.
.DESCRIPTION
    Never touches the live database or volumes:
    - the scratch server is a new pgvector/pgvector:0.8.1-pg17 container with its data directory on tmpfs, published
      on a free 127.0.0.1 port, NOT attached to the compose network, with a random one-off password;
    - files are copied from the backup folder into a new folder under -StagingRoot.
    Checks, in order:
    1. the backup on disk against its MANIFEST.json (Test-BackupManifest.ps1);
    2. pg_restore of database.dump into archive_drill;
    3. the restored files against MANIFEST.json (Test-BackupManifest.ps1 on the restored copy);
    4. `archive.cli verify-restore`: every live file_version row vs the restored files, key-table row counts vs
       DB_COUNTS.json (counted inside the dump's own snapshot), and the audit hash chain.
    The record is kept at <BackupRoot>\drills\drill-<stamp>\RESTORE_LOG.json in the layout that
    eval/verify_restore_log.py reads. Exits non-zero on any failure.
.EXAMPLE
    .\deploy\local-demo\Invoke-DemoRestoreDrill.ps1                         # newest verified backup
    .\deploy\local-demo\Invoke-DemoRestoreDrill.ps1 -Backup backup-20260927T063000Z -Keep
    # a worker nightly backup, after copying it out of the `backups` volume (docs/DATASETS_AND_BACKUP.md)
    .\deploy\local-demo\Invoke-DemoRestoreDrill.ps1 -BackupRoot data\backups\worker -Backup backup-20260927T072419Z
#>
[CmdletBinding()]
param(
    [string] $BackupRoot,
    [string] $Backup,
    [string] $StagingRoot = (Join-Path $env:TEMP 'archive-demo-restore'),
    [switch] $Keep
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_demo.ps1"

function Get-FreePort {
    $l = New-Object System.Net.Sockets.TcpListener ([System.Net.IPAddress]::Loopback, 0)
    $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); return $p
}

$BackupRoot = Get-DemoBackupRoot $BackupRoot
if (-not $Backup) {
    $Backup = (Get-ChildItem -LiteralPath $BackupRoot -Directory |
        Where-Object { $_.Name -match $script:BackupNamePattern -and (Test-VerifiedBackup $_.FullName) } |
        Sort-Object Name | Select-Object -Last 1).Name
    if (-not $Backup) { throw "No verified backup-* folder in $BackupRoot" }
}
$bdir = (Resolve-Path -LiteralPath (Join-Path $BackupRoot $Backup)).Path
$db = Get-DemoDbConfig
$tag = Get-UtcStamp
$work = Join-Path $StagingRoot "drill-$tag"
$root = Join-Path $work 'files'
$record = Join-Path $BackupRoot "drills\drill-$tag"
$name = "archive-restore-drill-$($tag.ToLower())"
New-Item -ItemType Directory -Path $root, $record | Out-Null
$exitCode = 1
$started = Get-Date
try {
    # 1. The backup on disk.
    $pre = & (Join-Path $script:ProdScripts 'Test-BackupManifest.ps1') -BackupDir $bdir -LogPath (Join-Path $record 'BACKUP_VERIFY.json')
    if ($LASTEXITCODE -ne 0) { throw "Backup $Backup failed checksum verification on disk; not restoring it" }
    $preLog = Read-JsonFile (Join-Path $record 'BACKUP_VERIFY.json')

    # 2. Throwaway server and database restore.
    $port = Get-FreePort
    if ($port -eq $db.Port) { throw "refusing to use the live database port $port" }
    $env:POSTGRES_PASSWORD = [guid]::NewGuid().ToString('N')
    $drillPassword = $env:POSTGRES_PASSWORD
    try {
        & docker run -d --rm --name $name --label archive.restore-drill=1 -e POSTGRES_PASSWORD -e POSTGRES_USER=archive `
            -e POSTGRES_DB=postgres --tmpfs /var/lib/postgresql/data:rw -p "127.0.0.1:${port}:5432" `
            -v "${bdir}:/backup:ro" $script:DemoPgImage | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "could not start the scratch PostgreSQL container" }
    } finally { Remove-Item Env:POSTGRES_PASSWORD -ErrorAction SilentlyContinue }
    $ready = $false
    $ErrorActionPreference = 'Continue'   # PS 5.1 turns redirected native stderr into terminating errors under Stop
    for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
        Start-Sleep -Seconds 1
        & docker exec $name pg_isready -q -h 127.0.0.1 -U archive -d postgres 2>$null
        $ready = ($LASTEXITCODE -eq 0)
    }
    $ErrorActionPreference = 'Stop'
    if (-not $ready) { throw "scratch PostgreSQL did not become ready" }
    $serverUp = Get-Date
    & docker exec $name createdb -U archive archive_drill
    if ($LASTEXITCODE -ne 0) { throw "createdb failed" }
    & docker exec $name pg_restore -U archive -d archive_drill --no-owner /backup/database.dump
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed with exit code $LASTEXITCODE" }
    $dbRestored = Get-Date

    # 3. Files into the temporary folder, then re-hash against the manifest.
    foreach ($item in @('preservation', 'delivery', 'derivatives')) {
        if (Test-Path -LiteralPath (Join-Path $bdir $item)) {
            & robocopy (Join-Path $bdir $item) (Join-Path $root $item) /E /COPY:DT /R:1 /W:1 /NP /NFL /NDL /NJH /NJS | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "robocopy of $item failed with exit code $LASTEXITCODE" }
        }
    }
    Copy-Item -LiteralPath (Join-Path $bdir 'MANIFEST.json'), (Join-Path $bdir 'database.dump') -Destination $root
    $filesRestored = Get-Date
    & (Join-Path $script:ProdScripts 'Test-BackupManifest.ps1') -BackupDir $root -LogPath (Join-Path $record 'RESTORED_FILES_VERIFY.json') | Out-Null
    $filesLog = Read-JsonFile (Join-Path $record 'RESTORED_FILES_VERIFY.json')

    # 4. Restored database: file rows, row counts, audit chain.
    $target = "postgresql+psycopg://archive:${drillPassword}@127.0.0.1:${port}/archive_drill"
    $verifyOut = Join-Path $record 'VERIFY_RESTORE.json'
    try {
        Invoke-ArchiveCli -CliArgs @('verify-restore', '--target-db', $target, '--target-root', $root,
            '--expected-counts', (Join-Path $bdir 'DB_COUNTS.json'), '--out', $verifyOut) | Out-Null
    } catch { Write-Warning $_ }
    if (-not (Test-Path -LiteralPath $verifyOut)) { throw "verify-restore wrote no result" }
    $v = Read-JsonFile $verifyOut
    $finished = Get-Date

    $mismatches = @($filesLog['missing']) + @($filesLog['mismatched']) | Where-Object { $_ }
    $success = [bool]$preLog['success'] -and [bool]$filesLog['success'] -and [bool]$v['success']
    $log = [ordered]@{
        backup = $bdir
        target_db = "archive_drill in throwaway container $name ($($script:DemoPgImage), data on tmpfs, not on the compose network)"
        target_root = $root
        source_host = $env:COMPUTERNAME
        target_host = $env:COMPUTERNAME
        target_note = 'Same host as the live demo: separate scratch container and temporary folder. Not a clean machine.'
        started = $started.ToUniversalTime().ToString('o')
        finished = $finished.ToUniversalTime().ToString('o')
        database_dump_checksum_ok = [bool]$preLog['database_dump_checksum_ok']
        backup_files_verified_on_disk = $preLog['files_checked']
        files_restored = $filesLog['files_checked']
        manifest_mismatches = @($mismatches)
        db_file_rows_checked = $v['db_file_rows_checked']
        db_file_rows_failed = @($v['db_file_rows_failed'])
        expected_counts = $v['expected_counts']
        restored_counts = $v['restored_counts']
        row_count_mismatches = $v['row_count_mismatches']
        audit_chain_ok = $v['audit_chain_ok']
        audit_events = $v['audit_events']
        seconds = [math]::Round(($finished - $started).TotalSeconds, 1)
        seconds_breakdown = [ordered]@{
            verify_backup_on_disk = [math]::Round(($serverUp - $started).TotalSeconds, 1)
            database_restore = [math]::Round(($dbRestored - $serverUp).TotalSeconds, 1)
            file_restore = [math]::Round(($filesRestored - $dbRestored).TotalSeconds, 1)
            verification = [math]::Round(($finished - $filesRestored).TotalSeconds, 1)
        }
        success = $success
    }
    $json = $log | ConvertTo-Json -Depth 6
    Write-Utf8NoBom -Path (Join-Path $record 'RESTORE_LOG.json') -Content $json
    Write-Output $json
    if (-not $success) { throw "Restore drill FAILED for $Backup; record: $record" }
    Write-Host "Restore drill passed for $Backup in $($log.seconds) s. Record: $(Join-Path $record 'RESTORE_LOG.json')"
    $exitCode = 0
} catch {
    Write-Error $_ -ErrorAction Continue
} finally {
    $ErrorActionPreference = 'Continue'
    & docker stop $name 2>$null | Out-Null   # started with --rm and tmpfs: stopping removes it and its data
    if (-not $Keep) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
}
exit $exitCode
