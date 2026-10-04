#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sdkRoot = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { $env:ANDROID_HOME }
if (-not $sdkRoot) { throw 'ANDROID_SDK_ROOT or ANDROID_HOME is required.' }
$adb = Join-Path $sdkRoot 'platform-tools\adb.exe'
$apk = Join-Path $repositoryRoot 'apps\android\app\build\outputs\apk\debug\app-debug.apk'
if (-not (Test-Path -LiteralPath $apk)) { throw 'Debug APK missing. Run scripts\android-build.ps1 first.' }
$devices = @(& $adb devices | Select-Object -Skip 1 | Where-Object { $_ -match '\sdevice$' })
if ($devices.Count -ne 1) { throw "Exactly one authorized Android device is required; found $($devices.Count)." }
$serial = ($devices[0] -split '\s+')[0]
$serialBytes = [System.Text.Encoding]::UTF8.GetBytes($serial)
$serialDigest = [System.Security.Cryptography.SHA256]::Create().ComputeHash($serialBytes)
$serialHashPrefix = ([BitConverter]::ToString($serialDigest) -replace '-', '').Substring(0, 12)
$model = (& $adb -s $serial shell getprop ro.product.model).Trim()
Write-Output "Install target: model=$model serial_sha256_prefix=$serialHashPrefix"
& $adb -s $serial install -r $apk
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $adb -s $serial shell am start -n 'tw.ky.jarvis.debug/tw.ky.jarvis.MainActivity'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output 'Debug APK installed with user data preserved; onboarding activity launched.'
