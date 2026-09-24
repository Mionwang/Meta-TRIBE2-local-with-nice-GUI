@echo off
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%.venv\Scripts\python.exe" (echo Run setup.ps1 first.& pause& exit /b 1)
"%ROOT%.venv\Scripts\python.exe" "%ROOT%diagnostics.py"
pause
