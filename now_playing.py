# ============================================================================
#   SPOTIFY 200x200 NOW PLAYING DISPLAY SENDER (WITH STANDBY CLOCK MODE)
# ============================================================================
# Features:
#   - High-Res 200x200 Album Cover Art Streamer (Full portrait utilization).
#   - Instant Mid-Stream Abort (#A): Cancels image in <80ms if song is skipped.
#   - Standby Clock Mode: Minimalist Digital Clock (5:19:22 PM) when idle/paused.
#   - Frozen timer when paused (zero phantom increments).
#   - Instant wake-up when music starts playing.
#   - Auto-Reconnect: Robust plug-and-play background service.
# ============================================================================

import asyncio
import concurrent.futures
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import io
import os
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata

# Ensure safe stdout/stderr when running as background service via pythonw.exe
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_run.log")
_log_fp = None
try:
    _log_fp = open(log_file_path, "a", encoding="utf-8")
    sys.stdout = _log_fp
    sys.stderr = _log_fp
except Exception:
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()

def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    if _log_fp:
        try:
            _log_fp.write(formatted + "\n")
            _log_fp.flush()
        except Exception:
            pass

from PIL import Image, ImageEnhance
import comtypes
from pycaw.pycaw import AudioUtilities, IMMDeviceEnumerator, IAudioEndpointVolume
from pycaw.constants import CLSID_MMDeviceEnumerator, EDataFlow, ERole
import serial
import serial.tools.list_ports

# Suppress benign CH340 driver Error 31 on Windows when reconfiguring COM port DCB
try:
    from serial.serialwin32 import Serial as Win32Serial
    _orig_reconfig = Win32Serial._reconfigure_port
    def _safe_reconfig(self):
        try:
            _orig_reconfig(self)
        except serial.SerialException as ex:
            if "31" in str(ex):
                log("Note: Suppressed benign CH340 DCB Error 31 during port reconfigure")
            else:
                raise
    Win32Serial._reconfigure_port = _safe_reconfig
except Exception:
    pass
from winrt.windows.devices.radios import Radio, RadioKind, RadioState
from winrt.windows.devices.bluetooth import BluetoothDevice, BluetoothLEDevice, BluetoothConnectionStatus
from winrt.windows.devices.enumeration import DeviceInformation
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlayStatus,
)
from winrt.windows.storage.streams import DataReader
from winrt.windows.ui.notifications.management import (
    UserNotificationListener,
    UserNotificationListenerAccessStatus,
)
from winrt.windows.ui.notifications import NotificationKinds

PORT = "AUTO"       # Arduino Port (e.g. "COM3", "COM5", "COM7"), or "AUTO" to auto-detect any port
BAUD = 115200
ART_SIZE = 200      # 200x200 Cover Art (Maximized Screen Width)

_single_instance_mutex = None

def acquire_single_instance_lock(name: str = "Global\\SpotifyDeskDisplay_Lock"):
    """Prevents multiple concurrent instances of now_playing.py from running."""
    global _single_instance_mutex
    mutex = ctypes.windll.kernel32.CreateMutexW(None, True, name)
    ERROR_ALREADY_EXISTS = 183
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    _single_instance_mutex = mutex
    return mutex


# ═══════════════════════════════════════════════════════════════════
#   BATTERY, WIFI, BLUETOOTH & NOTIFICATION COLLECTORS
# ═══════════════════════════════════════════════════════════════════

class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ('ACLineStatus', ctypes.c_byte),
        ('BatteryFlag', ctypes.c_byte),
        ('BatteryLifePercent', ctypes.c_byte),
        ('SystemStatusFlag', ctypes.c_byte),
        ('BatteryLifeTime', ctypes.c_ulong),
        ('BatteryFullLifeTime', ctypes.c_ulong),
    ]


def get_battery_info() -> tuple[int, int]:
    """Returns (percent, is_charging)."""
    status = SYSTEM_POWER_STATUS()
    if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        pct = int(status.BatteryLifePercent)
        if pct < 0 or pct > 100:
            pct = 100
        chg = 1 if status.ACLineStatus == 1 else 0
        return pct, chg
    return 100, 0


_cached_wifi: str = ""
_wifi_last_check: float = 0.0


async def get_wifi_status() -> str:
    global _cached_wifi, _wifi_last_check
    now = time.time()
    if now - _wifi_last_check < 4.0 and _cached_wifi:
        return _cached_wifi
    _wifi_last_check = now

    try:
        radios = await Radio.get_radios_async()
        wifi_r = next((r for r in radios if r.kind == RadioKind.WI_FI), None)
        if wifi_r and wifi_r.state != RadioState.ON:
            _cached_wifi = "Off"
            return _cached_wifi
    except Exception:
        pass

    try:
        out = await asyncio.to_thread(
            subprocess.check_output,
            ["netsh", "wlan", "show", "interfaces"],
            creationflags=0x08000000,
            text=True,
            timeout=1.5,
        )
        m = re.search(r'^\s*SSID\s*:\s*(.+)$', out, re.MULTILINE)
        if m:
            s = m.group(1).strip()
            if s:
                _cached_wifi = clean(s, 16)
                return _cached_wifi
        st = re.search(r'^\s*State\s*:\s*(.+)$', out, re.MULTILINE)
        if st and "disconnected" in st.group(1).lower():
            _cached_wifi = "On"
            return _cached_wifi
    except Exception:
        pass
    _cached_wifi = "On"
    return _cached_wifi


_cached_bt: str = "Off"
_bt_last_check: float = 0.0


async def get_bluetooth_device() -> str:
    global _cached_bt, _bt_last_check
    now = time.time()
    if now - _bt_last_check < 3.0:
        return _cached_bt
    _bt_last_check = now

    try:
        radios = await Radio.get_radios_async()
        bt_r = next((r for r in radios if r.kind == RadioKind.BLUETOOTH), None)
        if bt_r and bt_r.state != RadioState.ON:
            _cached_bt = "Off"
            return _cached_bt
    except Exception:
        pass

    try:
        selector = BluetoothDevice.get_device_selector_from_connection_status(BluetoothConnectionStatus.CONNECTED)
        devices = await DeviceInformation.find_all_async_aqs_filter(selector)
        for d in devices:
            if not d.name:
                continue
            # 1. Classic Bluetooth device verification (speakers, headphones, etc.)
            try:
                bd = await BluetoothDevice.from_id_async(d.id)
                if bd and bd.connection_status == BluetoothConnectionStatus.CONNECTED:
                    _cached_bt = clean(bd.name or d.name, 16)
                    return _cached_bt
            except Exception:
                pass

            # 2. Bluetooth LE device verification (smartwatches, buds, etc.)
            try:
                ble = await BluetoothLEDevice.from_id_async(d.id)
                if ble and ble.connection_status == BluetoothConnectionStatus.CONNECTED:
                    _cached_bt = clean(ble.name or d.name, 16)
                    return _cached_bt
            except Exception:
                pass
    except Exception:
        pass
    _cached_bt = "On"
    return _cached_bt


async def init_notification_listener():
    try:
        listener = UserNotificationListener.current
        status = await listener.request_access_async()
        if status == UserNotificationListenerAccessStatus.ALLOWED:
            notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
            last_id = notifs[len(notifs) - 1].id if len(notifs) > 0 else 0
            return listener, last_id
    except Exception:
        pass
    return None, 0


EMOJI_DICT = {
    # Faces & Reactions
    '😊': ':)', '🙂': ':)', '😀': ':)', '😃': ':)', '😄': ':)', '😺': ':)', '😸': ':)',
    '😉': ';)', '😏': ';)',
    '😂': ':D', '🤣': ':D', '😆': ':D',
    '😍': '<3', '🥰': '<3', '😘': '<3', '😚': '<3',
    '😋': ':P', '😜': ':P', '😝': ':P', '😛': ':P',
    '😎': 'B)',
    '😢': ':(', '😭': ':(', '😿': ':(', '🥺': ':(', '😞': ':(', '😔': ':(', '😟': ':(', '🙁': ':(', '☹️': ':(', '☹': ':(',
    '😠': '>:(', '😡': '>:(', '🤬': '>:(', '👿': '>:(', '😈': '>:(',
    '😱': '[shock]', '😨': '[shock]', '😰': '[shock]', '😳': '[flushed]',
    '🤔': '[thinking]', '🧐': '[thinking]',
    '🤫': '[shh]', '🤐': '[quiet]',
    '😴': '[zzz]', '😪': '[zzz]', '💤': '[zzz]',
    '💀': '[skull]', '☠️': '[skull]', '☠': '[skull]',
    '👻': '[ghost]', '🤡': '[clown]',
    
    # Hearts
    '❤️': '<3', '❤': '<3', '🧡': '<3', '💛': '<3', '💚': '<3', '💙': '<3',
    '💜': '<3', '🖤': '<3', '🤍': '<3', '🤎': '<3', '💔': '<3', '❣️': '<3',
    '💕': '<3', '💞': '<3', '💓': '<3', '💗': '<3', '💖': '<3', '💘': '<3', '💝': '<3',
    
    # Hand gestures
    '👍': '(y)', '👎': '(n)', '👌': '[ok]', '✌️': '[peace]', '✌': '[peace]',
    '🤞': '[crossed]', '🤙': '[call]', '👏': '[clap]', '🙌': '[yay]',
    '🙏': '[pray]', '🤝': '[handshake]', '💪': '[strong]', '👊': '[fist]',
    '👋': '[wave]', '🖐️': '[hand]', '🖐': '[hand]', '✋': '[stop]',
    
    # Symbols & objects
    '🔥': '[fire]', '💯': '[100]', '🎉': '[party]', '🎊': '[party]', '🥳': '[party]',
    '✨': '*', '⭐': '*', '🌟': '*', '💫': '*',
    '🎂': '[cake]', '🍰': '[cake]', '☕': '[coffee]', '🍺': '[beer]', '🍻': '[cheers]',
    '🍷': '[wine]', '🍾': '[cheers]', '🍕': '[food]', '🍔': '[food]', '🍟': '[food]',
    '🍲': '[food]', '🍜': '[food]', '🥗': '[food]',
    '📞': '[call]', '☎️': '[call]', '☎': '[call]', '📲': '[phone]', '📱': '[phone]',
    '💬': '[msg]', '🗨️': '[msg]', '🗨': '[msg]', '📸': '[photo]', '📷': '[photo]',
    '🎥': '[video]', '📹': '[video]', '🎵': '♫', '🎶': '♫', '📍': '[loc]', '📌': '[pin]',
    '⏰': '[time]', '⏱️': '[time]', '⏳': '[time]', '⌛': '[time]',
    '⚠️': '[!]', '✅': '[ok]', '✔️': '[ok]', '❌': '[x]', '✖️': '[x]', '✖': '[x]',
    '❓': '?', '❔': '?', '❗': '!', '❕': '!', '💰': '[money]', '💵': '[money]',
    '🚗': '[car]', '🚕': '[car]', '🏎️': '[car]', '🏍️': '[bike]', '🛵': '[bike]',
    '🚲': '[cycle]', '✈️': '[flight]', '✈': '[flight]', '🏠': '[home]', '🏡': '[home]',
    '👀': '[eyes]', '📄': '[doc]', '📝': '[note]', '💡': '[idea]'
}

SKIN_TONES = ['\U0001F3FB', '\U0001F3FC', '\U0001F3FD', '\U0001F3FE', '\U0001F3FF']

def format_notification_text(text: str, max_len: int = 240) -> str:
    if not text:
        return ''
    for tone in SKIN_TONES:
        text = text.replace(tone, '')
    for emo, rep in EMOJI_DICT.items():
        text = text.replace(emo, rep)
    text = text.replace('\ufe0f', '').replace('\u200d', '')
    
    res = []
    for ch in text:
        code = ord(ch)
        if (0x1F000 <= code <= 0x1FFFF) or (0x2600 <= code <= 0x27BF):
            try:
                name = unicodedata.name(ch, '')
                words = name.split()
                short = words[-1].lower() if words else 'emoji'
                res.append(f'[{short}]')
            except Exception:
                pass
        else:
            res.append(ch)
    cleaned = ''.join(res)
    
    replacements = {
        '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
        '\u2013': '-', '\u2014': '-', '\u2026': '...', '\u2022': '*',
        '\u00b7': '*', '\u20b9': 'Rs ', '|': '/'
    }
    for k, v in replacements.items():
        cleaned = cleaned.replace(k, v)
        
    cleaned = cleaned.replace('\r', ' ').replace('\n', ' ')
    cleaned = re.sub(r' {2,}', ' ', cleaned).strip()
    return cleaned.encode('ascii', 'ignore').decode()[:max_len]

def clean(s: str, n: int = 36) -> str:
    return format_notification_text(s, max_len=n)


async def check_new_notification(listener, last_id: int) -> tuple[int, str, str] | None:
    if not listener:
        return None
    try:
        notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
        cnt = len(notifs)
        if cnt > 0:
            latest = notifs[cnt - 1]
            if latest.id > last_id:
                app_name = "Notification"
                try:
                    if latest.app_info and latest.app_info.display_info and latest.app_info.display_info.display_name:
                        app_name = latest.app_info.display_info.display_name.strip()
                except Exception:
                    pass

                header = app_name
                msg = ""
                try:
                    b = latest.notification.visual.get_binding("ToastGeneric")
                    if b:
                        elems = list(b.get_text_elements())
                        raw_texts = [e.text.strip() for e in elems if e.text and e.text.strip()]
                        if len(raw_texts) == 1:
                            msg = raw_texts[0]
                        elif len(raw_texts) >= 2:
                            sender = raw_texts[0]
                            msg = " - ".join(raw_texts[1:])
                            if "phone" in app_name.lower() or "link" in app_name.lower():
                                # For Phone Link: put contact/sender name directly in header!
                                header = sender if sender else app_name
                            else:
                                if sender and sender.lower() != app_name.lower():
                                    header = sender if len(sender) <= 15 else app_name
                except Exception:
                    pass

                clean_header = clean(header, 15)
                clean_msg = format_notification_text(msg, 240)
                if clean_msg:
                    return latest.id, clean_header, clean_msg
    except Exception:
        pass
    return None


async def telemetry_background_worker(notif_listener, state_tracker: dict):
    """Background worker that continuously refreshes battery, Wi-Fi, Bluetooth, and notifications."""
    while state_tracker.get("running", True):
        try:
            if state_tracker.get("clock_mode", False):
                # 1. Instant Battery query (ctypes)
                pct, chg = get_battery_info()
                state_tracker["battery_pct"] = pct
                state_tracker["charging"] = chg

                # 2. Async Wi-Fi query (checked with Radio state & netsh)
                wifi = await get_wifi_status()
                state_tracker["wifi"] = wifi

                # 3. Bluetooth query (WinRT async)
                bt = await get_bluetooth_device()
                state_tracker["bt"] = bt

                # 4. Check for toast notifications (WinRT, runs in background without blocking clock)
                if notif_listener:
                    new_notif = await check_new_notification(notif_listener, state_tracker.get("last_notif_id", 0))
                    if new_notif:
                        nid, napp, nmsg = new_notif
                        state_tracker["last_notif_id"] = nid
                        state_tracker["pending_notif"] = (napp, nmsg)
        except Exception:
            pass

        await asyncio.sleep(2.0)


def safe_write(ser: serial.Serial, data: bytes) -> bool:
    """Safe serial writer that catches timeouts and transient write errors without crashing."""
    if not ser or not ser.is_open:
        return False
    try:
        ser.write(data)
        return True
    except (serial.SerialTimeoutException, serial.SerialException, OSError, PermissionError) as e:
        log(f"Serial write error: {e} -> closing port to trigger auto-reconnect")
        try:
            ser.close()
        except Exception:
            pass
        return False


def send_clock_dashboard(ser: serial.Serial, state_tracker: dict):
    """Dispatches the live second clock tick, system telemetry, and notifications in <0.1ms."""
    global _last_applied_vol, _last_applied_time
    now = datetime.now()
    t_str = f"{now.hour % 12 or 12:2d}:{now.minute:02d}:{now.second:02d}"
    ampm  = now.strftime("%p")
    d_str = now.strftime("%A, %d %b")
    safe_write(ser, f"#CLOCK:{t_str}|{ampm}|{d_str}\n".encode("ascii"))

    cur_time = time.time()
    pct  = state_tracker.get("battery_pct", 100)
    chg  = state_tracker.get("charging", 0)
    wifi = state_tracker.get("wifi", "Disconnected")
    bt   = state_tracker.get("bt", "None")
    sys_state = f"{pct}|{chg}|{wifi}|{bt}"

    if sys_state != state_tracker.get("last_sys_state", "") or (cur_time - state_tracker.get("last_sys_sent", 0) >= 5.0):
        safe_write(ser, f"#SYS:{sys_state}\n".encode("ascii"))
        state_tracker["last_sys_state"] = sys_state
        state_tracker["last_sys_sent"] = cur_time

    if state_tracker.get("pending_notif"):
        napp, nmsg = state_tracker["pending_notif"]
        state_tracker["pending_notif"] = None
        safe_write(ser, f"#NOTIF:{napp}|{nmsg}\n".encode("ascii"))
        log(f"Notification sent to display: [{napp}] {nmsg}")

    # Sync system volume to Arduino clock mode ONLY if changed independently from Windows side
    ep = get_audio_endpoint()
    if ep:
        try:
            cur_vol = round(ep.GetMasterVolumeLevelScalar() * 100)
            if cur_vol != state_tracker.get("last_synced_vol", -1):
                state_tracker["last_synced_vol"] = cur_vol
                # Only sync to Arduino if pot hasn't moved in >3.0s and changed by >=3% to avoid feedback jitter
                if time.time() - _last_applied_time > 3.0 and abs(cur_vol - _last_applied_vol) >= 3:
                    _last_applied_vol = cur_vol
                    ser.write(f"#VOL:{cur_vol}\n".encode("ascii"))
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
#   HARDWARE VOLUME CONTROLLER & POPUP TRIGGER (PIN A5 -> WINDOWS)
# ═══════════════════════════════════════════════════════════════════

VK_VOLUME_UP   = 0xAF
VK_VOLUME_DOWN = 0xAE
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP       = 0x0002

_device_enumerator = None

def get_audio_endpoint():
    """Returns the live active default multimedia audio endpoint (auto-adapts when headphones/BT connect)."""
    global _device_enumerator
    try:
        if _device_enumerator is None:
            _device_enumerator = comtypes.CoCreateInstance(
                CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER
            )
        device = _device_enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eMultimedia.value)
        endpoint = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_INPROC_SERVER, None)
        return endpoint.QueryInterface(IAudioEndpointVolume)
    except Exception:
        _device_enumerator = None
        try:
            sp = AudioUtilities.GetSpeakers()
            return sp.EndpointVolume if sp else None
        except Exception:
            return None


_last_applied_vol = -1
_last_applied_time = 0.0

_vol_key_queue: queue.Queue = queue.Queue()


def _desktop_input_worker():
    """Dedicated background thread that attaches to the interactive 'Default' desktop
    and triggers the native Windows volume popup (OSD) and sets the exact active volume."""
    try:
        ctypes.windll.ole32.CoInitialize(None)
    except Exception:
        pass

    try:
        hdesk = ctypes.windll.user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(hdesk)
    except Exception:
        pass

    worker_enumerator = None
    try:
        worker_enumerator = comtypes.CoCreateInstance(
            CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER
        )
    except Exception:
        worker_enumerator = None

    def _get_worker_ep():
        nonlocal worker_enumerator
        try:
            if worker_enumerator is None:
                worker_enumerator = comtypes.CoCreateInstance(
                    CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER
                )
            device = worker_enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eMultimedia.value)
            endpoint = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_INPROC_SERVER, None)
            return endpoint.QueryInterface(IAudioEndpointVolume)
        except Exception:
            worker_enumerator = None
            try:
                sp = AudioUtilities.GetSpeakers()
                return sp.EndpointVolume if sp else None
            except Exception:
                return None

    user32 = ctypes.windll.user32
    while True:
        try:
            item = _vol_key_queue.get()
            if item is None:
                break
            # Rapid knob movement: drop intermediate events and keep only the freshest direction & scalar
            while not _vol_key_queue.empty():
                try:
                    item = _vol_key_queue.get_nowait()
                    _vol_key_queue.task_done()
                except queue.Empty:
                    break

            vk, scan, scalar = item
            # Extended key event triggers Windows Shell volume popup
            user32.keybd_event(vk, scan, KEYEVENTF_EXTENDEDKEY, 0)
            time.sleep(0.002)
            user32.keybd_event(vk, scan, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
            time.sleep(0.010)
            # Re-assert exact scalar level on the currently active default endpoint (0-100% exact match)
            ep = _get_worker_ep()
            if ep:
                ep.SetMasterVolumeLevelScalar(scalar, None)
            _vol_key_queue.task_done()
        except Exception:
            pass


# Start dedicated desktop input thread immediately as a daemon
_input_thread = threading.Thread(target=_desktop_input_worker, daemon=True, name="DesktopInputWorker")
_input_thread.start()


def init_volume():
    """Initializes the cached volume state from Windows Master Volume on boot."""
    global _last_applied_vol
    ep = get_audio_endpoint()
    if ep:
        try:
            _last_applied_vol = round(ep.GetMasterVolumeLevelScalar() * 100)
        except Exception:
            _last_applied_vol = -1


def set_system_volume(vol_pct: int):
    """Sets master volume (0-100%) and triggers the live native Windows volume popup (OSD)."""
    global _last_applied_vol, _last_applied_time
    vol_pct = max(0, min(100, vol_pct))
    if vol_pct == _last_applied_vol:
        return
    prev_vol = _last_applied_vol
    _last_applied_vol = vol_pct
    _last_applied_time = time.time()

    scalar = vol_pct / 100.0
    ep = get_audio_endpoint()
    if ep:
        try:
            ep.SetMasterVolumeLevelScalar(scalar, None)
        except Exception:
            pass

    # Trigger native Windows Volume Flyout in matching direction
    if prev_vol < 0:
        vk = VK_VOLUME_UP if vol_pct >= 50 else VK_VOLUME_DOWN
        scan = 0x30 if vol_pct >= 50 else 0x2E
    else:
        if vol_pct >= prev_vol:
            vk = VK_VOLUME_UP
            scan = 0x30
        else:
            vk = VK_VOLUME_DOWN
            scan = 0x2E

    _vol_key_queue.put((vk, scan, scalar))


async def serial_reader_worker(ser: serial.Serial, state_tracker: dict):
    """Continuously reads incoming serial lines from Arduino (e.g. #VOL:45) with <15ms latency."""
    buffer = ""
    while state_tracker.get("running", True):
        try:
            # During cover streaming, let send_cover_async have exclusive access to ser.read
            if state_tracker.get("streaming_cover", False):
                await asyncio.sleep(0.04)
                continue

            if ser.is_open and ser.in_waiting > 0:
                raw = ser.read(ser.in_waiting).decode("ascii", errors="ignore")
                buffer += raw
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line.startswith("#VOL:"):
                        try:
                            vol = int(line[5:])
                            set_system_volume(vol)
                        except ValueError:
                            pass
                    elif line == "#READY":
                        log("Arduino sent #READY handshake")
                        state_tracker["force_track_refresh"] = True
                        if not is_workstation_locked():
                            try:
                                ser.write(b"#UNLOCK\n")
                                log("Workstation unlocked -> sent #UNLOCK on #READY")
                            except Exception:
                                pass
                        else:
                            try:
                                ser.write(b"#LOCK\n")
                                log("Workstation is locked -> sent #LOCK on #READY")
                            except Exception:
                                pass
        except (serial.SerialException, OSError, PermissionError) as e:
            log(f"Serial reader disconnected or error: {e}")
            try:
                ser.close()
            except Exception:
                pass
            break
        except Exception:
            pass
        await asyncio.sleep(0.015)


# ═══════════════════════════════════════════════════════════════════
#   WINDOWS WORKSTATION LOCK / UNLOCK & DISPLAY STATE MONITOR
# ═══════════════════════════════════════════════════════════════════

_session_locked = False
_display_off = False
_session_monitor_started = False

user32 = ctypes.windll.user32
wtsapi32 = ctypes.windll.wtsapi32
kernel32 = ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID
]
user32.CreateWindowExW.restype = wintypes.HWND

class GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', wintypes.DWORD),
        ('Data2', wintypes.WORD),
        ('Data3', wintypes.WORD),
        ('Data4', ctypes.c_byte * 8)
    ]

# GUID_CONSOLE_DISPLAY_STATE: da396341-524d-41e8-a92d-7201e8ce458a
GUID_CONSOLE_DISPLAY_STATE = GUID(
    0xda396341, 0x524d, 0x41e8,
    (ctypes.c_byte * 8)(0xa9, 0x2d, 0x72, 0x01, 0xe8, 0xce, 0x45, 0x8a)
)

WM_WTSSESSION_CHANGE   = 0x02B1
WTS_SESSION_LOCK       = 0x7
WTS_SESSION_UNLOCK     = 0x8
WM_POWERBROADCAST      = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013

class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [
        ('PowerSetting', GUID),
        ('DataLength', wintypes.DWORD),
        ('Data', ctypes.c_byte * 4),
    ]

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.UINT),
        ('dwTime', wintypes.DWORD),
    ]

def get_idle_seconds() -> float:
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if user32.GetLastInputInfo(ctypes.byref(lii)):
            return (kernel32.GetTickCount() - lii.dwTime) / 1000.0
    except Exception:
        pass
    return 0.0

class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ('style', wintypes.UINT),
        ('lpfnWndProc', WNDPROC),
        ('cbClsExtra', ctypes.c_int),
        ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE),
        ('hIcon', wintypes.HICON),
        ('hCursor', wintypes.HICON),
        ('hbrBackground', wintypes.HBRUSH),
        ('lpszMenuName', wintypes.LPCWSTR),
        ('lpszClassName', wintypes.LPCWSTR),
    ]

_proc_ref = None  # Keep strong reference to prevent GC callback crash

def _session_wnd_proc(hwnd, msg, wparam, lparam):
    global _session_locked, _display_off
    if msg == WM_WTSSESSION_CHANGE:
        if wparam == WTS_SESSION_LOCK:
            _session_locked = True
            log("Session Event: Workstation LOCKED (WTS_SESSION_LOCK)")
        elif wparam == WTS_SESSION_UNLOCK:
            _session_locked = False
            _display_off = False
            log("Session Event: Workstation UNLOCKED (WTS_SESSION_UNLOCK)")
    elif msg == WM_POWERBROADCAST:
        if wparam == PBT_POWERSETTINGCHANGE and lparam:
            try:
                pbs = ctypes.cast(lparam, ctypes.POINTER(POWERBROADCAST_SETTING)).contents
                if pbs.PowerSetting.Data1 == 0xda396341:  # GUID_CONSOLE_DISPLAY_STATE
                    state = int.from_bytes(bytes(pbs.Data[:4]), 'little')
                    if state == 0:
                        _display_off = True
                        _session_locked = True
                        log("Power Event: Laptop Display turned OFF (Screen Timeout / Sleep) -> Locking Deck")
                    elif state == 1:
                        _display_off = False
                        log("Power Event: Laptop Display turned ON (Woken up)")
            except Exception as e:
                log(f"Power event parse error: {e}")
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

def start_session_lock_monitor():
    global _session_monitor_started, _proc_ref, _session_locked
    if _session_monitor_started:
        return
    _session_monitor_started = True

    # Detect initial state
    try:
        desk = user32.OpenInputDesktop(0, False, 0x01FF)
        if desk == 0:
            _session_locked = True
        else:
            name_buf = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            user32.GetUserObjectInformationW(desk, 2, name_buf, ctypes.sizeof(name_buf), ctypes.byref(needed))
            user32.CloseDesktop(desk)
            if name_buf.value.lower() != 'default':
                _session_locked = True
    except Exception:
        pass

    def worker():
        global _proc_ref
        _proc_ref = WNDPROC(_session_wnd_proc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = _proc_ref
        wc.lpszClassName = 'SpotifyDeck_SessionNotifier'
        wc.hInstance = kernel32.GetModuleHandleW(None)
        user32.RegisterClassW(ctypes.byref(wc))
        hwnd = user32.CreateWindowExW(0, wc.lpszClassName, 'SpotifyDeck_Session', 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
        wtsapi32.WTSRegisterSessionNotification(hwnd, 0)
        user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), 0)

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    t = threading.Thread(target=worker, daemon=True, name='SessionLockMonitor')
    t.start()

class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ('ACLineStatus', wintypes.BYTE),
        ('BatteryFlag', wintypes.BYTE),
        ('BatteryLifePercent', wintypes.BYTE),
        ('SystemStatusFlag', wintypes.BYTE),
        ('BatteryLifeTime', wintypes.DWORD),
        ('BatteryFullLifeTime', wintypes.DWORD),
    ]

_cached_screen_timeout_ac = 1800
_cached_screen_timeout_dc = 180
_last_timeout_query = 0.0

def get_screen_timeout_seconds() -> int:
    global _cached_screen_timeout_ac, _cached_screen_timeout_dc, _last_timeout_query
    now = time.time()
    if now - _last_timeout_query > 60.0:
        _last_timeout_query = now
        try:
            out = subprocess.check_output(
                'powercfg /query SCHEME_CURRENT SUB_VIDEO VIDEOIDLE',
                text=True,
                creationflags=0x08000000
            )
            m_ac = re.search(r'Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)', out)
            m_dc = re.search(r'Current DC Power Setting Index:\s*0x([0-9a-fA-F]+)', out)
            if m_ac:
                val = int(m_ac.group(1), 16)
                if val > 0:
                    _cached_screen_timeout_ac = val
            if m_dc:
                val = int(m_dc.group(1), 16)
                if val > 0:
                    _cached_screen_timeout_dc = val
        except Exception:
            pass

    try:
        sps = SYSTEM_POWER_STATUS()
        kernel32.GetSystemPowerStatus(ctypes.byref(sps))
        is_ac = (sps.ACLineStatus == 1)
    except Exception:
        is_ac = True

    return _cached_screen_timeout_ac if is_ac else _cached_screen_timeout_dc

def is_workstation_locked() -> bool:
    """Accurately detects if Windows workstation is currently locked or display is turned off."""
    global _session_locked, _display_off
    # Real OS lock desktop check: Winlogon desktop indicates lock screen
    try:
        desk = user32.OpenInputDesktop(0, False, 0x01FF)
        if desk == 0:
            _session_locked = True
            return True
        name_buf = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        user32.GetUserObjectInformationW(desk, 2, name_buf, ctypes.sizeof(name_buf), ctypes.byref(needed))
        user32.CloseDesktop(desk)
        if name_buf.value.lower() != 'default':
            _session_locked = True
            return True
        else:
            # Active interactive user desktop is 'default' -> user is unlocked at the workstation
            _session_locked = False
            _display_off = False
            return False
    except Exception:
        pass

    return _session_locked or _display_off


def find_arduino_port() -> str | None:
    """Resolve serial port using user config or auto-discovery across any connected COM port."""
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        return None

    port_names = [p.device.upper() for p in ports]
    if PORT and PORT.upper() != "AUTO" and PORT.upper() in port_names:
        return PORT

    # Priority 1: Match known Arduino / CH340 / FTDI / CP210x hardware IDs and keywords
    keywords = [
        "ch340", "ch341", "ch9102", "arduino", "wch", "cp210", "ftdi",
        "usb-serial", "usb serial", "silicon labs", "prolific", "1a86:7523", "2341:"
    ]
    for p in ports:
        desc = (p.description or "").lower()
        mfg = (p.manufacturer or "").lower()
        hwid = (p.hwid or "").lower()
        if any(k in desc or k in mfg or k in hwid for k in keywords):
            return p.device

    # Priority 2: Filter out virtual Bluetooth COM ports, accept any physical USB serial port
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if "bluetooth" in desc or "bluetooth" in hwid or "bth" in hwid:
            continue
        if "usb" in hwid or "usb" in desc:
            return p.device

    # Priority 3: Fallback to first non-bluetooth port
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if "bluetooth" not in desc and "bth" not in hwid and "bluetooth" not in hwid:
            return p.device

    return None


async def get_best_session(mgr):
    if not mgr:
        try:
            mgr = await SessionManager.request_async()
        except Exception:
            return None
    if not mgr:
        return None

    try:
        sessions = mgr.get_sessions()
    except Exception:
        sessions = []

    spotify = None
    playing = None
    first_other = None
    for ses in sessions:
        try:
            app = (ses.source_app_user_model_id or "").lower()
            info = ses.get_playback_info()
            st = info.playback_status if info else None
            if st == PlayStatus.PLAYING:
                if "spotify" in app:
                    return ses
                if playing is None:
                    playing = ses
            elif "spotify" in app:
                if spotify is None:
                    spotify = ses
            else:
                if first_other is None:
                    first_other = ses
        except Exception:
            continue

    if playing:
        return playing
    if spotify:
        return spotify
    if first_other:
        return first_other
    try:
        return mgr.get_current_session()
    except Exception:
        return None


async def extract_cover_rgb565(props) -> bytes | None:
    if not props or not props.thumbnail:
        return None
    try:
        stream = await props.thumbnail.open_read_async()
        if stream.size == 0:
            return None
        reader = DataReader(stream)
        await reader.load_async(stream.size)
        buf = bytearray(stream.size)
        reader.read_bytes(buf)

        im = Image.open(io.BytesIO(buf)).convert("RGB")
        im = im.resize((ART_SIZE, ART_SIZE), Image.Resampling.LANCZOS)
        im = ImageEnhance.Sharpness(im).enhance(1.2)
        im = ImageEnhance.Contrast(im).enhance(1.15)
        im = ImageEnhance.Color(im).enhance(1.2)

        raw = bytearray(ART_SIZE * ART_SIZE * 2)
        idx = 0
        for y in range(ART_SIZE):
            for x in range(ART_SIZE):
                r, g, b = im.getpixel((x, y))
                c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                raw[idx]     = c & 0xFF        # LSB
                raw[idx + 1] = (c >> 8) & 0xFF # MSB
                idx += 2
        return bytes(raw)
    except Exception:
        return None


_cover_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

def _extract_cover_sync():
    """Extracts thumbnail stream in dedicated thread to prevent WinRT COM apartment deadlocks."""
    async def _extract():
        mgr = await SessionManager.request_async()
        ses = await get_best_session(mgr)
        props = await ses.try_get_media_properties_async() if ses else None
        if not props or not props.thumbnail:
            return None
        return await extract_cover_rgb565(props)
    try:
        return asyncio.run(_extract())
    except Exception:
        return None

async def extract_cover_safe() -> bytes | None:
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_cover_executor, _extract_cover_sync),
            timeout=2.0
        )
    except Exception:
        return None

_cached_chrome_cover = None
_cached_spotify_cover = None

def get_chrome_cover_rgb565() -> bytes:
    global _cached_chrome_cover
    if _cached_chrome_cover is not None:
        return _cached_chrome_cover

    raw_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_cover_200.raw")
    if os.path.exists(raw_path) and os.path.getsize(raw_path) == 80000:
        try:
            with open(raw_path, "rb") as f:
                _cached_chrome_cover = f.read()
            return _cached_chrome_cover
        except Exception:
            pass

    try:
        size = 200
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "official_chrome.png")
        if os.path.exists(logo_path):
            src = Image.open(logo_path).convert("RGBA")
            im = Image.new("RGB", (size, size), (0, 0, 0))
            logo = src.resize((150, 150), Image.Resampling.LANCZOS)
            im.paste(logo, ((size - 150) // 2, (size - 150) // 2), logo)
        else:
            im = Image.new("RGB", (size, size), (0, 0, 0))

        raw = bytearray(size * size * 2)
        idx = 0
        for y in range(size):
            for x in range(size):
                r_c, g_c, b_c = im.getpixel((x, y))
                c = ((r_c & 0xF8) << 8) | ((g_c & 0xFC) << 3) | (b_c >> 3)
                raw[idx]     = c & 0xFF
                raw[idx + 1] = (c >> 8) & 0xFF
                idx += 2
        _cached_chrome_cover = bytes(raw)
    except Exception:
        _cached_chrome_cover = b""
    return _cached_chrome_cover

def get_spotify_cover_rgb565() -> bytes:
    global _cached_spotify_cover
    if _cached_spotify_cover is not None:
        return _cached_spotify_cover
    try:
        from PIL import ImageDraw
        size = 200
        im = Image.new('RGB', (size, size), (24, 24, 28))
        d = ImageDraw.Draw(im)
        cx, cy, r = 100, 100, 68
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(30, 215, 96)) # Spotify Green
        d.arc([cx - 45, cy - 35, cx + 45, cy + 55], start=205, end=335, fill=(24, 24, 28), width=8)
        d.arc([cx - 38, cy - 22, cx + 38, cy + 58], start=208, end=332, fill=(24, 24, 28), width=7)
        d.arc([cx - 30, cy - 10, cx + 30, cy + 60], start=210, end=330, fill=(24, 24, 28), width=6)

        raw = bytearray(size * size * 2)
        idx = 0
        for y in range(size):
            for x in range(size):
                r_c, g_c, b_c = im.getpixel((x, y))
                c = ((r_c & 0xF8) << 8) | ((g_c & 0xFC) << 3) | (b_c >> 3)
                raw[idx]     = c & 0xFF
                raw[idx + 1] = (c >> 8) & 0xFF
                idx += 2
        _cached_spotify_cover = bytes(raw)
    except Exception:
        _cached_spotify_cover = b""
    return _cached_spotify_cover


async def send_cover_async(ser: serial.Serial, img_bytes: bytes, ses, active_track_key: str) -> bool:
    """Stream 200 rows with active mid-stream skip detection and live volume control."""
    vol_line_buf = ""

    def process_incoming_data(data: bytes) -> bool:
        """Parses incoming bytes, extracts #VOL: lines, and checks for 'K' ACK."""
        nonlocal vol_line_buf
        got_k = False
        for byte_val in data:
            if byte_val == ord('K'):
                got_k = True
            elif byte_val == ord('\n'):
                line = vol_line_buf.strip()
                if line.startswith("#VOL:"):
                    try:
                        set_system_volume(int(line[5:]))
                    except ValueError:
                        pass
                vol_line_buf = ""
            elif byte_val != ord('\r'):
                vol_line_buf += chr(byte_val)
        return got_k

    # Drain any buffered lines (e.g. #VOL) before sending #IMG_START
    while ser.in_waiting > 0:
        chunk = ser.read(ser.in_waiting)
        process_incoming_data(chunk)

    ser.write(b"#IMG_START\n")

    ack = False
    t0 = time.time()
    while time.time() - t0 < 2.0:
        if ser.in_waiting > 0:
            raw = ser.read(ser.in_waiting)
            if process_incoming_data(raw):
                ack = True
                break
        await asyncio.sleep(0.005)

    if not ack:
        log("Cover stream failed: Arduino did not ACK #IMG_START")
        return False

    row_bytes = ART_SIZE * 2
    for r in range(ART_SIZE):
        # Every 6 rows (~80ms), check if user skipped or paused song in Spotify
        if r % 6 == 0 and ses:
            try:
                cur_info = ses.get_playback_info()
                if cur_info and cur_info.playback_status != PlayStatus.PLAYING:
                    # User paused! Abort cover stream immediately
                    log("User paused during cover stream -> Aborted")
                    ser.write(b"#A\x00")
                    await asyncio.sleep(0.02)
                    ser.reset_input_buffer()
                    return False

                cur_props = await ses.try_get_media_properties_async()
                if cur_props:
                    ct = clean(cur_props.title)
                    ca = clean(cur_props.artist or cur_props.album_artist or "")
                    cur_app = (ses.source_app_user_model_id or "").lower()
                    cur_src = "S" if "spotify" in cur_app else ("C" if "chrome" in cur_app else "M")
                    if not ca:
                        ca = clean(cur_props.album_title or ("Chrome" if cur_src == "C" else "Spotify"))
                    new_key = f"{cur_src}:::{ct}:::{ca}"
                    if ct and new_key != active_track_key:
                        # User skipped! Abort immediately
                        log(f"Song skipped during cover stream: {active_track_key} -> {new_key} -> Aborted")
                        ser.write(b"#A\x00")
                        await asyncio.sleep(0.02)
                        ser.reset_input_buffer()
                        return False
            except Exception:
                pass

        row_data = img_bytes[r * row_bytes : (r + 1) * row_bytes]
        ser.write(b"#L" + bytes([r]) + row_data)

        ack = False
        t0 = time.time()
        while time.time() - t0 < 1.5:
            if ser.in_waiting > 0:
                raw = ser.read(ser.in_waiting)
                if process_incoming_data(raw):
                    ack = True
                    break
            await asyncio.sleep(0.002)

        if not ack:
            log(f"Cover stream row {r} ACK timed out")
            return False

    log(f"Cover stream completed successfully (200x200) for: {active_track_key}")
    return True


def compute_position(tl, status) -> tuple[int, int, str]:
    pos = tl.position.total_seconds() if tl and tl.position else 0.0
    dur = (tl.end_time - tl.start_time).total_seconds() if tl and tl.end_time else 0.0

    if status == PlayStatus.PLAYING and tl and tl.last_updated_time:
        lut = tl.last_updated_time
        if lut.tzinfo is None:
            lut = lut.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - lut).total_seconds()
        if 0 < elapsed < 86400:
            pos += elapsed

    if dur > 0 and pos > dur:
        pos = dur
    pos = max(0.0, pos)
    flag = "P" if status == PlayStatus.PLAYING else ("S" if status == PlayStatus.PAUSED else "N")
    return int(pos), int(dur), flag


async def run_playback_loop(ser: serial.Serial, mgr, notif_listener, initial_notif_id: int):
    """Main loop streaming metadata, live time, covers, and clock dashboard."""
    last_track_id = ""
    paused_since: float | None = None
    clock_state = {
        "battery_pct": 100,
        "charging": 0,
        "wifi": "Disconnected",
        "bt": "None",
        "last_sys_sent": 0.0,
        "last_sys_state": "",
        "last_notif_id": initial_notif_id,
        "pending_notif": None,
        "clock_mode": True,
        "running": True,
    }

    try:
        pct, chg = get_battery_info()
        clock_state["battery_pct"] = pct
        clock_state["charging"] = chg
        clock_state["wifi"] = await get_wifi_status()
        clock_state["bt"] = await get_bluetooth_device()
    except Exception:
        pass

    clock_state["streaming_cover"] = False
    worker_task = asyncio.create_task(telemetry_background_worker(notif_listener, clock_state))
    reader_task = asyncio.create_task(serial_reader_worker(ser, clock_state))

    # Check if Windows is currently locked or at login screen
    if is_workstation_locked():
        was_locked = True
        try:
            ser.write(b"#LOCK\n")
            log("Workstation is locked at startup -> sent #LOCK to display")
        except Exception:
            pass
    else:
        was_locked = False
        try:
            ser.write(b"#UNLOCK\n")
            log("Workstation is unlocked at startup -> sent #UNLOCK to display")
            await asyncio.sleep(0.4)
        except Exception:
            pass
        clock_state["clock_mode"] = True
        clock_state["last_sys_sent"] = 0.0
        send_clock_dashboard(ser, clock_state)

    try:
        while ser.is_open:
            # ── Check if Windows is Locked / Login Screen ──
            if is_workstation_locked():
                if not was_locked:
                    try:
                        ser.write(b"#LOCK\n")
                        log("Workstation locked -> sent #LOCK to display")
                    except Exception:
                        pass
                    was_locked = True
                await asyncio.sleep(0.5)
                continue

            # If user just unlocked workstation:
            if was_locked:
                was_locked = False
                try:
                    ser.write(b"#UNLOCK\n")
                    log("Workstation unlocked -> sent #UNLOCK to display")
                    await asyncio.sleep(0.4)
                except Exception:
                    pass
                clock_state["clock_mode"] = True
                clock_state["last_sys_sent"] = 0.0  # Force instant dashboard refresh
                send_clock_dashboard(ser, clock_state)

            if clock_state.get("force_track_refresh"):
                clock_state["force_track_refresh"] = False
                last_track_id = ""

            ses = await get_best_session(mgr)

            # ── Standby / No Media Session -> Clock Mode ──
            if ses is None:
                clock_state["clock_mode"] = True
                send_clock_dashboard(ser, clock_state)
                last_track_id = ""
                paused_since = None
                now = datetime.now()
                ms_left = (1_000_000 - now.microsecond) / 1_000_000.0
                await asyncio.sleep(max(0.05, ms_left))
                continue

            try:
                props  = await ses.try_get_media_properties_async()
                tl     = ses.get_timeline_properties()
                info   = ses.get_playback_info()
                status = info.playback_status if info else PlayStatus.STOPPED
            except Exception:
                await asyncio.sleep(0.3)
                continue

            pos, dur, flag = compute_position(tl, status)

            # ── If music is not playing -> Instantly switch to Main Display (Clock Mode) ──
            if status != PlayStatus.PLAYING:
                if not clock_state.get("clock_mode", True):
                    safe_write(ser, f"#T:{pos}:{dur}:S\n".encode("ascii"))
                    log(f"Playback paused/stopped ({pos}/{dur}s) -> sent frozen #T and switching to Clock Mode")
                clock_state["clock_mode"] = True
                send_clock_dashboard(ser, clock_state)
                last_track_id = ""
                paused_since = None
                now = datetime.now()
                ms_left = (1_000_000 - now.microsecond) / 1_000_000.0
                await asyncio.sleep(max(0.05, ms_left))
                continue
            else:
                # ── Music IS playing! ──
                if clock_state.get("clock_mode"):
                    last_track_id = ""
                clock_state["clock_mode"] = False
                paused_since = None

            app_id = (ses.source_app_user_model_id or "").lower()
            if "spotify" in app_id:
                src_code = "S"
            elif "chrome" in app_id:
                src_code = "C"
            else:
                src_code = "M"

            t  = clean(props.title) if props else ""
            ar = clean(props.artist or props.album_artist or "") if props else ""
            al = clean(props.album_title or "") if props else ""
            if not ar:
                ar = al or ("Chrome" if src_code == "C" else "Spotify")

            track_key = f"{src_code}:::{t}:::{ar}"

            # ── Track changed: trigger ONLY when title or artist actually changes ──
            if t and track_key != last_track_id:
                await asyncio.sleep(0.20)
                try:
                    props  = await ses.try_get_media_properties_async()
                    tl     = ses.get_timeline_properties()
                    info   = ses.get_playback_info()
                    status = info.playback_status if info else PlayStatus.STOPPED
                    t  = clean(props.title) if props else t
                    ar = clean(props.artist or props.album_artist or "") if props else ar
                    al = clean(props.album_title or "") if props else al
                    if not ar:
                        ar = al or ("Chrome" if src_code == "C" else "Spotify")
                    pos, dur, flag = compute_position(tl, status)
                    track_key = f"{src_code}:::{t}:::{ar}"
                except Exception:
                    pass

                # Immediately send title, artist, duration, current position, and play/pause state!
                song_cmd = f"#SONG:{t}|{ar}|{al}|{dur}|{pos}|{flag}|{src_code}\n"
                safe_write(ser, song_cmd.encode("ascii"))
                await asyncio.sleep(0.04)

                # Stream cover with active mid-stream abort check
                cover = await extract_cover_safe()
                success = False
                if cover:
                    clock_state["streaming_cover"] = True
                    try:
                        success = await send_cover_async(ser, cover, ses, track_key)
                    finally:
                        clock_state["streaming_cover"] = False
                else:
                    safe_write(ser, b"#NOIMG\n")
                    success = True

                last_track_id = track_key
                if not success:
                    await asyncio.sleep(0.3)

                try:
                    tl = ses.get_timeline_properties()
                    info = ses.get_playback_info()
                    status = info.playback_status if info else PlayStatus.STOPPED
                    pos, dur, flag = compute_position(tl, status)
                except Exception:
                    pass

            # ── Send Live Time Update ──
            time_cmd = f"#T:{pos}:{dur}:{flag}\n"
            safe_write(ser, time_cmd.encode("ascii"))
            await asyncio.sleep(0.4)
    finally:
        clock_state["running"] = False
        worker_task.cancel()
        reader_task.cancel()
        try:
            await asyncio.gather(worker_task, reader_task, return_exceptions=True)
        except Exception:
            pass
        try:
            ser.close()
        except Exception:
            pass


async def get_session_manager_safe():
    """Resilient helper to request SessionManager with retries on cold boot."""
    for _ in range(6):
        try:
            mgr = await SessionManager.request_async()
            if mgr:
                return mgr
        except Exception:
            pass
        await asyncio.sleep(1.0)
    return None


async def main():
    _mutex = acquire_single_instance_lock()
    if not _mutex:
        # Another instance is already running! Exit silently.
        return

    start_session_lock_monitor()
    log(f"Service started (PID {os.getpid()})")
    await asyncio.sleep(0.2)
    init_volume()

    mgr = await get_session_manager_safe()
    notif_listener, initial_notif_id = await init_notification_listener()

    # Infinite plug-and-play auto-reconnect loop
    while True:
        target_port = find_arduino_port()
        if not target_port:
            await asyncio.sleep(1.0)
            continue
        ser = None
        try:
            log(f"Arduino detected on {target_port}. Opening serial...")
            ser = serial.Serial(
                port=target_port,
                baudrate=BAUD,
                timeout=1.5,
                write_timeout=1.5,
            )
            await asyncio.sleep(0.3)
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except Exception:
                pass
            log(f"Serial connected to {target_port}")
            if mgr is None:
                mgr = await get_session_manager_safe()
            await run_playback_loop(ser, mgr, notif_listener, initial_notif_id)
        except (serial.SerialException, PermissionError, OSError) as e:
            log(f"Serial error on {target_port}: {e}. Retrying in 1.5s...")
            await asyncio.sleep(1.5)
        except KeyboardInterrupt:
            log("Service stopping via KeyboardInterrupt")
            break
        except Exception as e:
            log(f"Unexpected error in main loop: {e}")
            await asyncio.sleep(1.5)
        finally:
            if ser:
                try:
                    ser.close()
                except Exception:
                    pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log(f"CRITICAL CRASH: {e}\n{tb}")
