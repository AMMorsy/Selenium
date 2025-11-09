@echo off
setlocal
cd /d "%~dp0"

REM Prefer venv Python; fall back to system "py" if venv not found
set PY="%~dp0venv\Scripts\python.exe"
if not exist %PY% set PY=py

REM Run and keep a log
set LOGDIR="%~dp0logs"
if not exist %LOGDIR% mkdir %LOGDIR%
set LOG="%LOGDIR%\run_%DATE:~10,4%%DATE:~4,2%%DATE:~7,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%.log"
set LOG=%LOG:"=%

echo Starting... > "%LOG%"
%PY% "%~dp0downloader_selenium.py" 1>>"%LOG%" 2>&1

echo Done. See "%LOG%".
pause
