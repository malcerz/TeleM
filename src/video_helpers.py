"""Video helpers for TeleMGP HUD Tuner.

Contains FFmpeg, FFprobe, OpenCV proxy caching, and frame extraction functions.
"""

import io
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
try:
    from PIL import Image
except ImportError:
    print("Błąd: brakuje Pillow. Zainstaluj: python -m pip install pillow", file=sys.stderr)
    sys.exit(1)

from src.ffmpeg.detection import detect_gpu_decoder

_FFPROBE_DURATION_CACHE: dict[str, float] = {}
_CV2_CAP_CACHE: dict[str, any] = {}


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return p.stdout


def run_live(cmd):
    p = subprocess.run(cmd)
    if p.returncode != 0:
        raise RuntimeError(f'Polecenie zakończone błędem: {p.returncode}')


def find_local_tool(base_dir, names):
    for name in names:
        p = base_dir / name
        if p.exists():
            return p
    return None


def find_executable(name, extra_candidates=None):
    p = shutil.which(name)
    if p:
        return p
    extra_candidates = extra_candidates or []
    for candidate in extra_candidates:
        if Path(candidate).exists():
            return str(Path(candidate))
    return None


def sanitize_output_path(path_text):
    txt = str(path_text).strip()
    while txt.endswith('.'):
        txt = txt[:-1]
    return Path(txt)


def get_proxy_path(video_path):
    """Return a low-res proxy path for the given video, or None.

    Used only as a fallback for OpenCV frame extraction (CPU path).
    The primary preview path now goes through QMediaPlayer (HW-accelerated).
    """
    p = Path(video_path)
    parent = p.parent
    name = p.name

    for ext in ('.mp4', '.MP4'):
        cand = parent / f"{p.stem}_proxy{ext}"
        if cand.exists():
            return cand

    if len(name) >= 4:
        for prefix_type in [('GX', 'GL'), ('gx', 'gl'), ('GH', 'GL'), ('gh', 'gl'), ('GP', 'GL'), ('gp', 'gl')]:
            src_pref, tgt_pref = prefix_type
            if name.startswith(src_pref):
                lrv_name = tgt_pref + name[len(src_pref):]
                for ext in ('.lrv', '.LRV', '.mp4', '.MP4'):
                    cand = parent / Path(lrv_name).with_suffix(ext)
                    if cand.exists() and cand != p:
                        return cand

    for ext in ('.lrv', '.LRV'):
        cand = p.with_suffix(ext)
        if cand.exists() and cand != p:
            return cand

    return None


def get_cached_capture(path):
    path_str = str(path)
    if path_str not in _CV2_CAP_CACHE:
        try:
            import cv2
            cap = None
            # Try hardware-accelerated capture first (OpenCV ≥ 4.5.4)
            if hasattr(cv2, 'CAP_PROP_HW_ACCELERATION') and hasattr(cv2, 'VIDEO_ACCELERATION_ANY'):
                try:
                    cap = cv2.VideoCapture(
                        path_str,
                        cv2.CAP_FFMPEG,
                        [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY]
                    )
                    if not cap.isOpened():
                        cap.release()
                        cap = None
                except Exception:
                    cap = None
            # Fallback: standard CPU capture
            if cap is None:
                cap = cv2.VideoCapture(path_str)
            if cap.isOpened():
                _CV2_CAP_CACHE[path_str] = cap
            else:
                return None
        except Exception:
            return None
    return _CV2_CAP_CACHE[path_str]


def clear_capture_cache():
    for cap in list(_CV2_CAP_CACHE.values()):
        try:
            cap.release()
        except Exception:
            pass
    _CV2_CAP_CACHE.clear()


def extract_frame(video_paths, timestamp_s, ffmpeg_exe='ffmpeg', ffprobe_exe='ffprobe', target_w=960, preferred_encoder='', cache_capture=True):
    if not isinstance(video_paths, list):
        video_paths = [video_paths]

    target_path = video_paths[0]
    target_ts = timestamp_s

    current_offset = 0.0
    for p in video_paths:
        if p not in _FFPROBE_DURATION_CACHE:
            info = ffprobe_stream_info(ffprobe_exe, p)
            _FFPROBE_DURATION_CACHE[p] = float(info.get('format', {}).get('duration', 0) or 0)

        dur = _FFPROBE_DURATION_CACHE[p]

        if current_offset + dur > timestamp_s:
            target_path = p
            target_ts = timestamp_s - current_offset
            break
        current_offset += dur

    try:
        import cv2
        actual_path = get_proxy_path(target_path) or target_path
        
        local_caps = []
        if cache_capture:
            cap = get_cached_capture(actual_path)
        else:
            cap = cv2.VideoCapture(actual_path)
            if cap is not None:
                local_caps.append(cap)
                if not cap.isOpened():
                    cap.release()
                    cap = None
        if cap is not None:
            cap.set(cv2.CAP_PROP_POS_MSEC, target_ts * 1000.0)
            ret, frame = cap.read()
            
            if not ret and actual_path != target_path:
                if cache_capture:
                    cap = get_cached_capture(target_path)
                else:
                    cap = cv2.VideoCapture(target_path)
                    if cap is not None:
                        local_caps.append(cap)
                        if not cap.isOpened():
                            cap.release()
                            cap = None
                if cap is not None:
                    cap.set(cv2.CAP_PROP_POS_MSEC, target_ts * 1000.0)
                    ret, frame = cap.read()
            
            if ret:
                h, w = frame.shape[:2]
                if target_w and w > target_w:
                    scale = target_w / w
                    frame = cv2.resize(frame, (target_w, int(h * scale)))
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
                return Image.fromarray(frame_rgb)
    except Exception:
        pass
    finally:
        # Export Preview uses cache_capture=False and owns each decoder for
        # one snapshot only.  Never leave a VideoCapture alive between
        # renders or after Preview is disabled.
        for local_cap in locals().get("local_caps", []):
            try:
                local_cap.release()
            except Exception:
                pass

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
    scale_filter = []
    if target_w:
        scale_filter = ['-vf', f'scale={target_w}:-1']

    hwaccel = detect_gpu_decoder(preferred_encoder)
    for attempt in (0, 1):
        cmd = [ffmpeg_exe]
        if attempt == 0 and hwaccel:
            cmd.extend(['-hwaccel', hwaccel])
        cmd.extend(['-ss', str(target_ts), '-i', str(target_path)])
        cmd.extend(scale_filter)
        cmd.extend([
            '-frames:v', '1', '-q:v', '4',
            '-f', 'image2pipe', '-vcodec', 'mjpeg', '-'
        ])
        p = subprocess.run(cmd, capture_output=True, startupinfo=startupinfo)
        if p.returncode == 0 and p.stdout:
            break
        if attempt == 0 and hwaccel:
            continue
        return None
    return Image.open(io.BytesIO(p.stdout)).convert('RGBA')


def ffprobe_resolution(video_path, ffprobe='ffprobe'):
    out = run([ffprobe, '-v', 'error', '-select_streams', 'v:0',
               '-show_entries', 'stream=width,height', '-of', 'json', str(video_path)])
    data = json.loads(out)
    streams = data.get('streams', [])
    if not streams:
        return 1280, 720
    return int(streams[0].get('width', 1280)), int(streams[0].get('height', 720))


def ffprobe_stream_info(ffprobe_exe, input_file):
    out = run([
        ffprobe_exe, '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=r_frame_rate,avg_frame_rate,width,height:format=duration',
        '-of', 'json', str(input_file)
    ])
    return json.loads(out)


def parse_fps(rate_text):
    if not rate_text or rate_text == '0/0':
        return 30.0
    if '/' in rate_text:
        a, b = rate_text.split('/')
        a, b = float(a), float(b)
        if b == 0:
            return 30.0
        return a / b
    return float(rate_text)


def round_dt_to_nearest_5min(dt: datetime) -> datetime:
    """Round a datetime to the nearest 5 minutes (300 seconds).

    Correctly handles rollover like 23:58 -> next day 00:00.
    """
    minute_s = dt.minute * 60 + dt.second + dt.microsecond / 1e6
    rounded_s = round(minute_s / 300.0) * 300
    base = dt.replace(minute=0, second=0, microsecond=0)
    return base + timedelta(seconds=rounded_s)


def resolve_local_datetime(
    dt: datetime,
    fit_data: any = None,
    tz_offset_hours: float | None = None,
    tzinfo: any = None,
) -> tuple[datetime, str]:
    """Convert a UTC (or naive-UTC) datetime to local recording datetime.

    Resolution order:
    1. FIT / GPMF / project timezone information if available and reliable.
    2. Existing project / application timezone offset (tz_offset_hours).
    3. System local timezone as DST-aware fallback (via datetime.astimezone()).

    Returns:
        (local_dt, resolution_reason)
    """
    from datetime import timezone as _dt_tz

    # 1. FIT timezone information (e.g. Garmin Edge activity local_timestamp offset)
    if fit_data is not None:
        offset = getattr(fit_data, "timezone_offset_hours", None)
        if offset is None and hasattr(fit_data, "records"):
            offset = getattr(fit_data.records, "timezone_offset_hours", None)
        if offset is not None:
            base = dt.replace(tzinfo=None) if dt.tzinfo else dt
            return base + timedelta(hours=offset), f"FIT activity offset ({offset:+.1f}h)"

    # 2. Explicit project / application timezone offset
    if tz_offset_hours is not None:
        base = dt.replace(tzinfo=None) if dt.tzinfo else dt
        return base + timedelta(hours=tz_offset_hours), f"Project/App timezone offset ({tz_offset_hours:+.1f}h)"

    # Explicit tzinfo object if provided
    if tzinfo is not None:
        dt_utc = dt.replace(tzinfo=_dt_tz.utc) if dt.tzinfo is None else dt.astimezone(_dt_tz.utc)
        dt_loc = dt_utc.astimezone(tzinfo)
        return dt_loc.replace(tzinfo=None), f"Explicit tzinfo ({tzinfo})"

    # 3. System local timezone as DST-aware fallback
    dt_utc = dt.replace(tzinfo=_dt_tz.utc) if dt.tzinfo is None else dt.astimezone(_dt_tz.utc)
    dt_loc = dt_utc.astimezone()
    tz_name = dt_loc.tzname() or "local"
    return dt_loc.replace(tzinfo=None), f"System local timezone ({tz_name}, {dt_loc.utcoffset()})"


def generate_auto_export_filename(
    start_dt: datetime,
    target_dir: Path | str | None = None,
    fit_data: any = None,
    tz_offset_hours: float | None = None,
    tzinfo: any = None,
) -> str:
    """Generate default export filename YYYYMMDD-HHMM.mp4 with collision suffixes.

    Converts start_dt (assumed UTC if naive) to local datetime using:
    1. FIT / GPMF / project timezone information if available.
    2. Explicit project / app timezone offset.
    3. System local timezone as DST-aware fallback.
    """
    local_dt, _ = resolve_local_datetime(
        start_dt, fit_data=fit_data, tz_offset_hours=tz_offset_hours, tzinfo=tzinfo
    )
    rd = round_dt_to_nearest_5min(local_dt)
    base_stem = rd.strftime("%Y%m%d-%H%M")
    candidate_name = f"{base_stem}.mp4"
    if target_dir is None:
        return candidate_name
    t_dir = Path(target_dir)
    if not (t_dir / candidate_name).exists():
        return candidate_name
    idx = 1
    while (t_dir / f"{base_stem}-{idx:02d}.mp4").exists():
        idx += 1
    return f"{base_stem}-{idx:02d}.mp4"

