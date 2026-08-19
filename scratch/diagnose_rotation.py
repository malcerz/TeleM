"""Diagnose why video is upside down during scaling."""
import json
import sys
import ctypes
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
from src.video_helpers import ffprobe_stream_info

def test_rotation_diagnostics():
    mp4_in = root / "Video" / "GX030120.MP4"
    json_path = root / "Video" / "GX030120.json"
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    
    # We will test 4K export vs 1080p export
    # And extract frame 30 to see the orientation of the video!
    import subprocess
    diag_dir = root / "scratch" / "rotation_diag"
    diag_dir.mkdir(parents=True, exist_ok=True)
    
    # Let's extract frame 30 directly from GX030120.MP4 with ffmpeg with and without autorotate
    # FFmpeg auto-rotates by default using container metadata
    subprocess.run([
        r"C:\tools\ffmpeg.exe", "-y", "-ss", "1.0", "-i", str(mp4_in),
        "-vframes", "1", "-q:v", "2", str(diag_dir / "raw_ffmpeg_autorotated.png")
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # FFmpeg without auto-rotate (-noautorotate)
    subprocess.run([
        r"C:\tools\ffmpeg.exe", "-y", "-noautorotate", "-ss", "1.0", "-i", str(mp4_in),
        "-vframes", "1", "-q:v", "2", str(diag_dir / "raw_ffmpeg_noautorotate.png")
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    print("Extracted raw FFmpeg reference frames (with and without autorotate).")

if __name__ == "__main__":
    test_rotation_diagnostics()
