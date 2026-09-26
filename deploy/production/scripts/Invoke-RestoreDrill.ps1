<#
.SYNOPSIS
    Scheduled restore test (spec 6.5 / 9): restores a backup into a scratch database and folder, verifies
    every checksum and the audit hash chain, records the result, and removes the scratch copy.
.DESCRIPTION
    Verifies the backup on disk first (Test-BackupManifest.ps1), then runs restore-drill.sh in the ops
    container. The live database and volumes are not touched. The drill record is kept at
    RESTORE_STAGING_PATH\drill-<tag>\RESTORE_LOG.json.
.EXAMPLE
    .\Invoke-RestoreDrill.ps1                       # newest backup
    .\Invoke-RestoreDrill.ps1 -Backup backup-20260926T020000Z -Keep
#>
[CmdletBinding()]
param(
    [string] $EnvFile,
    [string] $Backup,
    [switch] $Keep
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_common.ps1"
if (-not $EnvFile) { $EnvFile = Join-Path $script:ProdRoot '.env' }
$envVals = Read-DotEnv $EnvFile
$backupRoot = ConvertTo-HostPath ([string]$envVals['BACKUP_PATH'])
$stagingRoot = ConvertTo-HostPath ([string]$envVals['RESTORE_STAGING_PATH'])

if (-not $Backup) {
    $Backup = (Get-ChildItem -LiteralPath $backupRoot -Directory -Filter 'backup-*' | Sort-Object Name | Select-Object -Last 1).Name
    if (-not $Backup) { throw "No backup-* folder in $backupRoot" }
}
& "$PSScriptRoot\Test-BackupManifest.ps1" -BackupDir (Join-Path $backupRoot $Backup)
if ($LASTEXITCODE -ne 0) { throw "Backup $Backup failed checksum verification on disk; not restoring it" }

$tag = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
$mode = if ($Keep) { 'keep' } else { 'drop' }
Invoke-Compose -EnvFile $EnvFile run --rm -T ops sh /opt/ops/restore-drill.sh $Backup $tag $mode

$log = Join-Path $stagingRoot "drill-$tag\RESTORE_LOG.json"
Get-Content -Raw -LiteralPath $log | Write-Output
Write-Host "Restore drill passed for $Backup. Record: $log"
exit 0
