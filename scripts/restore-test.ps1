#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$BackupDirectory,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]*$')]
    [string]$Container = 'ky-jarvis-postgres-1'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$resolvedBackup = (Resolve-Path -LiteralPath $BackupDirectory).Path

function Assert-NoReparseComponent {
    param(
        [Parameter(Mandatory)] [string]$CandidatePath,
        [Parameter(Mandatory)] [string]$RootPath
    )

    $item = Get-Item -LiteralPath $CandidatePath -Force
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Backup payload contains a reparse point.'
        }
        if ($item.FullName.Equals($RootPath, [StringComparison]::OrdinalIgnoreCase)) {
            return
        }
        $item = if ($item -is [IO.DirectoryInfo]) { $item.Parent } else { $item.Directory }
    }
    throw 'Backup payload path is not rooted in the selected backup.'
}

Assert-NoReparseComponent -CandidatePath $resolvedBackup -RootPath $resolvedBackup
$dumpPath = Join-Path $resolvedBackup 'ky-jarvis-postgres.dump'
$manifestPath = Join-Path $resolvedBackup 'manifest.json'
if (-not (Test-Path -LiteralPath $dumpPath) -or -not (Test-Path -LiteralPath $manifestPath)) {
    throw 'Backup dump or manifest is missing.'
}
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dumpPath).Hash
if ($actualHash -ne $manifest.sha256) { throw 'Backup checksum mismatch.' }
if ($null -ne $manifest.PSObject.Properties['files']) {
    $backupPrefix = $resolvedBackup.TrimEnd('\') + '\'
    foreach ($entry in $manifest.files) {
        $relativePath = [string]$entry.path
        if ([IO.Path]::IsPathRooted($relativePath) -or
            ($relativePath -split '[\\/]') -contains '..') {
            throw 'Backup manifest contains an unsafe relative path.'
        }
        $candidatePath = [IO.Path]::GetFullPath((
            Join-Path $resolvedBackup $relativePath.Replace('/', '\')
        ))
        if (-not $candidatePath.StartsWith(
            $backupPrefix,
            [StringComparison]::OrdinalIgnoreCase
        ) -or -not (Test-Path -LiteralPath $candidatePath -PathType Leaf)) {
            throw 'Backup manifest references a missing or out-of-root file.'
        }
        Assert-NoReparseComponent -CandidatePath $candidatePath -RootPath $resolvedBackup
        $entryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $candidatePath).Hash
        if ($entryHash -ne $entry.sha256) {
            throw "Backup payload checksum mismatch: $relativePath"
        }
    }
}

$suffix = Get-Date -Format 'yyyyMMddHHmmss'
$restoreDatabase = "ky_jarvis_restore_$suffix"
$containerDump = "/tmp/ky-jarvis-restore-$suffix.dump"
if ($restoreDatabase -notmatch '^ky_jarvis_restore_\d{14}$') { throw 'Unsafe restore database name.' }

$restoreDatabaseCreated = $false
try {
    & docker cp $dumpPath "${Container}:${containerDump}"
    if ($LASTEXITCODE -ne 0) { throw 'docker cp failed.' }
    & docker exec $Container createdb -U ky_jarvis $restoreDatabase
    if ($LASTEXITCODE -ne 0) { throw 'isolated database creation failed.' }
    $restoreDatabaseCreated = $true
    & docker exec $Container pg_restore -U ky_jarvis -d $restoreDatabase `
        --no-owner --no-privileges --exit-on-error $containerDump
    if ($LASTEXITCODE -ne 0) { throw 'isolated restore failed.' }
    $tableCount = & docker exec $Container psql -U ky_jarvis -d $restoreDatabase -Atc "select count(*) from information_schema.tables where table_schema='public';"
    if ([int]$tableCount -lt 58) { throw "restored table count too low: $tableCount" }
    Write-Output "Isolated restore PASS: $tableCount public tables"
}
finally {
    if ($restoreDatabaseCreated) {
        & docker exec $Container dropdb -U ky_jarvis --if-exists $restoreDatabase 2>$null
    }
    & docker exec $Container rm -f -- $containerDump 2>$null
}
