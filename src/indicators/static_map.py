"""Static-map indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

import threading
from datetime import timezone

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

from src.indicators.helpers import _parse_marker_color, s, apply_map_shape


def _render_static_map_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    gps_track=None, target_dt=None, current_position=None,
):
    """Render a static-map indicator."""
    if not gps_track or len(gps_track) < 2:
        return None, 0, 0, None
    try:
        from src.map_renderer import render_map_overlay, precache_map_tiles

        map_w = size_px
        map_h = map_w  # kwadrat / średnica okręgu (kształt z zakładki Shape)
        zoom = int(cfg.get("zoom", 16))
        map_style = cfg.get("map_style", "light_all")

        _pc_key = ("static_precache", id(gps_track), zoom, map_style)
        if not hasattr(_render_static_map_indicator, "_precached"):
            _render_static_map_indicator._precached = set()
        if _pc_key not in _render_static_map_indicator._precached:
            _render_static_map_indicator._precached.add(_pc_key)
            zooms_to_cache = list(range(13, 19))
            if zoom not in zooms_to_cache:
                zooms_to_cache.append(zoom)
            zooms_to_cache.sort(key=lambda z: abs(z - zoom))
            
            threading.Thread(target=precache_map_tiles, args=(gps_track, zoom, map_style, 2, zooms_to_cache), daemon=True).start()
            _is_first = True
        else:
            _is_first = False

        if target_dt is not None:
            import bisect
            # Normalise to consistent UTC epoch (naive → treated as UTC)
            target_ts = (target_dt.timestamp()
                         if target_dt.tzinfo is not None
                         else target_dt.replace(tzinfo=timezone.utc).timestamp())
            cache_key = id(gps_track)
            if (not hasattr(_render_static_map_indicator, "_gps_times")
                    or _render_static_map_indicator._gps_times_id != cache_key):
                _render_static_map_indicator._gps_times = [
                    (dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp())
                    for dt, _, _ in gps_track
                ]
                _render_static_map_indicator._gps_times_id = cache_key
            times = _render_static_map_indicator._gps_times
            ci = bisect.bisect_left(times, target_ts)
            if ci > 0 and ci < len(times) and abs(times[ci] - target_ts) > abs(times[ci - 1] - target_ts):
                ci = ci - 1
            ci = max(0, min(len(gps_track) - 1, ci))
        else:
            ci = int(round((current_position if current_position is not None else 0.0) * (len(gps_track) - 1)))
            ci = max(0, min(len(gps_track) - 1, ci))

        track_color_cfg = cfg.get("track_color", "#FF3C1E")
        track_color = _parse_marker_color(track_color_cfg)
        if len(track_color) == 3:
            track_color = (*track_color, 220)
            
        track_width = int(cfg.get("track_width", 3))
        hide_marker = bool(cfg.get("hide_marker", False))
        hide_track = bool(cfg.get("hide_track", False))

        map_img = render_map_overlay(
            gps_track, ci, map_w, map_h,
            zoom=zoom, map_style=map_style,
            marker_radius=int(cfg.get("marker_size", 7)),
            marker_color=_parse_marker_color(cfg.get("marker_color", "#FFFFFF")),
            track_color=track_color,
            track_width=track_width,
            hide_marker=hide_marker,
            hide_track=hide_track,
            download_missing=False,
            track_antialiasing=max(1, min(8, int(cfg.get("track_antialiasing", 1) or 1))),
            track_outline_width=max(0, int(cfg.get("track_outline_width", 0) or 0)),
            track_outline_color=_parse_marker_color(cfg.get("track_outline_color", "#000000")),
        )
        # Kształt mapy: kwadrat (domyślnie) lub okrąg — z zakładki Shape
        map_img = apply_map_shape(map_img, cfg.get("map_shape", "square"))
        return map_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
    except Exception:
        return None, 0, 0, None
