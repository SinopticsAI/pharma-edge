. (Join-Path $PSScriptRoot "_common.ps1")
$folder = Get-AccountValue "YC_FOLDER_ID" "b1g07nbj3q7ccru38on0"
$name = Get-AccountValue "YDB_NAME" "pharma-edge"
$sa = Get-AccountValue "SA_FUNC_ID"

$dbs = yc ydb database list --folder-id $folder --format json | ConvertFrom-Json
$db = $dbs | Where-Object { $_.name -eq $name } | Select-Object -First 1
if (-not $db) {
    Write-Host "Creating serverless YDB $name"
    $db = yc ydb database create $name --serverless --folder-id $folder --format json | ConvertFrom-Json
    for ($i = 0; $i -lt 30; $i++) {
        $got = yc ydb database get --id $db.id --format json | ConvertFrom-Json
        Write-Host "ydb status=$($got.status)"
        if ($got.status -eq "RUNNING") { break }
        Start-Sleep -Seconds 10
    }
}
$got = yc ydb database get --id $db.id --format json | ConvertFrom-Json
$parts = $got.endpoint -split "/\?database=", 2
$endpoint = $parts[0]
$database = if ($parts.Count -gt 1) { $parts[1] } else { "" }
if ($sa) {
    try {
        yc ydb database add-access-binding --id $db.id --role ydb.editor --service-account-id $sa
    } catch {
        Write-Host "database access-binding skipped: $($_.Exception.Message)"
    }
}
Set-AccountValue "YDB_ID" $db.id
Set-AccountValue "YDB_ENDPOINT" $endpoint
Set-AccountValue "YDB_DATABASE" $database
Write-Host "YDB $name = $($db.id)"
Write-Host "YDB_ENDPOINT=$endpoint"
Write-Host "YDB_DATABASE=$database"
