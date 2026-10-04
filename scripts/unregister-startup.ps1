#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Confirm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Confirm) {
    throw 'Removing launch at login is explicit. Re-run with -Confirm.'
}

$startupDirectory = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDirectory 'KY-JARVIS.lnk'
$ownerMarker = 'KY-JARVIS current-user startup'
if (-not (Test-Path -LiteralPath $shortcutPath)) {
    Write-Output 'KY-JARVIS launch at login is not registered.'
    return
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ($shortcut.Description -ne $ownerMarker) {
    throw 'Refusing to remove a Startup shortcut not owned by KY-JARVIS.'
}
Remove-Item -LiteralPath $shortcutPath
Write-Output 'KY-JARVIS current-user launch at login was removed.'
