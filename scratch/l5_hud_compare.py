"""ETAP 5L — final HUD comparison: CPU_REFERENCE gauge vs GPU gauge.

Runs a short 31-frame export with AMD_NATIVE_DIAGNOSTICS=1 in each gauge mode
(GPU_SPLIT charts + GPU map in both), dumps the persistent HUD canvas and
compares the gauge bbox and the rest of the canvas.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"c:\_DEV\TeleM\.venv-1\Scripts\python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
BASE = ROOT / "Raporty" / "AMD_ETAP5G"
BASE.mkdir(parents=True, exist_ok=True)

GAUGE_BBOX = (1544, 1632, 648, 648)


def run(gauge_path: str, tag: str) -> dict:
    work = BASE / f"l5_hud_{tag}"
    work.mkdir(parents=True, exist_ok=True)
    env = {
        "AMD_NATIVE_DIAGNOSTICS": "1",
        "AMD_CHART_PATH": "GPU_SPLIT",
        "AMD_GAUGE_PATH": gauge_path,
    }
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "31", "--chart-path", "GPU_SPLIT",
         "--output", str(work / f"hud_{tag}.mp4")],
        cwd=str(work), env={**os.environ, **env},
        capture_output=True, text=True,
    )
    return {"rc": proc.returncode, "work": work, "out": proc.stdout + proc.stderr}


def load_canvas(work: Path, frame: int):
    p = work / f"H_hud_canvas_{frame}.png"
    if not p.exists():
        return None
    from PIL import Image
    import numpy as np
    return np.asarray(Image.open(p).convert("RGBA"), dtype=np.int16)


def main() -> int:
    import numpy as np
    a = run("CPU_REFERENCE", "cpu")
    b = run("GPU", "gpu")
    print(f"rc: CPU_REFERENCE={a['rc']} GPU={b['rc']}")
    if a["rc"] != 0 or b["rc"] != 0:
        print("--- CPU tail ---")
        print("\n".join(a["out"].splitlines()[-15:]))
        print("--- GPU tail ---")
        print("\n".join(b["out"].splitlines()[-15:]))
        return 1
    overall = True
    for frame in (30,):
        ca = load_canvas(a["work"], frame)
        cb = load_canvas(b["work"], frame)
        if ca is None or cb is None:
            print(f"  frame {frame}: canvas missing", flush=True)
            overall = False
            continue
        d = np.abs(ca - cb)
        bx, by, bw, bh = GAUGE_BBOX
        mask = np.zeros(d.shape[:2], dtype=bool)
        mask[by:by + bh, bx:bx + bw] = True
        outside = d[~mask]
        inside = d[mask]
        # inside: alpha-aware — the gauge has partial alpha; count per-threshold
        diffs = inside.max(axis=1)
        print(
            f"  frame {frame}: outside-gauge MAE={outside.mean():.6f} MAX={outside.max()} "
            f"diff_px={int((outside.max(axis=1) > 0).sum())}",
            flush=True,
        )
        print(
            f"    in-gauge MAE={inside.mean():.6f} MAX={inside.max()} "
            f"n>1={(diffs > 1).sum()} n>2={(diffs > 2).sum()} "
            f"n>4={(diffs > 4).sum()} n>8={(diffs > 8).sum()}",
            flush=True,
        )
        ok_out = outside.max() == 0
        ok_in = inside.max() == 0
        overall &= ok_out and ok_in
    print("RESULT:", "PASS-EXACT" if overall else "CHECK")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
