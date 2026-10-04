#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repositoryRoot
try {
    & uv run python -m ky_jarvis_core.mcp_gateway
    if ($LASTEXITCODE -ne 0) { throw 'KY-JARVIS MCP gateway exited with an error' }
}
finally {
    Pop-Location
}
