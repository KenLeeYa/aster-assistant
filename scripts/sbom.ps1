#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = Join-Path $repositoryRoot 'reports\sbom'
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

$syftCommand = Get-Command syft -ErrorAction SilentlyContinue | Select-Object -First 1
if ($syftCommand) {
    $syftPath = $syftCommand.Source
} else {
    $syftFile = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Filter 'syft.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $syftFile) { throw 'Syft is not installed.' }
    $syftPath = $syftFile.FullName
}

& $syftPath "dir:$repositoryRoot" --source-name 'ky-jarvis-source' --source-version '0.1.0' --exclude './.git/**' --exclude './.venv/**' --exclude '**/node_modules/**' --exclude '**/build/**' -o "cyclonedx-json=$outputRoot\source.cdx.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$sourceBom = Get-Content -Raw -LiteralPath (Join-Path $outputRoot 'source.cdx.json') | ConvertFrom-Json
$androidComponents = @(
    $sourceBom.components | Where-Object {
        $null -ne $_.PSObject.Properties['purl'] -and $_.purl -like 'pkg:maven/*'
    }
)
$androidDependencyBom = [ordered]@{
    bomFormat = 'CycloneDX'
    specVersion = '1.6'
    version = 1
    metadata = [ordered]@{
        component = [ordered]@{
            type = 'application'
            name = 'KY-JARVIS Android dependencies'
            version = '0.1.0'
        }
    }
    components = $androidComponents
}
$androidDependencyBom | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath (Join-Path $outputRoot 'android-dependencies.cdx.json') -Encoding UTF8
$apk = Join-Path $repositoryRoot 'apps\android\app\build\outputs\apk\debug\app-debug.apk'
if (Test-Path -LiteralPath $apk) {
    & $syftPath "file:$apk" -o "cyclonedx-json=$outputRoot\android-debug.cdx.json"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$windowsDesktop = Join-Path $repositoryRoot `
    'apps\desktop\src-tauri\target\release\ky-jarvis-desktop.exe'
if (Test-Path -LiteralPath $windowsDesktop) {
    & $syftPath "file:$windowsDesktop" -o "cyclonedx-json=$outputRoot\windows-desktop.cdx.json"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$androidArtifacts = @(
    [pscustomobject]@{
        Path = Join-Path $repositoryRoot 'apps\android\app\build\outputs\apk\debug\app-debug.apk'
        Label = 'apps/android/app/build/outputs/apk/debug/app-debug.apk'
    },
    [pscustomobject]@{
        Path = Join-Path $repositoryRoot 'apps\android\app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk'
        Label = 'apps/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk'
    },
    [pscustomobject]@{
        Path = Join-Path $repositoryRoot 'apps\android\app\build\outputs\apk\release\app-release-unsigned.apk'
        Label = 'apps/android/app/build/outputs/apk/release/app-release-unsigned.apk'
    },
    [pscustomobject]@{
        Path = Join-Path $repositoryRoot 'apps\android\app\build\outputs\bundle\release\app-release.aab'
        Label = 'apps/android/app/build/outputs/bundle/release/app-release.aab'
    }
)
$androidChecksums = foreach ($artifact in $androidArtifacts) {
    if (Test-Path -LiteralPath $artifact.Path) {
        "$((Get-FileHash -Algorithm SHA256 -LiteralPath $artifact.Path).Hash)  $($artifact.Label)"
    }
}
$androidChecksums | Set-Content -LiteralPath (
    Join-Path $outputRoot 'ANDROID_ARTIFACT_SHA256SUMS'
) -Encoding ASCII

$artifacts = Get-ChildItem $outputRoot -File | Where-Object {
    $_.Name -notin @('SHA256SUMS', 'ANDROID_ARTIFACT_SHA256SUMS')
}
$checksums = foreach ($artifact in $artifacts) {
    "$((Get-FileHash -Algorithm SHA256 -LiteralPath $artifact.FullName).Hash)  $($artifact.Name)"
}
$checksums | Set-Content -LiteralPath (Join-Path $outputRoot 'SHA256SUMS') -Encoding ASCII
Write-Output "SBOM generated: $outputRoot"
