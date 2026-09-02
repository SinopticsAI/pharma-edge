#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Auto: git add -A -> git commit (auto-generated English message) -> git push origin HEAD.

.DESCRIPTION
    Stages all changes, builds a Conventional-Commit-ish English commit message
    from the staged diff (file paths + per-file status + shortstat), commits,
    and pushes to the current branch on the `origin` remote.

    Designed to be invoked from a VS Code / Cursor task (.vscode/tasks.json) but
    also runnable standalone from any PowerShell host (5.1 or 7+).

    Idempotent: exits 0 with a notice when there is nothing to commit.

    Works for the very first commit too (no HEAD): uses git's empty-tree object
    as the diff base.

.PARAMETER Message
    Override the auto-generated commit subject. The body (file list + shortstat)
    is still appended.

.PARAMETER NoPush
    Commit but do not push.

.PARAMETER DryRun
    Print what would be done without changing anything (works on a temporary
    index copy via GIT_INDEX_FILE; the real .git/index is not touched).

.PARAMETER NoAdd
    Skip `git add -A`; commit only what is already staged.

.EXAMPLE
    powershell -NoProfile -File .\scripts\git-autocommit.ps1
.EXAMPLE
    powershell -NoProfile -File .\scripts\git-autocommit.ps1 -DryRun
.EXAMPLE
    powershell -NoProfile -File .\scripts\git-autocommit.ps1 -Message "fix: broken deploy step"
#>

[CmdletBinding()]
param(
    [string]$Message,
    [switch]$NoPush,
    [switch]$DryRun,
    [switch]$NoAdd
)

# Use 'Continue' so non-zero exits / stderr from native git commands don't
# become terminating errors. Failure of must-succeed calls is handled explicitly
# via Invoke-Git (which throws) or by checking $LASTEXITCODE after the call.
$ErrorActionPreference = 'Continue'
# PS 7.4+: also disable auto-throwing on native command non-zero exits.
$PSNativeCommandUseErrorActionPreference = $false

# git's well-known empty-tree object id (works in every repo, no commits needed)
$EmptyTree = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $out = & git @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed (exit $LASTEXITCODE):`n$out"
    }
    return $out
}

function Test-GitOk {
    # Run a git command, suppress all output, return $true on exit 0.
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $null = & git @Arguments 2>&1
    return $LASTEXITCODE -eq 0
}

# --- locate repo root --------------------------------------------------------

if (-not (Test-GitOk rev-parse --is-inside-work-tree)) {
    Write-Error "Not a git repository: $(Get-Location)"
    exit 1
}

$repoRoot = (Invoke-Git rev-parse --show-toplevel) | Select-Object -First 1
$gitDir   = (Invoke-Git rev-parse --git-dir)        | Select-Object -First 1
if (-not [System.IO.Path]::IsPathRooted($gitDir)) {
    $gitDir = Join-Path $repoRoot $gitDir
}

# Does HEAD point at any commit yet?
$hasHead  = Test-GitOk rev-parse --verify HEAD
$diffBase = if ($hasHead) { 'HEAD' } else { $EmptyTree }

Push-Location $repoRoot
$tempIndex = $null
try {
    Write-Host "Repo: $repoRoot" -ForegroundColor DarkGray
    if (-not $hasHead) {
        Write-Host "(no commits yet - this will create the initial commit)" -ForegroundColor DarkGray
    }

    # --- stage --------------------------------------------------------------
    # In dry-run we redirect the staging area to a throwaway index file so the
    # user's real .git/index is never modified.

    if ($DryRun -and -not $NoAdd) {
        $tempIndex = Join-Path $gitDir ('index.autocommit-dryrun-' + [guid]::NewGuid().Guid.Substring(0, 8))
        $realIndex = Join-Path $gitDir 'index'
        if (Test-Path -LiteralPath $realIndex) {
            Copy-Item -LiteralPath $realIndex -Destination $tempIndex -Force
        }
        $env:GIT_INDEX_FILE = $tempIndex
    }

    if (-not $NoAdd) {
        Invoke-Git -- add -A | Out-Null
        if ($DryRun) { Write-Host '[dry-run] simulated: git add -A (on temp index)' -ForegroundColor Yellow }
    }

    # --- collect staged entries --------------------------------------------

    $rawStatus = & git diff --cached $diffBase --name-status 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git diff --cached failed:`n$rawStatus"
    }
    if (-not $rawStatus) {
        Write-Host 'Nothing to commit.' -ForegroundColor Yellow
        exit 0
    }

    $entries = @()
    foreach ($line in $rawStatus) {
        if (-not $line) { continue }
        $parts = $line -split "`t"
        $rawSt = $parts[0]
        $st = $rawSt.Substring(0, 1)
        # Renames/copies: status looks like "R100", new path is $parts[2]
        if ($rawSt -like 'R*' -or $rawSt -like 'C*') {
            $path = $parts[2]
        } else {
            $path = $parts[1]
        }
        $entries += [PSCustomObject]@{ Status = $st; Path = $path }
    }

    # --- heuristic: prefix --------------------------------------------------

    function Get-CommitPrefix($items) {
        $paths    = @($items | ForEach-Object { $_.Path })
        $statuses = @($items | ForEach-Object { $_.Status } | Sort-Object -Unique)

        $allMd = ($paths | Where-Object {
            $_ -notmatch '\.(md|markdown|txt|rst)$' -and $_ -notmatch '(^|/)README(\.|$)'
        }).Count -eq 0

        $allCi = ($paths | Where-Object {
            $_ -notmatch '^\.github/workflows/'
        }).Count -eq 0

        $allTests = ($paths | Where-Object {
            $_ -notmatch '(^|/)(tests?|__tests__|spec)(/|$)' -and $_ -notmatch '\.(test|spec)\.[a-z0-9]+$'
        }).Count -eq 0

        $configRx = '^(\.gitignore|\.gitattributes|\.editorconfig|\.prettierrc.*|\.eslintrc.*|tsconfig.*\.json|package(-lock)?\.json|pnpm-lock\.yaml|yarn\.lock|pyproject\.toml|requirements.*\.txt|Pipfile.*|Cargo\.(toml|lock)|go\.(mod|sum)|Dockerfile.*|docker-compose.*\.ya?ml|Makefile)$|/(\.gitignore|\.gitattributes|Dockerfile.*|docker-compose.*\.ya?ml|Makefile)$'
        $allConfig = ($paths | Where-Object { $_ -notmatch $configRx }).Count -eq 0

        if ($allMd)     { return 'docs' }
        if ($allCi)     { return 'ci' }
        if ($allTests)  { return 'test' }
        if ($allConfig) { return 'chore' }
        if (($statuses -join '') -eq 'D') { return 'chore' }
        if (($statuses -join '') -eq 'A') { return 'feat' }
        return 'chore'
    }

    function Get-CommitVerb($items) {
        $statuses = @($items | ForEach-Object { $_.Status } | Sort-Object -Unique)
        if ($statuses.Count -eq 1) {
            switch ($statuses[0]) {
                'A' { return 'add' }
                'D' { return 'remove' }
                'M' { return 'update' }
                'R' { return 'rename' }
                'C' { return 'copy' }
                default { return 'update' }
            }
        }
        return 'update'
    }

    function Get-CommitScope($items) {
        $tops = @($items | ForEach-Object { ($_.Path -split '/', 2)[0] } | Sort-Object -Unique)
        if ($tops.Count -eq 1) {
            $top = $tops[0]
            if ($top -match '^\.') { return $null }            # dotfile/dir at root: skip scope
            if ($top -match '\.[a-z0-9]+$') { return $null }   # plain file at root: skip scope
            return $top
        }
        if ($tops.Count -le 3) {
            $clean = $tops | Where-Object { $_ -notmatch '^\.' }
            if ($clean.Count -ge 2) { return ($clean -join ',') }
        }
        return $null
    }

    $prefix = Get-CommitPrefix $entries
    $verb   = Get-CommitVerb   $entries
    $scope  = Get-CommitScope  $entries
    $count  = $entries.Count
    $names  = @($entries | ForEach-Object { Split-Path -Leaf $_.Path } | Sort-Object -Unique)

    # --- compose subject ----------------------------------------------------

    if ($Message) {
        $subject = $Message
    } elseif ($scope) {
        if ($count -eq 1) {
            $subject = "{0}({1}): {2} {3}" -f $prefix, $scope, $verb, $names[0]
        } elseif ($count -le 3) {
            $subject = "{0}({1}): {2} {3}" -f $prefix, $scope, $verb, ($names -join ', ')
        } else {
            $subject = "{0}({1}): {2} {3} files" -f $prefix, $scope, $verb, $count
        }
    } elseif ($count -le 3) {
        $subject = "{0}: {1} {2}" -f $prefix, $verb, ($names -join ', ')
    } else {
        $subject = "{0}: {1} {2} files" -f $prefix, $verb, $count
    }

    if ($subject.Length -gt 72) {
        $subject = $subject.Substring(0, 69) + '...'
    }

    # --- compose body -------------------------------------------------------

    $shortstat = (& git diff --cached $diffBase --shortstat 2>&1) | Select-Object -First 1
    if ($LASTEXITCODE -ne 0) { $shortstat = $null }

    $bodyLines = @()
    foreach ($e in ($entries | Select-Object -First 20)) {
        $bodyLines += ('- {0}  {1}' -f $e.Status, $e.Path)
    }
    if ($entries.Count -gt 20) {
        $bodyLines += ('- ... and {0} more' -f ($entries.Count - 20))
    }
    if ($shortstat) {
        $bodyLines += ''
        $bodyLines += $shortstat.Trim()
    }

    $body = $bodyLines -join "`n"
    $fullMessage = "$subject`n`n$body"

    Write-Host ''
    Write-Host '--- commit message ---' -ForegroundColor Cyan
    Write-Host $fullMessage
    Write-Host '----------------------' -ForegroundColor Cyan
    Write-Host ''

    # --- commit -------------------------------------------------------------

    if ($DryRun) {
        Write-Host '[dry-run] would: git commit -F <tempfile>' -ForegroundColor Yellow
    } else {
        $msgFile = New-TemporaryFile
        try {
            # UTF-8 without BOM: git treats a leading BOM as part of the subject.
            $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($msgFile.FullName, $fullMessage, $utf8NoBom)
            Invoke-Git -- commit -F $msgFile.FullName | Out-Null
            $head = (Invoke-Git -- log -1 --pretty=oneline) | Select-Object -First 1
            Write-Host ('Committed: ' + $head) -ForegroundColor Green
        } finally {
            Remove-Item -LiteralPath $msgFile.FullName -ErrorAction SilentlyContinue
        }
    }

    # --- push ---------------------------------------------------------------

    if ($NoPush) {
        Write-Host 'Skipping push (-NoPush).' -ForegroundColor Yellow
        exit 0
    }

    # `rev-parse --abbrev-ref HEAD` returns 'HEAD' for detached HEAD AND fails
    # for unborn branches (no commits yet). `symbolic-ref --short HEAD` works
    # for unborn branches and fails (non-zero) for detached HEAD - perfect.
    $branch = (& git symbolic-ref --short HEAD 2>&1) | Select-Object -First 1
    if ($LASTEXITCODE -ne 0 -or -not $branch) {
        Write-Warning 'Detached HEAD - refusing to push.'
        exit 2
    }

    $remotes = @(Invoke-Git remote)
    if ($remotes -notcontains 'origin') {
        Write-Warning "No 'origin' remote configured - committed locally, not pushing."
        exit 0
    }

    $hasUpstream = Test-GitOk rev-parse --abbrev-ref --symbolic-full-name '@{u}'

    if ($DryRun) {
        if ($hasUpstream) {
            Write-Host "[dry-run] would: git push origin $branch" -ForegroundColor Yellow
        } else {
            Write-Host "[dry-run] would: git push -u origin $branch" -ForegroundColor Yellow
        }
        exit 0
    }

    if ($hasUpstream) {
        $pushOut = Invoke-Git -- push origin $branch
    } else {
        $pushOut = Invoke-Git -- push -u origin $branch
    }
    if ($pushOut) { $pushOut | ForEach-Object { Write-Host $_ } }

    Write-Host 'Done.' -ForegroundColor Green
}
finally {
    Pop-Location
    if ($tempIndex) {
        $env:GIT_INDEX_FILE = $null
        Remove-Item -LiteralPath $tempIndex -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath ($tempIndex + '.lock') -ErrorAction SilentlyContinue
    }
}
