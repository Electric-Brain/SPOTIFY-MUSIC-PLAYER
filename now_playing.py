# ============================================================================
#   SPOTIFY NOW PLAYING - 200x200 FAST STREAMING SENDER
# ============================================================================

import asyncio
from datetime import datetime, timezone
import io
import time
import serial
from PIL import Image, ImageEnhance
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlayStatus,
)
from winrt.windows.storage.streams import DataReader

PORT = "COM5"       # Arduino IDE > Tools > Port
BAUD = 115200
ART_SIZE = 200      # 200x200 Cover Art


def clean(s: str, n: int = 48) -> str:
    s = (s or "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
    return s.encode("ascii", "replace").decode()[:n]


async def get_best_session(mgr):
    """Find the best active session, strongly preferring Spotify."""
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
    """Extract, resize to 200x200, enhance, and convert to Little-Endian RGB565."""
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

        # Enhance contrast & saturation for TFT
        im = ImageEnhance.Contrast(im).enhance(1.15)
        im = ImageEnhance.Color(im).enhance(1.2)

        # Convert to Little-Endian RGB565 bytes
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

    except Exception as e:
        print(f"  [Cover] Extraction error: {e}")
        return None


def send_cover(ser: serial.Serial, img_bytes: bytes) -> bool:
    """Stream 200 rows of RGB565 data rapidly with ACK handshake."""
    ser.write(b"#IMG_START\n")

    ack = ser.read(1)
    if ack != b'K':
        print("  [Cover] Arduino did not acknowledge start")
        return False

    row_bytes = ART_SIZE * 2  # 400 bytes per row

    for r in range(ART_SIZE):
        row_data = img_bytes[r * row_bytes : (r + 1) * row_bytes]
        ser.write(b"#L" + bytes([r]) + row_data)

        # Wait for per-row ACK (no redundant ser.flush() for 2x faster transfer!)
        ack = ser.read(1)
        if ack != b'K':
            print(f"  [Cover] Lost sync at row {r}")
            return False

    print("  [Cover] 200x200 transfer complete!")
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


async def main():
    mgr = await SessionManager.request_async()

    print("=" * 60)
    print("  SPOTIFY 200x200 NOW PLAYING DISPLAY SENDER")
    print("=" * 60)
    print(f"  Port: {PORT}  Baud: {BAUD}\n")

    try:
        ser = serial.Serial(PORT, BAUD, timeout=2)
        time.sleep(2)  # UNO reboot wait
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print(f"  Connected to Arduino on {PORT}!\n")
    except Exception as e:
        print(f"  Error opening {PORT}: {e}")
        return

    last_track_id = ""

    try:
        while True:
            ses = await get_best_session(mgr)
            if ses is None:
                ser.write(b"#T:0:0:N\n")
                await asyncio.sleep(1)
                continue

            try:
                props = await ses.try_get_media_properties_async()
                tl    = ses.get_timeline_properties()
                info  = ses.get_playback_info()
                status = info.playback_status if info else PlayStatus.STOPPED
            except Exception:
                await asyncio.sleep(0.5)
                continue

            pos, dur, flag = compute_position(tl, status)

            t  = clean(props.title) if props else ""
            ar = clean(props.artist or props.album_artist or "") if props else ""
            al = clean(props.album_title or "") if props else ""
            if not ar:
                ar = al or "Spotify"

            track_id = f"{t}|{ar}|{al}|{dur}"

            # ── Track changed ──
            if track_id != last_track_id and t:
                # Brief wait for Spotify UWP thumbnail buffer to settle
                await asyncio.sleep(0.25)
                try:
                    props = await ses.try_get_media_properties_async()
                except Exception:
                    pass

                print(f"\n  ♪ {t} — {ar}")
                song_cmd = f"#SONG:{t}|{ar}|{al}|{dur}\n"
                ser.write(song_cmd.encode("ascii"))
                await asyncio.sleep(0.05)

                cover = await extract_cover_rgb565(props)
                if cover:
                    send_cover(ser, cover)
                else:
                    ser.write(b"#NOIMG\n")

                last_track_id = track_id

                # Re-calculate position fresh after cover transfer so stale pos=0 is NEVER sent!
                try:
                    tl = ses.get_timeline_properties()
                    info = ses.get_playback_info()
                    status = info.playback_status if info else PlayStatus.STOPPED
                    pos, dur, flag = compute_position(tl, status)
                except Exception:
                    pass

            # ── Send live time update ──
            time_cmd = f"#T:{pos}:{dur}:{flag}\n"
            ser.write(time_cmd.encode("ascii"))
            m, s = divmod(pos, 60)
            dm, ds = divmod(dur, 60)
            print(f"\r  [{flag}] {m}:{s:02d} / {dm}:{ds:02d}", end="", flush=True)

            await asyncio.sleep(0.5)

    except KeyboardInterrupt:
        print("\n  Stopping sender...")
    finally:
        ser.close()
        print("  Serial port closed.")


if __name__ == "__main__":
    asyncio.run(main())
