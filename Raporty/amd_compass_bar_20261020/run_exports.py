"""Reproduce post-change exports through the existing application harness.

The original before.mp4 was captured before code changes; do not overwrite it.
"""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
env = dict(os.environ, PYTHONUTF8="1", QT_QPA_PLATFORM="offscreen")
names = sys.argv[1:] or ["top_fit", "bottom_fit"]
for name in names:
    assert name in ("after_moving", "top_fit", "bottom_fit", "night_gpmf")
    night = name == "night_gpmf"
    layout = OUT / ("layout_top.json" if name == "top_fit" else "layout_bottom.json") if name.endswith("_fit") else ROOT / "def_layout.json"
    video = r"F:\GoPro\2026-10-16\GX010380.MP4" if night else r"F:\GoPro\2026-10-12\GX010368.MP4"
    fit = r"F:\GoPro\2026-10-16\2026-10-16_06-22-14.fit" if night else r"F:\GoPro\2026-10-12\Afternoon_Ride.fit"
    command = [sys.executable, str(ROOT / "SportCamHUD.py"), "--test-amd-export",
               "--mode", "queue" if name.endswith("_fit") else "direct", "--video", video,
               "--fit", fit, "--frames", "180" if name.endswith("_fit") else "120",
               "--start-seconds", "60", "--quality", "QUALITY", "--codec", "hevc",
               "--bitrate", "40M", "--preview-hud", "--layout", str(layout),
               "--output", str(OUT / f"{name}.mp4"), "--result-json", str(OUT / f"{name}.json")]
    print(name, flush=True)
    with (OUT / f"{name}.stdout.log").open("w", encoding="utf-8") as output:
        subprocess.run(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=240)
