# 🎵 Spotify Hardware Desk Display & Standby Clock

An ambient, hardware-driven Spotify Now Playing display and zero-blink desk clock built with an **Arduino UNO** and a **2.4"/2.8" TFT LCD Shield (240x320)**.

Communicating over high-speed serial with a lightweight Windows background service, it renders 200x200 album cover art, live track progress, playback state, and seamlessly transitions into a sleek digital clock when music stops.

---

## ✨ Features

- 🎨 **High-Resolution 200x200 Album Art**: Direct 16-bit RGB565 streaming that maximizes screen width with vibrant colors.
- ⚡ **Instant Mid-Stream Skip Abort (`#A`)**: Zero lag when skipping songs. Image transmission cancels within <80ms, immediately drawing the next track.
- 🕒 **Zero-Blink Standby Clock**: When playback is paused or Spotify closes (after 8 seconds), the display switches to a minimalist digital clock (`6:44:24 PM` + full date `Sunday, 18 Oct`).
- 👁️ **Differential Character Rendering**: Clock updates only redraw the changing second digits. Zero full-screen clears, zero backlight flicker.
- ⏱️ **Real-Time Synchronized Progress Bar & Scrubber**: Live seconds counter and progress knob synchronized with Windows Media Controls.
- ⏸️ **Instant Freeze on Pause**: Elapsed timer stops immediately when paused, displaying a clean `PAUSED` badge without drifting.
- 🔁 **Instant Music Wake-Up**: As soon as music resumes, the screen wakes instantly from clock mode and renders the track view.
- 🚀 **Silent Windows Background Service**: Runs quietly in the background via `pythonw.exe` without cluttering your taskbar with terminal windows.
- 🔌 **Plug-and-Play Auto-Reconnect**: Unplug and reconnect the Arduino at any time; the Python service reconnects automatically.

---

## 🛠️ Components Required

| Component | Description | Quantity |
| :--- | :--- | :--- |
| **Arduino UNO R3** | Standard ATmega328P development board (or compatible clone with CH340 / ATmega16U2) | 1 |
| **2.4" or 2.8" TFT LCD Shield** | 240x320 resolution, 8-bit parallel interface (MCUFRIEND / ILI9341 / ST7789 compatible) | 1 |
| **USB Cable** | USB Type-A to Type-B cable for power and serial communication | 1 |
| **Windows PC** | Windows 10 or Windows 11 running the Spotify Desktop application | 1 |

> [!TIP]
> **No Soldering or Jumper Wires Required!**  
> The TFT LCD Shield is designed to plug directly on top of the Arduino UNO header sockets.

---

## 📐 Hardware Assembly

1. Align the header pins of the **TFT LCD Shield** with the female headers on the **Arduino UNO**.
2. Press down firmly and evenly until the shield sits flush on top of the Arduino board.
3. Connect the Arduino to your computer using the USB Type-B cable.

---

## 💻 Software Prerequisites

1. **Operating System**: Windows 10 or Windows 11 (required for native Windows Media Transport Controls).
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
5. Once uploaded, the display will show the radar boot animation and wait for connection.

### Step 4: Configure COM Port
Open [`now_playing.py`](now_playing.py) in any text editor and check line 33:
```python
PORT = "COM5"       # Change to your Arduino COM port (e.g. "COM3", "COM5"), or "AUTO"
BAUD = 115200
```
> [!NOTE]
> Setting `PORT = "AUTO"` will automatically scan and detect connected Arduino / CH340 serial ports.

### Step 5: Start the Display Service
You can test the script by running:
```bash
python now_playing.py
```
Play any song on Spotify desktop. The display will immediately render the 200x200 album cover, song title, artist, and live progress bar!

---

## 🪟 Running Silently in Background

To keep the service running silently in the background without keeping a command prompt open:

- **Start Background Service**: Double-click [`start_display.bat`](start_display.bat) or [`start_hidden.vbs`](start_hidden.vbs).
- **Stop Service**: Double-click [`stop_display.bat`](stop_display.bat).

### Start Automatically on Windows Boot
1. Press `Win + R`, type `shell:startup`, and press **Enter**.
2. Right-click [`start_hidden.vbs`](start_hidden.vbs) in this folder and select **Create shortcut**.
3. Move that shortcut into the **Startup** folder.
4. The display service will now start automatically in the background whenever you log in to Windows!

---

## 📁 Repository Structure

```text
SPOTIFY-MUSIC-PLAYER/
│
├── music_display.ino      # Arduino sketch (MCUFRIEND TFT rendering, differential clock, fast serial)
├── now_playing.py         # Python Windows Media controller & RGB565 image streamer
├── requirements.txt       # Python package dependencies
├── start_display.bat      # One-click background launcher
├── start_hidden.vbs       # Zero-window silent VBScript launcher
├── stop_display.bat       # Stops the background Python service and frees the COM port
├── .gitignore             # Git ignore file for Python and Arduino artifacts
├── LICENSE                # MIT License
└── README.md              # Project documentation
```

---

## 📡 Serial Protocol Specification

Communication runs at **115200 baud** over USB Serial.

| Command | Direction | Description |
| :--- | :--- | :--- |
| `#SONG:title\|artist\|album\|dur\|pos\|state` | Host → Arduino | Transmits new song metadata and initializes player shell. |
| `#L:row_num` + 400 bytes binary | Host → Arduino | Sends row `row_num` of 200x200 cover art in RGB565 format. |
| `K` | Arduino → Host | Acknowledge token sent after writing row to TFT GRAM. |
| `#A` | Host → Arduino | Instant abort signal. Cancels active image transfer when song skips. |
| `#T:pos:dur:state` | Host → Arduino | Live playback tick with current elapsed seconds and state (`P` or `S`). |
| `#CLOCK:time\|ampm\|date` | Host → Arduino | Standby clock update with differential digit rendering. |

---

## ❓ Troubleshooting

### 1. The display shows a white screen after uploading sketch
- Open Arduino IDE Serial Monitor or run `detect_controller` examples in `MCUFRIEND_kbv`.
- Some displays have an unconventional LCD controller ID. If `tft.readID()` returns `0x0` or `0xD3D3`, you can force the driver ID in `setup()`:
  ```cpp
  uint16_t id = tft.readID();
  if (id == 0xD3D3 || id == 0x0) id = 0x9341; // Force ILI9341 driver
  tft.begin(id);
  ```

### 2. "PermissionError" or "Access Denied" on COM port
- Ensure the Arduino IDE Serial Monitor is closed before running `now_playing.py`.
- If an older background instance is still running, double-click [`stop_display.bat`](stop_display.bat).

### 3. Display stays on Standby Clock or doesn't detect songs
- Ensure you are using the **Spotify Desktop Client** (installed from Spotify.com or Microsoft Store). Web-browser Spotify players do not always broadcast timeline metadata to Windows Media Transport Controls.
- Start playback in Spotify and ensure Windows Media Controls show the track.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) — feel free to modify, build, and use it for your own desk setups!
