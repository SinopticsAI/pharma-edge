. (Join-Path $PSScriptRoot "_common.ps1")
$zone = Get-AccountValue "DNS_ZONE_SINOPTICS_RU_ID" "dns5ia445jp8cqmbnnfk"
$custom = Get-AccountValue "CUSTOM_DOMAIN" "pharma-edge.sinoptics.ru"
$domain = Get-AccountValue "API_GATEWAY_DOMAIN"
if (-not $domain) { throw "API_GATEWAY_DOMAIN is empty; run deploy-gateway.ps1 first" }
$target = $domain.TrimEnd(".") + "."
Write-Host "CNAME $custom. -> $target"
$records = yc dns zone list-records --id $zone --format json | ConvertFrom-Json
$exists = $records | Where-Object { ($_.name.TrimEnd(".")) -eq $custom }
if ($exists) {
    yc dns zone replace-records --id $zone --record "$custom. 600 CNAME $target"
} else {
    yc dns zone add-records --id $zone --record "$custom. 600 CNAME $target"
}
Write-Host "DNS updated"
