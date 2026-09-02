# Managed PostgreSQL for the cabinet SoR and the agent memory.
#
# Two databases in one cluster, separate owners:
#   pharma_cabinet — Edge system of record
#   pharma_agent   — Mastra threads, working memory, workflow snapshots
#
# The cluster is shared with orders-panel production, so this script only adds
# and never drops. Run it once before the first deploy, then on demand.

. (Join-Path $PSScriptRoot "_common.ps1")

$folder = Get-AccountValue "YC_FOLDER_ID" "b1g07nbj3q7ccru38on0"
$clusterId = Get-AccountValue "PG_CLUSTER_ID" "c9qbferg3hcqjnqkghcp"
$diskLimitGb = [int](Get-AccountValue "PG_DISK_LIMIT_GB" "60")

# Functions and containers attached to a cloud network get addresses from this
# range, so the security group must let it reach the pooler.
$ServerlessCidr = "198.19.0.0/16"
$PoolerPort = 6432

function New-Password {
    $chars = (48..57) + (65..90) + (97..122)
    return -join ($chars | Get-Random -Count 32 | ForEach-Object { [char]$_ })
}

Write-Host "== cluster =="
$cluster = Invoke-YcJson @("managed-postgresql", "cluster", "get", "--id", $clusterId)
if (-not $cluster) {
    throw "PostgreSQL cluster $clusterId not found. Check PG_CLUSTER_ID in infra/account.env."
}
Write-Host "cluster $($cluster.name) status=$($cluster.status) network=$($cluster.network_id)"
Set-AccountValue "PG_CLUSTER_ID" $clusterId
Set-AccountValue "VPC_NETWORK_ID" $cluster.network_id
Set-AccountValue "PG_HOST" "c-$clusterId.rw.mdb.yandexcloud.net"
Set-AccountValue "PG_PORT" "$PoolerPort"

# --- cluster hardening ------------------------------------------------------
# serverless access is what lets Cloud Functions and Serverless Containers
# open a connection at all; the rest is durability of a store that is about to
# become the system of record.
Write-Host "== hardening =="
try {
    yc managed-postgresql cluster update --id $clusterId `
        --deletion-protection `
        --serverless-access `
        --disk-size-autoscaling-disk-size-limit "${diskLimitGb}GB" `
        --disk-size-autoscaling-planned-usage-threshold 70 `
        --disk-size-autoscaling-emergency-usage-threshold 85
    Write-Host "deletion protection, serverless access and disk autoscaling up to ${diskLimitGb}GB applied"
} catch {
    Write-Host "cluster update skipped: $($_.Exception.Message)"
    Write-Host "apply manually: deletion protection, serverless access, disk autoscaling"
}

# --- replica ----------------------------------------------------------------
# One host means no failover. Add a second in a different zone before prod.
$hosts = Invoke-YcJson @("managed-postgresql", "host", "list", "--cluster-id", $clusterId)
$hostCount = @($hosts).Count
Write-Host "hosts: $hostCount"
if ($hostCount -lt 2) {
    $zone = Get-AccountValue "PG_REPLICA_ZONE" "ru-central1-b"
    $subnet = Get-AccountValue "PG_REPLICA_SUBNET_ID" ""
    if (-not $subnet) {
        Write-Host "PG_REPLICA_SUBNET_ID is empty — set it and re-run to add a replica in $zone"
    } else {
        Write-Host "Adding replica in $zone"
        try {
            yc managed-postgresql host add --cluster-id $clusterId --host "zone-id=$zone,subnet-id=$subnet"
        } catch {
            Write-Host "replica add skipped: $($_.Exception.Message)"
        }
    }
}

# --- security group ---------------------------------------------------------
Write-Host "== security group =="
$sgId = Get-AccountValue "PG_SECURITY_GROUP_ID" ""
if (-not $sgId -and $cluster.security_group_ids) {
    $sgId = @($cluster.security_group_ids)[0]
    Set-AccountValue "PG_SECURITY_GROUP_ID" $sgId
}
if ($sgId) {
    $sg = Invoke-YcJson @("vpc", "security-group", "get", "--id", $sgId)
    $hasRule = $false
    foreach ($rule in @($sg.rules)) {
        if ($rule.direction -eq "INGRESS" -and $rule.ports.from_port -le $PoolerPort -and $rule.ports.to_port -ge $PoolerPort) {
            $hasRule = $true
        }
    }
    if ($hasRule) {
        Write-Host "ingress on $PoolerPort already present"
    } else {
        Write-Host "Adding ingress $PoolerPort from $ServerlessCidr"
        try {
            yc vpc security-group update-rules --id $sgId `
                --add-rule "direction=ingress,port=$PoolerPort,protocol=tcp,v4-cidrs=[$ServerlessCidr]"
        } catch {
            Write-Host "rule add skipped: $($_.Exception.Message)"
        }
    }
} else {
    Write-Host "no security group on the cluster — nothing to open"
}

# --- users and databases ----------------------------------------------------
Write-Host "== databases =="
$existingUsers = Invoke-YcJson @("managed-postgresql", "user", "list", "--cluster-id", $clusterId)
$existingDbs = Invoke-YcJson @("managed-postgresql", "database", "list", "--cluster-id", $clusterId)
$passwords = @{}

foreach ($name in @("pharma_cabinet", "pharma_agent")) {
    $user = @($existingUsers) | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if (-not $user) {
        $password = New-Password
        $passwords[$name] = $password
        Write-Host "Creating user $name"
        yc managed-postgresql user create $name `
            --cluster-id $clusterId `
            --password $password `
            --conn-limit 50 `
            --permissions $name
    } else {
        Write-Host "user $name exists — password left as is"
    }

    $db = @($existingDbs) | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if (-not $db) {
        Write-Host "Creating database $name"
        yc managed-postgresql database create $name --cluster-id $clusterId --owner $name
    } else {
        Write-Host "database $name exists"
    }
}

# --- lockbox ----------------------------------------------------------------
if ($passwords.Count -gt 0) {
    Write-Host "== lockbox =="
    $entries = @()
    foreach ($key in $passwords.Keys) {
        $entries += @{ key = "${key}_password"; textValue = $passwords[$key] }
    }
    $payloadJson = ($entries | ConvertTo-Json -Compress -Depth 5)
    $secrets = Invoke-YcJson @("lockbox", "secret", "list", "--folder-id", $folder)
    $existing = @($secrets) | Where-Object { $_.name -eq "pharma-edge-pg" } | Select-Object -First 1
    if (-not $existing) {
        $secret = yc lockbox secret create --name "pharma-edge-pg" --payload $payloadJson --folder-id $folder --format json | ConvertFrom-Json
        Set-AccountValue "LOCKBOX_PG_ID" $secret.id
        Write-Host "Lockbox pharma-edge-pg created"
    } else {
        Set-AccountValue "LOCKBOX_PG_ID" $existing.id
        yc lockbox secret add-version --id $existing.id --payload $payloadJson
        Write-Host "Lockbox pharma-edge-pg updated"
    }
    Write-Host "Passwords are only in Lockbox. They are not printed and not written to account.env."
}

Write-Host ""
Write-Host "Done. Connection: c-$clusterId.rw.mdb.yandexcloud.net:$PoolerPort, sslmode=verify-full"
Write-Host "Root certificate: https://storage.yandexcloud.net/cloud-certs/CA.pem"
Write-Host "Next: apply sql/01_cabinet.sql to pharma_cabinet."
