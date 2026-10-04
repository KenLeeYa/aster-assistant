#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$OutputDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) 'reports'
}

function Get-CommandSummary {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [string[]]$CandidatePaths = @()
    )

    $resolvedCommand = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $resolvedCommand) {
        $candidate = $CandidatePaths |
            Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
            Select-Object -First 1
        if ($candidate) {
            $resolvedCommand = [pscustomobject]@{ Source = $candidate }
        }
    }
    if ($null -eq $resolvedCommand) {
        return [pscustomobject]@{ found = $false; path = $null; version = $null }
    }

    $previousErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $captured = & $resolvedCommand.Source @Arguments 2>&1 | Select-Object -First 6
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    return [pscustomobject]@{
        found = $true
        path = $resolvedCommand.Source
        version = (($captured | ForEach-Object { $_.ToString().Trim() }) -join ' | ')
    }
}

function Invoke-UnicodeProcess {
    param(
        [Parameter(Mandatory)] [string]$FileName,
        [Parameter(Mandatory)] [string]$Arguments
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FileName
    $startInfo.Arguments = $Arguments
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [System.Text.Encoding]::Unicode
    $startInfo.StandardErrorEncoding = [System.Text.Encoding]::Unicode
    $process = [System.Diagnostics.Process]::Start($startInfo)
    $standardOutput = $process.StandardOutput.ReadToEnd()
    $standardError = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    return [pscustomobject]@{
        exitCode = $process.ExitCode
        output = $standardOutput.Trim()
        error = $standardError.Trim()
    }
}

function Get-Sha256Prefix {
    param([Parameter(Mandatory)] [string]$Value)

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        $hashBytes = $sha256.ComputeHash($bytes)
        return (($hashBytes | ForEach-Object { $_.ToString('X2') }) -join '').Substring(0, 12)
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-AndroidInventory {
    $sdkCandidates = @(
        $env:ANDROID_SDK_ROOT,
        $env:ANDROID_HOME,
        (Join-Path $env:LOCALAPPDATA 'Android\Sdk')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $sdkPath = $sdkCandidates | Select-Object -First 1
    $studioCandidates = @(
        (Join-Path $env:ProgramFiles 'Android\Android Studio\bin\studio64.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Android Studio\bin\studio64.exe')
    )
    $studioPath = $studioCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

    $adbPath = $null
    $adbCommand = Get-Command adb -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($adbCommand) {
        $adbPath = $adbCommand.Source
    }
    elseif ($sdkPath) {
        $candidate = Join-Path $sdkPath 'platform-tools\adb.exe'
        if (Test-Path -LiteralPath $candidate) { $adbPath = $candidate }
    }

    $devices = @()
    $adbVersion = $null
    if ($adbPath) {
        $adbVersion = ((& $adbPath version 2>&1 | Select-Object -First 3) -join ' | ')
        $deviceLines = @(& $adbPath devices -l 2>&1) | Where-Object {
            $_ -match '^([^\s]+)\s+(device|unauthorized|offline)(\s|$)'
        }
        foreach ($deviceLine in $deviceLines) {
            $parts = $deviceLine -split '\s+', 3
            $devices += [pscustomobject]@{
                serialHash = Get-Sha256Prefix -Value $parts[0]
                state = $parts[1]
                metadata = if ($parts.Count -gt 2) { $parts[2] } else { '' }
            }
        }
    }

    $platforms = @()
    $buildTools = @()
    if ($sdkPath) {
        $platformDirectory = Join-Path $sdkPath 'platforms'
        $buildToolsDirectory = Join-Path $sdkPath 'build-tools'
        if (Test-Path -LiteralPath $platformDirectory) {
            $platforms = @(Get-ChildItem -Directory -LiteralPath $platformDirectory |
                    Select-Object -ExpandProperty Name)
        }
        if (Test-Path -LiteralPath $buildToolsDirectory) {
            $buildTools = @(Get-ChildItem -Directory -LiteralPath $buildToolsDirectory |
                    Select-Object -ExpandProperty Name)
        }
    }

    return [pscustomobject]@{
        studioPath = $studioPath
        sdkPath = $sdkPath
        installedPlatforms = $platforms
        installedBuildTools = $buildTools
        adbFound = $null -ne $adbPath
        adbVersion = $adbVersion
        connectedDeviceCount = $devices.Count
        connectedDevices = $devices
    }
}

function Get-MsvcInventory {
    $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    $vswherePath = $null
    if ($programFilesX86) {
        $candidate = Join-Path $programFilesX86 'Microsoft Visual Studio\Installer\vswhere.exe'
        if (Test-Path -LiteralPath $candidate) {
            $vswherePath = $candidate
        }
    }

    if (-not $vswherePath) {
        return [pscustomobject]@{
            installed = $false
            vswherePath = $null
            installationPath = $null
            toolsetVersion = $null
            compilerPath = $null
            compilerFileVersion = $null
            linkerPath = $null
            windowsSdkVersion = $null
            resourceCompilerPath = $null
        }
    }

    $installationPath = & $vswherePath -latest -products '*' `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($installationPath)) {
        return [pscustomobject]@{
            installed = $false
            vswherePath = $vswherePath
            installationPath = $null
            toolsetVersion = $null
            compilerPath = $null
            compilerFileVersion = $null
            linkerPath = $null
            windowsSdkVersion = $null
            resourceCompilerPath = $null
        }
    }

    $toolset = Get-ChildItem -Directory -LiteralPath (Join-Path $installationPath 'VC\Tools\MSVC') |
        Sort-Object Name -Descending |
        Select-Object -First 1
    $compilerPath = if ($toolset) {
        Join-Path $toolset.FullName 'bin\Hostx64\x64\cl.exe'
    }
    else { $null }
    $linkerPath = if ($toolset) {
        Join-Path $toolset.FullName 'bin\Hostx64\x64\link.exe'
    }
    else { $null }
    $compilerVersion = if ($compilerPath -and (Test-Path -LiteralPath $compilerPath)) {
        (Get-Item -LiteralPath $compilerPath).VersionInfo.FileVersion
    }
    else { $null }

    $sdkRoot = if ($programFilesX86) { Join-Path $programFilesX86 'Windows Kits\10\bin' } else { $null }
    $sdkDirectory = if ($sdkRoot -and (Test-Path -LiteralPath $sdkRoot)) {
        Get-ChildItem -Directory -LiteralPath $sdkRoot |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'x64\rc.exe') } |
            Sort-Object Name -Descending |
            Select-Object -First 1
    }
    else { $null }
    $resourceCompilerPath = if ($sdkDirectory) {
        Join-Path $sdkDirectory.FullName 'x64\rc.exe'
    }
    else { $null }

    return [pscustomobject]@{
        installed = ($compilerPath -and $linkerPath -and $resourceCompilerPath -and
            (Test-Path -LiteralPath $compilerPath) -and
            (Test-Path -LiteralPath $linkerPath) -and
            (Test-Path -LiteralPath $resourceCompilerPath))
        vswherePath = $vswherePath
        installationPath = $installationPath
        toolsetVersion = if ($toolset) { $toolset.Name } else { $null }
        compilerPath = $compilerPath
        compilerFileVersion = $compilerVersion
        linkerPath = $linkerPath
        windowsSdkVersion = if ($sdkDirectory) { $sdkDirectory.Name } else { $null }
        resourceCompilerPath = $resourceCompilerPath
    }
}

$operatingSystem = Get-CimInstance Win32_OperatingSystem
$computerSystem = Get-CimInstance Win32_ComputerSystem
$processors = @(Get-CimInstance Win32_Processor | ForEach-Object {
        [pscustomobject]@{
            name = $_.Name.Trim()
            cores = $_.NumberOfCores
            logicalProcessors = $_.NumberOfLogicalProcessors
            maximumClockMHz = $_.MaxClockSpeed
        }
    })
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
        [pscustomobject]@{
            device = $_.DeviceID
            sizeBytes = [int64]$_.Size
            freeBytes = [int64]$_.FreeSpace
        }
    })

$nvidia = [pscustomobject]@{ found = $false; gpus = @() }
$nvidiaCommand = Get-Command nvidia-smi -ErrorAction SilentlyContinue | Select-Object -First 1
if ($nvidiaCommand) {
    $gpuRows = & $nvidiaCommand.Source --query-gpu=name,driver_version,memory.total `
        --format=csv,noheader,nounits 2>$null
    $nvidia = [pscustomobject]@{
        found = $true
        gpus = @($gpuRows | ForEach-Object {
                $parts = $_ -split ',\s*'
                [pscustomobject]@{
                    name = $parts[0]
                    driverVersion = $parts[1]
                    memoryMiB = [int]$parts[2]
                }
            })
    }
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue | Select-Object -First 1
$dockerService = Get-Service 'com.docker.service' -ErrorAction SilentlyContinue
$docker = [pscustomobject]@{
    found = $null -ne $dockerCommand
    clientVersion = if ($dockerCommand) { & $dockerCommand.Source version --format '{{.Client.Version}}' 2>$null } else { $null }
    serverVersion = if ($dockerCommand) { & $dockerCommand.Source version --format '{{.Server.Version}}' 2>$null } else { $null }
    serviceStatus = if ($dockerService) { $dockerService.Status.ToString() } else { $null }
}

$wsl = [pscustomobject]@{ found = $false; version = $null; distributions = $null }
if (Get-Command wsl -ErrorAction SilentlyContinue) {
    $wslVersion = Invoke-UnicodeProcess -FileName 'wsl.exe' -Arguments '--version'
    $wslDistributions = Invoke-UnicodeProcess -FileName 'wsl.exe' -Arguments '--list --verbose'
    $wsl = [pscustomobject]@{
        found = $true
        version = $wslVersion.output
        distributions = $wslDistributions.output
    }
}

$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $ollamaCommand) {
    $ollamaCandidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path -LiteralPath $ollamaCandidate) {
        $ollamaCommand = [pscustomobject]@{ Source = $ollamaCandidate }
    }
}
$ollamaApiVersion = $null
$ollamaModels = @()
try {
    $ollamaApiVersion = (Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' `
            -Method Get -TimeoutSec 2).version
    $ollamaTags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' `
        -Method Get -TimeoutSec 2
    $ollamaModels = @($ollamaTags.models | ForEach-Object {
            [pscustomobject]@{
                name = $_.name
                digest = $_.digest
                sizeBytes = [int64]$_.size
                quantization = if ($_.details) { $_.details.quantization_level } else { $null }
            }
        })
}
catch {}

$tools = [ordered]@{
    git = Get-CommandSummary -Name 'git' -Arguments @('--version')
    powershell7 = Get-CommandSummary -Name 'pwsh' -Arguments @('--version')
    windowsPowerShell = Get-CommandSummary -Name 'powershell' -Arguments @('-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()')
    python = Get-CommandSummary -Name 'python' -Arguments @('--version')
    uv = Get-CommandSummary -Name 'uv' -Arguments @('--version')
    node = Get-CommandSummary -Name 'node' -Arguments @('--version')
    corepack = Get-CommandSummary -Name 'corepack' -Arguments @('--version')
    pnpm = Get-CommandSummary -Name 'pnpm' -Arguments @('--version')
    rustc = Get-CommandSummary -Name 'rustc' -Arguments @('--version') -CandidatePaths @(
        (Join-Path $env:USERPROFILE '.cargo\bin\rustc.exe')
    )
    cargo = Get-CommandSummary -Name 'cargo' -Arguments @('--version') -CandidatePaths @(
        (Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe')
    )
    java = Get-CommandSummary -Name 'java' -Arguments @('-version')
}

$soundDevices = @(Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue | ForEach-Object {
        [pscustomobject]@{ name = $_.Name; manufacturer = $_.Manufacturer; status = $_.Status }
    })
$audioEndpoints = @(Get-PnpDevice -Class AudioEndpoint -Status OK -ErrorAction SilentlyContinue |
        ForEach-Object { [pscustomobject]@{ name = $_.FriendlyName; status = $_.Status } })

$inventory = [ordered]@{
    schemaVersion = '1.0'
    capturedAt = (Get-Date).ToUniversalTime().ToString('o')
    timezone = (Get-TimeZone).Id
    operatingSystem = [ordered]@{
        caption = $operatingSystem.Caption
        version = $operatingSystem.Version
        buildNumber = $operatingSystem.BuildNumber
        architecture = $operatingSystem.OSArchitecture
    }
    computer = [ordered]@{
        manufacturer = $computerSystem.Manufacturer
        model = $computerSystem.Model
        totalPhysicalMemoryBytes = [int64]$computerSystem.TotalPhysicalMemory
        totalPhysicalMemoryGiB = [math]::Round($computerSystem.TotalPhysicalMemory / 1GB, 2)
    }
    processors = $processors
    disks = $disks
    nvidia = $nvidia
    docker = $docker
    wsl = $wsl
    ollama = [ordered]@{
        cliFound = $null -ne $ollamaCommand
        cliPath = if ($ollamaCommand) { $ollamaCommand.Source } else { $null }
        apiVersion = $ollamaApiVersion
        models = $ollamaModels
    }
    msvc = Get-MsvcInventory
    tools = $tools
    android = Get-AndroidInventory
    audio = [ordered]@{ soundDevices = $soundDevices; endpoints = $audioEndpoints }
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$jsonPath = Join-Path $OutputDirectory 'system_inventory.json'
$markdownPath = Join-Path $OutputDirectory 'system_inventory.md'
$androidPath = Join-Path $OutputDirectory 'android_environment.md'
$inventory | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $jsonPath -Encoding utf8

$ramGiB = $inventory.computer.totalPhysicalMemoryGiB
$diskLine = ($disks | ForEach-Object {
        "- $($_.device) size: $([math]::Round($_.sizeBytes / 1GB, 2)) GiB; free: $([math]::Round($_.freeBytes / 1GB, 2)) GiB"
    }) -join "`n"
$toolLines = ($tools.GetEnumerator() | ForEach-Object {
        "| $($_.Key) | $($_.Value.found) | $($_.Value.version) |"
    }) -join "`n"
$ollamaModelSummary = if ($ollamaModels.Count -gt 0) {
    ($ollamaModels | ForEach-Object { "$($_.name) [$($_.quantization)]" }) -join ', '
}
else {
    'none detected'
}
$androidConstraint = if ($inventory.android.connectedDeviceCount -gt 0) {
    "- Authorized Android devices detected: $($inventory.android.connectedDeviceCount); physical-device test status is tracked in reports/android_compatibility.md."
}
else {
    '- No authorized Android device was detected; physical-device test status is tracked in reports/android_compatibility.md.'
}
$inventoryMarkdown = @"
# System inventory

Captured: $($inventory.capturedAt)

## Hardware and operating system

- OS: $($inventory.operatingSystem.caption) $($inventory.operatingSystem.version) build $($inventory.operatingSystem.buildNumber)
- Computer: $($inventory.computer.manufacturer) $($inventory.computer.model)
- Physical memory: $ramGiB GiB (32 GB design class)
- CPU: $($processors[0].name), $($processors[0].cores) cores / $($processors[0].logicalProcessors) logical processors
- GPU: $($nvidia.gpus[0].name), $($nvidia.gpus[0].memoryMiB) MiB VRAM, driver $($nvidia.gpus[0].driverVersion)
- Timezone: $($inventory.timezone)

## Local fixed disks

$diskLine

## Toolchain

| Tool | Found | Version evidence |
|---|---:|---|
$toolLines

## Runtime observations

- Docker client/server: $($docker.clientVersion) / $($docker.serverVersion)
- Docker service status at capture: $($docker.serviceStatus)
- WSL: $($wsl.version -replace "`r?`n", '; ')
- Ollama CLI/API: $($inventory.ollama.cliFound) / $($inventory.ollama.apiVersion)
- Ollama models: $ollamaModelSummary
- MSVC x64 toolset: $($inventory.msvc.installed), compiler $($inventory.msvc.compilerFileVersion), Windows SDK $($inventory.msvc.windowsSdkVersion)
- Android SDK: $($inventory.android.sdkPath)
- Android platforms: $($inventory.android.installedPlatforms -join ', ')
- Connected Android devices: $($inventory.android.connectedDeviceCount) (serials are never recorded in plaintext)
- Working audio endpoints: $($audioEndpoints.name -join '; ')

## Constraints

- Rust CLI detected: $($tools.rustc.found). Visual C++/MSVC x64 toolset detected: $($inventory.msvc.installed).
- Ollama CLI/API detected: $($inventory.ollama.cliFound) / $($inventory.ollama.apiVersion). Models: $ollamaModelSummary.
$androidConstraint
- Inventory is read-only evidence. It is not proof that optional runtimes pass application tests.
"@
$inventoryMarkdown | Set-Content -LiteralPath $markdownPath -Encoding utf8

$androidMarkdown = @"
# Android environment

- Android Studio: $($inventory.android.studioPath)
- SDK root: $($inventory.android.sdkPath)
- Platforms: $($inventory.android.installedPlatforms -join ', ')
- Build tools: $($inventory.android.installedBuildTools -join ', ')
- ADB: $($inventory.android.adbVersion)
- Connected/authorized devices: $($inventory.android.connectedDeviceCount)
- JDK: $($tools.java.version)

Status: environment discovery PASS; physical-device test status is tracked in reports/android_compatibility.md.
"@
$androidMarkdown | Set-Content -LiteralPath $androidPath -Encoding utf8

Write-Output "Inventory written to $OutputDirectory"
