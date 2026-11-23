# 🎵 Spotify Smart Deck & Standby Desk Companion

An ambient, hardware-driven Spotify Now Playing display, real-time desk dashboard, and zero-blink quartz clock built with an **Arduino UNO** and a **2.4"/2.8" TFT LCD Shield (240x320)**.

Communicating over high-speed serial with an event-driven Windows background service, it renders 200x200 album cover art, live track progress, playback controls, and seamlessly transitions into a sleek digital clock when music stops or when your laptop locks/sleeps.

---

## ✨ Features

### 🎨 1. High-Resolution Music Mode
- **200x200 Full-Width Album Art**: Direct 16-bit RGB565 streaming that maximizes screen width with crisp, vibrant colors.
- **⚡ Instant Mid-Stream Skip & Pause Abort (`#A`)**: Zero lag when skipping or pausing songs. Image transmission cancels in <80ms, immediately returning control.
- **⏱️ Synchronized Progress Bar & Scrubber**: Live seconds counter and smooth progress bar synchronized with Windows Media Controls.
- **Instant Pause Transition (0s delay)**: The exact millisecond you pause Spotify, the screen flips from album art to the Main Clock Dashboard. Unpausing wakes the music player view instantly!

### 🕒 2. Smart Desk Clock & System Dashboard
- **⏱️ Autonomous Precision Quartz Clock**: Large differential digits (`9:53:12 PM` + `Monday, 23 Nov`) with autonomous hardware second-ticking on ATmega328P.
- **🔋 Live Laptop Battery Status**: Percentage bar with battery level color coding (Red <20%, Orange <50%, Green >50%) and dynamic lightning bolt ⚡ indicator when charging.
- **📶 Physical Wi-Fi State**: Accurate physical radio status: `"Off"` in dim gray when radio is disabled, `"On"` when disconnected, or active SSID (e.g., `Nothing Phone 2A`).
- **🎧 Connected Bluetooth Device**: Displays `"Off"`, `"On"`, or the name of your connected wireless headphones, earbuds, or speakers.
- **🔊 Hardware Volume Knob & On-Screen Slider**: Connect a potentiometer (10kΩ to 50kΩ) to analog pin `A5`. Smoothly controls Windows master volume (0–100%) and updates the native Windows volume flyout in real time. Features an integrated vector speaker icon with volume mute indication.

### 🔒 3. Seamless Windows Lock, Sleep & Boot Synchronization
- **Minimalist Hardware Boot Animation**: Sleek Apple/Google hardware-designer aesthetic unibody laptop icon with ambient camera dot, trackpad groove, thin macOS-style progress bar, and `SMART DECK / DESK COMPANION` typography.
- **Cold Boot & Lock Screen**: When your PC boots or is locked, the display shows a modern green lock icon, `LOCKED / ENTER PASSWORD`, and an animated scanning pulse bar.
- **Instant Unlock (<1s)**: The moment you log into Windows, the deck flashes a sleek green checkmark **`CONNECTED`** badge for 350ms, then immediately loads your clock and system telemetry.
- **Kernel-Level Session Monitoring (`WTSRegisterSessionNotification`)**: Direct OS-level hook (`WM_WTSSESSION_CHANGE`) tracks `Win + L` and password unlocks without false triggers.
- **Display Power State Monitoring (`GUID_CONSOLE_DISPLAY_STATE`)**: When your laptop display turns off due to inactivity/screen timeout or when the lid closes, the deck automatically locks itself to protect privacy.

### 💧 4. Clean Canvas & Kawaii Hydration Reminder
- **100% Clean Idle Canvas**: The notification/alert area remains completely clean and black during normal desk work.
- **Cute 30-Minute Hydration Pop-Up**: Every 30 minutes, an animated 12-second pop-up appears featuring a cute water droplet buddy with natural blinking eyes, *"HYDRATE! Time to drink water! 💧"*, and a countdown progress bar. Auto-dismisses back to pure black after 12 seconds.
- **🔔 Live Toast Notification Overrides**: Incoming Windows notifications (WhatsApp, Telegram, Slack, SMS) pop up instantly in a 10-line word-wrapped card with emoji support, overriding the card area for 16 seconds.

---

## 🛠️ Components Required

| Component | Description | Quantity |
| :--- | :--- | :--- |
| **Arduino UNO R3** | Standard ATmega328P development board (or compatible clone with CH340 / ATmega16U2) | 1 |
| **2.4" or 2.8" TFT LCD Shield** | 240x320 resolution, 8-bit parallel interface (MCUFRIEND / ILI9341 / ST7789 compatible) | 1 |
| **Potentiometer (Rotary Knob)** | 10kΩ to 50kΩ linear/log potentiometer (e.g., 47kΩ 6-pin dual-gang or 10kΩ 3-pin) *(Optional)* | 1 |
| **USB Cable** | USB Type-A to Type-B cable for power and serial communication | 1 |
| **Windows PC** | Windows 10 or Windows 11 running the Spotify Desktop application | 1 |

> [!TIP]
> **Zero Soldering!**  
> The TFT LCD Shield plugs directly on top of the Arduino UNO header sockets. If using the volume knob, only 3 jumper wires are needed.

---

## 📐 Hardware Assembly

1. Align the header pins of the **TFT LCD Shield** with the female headers on the **Arduino UNO**.
2. Press down firmly and evenly until the shield sits flush on top of the Arduino board.
3. *(Optional) Connect Volume Potentiometer*:
   - Pin 1 (Outer pin): Connect to Arduino **GND**
   - Pin 2 (Middle wiper pin): Connect to Arduino **A5**
   - Pin 3 (Outer pin): Connect to Arduino **5V**
   *(Note: For 6-pin dual-gang potentiometers, simply use one row of 3 pins).*
4. Connect the Arduino to your computer using the USB Type-B cable.

---

## 💻 Software Prerequisites

1. **Operating System**: Windows 10 or Windows 11 (required for WinRT and native Windows Media Transport Controls).
2. **Python**: Python 3.10 or higher. Make sure *"Add python.exe to PATH"* is checked during installation.
3. **Spotify Desktop App**: The official Spotify desktop client for Windows.
4. **Arduino IDE**: Version 1.8.x or 2.x to flash the microcontroller.

---

## 📦 Arduino Libraries Setup

Open **Arduino IDE** and install the following libraries via **Tools** → **Manage Libraries...**:

1. **`MCUFRIEND_kbv`** (by David Prentice) — version 3.0.0 or higher.
2. **`Adafruit GFX Library`** (by Adafruit) — version 1.12.0 or higher.
3. **`Adafruit BusIO`** (by Adafruit) — required dependency for Adafruit GFX.

---

## 🚀 Quick Start Guide

### Step 1: Clone the Repository
```bash
git clone https://github.com/Electric-Brain/SPOTIFY-MUSIC-PLAYER.git
cd SPOTIFY-MUSIC-PLAYER
```

### Step 2: Install Python Dependencies
Open PowerShell or Command Prompt in the repository folder:
```bash
pip install -r requirements.txt
```

### Step 3: Flash the Arduino Sketch
1. Open [`music_display.ino`](music_display.ino) in the Arduino IDE.
2. Select your board: **Tools** → **Board** → **Arduino AVR Boards** → **Arduino Uno**.
3. Select your port: **Tools** → **Port** → `COMx` (e.g., `COM5`).
4. Click **Upload** (Ctrl + U).
5. Once uploaded, the display will play the sleek unibody boot animation and settle into locked standby mode.

### Step 4: Configure COM Port (Optional)
Open [`now_playing.py`](now_playing.py) in any text editor:
```python
PORT = "AUTO"       # Automatically detects Arduino / CH340 COM ports, or set to e.g. "COM5"
BAUD = 115200
```

### Step 5: Start the Display Service
You can test the script by running:
```bash
python now_playing.py
```
Play any song on Spotify desktop. The display will immediately render the 200x200 album cover, song title, artist, and live progress bar!

---

## 🪟 Windows Background Auto-Start

To have the Smart Deck start automatically in the background whenever your PC turns on or you log into Windows:

### Recommended: Windows Task Scheduler (100% Reliable)
Windows 11 can throttle or delay classic Startup folder shortcuts. Windows Task Scheduler launches `pythonw.exe` in <100ms with zero terminal windows:

Open PowerShell as Administrator and run:
```powershell
$action = New-ScheduledTaskAction -Execute "C:\Users\YOUR_USERNAME\AppData\Local\Programs\Python\Python311\pythonw.exe" -Argument "C:\path\to\music_display\now_playing.py" -WorkingDirectory "C:\path\to\music_display"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -Priority 4
Register-ScheduledTask -TaskName "SpotifyDeskDisplay" -Action $action -Trigger $trigger -Settings $settings -Force
```

---

## 📁 Repository Structure

```text
SPOTIFY-MUSIC-PLAYER/
│
├── music_display.ino      # Arduino sketch (MCUFRIEND TFT rendering, sleek UI, live quartz clock)
├── now_playing.py         # Python Windows Media controller, power/lock monitor & RGB565 streamer
├── requirements.txt       # Python package dependencies (winrt, pycaw, pyserial, pillow)
├── start_display.bat      # One-click manual background launcher
├── start_hidden.vbs       # Zero-window silent VBScript launcher
├── stop_display.bat       # Stops the background service and frees the serial COM port
├── .gitignore             # Git ignore file for Python and Arduino artifacts
├── LICENSE                # MIT License
└── README.md              # Project documentation
```

---

## 📡 Serial Protocol Specification

Communication runs at **115200 baud** over USB Serial.

| Command | Direction | Description |
| :--- | :--- | :--- |
| `#SONG:title\|artist\|album\|dur\|pos\|state` | Host → Arduino | Transmits new song metadata and switches to Music Mode. |
| `#L:row_num` + 400 bytes binary | Host → Arduino | Sends row `row_num` of 200x200 cover art in RGB565 format. |
| `K` | Arduino → Host | Acknowledge token sent after writing row to TFT GRAM. |
| `#A` | Host → Arduino | Instant abort signal. Cancels active image transfer when song skips or pauses. |
| `#T:pos:dur:state` | Host → Arduino | Live playback tick with current elapsed seconds and state (`P` or `S`). |
| `#CLOCK:time\|ampm\|date` | Host → Arduino | Standby clock update with differential digit rendering. |
| `#SYS:batt\|chg\|wifi\|bt` | Host → Arduino | System telemetry: Battery %, Charging flag, Wi-Fi SSID, BT device. |
| `#NOTIF:app\|msg` | Host → Arduino | Live toast notification popup banner on standby screen. |
| `#VOL:<0-100>` | Arduino → Host | Real-time potentiometer volume percentage (0–100%) when turned. |
| `#LOCK` | Host → Arduino | Switches display to `LOCKED / ENTER PASSWORD` lock screen. |
| `#UNLOCK` | Host → Arduino | Shows green `CONNECTED` checkmark banner (350ms) and unlocks dashboard. |
| `#READY` | Arduino → Host | Handshake sent by Arduino upon completing boot sequence. |

---

## ❓ Troubleshooting

### 1. The display shows a white screen after uploading sketch
- Open Arduino IDE Serial Monitor or run `detect_controller` examples in `MCUFRIEND_kbv`.
- Some displays have an unconventional LCD controller ID. If `tft.readID()` returns `0x0` or `0xD3D3`, force the driver ID in `setup()`:
  ```cpp
  uint16_t id = tft.readID();
  if (id == 0xD3D3 || id == 0x0) id = 0x9341; // Force ILI9341 driver
  tft.begin(id);
  ```

### 2. "PermissionError" or "Access Denied" on COM port
- Ensure the Arduino IDE Serial Monitor is closed before running `now_playing.py`.
- If an older background instance is still running, double-click [`stop_display.bat`](stop_display.bat) or terminate `pythonw.exe`.

### 3. Display stays on Standby Clock or doesn't detect songs
- Ensure you are using the **Spotify Desktop Client** (installed from Spotify.com or Microsoft Store). Web-browser Spotify players do not always broadcast timeline metadata to Windows Media Transport Controls.
- Start playback in Spotify and ensure Windows Media Controls show the track.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) — feel free to modify, build, and use it for your own desk setups!
