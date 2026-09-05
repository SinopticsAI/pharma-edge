# Canon: SinopticsAI/pharma_env. Keep this copy in sync or run that repo.
# The gateway and the CNAME are created there; here it is a convenience for
# re-rendering the spec after a function deploy.

. (Join-Path $PSScriptRoot "_common.ps1")
$folder = Get-AccountValue "YC_FOLDER_ID" "b1g07nbj3q7ccru38on0"
$name = Get-AccountValue "API_GATEWAY_NAME" "pharma-edge-api-gateway"
$domain = Get-AccountValue "CUSTOM_DOMAIN" "pharma-edge.sinoptics.ru"
$sa = Get-AccountValue "SA_API_GATEWAY_ID"
if (-not $sa) { throw "SA_API_GATEWAY_ID is empty; run provision.ps1 first" }
if (-not (Get-AccountValue "FN_CASES")) { throw "FN_CASES is empty; run deploy-function.ps1 first" }

python (Join-Path $PSScriptRoot "render_gateway.py")
if ($LASTEXITCODE -ne 0) { throw "render_gateway.py failed" }
$spec = Join-Path $InfraDir "gateway\openapi.yaml"

$list = yc serverless api-gateway list --folder-id $folder --format json | ConvertFrom-Json
$gw = $list | Where-Object { $_.name -eq $name } | Select-Object -First 1
if (-not $gw) {
    $created = yc serverless api-gateway create --name $name --description "Pharma Edge API" --spec $spec --folder-id $folder --format json | ConvertFrom-Json
    $gwId = $created.id
    $gwDomain = $created.domain
} else {
    $gwId = $gw.id
    yc serverless api-gateway update --id $gwId --spec $spec
    $got = yc serverless api-gateway get --id $gwId --format json | ConvertFrom-Json
    $gwDomain = $got.domain
}
Set-AccountValue "API_GATEWAY_ID" $gwId
if ($gwDomain) { Set-AccountValue "API_GATEWAY_DOMAIN" $gwDomain }

# Domain and certificate are owned by pharma_env. Reattaching here swapped
# a working managed cert for CERT_WILDCARD and broke TLS on the custom domain.
$attached = (yc serverless api-gateway get --id $gwId --format json | ConvertFrom-Json).attached_domains
$current = $attached | Where-Object { $_.domain -eq $domain } | Select-Object -First 1
if ($current) {
    Write-Host "Domain $domain already attached cert=$($current.certificate_id); leave as-is"
} else {
    Write-Host "WARNING: $domain is not attached; run deploy-gateway.ps1 in SinopticsAI/pharma_env"
}

Write-Host "Gateway $name = $gwId domain=$gwDomain"
Write-Host "Do not update pharma-api-gateway from this repo."
