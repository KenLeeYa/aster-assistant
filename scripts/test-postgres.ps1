#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'KY-JARVIS\database'
$passwordFile = Join-Path $runtimeRoot 'postgres-password.txt'

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $passwordFile)) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $password = [Convert]::ToHexString($bytes).ToLowerInvariant()
    [System.IO.File]::WriteAllText($passwordFile, $password, [System.Text.UTF8Encoding]::new($false))
}

$password = [System.IO.File]::ReadAllText($passwordFile).Trim()
$env:KY_JARVIS_DB_PASSWORD_FILE = $passwordFile
# The PostgreSQL entrypoint rejects configurations that set both password inputs.
# Force this process to use only the Compose file-secret contract.
Remove-Item Env:KY_JARVIS_DB_PASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:KY_JARVIS_DB_PASSWORD_FILE_CONTAINER -ErrorAction SilentlyContinue
$env:KY_JARVIS_DATABASE_URL = "postgresql+psycopg://ky_jarvis:$password@127.0.0.1:55433/ky_jarvis"

Push-Location $repositoryRoot
try {
    & docker compose --project-name ky-jarvis --file infra/compose.yaml --profile core up -d --wait postgres
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL container did not become healthy' }
    & uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Alembic upgrade failed' }
    & uv run python scripts/verify_postgres.py
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL schema inspection failed' }
    & uv run pytest services/core-api/tests/test_agent_postgres.py -q
    if ($LASTEXITCODE -ne 0) { throw 'LangGraph PostgreSQL checkpoint test failed' }
    Write-Output 'PostgreSQL/pgvector profile is healthy and migrated. Secret value was not printed.'
}
finally {
    Pop-Location
}
