# Apply the cabinet schema to Managed PostgreSQL.
#
# The cluster has no public host, so this runs from inside the network: a VM in
# the same cloud network, or a tunnel. Password comes from Lockbox, not here.

. (Join-Path $PSScriptRoot "_common.ps1")

$pgHost = Get-AccountValue "PG_HOST"
$pgPort = Get-AccountValue "PG_PORT" "6432"
$database = Get-AccountValue "PG_CABINET_DB" "pharma_cabinet"
$user = Get-AccountValue "PG_CABINET_USER" "pharma_cabinet"
$lockboxId = Get-AccountValue "LOCKBOX_PG_ID"

if (-not $pgHost) {
    throw "PG_HOST is empty; run ensure-postgres.ps1 first"
}
if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
    throw "psql not found. Install the PostgreSQL client or apply sql/*.sql through WebSQL."
}

$certPath = Join-Path $env:USERPROFILE ".postgresql\root.crt"
if (-not (Test-Path $certPath)) {
    Write-Host "Downloading Yandex root certificate"
    New-Item -ItemType Directory -Force -Path (Split-Path $certPath) | Out-Null
    curl.exe -sS -o $certPath "https://storage.yandexcloud.net/cloud-certs/CA.pem"
}

if (-not $env:PGPASSWORD) {
    if (-not $lockboxId) {
        throw "Set PGPASSWORD or LOCKBOX_PG_ID so the password can be read from Lockbox"
    }
    $payload = Invoke-YcJson @("lockbox", "payload", "get", "--id", $lockboxId)
    $entry = @($payload.entries) | Where-Object { $_.key -eq "${user}_password" } | Select-Object -First 1
    if (-not $entry) { throw "Lockbox $lockboxId has no key ${user}_password" }
    $env:PGPASSWORD = $entry.text_value
}

$sqlFiles = @(
    (Join-Path $RepoRoot "sql\01_cabinet.sql"),
    (Join-Path $RepoRoot "sql\02_seed.sql")
)

$connection = "host=$pgHost port=$pgPort dbname=$database user=$user sslmode=verify-full"
foreach ($file in $sqlFiles) {
    Write-Host "Applying $file"
    psql $connection -v ON_ERROR_STOP=1 -f $file
    if ($LASTEXITCODE -ne 0) { throw "psql failed on $file" }
}

$env:PGPASSWORD = $null
Write-Host "Cabinet schema applied to $database"
