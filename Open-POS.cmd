@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Open-POS.ps1" %*
if errorlevel 1 (
  echo.
  echo SQI POS could not open. Show this window to the person who set up the main laptop.
  pause
  exit /b 1
)
