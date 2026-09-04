. (Join-Path $PSScriptRoot "_common.ps1")
$folder = Get-AccountValue "YC_FOLDER_ID" "b1g07nbj3q7ccru38on0"
$bucket = Get-AccountValue "DOSSIER_BUCKET" "pharma-dossier"

function Ensure-ServiceAccount {
    param([string]$Name, [string[]]$Roles, [string]$AccountKey)
    $list = yc iam service-account list --folder-id $folder --format json | ConvertFrom-Json
    $sa = $list | Where-Object { $_.name -eq $Name } | Select-Object -First 1
    if (-not $sa) {
        Write-Host "Creating SA $Name"
        $sa = yc iam service-account create --name $Name --description "pharma-edge" --folder-id $folder --format json | ConvertFrom-Json
    }
    Set-AccountValue $AccountKey $sa.id
    foreach ($role in $Roles) {
        try {
            yc resource-manager folder add-access-binding --id $folder --role $role --service-account-id $sa.id
        } catch {
            Write-Host "role $role on $Name skipped: $($_.Exception.Message)"
        }
    }
    return $sa.id
}

$funcId = Ensure-ServiceAccount -Name "pharma-edge-sa-func" -AccountKey "SA_FUNC_ID" -Roles @(
    "functions.functionInvoker",
    "ymq.writer",
    "ymq.reader",
    "storage.editor",
    "lockbox.payloadViewer",
    # Functions run inside the cluster network to reach the pooler.
    "vpc.user"
)
$gwSa = Ensure-ServiceAccount -Name "pharma-edge-sa-gateway" -AccountKey "SA_API_GATEWAY_ID" -Roles @(
    "functions.functionInvoker",
    "serverless-containers.containerInvoker",
    "storage.viewer"
)
$ciSa = Ensure-ServiceAccount -Name "pharma-edge-sa-ci" -AccountKey "SA_CI_ID" -Roles @(
    "functions.editor",
    "serverless.functions.invoker",
    "ymq.admin",
    "storage.editor",
    "lockbox.editor",
    "lockbox.viewer",
    "lockbox.payloadViewer",
    "mdb.viewer",
    "vpc.user",
    "api-gateway.editor",
    "serverless-containers.viewer",
    "iam.serviceAccounts.user"
)
Write-Host "SA func=$funcId gateway=$gwSa ci=$ciSa"

$buckets = yc storage bucket list --format json | ConvertFrom-Json
$exists = $buckets | Where-Object { $_.name -eq $bucket } | Select-Object -First 1
if (-not $exists) {
    Write-Host "Creating private bucket $bucket"
    yc storage bucket create --name $bucket --default-storage-class standard
}
try {
    yc storage bucket update --name $bucket --private
} catch {
    Write-Host "bucket private update skipped: $($_.Exception.Message)"
}

# The SPA PUTs the file itself to a presigned URL. Object Storage answers
# OPTIONS without CORS headers unless the bucket has a rule, and the UI then
# reports storage_unreachable ("signed link is unavailable").
$portalOrigin = Get-AccountValue "PORTAL_ORIGIN" "https://pharma.sinoptics.ru"
try {
    $cors = "allowed-methods='[method-put,method-get,method-head]',allowed-origins='[$portalOrigin]',allowed-headers='[*]',expose-headers='[ETag]',max-age-seconds=3600"
    yc storage bucket update --name $bucket --cors $cors
    Write-Host "bucket CORS for $portalOrigin"
} catch {
    Write-Host "bucket CORS update skipped: $($_.Exception.Message)"
}

function Ensure-Lockbox {
    param([string]$Name, [string]$AccountKey, [hashtable]$Entries)
    $secrets = yc lockbox secret list --folder-id $folder --format json | ConvertFrom-Json
    $secret = $secrets | Where-Object { $_.name -eq $Name } | Select-Object -First 1
    $payload = @()
    foreach ($key in $Entries.Keys) {
        $payload += @{ key = $key; textValue = [string]$Entries[$key] }
    }
    $payloadJson = ($payload | ConvertTo-Json -Compress -Depth 5)
    if (-not $secret) {
        Write-Host "Creating Lockbox $Name"
        $secret = yc lockbox secret create --name $Name --payload $payloadJson --folder-id $folder --format json | ConvertFrom-Json
    }
    Set-AccountValue $AccountKey $secret.id
    return $secret.id
}

$apiKey = -join ((48..57 + 97..122) | Get-Random -Count 40 | ForEach-Object { [char]$_ })
$httpSecrets = yc lockbox secret list --folder-id $folder --format json | ConvertFrom-Json
$httpExisting = $httpSecrets | Where-Object { $_.name -eq "pharma-edge-http" } | Select-Object -First 1
if (-not $httpExisting) {
    Ensure-Lockbox -Name "pharma-edge-http" -AccountKey "LOCKBOX_HTTP_ID" -Entries @{ PHARMA_EDGE_API_KEY = $apiKey }
    Write-Host "Generated PHARMA_EDGE_API_KEY (stored in Lockbox pharma-edge-http)"
} else {
    Set-AccountValue "LOCKBOX_HTTP_ID" $httpExisting.id
}

$s3Secrets = yc lockbox secret list --folder-id $folder --format json | ConvertFrom-Json
$s3Existing = $s3Secrets | Where-Object { $_.name -eq "pharma-edge-s3" } | Select-Object -First 1
if (-not $s3Existing) {
    Write-Host "Creating Object Storage access key for $funcId"
    $key = yc iam access-key create --service-account-id $funcId --format json | ConvertFrom-Json
    Ensure-Lockbox -Name "pharma-edge-s3" -AccountKey "LOCKBOX_S3_ID" -Entries @{
        AWS_ACCESS_KEY_ID = $key.key_id
        AWS_SECRET_ACCESS_KEY = $key.secret
    }
} else {
    Set-AccountValue "LOCKBOX_S3_ID" $s3Existing.id
}

function Ensure-Queue {
    param([string]$Name)
    try {
        $q = yc message-queue queue get --name $Name --format json 2>$null | ConvertFrom-Json
        if ($q) { return $q }
    } catch { }
    Write-Host "Creating queue $Name"
    return yc message-queue queue create --name $Name --format json | ConvertFrom-Json
}

$queueNames = @(
    "pharma-ingest-dlq", "pharma-item-update-dlq", "pharma-completed-dlq", "pharma-intel-dlq",
    "pharma-ingest", "pharma-item-update", "pharma-completed", "pharma-intel"
)
$urls = @{}
foreach ($qname in $queueNames) {
    $q = Ensure-Queue -Name $qname
    $url = $q.url
    if (-not $url) { $url = $q.QueueUrl }
    if ($url) { $urls[$qname] = $url }
}

$ymqExisting = (yc lockbox secret list --folder-id $folder --format json | ConvertFrom-Json) |
    Where-Object { $_.name -eq "pharma-edge-ymq" } | Select-Object -First 1
if (-not $ymqExisting) {
    Ensure-Lockbox -Name "pharma-edge-ymq" -AccountKey "LOCKBOX_YMQ_ID" -Entries @{
        PHARMA_INGEST_QUEUE_URL = $(if ($urls.ContainsKey("pharma-ingest")) { $urls["pharma-ingest"] } else { "" })
        PHARMA_ITEM_UPDATE_QUEUE_URL = $(if ($urls.ContainsKey("pharma-item-update")) { $urls["pharma-item-update"] } else { "" })
        PHARMA_COMPLETED_QUEUE_URL = $(if ($urls.ContainsKey("pharma-completed")) { $urls["pharma-completed"] } else { "" })
        PHARMA_INTEL_QUEUE_URL = $(if ($urls.ContainsKey("pharma-intel")) { $urls["pharma-intel"] } else { "" })
    }
} else {
    Set-AccountValue "LOCKBOX_YMQ_ID" $ymqExisting.id
}

Write-Host "Provision finished. Run ensure-ydb.ps1 next."
