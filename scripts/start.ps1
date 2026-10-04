#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('economy', 'balanced', 'performance')]
    [string]$ResourceProfile = 'balanced',
    [switch]$WithWeb,
    [switch]$SkipDatabase
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'KY-JARVIS\runtime'
$previousDatabaseUrl = [Environment]::GetEnvironmentVariable(
    'KY_JARVIS_DATABASE_URL',
    [EnvironmentVariableTarget]::Process
)
$previousOperatorSecret = [Environment]::GetEnvironmentVariable(
    'KY_JARVIS_OPERATOR_BOOTSTRAP_SECRET',
    [EnvironmentVariableTarget]::Process
)
$previousOperatorCredentialPath = [Environment]::GetEnvironmentVariable(
    'KY_JARVIS_OPERATOR_CREDENTIAL_PATH',
    [EnvironmentVariableTarget]::Process
)
try {
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    $env:KY_JARVIS_RESOURCE_PROFILE = $ResourceProfile

$operatorRoot = Join-Path $runtimeRoot 'operator'
New-Item -ItemType Directory -Path $operatorRoot -Force | Out-Null
$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $operatorRoot /inheritance:r /grant:r `
    "${currentIdentity}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' /Q | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to restrict the desktop operator runtime directory ACL.'
}

$operatorCredentialPath = Join-Path $operatorRoot 'credential.json'
$operatorEnrollmentPath = Join-Path $operatorRoot 'enrollment-secret.txt'
$env:KY_JARVIS_OPERATOR_CREDENTIAL_PATH = $operatorCredentialPath
if (Test-Path -LiteralPath $operatorCredentialPath) {
    Remove-Item Env:KY_JARVIS_OPERATOR_BOOTSTRAP_SECRET -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $operatorEnrollmentPath) {
        Remove-Item -LiteralPath $operatorEnrollmentPath -Force
    }
}
else {
    if (-not (Test-Path -LiteralPath $operatorEnrollmentPath)) {
        $secretBytes = New-Object byte[] 32
        $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $generator.GetBytes($secretBytes)
        }
        finally {
            $generator.Dispose()
        }
        [System.IO.File]::WriteAllText(
            $operatorEnrollmentPath,
            [Convert]::ToBase64String($secretBytes),
            [System.Text.Encoding]::ASCII
        )
    }
    $operatorEnrollmentSecret = [System.IO.File]::ReadAllText($operatorEnrollmentPath).Trim()
    if ($operatorEnrollmentSecret.Length -lt 32) {
        throw 'Desktop operator enrollment secret is invalid.'
    }
    $env:KY_JARVIS_OPERATOR_BOOTSTRAP_SECRET = $operatorEnrollmentSecret
}

if (-not $SkipDatabase) {
    & (Join-Path $PSScriptRoot 'test-postgres.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Database startup or migration failed' }
    $databasePasswordPath = Join-Path $env:LOCALAPPDATA 'KY-JARVIS\database\postgres-password.txt'
    $databasePassword = [System.IO.File]::ReadAllText($databasePasswordPath).Trim()
    $env:KY_JARVIS_DATABASE_URL = "postgresql+psycopg://ky_jarvis:$databasePassword@127.0.0.1:55433/ky_jarvis"
}

function Start-OwnedProcess {
    param(
        [Parameter(Mandatory)] [string]$Label,
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [string[]]$ArgumentList,
        [Parameter(Mandatory)] [string]$WorkingDirectory
    )

    $recordPath = Join-Path $runtimeRoot "$Label.json"
    if (Test-Path -LiteralPath $recordPath) {
        throw "$Label already has a runtime record. Run scripts/status.ps1 or scripts/stop.ps1 first."
    }
    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtimeRoot "$Label.stdout.log") `
        -RedirectStandardError (Join-Path $runtimeRoot "$Label.stderr.log")
    [pscustomobject]@{
        label = $Label
        processId = $process.Id
        startedAt = (Get-Date).ToUniversalTime().ToString('o')
        repositoryRoot = $repositoryRoot
    } | ConvertTo-Json | Set-Content -LiteralPath $recordPath -Encoding utf8
}

$uvPath = (Get-Command uv -ErrorAction Stop).Source
    Start-OwnedProcess -Label 'core-api' -FilePath $uvPath `
        -ArgumentList @('run', '--project', $repositoryRoot, 'uvicorn', 'ky_jarvis_core.main:app', '--host', '127.0.0.1', '--port', '8765') `
        -WorkingDirectory $repositoryRoot

    Remove-Item Env:KY_JARVIS_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:KY_JARVIS_OPERATOR_BOOTSTRAP_SECRET -ErrorAction SilentlyContinue
    Remove-Item Env:KY_JARVIS_OPERATOR_CREDENTIAL_PATH -ErrorAction SilentlyContinue

    if ($WithWeb) {
        $corepackPath = (Get-Command corepack -ErrorAction Stop).Source
        $webRoot = Join-Path $repositoryRoot 'apps\web'
        Start-OwnedProcess -Label 'web' -FilePath $corepackPath `
            -ArgumentList @('pnpm', '--dir', $webRoot, 'dev') -WorkingDirectory $repositoryRoot
    }

    Write-Output "KY-JARVIS started with profile $ResourceProfile."
}
finally {
    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:KY_JARVIS_DATABASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:KY_JARVIS_DATABASE_URL = $previousDatabaseUrl
    }
    if ($null -eq $previousOperatorSecret) {
        Remove-Item Env:KY_JARVIS_OPERATOR_BOOTSTRAP_SECRET -ErrorAction SilentlyContinue
    }
    else {
        $env:KY_JARVIS_OPERATOR_BOOTSTRAP_SECRET = $previousOperatorSecret
    }
    if ($null -eq $previousOperatorCredentialPath) {
        Remove-Item Env:KY_JARVIS_OPERATOR_CREDENTIAL_PATH -ErrorAction SilentlyContinue
    }
    else {
        $env:KY_JARVIS_OPERATOR_CREDENTIAL_PATH = $previousOperatorCredentialPath
    }
}
