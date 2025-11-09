@echo off
pushd "E:\onmeeting-downloader"
rem ensure no leftover Chrome locks
taskkill /F /IM chrome.exe /T >nul 2>&1
taskkill /F /IM chromedriver.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

rem run your EXE and capture output to a log
"E:\onmeeting-downloader\OnMeetingDownloader.exe" 1> "E:\onmeeting-downloader\tasklog.txt" 2>&1
