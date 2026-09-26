<#
.SYNOPSIS
    Builds the release images tagged RELEASE_TAG: ambedkar-archive/api, /web and /ops.
.DESCRIPTION
    The only step that builds images. api uses backend/Dockerfile without dev dependencies and with the
    embedding/reranker models baked in (the edge server must work offline); web uses web/Dockerfile;
    ops layers PostgreSQL client tools on the api image. Needs internet access (PyPI, npm, model hub,
    apt.postgresql.org). Run it after checking out the release, then `up -d`.
.EXAMPLE
    .\Invoke-ReleaseBuild.ps1
#>
[CmdletBinding()]
param([string] $EnvFile)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_common.ps1"
if (-not $EnvFile) { $EnvFile = Join-Path $script:ProdRoot '.env' }
$tag = [string](Read-DotEnv $EnvFile)['RELEASE_TAG']
if (-not $tag) { throw "RELEASE_TAG is not set in $EnvFile" }

Invoke-Compose -EnvFile $EnvFile build api web
& docker build --build-context "base=docker-image://ambedkar-archive/api:$tag" --build-arg PG_MAJOR=17 `
    -t "ambedkar-archive/ops:$tag" (Join-Path $script:ProdRoot 'ops')
if ($LASTEXITCODE -ne 0) { throw "ops image build failed with exit code $LASTEXITCODE" }
& docker run --rm --entrypoint pg_dump "ambedkar-archive/ops:$tag" --version
if ($LASTEXITCODE -ne 0) { throw "ops image has no working pg_dump" }
Write-Host "Built ambedkar-archive/api:$tag, ambedkar-archive/web:$tag, ambedkar-archive/ops:$tag"
exit 0
