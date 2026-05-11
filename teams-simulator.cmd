@echo off
REM Launcher for Teams Simulator GUI - uses pythonw to avoid a console window.
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
if not exist ".venv\Scripts\pythonw.exe" (
    echo .venv missing - run setup\install.ps1 first.
    pause
    exit /b 1
)
start "Teams Simulator" /D "%ROOT%" ".venv\Scripts\pythonw.exe" -m teams_simulator
endlocal
