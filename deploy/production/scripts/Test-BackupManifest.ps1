<#
.SYNOPSIS
    Re-hashes every file in an archive backup and compares it with the backup's MANIFEST.json (SHA-256).
.DESCRIPTION
    Needs no Docker, so it also verifies off-site copies. Exits 1 on any missing or mismatched file.
.EXAMPLE
    .\Test-BackupManifest.ps1 -BackupDir B:\archive-backups\backup-20260926T020000Z
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $BackupDir,
    [string] $LogPath
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_common.ps1"

$started = Get-Date
$manifest = Read-JsonFile (Join-Path $BackupDir 'MANIFEST.json')
$dump = Join-Path $BackupDir 'database.dump'
$dumpOk = (Test-Path -LiteralPath $dump) -and
    ((Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash.ToLower() -eq ([string]$manifest['database_dump_sha256']).ToLower())

$missing = New-Object System.Collections.Generic.List[string]
$mismatched = New-Object System.Collections.Generic.List[string]
$checked = 0
foreach ($entry in $manifest['files'].GetEnumerator()) {
    $path = Join-Path $BackupDir ($entry.Key -replace '/', '\')
    $checked++
    if (-not (Test-Path -LiteralPath $path)) { $missing.Add($entry.Key); continue }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() -ne ([string]$entry.Value).ToLower()) {
        $mismatched.Add($entry.Key)
    }
}

$result = [ordered]@{
    backup = (Resolve-Path -LiteralPath $BackupDir).Path
    manifest_created_at = $manifest['created_at']
    database_dump_checksum_ok = $dumpOk
    files_checked = $checked
    missing = @($missing)
    mismatched = @($mismatched)
    success = ($dumpOk -and $missing.Count -eq 0 -and $mismatched.Count -eq 0)
    seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    verified_at = (Get-Date).ToUniversalTime().ToString('o')
}
$json = $result | ConvertTo-Json -Depth 4
if ($LogPath) { Write-Utf8NoBom -Path $LogPath -Content $json }
Write-Output $json
if (-not $result.success) { exit 1 }
exit 0
