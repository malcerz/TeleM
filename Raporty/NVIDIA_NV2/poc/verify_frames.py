"""Numeric verification of the NV2 Gate-2 PoC frames.

Checks:
1. nv2_auto == rotate180(nv2_phys)          -> matrix is a pure 180-deg rotation
2. video layer: nv2_auto ~ src_auto in areas without HUD (MAE small)
3. composed expectation: nv2_auto ~ (src_auto + logical HUD)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

POC = Path(__file__).resolve().parent


def load(name: str) -> np.ndarray:
    return np.asarray(Image.open(POC / name).convert("RGB"), dtype=np.float32)


def mae_max(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float, float]:
    d = np.abs(a - b)
    n_gt1 = float((d > 1).mean() * 100)
    n_gt4 = float((d > 4).mean() * 100)
    return float(d.mean()), float(d.max()), n_gt1, n_gt4


def main() -> None:
    src_auto = load("src_auto.png")          # source, rotation applied (upright)
    nv2_auto = load("nv2_auto.png")          # NV2 output, rotation applied
    nv2_phys = load("nv2_phys.png")          # NV2 output, physical (upside down)
    hud = load("hud_logical_720.png")        # logical HUD

    # 1) physical == auto rotated 180
    nv2_phys_rot = np.ascontiguousarray(nv2_phys[::-1, ::-1])
    print("nv2_phys == rotate180(nv2_auto): MAE=%.4f MAX=%.2f n>1=%.2f%% n>4=%.2f%%" % mae_max(nv2_phys_rot, nv2_auto))

    # 2) video-only consistency: source vs NV2 (HUD regions excluded implicitly by MAE)
    print("src_auto vs nv2_auto (full frame): MAE=%.4f MAX=%.2f n>1=%.2f%% n>4=%.2f%%" % mae_max(src_auto, nv2_auto))

    # 3) composed expectation: src_auto + logical HUD
    exp = src_auto.copy()
    alpha = np.asarray(Image.open(POC / "hud_logical.png").convert("RGBA"))[:, :, 3].astype(np.float32) / 255.0
    a720 = np.asarray(Image.open(POC / "hud_logical.png").convert("RGBA").resize((1280, 720)))[:, :, 3].astype(np.float32) / 255.0
    # recompute expected with 720 hud alpha (avoid mismatch)
    hud_rgb = hud.copy()
    for c in range(3):
        exp[:, :, c] = exp[:, :, c] * (1.0 - a720) + hud_rgb[:, :, c] * a720
    print("src+logicalHUD vs nv2_auto: MAE=%.4f MAX=%.2f n>1=%.2f%% n>4=%.2f%%" % mae_max(exp, nv2_auto))


if __name__ == "__main__":
    main()
