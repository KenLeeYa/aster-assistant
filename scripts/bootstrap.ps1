#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipWeb
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repositoryRoot
try {
    & uv sync --all-extras --group dev
    if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }

    if (-not $SkipWeb) {
        & corepack pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'pnpm install failed' }
    }

    Write-Output 'Bootstrap complete. No external connector, model, or database secret was created.'
}
finally {
    Pop-Location
}
