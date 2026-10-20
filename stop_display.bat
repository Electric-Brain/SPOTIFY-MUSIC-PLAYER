@echo off
echo Stopping Spotify Display Service...
taskkill /F /IM pythonw.exe >nul 2>&1
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*now_playing.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo Done! Display service stopped and COM port released.
ping 127.0.0.1 -n 2 >nul
