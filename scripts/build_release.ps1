[CmdletBinding()]
param(
  [string]$AppName = "NotesAgentApp",
  [string]$Version = "1.2"
)

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$projectRoot = (Get-Location).Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

function Remove-PathSafe {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PathText,
    [int]$Retry = 5
  )
  if (-not (Test-Path $PathText)) { return }
  for ($i = 1; $i -le $Retry; $i++) {
    try {
      Remove-Item $PathText -Recurse -Force -ErrorAction Stop
      return
    } catch {
      if ($i -eq $Retry) {
        Write-Warning "Failed to remove '$PathText'. Continue build with existing files."
        return
      }
      Start-Sleep -Milliseconds (250 * $i)
    }
  }
}

if (-not (Test-Path $venvPython)) {
  python -m venv .venv
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

try {
  & $venvPython -m pip install pyinstaller
} catch {
  throw "Failed to install PyInstaller. Please check network or pip index and retry."
}

Remove-PathSafe "build"
Remove-PathSafe "dist\$AppName"
Remove-PathSafe "release\$AppName"
Remove-PathSafe "release\$AppName-win64.zip"
Remove-PathSafe "release\$AppName-v$Version-win64.zip"
Remove-PathSafe "build_tmp\$AppName-v$Version"
Remove-PathSafe "dist_tmp\$AppName-v$Version"

$workPath = "build_tmp\$AppName-v$Version"
$distRoot = "dist_tmp\$AppName-v$Version"
$distAppDir = Join-Path $distRoot $AppName

& $venvPython -m PyInstaller `
  --noconfirm `
  --windowed `
  --onedir `
  --workpath $workPath `
  --distpath $distRoot `
  --name $AppName `
  --paths "." `
  "app\main.py"

$releaseDir = Join-Path $projectRoot "release\$AppName"
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
Copy-Item "$distAppDir\*" $releaseDir -Recurse -Force

$runBat = @"
@echo off
setlocal
cd /d %~dp0
start "" "%~dp0$AppName.exe"
"@
$runBat | Set-Content -Encoding ASCII (Join-Path $releaseDir "Run $AppName.bat")

Copy-Item "scripts\create_shortcut.ps1" (Join-Path $releaseDir "create_shortcut.ps1") -Force
Copy-Item "README.md" (Join-Path $releaseDir "README.md") -Force

$zipPath = "release\$AppName-win64.zip"
$zipVersionedPath = "release\$AppName-v$Version-win64.zip"
$maxRetry = 5
for ($i = 1; $i -le $maxRetry; $i++) {
  try {
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    if (Test-Path $zipVersionedPath) { Remove-Item $zipVersionedPath -Force }
    Compress-Archive -Path "$releaseDir\*" -DestinationPath $zipPath -Force
    Copy-Item $zipPath $zipVersionedPath -Force
    break
  } catch {
    if ($i -eq $maxRetry) { throw }
    Start-Sleep -Seconds (2 * $i)
  }
}

Write-Host "Build completed:"
Write-Host "1) Folder: $releaseDir"
Write-Host "2) Zip: $(Join-Path $projectRoot $zipPath)"
Write-Host "3) Versioned Zip: $(Join-Path $projectRoot $zipVersionedPath)"
