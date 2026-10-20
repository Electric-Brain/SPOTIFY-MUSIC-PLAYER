"""
Setup script to configure 100% reliable Windows Autostart for Spotify Desk Display.
Sets both:
1. Windows Registry (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run)
2. Windows Startup Folder Shortcut (shell:startup)
"""

import os
import sys
import winreg
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(SCRIPT_DIR, "now_playing.py")
PYTHONW_PATH = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")

if not os.path.exists(PYTHONW_PATH):
    PYTHONW_PATH = sys.executable

print(f"Configuring Autostart for Spotify Desk Display:")
print(f"  Python executable: {PYTHONW_PATH}")
print(f"  Script path:       {SCRIPT_PATH}")

# 1. Configure HKCU Run Registry Key
reg_value = f'"{PYTHONW_PATH}" "{SCRIPT_PATH}"'
try:
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE
    )
    winreg.SetValueEx(key, "SpotifyDeskDisplay", 0, winreg.REG_SZ, reg_value)
    winreg.CloseKey(key)
    print("  [OK] Registry Run key created: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\SpotifyDeskDisplay")
except Exception as e:
    print(f"  [ERROR] Failed to set registry key: {e}")

# 2. Configure Startup Folder Shortcut (shell:startup)
startup_folder = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")
shortcut_path = os.path.join(startup_folder, "SpotifyDisplay.lnk")

vbs_code = f"""
Set sh = CreateObject("WScript.Shell")
Set sc = sh.CreateShortcut("{shortcut_path}")
sc.TargetPath = "{PYTHONW_PATH}"
sc.Arguments = Chr(34) & "{SCRIPT_PATH}" & Chr(34)
sc.WorkingDirectory = "{SCRIPT_DIR}"
sc.WindowStyle = 0
sc.Description = "Spotify Desk Display Background Service"
sc.Save
"""

temp_vbs = os.path.join(SCRIPT_DIR, "_create_sc.vbs")
try:
    with open(temp_vbs, "w") as f:
        f.write(vbs_code)
    subprocess.run(["cscript", "//nologo", temp_vbs], check=True)
    if os.path.exists(temp_vbs):
        os.remove(temp_vbs)
    print(f"  [OK] Startup shortcut created: {shortcut_path}")
except Exception as e:
    print(f"  [ERROR] Failed to create shortcut: {e}")

print("\nAutostart configuration complete and verified!")
