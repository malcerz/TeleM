"""ETAP 5E.4 baseline: local chart raster versus atlas transfer."""

from __future__ import annotations

import json
import statistics
import sys
import time
from bisect import bisect_right
from datetime import timedelta
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.frame_renderer import _direct_region_members
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.compositor import compose_overlay
from src.indicators.profiling import get_overlay_profiler


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def summary(values):
    return {
        "avg_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p95_ms": percentile(values, 0.95),
    }


def main():
    layout, regions, _anchor, *_ = setup()
    histories = WORKER_CACHE["_precomputed_chart_data"]
    telemetry = WORKER_CACHE["_telemetry_cache"]
    profiler = get_overlay_profiler()

    owners = _direct_region_members(layout, regions)
    region_info = []
    for index, region in enumerate(regions):
        dest_x, dest_y, atlas_x, atlas_y, rw, rh = region
        region_info.append({
            "index": index, "rect": list(region),
            "members": sorted(owners[index]) if owners else [],
        })

    # Representative full-canvas composition gives conservative actual widget
    # bboxes.  It is diagnostic only; no renderer semantics are changed.
    bbox_by_frame = {}
    for frame in (0, 1350, 2700, 4050, 5399):
        data = dict(telemetry.lookup(frame))
        target = histories["fit_heart_rate_text"].chart_start_dt + timedelta(
            seconds=frame / FPS
        )
        data["target_dt"] = target
        data["current_position"] = frame / (N - 1)
        extra = dict(data.get("extra_indicators") or {})
        for chart_key in ("fit_cadence_text", "fit_heart_rate_text"):
            history = histories[chart_key]
            visible = bisect_right(history.timestamps, target) - 1
            value = history[visible] if visible >= 0 else None
            if chart_key in extra:
                _old, unit, label = extra[chart_key]
                extra[chart_key] = (value, unit, label)
        data["extra_indicators"] = extra
        bboxes = {}
        compose_overlay(W, H, layout, "", _bboxes=bboxes, reuse_canvas=False, **data)
        bbox_by_frame[str(frame)] = {
            key: list(value) for key, value in bboxes.items()
            if key in {"fit_cadence_text", "fit_heart_rate_text", "fit_enhanced_speed_text"}
        }

    phase_results = {}
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        chart_region = next(
            (item for item in region_info if key in item["members"]), None
        )
        if chart_region is None:
            raise RuntimeError(f"No atlas region owns {key}")
        dest_x, dest_y, atlas_x, atlas_y, rw, rh = regions[chart_region["index"]]
        external = []
        local_external = []
        profiler._frames.clear()
        history = histories[key]
        for repeat in range(1000):
            frame = (repeat * (N - 1)) // 999
            data = dict(telemetry.lookup(frame))
            target = history.chart_start_dt + timedelta(seconds=frame / FPS)
            data["target_dt"] = target
            data["current_position"] = frame / (N - 1)
            extra = dict(data.get("extra_indicators") or {})
            visible = bisect_right(history.timestamps, target) - 1
            visible_value = history[visible] if visible >= 0 else None
            if key in extra:
                _old, unit, label = extra[key]
                extra[key] = (visible_value, unit, label)
            data["extra_indicators"] = extra
            local_bboxes = {}
            local_started = time.perf_counter()
            compose_overlay(
                W, H, layout, "", _bboxes=local_bboxes, reuse_canvas=False,
                render_keys={key}, **data,
            )
            local_external.append((time.perf_counter() - local_started) * 1000.0)
            atlas = Image.new("RGBA", (max(1, atlas_x + rw), max(1, atlas_y + rh)), (0, 0, 0, 0))
            bboxes = {}
            profiler.start_frame(frame, W, H)
            started = time.perf_counter()
            compose_overlay(
                W, H, layout, "", _bboxes=bboxes, reuse_canvas=False,
                target_image=atlas,
                coordinate_origin=(dest_x - atlas_x, dest_y - atlas_y),
                render_keys={key},
                **data,
            )
            external.append((time.perf_counter() - started) * 1000.0)
            profiler.finish_frame()
        metrics = profiler.summary().get("metrics", {})
        prefix = f"indicator.{key}."
        own = {
            name[len(prefix):]: value for name, value in metrics.items()
            if name.startswith(prefix)
        }
        phase_results[key] = {
            "region": chart_region,
            "local_raster_plus_full_canvas_ms": summary(local_external),
            "external_render_plus_atlas_ms": summary(external),
            "profiler_metrics": own,
        }

    output = {
        "frames_profiled": 1000,
        "atlas_size": list(layout["_nvidia_atlas_size"]),
        "regions": region_info,
        "representative_bboxes": bbox_by_frame,
        "chart_results": phase_results,
    }
    destination = ROOT / "scratch" / "etap5e4_local_atlas_baseline.json"
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
