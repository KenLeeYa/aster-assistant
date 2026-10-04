#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$BackupRoot = (Join-Path $env:LOCALAPPDATA 'KY-JARVIS\backups'),
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]*$')]
    [string]$Container = 'ky-jarvis-postgres-1',
    [string]$ArtifactsRoot = (Join-Path $env:LOCALAPPDATA 'KY-JARVIS\artifacts'),
    [ValidateRange(0, 3650)]
    [int]$RetentionDays = 0,
    [switch]$ConfirmRetentionPrune
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ($ConfirmRetentionPrune -and $RetentionDays -eq 0) {
    throw '-ConfirmRetentionPrune requires a positive -RetentionDays value.'
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDirectory = Join-Path $BackupRoot $stamp
$dumpPath = Join-Path $backupDirectory 'ky-jarvis-postgres.dump'
$containerDump = "/tmp/ky-jarvis-$stamp.dump"
$resolvedBackupRoot = [IO.Path]::GetFullPath($BackupRoot).TrimEnd('\')
$resolvedRepositoryRoot = [IO.Path]::GetFullPath($repositoryRoot).TrimEnd('\')
if ($resolvedBackupRoot.Equals(
    [IO.Path]::GetPathRoot($resolvedBackupRoot).TrimEnd('\'),
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw 'BackupRoot cannot be a filesystem root.'
}
if ($resolvedBackupRoot -eq $resolvedRepositoryRoot -or
    $resolvedBackupRoot.StartsWith(
        $resolvedRepositoryRoot + '\',
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'BackupRoot must remain outside the repository.'
}
if (Test-Path -LiteralPath $backupDirectory) {
    throw 'Timestamped backup directory already exists; retry after the current second.'
}
New-Item -ItemType Directory -Path $backupDirectory | Out-Null

function Copy-BackupTree {
    param(
        [Parameter(Mandatory)] [string]$SourceRoot,
        [Parameter(Mandatory)] [string]$DestinationRoot
    )

    if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
        return 0
    }
    $sourceItem = Get-Item -LiteralPath $SourceRoot -Force
    if (($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Refusing to follow a reparse-point backup root.'
    }
    $resolvedSource = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd('\')
    if ($resolvedSource -eq [IO.Path]::GetPathRoot($resolvedSource).TrimEnd('\')) {
        throw 'Refusing to recursively back up a filesystem root.'
    }
    $copied = 0
    foreach ($file in Get-ChildItem -LiteralPath $resolvedSource -File -Recurse -Force) {
        if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            continue
        }
        $directory = $file.Directory
        $hasReparseParent = $false
        while ($null -ne $directory -and
            -not $directory.FullName.Equals(
                $resolvedSource,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            if (($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                $hasReparseParent = $true
                break
            }
            $directory = $directory.Parent
        }
        if ($hasReparseParent -or $null -eq $directory) {
            continue
        }
        $relativePath = $file.FullName.Substring($resolvedSource.Length).TrimStart('\')
        if ($relativePath -match '(?i)(^|[\\/])(?:\.env(?:\.|$)|[^\\/]*(?:secret|token|password|credential|private[-_.]?key|keystore)[^\\/]*)$') {
            continue
        }
        $destination = Join-Path $DestinationRoot $relativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination
        $copied++
    }
    return $copied
}

try {
    & docker exec $Container pg_dump -U ky_jarvis -d ky_jarvis --format=custom --no-owner --no-privileges --file=$containerDump
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed.' }
    & docker cp "${Container}:${containerDump}" $dumpPath
    if ($LASTEXITCODE -ne 0) { throw 'docker cp failed.' }
}
finally {
    & docker exec $Container rm -f -- $containerDump 2>$null
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dumpPath).Hash
$metadataRoot = Join-Path $backupDirectory 'metadata'
$configurationRoot = Join-Path $metadataRoot 'config'
$configurationCount = 0
$configurationFiles = @(
    Get-ChildItem -LiteralPath (Join-Path $repositoryRoot 'config') -File |
        Where-Object { $_.Name -like '*.example.yaml' -or $_.Name -eq 'resource_profiles.yaml' }
)
foreach ($configurationFile in $configurationFiles) {
    New-Item -ItemType Directory -Path $configurationRoot -Force | Out-Null
    Copy-Item -LiteralPath $configurationFile.FullName -Destination (
        Join-Path $configurationRoot $configurationFile.Name
    )
    $configurationCount++
}
$skillCount = Copy-BackupTree -SourceRoot (Join-Path $repositoryRoot 'skills') `
    -DestinationRoot (Join-Path $backupDirectory 'skills')
$artifactCount = Copy-BackupTree -SourceRoot $ArtifactsRoot `
    -DestinationRoot (Join-Path $backupDirectory 'artifacts')

$backupFiles = @(
    Get-ChildItem -LiteralPath $backupDirectory -File -Recurse |
        Sort-Object FullName |
        ForEach-Object {
            [ordered]@{
                path = $_.FullName.Substring($backupDirectory.Length).TrimStart('\').Replace('\', '/')
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
                bytes = $_.Length
            }
        }
)
$manifest = [ordered]@{
    schema_version = 2
    created_at = (Get-Date).ToUniversalTime().ToString('o')
    format = 'PostgreSQL custom archive'
    database = 'ky_jarvis'
    sha256 = $hash
    contains_credentials = $false
    included = [ordered]@{
        configuration_files = $configurationCount
        skill_files = $skillCount
        artifact_files = $artifactCount
    }
    excluded_secret_sources = @(
        '%LOCALAPPDATA%/KY-JARVIS/database'
        '%LOCALAPPDATA%/KY-JARVIS/runtime/operator'
        'environment variables and .env files'
    )
    retention = [ordered]@{
        days = $RetentionDays
        prune_confirmed = [bool]$ConfirmRetentionPrune
    }
    files = $backupFiles
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (
    Join-Path $backupDirectory 'manifest.json'
) -Encoding UTF8
Write-Output "Backup created: $backupDirectory"
if ($RetentionDays -gt 0) {
    $pruneParameters = @{
        BackupRoot = $resolvedBackupRoot
        RetentionDays = $RetentionDays
    }
    if ($ConfirmRetentionPrune) {
        $pruneParameters.ConfirmPrune = $true
    }
    & (Join-Path $PSScriptRoot 'prune-backups.ps1') @pruneParameters
}
