<#
.SYNOPSIS
    Sign in to Storm, hand the session to GitHub, and kick off a catalog refresh.

.DESCRIPTION
    The one command to run when you want the catalog updated:

        cd C:\Users\jorda\OneDrive\Desktop\bowling_order_app
        .\scripts\refresh-storm-login.ps1

    A browser opens. Log in to stormbowling.com, come back, press Enter. The
    script uploads the session to the STORM_AUTH_STATE secret and starts the
    workflow, so the scrape runs while the login is at its freshest. Nothing is
    scraped or built on your machine.

    By default it starts a dry run, which checks everything and reports what it
    would change without touching the database. Add -Apply to write for real.

        .\scripts\refresh-storm-login.ps1 -Apply       # actually update prices
        .\scripts\refresh-storm-login.ps1 -NoRun       # refresh the secret only
        .\scripts\refresh-storm-login.ps1 -Reuse       # skip the browser, reuse
                                                       # the session already saved

    Storm sessions do not last long - one cookie expires within the hour - so
    signing in immediately before a run is more reliable than relying on the
    Monday schedule to find a session still valid from days earlier.
#>

[CmdletBinding()]
param(
    [switch]$Apply,     # write to the database instead of a dry run
    [switch]$NoRun,     # update the secret but don't start the workflow
    [switch]$Reuse      # use the existing storm_auth_state.json, don't sign in again
)

$ErrorActionPreference = 'Stop'
$repo = 'SlinkySpace/StevensBallOrders'
$stateFile = 'storm_auth_state.json'

function Write-Step($n, $t) { Write-Host "`n[$n] $t" -ForegroundColor Cyan }
function Write-Ok($t)       { Write-Host "    OK  $t" -ForegroundColor Green }
function Write-Note($t)     { Write-Host "    !   $t" -ForegroundColor Yellow }

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
Write-Host "Working in $projectRoot"

foreach ($tool in 'gh', 'python') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "$tool is not on PATH." -ForegroundColor Red
        exit 1
    }
}

# --- 1. Capture the session -------------------------------------------------
Write-Step 1 'Signing in to stormbowling.com'

if ($Reuse -and (Test-Path $stateFile)) {
    Write-Note "reusing the existing $stateFile (-Reuse given)"
}
else {
    if (Test-Path $stateFile) { Remove-Item $stateFile -Force }

    Write-Host '    A browser window will open.'
    Write-Host '    1. Log in to stormbowling.com'
    Write-Host '    2. Come back to THIS window and press Enter when the prompt appears'
    Write-Host ''

    $env:SCRAPER_SETUP_LOGIN = 'true'
    try { python storm_scraper.py }
    finally { Remove-Item Env:\SCRAPER_SETUP_LOGIN -ErrorAction SilentlyContinue }

    if (-not (Test-Path $stateFile)) {
        Write-Host '    No session was saved. Did the login finish?' -ForegroundColor Red
        exit 1
    }
    Write-Ok "session captured ($((Get-Item $stateFile).Length) bytes)"
}

# Report how long this session is good for, since that decides whether the
# scheduled run can rely on it or whether you need to be here for it.
#
# A single-quoted here-string, piped to python. PowerShell has no "<" input
# redirection, so a bash heredoc here would be a parse error.
$cookieReport = @'
import datetime, json
try:
    state = json.load(open('storm_auth_state.json'))
except Exception as exc:
    raise SystemExit(f'    could not read the session file: {exc}')

now = datetime.datetime.now().timestamp()
storm = [c for c in state.get('cookies', [])
         if 'stormbowling' in c.get('domain', '') and c.get('expires', -1) > 0]
if not storm:
    print('    session cookies carry no expiry (they end when the browser closes)')
else:
    soonest = min(c['expires'] for c in storm)
    longest = max(c['expires'] for c in storm)
    mins = (soonest - now) / 60
    days = (longest - now) / 86400
    print(f'    earliest Storm cookie expires in {mins:,.0f} min; '
          f'the longest lasts {days:,.1f} days')
    if mins < 90:
        print('    -> short-lived, so run the scrape now rather than leaving it '
              'to the schedule')
'@

$cookieReport | python -

# --- 2. Upload it -----------------------------------------------------------
Write-Step 2 'Updating the STORM_AUTH_STATE secret'

# PowerShell has no "<" redirection; pipe the file contents instead.
Get-Content $stateFile -Raw | gh secret set STORM_AUTH_STATE -R $repo
if ($LASTEXITCODE -ne 0) {
    Write-Host '    Upload failed.' -ForegroundColor Red
    exit 1
}
Write-Ok 'secret updated'

# --- 3. Start the refresh ---------------------------------------------------
if ($NoRun) {
    Write-Step 3 'Not starting a run (-NoRun given)'
    Write-Host "`nDone." -ForegroundColor Green
    exit 0
}

$dryRun = (-not $Apply)
Write-Step 3 $(if ($dryRun) { 'Starting a dry run (nothing will be written)' }
               else          { 'Starting a real refresh (prices WILL be updated)' })

gh workflow run refresh-catalog.yml -R $repo --ref main -f dry_run=$($dryRun.ToString().ToLower())
if ($LASTEXITCODE -ne 0) {
    Write-Host '    Could not start the workflow.' -ForegroundColor Red
    exit 1
}

Start-Sleep -Seconds 12
$runId = gh run list -R $repo --workflow refresh-catalog.yml --limit 1 --json databaseId --jq '.[0].databaseId'
Write-Ok "run $runId started"

Write-Host ''
Write-Host 'The scrape takes roughly 40 minutes. Watch it with:'
Write-Host "    gh run watch $runId -R $repo" -ForegroundColor Cyan
Write-Host 'or open:'
Write-Host "    https://github.com/$repo/actions/runs/$runId" -ForegroundColor Cyan

if ($dryRun) {
    Write-Host ''
    Write-Host 'This was a dry run. If the report looks right, apply it with:' -ForegroundColor Yellow
    Write-Host '    .\scripts\refresh-storm-login.ps1 -Reuse -Apply' -ForegroundColor Yellow
}
