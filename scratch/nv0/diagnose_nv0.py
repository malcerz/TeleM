# -*- coding: utf-8 -*-
"""diagnose_nv0.py

Diagnostic script for NVIDIA ETAP NV0.
Collects a true end‑to‑end FPS baseline, captures the exact FFmpeg command,
records nvidia‑smi utilization samples, and writes artefacts to
`Raporty/NVIDIA_NV0/`.

The script runs the production GUI export pipeline in a head‑less fashion
by invoking the `stream_overlay_to_ffmpeg` function directly. It does not
modify any production source files.
"""

import json
import os
import sys
import threading
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# --- Helper: locate reference video --------------------------------------
BASE_DIR = Path(__file__).resolve().parents[2]  # f:/_DEV/TeleM
VIDEO_DIR = BASE_DIR / "Video"
VIDEO_NAME = "GX020079.MP4"
VIDEO_PATH = VIDEO_DIR / VIDEO_NAME
if not VIDEO_PATH.is_file():
    print(f"[ERROR] Reference video not found at {VIDEO_PATH}", file=sys.stderr)
    sys.exit(1)

# Find associated telemetry JSON (if present)
JSON_PATH = VIDEO_PATH.with_suffix('.json')
if not JSON_PATH.is_file():
    JSON_PATH = None

# --- Helper: locate ffprobe (for duration/FPS) ---------------------------
def which(exe_name: str) -> Optional[Path]:
    """Return the absolute Path of an executable found in PATH or None."""
    from shutil import which as _which
    p = _which(exe_name)
    return Path(p) if p else None

ffprobe_exe = which('ffprobe')
if not ffprobe_exe:
    print('[ERROR] ffprobe not found in PATH.', file=sys.stderr)
    sys.exit(1)

# Get video duration and fps via ffprobe (exact values, no rounding)
probe_cmd = [str(ffprobe_exe), '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=duration,avg_frame_rate',
             '-of', 'json', str(VIDEO_PATH)]
result = subprocess.run(probe_cmd, capture_output=True, text=True)
if result.returncode != 0:
    print('[ERROR] ffprobe failed:', result.stderr, file=sys.stderr)
    sys.exit(1)
info = json.loads(result.stdout)
stream = info['streams'][0]
duration_s = float(stream['duration'])
# avg_frame_rate is a string like "30/1"
num, den = map(int, stream['avg_frame_rate'].split('/'))
fps = num / den if den != 0 else 30.0
# Ensure we use the reference frame count (1131) as per user spec.
TARGET_FRAME_COUNT = 1131

# --- nvidia‑smi sampler ---------------------------------------------------
class NvidiaSampler(threading.Thread):
    def __init__(self, output_csv: Path, interval: float = 1.0):
        super().__init__(daemon=True)
        self.output_csv = output_csv
        self.interval = interval
        self.samples: List[str] = []
        self._stop_event = threading.Event()
        self.nvidia_smi = which('nvidia-smi')
        if not self.nvidia_smi:
            raise RuntimeError('nvidia-smi not found in PATH')

    def run(self):
        query = [str(self.nvidia_smi), '--query-gpu=timestamp,utilization.gpu,memory.total,memory.used',
                 '--format=csv,noheader,nounits']
        while not self._stop_event.is_set():
            try:
                out = subprocess.check_output(query, text=True)
                ts = datetime.utcnow().isoformat()
                self.samples.append(f"{ts}," + out.strip())
            except Exception as e:
                self.samples.append(f"{datetime.utcnow().isoformat()},ERROR,{e}")
            time.sleep(self.interval)

    def stop(self):
        self._stop_event.set()
        self.join()
        header = 'timestamp,utilization.gpu,memory.total,memory.used\n'
        with open(self.output_csv, 'w', encoding='utf-8') as f:
            f.write(header)
            for line in self.samples:
                f.write(line + '\n')

# --- Capture FFmpeg command ------------------------------------------------
class CaptureStdout:
    def __init__(self):
        self.captured = []
        self._original = sys.stdout

    def write(self, data):
        self.captured.append(data)
        self._original.write(data)

    def flush(self):
        self._original.flush()

    def __enter__(self):
        sys.stdout = self
        return self

    def __exit__(self, exc_type, exc, tb):
        sys.stdout = self._original

# --- Main diagnostic flow -------------------------------------------------
def main():
    # Record wall‑clock time for the full export
    export_start = time.perf_counter()
    report_dir = BASE_DIR / 'Raporty' / 'NVIDIA_NV0'
    report_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir = BASE_DIR / 'scratch' / 'nv0'
    scratch_dir.mkdir(parents=True, exist_ok=True)

    sampler = NvidiaSampler(report_dir / 'nvidia_samples.csv')
    sampler.start()

    output_path = report_dir / 'nv0_output.mp4'

    sys.path.append(str(BASE_DIR))
    from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
    from src.gui.qt.controller import AppController

    controller = AppController()
    layout = controller.layout

    ffmpeg_exe = which('ffmpeg')
    if not ffmpeg_exe:
        print('[ERROR] ffmpeg not found in PATH.', file=sys.stderr)
        sampler.stop()
        sys.exit(1)

    with CaptureStdout() as capt:
        total_frames = stream_overlay_to_ffmpeg(
            ffmpeg_exe=str(ffmpeg_exe),
            input_files=str(VIDEO_PATH),
            output_file=str(output_path),
            duration_s=duration_s,
            start_dt_utc=None,
            tz_offset_hours=0,
            speed_samples=[],
            track_samples=[],
            alt_samples=[],
            font_path='',
            layout=layout,
            field_samples={},
            max_distance_m=None,
            target_fps=fps,
            render_w=3840,
            render_h=2160,
            resolution_name='source',
            rotation_degrees=0,
            container_rotation=0,
            overlay_w=3840,
            overlay_h=2160,
            progress_cb=None,
            on_render_progress=None,
            cancel_event=None,
            active_process_holder=None,
        )
    ffmpeg_cmd_line = ''
    for line in capt.captured:
        # Capture the full ffmpeg command line regardless of prefix
        if 'ffmpeg' in line.lower() and '-hwaccel' in line.lower():
            # Assume the entire line is the command
            ffmpeg_cmd_line = line.strip()
            break
    if ffmpeg_cmd_line:
        (report_dir / 'ffmpeg_cmd.txt').write_text(ffmpeg_cmd_line + '\n', encoding='utf-8')
    else:
        print('[WARNING] Could not capture FFmpeg command.', file=sys.stderr)

    sampler.stop()

    export_end = time.perf_counter()
    export_wall_seconds = export_end - export_start
    true_fps = total_frames / export_wall_seconds if export_wall_seconds > 0 else 0.0
    summary = {
        'reference_video': str(VIDEO_PATH),
        'reference_frame_count': TARGET_FRAME_COUNT,
        'source_duration_seconds': duration_s,
        'source_fps': fps,
        'exported_frames': total_frames,
        'export_wall_seconds': export_wall_seconds,
        'true_fps': true_fps,
        'ffmpeg_command': ffmpeg_cmd_line,
        'output_file': str(output_path),
        'nvidia_smi_csv': str(report_dir / 'nvidia_samples.csv'),
    }
    (report_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')

    md = f"""# NVIDIA ETAP NV0 – Diagnostic Report

**Reference video:** `{VIDEO_PATH.name}` (expected frames: {TARGET_FRAME_COUNT})

## Source Media Information
- Duration (seconds): {duration_s:.3f}
- Source FPS (from ffprobe): {fps:.3f}
- Reference frame count: {TARGET_FRAME_COUNT}

## Export Results
- Export wall‑clock time (seconds): {export_wall_seconds:.3f}
- Exported frames: {total_frames}
- **TRUE Export FPS:** {true_fps:.2f}

## Artefacts
- FFmpeg command: `ffmpeg_cmd.txt`
- GPU utilisation samples: `nvidia_samples.csv`
- JSON summary: `summary.json`

## Preliminary Bottleneck Observations
- The pipeline reports **{true_fps:.2f} FPS** vs source FPS {fps:.3f}.
- Review `nvidia_samples.csv` for GPU utilisation (max 1 sample/sec).
- If utilisation is low or pipe write latency spikes, investigate SHM pool size or writer thread throughput.
"""
    (report_dir / 'RAPORT_NV0.md').write_text(md, encoding='utf-8')

    print('--- Diagnostic completed ---')
    print(f'Output video: {output_path}')
    print(f'Summary JSON: {report_dir / "summary.json"}')

if __name__ == '__main__':
    main()
