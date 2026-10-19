@echo off
rem One hourly tick of the weekly team cleanup's autopilot (scripts\team_cleanup\advance.py).
rem The scheduled task runs a copy of this file kept in the run store: a tick may move
rem C:\pitchrank-weekly, this file's own checkout, to newer code while cmd.exe is still reading it.
rem Argument 1 is the Python to run, which register_team_cleanup.ps1 records.
setlocal
set PYTHONUTF8=1
set PY=%~1
if "%PY%"=="" set PY=python
set STORE=%USERPROFILE%\pitchrank-cleanup-runs
set LOG=%STORE%\logs\advance.log
if not exist "%STORE%\logs" mkdir "%STORE%\logs"
cd /d C:\pitchrank-weekly || exit /b 1
echo ==== %DATE% %TIME% >> "%LOG%"
"%PY%" -m dotenv -f C:\PitchRank\.env run -- "%PY%" scripts\team_cleanup\advance.py --execute --pin-code >> "%LOG%" 2>&1
set CODE=%ERRORLEVEL%
echo ==== exit %CODE% >> "%LOG%"
exit /b %CODE%
