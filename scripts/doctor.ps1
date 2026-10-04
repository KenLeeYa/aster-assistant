#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$required = @('git', 'python', 'uv', 'node', 'corepack', 'pnpm')
$optional = @('docker', 'ollama', 'rustc', 'cargo', 'adb')
$optionalCandidates = @{
    ollama = @((Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'))
    rustc = @((Join-Path $env:USERPROFILE '.cargo\bin\rustc.exe'))
    cargo = @((Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'))
    adb = @((Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'))
}
$results = @()

foreach ($toolName in $required) {
    $tool = Get-Command $toolName -ErrorAction SilentlyContinue | Select-Object -First 1
    $results += [pscustomobject]@{
        Tool = $toolName
        Requirement = 'foundation'
        Status = if ($tool) { 'PASS' } else { 'FAIL' }
        Path = if ($tool) { $tool.Source } else { $null }
    }
}

foreach ($toolName in $optional) {
    $tool = Get-Command $toolName -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $tool -and $optionalCandidates.ContainsKey($toolName)) {
        $candidate = $optionalCandidates[$toolName] |
            Where-Object { Test-Path -LiteralPath $_ } |
            Select-Object -First 1
        if ($candidate) {
            $tool = [pscustomobject]@{ Source = $candidate }
        }
    }
    $results += [pscustomobject]@{
        Tool = $toolName
        Requirement = 'later-phase'
        Status = if ($tool) { 'PASS' } else { 'BLOCKED' }
        Path = if ($tool) { $tool.Source } else { $null }
    }
}

$programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
$vswherePath = if ($programFilesX86) {
    Join-Path $programFilesX86 'Microsoft Visual Studio\Installer\vswhere.exe'
}
else { $null }
$msvcPath = if ($vswherePath -and (Test-Path -LiteralPath $vswherePath)) {
    & $vswherePath -latest -products '*' `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath | Select-Object -First 1
}
else { $null }
$results += [pscustomobject]@{
    Tool = 'msvc-x64'
    Requirement = 'later-phase'
    Status = if ($msvcPath) { 'PASS' } else { 'BLOCKED' }
    Path = $msvcPath
}

$portChecks = foreach ($portNumber in @(3000, 8765, 55433)) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $portNumber -ErrorAction SilentlyContinue
    [pscustomobject]@{
        Tool = "tcp:$portNumber"
        Requirement = 'startup'
        Status = if ($listener) { 'IN_USE' } else { 'PASS' }
        Path = $null
    }
}
$results += $portChecks
$results | Format-Table -AutoSize

if ($results | Where-Object { $_.Requirement -eq 'foundation' -and $_.Status -eq 'FAIL' }) {
    exit 1
}
exit 0
