"""ETAP 5K — section 22: FINAL HUD comparison GPU (5J) vs GPU_SPLIT.

Runs a short 31-frame export with AMD_NATIVE_DIAGNOSTICS=1 in each mode so the
native side dumps the persistent HUD canvas (H_hud_canvas_30/300/900.png), then
compares the canvases.  Outside the chart bboxes MAE=0 / MAX=0 is mandatory
(both modes share the identical CPU HUD path for everything else); inside the
chart bboxes the GPU_SPLIT assembly was already proven byte-identical.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"c:\_DEV\TeleM\.venv-1\Scripts\python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
BASE = ROOT / "Raporty" / "AMD_ETAP5G"
BASE.mkdir(parents=True, exist_ok=True)

CHART_BBOXES = {
    "fit_cadence_text": (185, 1589, 1160, 511),
    "fit_heart_rate_text": (2477, 1592, 1160, 511),
}

FRAMES = (30, 300, 900)


def run(mode: str, tag: str) -> dict:
    work = BASE / f"k5_hud_{tag}"
    work.mkdir(parents=True, exist_ok=True)
    env = {
        "AMD_NATIVE_DIAGNOSTICS": "1",
        "AMD_CHART_PATH": mode,
    }
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "31", "--chart-path", mode,
         "--output", str(work / f"hud_{tag}.mp4")],
        cwd=str(work), env={**__import__("os").environ, **env},
        capture_output=True, text=True,
    )
    return {"rc": proc.returncode, "work": work}


def load_canvas(work: Path, frame: int):
    p = work / f"H_hud_canvas_{frame}.png"
    if not p.exists():
        return None
    from PIL import Image
    import numpy as np
    return np.asarray(Image.open(p).convert("RGBA"), dtype=np.int16)


def main() -> int:
    import numpy as np
    a = run("GPU", "gpu")
    b = run("GPU_SPLIT", "split")
    print(f"rc: GPU={a['rc']} GPU_SPLIT={b['rc']}")
    overall = True
    for frame in FRAMES:
        ca = load_canvas(a["work"], frame)
        cb = load_canvas(b["work"], frame)
        if ca is None or cb is None:
            print(f"  frame {frame}: canvas missing", flush=True)
            overall = False
            continue
        if ca.shape != cb.shape:
            print(f"  frame {frame}: size mismatch {ca.shape} vs {cb.shape}", flush=True)
            overall = False
            continue
        d = np.abs(ca - cb)
        # outside chart bboxes
        mask = np.zeros(d.shape[:2], dtype=bool)
        for _, (bx, by, bw, bh) in CHART_BBOXES.items():
            mask[by:by + bh, bx:bx + bw] = True
        outside = d[~mask]
        inside_all = d[mask]
        print(
            f"  frame {frame}: outside-charts MAE={outside.mean():.6f} "
            f"MAX={outside.max()} diff_px={int((outside.max(axis=1) > 0).sum() if outside.size else 0)} "
            f"| in-charts MAE={inside_all.mean():.6f} MAX={inside_all.max()}",
            flush=True,
        )
        ok_out = outside.max() == 0
        overall &= ok_out
    print("RESULT:", "PASS-EXACT(outside charts)" if overall else "CHECK")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
