[CmdletBinding()]
param(
  [string]$AppName = "NotesAgentApp",
  [string]$Version = "1.2"
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$projectRoot = (Get-Location).Path

# 1) Build portable release first
& ".\scripts\build_release.ps1" -AppName $AppName -Version $Version

# 2) Find Inno Setup compiler
$isccCandidates = @(
  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
  "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$isccPath = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $isccPath) {
  throw "Inno Setup compiler (ISCC.exe) not found. Please install Inno Setup 6 first."
}

$sourceDir = Join-Path $projectRoot "release\$AppName"
if (-not (Test-Path (Join-Path $sourceDir "$AppName.exe"))) {
  throw "Portable build not found: $(Join-Path $sourceDir "$AppName.exe")"
}

# 3) Build installer
New-Item -ItemType Directory -Path "release\installer" -Force | Out-Null
& $isccPath "/DSourceDir=$sourceDir" "/DMyAppVersion=$Version" "/DMyOutputBaseFilename=$AppName-v$Version-Setup" ".\installer\NotesAgentApp.iss"

$setupPath = Join-Path $projectRoot "release\installer\$AppName-Setup.exe"
$setupVersionedPath = Join-Path $projectRoot "release\installer\$AppName-v$Version-Setup.exe"
if (-not (Test-Path $setupVersionedPath)) {
  throw "Setup build failed, versioned output not found: $setupVersionedPath"
}

Write-Host "Setup build completed:"
if (Test-Path $setupPath) {
  Write-Host "1) Default: $setupPath"
}
Write-Host "2) Versioned: $setupVersionedPath"
