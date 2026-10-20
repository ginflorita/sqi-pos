@echo off
setlocal
cd /d "%~dp0"
call tools\Find-Python.cmd
if errorlevel 1 goto missing_python
%POS_PYTHON% %POS_PYTHON_ARGS% -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip --isolated install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Installation complete. Open Start-POS.cmd to create your counter.
pause
exit /b 0
:missing_python
pause
exit /b 1
:failed
echo Installation failed. Review the error above. Dependency downloads require internet access.
pause
exit /b 1
