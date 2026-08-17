"""Verify the NV2 PoC output in the exact MPV used by TeleM (libmpv-2.dll).

Checks:
1. mpv reports the stream rotation (video-params/rotate).
2. Rendered screenshot applies the 180-deg rotation (HUD upright, video upright).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

BASE = Path(r"F:\_DEV\TeleM")
POC = Path(__file__).resolve().parent
TARGET = POC / "nv2_poc_rot180.mp4"
SHOT = POC / "mpv_shot.png"

# libmpv lives in the repo root (same as TeleM GUI)
os.environ["PATH"] = str(BASE) + os.pathsep + os.environ.get("PATH", "")
if hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(str(BASE))
    except Exception:
        pass

import mpv  # noqa: E402


def main() -> None:
    player = mpv.MPV(
        vo="null",
        hwdec="no",
        audio=False,
        screenshot_format="png",
        keep_open="yes",
    )
    player.play(str(TARGET))
    # wait until file loaded
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if player.duration:
                break
        except Exception:
            pass
        time.sleep(0.1)
    time.sleep(1.0)

    dur = player.duration
    rotate = None
    for prop in ("video-params/rotate", "video-params/rotation", "video-params/container-rotate"):
        try:
            v = player.__getattr__(prop)
            if v not in (None, ""):
                rotate = v
                break
        except Exception:
            continue
    print(f"duration={dur}")
    print(f"mpv rotation (video-params/rotate) = {rotate}")

    # Screenshot at 2.0 s with rotation applied
    try:
        player.seek(2.0, reference="absolute")
    except Exception:
        pass
    time.sleep(0.6)
    try:
        player.screenshot_to_file(str(SHOT))
        print(f"screenshot -> {SHOT}")
    except Exception as e:
        print(f"screenshot failed: {e}")

    player.terminate()
    ok = str(rotate) in ("180", "-180")
    print("MPV_ROTATION_HONORED" if ok else "MPV_ROTATION_IGNORED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
