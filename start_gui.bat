@echo off
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%.venv\Scripts\python.exe" (
  echo Python environment missing. Run setup.ps1 first.
  pause
  exit /b 1
)
"%ROOT%.venv\Scripts\python.exe" "%ROOT%gui.py"
if errorlevel 1 pause
