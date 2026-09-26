<#
.SYNOPSIS
    Nightly backup: database dump + preservation, delivery and derivative files, then checksum verification,
    then (optionally) an off-site copy that is verified again.
.DESCRIPTION
    Uses `python -m archive.cli backup` in the ops container, which writes backup-<UTC stamp>/ with
    database.dump, the three file roots and MANIFEST.json (SHA-256 of every file) into BACKUP_PATH.
    Exits non-zero on any failure so Task Scheduler records it.
.EXAMPLE
    .\Invoke-ArchiveBackup.ps1
    .\Invoke-ArchiveBackup.ps1 -OffsiteRoot \\offsite-nas\archive-backups
#>
[CmdletBinding()]
param(
    [string] $EnvFile,
    [string] $OffsiteRoot
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_common.ps1"
if (-not $EnvFile) { $EnvFile = Join-Path $script:ProdRoot '.env' }
$backupRoot = ConvertTo-HostPath ([string](Read-DotEnv $EnvFile)['BACKUP_PATH'])

$before = @(Get-ChildItem -LiteralPath $backupRoot -Directory -Filter 'backup-*' | ForEach-Object Name)
Invoke-Compose -EnvFile $EnvFile run --rm -T ops python -m archive.cli backup
$new = @(Get-ChildItem -LiteralPath $backupRoot -Directory -Filter 'backup-*' |
    Where-Object { $before -notcontains $_.Name } | Sort-Object Name)
if ($new.Count -ne 1) { throw "Expected exactly one new backup folder in $backupRoot, found $($new.Count)" }
$dir = $new[0].FullName

& "$PSScriptRoot\Test-BackupManifest.ps1" -BackupDir $dir -LogPath (Join-Path $dir 'VERIFY_LOG.json')
if ($LASTEXITCODE -ne 0) { throw "Checksum verification failed for $dir" }

if ($OffsiteRoot) {
    $dest = Join-Path $OffsiteRoot $new[0].Name
    # /E copies without deleting anything at the destination; never use /MIR for backups.
    & robocopy $dir $dest /E /COPY:DT /DCOPY:DT /R:3 /W:10 /NP /NFL /NDL
    if ($LASTEXITCODE -ge 8) { throw "robocopy to $dest failed with exit code $LASTEXITCODE" }
    & "$PSScriptRoot\Test-BackupManifest.ps1" -BackupDir $dest
    if ($LASTEXITCODE -ne 0) { throw "Checksum verification failed for off-site copy $dest" }
}
Write-Host "Backup complete and verified: $dir"
exit 0
