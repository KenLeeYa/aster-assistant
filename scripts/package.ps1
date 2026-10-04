#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipDesktop,
    [switch]$SkipAndroid,
    [ValidatePattern('^emulator-\d+$')]
    [string]$AndroidEmulatorSerial
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$reportPath = Join-Path $repositoryRoot 'reports\package_report.md'
$sbomRoot = Join-Path $repositoryRoot 'reports\sbom'
$childPowerShell = Get-Command pwsh -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $childPowerShell) {
    $childPowerShell = Get-Command powershell.exe -ErrorAction Stop | Select-Object -First 1
}
$childPowerShellPath = $childPowerShell.Source
$laneResults = [ordered]@{}
$failures = [System.Collections.Generic.List[string]]::new()
$windowsArtifacts = @()
$androidArtifacts = @()

function Set-LaneResult {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$Status,
        [Parameter(Mandatory)] [string]$Evidence
    )
    $script:laneResults[$Name] = [pscustomobject]@{
        Status = $Status
        Evidence = $Evidence
    }
}

function Invoke-PackageLane {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [scriptblock]$Command
    )
    try {
        & $Command
        Set-LaneResult -Name $Name -Status 'PASS' -Evidence 'Build and artifact checks completed.'
    }
    catch {
        Set-LaneResult -Name $Name -Status 'FAIL' -Evidence $_.Exception.Message
        $script:failures.Add($Name)
    }
}

Push-Location $repositoryRoot
try {
    if ($SkipDesktop) {
        Set-LaneResult -Name 'Windows desktop' -Status 'SKIPPED' -Evidence 'Skipped by caller.'
    }
    elseif (-not (Get-Command corepack -ErrorAction SilentlyContinue) -or
        -not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        Set-LaneResult -Name 'Windows desktop' -Status 'BLOCKED' `
            -Evidence 'Corepack or Cargo is unavailable; no desktop build was attempted.'
    }
    else {
        Invoke-PackageLane -Name 'Windows desktop' -Command {
            & corepack pnpm@11.24.0 --dir apps/desktop build
            if ($LASTEXITCODE -ne 0) { throw 'Tauri build returned a non-zero exit code.' }

            $expected = @(
                [pscustomobject]@{
                    Label = 'ky-jarvis-desktop.exe'
                    Path = Join-Path $repositoryRoot `
                        'apps\desktop\src-tauri\target\release\ky-jarvis-desktop.exe'
                },
                [pscustomobject]@{
                    Label = 'KY-JARVIS_0.1.0_x64-setup.exe'
                    Path = Join-Path $repositoryRoot `
                        'apps\desktop\src-tauri\target\release\bundle\nsis\KY-JARVIS_0.1.0_x64-setup.exe'
                }
            )
            foreach ($artifact in $expected) {
                if (-not (Test-Path -LiteralPath $artifact.Path)) {
                    throw "Expected Windows artifact is missing: $($artifact.Label)"
                }
            }
            $script:windowsArtifacts = @($expected | ForEach-Object {
                $signature = Get-AuthenticodeSignature -LiteralPath $_.Path
                [pscustomobject]@{
                    Label = $_.Label
                    Path = $_.Path
                    Bytes = (Get-Item -LiteralPath $_.Path).Length
                    SHA256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.Path).Hash
                    Signature = $signature.Status.ToString()
                }
            })
        }
    }

    $androidSdk = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { $env:ANDROID_HOME }
    $gradleWrapper = Join-Path $repositoryRoot 'apps\android\gradlew.bat'
    if ($SkipAndroid) {
        Set-LaneResult -Name 'Android' -Status 'SKIPPED' -Evidence 'Skipped by caller.'
    }
    elseif (-not $androidSdk -or -not (Test-Path -LiteralPath $androidSdk) -or
        -not (Test-Path -LiteralPath $gradleWrapper) -or
        -not (Get-Command java -ErrorAction SilentlyContinue)) {
        Set-LaneResult -Name 'Android' -Status 'BLOCKED' `
            -Evidence 'Android SDK, Gradle wrapper, or Java is unavailable; desktop result is unaffected.'
    }
    else {
        Invoke-PackageLane -Name 'Android' -Command {
            $debugBuildArguments = @(
                '-NoProfile',
                '-File',
                (Join-Path $PSScriptRoot 'android-build.ps1'),
                '-Configuration',
                'Debug'
            )
            if ($AndroidEmulatorSerial) {
                $debugBuildArguments += @('-EmulatorSerial', $AndroidEmulatorSerial)
            }
            & $childPowerShellPath @debugBuildArguments
            if ($LASTEXITCODE -ne 0) { throw 'Android Debug lane returned a non-zero exit code.' }
            & $childPowerShellPath -NoProfile -File `
                (Join-Path $PSScriptRoot 'android-build.ps1') -Configuration Release -Bundle
            if ($LASTEXITCODE -ne 0) { throw 'Android Release lane returned a non-zero exit code.' }
            & $childPowerShellPath -NoProfile -File `
                (Join-Path $PSScriptRoot 'android-security-scan.ps1')
            if ($LASTEXITCODE -ne 0) { throw 'Android release security scan returned a non-zero exit code.' }

            $expected = @(
                [pscustomobject]@{
                    Label = 'app-debug.apk'
                    Path = Join-Path $repositoryRoot `
                        'apps\android\app\build\outputs\apk\debug\app-debug.apk'
                },
                [pscustomobject]@{
                    Label = 'app-debug-androidTest.apk'
                    Path = Join-Path $repositoryRoot `
                        'apps\android\app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk'
                },
                [pscustomobject]@{
                    Label = 'app-release-unsigned.apk'
                    Path = Join-Path $repositoryRoot `
                        'apps\android\app\build\outputs\apk\release\app-release-unsigned.apk'
                },
                [pscustomobject]@{
                    Label = 'app-release.aab'
                    Path = Join-Path $repositoryRoot `
                        'apps\android\app\build\outputs\bundle\release\app-release.aab'
                }
            )
            foreach ($artifact in $expected) {
                if (-not (Test-Path -LiteralPath $artifact.Path)) {
                    throw "Expected Android artifact is missing: $($artifact.Label)"
                }
            }
            $script:androidArtifacts = @($expected | ForEach-Object {
                [pscustomobject]@{
                    Label = $_.Label
                    Path = $_.Path
                    Bytes = (Get-Item -LiteralPath $_.Path).Length
                    SHA256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.Path).Hash
                }
            })
        }
        if ($laneResults['Android'].Status -eq 'PASS') {
            $laneResults['Android'].Evidence = if ($AndroidEmulatorSerial) {
                "Build, selected instrumentation and artifact checks completed on $AndroidEmulatorSerial."
            }
            else {
                'Build/static checks completed; instrumented tests were not rerun without an explicit emulator target.'
            }
        }
    }

    if ($windowsArtifacts.Count -gt 0) {
        New-Item -ItemType Directory -Path $sbomRoot -Force | Out-Null
        $windowsArtifacts | ForEach-Object {
            "$($_.SHA256)  $($_.Label)"
        } | Set-Content -LiteralPath (
            Join-Path $sbomRoot 'WINDOWS_ARTIFACT_SHA256SUMS'
        ) -Encoding ASCII
    }

    Invoke-PackageLane -Name 'SBOM/checksums' -Command {
        & $childPowerShellPath -NoProfile -File (Join-Path $PSScriptRoot 'sbom.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'SBOM generation returned a non-zero exit code.' }
    }

    $report = [System.Collections.Generic.List[string]]::new()
    $report.Add('# Package report')
    $report.Add('')
    $report.Add("Generated: $((Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz'))")
    $report.Add('')
    $report.Add('| Lane | Status | Evidence |')
    $report.Add('|---|---|---|')
    foreach ($entry in $laneResults.GetEnumerator()) {
        $safeEvidence = $entry.Value.Evidence.Replace('|', '/').Replace("`r", ' ').Replace("`n", ' ')
        $report.Add("| $($entry.Key) | $($entry.Value.Status) | $safeEvidence |")
    }

    $report.Add('')
    $report.Add('## Windows artifacts')
    $report.Add('')
    if ($windowsArtifacts.Count -eq 0) {
        $report.Add('No new Windows artifact was produced in this run.')
    }
    else {
        $report.Add('| Artifact | Bytes | SHA-256 | Authenticode |')
        $report.Add('|---|---:|---|---|')
        foreach ($artifact in $windowsArtifacts) {
            $report.Add(
                "| $($artifact.Label) | $($artifact.Bytes) | $($artifact.SHA256) | $($artifact.Signature) |"
            )
        }
    }

    $report.Add('')
    $report.Add('## Android artifacts')
    $report.Add('')
    if ($androidArtifacts.Count -eq 0) {
        $report.Add('No new Android artifact was produced in this run.')
    }
    else {
        $report.Add('| Artifact | Bytes | SHA-256 |')
        $report.Add('|---|---:|---|')
        foreach ($artifact in $androidArtifacts) {
            $report.Add("| $($artifact.Label) | $($artifact.Bytes) | $($artifact.SHA256) |")
        }
    }

    $report.Add('')
    $report.Add('Windows and Android release outputs remain unsigned Pilot artifacts. No signing key or password is created, read, or logged by this script.')
    $report | Set-Content -LiteralPath $reportPath -Encoding UTF8
}
finally {
    Pop-Location
}

if ($failures.Count -gt 0) {
    Write-Error "Packaging lanes failed: $($failures -join ', '). See reports/package_report.md."
    exit 1
}
Write-Output 'Packaging completed. See reports/package_report.md and reports/sbom/.'
