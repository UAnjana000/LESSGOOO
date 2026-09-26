<#
.SYNOPSIS
    Creates the Docker secret files for a production site in SECRETS_DIR (default deploy/production/secrets).
.DESCRIPTION
    Generates postgres_password, jwt_secret and bootstrap_admin_password with a CSPRNG. Creates empty
    sarvam_api_key, llm_api_key and langfuse_secret_key files for the operator to fill from the
    institution's secret store. Refuses to overwrite, restricts NTFS permissions, never prints a value.
.EXAMPLE
    .\New-ProductionSecrets.ps1
    .\New-ProductionSecrets.ps1 -SecretsDir E:\archive-secrets
#>
[CmdletBinding()]
param([string] $SecretsDir)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_common.ps1"
if (-not $SecretsDir) { $SecretsDir = Join-Path $script:ProdRoot 'secrets' }

$generated = 'postgres_password', 'jwt_secret', 'bootstrap_admin_password'
$provided = 'sarvam_api_key', 'llm_api_key', 'langfuse_secret_key'
foreach ($name in $generated + $provided) {
    if (Test-Path -LiteralPath (Join-Path $SecretsDir $name)) {
        throw "$SecretsDir\$name already exists. Rotate secrets as described in docs/ops/secrets.md instead."
    }
}
New-Item -ItemType Directory -Force -Path $SecretsDir | Out-Null

function New-UrlSafeToken([int] $Bytes) {
    $buf = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buf) } finally { $rng.Dispose() }
    # base64url: the database password is embedded in a connection URL without percent-encoding.
    return ([Convert]::ToBase64String($buf)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

$sizes = @{ postgres_password = 32; jwt_secret = 48; bootstrap_admin_password = 18 }
foreach ($name in $generated) { Write-Utf8NoBom -Path (Join-Path $SecretsDir $name) -Content (New-UrlSafeToken $sizes[$name]) }
foreach ($name in $provided) { [IO.File]::WriteAllBytes((Join-Path $SecretsDir $name), [byte[]]@()) }

foreach ($name in $generated + $provided) {
    $f = Join-Path $SecretsDir $name
    & icacls $f /inheritance:r /grant:r "${env:USERDOMAIN}\${env:USERNAME}:(R,W)" "*S-1-5-32-544:(F)" "*S-1-5-18:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning "Could not restrict permissions on $f; do it manually." }
}

Write-Host "Created secret files in $SecretsDir (permissions restricted):"
Write-Host "  generated: $($generated -join ', ')"
Write-Host "  empty, fill from the secret store if the service is used: $($provided -join ', ')"
Write-Host "Read bootstrap_admin_password once, store it in the password manager, and empty the file after the"
Write-Host "first successful start (the admin account is kept)."
