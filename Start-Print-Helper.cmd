@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tools\print_agent.py %*
) else (
  python tools\print_agent.py %*
)
if errorlevel 1 pause
