#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('economy', 'balanced', 'performance')]
    [string]$ResourceProfile = 'balanced',
    [switch]$Confirm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Confirm) {
    throw 'Launch at login is opt-in. Re-run with -Confirm after reviewing the shortcut target.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $PSScriptRoot 'start.ps1'
$startupDirectory = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDirectory 'KY-JARVIS.lnk'
$powershellCommand = Get-Command powershell.exe -ErrorAction Stop | Select-Object -First 1
$powershellPath = $powershellCommand.Source
$ownerMarker = 'KY-JARVIS current-user startup'
if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
    throw 'KY-JARVIS start script is missing.'
}
if (-not (Test-Path -LiteralPath $powershellPath -PathType Leaf)) {
    throw 'Windows PowerShell executable is missing.'
}

$shell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $shortcutPath) {
    $existing = $shell.CreateShortcut($shortcutPath)
    if ($existing.Description -ne $ownerMarker) {
        throw 'Refusing to replace a Startup shortcut not owned by KY-JARVIS.'
    }
}

$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -File `"$startScript`" -ResourceProfile $ResourceProfile -WithWeb"
$shortcut.WorkingDirectory = $repositoryRoot
$shortcut.Description = $ownerMarker
$shortcut.Save()
Write-Output "Current-user launch at login registered: $shortcutPath"
