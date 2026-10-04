#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$reportRoot = Join-Path $repositoryRoot 'reports\scans'
New-Item -ItemType Directory -Path $reportRoot -Force | Out-Null

function Resolve-Scanner([string]$Name, [string]$Executable) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    $match = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Filter $Executable -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($match) { return $match.FullName }
    throw "$Name is not installed."
}

$gitleaks = Resolve-Scanner 'gitleaks' 'gitleaks.exe'
$trivy = Resolve-Scanner 'trivy' 'trivy.exe'

& $gitleaks dir $repositoryRoot --redact --report-format json --report-path (Join-Path $reportRoot 'gitleaks.json')
$gitleaksExit = $LASTEXITCODE
& $trivy fs $repositoryRoot --scanners vuln,misconfig,secret --severity HIGH,CRITICAL --skip-dirs '.git' --skip-dirs '.venv' --skip-dirs 'node_modules' --skip-dirs 'apps/web/.next' --skip-dirs 'apps/android/.gradle' --skip-dirs 'apps/android/app/build' --skip-dirs 'apps/desktop/src-tauri/target' --skip-dirs 'reports/scans' --format json --output (Join-Path $reportRoot 'trivy.json') --exit-code 1
$trivyExit = $LASTEXITCODE
& $trivy fs $repositoryRoot --scanners vuln --skip-dirs '.git' --skip-dirs '.venv' --skip-dirs 'node_modules' --skip-dirs 'apps/web/.next' --skip-dirs 'apps/android/.gradle' --skip-dirs 'apps/android/app/build' --skip-dirs 'apps/desktop/src-tauri/target' --skip-dirs 'reports/scans' --format json --output (Join-Path $reportRoot 'trivy-all.json')
$trivyAllExit = $LASTEXITCODE

if ($gitleaksExit -ne 0 -or $trivyExit -ne 0 -or $trivyAllExit -ne 0) {
    Write-Error "Security gate failed: gitleaks=$gitleaksExit trivy=$trivyExit trivy-all=$trivyAllExit"
    exit 1
}
Write-Output 'Security scans PASS: no HIGH/CRITICAL findings and no detected secrets; all-severity dependency inventory generated.'
