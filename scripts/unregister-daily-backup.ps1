#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Confirm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Confirm) {
    throw 'Removing daily backup scheduling is explicit. Re-run with -Confirm.'
}
if ($env:OS -ne 'Windows_NT') {
    throw 'Daily backup unregistration is supported only on Windows.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$taskName = 'KY-JARVIS Daily Backup'
$ownerMarker = "KY-JARVIS current-user daily backup; repository=$repositoryRoot"
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $existingTask) {
    Write-Output 'KY-JARVIS daily backup is not registered.'
    return
}
if ($existingTask.Description -ne $ownerMarker) {
    throw 'Refusing to remove a scheduled task not owned by this KY-JARVIS repository.'
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Output 'KY-JARVIS current-user daily backup was removed.'
