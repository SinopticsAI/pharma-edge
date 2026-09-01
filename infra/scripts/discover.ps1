. (Join-Path $PSScriptRoot "_common.ps1")
$folder = Get-AccountValue "YC_FOLDER_ID" "b1g07nbj3q7ccru38on0"

Write-Host "Discovering folder $folder"
$nets = yc vpc network list --format json | ConvertFrom-Json
if ($nets) {
    Set-AccountValue "VPC_NETWORK_ID" $nets[0].id
    Write-Host "VPC $($nets[0].id) $($nets[0].name)"
}
$subs = yc vpc subnet list --format json | ConvertFrom-Json
if ($subs) {
    Set-AccountValue "VPC_SUBNET_ID" $subs[0].id
    Write-Host "subnet $($subs[0].id) $($subs[0].name)"
}
$certs = yc certificate-manager certificate list --format json | ConvertFrom-Json
$wild = $certs | Where-Object { $_.name -match "wildcard" } | Select-Object -First 1
if (-not $wild -and $certs) { $wild = $certs[0] }
if ($wild) {
    Set-AccountValue "CERT_WILDCARD_SINOPTICS_RU_ID" $wild.id
    Write-Host "cert $($wild.id) $($wild.name)"
}
$zones = yc dns zone list --format json | ConvertFrom-Json
$zone = $zones | Where-Object { $_.zone -eq "sinoptics.ru." -or $_.name -match "sinoptics" } | Select-Object -First 1
if ($zone) {
    Set-AccountValue "DNS_ZONE_SINOPTICS_RU_ID" $zone.id
    Write-Host "dns $($zone.id) $($zone.zone)"
}

$fnMap = @{
    "pharma-edge-cases" = "FN_CASES"
    "pharma-edge-case-get" = "FN_CASE_GET"
    "pharma-edge-case-update" = "FN_CASE_UPDATE"
    "pharma-edge-dossier-items" = "FN_DOSSIER_ITEMS"
    "pharma-edge-status-ingest" = "FN_STATUS_INGEST"
    "pharma-edge-registry-search" = "FN_REGISTRY_SEARCH"
    "pharma-edge-calendar-tick" = "FN_CALENDAR_TICK"
}
$fns = yc serverless function list --folder-id $folder --format json | ConvertFrom-Json
foreach ($pair in $fnMap.GetEnumerator()) {
    $found = $fns | Where-Object { $_.name -eq $pair.Key } | Select-Object -First 1
    if ($found) { Set-AccountValue $pair.Value $found.id }
}

$gw = yc serverless api-gateway list --folder-id $folder --format json | ConvertFrom-Json
$ourGw = $gw | Where-Object { $_.name -eq "pharma-edge-api-gateway" } | Select-Object -First 1
if ($ourGw) {
    Set-AccountValue "API_GATEWAY_ID" $ourGw.id
    if ($ourGw.domain) { Set-AccountValue "API_GATEWAY_DOMAIN" $ourGw.domain }
}

$sas = yc iam service-account list --folder-id $folder --format json | ConvertFrom-Json
foreach ($name in @("pharma-edge-sa-func", "pharma-edge-sa-gateway", "pharma-edge-sa-ci")) {
    $sa = $sas | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if (-not $sa) { continue }
    if ($name -eq "pharma-edge-sa-func") { Set-AccountValue "SA_FUNC_ID" $sa.id }
    if ($name -eq "pharma-edge-sa-gateway") { Set-AccountValue "SA_API_GATEWAY_ID" $sa.id }
    if ($name -eq "pharma-edge-sa-ci") { Set-AccountValue "SA_CI_ID" $sa.id }
}

$ydbName = Get-AccountValue "YDB_NAME" "pharma-edge"
$dbs = yc ydb database list --folder-id $folder --format json | ConvertFrom-Json
$db = $dbs | Where-Object { $_.name -eq $ydbName } | Select-Object -First 1
if ($db) {
    Set-AccountValue "YDB_ID" $db.id
}

Write-Host "Wrote $AccountEnv"
