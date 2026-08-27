"""ETAP 2F — lean_indicator per-frame cost breakdown (real project data).

Production parameters (3840x2160, def_layout.json lean_indicator, ss=1):
    g        = max(32, int(s(8.0, 3840)))          -> 307 px
    icon     = rower_ico.png fit into 307 box      -> 258x307
    rot pad  = 2 * max(gw, gh) + 4                -> 618 x 618 RGBA
    pivot    = bottom-centre of the graphic

Phases measured over N frames using REAL telemetry values from the production
precompute pipeline (GX030120 + def_layout.json):
    full_call   whole _render_lean_indicator(...)
    text_metrics dummy Image.new + textbbox calls (title/value)
    pad_build    Image.new(pad,pad) + alpha_composite(graphic)  [per frame!]
    rotate       pad_img.rotate(angle, BICUBIC)
    compose      img.alpha_composite(rotated, paste_xy)
    value_draw   _draw_text_bounded_cached(value tile)
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.frame_data import build_active_fit_field_plan
from src.indicators.helpers import load_font, s
from src.indicators.lean import (
    _draw_text_bounded_cached,
    _graphic_pivot,
    _load_lean_graphic,
    _render_lean_indicator,
    _rotate_paste_params,
    lean_angle,
)
from src.ffmpeg.worker_cache import init_worker
from src.telemetry_precompute import build_telemetry_cache

VIDEO = Path("Video/GX030120.MP4")
LAYOUT_PATH = Path("def_layout.json")
FRAMES = 300
FPS = 30000.0 / 1001.0
CANVAS_W, CANVAS_H = 3840, 2160


def build_production_args(layout: dict, font_path: str) -> dict:
    """Replicate dispatcher.render_value_indicator argument computation."""
    cfg = layout["indicators"]["lean_indicator"]
    min_dim = min(CANVAS_W, CANVAS_H)
    outline_raw = int(layout.get("global", {}).get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))
    fs_val = cfg.get("font_size") if "font_size" in cfg else cfg.get("size", 0.02)
    fs = max(8, s(fs_val, min_dim))
    raw_t = float(cfg.get("thickness", 1))
    rel = 0.6 + (raw_t - 1) * 0.2
    thickness = float(max(1, s(rel, min_dim)))
    size_px = s(cfg.get("size", 0.1), CANVAS_W)
    return dict(
        canvas_w=CANVAS_W, canvas_h=CANVAS_H,
        layout=layout, font_path=font_path,
        key="lean_indicator", unit="°", label="PRZECHYŁ",
        cfg=cfg, min_dim=min_dim, outline=outline,
        fs=fs, font=load_font(font_path, fs),
        val_min=float(cfg.get("min_val", 0)), val_max=float(cfg.get("max_val", 100)),
        ticks=int(cfg.get("ticks", 0)), thickness=thickness,
        size_px=size_px, ss=1,
    )


def collect_real_values(layout: dict) -> list:
    """Real lean source values via the production precompute pipeline."""
    tm = TelemetryDataManager()
    processed = read_processed_cache(VIDEO)
    assert processed is not None, "processed cache missing"
    apply_processed_cache(tm, processed)
    field_samples = {
        "speed_samples": tm.speed_samples,
        "track_samples": tm.track_samples,
        "alt_samples": tm.alt_samples,
        "heading_samples": tm.heading_samples,
        "gpx_heading_samples": tm.gpx_heading_samples,
        "slope_samples": tm.slope_samples,
        "gpx_slope_samples": tm.gpx_slope_samples,
        "iso_samples": tm.iso_samples,
        "exposure_samples": tm.exposure_samples,
        "temperature_samples": tm.temperature_samples,
        "accel_x_samples": tm.accel_x_samples,
        "accel_y_samples": tm.accel_y_samples,
        "accel_z_samples": tm.accel_z_samples,
        "accel_magnitude_samples": tm.accel_magnitude_samples,
        "gyro_x_samples": tm.gyro_x_samples,
        "gyro_y_samples": tm.gyro_y_samples,
        "gyro_z_samples": tm.gyro_z_samples,
        "gyro_magnitude_samples": tm.gyro_magnitude_samples,
    }
    fit_data = tm.fit_data or {}
    init_worker(
        video_width=CANVAS_W, video_height=CANVAS_H, font_path="",
        layout=layout, field_samples=field_samples,
        iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples, fit_data=fit_data,
        gps_track=(tm.gps_track or []), start_dt_utc=tm.start_dt_utc,
        target_fps=FPS, total_overlay_frames=FRAMES,
    )
    cache = build_telemetry_cache(
        layout=layout, base_dt=tm.start_dt_utc, tz_offset_hours=2.0,
        start_dt_utc=tm.start_dt_utc, speed_samples=tm.speed_samples,
        track_samples=tm.track_samples, alt_samples=tm.alt_samples,
        iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples, fit_data=fit_data,
        gps_track=tm.gps_track or [], chart_data={},
        resolve_cache_value=None, _range_cache={},
        fit_field_plan=build_active_fit_field_plan(layout, list(fit_data.keys())),
        total_frames=FRAMES, target_fps=FPS,
    )
    return [cache.lookup(i)["extra_indicators"]["lean_indicator"][0]
            for i in range(FRAMES)]



def p95(xs: list) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]


def report(name: str, samples_ms: list) -> None:
    print(
        f"  {name:<14} AVG={statistics.fmean(samples_ms):8.3f} ms  "
        f"MEDIAN={statistics.median(samples_ms):8.3f} ms  "
        f"P95={p95(samples_ms):8.3f} ms"
    )


def main() -> None:
    layout = json.load(open(LAYOUT_PATH, encoding="utf-8"))
    args = build_production_args(layout, "arial.ttf")
    cfg = args["cfg"]

    print("collecting real lean source values ...")
    values = collect_real_values(layout)
    angles = [lean_angle(v, cfg) for v in values]
    uniq = len({round(a, 6) for a in angles})
    print(f"values n={len(values)} unique_angles={uniq} "
          f"range=[{min(angles):+.2f}, {max(angles):+.2f}] deg")

    # --- geometry probe ---------------------------------------------------
    import src.indicators.lean as L

    g = max(32, int(args["size_px"]))
    graphic = _load_lean_graphic(cfg, g)
    gw, gh = graphic.size
    pivot_px, pivot_py = _graphic_pivot(cfg, gw, gh)
    pad_w, *_ = _rotate_paste_params(gw, gh, pivot_px, pivot_py, 400, 100.0)

    out0, _, _, _ = _render_lean_indicator(**args, value=angles[0], formatted_val=None)
    raster_w, raster_h = out0.size
    print(f"\nGEOMETRY: source sprite {gw}x{gh} | rotation pad {pad_w}x{pad_w} | "
          f"widget raster {raster_w}x{raster_h}")

    base_stats0 = L._LEAN_BASE_CACHE.stats()

    # --- phase probes -------------------------------------------------------
    t_full, t_metrics, t_pad, t_rot, t_comp, t_vdraw = ([] for _ in range(6))
    bb_areas, bb_union = [], None
    bicubic = (Image.Resampling.BICUBIC if hasattr(Image, "Resampling")
               else Image.BICUBIC)

    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    title_fs = max(8, int(round(float(cfg.get("title_font_scale", 1.0)) * args["fs"])))
    value_fs = max(8, int(round(float(cfg.get("value_font_scale", 0.9)) * args["fs"])))
    title_font = load_font("arial.ttf", title_fs)
    value_font = load_font("arial.ttf", value_fs)
    stroke = max(0, int(round(max(1, args["outline"]))))
    title = str(cfg.get("title_text", "PRZECHYŁ")).strip().upper()

    for i in range(FRAMES):
        v = values[i]
        t0 = time.perf_counter()
        img, _, _, _ = _render_lean_indicator(**args, value=v, formatted_val=None)
        t1 = time.perf_counter()
        t_full.append((t1 - t0) * 1000)

        a = lean_angle(v, cfg)
        vt = f"{a:+.0f}\u00b0"

        t0 = time.perf_counter()
        dd.textbbox((0, 0), title, font=title_font, stroke_width=stroke)
        dd.textbbox((0, 0), vt, font=value_font, stroke_width=stroke)
        t1 = time.perf_counter()
        t_metrics.append((t1 - t0) * 1000)

        t0 = time.perf_counter()
        pad_img = Image.new("RGBA", (pad_w, pad_w), (0, 0, 0, 0))
        pad_img.alpha_composite(
            graphic,
            (int(round(pad_w / 2.0 - pivot_px)), int(round(pad_w / 2.0 - pivot_py))),
        )
        t1 = time.perf_counter()
        t_pad.append((t1 - t0) * 1000)

        t0 = time.perf_counter()
        rotated = pad_img.rotate(a, resample=bicubic)
        t1 = time.perf_counter()
        t_rot.append((t1 - t0) * 1000)

        bb = rotated.getbbox()
        if bb is not None:
            bb_areas.append((bb[2] - bb[0]) * (bb[3] - bb[1]))
            if bb_union is None:
                bb_union = list(bb)
            else:
                bb_union = [min(bb_union[0], bb[0]), min(bb_union[1], bb[1]),
                            max(bb_union[2], bb[2]), max(bb_union[3], bb[3])]

        t0 = time.perf_counter()
        img.alpha_composite(rotated, (10, 10))
        t1 = time.perf_counter()
        t_comp.append((t1 - t0) * 1000)

        t0 = time.perf_counter()
        _draw_text_bounded_cached(
            img, (img.width / 2, 50), vt, font=value_font, font_path="arial.ttf",
            fill=(255, 255, 255, 255), stroke_width=stroke,
            stroke_fill=(0, 0, 0, 230), bounds=img.size, anchor="ma",
        )
        t1 = time.perf_counter()
        t_vdraw.append((t1 - t0) * 1000)

    base_stats1 = L._LEAN_BASE_CACHE.stats()
    base_rebuilds = base_stats1["misses"] - base_stats0["misses"]
    med_bb = statistics.median(bb_areas) if bb_areas else 0
    frac = 100.0 * med_bb / (pad_w * pad_w)

    print(f"\nBREAKDOWN over {FRAMES} frames (production params, real angles):")
    report("full_call", t_full)
    report("text_metrics", t_metrics)
    report("pad_build", t_pad)
    report("rotate", t_rot)
    report("compose", t_comp)
    report("value_draw", t_vdraw)
    print(f"\nBASE CACHE rebuilds during run: {base_rebuilds} "
          f"(hits={base_stats1['hits']}, misses={base_stats1['misses']})")
    print(f"ROTATED BBOX median area {med_bb:.0f} px^2 ({frac:.1f}% of pad); "
          f"union bbox={bb_union}")
    print(f"SUM(pad+rot+comp) median ~= "
          f"{statistics.median(t_pad) + statistics.median(t_rot) + statistics.median(t_comp):.3f} ms")


if __name__ == "__main__":
    main()
