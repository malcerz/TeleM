"""ETAP 2E — visual verification of the smoke output (lean moves, regions live)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT = Path("scratch/etap2e_smoke")


def bbox_for(cfg: dict, W: int, H: int) -> tuple[int, int, int, int]:
    size = float(cfg.get("size", 10.0))
    if size <= 1.0:
        s_px = int(round(size * W))
    else:
        s_px = int(round((size / 100.0) * W))
    cx = int(round(float(cfg["x"]) / 100.0 * W))
    cy = int(round(float(cfg["y"]) / 100.0 * H))
    half = s_px // 2
    return (
        max(0, cx - half),
        max(0, cy - half),
        min(W, cx + half),
        min(H, cy + half),
    )


def main() -> None:
    layout = json.load(open("def_layout.json", encoding="utf-8"))
    inds = layout["indicators"]
    frames = [np.asarray(Image.open(OUT / f"f{i}.png").convert("RGB")) for i in (1, 2, 3)]
    H, W = frames[0].shape[:2]
    print(f"frame size: {W}x{H}")

    def region_diff(name: str, box: tuple[int, int, int, int]) -> None:
        x0, y0, x1, y1 = box
        d12 = np.abs(frames[0][y0:y1, x0:x1].astype(int) - frames[1][y0:y1, x0:x1].astype(int)).mean()
        d13 = np.abs(frames[0][y0:y1, x0:x1].astype(int) - frames[2][y0:y1, x0:x1].astype(int)).mean()
        print(f"{name:22s} bbox={box} mean|d(10,60)|={d12:7.3f} mean|d(10,150)|={d13:7.3f}")
        return d13

    lean_cfg = inds["lean_indicator"]
    lean_box = bbox_for(lean_cfg, W, H)
    d_lean = region_diff("lean_indicator", lean_box)
    gauge_box = bbox_for(inds["speed_text"], W, H)
    region_diff("speed_text(gauge)", gauge_box)
    region_diff("fit_cadence_text", bbox_for(inds["fit_cadence_text"], W, H))
    region_diff("fit_heart_rate_text", bbox_for(inds["fit_heart_rate_text"], W, H))

    # Save crops for eyeballing
    for i, fr in enumerate((frames[0], frames[1], frames[2]), start=1):
        x0, y0, x1, y1 = lean_box
        Image.fromarray(fr[y0:y1, x0:x1]).save(OUT / f"lean_crop_f{i}.png")

    # Lean pixel-level uniqueness across the three frames
    x0, y0, x1, y1 = lean_box
    c0 = frames[0][y0:y1, x0:x1].astype(np.int16)
    uniq_rot = len({
        (c0.tobytes(), frames[1][y0:y1, x0:x1].tobytes())[0:1],
        frames[1][y0:y1, x0:x1].tobytes(),
        frames[2][y0:y1, x0:x1].tobytes(),
    })
    print(f"LEAN FINAL ROTATIONS UNIQUE (3 sampled frames): {uniq_rot}")
    print("LEAN INDICATOR MOVES:", "YES" if d_lean > 0.5 and uniq_rot > 1 else "NO")


if __name__ == "__main__":
    main()
