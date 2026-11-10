@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Setup-Host-Shortcut.ps1"
if errorlevel 1 (
  echo.
  echo Shortcut setup did not finish. Review the message above.
  pause
  exit /b 1
)
echo.
echo Setup complete. The desktop SQI POS icon opens the counter.
echo The server will start when this Windows user signs in.
pause
