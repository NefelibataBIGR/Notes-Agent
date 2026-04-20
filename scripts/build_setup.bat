@echo off
setlocal
cd /d %~dp0
powershell -ExecutionPolicy Bypass -File ".\build_setup.ps1"
if errorlevel 1 (
  echo.
  echo Setup.exe 构建失败，请查看上面的错误信息。
  pause
  exit /b 1
)
echo.
echo Setup.exe 构建完成。
pause
