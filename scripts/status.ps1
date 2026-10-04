#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'KY-JARVIS\runtime'
if (-not (Test-Path -LiteralPath $runtimeRoot)) {
    Write-Output 'No KY-JARVIS runtime directory exists.'
    exit 0
}

$records = Get-ChildItem -File -Filter '*.json' -LiteralPath $runtimeRoot -ErrorAction SilentlyContinue
foreach ($recordFile in $records) {
    $record = Get-Content -Raw -LiteralPath $recordFile.FullName | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.processId)" -ErrorAction SilentlyContinue
    [pscustomobject]@{
        Service = $record.label
        ProcessId = $record.processId
        Running = $null -ne $process
        StartedAt = $record.startedAt
    }
}
