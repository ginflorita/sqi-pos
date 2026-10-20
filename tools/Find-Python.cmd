@echo off
rem Check a working interpreter, not just the Microsoft Store shortcut.
set "POS_PYTHON="
set "POS_PYTHON_ARGS="
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "POS_PYTHON=python"
  exit /b 0
)
py -3.13 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "POS_PYTHON=py"
  set "POS_PYTHON_ARGS=-3.13"
  exit /b 0
)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "POS_PYTHON=py"
  set "POS_PYTHON_ARGS=-3"
  exit /b 0
)
echo.
echo Python 3.11 or newer could not be started. This POS was tested with Python 3.13.
echo Install Python from https://www.python.org/downloads/windows/
echo For the traditional installer, select Add python.exe to PATH.
echo For Python Install Manager, install a runtime with: py install 3.13
echo Close this window after installation, then run the POS command again.
echo Disabling the Microsoft Store shortcut alone does not install Python.
exit /b 1
