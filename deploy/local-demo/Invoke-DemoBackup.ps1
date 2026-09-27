<#
.SYNOPSIS
    MANUAL backup of the LOCAL DEMO stack to a host folder (for example an external disk or an off-site copy):
    database dump, preservation masters, delivery copies and derivatives, a SHA-256 manifest, an independent
    re-hash, then retention pruning of this script's own folder.
.DESCRIPTION
    The nightly schedule is the worker's `backup` job (backend/archive/worker.py, 01:30 IST, into the `backups`
    volume). Do not register this script as a second scheduled task; run it by hand when a copy outside Docker's
    volumes is wanted.
    Read-only against the running stack. Nothing is stopped, restarted or rebuilt.
    - Database: pg_dump 17 from the pgvector/pgvector:0.8.1-pg17 image, attached to the compose backend network.
      The api image's PostgreSQL 15 client cannot dump the 17 server. `archive.cli snapshot-dump` (host venv) opens
      a read-only REPEATABLE READ snapshot, counts the key tables inside it, and runs pg_dump --snapshot=<id>, so
      DB_COUNTS.json describes exactly what is in the dump. pg_dump takes ACCESS SHARE locks only, which never block
      inserts or updates. --lock-wait-timeout makes it give up instead of queueing behind a migration.
    - Files: the three named volumes are mounted read-only into the same image and copied with plain `cp -r`
      (`cp -a` fails on Windows bind mounts; see docs/ops/backup-and-restore.md).
    - MANIFEST.json has the `archive.cli backup` layout, so deploy/production/scripts/Test-BackupManifest.ps1 and
      `archive.cli restore` both read it. The re-hash result is written to VERIFY_LOG.json.
    - Retention keeps the newest -Retain VERIFIED backups. Folders that failed or were never verified are not
      counted as keeps and are never deleted automatically.
    Not included: .env and other secrets, quarantine, traces, the proxy's certificate store, container images.
    Exits non-zero on any failure.
.EXAMPLE
    .\deploy\local-demo\Invoke-DemoBackup.ps1
    .\deploy\local-demo\Invoke-DemoBackup.ps1 -BackupRoot E:\archive-demo-backups -Retain 14
#>
[CmdletBinding()]
param(
    [string] $BackupRoot,
    [ValidateRange(1, 365)] [int] $Retain = 7,
    [string] $EnvFile,
    [ValidateRange(1, 600)] [int] $LockWaitSeconds = 30
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_demo.ps1"

$BackupRoot = Get-DemoBackupRoot $BackupRoot
$stamp = Get-UtcStamp
New-Item -ItemType Directory -Force -Path $BackupRoot, (Join-Path $BackupRoot 'logs') | Out-Null
Start-Transcript -Path (Join-Path $BackupRoot "logs\backup-$stamp.log") | Out-Null
$exitCode = 1
try {
    Assert-DemoDbHealthy
    $db = Get-DemoDbConfig $EnvFile
    $net = "$($script:DemoProject)_backend"
    $dest = Join-Path $BackupRoot "backup-$stamp"
    New-Item -ItemType Directory -Path $dest | Out-Null
    $started = Get-Date

    # 1. Database, from one exported snapshot.
    $env:PGPASSWORD = $db.Password
    $env:ARCHIVE_DATABASE_URL = "postgresql+psycopg://archive:$([uri]::EscapeDataString($db.Password))@127.0.0.1:$($db.Port)/archive"
    try {
        Invoke-ArchiveCli -CliArgs @('snapshot-dump', '--counts-out', (Join-Path $dest 'DB_COUNTS.json'), '--',
            'docker', 'run', '--rm', '--network', $net, '-e', 'PGPASSWORD', '-v', "${dest}:/out", $script:DemoPgImage,
            'pg_dump', '-h', 'db', '-U', 'archive', '-d', 'archive', '-Fc', "--lock-wait-timeout=$($LockWaitSeconds)s",
            '-f', '/out/database.dump')
    } finally {
        Remove-Item Env:PGPASSWORD, Env:ARCHIVE_DATABASE_URL -ErrorAction SilentlyContinue
    }
    $dumped = Get-Date

    # 2. Files, from read-only volume mounts.
    $mounts = foreach ($v in $script:DemoVolumes) { '-v'; "$($script:DemoProject)_${v}:/src/${v}:ro" }
    & docker run --rm @mounts -v "${dest}:/out" $script:DemoPgImage sh -c 'cp -r /src/preservation /src/delivery /src/derivatives /out/'
    if ($LASTEXITCODE -ne 0) { throw "volume copy failed with exit code $LASTEXITCODE" }
    $copied = Get-Date

    # 3. Manifest (same layout as archive.cli backup).
    $files = [ordered]@{}
    $fileBytes = [int64]0
    foreach ($v in $script:DemoVolumes) {
        $dir = Join-Path $dest $v
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        foreach ($f in (Get-ChildItem -LiteralPath $dir -Recurse -File | Where-Object { $_.Name -notlike '*.tmp' } | Sort-Object FullName)) {
            $files[($f.FullName.Substring($dest.Length + 1) -replace '\\', '/')] = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLower()
            $fileBytes += $f.Length
        }
    }
    $dump = Join-Path $dest 'database.dump'
    $manifest = [ordered]@{
        created_at = $stamp
        source = "local demo stack ($($script:DemoProject)) on $env:COMPUTERNAME"
        database_dump_sha256 = (Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash.ToLower()
        files = $files
    }
    Write-Utf8NoBom -Path (Join-Path $dest 'MANIFEST.json') -Content ($manifest | ConvertTo-Json -Depth 4)
    $hashed = Get-Date

    # 4. Independent re-hash of the copy against the manifest.
    & (Join-Path $script:ProdScripts 'Test-BackupManifest.ps1') -BackupDir $dest -LogPath (Join-Path $dest 'VERIFY_LOG.json') | Out-Null
    $verifyOk = ($LASTEXITCODE -eq 0)
    $verified = Get-Date

    $counts = Read-JsonFile (Join-Path $dest 'DB_COUNTS.json')
    $dumpBytes = (Get-Item -LiteralPath $dump).Length
    $log = [ordered]@{
        created_at = $stamp
        host = $env:COMPUTERNAME
        source_project = $script:DemoProject
        pg_client = (& docker run --rm $script:DemoPgImage pg_dump --version)
        server_version = $counts['server_version']
        snapshot = $counts['snapshot']
        row_counts = $counts['counts']
        lock_wait_timeout_seconds = $LockWaitSeconds
        database_dump_bytes = $dumpBytes
        files = $files.Count
        file_bytes = $fileBytes
        total_bytes = (Get-FolderBytes $dest)
        seconds = [ordered]@{
            database_dump = [math]::Round(($dumped - $started).TotalSeconds, 1)
            snapshot_counts = $counts['count_seconds']
            pg_dump = $counts['dump_seconds']
            file_copy = [math]::Round(($copied - $dumped).TotalSeconds, 1)
            manifest_hash = [math]::Round(($hashed - $copied).TotalSeconds, 1)
            verify_rehash = [math]::Round(($verified - $hashed).TotalSeconds, 1)
            total = [math]::Round(($verified - $started).TotalSeconds, 1)
        }
        verified = $verifyOk
    }
    Write-Utf8NoBom -Path (Join-Path $dest 'BACKUP_LOG.json') -Content ($log | ConvertTo-Json -Depth 4)
    if (-not $verifyOk) { throw "Checksum verification failed for $dest; not pruning anything" }

    # 5. Retention: newest $Retain verified backups stay.
    $keep = @(Get-ChildItem -LiteralPath $BackupRoot -Directory |
        Where-Object { $_.Name -match $script:BackupNamePattern -and (Test-VerifiedBackup $_.FullName) } |
        Sort-Object Name -Descending)
    foreach ($old in ($keep | Select-Object -Skip $Retain)) {
        if ($old.FullName -eq $dest) { continue }
        Write-Host "Retention: removing $($old.Name)"
        Remove-Item -LiteralPath $old.FullName -Recurse -Force
    }

    Write-Host ("Backup verified: {0} ({1:N1} MB, {2} files, {3} s)" -f $dest, ($log.total_bytes / 1MB), $files.Count, $log.seconds.total)
    $exitCode = 0
} catch {
    Write-Error $_ -ErrorAction Continue
} finally {
    Stop-Transcript | Out-Null
}
exit $exitCode
