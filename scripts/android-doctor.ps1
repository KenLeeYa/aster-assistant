#Requires -Version 5.1
[CmdletBinding()]
param([switch]$RequireDevice)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$androidRoot = Join-Path $repositoryRoot 'apps\android'
$sdkRoot = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { $env:ANDROID_HOME }
$failures = @()

function Add-Result {
    param([string]$Check, [string]$Status, [string]$Evidence)
    [pscustomobject]@{ Check = $Check; Status = $Status; Evidence = $Evidence }
    if ($Status -eq 'FAIL') { $script:failures += $Check }
}

$results = @()
$results += Add-Result 'JAVA_HOME' $(if ($env:JAVA_HOME -and (Test-Path -LiteralPath $env:JAVA_HOME)) { 'PASS' } else { 'FAIL' }) $(if ($env:JAVA_HOME) { $env:JAVA_HOME } else { 'unset' })
$androidStudio = 'C:\Program Files\Android\Android Studio\bin\studio64.exe'
$results += Add-Result 'Android Studio' $(if (Test-Path -LiteralPath $androidStudio) { 'PASS' } else { 'FAIL' }) $androidStudio
$results += Add-Result 'Android SDK' $(if ($sdkRoot -and (Test-Path -LiteralPath $sdkRoot)) { 'PASS' } else { 'FAIL' }) $(if ($sdkRoot) { $sdkRoot } else { 'unset' })
$results += Add-Result 'Gradle wrapper' $(if (Test-Path -LiteralPath (Join-Path $androidRoot 'gradlew.bat')) { 'PASS' } else { 'FAIL' }) 'apps\android\gradlew.bat'

if ($sdkRoot) {
    $results += Add-Result 'compile SDK 37.1' $(if (Test-Path -LiteralPath (Join-Path $sdkRoot 'platforms\android-37.1')) { 'PASS' } else { 'FAIL' }) 'platforms;android-37.1'
    $results += Add-Result 'build tools 37.0.0' $(if (Test-Path -LiteralPath (Join-Path $sdkRoot 'build-tools\37.0.0')) { 'PASS' } else { 'FAIL' }) 'build-tools;37.0.0'
    $licenseFiles = @(Get-ChildItem (Join-Path $sdkRoot 'licenses') -File -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 0 })
    $results += Add-Result 'SDK license receipts' $(if ($licenseFiles.Count -gt 0) { 'PASS' } else { 'FAIL' }) "$($licenseFiles.Count) non-empty receipt file(s); values not displayed"
    $emulator = Join-Path $sdkRoot 'emulator\emulator.exe'
    $results += Add-Result 'Emulator executable' $(if (Test-Path -LiteralPath $emulator) { 'PASS' } else { 'FAIL' }) 'emulator\emulator.exe'
    if (Test-Path -LiteralPath $emulator) {
        $avds = @(& $emulator -list-avds | Where-Object { $_.Trim() })
        $results += Add-Result 'Configured emulator AVD' $(if ($avds.Count -gt 0) { 'PASS' } else { 'NOT RUN' }) $(if ($avds.Count -gt 0) { $avds -join ', ' } else { 'none configured' })
    }
    $adb = Join-Path $sdkRoot 'platform-tools\adb.exe'
    if (Test-Path -LiteralPath $adb) {
        $authorized = @(& $adb devices | Select-Object -Skip 1 | Where-Object { $_ -match '\sdevice$' })
        $deviceStatus = if ($authorized.Count -gt 0) { 'PASS' } elseif ($RequireDevice) { 'FAIL' } else { 'NOT RUN' }
        $deviceEvidence = if ($authorized.Count -gt 0) {
            $hashes = foreach ($line in $authorized) {
                $serial = ($line -split '\s+')[0]
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($serial)
                $digest = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
                ([BitConverter]::ToString($digest) -replace '-', '').Substring(0, 12)
            }
            "$($authorized.Count) authorized; serial_sha256_prefix=$($hashes -join ',')"
        } else { 'no authorized device' }
        $results += Add-Result 'ADB device' $deviceStatus $deviceEvidence
    } else {
        $results += Add-Result 'ADB' 'FAIL' 'platform-tools\adb.exe missing'
    }
}

$results | Format-Table -AutoSize
$reportPath = Join-Path $repositoryRoot 'reports\android_environment.md'
$reportLines = @(
    '# Android environment',
    '',
    "Generated: $((Get-Date).ToUniversalTime().ToString('o'))",
    '',
    '| Check | Status | Evidence |',
    '|---|---|---|'
)
foreach ($result in $results) {
    $safeEvidence = $result.Evidence -replace '\|', '\|'
    $reportLines += "| $($result.Check) | $($result.Status) | $safeEvidence |"
}
$reportLines += @(
    '',
    'The doctor does not accept licenses, install SDK components, expose raw device serials or alter an app/device.',
    'Current execution evidence and historical physical-device scope are kept in reports/android_compatibility.md and reports/android_device_test.md.'
)
$reportLines | Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Output "Android environment report: $reportPath"
if ($failures.Count -gt 0) {
    Write-Error "Android doctor failed: $($failures -join ', ')"
    exit 1
}
exit 0
