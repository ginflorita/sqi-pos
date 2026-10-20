@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip --isolated install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Installation complete. Open Start-POS.cmd to create your counter.
pause
exit /b 0
:failed
echo Installation failed. Check Python and internet access, then try again.
pause
exit /b 1
