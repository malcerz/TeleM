"""Moving-map indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

from datetime import timezone

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

from src.indicators.helpers import _parse_marker_color, s


def _render_moving_map_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    gps_track=None, target_dt=None, current_position=None,
):
    """Render a moving-map indicator."""
    if not gps_track or len(gps_track) < 2:
        return None, 0, 0, None
    try:
        from src.moving_map import MovingMapRenderer

        track_id = id(gps_track)
        zoom = int(cfg.get("zoom", 16))
        map_style = cfg.get("map_style", "light_all")
        cache_key = (track_id, zoom, map_style)
        if not hasattr(_render_moving_map_indicator, "_map_renderers"):
            _render_moving_map_indicator._map_renderers = {}
        _cache = _render_moving_map_indicator._map_renderers

        if cache_key not in _cache:
            renderer = MovingMapRenderer(
                gps_track, zoom=zoom, style=map_style,
                marker_color=_parse_marker_color(cfg.get("marker_color", "#FFFFFF")),
                marker_radius=int(cfg.get("marker_size", 7)),
            )
            _cache[cache_key] = renderer
            renderer._is_first_render = True
            renderer.background_precache(margin=2)
        else:
            renderer = _cache[cache_key]

        map_w = size_px
        map_h = max(40, int(map_w * 0.65))
        if target_dt is not None:
            gps0 = gps_track[0][0]
            if hasattr(gps0, 'timestamp'):
                gps0_ts = (gps0.replace(tzinfo=timezone.utc).timestamp()
                           if gps0.tzinfo is None else gps0.timestamp())
                ts = target_dt.timestamp() - gps0_ts
            else:
                ts = 0.0
        else:
            dur = (gps_track[-1][0].timestamp() - gps_track[0][0].timestamp())
            ts = (current_position if current_position is not None else 0.0) * dur
        
        dl_missing = getattr(renderer, '_is_first_render', False)
        map_img = renderer.render(ts, map_w, map_h, download_missing=dl_missing)
        renderer._is_first_render = False
        return map_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
    except Exception:
        return None, 0, 0, None
