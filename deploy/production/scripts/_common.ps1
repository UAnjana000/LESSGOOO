# Shared helpers for the production operations scripts. Dot-source it: . "$PSScriptRoot\_common.ps1"
# Compatible with Windows PowerShell 5.1 and PowerShell 7.

$script:ProdRoot = Split-Path -Parent $PSScriptRoot
$script:ComposeFile = Join-Path $script:ProdRoot 'compose.yaml'

function Read-DotEnv {
    param([Parameter(Mandatory)] [string] $Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "Missing $Path" }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        $values[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
    }
    return $values
}

function Invoke-Compose {
    # Runs docker compose against the production file. Throws on a non-zero exit code.
    param([Parameter(Mandatory)] [string] $EnvFile, [Parameter(ValueFromRemainingArguments)] [string[]] $Rest)
    & docker compose --env-file $EnvFile -f $script:ComposeFile @Rest
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($Rest -join ' ') failed with exit code $LASTEXITCODE" }
}

function ConvertTo-HostPath {
    # Compose-style path (P:/archive/x or ./certs) to a Windows path, relative ones resolved from deploy/production.
    param([Parameter(Mandatory)] [string] $Path)
    $p = $Path -replace '/', '\'
    if (-not [IO.Path]::IsPathRooted($p)) { $p = Join-Path $script:ProdRoot $p }
    return $p
}

function Read-JsonFile {
    # PowerShell 5.1's ConvertFrom-Json caps input size; large backup manifests need the raw serializer.
    param([Parameter(Mandatory)] [string] $Path)
    $text = [IO.File]::ReadAllText($Path)
    if ($PSVersionTable.PSVersion.Major -ge 6) { return ($text | ConvertFrom-Json -AsHashtable) }
    Add-Type -AssemblyName System.Web.Extensions
    $ser = New-Object System.Web.Script.Serialization.JavaScriptSerializer
    $ser.MaxJsonLength = [int]::MaxValue
    return $ser.DeserializeObject($text)
}

function Write-Utf8NoBom {
    # Docker's env-file parser does not strip a UTF-8 BOM, which Set-Content -Encoding UTF8 adds in 5.1.
    param([Parameter(Mandatory)] [string] $Path, [Parameter(Mandatory)] [string] $Content)
    [IO.File]::WriteAllText($Path, ($Content -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding $false))
}
