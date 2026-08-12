<#
.SYNOPSIS
    Remove duplicate and junk product rows from the hosted catalog.

.DESCRIPTION
    Run from the project folder:

        cd C:\Users\jorda\OneDrive\Desktop\bowling_order_app
        .\scripts\dedupe-products.ps1 -DryRun     # list everything, change nothing
        .\scripts\dedupe-products.ps1             # list, then ask before deleting
        .\scripts\dedupe-products.ps1 -Hide       # hide duplicates instead of deleting
        .\scripts\dedupe-products.ps1 -Local      # the local SQLite file instead

    Orders, users and balances are never touched - orders keep their own copy of
    the product details, so removing a catalog row cannot affect order history.

    DATABASE_URL is found in this order, so you should not need to paste it:
      1. $env:DATABASE_URL, if you have already set it this session
      2. .streamlit/secrets.toml, if you keep one locally
      3. a prompt, as a last resort
#>

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Hide,
    [switch]$Local
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
Write-Host "Working in $projectRoot"

# Talking to the hosted database needs psycopg, which is in requirements.txt but
# is easy not to have locally - the app runs on SQLite here unless DATABASE_URL
# is set, so nothing installs it until the first time you point at Postgres.
if (-not $Local) {
    python -c "import psycopg" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'psycopg is not installed, so this cannot reach the hosted database.' -ForegroundColor Yellow
        Write-Host 'Installing it now...' -ForegroundColor Yellow
        python -m pip install --quiet "psycopg[binary,pool]>=3.2"
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Install failed. Run this yourself, then retry:' -ForegroundColor Red
            Write-Host '    python -m pip install "psycopg[binary,pool]"' -ForegroundColor Red
            exit 1
        }
        Write-Host 'Installed.' -ForegroundColor Green
    }
}

$arguments = @('dedupe_products.py')
if ($DryRun) { $arguments += '--dry-run' }
if ($Hide)   { $arguments += '--hide' }

if ($Local) {
    $arguments += '--local'
    Write-Host 'Target: local SQLite file' -ForegroundColor Yellow
}
else {
    if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL) -and (Test-Path '.streamlit/secrets.toml')) {
        Write-Host 'Reading DATABASE_URL from .streamlit/secrets.toml'
        $env:DATABASE_URL = python -c @'
import tomllib
with open('.streamlit/secrets.toml','rb') as f:
    print(tomllib.load(f).get('DATABASE_URL',''), end='')
'@
    }

    if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
        Write-Host ''
        Write-Host 'DATABASE_URL is not set for this session.'
        Write-Host 'Copy it from Neon (Connection string) or from your Streamlit Cloud'
        Write-Host 'app under Settings -> Secrets. It is used for this run only and is'
        Write-Host 'not written anywhere.'
        $secure = Read-Host '  DATABASE_URL' -AsSecureString
        $env:DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    }

    if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
        Write-Host 'No DATABASE_URL. Aborting.' -ForegroundColor Red
        exit 1
    }

    # Show enough to confirm the right database without printing the password.
    $safe = $env:DATABASE_URL -replace '://[^@]*@', '://***@'
    Write-Host "Target: $safe" -ForegroundColor Yellow
}

Write-Host ''

# Relax the error preference around the native call. Under 'Stop', PowerShell
# 5.1 turns anything a native command writes to stderr into a terminating
# NativeCommandError - and importing streamlit outside a server prints a
# harmless "No runtime found" notice to stderr, which would abort the script
# before it ran. The exit code is what actually matters here.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try { python @arguments } finally { $ErrorActionPreference = $previousPreference }
$code = $LASTEXITCODE

if ($code -eq 0)     { Write-Host "`nFinished." -ForegroundColor Green }
elseif ($code -eq 1) { Write-Host "`nAborted, nothing changed." -ForegroundColor Yellow }
else                 { Write-Host "`nFailed (exit $code)." -ForegroundColor Red }

exit $code
