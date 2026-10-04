#Requires -Version 5.1
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'Low')]
param(
    [string]$BackupRoot = (Join-Path $env:LOCALAPPDATA 'KY-JARVIS\backups'),
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 30,
    [switch]$ConfirmPrune
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = (Split-Path -Parent $PSScriptRoot).TrimEnd('\')
$resolvedBackupRoot = [IO.Path]::GetFullPath($BackupRoot).TrimEnd('\')
$filesystemRoot = [IO.Path]::GetPathRoot($resolvedBackupRoot).TrimEnd('\')

if ($resolvedBackupRoot.Equals($filesystemRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Refusing to prune a filesystem root.'
}
$backupPrefix = $resolvedBackupRoot + '\'
$repositoryPrefix = $repositoryRoot + '\'
if ($resolvedBackupRoot.Equals($repositoryRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $resolvedBackupRoot.StartsWith(
        $repositoryPrefix,
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    $repositoryRoot.StartsWith(
        $backupPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'BackupRoot must be outside and must not contain the repository.'
}
if (-not (Test-Path -LiteralPath $resolvedBackupRoot -PathType Container)) {
    Write-Output "Backup root does not exist; nothing to prune: $resolvedBackupRoot"
    return
}

$rootComponent = Get-Item -LiteralPath $resolvedBackupRoot -Force
while ($null -ne $rootComponent) {
    if (($rootComponent.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Refusing to prune through a reparse-point backup-root component.'
    }
    $rootComponent = $rootComponent.Parent
}

$cutoffUtc = (Get-Date).ToUniversalTime().AddDays(-$RetentionDays)
$eligible = @()
foreach ($directory in Get-ChildItem -LiteralPath $resolvedBackupRoot -Directory -Force) {
    if (($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Write-Warning "Skipped reparse-point directory: $($directory.Name)"
        continue
    }

    $parsedStamp = [DateTime]::MinValue
    $isTimestamp = [DateTime]::TryParseExact(
        $directory.Name,
        'yyyyMMdd-HHmmss',
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeLocal,
        [ref]$parsedStamp
    )
    if (-not $isTimestamp -or $parsedStamp.ToUniversalTime() -ge $cutoffUtc) {
        continue
    }

    $manifestPath = Join-Path $directory.FullName 'manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        Write-Warning "Skipped unowned directory without manifest: $($directory.Name)"
        continue
    }
    try {
        $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    }
    catch {
        Write-Warning "Skipped directory with invalid manifest: $($directory.Name)"
        continue
    }
    if ($null -eq $manifest.PSObject.Properties['schema_version'] -or
        $null -eq $manifest.PSObject.Properties['database']) {
        Write-Warning "Skipped directory with an unrecognized manifest: $($directory.Name)"
        continue
    }
    try {
        $schemaVersion = [int]$manifest.schema_version
    }
    catch {
        Write-Warning "Skipped directory with an unrecognized manifest: $($directory.Name)"
        continue
    }
    if ($schemaVersion -ne 2 -or [string]$manifest.database -ne 'ky_jarvis') {
        Write-Warning "Skipped directory with an unrecognized manifest: $($directory.Name)"
        continue
    }

    $candidatePath = (Resolve-Path -LiteralPath $directory.FullName).Path.TrimEnd('\')
    $candidateParent = [IO.Path]::GetDirectoryName($candidatePath).TrimEnd('\')
    if (-not $candidatePath.StartsWith(
        $backupPrefix,
        [StringComparison]::OrdinalIgnoreCase
    ) -or -not $candidateParent.Equals(
        $resolvedBackupRoot,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw 'Resolved retention target is not a direct child of BackupRoot.'
    }
    $eligible += $candidatePath
}

if ($eligible.Count -eq 0) {
    Write-Output "No owned backup is older than $RetentionDays day(s)."
    return
}
foreach ($candidatePath in $eligible) {
    Write-Output "Retention candidate: $candidatePath"
}
if (-not $ConfirmPrune) {
    Write-Output 'Retention preview only; no backup was removed. Re-run with -ConfirmPrune.'
    return
}

$removed = 0
foreach ($candidatePath in $eligible) {
    if ($PSCmdlet.ShouldProcess($candidatePath, 'Remove expired KY-JARVIS backup')) {
        Remove-Item -LiteralPath $candidatePath -Recurse -Force
        $removed++
    }
}
Write-Output "Retention prune complete: $removed backup(s) removed."
