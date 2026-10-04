#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidatePattern('^(?:[01]\d|2[0-3]):[0-5]\d$')]
    [string]$At = '02:00',
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 30,
    [switch]$Confirm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Confirm) {
    throw 'Daily backup scheduling is opt-in. Re-run with -Confirm after reviewing the task.'
}
if ($env:OS -ne 'Windows_NT') {
    throw 'Daily backup registration is supported only on Windows.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$backupScript = Join-Path $PSScriptRoot 'backup.ps1'
$taskName = 'KY-JARVIS Daily Backup'
$ownerMarker = "KY-JARVIS current-user daily backup; repository=$repositoryRoot"
if (-not (Test-Path -LiteralPath $backupScript -PathType Leaf)) {
    throw 'KY-JARVIS backup script is missing.'
}

$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask -and $existingTask.Description -ne $ownerMarker) {
    throw 'Refusing to replace a scheduled task not owned by this KY-JARVIS repository.'
}

$powershellCommand = Get-Command powershell.exe -ErrorAction Stop | Select-Object -First 1
$powershellPath = $powershellCommand.Source
$taskArguments = (
    "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File `"$backupScript`" " +
    "-RetentionDays $RetentionDays -ConfirmRetentionPrune"
)
$triggerTime = [DateTime]::ParseExact(
    $At,
    'HH:mm',
    [Globalization.CultureInfo]::InvariantCulture
)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $powershellPath `
    -Argument $taskArguments -WorkingDirectory $repositoryRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime
$principal = New-ScheduledTaskPrincipal -UserId $identity `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Description $ownerMarker -Force | Out-Null
Write-Output (
    "Current-user daily backup registered at $At with $RetentionDays-day retention: $taskName"
)
