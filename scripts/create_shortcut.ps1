[CmdletBinding()]
param(
  [string]$TargetDir = $PSScriptRoot,
  [string]$AppName = "NotesAgentApp"
)

$ErrorActionPreference = "Stop"

$exePath = Join-Path $TargetDir "$AppName.exe"
if (-not (Test-Path $exePath)) {
  throw "Executable not found: $exePath"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "$AppName.lnk"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exePath
$shortcut.WorkingDirectory = $TargetDir
$shortcut.IconLocation = "$exePath,0"
$shortcut.WindowStyle = 1
$shortcut.Description = "Notes Agent Desktop Shortcut"
$shortcut.Save()

Write-Host "Shortcut created: $shortcutPath"
