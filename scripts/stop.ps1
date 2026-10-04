#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'KY-JARVIS\runtime'
if (-not (Test-Path -LiteralPath $runtimeRoot)) {
    Write-Output 'Nothing to stop.'
    exit 0
}

$recordFiles = Get-ChildItem -File -Filter '*.json' -LiteralPath $runtimeRoot
foreach ($recordFile in $recordFiles) {
    $record = Get-Content -Raw -LiteralPath $recordFile.FullName | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.processId)" -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        if ($process.CommandLine -notlike "*$($record.repositoryRoot)*") {
            throw "Refusing to stop PID $($record.processId): command line is not bound to the recorded repository."
        }
        $taskkillOutput = & taskkill.exe /PID $record.processId /T /F 2>&1

        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.processId)" -ErrorAction SilentlyContinue
            if ($null -eq $process) {
                break
            }
            Start-Sleep -Milliseconds 100
        }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.processId)" -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            throw "PID $($record.processId) remained after taskkill: $($taskkillOutput -join ' ')"
        }
    }
    Remove-Item -LiteralPath $recordFile.FullName
}
Write-Output 'Stopped only recorded KY-JARVIS process trees. Data and Docker volumes were preserved.'
