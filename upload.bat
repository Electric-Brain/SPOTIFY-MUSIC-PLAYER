@echo off
title Upload Spotify Deck Firmware
cd /d "%~dp0"
"C:\Users\Gautam\AppData\Local\Programs\Python\Python311\python.exe" -u upload_to_arduino.py
pause
