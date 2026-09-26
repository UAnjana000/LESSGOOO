<#
.SYNOPSIS
    Pre-flight checks before `docker compose up` on a production host. Exits 1 if any check fails.
.DESCRIPTION
    Checks site settings, secrets files, storage separation, certificates, that no secret is tracked by
    git, and that compose.yaml renders. Changes nothing.
.EXAMPLE
    .\Test-ProductionConfig.ps1
#>
[CmdletBinding()]
param([string] $EnvFile)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_common.ps1"
if (-not $EnvFile) { $EnvFile = Join-Path $script:ProdRoot '.env' }

$results = New-Object System.Collections.Generic.List[object]
function Check([string] $Name, [bool] $Ok, [string] $Detail = '') {
    $results.Add([pscustomobject]@{ Check = $Name; Result = $(if ($Ok) { 'PASS' } else { 'FAIL' }); Detail = $Detail })
}

$envVals = Read-DotEnv $EnvFile
$required = 'RELEASE_TAG', 'VISITOR_SITE', 'STAFF_SITE', 'VISITOR_BIND_IP', 'STAFF_BIND_IP',
    'ARCHIVE_PUBLIC_BASE_URL', 'ARCHIVE_CORS_ORIGINS', 'ARCHIVE_BOOTSTRAP_ADMIN_EMAIL', 'PRESERVATION_PATH',
    'BACKUP_PATH', 'RESTORE_STAGING_PATH', 'INTAKE_PATH'
foreach ($k in $required) { Check "setting $k" ([bool]$envVals[$k]) }
Check 'sites differ' ($envVals['VISITOR_SITE'] -ne $envVals['STAFF_SITE'])
Check 'no example hostnames' (-not (($envVals['VISITOR_SITE'] + $envVals['STAFF_SITE']) -match 'example\.org')) 'replace *.example.org'

# ---- secrets (values are read to validate them, never printed)
$secretsDir = ConvertTo-HostPath $(if ($envVals['SECRETS_DIR']) { $envVals['SECRETS_DIR'] } else { './secrets' })
function Read-Secret([string] $Name) {
    $f = Join-Path $secretsDir $Name
    if (-not (Test-Path -LiteralPath $f)) { return $null }
    return ([IO.File]::ReadAllText($f)).Trim()
}
foreach ($name in 'postgres_password', 'jwt_secret', 'bootstrap_admin_password', 'sarvam_api_key', 'llm_api_key', 'langfuse_secret_key') {
    Check "secret file $name exists" ($null -ne (Read-Secret $name)) (Join-Path $secretsDir $name)
}
$pg = [string](Read-Secret 'postgres_password')
Check 'postgres_password set and URL-safe' ($pg.Length -ge 24 -and $pg -match '^[A-Za-z0-9._~-]+$') 'embedded in ARCHIVE_DATABASE_URL'
Check 'jwt_secret >= 32 chars' (([string](Read-Secret 'jwt_secret')).Length -ge 32)
if ($envVals['ARCHIVE_LLM_PROVIDER'] -eq 'openai_compatible') {
    Check 'LLM: ARCHIVE_LLM_BASE_URL set' ([bool]$envVals['ARCHIVE_LLM_BASE_URL'])
    Check 'LLM: ARCHIVE_LLM_MODEL set' ([bool]$envVals['ARCHIVE_LLM_MODEL'])
    Check 'LLM: llm_api_key secret filled' ([bool](Read-Secret 'llm_api_key'))
}
if ($envVals['ARCHIVE_LANGFUSE_HOST']) {
    Check 'Langfuse: public key and secret set' ([bool]$envVals['ARCHIVE_LANGFUSE_PUBLIC_KEY'] -and [bool](Read-Secret 'langfuse_secret_key'))
}
if (-not (Read-Secret 'sarvam_api_key')) { Write-Warning 'sarvam_api_key is empty: OCR fallback, translation and Sarvam TTS are disabled.' }

# Secret-looking names must not be in .env (non-secret settings only).
$leaked = @($envVals.Keys | Where-Object { $_ -match '(PASSWORD|SECRET|API_KEY|DATABASE_URL)' -and $_ -ne 'SECRETS_DIR' -and $envVals[$_] })
Check 'no secret values in .env' ($leaked.Count -eq 0) ($leaked -join ', ')

# ---- storage separation
$pres = ConvertTo-HostPath ([string]$envVals['PRESERVATION_PATH'])
$back = ConvertTo-HostPath ([string]$envVals['BACKUP_PATH'])
$stage = ConvertTo-HostPath ([string]$envVals['RESTORE_STAGING_PATH'])
$intake = ConvertTo-HostPath ([string]$envVals['INTAKE_PATH'])
Check 'preservation path exists' (Test-Path -LiteralPath $pres) $pres
Check 'preservation marker present' (Test-Path -LiteralPath (Join-Path $pres '.archive-preservation-volume')) 'guards against an unmounted disk'
Check 'backup path exists' (Test-Path -LiteralPath $back) $back
Check 'restore staging exists' (Test-Path -LiteralPath $stage) $stage
Check 'intake path exists' (Test-Path -LiteralPath $intake) $intake
$presRoot = [IO.Path]::GetPathRoot($pres); $backRoot = [IO.Path]::GetPathRoot($back)
Check 'preservation not on system drive' ($presRoot -ne [IO.Path]::GetPathRoot($env:SystemRoot)) $presRoot
Check 'backup on a different drive from preservation' ($presRoot -ne $backRoot) "$presRoot vs $backRoot"

# ---- certificates
$certs = ConvertTo-HostPath $(if ($envVals['CERTS_PATH']) { $envVals['CERTS_PATH'] } else { './certs' })
foreach ($site in 'VISITOR', 'STAFF') {
    $tls = [string]$envVals["${site}_TLS"]
    if (-not $tls) { $tls = "/certs/$($site.ToLower()).crt /certs/$($site.ToLower()).key" }
    if ($tls -eq 'internal') { Check "$site TLS" $false "'internal' is for staging rehearsal only"; continue }
    foreach ($f in ($tls -split '\s+' | Where-Object { $_ -like '/certs/*' })) {
        $hostFile = Join-Path $certs ($f.Substring(7) -replace '/', '\')
        Check "$site certificate file $f" (Test-Path -LiteralPath $hostFile) $hostFile
    }
}

# ---- nothing secret tracked by git
Push-Location $script:ProdRoot
try {
    $tracked = @(& git ls-files -- .env secrets certs 2>$null | Where-Object { $_ -notmatch 'README\.md$' })
    Check 'no secrets tracked by git' (-not $tracked) ($tracked -join ', ')
} finally { Pop-Location }

# ---- compose renders
& docker compose --env-file $EnvFile -f $script:ComposeFile config --quiet
Check 'compose config renders' ($LASTEXITCODE -eq 0)

$results | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
$failed = @($results | Where-Object { $_.Result -eq 'FAIL' }).Count
if ($failed) { Write-Host "$failed check(s) failed." -ForegroundColor Red; exit 1 }
Write-Host 'All checks passed.' -ForegroundColor Green
