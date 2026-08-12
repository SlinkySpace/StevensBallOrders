<#
.SYNOPSIS
    Sets up the weekly catalog refresh: token scope, Storm login session,
    repository secrets, and the push.

.DESCRIPTION
    Run this from the project folder:

        cd C:\Users\jorda\OneDrive\Desktop\bowling_order_app
        .\scripts\setup-github-actions.ps1

    It is safe to re-run. Each step checks whether it is already done and skips
    if so. Two steps are interactive and cannot be automated: granting the
    workflow scope (opens a browser) and logging in to stormbowling.com.

    If PowerShell refuses to run the script, allow local scripts for this
    session only:

        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#>

[CmdletBinding()]
param(
    [switch]$SkipPush
)

$ErrorActionPreference = 'Stop'
$repo = 'SlinkySpace/StevensBallOrders'

function Write-Step($n, $text) { Write-Host "`n[$n] $text" -ForegroundColor Cyan }
function Write-Ok($text)       { Write-Host "    OK  $text" -ForegroundColor Green }
function Write-Warn2($text)    { Write-Host "    !   $text" -ForegroundColor Yellow }

function Invoke-Native {
    <#
        Runs a command line and returns its combined output as plain strings,
        with the exit code in $script:LastNativeExit.

        The redirection happens inside cmd rather than PowerShell on purpose.
        In PowerShell 5.1, "somecommand 2>&1" wraps every stderr line in an
        ErrorRecord, and with $ErrorActionPreference = 'Stop' that becomes a
        terminating NativeCommandError - so a command merely *mentioning*
        something on stderr kills the script. Letting cmd merge the streams
        avoids that entirely.
    #>
    param([string]$CommandLine)
    $output = cmd /c "$CommandLine 2>&1"
    $script:LastNativeExit = $LASTEXITCODE
    return @($output)
}

# Always operate from the project root, whatever directory the user invoked from.
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
Write-Host "Working in $projectRoot"

# --- 0. Prerequisites -------------------------------------------------------
Write-Step 0 'Checking prerequisites'

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "    GitHub CLI not found. Install it with:  winget install GitHub.cli" -ForegroundColor Red
    Write-Host "    Then close and reopen PowerShell and run this script again."
    exit 1
}
Write-Ok 'gh is installed'

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host '    python not found on PATH.' -ForegroundColor Red
    exit 1
}
Write-Ok 'python is on PATH'

# --- 1. Signed in? ----------------------------------------------------------
Write-Step 1 'Checking you are signed in to GitHub'

$status = Invoke-Native 'gh auth status'
if ($script:LastNativeExit -ne 0) {
    Write-Warn2 'gh is not signed in on this shell.'
    $status | ForEach-Object { Write-Host "        $_" }
    Write-Host ''
    Write-Host '        A browser will open so you can sign in.'
    Read-Host  '        Press Enter to run: gh auth login'

    gh auth login --hostname github.com --git-protocol https --web --scopes workflow
    if ($LASTEXITCODE -ne 0) {
        Write-Host '    Sign-in failed or was cancelled.' -ForegroundColor Red
        exit 1
    }

    $status = Invoke-Native 'gh auth status'
    if ($script:LastNativeExit -ne 0) {
        Write-Host '    Still not signed in. Try "gh auth login" on its own first.' -ForegroundColor Red
        exit 1
    }
}
$account = ($status | Select-String 'Logged in to' | Select-Object -First 1)
Write-Ok ($(if ($account) { $account.ToString().Trim() } else { 'signed in' }))

# --- 2. Workflow scope ------------------------------------------------------
Write-Step 2 'Checking the token can push workflow files'

$scopeLine = $status | Select-String 'Token scopes' | Select-Object -First 1
$scopes = if ($scopeLine) { $scopeLine.ToString() } else { '' }

if ($scopes -match 'workflow') {
    Write-Ok 'token already has workflow scope'
}
else {
    Write-Warn2 'token is missing the workflow scope, which GitHub requires to'
    Write-Host  '        create .github/workflows files.'
    if ($scopes) { Write-Host "        current: $($scopes.Trim())" }
    Write-Host  '        A browser will open. Approve the request, then come back here.'
    Write-Host  ''
    Read-Host  '        Press Enter to continue'

    gh auth refresh -h github.com -s workflow
    if ($LASTEXITCODE -ne 0) {
        Write-Host '    Scope refresh failed or was cancelled.' -ForegroundColor Red
        Write-Host '    You can also run it yourself:' -ForegroundColor Red
        Write-Host '        gh auth refresh -h github.com -s workflow' -ForegroundColor Red
        exit 1
    }

    $recheck = Invoke-Native 'gh auth status'
    $line = $recheck | Select-String 'Token scopes' | Select-Object -First 1
    if ($line -and $line.ToString() -notmatch 'workflow') {
        Write-Host '    Scope still missing. Close and reopen PowerShell, then re-run.' -ForegroundColor Red
        exit 1
    }
    Write-Ok 'workflow scope granted'
}

# --- 3. Storm login session -------------------------------------------------
Write-Step 3 'Checking for a saved stormbowling.com session'

if (Test-Path 'storm_auth_state.json') {
    $size = (Get-Item 'storm_auth_state.json').Length
    Write-Ok "storm_auth_state.json exists ($size bytes)"
    Write-Warn2 'if the scrape later fails as "logged out", delete this file and re-run'
}
else {
    Write-Warn2 'no saved session. A browser window will open.'
    Write-Host  '        Log in to stormbowling.com, then return here and press Enter'
    Write-Host  '        in THAT window (the scraper prompts you).'
    Write-Host  ''
    Read-Host  '        Press Enter to launch the browser'

    # PowerShell has no inline VAR=value prefix; set it on the environment.
    $env:SCRAPER_SETUP_LOGIN = 'true'
    try {
        python storm_scraper.py
    }
    finally {
        Remove-Item Env:\SCRAPER_SETUP_LOGIN -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path 'storm_auth_state.json')) {
        Write-Host '    storm_auth_state.json was not created. Did the login finish?' -ForegroundColor Red
        exit 1
    }
    Write-Ok 'session saved'
}

# --- 4. Repository secrets --------------------------------------------------
Write-Step 4 'Setting the Actions secrets'

$existing = @(Invoke-Native "gh secret list -R $repo --json name --jq "".[].name""")
if ($script:LastNativeExit -ne 0) {
    Write-Warn2 'could not list existing secrets; will set both regardless'
    $existing = @()
}

if ($existing -contains 'DATABASE_URL') {
    Write-Ok 'DATABASE_URL already set (re-run with it deleted to replace)'
}
else {
    Write-Host '    Paste your Neon connection string. It is sent straight to GitHub'
    Write-Host '    and not echoed or stored locally.'
    $dbUrl = Read-Host '    DATABASE_URL'
    if ([string]::IsNullOrWhiteSpace($dbUrl)) {
        Write-Host '    Nothing entered, skipping.' -ForegroundColor Red
        exit 1
    }
    $dbUrl | gh secret set DATABASE_URL -R $repo
    if ($LASTEXITCODE -ne 0) { Write-Host '    Failed.' -ForegroundColor Red; exit 1 }
    Write-Ok 'DATABASE_URL set'
}

# PowerShell has no "<" input redirection, so pipe the file contents instead.
Get-Content 'storm_auth_state.json' -Raw | gh secret set STORM_AUTH_STATE -R $repo
if ($LASTEXITCODE -ne 0) { Write-Host '    Failed to set STORM_AUTH_STATE.' -ForegroundColor Red; exit 1 }
Write-Ok 'STORM_AUTH_STATE set'

Write-Host ''
Write-Host '    Secrets now on the repo:'
gh secret list -R $repo

# --- 4. Push ----------------------------------------------------------------
if ($SkipPush) {
    Write-Step 5 'Skipping push (-SkipPush given)'
}
else {
    Write-Step 5 'Pushing the workflow'
    git push origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Host '    Push failed. If it still mentions workflow scope, close and' -ForegroundColor Red
        Write-Host '    reopen PowerShell so gh picks up the new token, then re-run.' -ForegroundColor Red
        exit 1
    }
    Write-Ok 'pushed'
}

Write-Host "`nDone." -ForegroundColor Green
Write-Host 'Next: open the repo Actions tab, choose "Refresh catalog", and run it'
Write-Host 'manually with "Dry run" ticked. That exercises the scrape and the'
Write-Host 'safety guards without writing anything to the database.'
