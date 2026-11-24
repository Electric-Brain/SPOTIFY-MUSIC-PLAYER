@echo off
cd /d "%~dp0"
echo Starting Spotify Smart Deck in background...
set "PYTHON_EXE=C:\Users\Gautam\AppData\Local\Programs\Python\Python311\pythonw.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=pythonw"

start "" "%PYTHON_EXE%" "%~dp0now_playing.py"
echo Done! Service is running silently in the background.
