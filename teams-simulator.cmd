@echo off
REM Launcher for Teams Simulator GUI - uses pythonw to avoid a console window.
REM We also redirect stdout/stderr from the launch into a fallback log on the
REM user's Desktop so that import errors / startup crashes leave a trace
REM even before Python's own FileHandler kicks in.
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
if not exist ".venv\Scripts\pythonw.exe" (
    echo .venv missing - run setup\install.ps1 first.
    pause
    exit /b 1
)

REM Resolve the log dir (mirrors logsetup.py priority).
set "LOGDIR=%TEAMS_SIMULATOR_LOG_DIR%"
if "%LOGDIR%"=="" if exist "%USERPROFILE%\Desktop" set "LOGDIR=%USERPROFILE%\Desktop\TeamsSimulatorLogs"
if "%LOGDIR%"=="" if exist "%PUBLIC%\Desktop"      set "LOGDIR=%PUBLIC%\Desktop\TeamsSimulatorLogs"
if "%LOGDIR%"=="" set "LOGDIR=%TEMP%\TeamsSimulatorLogs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" 2>nul

REM Timestamp for the fallback log.
for /f "tokens=2 delims==" %%a in ('wmic os get localdatetime /value 2^>nul') do set "TS=%%a"
if "%TS%"=="" set "TS=%RANDOM%"
set "TS=%TS:~0,8%-%TS:~8,6%"

REM start /B keeps no extra window; redirect captures any startup errors.
start "" /B "%ROOT%.venv\Scripts\pythonw.exe" -m teams_simulator 1>>"%LOGDIR%\launcher-%TS%.log" 2>&1
endlocal
