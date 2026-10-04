#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$')]
    [string]$ChatModel = 'qwen3:8b',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$')]
    [string]$EmbeddingModel = 'nomic-embed-text:latest',
    [switch]$ConfirmDownload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ollama = Get-Command ollama -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $ollama) {
    $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path -LiteralPath $candidate) {
        $ollama = [pscustomobject]@{ Source = $candidate }
    }
}
if (-not $ollama) {
    throw 'Ollama is not installed.'
}

$ollamaApiAvailable = $true
try {
    $catalog = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' `
        -Method Get -TimeoutSec 5
    $installedModels = @($catalog.models | ForEach-Object { $_.name })
}
catch {
    $ollamaApiAvailable = $false
    $manifestRoot = Join-Path $env:USERPROFILE `
        '.ollama\models\manifests\registry.ollama.ai\library'
    $installedModels = if (Test-Path -LiteralPath $manifestRoot) {
        @(
            Get-ChildItem -LiteralPath $manifestRoot -File -Recurse |
                ForEach-Object {
                    $_.FullName.Substring($manifestRoot.Length + 1).Replace('\', ':')
                }
        )
    }
    else { @() }
}
$requestedModels = @($ChatModel, $EmbeddingModel) | Select-Object -Unique
$missingModels = @($requestedModels | Where-Object { $_ -notin $installedModels })
if ($missingModels.Count -eq 0) {
    Write-Output "Recommended local models are already installed: $($requestedModels -join ', ')"
    if (-not $ollamaApiAvailable) {
        Write-Output 'Ollama is currently stopped; installed manifests were inspected without starting it.'
    }
    return
}

Write-Output "Missing recommended model(s): $($missingModels -join ', ')"
if (-not $ConfirmDownload) {
    Write-Output 'No download was started. Review disk/network impact, then re-run with -ConfirmDownload.'
    return
}
if (-not $ollamaApiAvailable) {
    throw 'Start Ollama before the explicitly approved download. No download was attempted.'
}

foreach ($model in $missingModels) {
    Write-Output "Downloading explicitly approved model: $model"
    & $ollama.Source pull $model
    if ($LASTEXITCODE -ne 0) {
        throw "Ollama failed to pull the approved model: $model"
    }
}
Write-Output 'Explicitly approved local model downloads completed.'
