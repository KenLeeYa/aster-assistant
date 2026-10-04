#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipWeb,
    [switch]$SkipWebE2E,
    [switch]$SkipAndroid
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$failures = @()
$childPowerShell = Get-Command pwsh -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $childPowerShell) {
    $childPowerShell = Get-Command powershell.exe -ErrorAction Stop | Select-Object -First 1
}
$childPowerShellPath = $childPowerShell.Source

function Invoke-Check {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [scriptblock]$Command
    )
    Write-Output "--- $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) { $script:failures += $Name }
}

Push-Location $repositoryRoot
try {
    Invoke-Check -Name 'ruff format' -Command { & uv run ruff format --check . }
    Invoke-Check -Name 'ruff' -Command { & uv run ruff check . }
    Invoke-Check -Name 'mypy' -Command { & uv run mypy }
    Invoke-Check -Name 'pytest' -Command { & uv run pytest }

    if (-not $SkipWeb) {
        Invoke-Check -Name 'web lint' -Command { & corepack pnpm@11.24.0 --dir apps/web lint }
        Invoke-Check -Name 'web typecheck' -Command { & corepack pnpm@11.24.0 --dir apps/web typecheck }
        Invoke-Check -Name 'web build' -Command { & corepack pnpm@11.24.0 --dir apps/web build }
        if (-not $SkipWebE2E) {
            $occupiedE2ePorts = @(
                foreach ($portNumber in @(3100, 8765)) {
                    if (Get-NetTCPConnection -State Listen -LocalPort $portNumber `
                        -ErrorAction SilentlyContinue) {
                        $portNumber
                    }
                }
            )
            if ($occupiedE2ePorts.Count -gt 0) {
                Write-Output (
                    '--- web e2e BLOCKED: isolated test port(s) already in use: ' +
                    ($occupiedE2ePorts -join ', ')
                )
                $failures += 'web e2e (isolated ports unavailable)'
            }
            else {
                Invoke-Check -Name 'web e2e' -Command {
                    & corepack pnpm@11.24.0 --dir apps/web test:e2e
                }
            }
        }
    }
    if (-not $SkipAndroid) {
        Invoke-Check -Name 'android unit/lint/build' -Command {
            & $childPowerShellPath -NoProfile -File `
                .\scripts\android-build.ps1 -Configuration Debug
        }
    }
}
finally {
    Pop-Location
}

if ($failures.Count -gt 0) {
    Write-Error "Checks failed: $($failures -join ', ')"
    exit 1
}
Write-Output 'All selected checks passed.'
