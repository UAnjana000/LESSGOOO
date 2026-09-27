# Shared helpers for the local-demo backup scripts. Dot-source it: . "$PSScriptRoot\_demo.ps1"
# Reuses deploy/production/scripts/_common.ps1 (Read-DotEnv, Read-JsonFile, Write-Utf8NoBom) and
# Test-BackupManifest.ps1. Compatible with Windows PowerShell 5.1 and PowerShell 7.

$script:RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script:ProdScripts = Join-Path $script:RepoRoot 'deploy\production\scripts'
. (Join-Path $script:ProdScripts '_common.ps1')

$script:DemoProject = 'ambedkar-archive'
$script:DemoPgImage = 'pgvector/pgvector:0.8.1-pg17'
$script:DemoVolumes = @('preservation', 'delivery', 'derivatives')
$script:BackupNamePattern = '^backup-\d{8}T\d{6}Z$'

function Get-DemoBackupRoot {
    # Absolute, because the archive CLI runs from backend\ and would misread a relative path.
    param([string] $BackupRoot)
    $root = if ($BackupRoot) { $BackupRoot }
            elseif ($env:ARCHIVE_DEMO_BACKUP_ROOT) { $env:ARCHIVE_DEMO_BACKUP_ROOT }
            else { Join-Path $script:RepoRoot 'data\backups\demo' }
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($root)
}

function Get-DemoDbConfig {
    # Password and host port of the demo database, from the repo .env (compose defaults otherwise). Never printed.
    param([string] $EnvFile)
    if (-not $EnvFile) { $EnvFile = Join-Path $script:RepoRoot '.env' }
    $vals = if (Test-Path -LiteralPath $EnvFile) { Read-DotEnv $EnvFile } else { @{} }
    $password = if ($vals['POSTGRES_PASSWORD']) { [string]$vals['POSTGRES_PASSWORD'] } else { 'archive-dev' }
    $port = if ($vals['DB_HOST_PORT']) { [int]$vals['DB_HOST_PORT'] } else { 55432 }
    return @{ Password = $password; Port = $port }
}

function Assert-DemoDbHealthy {
    param([string] $Project = $script:DemoProject)
    $id = & docker ps -q --filter "label=com.docker.compose.project=$Project" `
        --filter 'label=com.docker.compose.service=db' --filter 'health=healthy'
    if ($LASTEXITCODE -ne 0 -or -not $id) { throw "The $Project db container is not running and healthy; nothing backed up." }
}

function Get-DemoPython {
    $py = Join-Path $script:RepoRoot 'backend\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $py)) { throw "Host Python venv not found at $py" }
    return $py
}

function Invoke-ArchiveCli {
    # Runs `python -m archive.cli <args>` from backend/ with the host venv. Throws on a non-zero exit code.
    # Pass an explicit array: bare -v/-e/-d tokens would bind to PowerShell common parameters.
    param([Parameter(Mandatory)] [string[]] $CliArgs)
    Push-Location (Join-Path $script:RepoRoot 'backend')
    try {
        & (Get-DemoPython) -m archive.cli @CliArgs
        if ($LASTEXITCODE -ne 0) { throw "archive.cli $($CliArgs[0]) failed with exit code $LASTEXITCODE" }
    } finally { Pop-Location }
}

function Get-FolderBytes {
    param([Parameter(Mandatory)] [string] $Path)
    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    if ($sum) { return [int64]$sum } else { return [int64]0 }
}

function Test-VerifiedBackup {
    param([Parameter(Mandatory)] [string] $Path)
    $log = Join-Path $Path 'VERIFY_LOG.json'
    if (-not (Test-Path -LiteralPath $log)) { return $false }
    try { return [bool](Read-JsonFile $log)['success'] } catch { return $false }
}

function Get-UtcStamp { (Get-Date).ToUniversalTime().ToString("yyyyMMdd'T'HHmmss'Z'") }
