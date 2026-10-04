#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')] [string]$Configuration = 'Debug',
    [switch]$Bundle,
    [ValidatePattern('^(?:emulator-\d+)?$')]
    [string]$EmulatorSerial = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$androidRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'apps\android'
$qualityTasks = @(':app:ktlintCheck', ':app:detekt', ':app:testDebugUnitTest')
[string[]]$packageTasks = if ($Configuration -eq 'Debug') {
    $qualityTasks += ':app:lintDebug'
    @(':app:assembleDebug', ':app:assembleDebugAndroidTest')
} else {
    $qualityTasks += ':app:lintRelease'
    @(':app:assembleRelease')
}
if ($Bundle) { $packageTasks += ':app:bundleRelease' }

$originalAndroidSerial = $env:ANDROID_SERIAL
$hadAndroidSerial = Test-Path Env:ANDROID_SERIAL
if ($EmulatorSerial) {
    $androidSdk = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { $env:ANDROID_HOME }
    if (-not $androidSdk) { throw 'ANDROID_SDK_ROOT or ANDROID_HOME is required.' }
    $adb = Join-Path $androidSdk 'platform-tools\adb.exe'
    if (-not (Test-Path -LiteralPath $adb -PathType Leaf)) {
        throw 'Android platform-tools adb.exe is missing.'
    }
    $state = & $adb -s $EmulatorSerial get-state 2>$null
    if ($LASTEXITCODE -ne 0 -or $state.Trim() -ne 'device') {
        throw 'The explicitly selected emulator is not authorized and online.'
    }
    $isEmulator = & $adb -s $EmulatorSerial shell getprop ro.kernel.qemu 2>$null
    if ($LASTEXITCODE -ne 0 -or $isEmulator.Trim() -ne '1') {
        throw 'Instrumented tests accept an emulator target only; physical devices are refused.'
    }
    $env:ANDROID_SERIAL = $EmulatorSerial
}

Push-Location $androidRoot
try {
    & .\gradlew.bat @qualityTasks
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($EmulatorSerial) {
        & .\gradlew.bat :app:connectedDebugAndroidTest
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & .\gradlew.bat @packageTasks
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
    if ($hadAndroidSerial) {
        $env:ANDROID_SERIAL = $originalAndroidSerial
    }
    else {
        Remove-Item Env:ANDROID_SERIAL -ErrorAction SilentlyContinue
    }
}
