"""ETAP 2C producer state-machine simulation with REAL gauge renders.

Replicates the exporter capture-block AUTO decision logic verbatim (same
helpers, epoch/resync/prev-support rules) over synthetic frame streams and
runs the oracle (consecutive-capture diff ⊆ sent regions) on every frame.
Validated gates (no native pipeline needed):
  M1 multi-size layouts; M2 mid-stream geometry AND style change -> epoch
  reset + full upload + zero missed px; M3 >=3 style variants; M4 steady-
  state region frames + periodic full resyncs.
"""
import sys

import numpy as np

sys.path.insert(0, ".")

from src.indicators.gauge import (
    _render_gauge_indicator,
    get_gauge_dynamic_info,
)
from src.ffmpeg.amd_native_exporter import (
    _support_to_tile_rect,
    _union_tile_rects,
    _merge_tile_rects,
)

FONT = "C:/Windows/Fonts/arial.ttf"
KEY = "fit_enhanced_speed_text"
CANVAS_W, CANVAS_H = 3840, 2160
GX, GY = 1500, 900  # widget origin, fully on-canvas -> no clipping
FULL_REFRESH_N = 10


def render(value, size_px, cfg_over=None):
    cfg = {"x": GX / CANVAS_W, "y": GY / CANVAS_H, "size": size_px / CANVAS_W}
    if cfg_over:
        cfg.update(cfg_over)
    return _render_gauge_indicator(
        CANVAS_W, CANVAS_H, {}, FONT, KEY, value, "km/h", "SPEED",
        cfg, 1080, 2, 42, None, 0.0, 70.0, 5, 8, size_px, 1,
        formatted_val=f"{value:.1f}")


def sweep(n, start=12.0, **fc):
    out = []
    for i in range(n):
        d = dict(fc)
        d["value"] = start + 21.0 * (1.0 + np.sin(i * 0.37)) * 0.5 \
            + 15.0 * (1.0 + np.cos(i * 0.11)) * 0.5
        out.append(d)
    return out


def run_stream(name, frames_cfg):
    state = {"geom": None, "frame_in_geom": 0,
             "auto_prev_needle": None, "auto_prev_text": None}
    prev_arr = None
    stats = {"full": 0, "region": 0, "clear_only": 0, "epochs": 0,
             "missed": 0, "changed": 0}
    for i, fc in enumerate(frames_cfg):
        img, _, _, _ = render(fc["value"], fc["size_px"], fc.get("cfg_over"))
        info = get_gauge_dynamic_info(KEY)
        auto_ok = bool(info and info.get("supported")
                       and int(info.get("rotation", 0)) % 360 == 0)
        gw, gh = img.size
        gx, gy = GX, GY
        do_region = bool(auto_ok)
        if do_region:
            epoch = ((gw, gh, gx, gy, hash(info["sig"])) if auto_ok
                     else (gw, gh, gx, gy, "fallback"))
            if state["geom"] != epoch:
                state["geom"] = epoch
                state["frame_in_geom"] = 0
                state["auto_prev_needle"] = None
                state["auto_prev_text"] = None
                stats["epochs"] += 1
            fig = state["frame_in_geom"]
            do_region = bool(auto_ok and fig > 0
                             and fig % FULL_REFRESH_N != 0)
        prev_n = prev_t = None
        if auto_ok:
            prev_n = state["auto_prev_needle"]
            prev_t = state["auto_prev_text"]
            state["auto_prev_needle"] = _support_to_tile_rect(
                info.get("needle_bbox"), 0, 0, gw, gh)
            state["auto_prev_text"] = _support_to_tile_rect(
                info.get("text_bbox"), 0, 0, gw, gh)
        rects = []
        if do_region:
            cand = []
            u = _union_tile_rects(_support_to_tile_rect(
                info.get("needle_bbox"), 0, 0, gw, gh), prev_n)
            if u is not None:
                cand.append(u)
            u = _union_tile_rects(_support_to_tile_rect(
                info.get("text_bbox"), 0, 0, gw, gh), prev_t)
            if u is not None:
                cand.append(u)
            rects = _merge_tile_rects(cand)
            if not rects:
                stats["clear_only"] += 1
        arr = np.asarray(img)
        if prev_arr is not None and prev_arr.shape == arr.shape:
            mask = np.any(arr != prev_arr, axis=2)
            chg = int(np.count_nonzero(mask))
            stats["changed"] += chg
            if rects:
                cov = np.zeros(mask.shape, dtype=bool)
                for (x0, y0, x1, y1) in rects:
                    cov[y0:y1, x0:x1] = True
                miss = int(np.count_nonzero(mask & ~cov))
                stats["missed"] += miss
                stats["region"] += 1
                assert miss == 0, f"{name} f{i}: MISSED={miss} rects={rects}"
            else:
                stats["full"] += 1
        elif prev_arr is not None:
            stats["full"] += 1  # shape change == epoch switch, full upload
        prev_arr = arr
        state["frame_in_geom"] += 1
    print(f"[SIM] {name}: {stats}")
    return stats


def main():
    total_missed = 0
    for size in (160, 240, 360, 480):  # M1+M4 multi-size sweeps
        st = run_stream(f"size{size}", sweep(80, size_px=size))
        total_missed += st["missed"]
        assert st["region"] > 40 and st["full"] >= 7, st
    frames = sweep(60, size_px=240) + sweep(60, size_px=360)  # M2a geometry
    st = run_stream("geometry_change", frames)
    total_missed += st["missed"]
    assert st["epochs"] >= 2 and st["missed"] == 0, st
    frames = sweep(60, size_px=240, cfg_over={"needle_color": "#FF3B30"}) \
        + sweep(60, size_px=240, cfg_over={"needle_color": "#00E676"})
    st = run_stream("style_change", frames)  # M2b style mid-stream
    total_missed += st["missed"]
    assert st["epochs"] >= 2 and st["missed"] == 0, st
    variants = {  # M3 three style variants
        "arc210": {"start_angle": 210, "sweep_angle": 120},
        "redtext": {"text_color": "#FF2222", "outline": 4},
        "wide": {"thickness": 14, "marker_size": 10},
    }
    for vname, over in variants.items():
        st = run_stream(f"variant_{vname}",
                        sweep(90, size_px=280, cfg_over=dict(over)))
        total_missed += st["missed"]
        assert st["region"] > 40 and st["missed"] == 0, (vname, st)
    assert total_missed == 0
    print("ALL STATE-SIM PROBES PASS (missed=0 everywhere)")


if __name__ == "__main__":
    main()
