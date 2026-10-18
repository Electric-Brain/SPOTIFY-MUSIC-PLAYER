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
from datetime import datetime, timezone
import io
import re
import subprocess
import sys
import time

# Ensure safe stdout/stderr when running as background service via pythonw.exe
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

from PIL import Image, ImageEnhance
from pycaw.pycaw import AudioUtilities
import serial
import serial.tools.list_ports
from winrt.windows.devices.bluetooth import BluetoothDevice, BluetoothConnectionStatus
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

PORT = "COM5"       # Arduino Port (e.g. "COM3", "COM5"), or "AUTO" to auto-detect
BAUD = 115200
ART_SIZE = 200      # 200x200 Cover Art (Maximized Screen Width)


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


def get_wifi_ssid() -> str:
    global _cached_wifi, _wifi_last_check
    now = time.time()
    if now - _wifi_last_check < 4.0 and _cached_wifi:
        return _cached_wifi
    _wifi_last_check = now
    try:
        out = subprocess.check_output(
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
            _cached_wifi = "Disconnected"
            return _cached_wifi
    except Exception:
        pass
    _cached_wifi = "Disconnected"
    return _cached_wifi


_cached_bt: str = "None"
_bt_last_check: float = 0.0


async def get_bluetooth_device() -> str:
    global _cached_bt, _bt_last_check
    now = time.time()
    if now - _bt_last_check < 4.0:
        return _cached_bt
    _bt_last_check = now
    try:
        selector = BluetoothDevice.get_device_selector_from_connection_status(BluetoothConnectionStatus.CONNECTED)
        devices = await DeviceInformation.find_all_async_aqs_filter(selector)
        for d in devices:
            if d.name:
                _cached_bt = clean(d.name, 16)
                return _cached_bt
    except Exception:
        pass
    _cached_bt = "None"
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


async def check_new_notification(listener, last_id: int) -> tuple[int, str, str] | None:
    if not listener:
        return None
    try:
        notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
        cnt = len(notifs)
        if cnt > 0:
            latest = notifs[cnt - 1]
            if latest.id > last_id:
                app = "Notification"
                try:
                    if latest.app_info and latest.app_info.display_info:
                        app = clean(latest.app_info.display_info.display_name, 12)
                except Exception:
                    pass
                msg = ""
                try:
                    b = latest.notification.visual.get_binding("ToastGeneric")
                    if b:
                        elems = list(b.get_text_elements())
                        if len(elems) >= 1 and elems[0].text:
                            msg = elems[0].text
                        if len(elems) >= 2 and elems[1].text:
                            msg = f"{msg}: {elems[1].text}" if msg else elems[1].text
                except Exception:
                    pass
                return latest.id, app, clean(msg, 28)
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

                # 2. Async Wi-Fi query (in thread so subprocess doesn't block event loop)
                wifi = await asyncio.to_thread(get_wifi_ssid)
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


def send_clock_dashboard(ser: serial.Serial, state_tracker: dict):
    """Dispatches the live second clock tick, system telemetry, and notifications in <0.1ms."""
    now = datetime.now()
    t_str = f"{now.hour % 12 or 12:2d}:{now.minute:02d}:{now.second:02d}"
    ampm  = now.strftime("%p")
    d_str = now.strftime("%A, %d %b")
    ser.write(f"#CLOCK:{t_str}|{ampm}|{d_str}\n".encode("ascii"))

    cur_time = time.time()
    pct  = state_tracker.get("battery_pct", 100)
    chg  = state_tracker.get("charging", 0)
    wifi = state_tracker.get("wifi", "Disconnected")
    bt   = state_tracker.get("bt", "None")
    sys_state = f"{pct}|{chg}|{wifi}|{bt}"

    if sys_state != state_tracker.get("last_sys_state", "") or (cur_time - state_tracker.get("last_sys_sent", 0) >= 5.0):
        ser.write(f"#SYS:{sys_state}\n".encode("ascii"))
        state_tracker["last_sys_state"] = sys_state
        state_tracker["last_sys_sent"] = cur_time

    if state_tracker.get("pending_notif"):
        napp, nmsg = state_tracker["pending_notif"]
        state_tracker["pending_notif"] = None
        ser.write(f"#NOTIF:{napp}|{nmsg}\n".encode("ascii"))


# ═══════════════════════════════════════════════════════════════════
#   HARDWARE VOLUME CONTROLLER & POPUP TRIGGER (PIN A5 -> WINDOWS)
# ═══════════════════════════════════════════════════════════════════

VK_VOLUME_UP   = 0xAF
VK_VOLUME_DOWN = 0xAE

_cached_audio_endpoint = None

def get_audio_endpoint():
    global _cached_audio_endpoint
    if _cached_audio_endpoint is None:
        try:
            sp = AudioUtilities.GetSpeakers()
            _cached_audio_endpoint = sp.EndpointVolume if sp else None
        except Exception:
            _cached_audio_endpoint = None
    return _cached_audio_endpoint


_last_applied_vol = -1

def set_system_volume(vol_pct: int):
    """Sets master volume (0-100%) and triggers the live native Windows volume popup (OSD)."""
    global _last_applied_vol
    if vol_pct == _last_applied_vol:
        return
    _last_applied_vol = vol_pct

    ep = get_audio_endpoint()
    if not ep:
        return
    scalar = max(0.0, min(1.0, vol_pct / 100.0))
    try:
        # 1. Set exact scalar level directly
        ep.SetMasterVolumeLevelScalar(scalar, None)

        # 2. Trigger native Windows Volume Flyout / OSD banner popup
        if scalar >= 0.98:
            ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 2, 0)
        else:
            ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 2, 0)

        # 3. Re-assert exact scalar level so keystroke doesn't shift it
        ep.SetMasterVolumeLevelScalar(scalar, None)
    except Exception:
        pass


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
        except Exception:
            pass
        await asyncio.sleep(0.015)


def find_arduino_port() -> str:
    """Resolve serial port using user config or auto-discovery."""
    if PORT and PORT.upper() != "AUTO":
        return PORT
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        mfg = (p.manufacturer or "").lower()
        if "arduino" in desc or "arduino" in mfg or "ch340" in desc or "ch340" in mfg or "usb-serial" in desc:
            return p.device
    ports = list(serial.tools.list_ports.comports())
    if ports:
        return ports[0].device
    return "COM5"


def clean(s: str, n: int = 36) -> str:
    s = (s or "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
    return s.encode("ascii", "replace").decode()[:n]


async def get_best_session(mgr):
    try:
        sessions = mgr.get_sessions()
    except Exception:
        sessions = []

    spotify = None
    playing = None
    for ses in sessions:
        try:
            app = (ses.source_app_user_model_id or "").lower()
            st = ses.get_playback_info().playback_status
            if "spotify" in app:
                if st == PlayStatus.PLAYING:
                    return ses
                spotify = ses
            elif st == PlayStatus.PLAYING and playing is None:
                playing = ses
        except Exception:
            continue

    return spotify or playing or mgr.get_current_session()


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


async def send_cover_async(ser: serial.Serial, img_bytes: bytes, ses, active_track_key: str) -> bool:
    """Stream 200 rows with active mid-stream skip detection."""
    # Drain any buffered lines (e.g. #VOL) before sending #IMG_START
    while ser.in_waiting > 0:
        chunk = ser.read(ser.in_waiting)
        try:
            for part in chunk.decode("ascii", errors="ignore").split("\n"):
                if part.strip().startswith("#VOL:"):
                    set_system_volume(int(part.strip()[5:]))
        except Exception:
            pass

    ser.write(b"#IMG_START\n")

    ack = None
    t0 = time.time()
    while time.time() - t0 < 2.0:
        if ser.in_waiting > 0:
            b = ser.read(1)
            if b == b'K':
                ack = b'K'
                break
        await asyncio.sleep(0.005)

    if ack != b'K':
        return False

    row_bytes = ART_SIZE * 2
    for r in range(ART_SIZE):
        # Every 6 rows (~80ms), check if user skipped song in Spotify
        if r % 6 == 0 and ses:
            try:
                cur_props = await ses.try_get_media_properties_async()
                if cur_props:
                    ct = clean(cur_props.title)
                    ca = clean(cur_props.artist or cur_props.album_artist or "")
                    if not ca:
                        ca = clean(cur_props.album_title or "Spotify")
                    new_key = f"{ct}:::{ca}"
                    if ct and new_key != active_track_key:
                        # User skipped! Abort immediately
                        ser.write(b"#A\x00")
                        await asyncio.sleep(0.02)
                        ser.reset_input_buffer()
                        return False
            except Exception:
                pass

        row_data = img_bytes[r * row_bytes : (r + 1) * row_bytes]
        ser.write(b"#L" + bytes([r]) + row_data)

        ack = None
        t0 = time.time()
        while time.time() - t0 < 1.5:
            if ser.in_waiting > 0:
                b = ser.read(1)
                if b == b'K':
                    ack = b'K'
                    break
            await asyncio.sleep(0.002)

        if ack != b'K':
            return False

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
        "clock_mode": False,
        "running": True,
    }

    try:
        pct, chg = get_battery_info()
        clock_state["battery_pct"] = pct
        clock_state["charging"] = chg
        clock_state["wifi"] = get_wifi_ssid()
    except Exception:
        pass

    clock_state["streaming_cover"] = False
    worker_task = asyncio.create_task(telemetry_background_worker(notif_listener, clock_state))
    reader_task = asyncio.create_task(serial_reader_worker(ser, clock_state))

    try:
        while ser.is_open:
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

            # ── Pause / Idle detection -> Freeze timer and transition to Clock ──
            if status != PlayStatus.PLAYING:
                if paused_since is None:
                    paused_since = time.time()
                    # Immediately freeze timer and draw PAUSED badge
                    ser.write(f"#T:{pos}:{dur}:S\n".encode("ascii"))
                elif time.time() - paused_since >= 8.0:
                    # 8 seconds of continuous pause: Switch to sleek Standby Clock Dashboard
                    clock_state["clock_mode"] = True
                    send_clock_dashboard(ser, clock_state)
                    now = datetime.now()
                    ms_left = (1_000_000 - now.microsecond) / 1_000_000.0
                    await asyncio.sleep(max(0.05, ms_left))
                    continue
                else:
                    ser.write(f"#T:{pos}:{dur}:S\n".encode("ascii"))
                    await asyncio.sleep(0.4)
                    continue
            else:
                clock_state["clock_mode"] = False
                if paused_since is not None and paused_since > 0:
                    # Waking up from pause: force immediate refresh
                    last_track_id = ""
                paused_since = None

            t  = clean(props.title) if props else ""
            ar = clean(props.artist or props.album_artist or "") if props else ""
            al = clean(props.album_title or "") if props else ""
            if not ar:
                ar = al or "Spotify"

            track_key = f"{t}:::{ar}"

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
                        ar = al or "Spotify"
                    pos, dur, flag = compute_position(tl, status)
                    track_key = f"{t}:::{ar}"
                except Exception:
                    pass

                # Immediately send title, artist, duration, current position, and play/pause state!
                song_cmd = f"#SONG:{t}|{ar}|{al}|{dur}|{pos}|{flag}\n"
                ser.write(song_cmd.encode("ascii"))
                await asyncio.sleep(0.04)

                # Stream cover with active mid-stream abort check
                cover = await extract_cover_safe()
                if cover:
                    clock_state["streaming_cover"] = True
                    try:
                        await send_cover_async(ser, cover, ses, track_key)
                    finally:
                        clock_state["streaming_cover"] = False
                else:
                    ser.write(b"#NOIMG\n")

                last_track_id = track_key

                try:
                    tl = ses.get_timeline_properties()
                    info = ses.get_playback_info()
                    status = info.playback_status if info else PlayStatus.STOPPED
                    pos, dur, flag = compute_position(tl, status)
                except Exception:
                    pass

            # ── Send Live Time Update ──
            time_cmd = f"#T:{pos}:{dur}:{flag}\n"
            ser.write(time_cmd.encode("ascii"))
            await asyncio.sleep(0.4)
    finally:
        clock_state["running"] = False
        worker_task.cancel()
        reader_task.cancel()


async def main():
    mgr = await SessionManager.request_async()
    notif_listener, initial_notif_id = await init_notification_listener()

    # Infinite plug-and-play auto-reconnect loop
    while True:
        target_port = find_arduino_port()
        try:
            ser = serial.Serial(target_port, BAUD, timeout=2)
            time.sleep(2)  # UNO reboot wait
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(b"\n")
            await asyncio.sleep(0.05)
            await run_playback_loop(ser, mgr, notif_listener, initial_notif_id)
        except (serial.SerialException, PermissionError, OSError):
            await asyncio.sleep(2)
        except KeyboardInterrupt:
            break
        except Exception:
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
