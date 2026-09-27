<#
.SYNOPSIS
  Throwaway Docker stack for the Playwright suite (project ambedkar-e2e, ports 9443/9088/56432).

.EXAMPLE
  powershell -File web/e2e/stack.ps1 build     # build ambedkar-e2e/api:local and ambedkar-e2e/proxy:local
  powershell -File web/e2e/stack.ps1 up        # start, migrate (api entrypoint) and wait until healthy
  powershell -File web/e2e/stack.ps1 seed      # load the synthetic fixtures (archive.cli seed-fixtures)
  powershell -File web/e2e/stack.ps1 status
  powershell -File web/e2e/stack.ps1 llm-down  # restart api with an unreachable answer model
  powershell -File web/e2e/stack.ps1 llm-up    # restore the answer model from .env
  powershell -File web/e2e/stack.ps1 stop      # stop containers, keep volumes
  powershell -File web/e2e/stack.ps1 down      # remove containers AND this project's volumes
  powershell -File web/e2e/stack.ps1 rmi       # remove the two ambedkar-e2e images

  Every action logs to web/e2e/artifacts/stack-<action>.log.
  It never touches project ambedkar-archive (the demo stack on 8443).
#>
param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidateSet("build", "up", "seed", "status", "logs", "llm-down", "llm-up", "stop", "down", "rmi")]
  [string]$Action
)

$ErrorActionPreference = "Stop"
$Project = "ambedkar-e2e"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Base = Join-Path $Repo "docker-compose.yml"
$Override = Join-Path $PSScriptRoot "docker-compose.e2e.yml"
$LlmDown = Join-Path $PSScriptRoot "docker-compose.e2e-llm-down.yml"
$Artifacts = Join-Path $PSScriptRoot "artifacts"
New-Item -ItemType Directory -Force $Artifacts | Out-Null
$Log = Join-Path $Artifacts "stack-$Action.log"

function Assert-Project {
  # Three independent checks before anything that changes containers or volumes.
  if ($Project -ne "ambedkar-e2e") { throw "Project name is '$Project', expected 'ambedkar-e2e'." }
  if (-not (Select-String -Path $Override -Pattern '^name: ambedkar-e2e$' -Quiet)) { throw "$Override must declare name: ambedkar-e2e" }
  $foreign = docker ps -a --filter "label=com.docker.compose.project=$Project" --format "{{.Names}}" |
    Where-Object { $_ -and ($_ -notlike "$Project-*") }
  if ($foreign) { throw "Containers labelled $Project do not carry its prefix: $foreign" }
}

# Host ports and DB password for interpolation. Shell variables beat the repo .env.
$env:HTTP_PORT = "9088"
$env:HTTPS_PORT = "9443"
$env:DB_HOST_PORT = "56432"
$env:POSTGRES_PASSWORD = "e2e-throwaway-db"
$env:ARCHIVE_PUBLIC_BASE_URL = "https://localhost:9443"
$env:WORKER_CPUS = "1"
$env:WORKER_MEM = "2g"
$env:COMPOSE_PROJECT_NAME = $Project

function Compose([string[]]$Files, [string[]]$Rest) {
  # docker writes progress to stderr; Windows PowerShell would turn that into a terminating error.
  $ErrorActionPreference = "Continue"
  $fileArgs = @()
  foreach ($f in $Files) { $fileArgs += @("-f", $f) }
  $all = @("compose", "-p", $Project, "--project-directory", $Repo) + $fileArgs + $Rest
  "[$(Get-Date -Format s)] docker $($all -join ' ')" | Tee-Object -FilePath $Log -Append | Out-Host
  & docker @all 2>&1 | Tee-Object -FilePath $Log -Append | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "docker compose exited $LASTEXITCODE (see $Log)" }
}

$Std = @($Base, $Override)
Assert-Project
switch ($Action) {
  "build"    { Compose $Std @("build", "api", "proxy") }
  "up"       { Compose $Std @("up", "-d", "--wait", "--wait-timeout", "900") }
  "seed"     { Compose $Std @("exec", "-T", "api", "python", "-m", "archive.cli", "seed-fixtures") }
  "status"   { Compose $Std @("ps") }
  "logs"     { Compose $Std @("logs", "--no-color", "--tail", "200") }
  "llm-down" { Compose @($Base, $Override, $LlmDown) @("up", "-d", "--no-deps", "--wait", "--wait-timeout", "300", "api") }
  "llm-up"   { Compose $Std @("up", "-d", "--no-deps", "--wait", "--wait-timeout", "300", "api") }
  "stop"     { Compose $Std @("stop") }
  "down"     { Compose $Std @("down", "-v", "--remove-orphans") }
  "rmi"      {
    foreach ($img in @("ambedkar-e2e/api:local", "ambedkar-e2e/proxy:local")) {
      & docker image rm $img 2>&1 | Tee-Object -FilePath $Log -Append | Out-Host
    }
  }
}
