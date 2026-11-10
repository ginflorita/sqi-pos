@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Create-Cashier-Shortcut.ps1"
if errorlevel 1 (
  echo.
  echo Shortcut creation did not finish. Review the message above.
  pause
  exit /b 1
)
pause
