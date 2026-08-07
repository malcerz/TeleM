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

        track_color_cfg = cfg.get("track_color", "#FF3C1E")
        track_color = _parse_marker_color(track_color_cfg)
        if len(track_color) == 3:
            track_color = (*track_color, 220)
        track_width = int(cfg.get("track_width", 3))

        if cache_key not in _cache:
            renderer = MovingMapRenderer(
                gps_track, zoom=zoom, style=map_style,
                marker_color=_parse_marker_color(cfg.get("marker_color", "#FFFFFF")),
                marker_radius=int(cfg.get("marker_size", 7)),
                track_color=track_color,
                track_width=track_width,
            )
            _cache[cache_key] = renderer
            renderer._is_first_render = True
            
            # Precache common zoom levels to make slider smoother
            zooms_to_cache = list(range(13, 19))
            if zoom not in zooms_to_cache:
                zooms_to_cache.append(zoom)
            zooms_to_cache.sort(key=lambda z: abs(z - zoom))
            
            renderer.background_precache(margin=2, zooms=zooms_to_cache)
        else:
            renderer = _cache[cache_key]
            # Update renderer properties that can change dynamically
            renderer._trk_color = track_color
            renderer._trk_width = track_width
            renderer._mkr_color = _parse_marker_color(cfg.get("marker_color", "#FFFFFF"))
            renderer._mkr_radius = int(cfg.get("marker_size", 7))

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
        hide_marker = bool(cfg.get("hide_marker", False))
        hide_track = bool(cfg.get("hide_track", False))
        
        map_img = renderer.render(
            ts, map_w, map_h, 
            download_missing=False,
            draw_track=not hide_track,
            draw_marker=not hide_marker
        )
        renderer._is_first_render = False
        return map_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
    except Exception:
        return None, 0, 0, None
