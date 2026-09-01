$ErrorActionPreference = "Stop"
$env:YC_CLI_INITIALIZATION_SILENCE = "true"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$InfraDir = Join-Path $RepoRoot "infra"
$AccountEnv = Join-Path $InfraDir "account.env"
$AccountExample = Join-Path $InfraDir "account.env.example"

function Read-AccountEnv {
    $values = @{}
    $path = if (Test-Path $AccountEnv) { $AccountEnv } else { $AccountExample }
    Get-Content $path | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
        $name, $rest = $_.Split("=", 2)
        $values[$name.Trim()] = $rest.Trim()
    }
    return $values
}

function Set-AccountValue {
    param([string]$Name, [string]$Value)
    if (-not (Test-Path $AccountEnv)) {
        Copy-Item $AccountExample $AccountEnv
    }
    $lines = Get-Content $AccountEnv
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^$Name=") {
            $found = $true
            "$Name=$Value"
        } else {
            $line
        }
    }
    if (-not $found) {
        $out += "$Name=$Value"
    }
    Set-Content -Path $AccountEnv -Value $out -Encoding utf8
}

function Get-AccountValue {
    param([string]$Name, [string]$Default = "")
    $all = Read-AccountEnv
    if ($all.ContainsKey($Name) -and $all[$Name]) { return $all[$Name] }
    return $Default
}

function Invoke-YcJson {
    param([string[]]$Args)
    $raw = yc @Args --format json
    if (-not $raw) { return $null }
    return $raw | ConvertFrom-Json
}
