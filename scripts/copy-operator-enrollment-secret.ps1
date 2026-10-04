#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$operatorRoot = Join-Path $env:LOCALAPPDATA 'KY-JARVIS\runtime\operator'
$credentialPath = Join-Path $operatorRoot 'credential.json'
$enrollmentPath = Join-Path $operatorRoot 'enrollment-secret.txt'

if (Test-Path -LiteralPath $credentialPath) {
    throw 'Windows Hello operator is already registered; no enrollment secret was copied.'
}
if (-not (Test-Path -LiteralPath $enrollmentPath)) {
    throw 'Enrollment secret is unavailable. Start KY-JARVIS with scripts/start.ps1 first.'
}

$secret = [System.IO.File]::ReadAllText($enrollmentPath).Trim()
if ($secret.Length -lt 32) {
    throw 'Enrollment secret is invalid; stop and restart KY-JARVIS to investigate.'
}
Set-Clipboard -Value $secret
$secret = $null
Write-Output 'Enrollment secret copied to the Windows clipboard. Paste it only into the loopback KY-JARVIS Command Center.'
