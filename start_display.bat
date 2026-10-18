@echo off
echo Starting Spotify Display Service in background...
start "" pythonw "%~dp0now_playing.py"
echo Done! Service is running silently in the background.
ping 127.0.0.1 -n 2 >nul
