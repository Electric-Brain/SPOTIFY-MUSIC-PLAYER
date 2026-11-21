@echo off
cd /d "%~dp0"
echo Starting Spotify Display Service in background...

set "PY_EXE=C:\Users\Gautam\AppData\Local\Programs\Python\Python311\pythonw.exe"
if not exist "%PY_EXE%" set "PY_EXE=pythonw"

start "" "%PY_EXE%" "%~dp0now_playing.py"
echo Done! Service is running silently in the background.
ping 127.0.0.1 -n 2 >nul
