@echo off
setlocal
cd /d "%~dp0"
set "POS_ARGS=%*"
if "%~1"=="" if exist "certs\pos.crt" if exist "certs\pos.key" set "POS_ARGS=--lan --cert certs/pos.crt --key certs/pos.key"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run.py %POS_ARGS%
  if errorlevel 1 pause
  exit /b
)
call tools\Find-Python.cmd
if errorlevel 1 (
  pause
  exit /b 1
)
%POS_PYTHON% %POS_PYTHON_ARGS% run.py %POS_ARGS%
if errorlevel 1 pause
