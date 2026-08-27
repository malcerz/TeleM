"""ETAP 2E TEST 3 — preview integrity checks (headless).

1) Playback-loop mutation check: post-fix, last_src_pil stays UNCOMPOSITED
   while render_preview(inplace=True) mutates only an exclusive copy.
2) Preview vs reference overlay geometry parity (same layout+telemetry).
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.indicators.compositor import compose_overlay, render_preview
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data

VIDEO = Path("Video/GX030120.MP4")
W = H = 640


def make_frame() -> Image.Image:
    img = Image.new("RGBA", (W, H), (30, 30, 30, 255))
    for y in range(H):
        img.putpixel((W // 2, y), (200, 200, 200, 255))
    return img


def build_args(layout, od):
    return dict(
        layout=layout, font_path="arial.ttf",
        date_text=od["date_text"], time_text=od["time_text"],
        speed_value=od["speed_value"], distance_m=od["distance_m"],
        max_distance_m=od["max_distance_m"], alt_value=od["alt_value"],
        min_alt=od["min_alt"], max_alt=od["max_alt"],
        iso_value=od["iso_value"], exposure_value=od["exposure_value"],
        temp_value=od["temp_value"], indicator_values=od["indicator_values"],
        max_speed_kmh=od["max_speed_kmh"], power_value=od["power_value"],
        atemp_value=od["atemp_value"], hr_value=od["hr_value"],
        cad_value=od["cad_value"], battery_value=od["battery_value"],
        _bboxes={}, extra_indicators=od["extra_indicators"],
        chart_data=od["chart_data"], current_position=0.01,
        gps_track=[], target_dt=od["target_dt"],
        start_dt_utc=od["start_dt_utc"], elapsed_seconds=5.0,
        avg_speed_kmh=0.0,
    )


def main() -> None:
    layout = json.load(open("def_layout.json", encoding="utf-8"))
    tm = TelemetryDataManager()
    apply_processed_cache(tm, read_processed_cache(VIDEO))
    od = prepare_overlay_frame_data(
        layout=layout,
        target_dt=tm.start_dt_utc + timedelta(seconds=5),
        tz_offset_hours=2,
        start_dt_utc=tm.start_dt_utc,
        speed_samples=tm.speed_samples,
        track_samples=tm.track_samples,
        alt_samples=tm.alt_samples,
    )
    args = build_args(layout, od)

    # ── 1) playback-loop mutation check (ETAP 2E semantics) ──────────────
    clean = make_frame()
    out1 = render_preview(clean.copy(), inplace=True, **args)
    last_src_pil = clean.copy()          # protected clean reference
    out2 = render_preview(last_src_pil.copy(), inplace=True, **args)

    d12 = int(np.abs(np.asarray(out1.convert("RGB"), int)
                     - np.asarray(out2.convert("RGB"), int)).max())
    ref_drift = int(np.abs(np.asarray(last_src_pil.convert("RGB"), int)
                           - np.asarray(clean.convert("RGB"), int)).max())
    print(f"clean reference drift after inplace pass: {ref_drift} (must be 0)")
    print(f"composite#2 vs #1 max|diff|: {d12} (must be 0)")
    double_compose = not (d12 == 0 and ref_drift == 0)
    print("PREVIEW DOUBLE COMPOSE:", "YES" if double_compose else "NO")

    shared = make_frame()
    l1 = render_preview(shared, inplace=True, **args)
    l2 = render_preview(shared, inplace=True, **args)
    stack = int(np.abs(np.asarray(l1.convert("RGB"), int)
                       - np.asarray(l2.convert("RGB"), int)).max())
    print(f"legacy shared-object pattern diff after 2nd pass: {stack} "
          f"({'stacking reproduced' if stack else 'no stacking'})")

    # ── 2) preview vs reference geometry parity ──────────────────────────
    bf, bp = {}, {}
    common = dict(
        canvas_w=W, canvas_h=H, layout=layout, font_path="arial.ttf",
        indicator_values=od["indicator_values"],
        max_speed_kmh=od["max_speed_kmh"], power_value=od["power_value"],
        atemp_value=od["atemp_value"], hr_value=od["hr_value"],
        cad_value=od["cad_value"], battery_value=od["battery_value"],
        extra_indicators=od["extra_indicators"], chart_data=od["chart_data"],
        current_position=0.01, gps_track=[], target_dt=od["target_dt"],
        start_dt_utc=od["start_dt_utc"], elapsed_seconds=5.0,
        avg_speed_kmh=0.0,
    )
    head = dict(
        date_text=od["date_text"], time_text=od["time_text"],
        speed_value=od["speed_value"], distance_m=od["distance_m"],
        max_distance_m=od["max_distance_m"], alt_value=od["alt_value"],
        min_alt=od["min_alt"], max_alt=od["max_alt"],
        iso_value=od["iso_value"], exposure_value=od["exposure_value"],
        temp_value=od["temp_value"],
    )
    compose_overlay(_bboxes=bf, **head, **common)
    compose_overlay(_bboxes=bp, fast_preview=True, **head, **common)

    keys = sorted(set(bf) & set(bp))
    bad = []
    for k in keys:
        rel = tuple(round(v / s, 4) for v, s in zip(bf[k], (W, H, W, H)))
        relp = tuple(round(v / s, 4) for v, s in zip(bp[k], (W, H, W, H)))
        if rel != relp:
            bad.append((k, rel, relp))
    print(f"indicators compared: {len(keys)}; geometry mismatches: {len(bad)}")
    for k, r, p in bad[:10]:
        print("  MISMATCH", k, "ref", r, "prev", p)
    print("sample bboxes:", {k: bp[k] for k in keys[:6]})
    print("PREVIEW RAW OVERLAY CORRECT:",
          "YES" if (not bad and keys) else "NO")


if __name__ == "__main__":
    main()
