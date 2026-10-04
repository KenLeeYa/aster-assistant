#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$androidSdk = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { $env:ANDROID_HOME }
if (-not $androidSdk) { throw 'ANDROID_SDK_ROOT or ANDROID_HOME is required.' }

$releaseApk = Join-Path $repositoryRoot 'apps\android\app\build\outputs\apk\release\app-release-unsigned.apk'
$releaseBundle = Join-Path $repositoryRoot 'apps\android\app\build\outputs\bundle\release\app-release.aab'
$apkanalyzer = Get-ChildItem (Join-Path $androidSdk 'cmdline-tools') -Filter 'apkanalyzer.bat' -Recurse -File |
    Sort-Object FullName | Select-Object -Last 1 -ExpandProperty FullName
$apksigner = Get-ChildItem (Join-Path $androidSdk 'build-tools') -Filter 'apksigner.bat' -Recurse -File |
    Sort-Object FullName | Select-Object -Last 1 -ExpandProperty FullName
$jarsigner = Join-Path $env:JAVA_HOME 'bin\jarsigner.exe'

foreach ($required in @($releaseApk, $releaseBundle, $apkanalyzer, $apksigner, $jarsigner)) {
    if (-not $required -or -not (Test-Path -LiteralPath $required)) {
        throw "Required Android release scanner input is missing: $required"
    }
}

$failures = @()
function Add-Failure([string]$Message) {
    $script:failures += $Message
}

$manifestOutput = & $apkanalyzer manifest print $releaseApk 2>&1
if ($LASTEXITCODE -ne 0) { throw "apkanalyzer failed: $($manifestOutput -join ' ')" }
[xml]$manifest = $manifestOutput -join [Environment]::NewLine
$androidNamespace = 'http://schemas.android.com/apk/res/android'
$application = $manifest.manifest.application
$usesSdk = $manifest.manifest.'uses-sdk'

if ($application.GetAttribute('allowBackup', $androidNamespace) -ne 'false') {
    Add-Failure 'release application must disable backup'
}
if ($application.GetAttribute('usesCleartextTraffic', $androidNamespace) -ne 'false') {
    Add-Failure 'release application must disable cleartext traffic'
}
$debuggable = $application.GetAttribute('debuggable', $androidNamespace)
if ($debuggable -and $debuggable -ne 'false') {
    Add-Failure 'release application must not be debuggable'
}
if ($usesSdk.GetAttribute('minSdkVersion', $androidNamespace) -ne '29') {
    Add-Failure 'release minimum SDK must remain 29'
}
if ($usesSdk.GetAttribute('targetSdkVersion', $androidNamespace) -ne '37') {
    Add-Failure 'release target SDK must remain 37'
}

$permissions = @($manifest.manifest.'uses-permission' | ForEach-Object {
    $_.GetAttribute('name', $androidNamespace)
})
$prohibitedPermissions = @(
    'android.permission.ACCESS_COARSE_LOCATION',
    'android.permission.ACCESS_FINE_LOCATION',
    'android.permission.MANAGE_EXTERNAL_STORAGE',
    'android.permission.QUERY_ALL_PACKAGES',
    'android.permission.READ_CONTACTS',
    'android.permission.READ_EXTERNAL_STORAGE',
    'android.permission.READ_SMS',
    'android.permission.RECEIVE_SMS',
    'android.permission.SEND_SMS',
    'android.permission.SYSTEM_ALERT_WINDOW',
    'android.permission.WRITE_CONTACTS',
    'android.permission.WRITE_EXTERNAL_STORAGE'
)
foreach ($permission in $prohibitedPermissions) {
    if ($permissions -contains $permission) { Add-Failure "prohibited permission: $permission" }
}

$components = @()
foreach ($kind in @('activity', 'service', 'receiver', 'provider')) {
    foreach ($node in @($application.$kind)) {
        if ($null -ne $node) {
            $components += [pscustomobject]@{
                Kind = $kind
                Name = $node.GetAttribute('name', $androidNamespace)
                Exported = $node.GetAttribute('exported', $androidNamespace)
                Permission = $node.GetAttribute('permission', $androidNamespace)
            }
        }
    }
}
$allowedExported = @(
    'activity|tw.ky.jarvis.MainActivity|',
    'receiver|androidx.profileinstaller.ProfileInstallReceiver|android.permission.DUMP',
    'receiver|tw.ky.jarvis.widget.JarvisWidgetProvider|',
    'service|tw.ky.jarvis.voice.JarvisQuickSettingsTile|android.permission.BIND_QUICK_SETTINGS_TILE',
    'service|tw.ky.jarvis.voice.JarvisVoiceInteractionService|android.permission.BIND_VOICE_INTERACTION'
)
$mainActivity = @($application.activity) | Where-Object {
    $_.GetAttribute('name', $androidNamespace) -eq 'tw.ky.jarvis.MainActivity'
} | Select-Object -First 1
if (-not $mainActivity) {
    Add-Failure 'release main activity is missing'
} elseif (
    $mainActivity.GetAttribute('showWhenLocked', $androidNamespace) -ne 'false' -or
    $mainActivity.GetAttribute('turnScreenOn', $androidNamespace) -ne 'false'
) {
    Add-Failure 'release main activity must remain hidden and inactive on the lock screen'
}
foreach ($component in @($components | Where-Object { $_.Exported -eq 'true' })) {
    $identity = "$($component.Kind)|$($component.Name)|$($component.Permission)"
    if ($allowedExported -notcontains $identity) {
        Add-Failure "unexpected exported component: $identity"
    }
}
if (($manifestOutput -join [Environment]::NewLine) -match 'android.intent.action.BOOT_COMPLETED') {
    Add-Failure 'release application must not auto-start on boot'
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$forbiddenArchivePatterns = [ordered]@{
    debug_package = 'tw\.ky\.jarvis\.debug'
    emulator_endpoint = 'http://10\.0\.2\.2:8765'
    instrumented_token_marker = 'instrumented-token-marker'
    loopback_debug_endpoint = 'http://127\.0\.0\.1:8765'
    openai_environment_key = 'OPENAI_API_KEY'
    reusable_openai_key_shape = 'sk-[A-Za-z0-9_-]{20,}'
}
function Find-ArchivePattern([string]$ArchivePath, [string]$Pattern) {
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        foreach ($entry in $archive.Entries) {
            $stream = $entry.Open()
            $memory = New-Object System.IO.MemoryStream
            try {
                $stream.CopyTo($memory)
                $text = [System.Text.Encoding]::GetEncoding(28591).GetString($memory.ToArray())
                if ($text -match $Pattern) { return $entry.FullName }
            }
            finally {
                $memory.Dispose()
                $stream.Dispose()
            }
        }
    }
    finally {
        $archive.Dispose()
    }
    return $null
}

$archiveHits = @()
foreach ($artifact in @($releaseApk, $releaseBundle)) {
    foreach ($pattern in $forbiddenArchivePatterns.GetEnumerator()) {
        $entry = Find-ArchivePattern $artifact $pattern.Value
        if ($entry) {
            $archiveHits += "$([IO.Path]::GetFileName($artifact)):$($pattern.Key):$entry"
        }
    }
}
foreach ($hit in $archiveHits) { Add-Failure "forbidden release archive content: $hit" }

$apkSignatureOutput = & $apksigner verify --verbose $releaseApk 2>&1
$apkSignatureExit = $LASTEXITCODE
if ($apkSignatureExit -eq 0 -or ($apkSignatureOutput -join ' ') -notmatch 'Missing META-INF/MANIFEST\.MF') {
    Add-Failure 'Pilot release APK must remain explicitly unsigned until protected signing is configured'
}
$bundleSignatureOutput = & $jarsigner -verify $releaseBundle 2>&1
if (($bundleSignatureOutput -join ' ') -notmatch 'jar is unsigned') {
    Add-Failure 'Pilot release AAB must remain explicitly unsigned until protected signing is configured'
}

$reportRoot = Join-Path $repositoryRoot 'reports\scans'
New-Item -ItemType Directory -Path $reportRoot -Force | Out-Null
$report = [ordered]@{
    generated_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    release_apk_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $releaseApk).Hash
    release_aab_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $releaseBundle).Hash
    min_sdk = $usesSdk.GetAttribute('minSdkVersion', $androidNamespace)
    target_sdk = $usesSdk.GetAttribute('targetSdkVersion', $androidNamespace)
    allow_backup = $application.GetAttribute('allowBackup', $androidNamespace)
    cleartext = $application.GetAttribute('usesCleartextTraffic', $androidNamespace)
    debuggable = $(if ($debuggable) { $debuggable } else { 'absent' })
    permissions = @($permissions | Sort-Object)
    exported_components = @($components | Where-Object { $_.Exported -eq 'true' })
    archive_forbidden_hits = $archiveHits
    apk_signing = 'unsigned-pilot'
    aab_signing = 'unsigned-pilot'
    failures = $failures
}
$report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (
    Join-Path $reportRoot 'android-release-static.json'
) -Encoding UTF8

if ($failures.Count -gt 0) {
    throw "Android release static scan failed: $($failures -join '; ')"
}
Write-Output 'Android release static scan PASS: hardened manifest, no forbidden archive strings, unsigned Pilot artifacts.'
