"""Compass geometry v2 evidence: legacy parity, migration parity, scaling, subticks.

* legacy: v1 configs rendered by the new renderer vs the HEAD renderer
  (``git show <rev>:src/indicators/gauge.py`` imported as a side module),
* migration: migrate_compass_geometry(v1) rendered on the 4K canvas vs the
  HEAD v1 render (must be identical),
* scaling: ring/needle thickness at Rozmiar 50/100/200 % on 4K and Preview,
* subticks: tick count for 0/1/4/8 subticks.

Usage: python compass_geometry_check.py <out_dir> [--rev HEAD]
"""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.indicators import gauge as new_gauge  # noqa: E402
from src.indicators.dispatcher import _render_value_indicator  # noqa: E402
from src.indicators.helpers import _STATIC_CACHE  # noqa: E402

FONT = r"C:\Windows\Fonts\arial.ttf"
USER = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))["indicators"]["compass"]


def load_head(out_dir: Path, rev: str):
    src = subprocess.run(["git", "show", f"{rev}:src/indicators/gauge.py"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    path = out_dir / "_gauge_head.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("src.indicators._gauge_head", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def render(gmod, cfg, w, h, value=123.4, ss=2):
    """Render through the real dispatcher with ``gmod`` as the gauge module."""
    import src.indicators.dispatcher as disp
    import src.indicators.gauge as g
    saved = g._render_compass_indicator
    g._render_compass_indicator = gmod._render_compass_indicator
    _STATIC_CACHE.clear()
    try:
        layout = {"indicators": {"compass": cfg}, "global": {"text_outline": 3}}
        img, *_ = disp._render_value_indicator(w, h, layout, FONT, "compass", value, "°", "C",
                                               cfg_override=cfg, supersample=ss)
    finally:
        g._render_compass_indicator = saved
    return np.asarray(img.convert("RGBA")).astype(np.int16)


def diff(a, b):
    if a.shape != b.shape:
        return {"shape_a": a.shape, "shape_b": b.shape, "identical": False}
    d = np.abs(a - b)
    return {"max_diff": int(d.max()), "mae": float(d.mean()),
            "different_pixels": int((d.max(axis=2) > 0).sum()), "identical": bool(d.max() == 0)}


def ring_thickness(img):
    """Median ink thickness [px] of the outermost opaque band (the ring).

    Radial rays every 1°; on each ray, from outside inwards, the alpha of the
    first contiguous band is integrated (sub-pixel), the shadow is disabled.
    """
    a = img[:, :, 3].astype(np.float64) / 255.0
    h, w = a.shape
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    r_max = min(cx, cy)
    step = 0.25
    vals = []
    for deg in range(0, 360):
        t = np.deg2rad(deg)
        rs = np.arange(r_max, 0, -step)
        xs = np.clip(np.round(cx + np.cos(t) * rs).astype(int), 0, w - 1)
        ys = np.clip(np.round(cy + np.sin(t) * rs).astype(int), 0, h - 1)
        prof = a[ys, xs]
        idx = np.where(prof > 0.08)[0]
        if idx.size == 0:
            continue
        i0 = idx[0]
        i1 = i0
        while i1 < prof.size and prof[i1] > 0.08:
            i1 += 1
        vals.append(float(prof[i0:i1].sum() * step))
    return round(float(np.median(vals)), 2) if vals else 0.0


def base_cfgs():
    user = {k: v for k, v in USER.items()}
    default_like = {"enabled": True, "form": "gauge", "gauge_style": "compass", "x": 50, "y": 50,
                    "size": 7.8, "font_size": 1.2, "compass_rotation_mode": "rose",
                    "compass_tick_degrees": 15, "compass_major_tick_degrees": 45}
    needle = dict(user, compass_rotation_mode="needle")
    effects = dict(user, outline_enabled=True, outline_width=2.0, shadow_enabled=True,
                   shadow_length=6.0, shadow_distance=4.0, shadow_angle=60.0, size=12.0)
    return {"user_rose": user, "default_like": default_like, "user_needle": needle, "effects_big": effects}


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    rev = sys.argv[sys.argv.index("--rev") + 1] if "--rev" in sys.argv else "HEAD"
    head = load_head(out, rev)
    res = {"rev": rev, "legacy_parity": {}, "migration_parity_4k": {}, "scaling": {}, "subticks": {}}
    canvases = {"4k": (3840, 2160), "preview": (1060, 596)}
    for name, cfg in base_cfgs().items():
        for cname, (w, h) in canvases.items():
            res["legacy_parity"][f"{name}@{cname}"] = diff(render(head, copy.deepcopy(cfg), w, h),
                                                          render(new_gauge, copy.deepcopy(cfg), w, h))
        mig = copy.deepcopy(cfg)
        new_gauge.migrate_compass_geometry(mig)
        res["migration_parity_4k"][name] = diff(render(head, copy.deepcopy(cfg), 3840, 2160),
                                                render(new_gauge, mig, 3840, 2160))
    # Proportional scaling (v2): Rozmiar 50/100/200 % of the user's size.
    v2 = copy.deepcopy(USER)
    v2["shadow_enabled"] = False
    new_gauge.migrate_compass_geometry(v2)
    for pct in (50, 100, 200):
        cfg = dict(v2, size=float(USER["size"]) * pct / 100.0)
        row = {}
        for cname, (w, h) in canvases.items():
            img = render(new_gauge, cfg, w, h)
            from PIL import Image
            Image.fromarray(img.astype(np.uint8)).save(out / f"size{pct}_{cname}.png")
            row[cname] = {"raster": list(img.shape[:2]), "ring_px": ring_thickness(img)}
        cfg_legacy = dict(copy.deepcopy(USER), shadow_enabled=False, size=float(USER["size"]) * pct / 100.0)
        row["4k_legacy_ring_px"] = ring_thickness(render(head, cfg_legacy, 3840, 2160))
        res["scaling"][f"{pct}%"] = row
    for n in (0, 1, 4, 8, 14, 99):
        cfg = dict(v2, compass_subticks=n, compass_major_tick_degrees=45)
        angles = new_gauge.compass_tick_angles(cfg)
        res["subticks"][str(n)] = {"ticks": len(angles), "majors": sum(1 for _, m in angles if m),
                                   "spacing_deg": round(angles[1][0] - angles[0][0], 4) if len(angles) > 1 else None}
        from PIL import Image
        Image.fromarray(render(new_gauge, dict(cfg, size=16.0), 1060, 596).astype(np.uint8)).save(out / f"subticks{n}.png")
    (out / "geometry_check.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=1))
    ok = all(v["identical"] for v in res["legacy_parity"].values()) and \
        all(v["identical"] for v in res["migration_parity_4k"].values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
