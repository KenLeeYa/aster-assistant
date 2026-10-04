#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$BackupDirectory,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]*$')]
    [string]$Container = 'ky-jarvis-postgres-1',
    [string]$RecoveredFilesRoot = (Join-Path $env:LOCALAPPDATA 'KY-JARVIS\recovered'),
    [switch]$ConfirmReplaceActiveData
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$activeDatabase = 'ky_jarvis'
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'KY-JARVIS\runtime'

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

if (-not $ConfirmReplaceActiveData) {
    & (Join-Path $PSScriptRoot 'restore-test.ps1') `
        -BackupDirectory $BackupDirectory -Container $Container
    Write-Output 'Validation-only restore completed. Active data was not changed.'
    return
}

if (Test-Path -LiteralPath $runtimeRoot) {
    foreach ($recordFile in Get-ChildItem -LiteralPath $runtimeRoot -File -Filter '*.json') {
        $record = Get-Content -Raw -LiteralPath $recordFile.FullName | ConvertFrom-Json
        $process = Get-CimInstance Win32_Process `
            -Filter "ProcessId = $($record.processId)" -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            throw 'Stop all recorded KY-JARVIS writers with scripts/stop.ps1 before active restore.'
        }
    }
}

$resolvedBackup = (Resolve-Path -LiteralPath $BackupDirectory).Path
$dumpPath = Join-Path $resolvedBackup 'ky-jarvis-postgres.dump'
$manifestPath = Join-Path $resolvedBackup 'manifest.json'
if (-not (Test-Path -LiteralPath $dumpPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw 'Backup dump or manifest is missing.'
}
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.database -ne $activeDatabase -or
    $manifest.format -ne 'PostgreSQL custom archive') {
    throw 'Backup manifest does not target the exact KY-JARVIS database contract.'
}
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dumpPath).Hash
if ($actualHash -ne $manifest.sha256) {
    throw 'Backup checksum mismatch.'
}

# A disposable rehearsal must pass immediately before the active swap.
& (Join-Path $PSScriptRoot 'restore-test.ps1') `
    -BackupDirectory $resolvedBackup -Container $Container

# Preserve a fresh logical image of the current database. If this fails, the
# replacement remains blocked instead of making a partially recoverable change.
& (Join-Path $PSScriptRoot 'backup.ps1') -Container $Container

$suffix = Get-Date -Format 'yyyyMMddHHmmss'
$stagedDatabase = "ky_jarvis_restore_$suffix"
$previousDatabase = "ky_jarvis_pre_restore_$suffix"
$containerDump = "/tmp/ky-jarvis-active-restore-$suffix.dump"
if ($stagedDatabase -notmatch '^ky_jarvis_restore_\d{14}$' -or
    $previousDatabase -notmatch '^ky_jarvis_pre_restore_\d{14}$') {
    throw 'Unsafe generated restore database name.'
}

# Non-database payloads are recovered side by side. Repository files and the
# active artifacts directory are never overwritten automatically.
if ($null -ne $manifest.PSObject.Properties['files']) {
    $payloadEntries = @($manifest.files | Where-Object {
        $_.path -ne 'ky-jarvis-postgres.dump'
    })
    if ($payloadEntries.Count -gt 0) {
        $repositoryRoot = Split-Path -Parent $PSScriptRoot
        $resolvedRecoveryRoot = [IO.Path]::GetFullPath($RecoveredFilesRoot).TrimEnd('\')
        $resolvedRepositoryRoot = [IO.Path]::GetFullPath($repositoryRoot).TrimEnd('\')
        if ($resolvedRecoveryRoot -eq $resolvedRepositoryRoot -or
            $resolvedRecoveryRoot.StartsWith(
                $resolvedRepositoryRoot + '\',
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw 'RecoveredFilesRoot must remain outside the repository.'
        }
        $recoveryDirectory = Join-Path $RecoveredFilesRoot $suffix
        if (Test-Path -LiteralPath $recoveryDirectory) {
            throw 'Generated recovery directory already exists.'
        }
        New-Item -ItemType Directory -Path $recoveryDirectory | Out-Null
        $backupPrefix = $resolvedBackup.TrimEnd('\') + '\'
        foreach ($entry in $payloadEntries) {
            $relativePath = [string]$entry.path
            if ([IO.Path]::IsPathRooted($relativePath) -or
                ($relativePath -split '[\\/]') -contains '..') {
                throw 'Backup manifest contains an unsafe relative path.'
            }
            $sourcePath = [IO.Path]::GetFullPath((
                Join-Path $resolvedBackup $relativePath.Replace('/', '\')
            ))
            if (-not $sourcePath.StartsWith(
                $backupPrefix,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                throw 'Backup manifest path escapes the backup directory.'
            }
            Assert-NoReparseComponent -CandidatePath $sourcePath -RootPath $resolvedBackup
            $destinationPath = Join-Path $recoveryDirectory $relativePath.Replace('/', '\')
            New-Item -ItemType Directory -Path (Split-Path -Parent $destinationPath) `
                -Force | Out-Null
            Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
        }
        Write-Output "Configuration, skills, and artifacts recovered side by side: $recoveryDirectory"
    }
}

$stagedExists = $false
$activeRenamed = $false
try {
    & docker cp $dumpPath "${Container}:${containerDump}"
    if ($LASTEXITCODE -ne 0) { throw 'docker cp failed.' }
    & docker exec $Container createdb -U ky_jarvis $stagedDatabase
    if ($LASTEXITCODE -ne 0) { throw 'staged database creation failed.' }
    $stagedExists = $true
    & docker exec $Container pg_restore -U ky_jarvis -d $stagedDatabase `
        --no-owner --no-privileges --exit-on-error $containerDump
    if ($LASTEXITCODE -ne 0) { throw 'staged restore failed.' }
    $tableCount = & docker exec $Container psql -U ky_jarvis -d $stagedDatabase `
        -Atc "select count(*) from information_schema.tables where table_schema='public';"
    if ($LASTEXITCODE -ne 0 -or [int]$tableCount -lt 58) {
        throw "restored table count too low: $tableCount"
    }

    $connectionCount = & docker exec $Container psql -U ky_jarvis -d postgres `
        -Atc "select count(*) from pg_stat_activity where datname='$activeDatabase' and pid <> pg_backend_pid();"
    if ($LASTEXITCODE -ne 0 -or [int]$connectionCount -ne 0) {
        throw 'Active database still has clients. No connection was terminated automatically.'
    }

    & docker exec $Container psql -U ky_jarvis -d postgres -v ON_ERROR_STOP=1 `
        -c "alter database $activeDatabase rename to $previousDatabase;"
    if ($LASTEXITCODE -ne 0) { throw 'Unable to preserve the previous active database.' }
    $activeRenamed = $true
    & docker exec $Container psql -U ky_jarvis -d postgres -v ON_ERROR_STOP=1 `
        -c "alter database $stagedDatabase rename to $activeDatabase;"
    if ($LASTEXITCODE -ne 0) {
        & docker exec $Container psql -U ky_jarvis -d postgres -v ON_ERROR_STOP=1 `
            -c "alter database $previousDatabase rename to $activeDatabase;" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $activeRenamed = $false
            throw 'Unable to activate staged restore; the previous database rename was rolled back.'
        }
        throw "Unable to activate or roll back automatically. Previous data remains in $previousDatabase; staged data remains in $stagedDatabase."
    }
    $stagedExists = $false
    Write-Output "Active restore PASS: $tableCount public tables. Previous database retained as $previousDatabase."
}
finally {
    if ($stagedExists -and -not $activeRenamed) {
        & docker exec $Container dropdb -U ky_jarvis --if-exists $stagedDatabase 2>$null
    }
    & docker exec $Container rm -f -- $containerDump 2>$null
}
