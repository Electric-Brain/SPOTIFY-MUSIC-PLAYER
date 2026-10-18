@echo off
echo Stopping Spotify Display Service...
taskkill /F /IM pythonw.exe >nul 2>&1
echo Done! Display service stopped and COM port released.
ping 127.0.0.1 -n 2 >nul
