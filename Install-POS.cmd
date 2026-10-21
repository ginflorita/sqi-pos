@echo off
setlocal
cd /d "%~dp0"
if exist "installers\python-3.13.16-amd64.exe" if exist "wheelhouse\*.whl" goto find_offline_python
call tools\Find-Python.cmd
if errorlevel 1 goto install_bundled_python
:python_ready
%POS_PYTHON% %POS_PYTHON_ARGS% -m venv .venv
if errorlevel 1 goto failed
if exist "wheelhouse\*.whl" (
  echo Installing bundled Python packages offline...
  ".venv\Scripts\python.exe" -m pip --isolated install --no-index --find-links "%~dp0wheelhouse" -r requirements.txt
) else (
  echo Downloading Python packages...
  ".venv\Scripts\python.exe" -m pip --isolated install -r requirements.txt
)
if errorlevel 1 goto failed
echo.
echo Installation complete. Open Start-POS.cmd to create your counter.
pause
exit /b 0
:find_offline_python
call tools\Find-Python.cmd
if not errorlevel 1 (
  %POS_PYTHON% %POS_PYTHON_ARGS% -c "import sys; sys.exit(0 if sys.version_info[:2] == (3,13) else 1)" >nul 2>&1
  if not errorlevel 1 goto python_ready
)
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
  set "POS_PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
  set "POS_PYTHON_ARGS="
  goto python_ready
)
goto install_bundled_python
:install_bundled_python
if not exist "installers\python-3.13.16-amd64.exe" goto missing_python
echo.
echo Python is not installed. Starting the bundled official Python installer...
echo This installs Python for the current Windows user and does not require internet.
start "Python installer" /wait "installers\python-3.13.16-amd64.exe" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_test=0
if errorlevel 1 goto python_install_failed
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
  set "POS_PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
  set "POS_PYTHON_ARGS="
  goto python_ready
)
call tools\Find-Python.cmd
if not errorlevel 1 goto python_ready
goto python_install_failed
:missing_python
echo No bundled Python installer was found. Install Python 3.11 or newer, then run this file again.
pause
exit /b 1
:python_install_failed
echo Python installation did not finish. Review the installer message, restart Windows if requested, then run Install-POS.cmd again.
pause
exit /b 1
:failed
echo Installation failed. Review the error above.
pause
exit /b 1
