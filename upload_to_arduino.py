import os
import subprocess
import sys
import time
import serial.tools.list_ports

import shutil

SKETCH_PATH = os.path.dirname(os.path.abspath(__file__))
ARDUINO_CLI = shutil.which("arduino-cli") or r"D:\Arduino\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"

def find_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    keywords = [
        "ch340", "ch341", "ch9102", "arduino", "wch", "cp210", "ftdi",
        "usb-serial", "usb serial", "silicon labs", "1a86:7523", "2341:"
    ]
    for p in ports:
        desc = (p.description or "").lower()
        mfg = (p.manufacturer or "").lower()
        hwid = (p.hwid or "").lower()
        if any(k in desc or k in mfg or k in hwid for k in keywords):
            return p.device
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if "bluetooth" in desc or "bluetooth" in hwid or "bth" in hwid:
            continue
        if "usb" in hwid or "usb" in desc:
            return p.device
    return None

def stop_running_service():
    try:
        subprocess.run(["powershell", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*now_playing.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True)
    except Exception:
        pass

def start_running_service():
    pyw = r"C:\Users\Gautam\AppData\Local\Programs\Python\Python311\pythonw.exe"
    script = os.path.join(SKETCH_PATH, "now_playing.py")
    try:
        subprocess.Popen([pyw, script], cwd=SKETCH_PATH)
    except Exception:
        pass

def main():
    print("=" * 60)
    print("   SPOTIFY DECK - ONE-CLICK AUTO COMPILE & UPLOADER")
    print("=" * 60)

    # Free COM port
    stop_running_service()
    
    # 1. Compile
    print("\n[1/2] Compiling sketch with arduino-cli...")
    res = subprocess.run([ARDUINO_CLI, "compile", "--fqbn", "arduino:avr:uno", SKETCH_PATH], capture_output=True, text=True)
    if res.returncode != 0:
        print("[ERROR] Compilation failed:")
        print(res.stderr or res.stdout)
        sys.exit(1)
    print("      [OK] Compilation successful!")

    # 2. Detect Port
    print("\n[2/2] Detecting Arduino Uno port...")
    port = find_arduino_port()
    if not port:
        print("      No Arduino Uno USB detected yet.")
        print("      --> Please plug in the Arduino Uno USB cable into your PC.")
        print("      --> Waiting for device connection (listening)...")
        while not port:
            time.sleep(1.0)
            port = find_arduino_port()
    
    print(f"      [OK] Found Arduino Uno on port: {port}")
    print(f"\n[3/3] Uploading firmware to {port}...")
    up_res = subprocess.run([ARDUINO_CLI, "upload", "-p", port, "--fqbn", "arduino:avr:uno", SKETCH_PATH], capture_output=True, text=True)
    if up_res.returncode == 0:
        print("\n" + "=" * 60)
        print(f"   [SUCCESS] Code successfully uploaded to Arduino Uno on {port}!")
        print("=" * 60)
        print("\n[+] Starting now_playing.py background service...")
        start_running_service()
        print("    Service started! Display is now live.")
    else:
        print("[ERROR] Upload failed:")
        print(up_res.stderr or up_res.stdout)
        sys.exit(1)

if __name__ == "__main__":
    main()
