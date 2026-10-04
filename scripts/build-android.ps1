#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('debug', 'release')] [string]$Variant = 'debug',
    [switch]$Bundle
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$configuration = if ($Variant -eq 'debug') { 'Debug' } else { 'Release' }
& (Join-Path $PSScriptRoot 'android-build.ps1') -Configuration $configuration -Bundle:$Bundle
exit $LASTEXITCODE
