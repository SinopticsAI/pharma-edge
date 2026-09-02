. (Join-Path $PSScriptRoot "_common.ps1")
$folder = Get-AccountValue "YC_FOLDER_ID" "b1g07nbj3q7ccru38on0"
$sa = Get-AccountValue "SA_FUNC_ID"
if (-not $sa) { throw "SA_FUNC_ID is empty; run provision.ps1 first" }

python (Join-Path $PSScriptRoot "sync_shared.py")
if ($LASTEXITCODE -ne 0) { throw "sync_shared.py failed" }

$manifestPath = Join-Path $RepoRoot ".github\functions-paths.json"
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$only = $args
$bucket = Get-AccountValue "DOSSIER_BUCKET" "pharma-dossier"
$lockboxHttp = Get-AccountValue "LOCKBOX_HTTP_ID"
$lockboxS3 = Get-AccountValue "LOCKBOX_S3_ID"
$lockboxPg = Get-AccountValue "LOCKBOX_PG_ID"
$pgHost = Get-AccountValue "PG_HOST"
$pgPort = Get-AccountValue "PG_PORT" "6432"
$pgDatabase = Get-AccountValue "PG_CABINET_DB" "pharma_cabinet"
$pgUser = Get-AccountValue "PG_CABINET_USER" "pharma_cabinet"
# The managed cluster has no public host, so a function without a network
# cannot reach the pooler at all.
$networkId = Get-AccountValue "VPC_NETWORK_ID"
if (-not $networkId) { throw "VPC_NETWORK_ID is empty; run ensure-postgres.ps1 first" }
$planeBase = Get-AccountValue "PHARMA_PLANE_BASE_URL"

$envKeyMap = @{
    identity = "FN_IDENTITY"
    organizations = "FN_ORGANIZATIONS"
    organization_items = "FN_ORGANIZATION_ITEMS"
    products = "FN_PRODUCTS"
    intake = "FN_INTAKE"
    cases = "FN_CASES"
    case_get = "FN_CASE_GET"
    case_update = "FN_CASE_UPDATE"
    case_start = "FN_CASE_START"
    dossier_items = "FN_DOSSIER_ITEMS"
    status_ingest = "FN_STATUS_INGEST"
    registry_search = "FN_REGISTRY_SEARCH"
    webhooks = "FN_WEBHOOKS"
    calendar_tick = "FN_CALENDAR_TICK"
}

$fns = yc serverless function list --folder-id $folder --format json | ConvertFrom-Json
foreach ($entry in $manifest) {
    if ($only.Count -gt 0 -and $only -notcontains $entry.id) { continue }
    $name = $entry.yc_name
    $src = Join-Path $RepoRoot $entry.path
    $fn = $fns | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if (-not $fn) {
        Write-Host "Creating function $name"
        $fn = yc serverless function create --name $name --folder-id $folder --format json | ConvertFrom-Json
        $fns = yc serverless function list --folder-id $folder --format json | ConvertFrom-Json
    }
    $accountKey = $envKeyMap[$entry.id]
    if ($accountKey) { Set-AccountValue $accountKey $fn.id }

    $envArg = "DEPLOY_ENV=prod,YC_FUNCTION_NAME=$name,DOSSIER_BUCKET=$bucket,S3_ENDPOINT=https://storage.yandexcloud.net"
    $envArg = "$envArg,PG_HOST=$pgHost,PG_PORT=$pgPort,PG_DATABASE=$pgDatabase,PG_USER=$pgUser,PG_SSLMODE=verify-full"
    if ($planeBase) {
        $envArg = "$envArg,PHARMA_PLANE_BASE_URL=$planeBase"
    }
    $versionArgs = @(
        "serverless", "function", "version", "create",
        "--function-id", $fn.id,
        "--runtime", "python312",
        "--entrypoint", "index.handler",
        "--memory", "256m",
        "--execution-timeout", "30s",
        "--source-path", $src,
        "--service-account-id", $sa,
        "--network-id", $networkId,
        "--environment", $envArg
    )
    if ($lockboxHttp) {
        $versionArgs += @("--secret", "environment-variable=PHARMA_EDGE_API_KEY,id=$lockboxHttp,key=PHARMA_EDGE_API_KEY")
    }
    if ($lockboxPg) {
        $versionArgs += @("--secret", "environment-variable=PG_PASSWORD,id=$lockboxPg,key=${pgUser}_password")
    }
    # Presigned uploads happen in two places now: case dossiers and intake.
    if ($lockboxS3 -and ($entry.id -eq "dossier_items" -or $entry.id -eq "organization_items")) {
        $versionArgs += @("--secret", "environment-variable=AWS_ACCESS_KEY_ID,id=$lockboxS3,key=AWS_ACCESS_KEY_ID")
        $versionArgs += @("--secret", "environment-variable=AWS_SECRET_ACCESS_KEY,id=$lockboxS3,key=AWS_SECRET_ACCESS_KEY")
    }
    Write-Host "Publishing $name ($($fn.id))"
    yc @versionArgs
    if ($LASTEXITCODE -ne 0) { throw "version create failed for $name" }
}

$triggers = yc serverless trigger list --folder-id $folder --format json | ConvertFrom-Json
$tick = $triggers | Where-Object { $_.name -eq "pharma-edge-calendar-tick" } | Select-Object -First 1
if (-not $tick) {
    Write-Host "Creating timer pharma-edge-calendar-tick"
    yc serverless trigger create timer `
        --name pharma-edge-calendar-tick `
        --cron-expression "0 3 * * ? *" `
        --invoke-function-name pharma-edge-calendar-tick `
        --invoke-function-service-account-id $sa `
        --folder-id $folder
} else {
    Write-Host "Timer pharma-edge-calendar-tick already exists"
}

Write-Host "Functions deployed"
