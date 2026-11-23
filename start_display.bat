@echo off
cd /d "%~dp0"
echo Starting Spotify Smart Deck in background...
start "" pythonw now_playing.py
if %ERRORLEVEL% NEQ 0 (
    start "" python now_playing.py
)
echo Done! Service is running silently in the background.
timeout /t 2 >nul
