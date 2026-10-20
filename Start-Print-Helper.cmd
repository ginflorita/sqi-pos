@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tools\print_agent.py %*
  if errorlevel 1 pause
  exit /b
)
call tools\Find-Python.cmd
if errorlevel 1 (
  pause
  exit /b 1
)
%POS_PYTHON% %POS_PYTHON_ARGS% tools\print_agent.py %*
if errorlevel 1 pause
