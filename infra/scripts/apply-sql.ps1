. (Join-Path $PSScriptRoot "_common.ps1")
$ydbId = Get-AccountValue "YDB_ID"
$endpoint = Get-AccountValue "YDB_ENDPOINT"
$database = Get-AccountValue "YDB_DATABASE"
if (-not $ydbId -and -not ($endpoint -and $database)) {
    throw "YDB_ID or YDB_ENDPOINT/YDB_DATABASE is empty; run ensure-ydb.ps1 first"
}

$sqlFiles = @(
    (Join-Path $RepoRoot "sql\01_edge_sor.sql"),
    (Join-Path $RepoRoot "sql\02_seed.sql")
)

function Invoke-YqlFile {
    param([string]$File)
    Write-Host "Applying $File"
    if (Get-Command ydb -ErrorAction SilentlyContinue) {
        if (-not $endpoint -or -not $database) { throw "YDB_ENDPOINT/YDB_DATABASE required for ydb CLI" }
        $token = yc iam create-token
        $env:YDB_TOKEN = $token
        ydb --endpoint $endpoint --database $database scripting yql --file $File
        if ($LASTEXITCODE -ne 0) { throw "ydb apply failed for $File" }
        return
    }
    if ($ydbId) {
        yc ydb scripting yql execute --id $ydbId --file $File
        if ($LASTEXITCODE -eq 0) { return }
    }
    throw "No ydb CLI and yc ydb scripting failed for $File"
}

foreach ($file in $sqlFiles) {
    Invoke-YqlFile -File $file
}
Write-Host "YDB schema applied"
