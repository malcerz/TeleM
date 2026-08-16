"""ETAP 5L — diagnose the in-gauge diff (CPU_REFERENCE vs GPU gauge)."""
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


def run(gauge_path, tag):
    work = BASE / f"l5_diag_{tag}"
    work.mkdir(parents=True, exist_ok=True)
    env = {"AMD_NATIVE_DIAGNOSTICS": "1", "AMD_CHART_PATH": "GPU_SPLIT",
           "AMD_GAUGE_PATH": gauge_path}
    subprocess.run([PY, str(RUNNER), "--frames", "31", "--chart-path", "GPU_SPLIT",
                    "--output", str(work / f"x.mp4")],
                   cwd=str(work), env={**os.environ, **env}, capture_output=True, text=True)
    return work


def main() -> int:
    import numpy as np
    from PIL import Image
    a = run("CPU_REFERENCE", "cpu")
    b = run("GPU", "gpu")
    ca = np.asarray(Image.open(a / "H_hud_canvas_30.png").convert("RGBA"), dtype=np.int16)
    cb = np.asarray(Image.open(b / "H_hud_canvas_30.png").convert("RGBA"), dtype=np.int16)
    bx, by, bw, bh = GAUGE_BBOX
    ga = ca[by:by+bh, bx:bx+bw]
    gb = cb[by:by+bh, bx:bx+bw]
    d = np.abs(ga - gb)
    diffs = d.max(axis=2)
    ys, xs = np.where(diffs > 0)
    print(f"diff px: {len(ys)}")
    # classify: what are the alpha values of the CPU gauge at diff pixels?
    a_alpha = ga[ys, xs, 3]
    b_alpha = gb[ys, xs, 3]
    print("CPU gauge alpha at diff px: min", a_alpha.min(), "max", a_alpha.max())
    print("GPU gauge alpha at diff px: min", b_alpha.min(), "max", b_alpha.max())
    # histogram of CPU alpha at diff pixels
    import collections
    h = collections.Counter(int(v) for v in a_alpha)
    print("CPU alpha histogram (diff px):", dict(sorted(h.items())))
    # show a few diff pixels
    for y, x in zip(ys[:10], xs[:10]):
        print(f"  ({x},{y}) CPU={tuple(ga[y,x])} GPU={tuple(gb[y,x])} d={tuple(d[y,x])}")
    # save diff map (amplified)
    Image.fromarray(np.clip(diffs.astype(np.float32) * 16, 0, 255).astype(np.uint8), "L").save(
        str(BASE / "l5_gauge_diff_amplified.png"))
    Image.fromarray(ga.astype(np.uint8), "RGBA").save(str(BASE / "l5_gauge_cpu.png"))
    Image.fromarray(gb.astype(np.uint8), "RGBA").save(str(BASE / "l5_gauge_gpu.png"))
    print("saved l5_gauge_diff_amplified.png / cpu / gpu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
