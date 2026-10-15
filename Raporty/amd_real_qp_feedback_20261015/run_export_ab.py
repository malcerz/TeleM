"""A/B short AMD export for the real-QP feedback fix (canonical GX020079 pair).

Usage: python run_export_ab.py <label> <dll_path> [frames]
Writes <label>.mp4/.json/.log next to this script.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\_DEV\BikeRideHUD-main-new")
OUT = Path(__file__).resolve().parent
VIDEO = r"F:\_DEV\BikeRideHUD-amd\Video\GX020079.mp4"
FIT = r"F:\_DEV\BikeRideHUD-amd\Video\GX020079.fit"

label, dll = sys.argv[1], sys.argv[2]
frames = sys.argv[3] if len(sys.argv) > 3 else "300"
env = dict(os.environ)
env["TELEM_AMD_NATIVE_DLL"] = dll
cmd = [
    sys.executable, str(REPO / "SportCamHUD.py"), "--test-amd-export", "--mode", os.environ.get("AB_MODE", "direct"),
    "--video", VIDEO, "--fit", FIT, "--frames", frames, "--start-seconds", "0",
    "--quality", "FAST", "--codec", "hevc", "--bitrate", "40M",
    "--layout", str(REPO / "def_layout.json"),
    "--output", str(OUT / f"{label}.mp4"), "--result-json", str(OUT / f"{label}.json"),
]
with open(OUT / f"{label}.log", "w", encoding="utf-8", errors="replace") as log:
    rc = subprocess.run(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1800).returncode
print(label, "exit", rc)
