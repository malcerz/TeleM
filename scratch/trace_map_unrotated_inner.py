import json
import sys
from datetime import timedelta, timezone
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.moving_map import _map_render_plan, _shared_map_renderers, map_required_tile_margin, track_up_rotation_degrees, apply_map_shape
from src.indicators.helpers import s, _parse_marker_color
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = repo_root / "def_layout.json"

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed is not None:
    apply_processed_cache(tm, processed)
else:
    tm.load_gpmf_from_exiftool(VIDEO)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

layout = json.load(open(LAYOUT_PATH, encoding="utf-8"))
fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())

fps = 30000.0 / 1001.0
frame_idx = 150
target_dt = tm.start_dt_utc + timedelta(seconds=frame_idx / fps) if tm.start_dt_utc else None
gps_track = tm.get_gps_track_for_source(layout.get("indicators", {}).get("track_map", {}).get("source", "fit"))

frame_kwargs = prepare_overlay_frame_data(
    layout=layout,
    target_dt=target_dt,
    tz_offset_hours=2,
    start_dt_utc=tm.start_dt_utc,
    speed_samples=tm.speed_samples,
    track_samples=tm.track_samples,
    alt_samples=tm.alt_samples,
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=gps_track,
    fit_field_plan=fit_field_plan,
)

canvas_w, canvas_h = 3840, 2160
key = "track_map"
map_heading = frame_kwargs.get("map_heading")
current_position = frame_kwargs.get("current_position")

from src.moving_map import MovingMapRenderer, is_map_network_allowed, track_up_working_size

cfg = layout["indicators"].get(key)
map_w = s(cfg.get("size", 0.1), canvas_w)
render_plan = _map_render_plan(canvas_w, map_w, int(cfg.get("zoom", 16)))
effective_zoom = render_plan["effective_zoom"]
working_size = track_up_working_size(map_w)
map_style = cfg.get("map_style", "light_all")
marker_style = str(cfg.get("map_marker_style", "dot")).strip().lower()
track_color = _parse_marker_color(cfg.get("track_color", "#FF3C1E"))
if len(track_color) == 3:
    track_color = (*track_color, 220)
track_width = int(cfg.get("track_width", 3))
track_aa = max(1, min(8, int(cfg.get("track_antialiasing", 1) or 1)))
track_outline_w = max(0, int(cfg.get("track_outline_width", 0) or 0))
track_outline_color = _parse_marker_color(cfg.get("track_outline_color", "#000000"))
cache_key = (
    id(gps_track), effective_zoom, map_style, marker_style,
    track_color, track_width, track_aa, track_outline_w, track_outline_color,
)
renderers = _shared_map_renderers()
renderer = renderers.get(cache_key)
if renderer is None:
    renderer = MovingMapRenderer(
        gps_track, zoom=effective_zoom, style=map_style,
        marker_color=_parse_marker_color(cfg.get("marker_color", "#FFFFFF")),
        marker_radius=max(1, int(round(
            float(cfg.get("marker_size", 7)) * (2.0 ** render_plan["zoom_offset"])
        ))),
        track_color=track_color,
        track_width=max(1, int(round(
            track_width * (2.0 ** render_plan["zoom_offset"])
        ))),
        marker_style=marker_style,
        track_antialiasing=track_aa,
        track_outline_width=track_outline_w,
        track_outline_color=track_outline_color,
    )
    renderers[cache_key] = renderer
    renderer._is_first_render = True
    margin = map_required_tile_margin(canvas_w, map_w, True)
    renderer.background_precache(margin=margin, zooms=[effective_zoom])

if target_dt is not None:
    gps0 = gps_track[0][0]
    if hasattr(gps0, "timestamp"):
        target_epoch = (target_dt.timestamp()
                        if target_dt.tzinfo is not None
                        else target_dt.replace(tzinfo=timezone.utc).timestamp())
        gps0_ts = (gps0.timestamp()
                   if gps0.tzinfo is not None
                   else gps0.replace(tzinfo=timezone.utc).timestamp())
        ts = target_epoch - gps0_ts
    else:
        ts = 0.0
else:
    dur = (gps_track[-1][0].timestamp() - gps_track[0][0].timestamp())
    ts = (current_position if current_position is not None else 0.0) * dur

dl_missing = getattr(renderer, '_is_first_render', False) and is_map_network_allowed()
draw_track = not bool(cfg.get("hide_track", False))
angle = track_up_rotation_degrees(map_heading)
if angle == 0.0:
    working_size = map_w
    draw_marker = not bool(cfg.get("hide_marker", False))
    heading_val = 0.0
else:
    working_size = track_up_working_size(map_w)
    draw_marker = not bool(cfg.get("hide_marker", False)) and marker_style != "directional"
    heading_val = float(map_heading)

print("Calling renderer.render...")
map_img = renderer.render(
    ts, working_size, working_size,
    download_missing=dl_missing,
    draw_track=draw_track,
    draw_marker=draw_marker,
    heading=(0.0 if map_heading is not None else None),
)
print(f"map_img result: {map_img.size if map_img else None}")
