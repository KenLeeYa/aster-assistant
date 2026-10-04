#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
throw 'BLOCKED: scripted device pairing requires the pending OS-protected desktop operator session. Use the visible loopback Command Center for Pilot pairing; no secret was created or printed.'
