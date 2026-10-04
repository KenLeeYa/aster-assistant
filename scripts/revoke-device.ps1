#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidatePattern('^[0-9a-fA-F-]{36}$')] [string]$DeviceId,
    [switch]$Confirm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Confirm) {
    throw "Refusing device revocation for $DeviceId without -Confirm."
}
throw 'BLOCKED: scripted device revocation requires the pending OS-protected desktop operator session. Use the visible loopback Command Center for Pilot revocation; no token or secret was read.'
