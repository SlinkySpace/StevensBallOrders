<#
.SYNOPSIS
    Deletes every order and resets balances, on the hosted database.

.DESCRIPTION
    Run from the project folder:

        cd C:\Users\jorda\OneDrive\Desktop\bowling_order_app
        .\scripts\wipe-orders.ps1              # shows what it would do, then asks
        .\scripts\wipe-orders.ps1 -DryRun      # report only, changes nothing
        .\scripts\wipe-orders.ps1 -Local       # the local SQLite file instead

    Accounts, passwords, saved carts and the product catalog are NOT touched.
    A CSV backup of the orders is written before anything is deleted.

    DATABASE_URL is read from $env:DATABASE_URL, or from .streamlit/secrets.toml
    if that exists. If neither, you are prompted.
#>

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Local,
    [switch]$KeepBalances
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
Write-Host "Working in $projectRoot"

# See dedupe-products.ps1: psycopg is in requirements.txt but nothing installs
# it locally until you first point at the hosted database.
if (-not $Local) {
    python -c "import psycopg" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing psycopg, needed to reach the hosted database...' -ForegroundColor Yellow
        python -m pip install --quiet "psycopg[binary,pool]>=3.2"
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Install failed. Run this yourself, then retry:' -ForegroundColor Red
            Write-Host '    python -m pip install "psycopg[binary,pool]"' -ForegroundColor Red
            exit 1
        }
    }
}

$arguments = @('wipe_orders.py')
if ($DryRun)       { $arguments += '--dry-run' }
if ($KeepBalances) { $arguments += '--keep-balances' }

if ($Local) {
    $arguments += '--local'
    Write-Host 'Target: local SQLite file' -ForegroundColor Yellow
}
else {
    if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
        # Try the local secrets file before asking.
        if (Test-Path '.streamlit/secrets.toml') {
            Write-Host 'Reading DATABASE_URL from .streamlit/secrets.toml'
            $env:DATABASE_URL = python -c @'
import tomllib
with open('.streamlit/secrets.toml','rb') as f:
    print(tomllib.load(f).get('DATABASE_URL',''), end='')
'@
        }
    }

    if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
        Write-Host 'DATABASE_URL is not set and no .streamlit/secrets.toml was found.'
        Write-Host 'Paste your Neon connection string (used for this run only):'
        $env:DATABASE_URL = Read-Host '  DATABASE_URL'
    }

    if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
        Write-Host 'No DATABASE_URL. Aborting.' -ForegroundColor Red
        exit 1
    }

    # Show enough to confirm the right database, without printing the password.
    $safe = $env:DATABASE_URL -replace '://[^@]*@', '://***@'
    Write-Host "Target: $safe" -ForegroundColor Yellow
}

Write-Host ''

# See dedupe-products.ps1: under $ErrorActionPreference = 'Stop', PowerShell 5.1
# escalates a native command's stderr into a terminating error, and streamlit
# prints a harmless notice there when imported outside a server.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try { python @arguments } finally { $ErrorActionPreference = $previousPreference }
$code = $LASTEXITCODE

if ($code -eq 0)      { Write-Host "`nFinished." -ForegroundColor Green }
elseif ($code -eq 1)  { Write-Host "`nAborted, nothing changed." -ForegroundColor Yellow }
else                  { Write-Host "`nFailed (exit $code)." -ForegroundColor Red }

exit $code
