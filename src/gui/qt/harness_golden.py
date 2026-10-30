"""Harness-only: capture the editor HUD for a frame so it can be compared with
the export HUD (CPU P0.4 Golden HUD).  Never imported by normal application
start-up; ``application.py`` calls it only for ``--golden-dir``.

Writes into ``out_dir``:
  editor_hud_f<N>.png   what the editor draws (render_preview: fast_preview=True,
                        async_map=True) on a transparent canvas of the video size
  exportalgo_hud_f<N>.png  compose_overlay with the export settings
                        (fast_preview=False, async_map=False), upright
  telemetry_f<N>.json   the prepared telemetry record both paths consume
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value[:200]]
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return repr(value)


def capture_editor_hud(controller: Any, abs_frame: int, out_dir: str, width: int, height: int) -> dict:
    from src.indicators.compositor import compose_overlay, render_preview

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    provider = controller._prepared_hud_provider
    data = provider.frame(abs_frame)
    layout = controller.layout
    font_path = controller.font_path
    try:
        from src.indicators.map_prepare import set_current_map_context
        set_current_map_context(getattr(controller, "map_context", None))
    except Exception:
        pass

    def args(d):
        return (
            d["date_text"], d["time_text"], d["speed_value"], d["distance_m"], d["max_distance_m"],
            d["alt_value"], d["min_alt"], d["max_alt"], d["iso_value"], d["exposure_value"], d["temp_value"],
        )

    def kw(d):
        return dict(
            indicator_values=d["indicator_values"], max_speed_kmh=d["max_speed_kmh"],
            power_value=d["power_value"], atemp_value=d["atemp_value"], hr_value=d["hr_value"],
            cad_value=d["cad_value"], battery_value=d["battery_value"], chart_data=d["chart_data"],
            extra_indicators=d["extra_indicators"], gps_track=d["gps_track"],
            map_heading=d.get("map_heading"), target_dt=d["target_dt"], start_dt_utc=d["start_dt_utc"],
            elapsed_seconds=d["elapsed_seconds"], avg_speed_kmh=d["avg_speed_kmh"],
            auto_ranges=d.get("auto_ranges"), indicator_availability=d.get("indicator_availability"),
        )

    # Editor path (as _render_preview_sync): the HUD position in charts is
    # global_time / video_duration, not the prepared record's value.
    duration = max(1.0, float(getattr(controller, "video_duration_s", 0) or 1.0))
    global_time = abs_frame / float(provider.fps)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    editor = render_preview(
        canvas, layout, font_path, *args(data), **kw(data),
        _bboxes={}, current_position=global_time / duration, inplace=False, async_map=True,
    )
    editor.save(out / f"editor_hud_f{abs_frame}.png")

    export_algo = compose_overlay(
        width, height, layout, font_path, *args(data), **kw(data),
        current_position=data["current_position"], fast_preview=False, async_map=False, rot180=False,
        _bboxes={},
    )
    export_algo.save(out / f"exportalgo_hud_f{abs_frame}.png")
    (out / f"telemetry_f{abs_frame}.json").write_text(
        json.dumps(_jsonable(data), indent=1, ensure_ascii=False), encoding="utf-8")
    return {"frame": abs_frame, "global_time": global_time, "editor_current_position": global_time / duration,
            "record_current_position": data["current_position"]}
