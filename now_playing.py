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
from datetime import datetime, timezone
import io
import sys
import time

# Ensure safe stdout/stderr when running as background service via pythonw.exe
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

from PIL import Image, ImageEnhance
import serial
import serial.tools.list_ports
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlayStatus,
)
from winrt.windows.storage.streams import DataReader

PORT = "COM5"       # Arduino Port (e.g. "COM3", "COM5"), or "AUTO" to auto-detect
BAUD = 115200
ART_SIZE = 200      # 200x200 Cover Art (Maximized Screen Width)


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


async def send_cover_async(ser: serial.Serial, img_bytes: bytes, ses, active_track_key: str) -> bool:
    """Stream 200 rows with active mid-stream skip detection."""
    ser.write(b"#IMG_START\n")

    t0 = time.time()
    while ser.in_waiting == 0:
        await asyncio.sleep(0.01)
        if time.time() - t0 > 2.0:
            return False
    ack = ser.read(1)
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

        t0 = time.time()
        while ser.in_waiting == 0:
            await asyncio.sleep(0.005)
            if time.time() - t0 > 1.5:
                return False
        ack = ser.read(1)
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


async def run_playback_loop(ser: serial.Serial, mgr):
    """Main loop streaming metadata, live time, covers, and standby clock."""
    last_track_id = ""
    paused_since: float | None = None

    while ser.is_open:
        ses = await get_best_session(mgr)

        # ── Standby / No Media Session -> Clock Mode ──
        if ses is None:
            now = datetime.now()
            t_str = f"{now.hour % 12 or 12:2d}:{now.minute:02d}:{now.second:02d}"
            ampm  = now.strftime("%p")
            d_str = now.strftime("%A, %d %b")
            ser.write(f"#CLOCK:{t_str}|{ampm}|{d_str}\n".encode("ascii"))
            last_track_id = ""
            paused_since = None
            await asyncio.sleep(1.0)
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
                # 8 seconds of continuous pause: Switch to sleek Standby Clock
                now = datetime.now()
                t_str = f"{now.hour % 12 or 12:2d}:{now.minute:02d}:{now.second:02d}"
                ampm  = now.strftime("%p")
                d_str = now.strftime("%A, %d %b")
                ser.write(f"#CLOCK:{t_str}|{ampm}|{d_str}\n".encode("ascii"))
                await asyncio.sleep(1.0)
                continue
            else:
                ser.write(f"#T:{pos}:{dur}:S\n".encode("ascii"))
                await asyncio.sleep(0.4)
                continue
        else:
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
            cover = await extract_cover_rgb565(props)
            if cover:
                success = await send_cover_async(ser, cover, ses, track_key)
                if not success:
                    continue
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


async def main():
    mgr = await SessionManager.request_async()

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
            await run_playback_loop(ser, mgr)
        except (serial.SerialException, PermissionError, OSError):
            await asyncio.sleep(2)
        except KeyboardInterrupt:
            break
        except Exception:
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
