"""Moving-map indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

import math
from datetime import timezone

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

from src.indicators.helpers import _parse_marker_color, s, apply_map_shape


def _shared_map_renderers() -> dict:
    """Shared per-(track,zoom,style) MovingMapRenderer cache used by both the
    indicator path and the ETAP 5G GPU upload helper, so exactly one renderer
    (and one cached tile grid) exists per export."""
    if not hasattr(_render_moving_map_indicator, "_map_renderers"):
        _render_moving_map_indicator._map_renderers = {}
    return _render_moving_map_indicator._map_renderers


def render_map_working_image(
    canvas_w: int,
    canvas_h: int,
    layout: dict,
    key: str,
    gps_track,
    target_dt=None,
    current_position=None,
):
    """Render the map working image (692x692 for 4K) WITHOUT the final Pillow
    LANCZOS resize, using the same render plan/renderer semantics as the
    indicator path.  ``MovingMapRenderer`` and all CPU map rendering are
    unchanged.

    Returns ``(working_image_RGBA, dst_bbox)`` where ``dst_bbox =
    (x, y, w, h)`` is the top-left destination in canvas coordinates (w/h =
    final widget size, e.g. 691).  Returns ``(None, None)`` on error.
    """
    if not gps_track or len(gps_track) < 2:
        return None, None
    try:
        from src.moving_map import MovingMapRenderer

        cfg = layout["indicators"].get(key)
        if not cfg or not cfg.get("enabled", True):
            return None, None
        map_w = s(cfg.get("size", 0.1), canvas_w)
        render_plan = _map_render_plan(canvas_w, map_w, int(cfg.get("zoom", 16)))
        working_size = render_plan["working_size"]
        effective_zoom = render_plan["effective_zoom"]
        map_style = cfg.get("map_style", "light_all")
        cache_key = (id(gps_track), effective_zoom, map_style)
        renderers = _shared_map_renderers()
        renderer = renderers.get(cache_key)
        if renderer is None:
            track_color = _parse_marker_color(cfg.get("track_color", "#FF3C1E"))
            if len(track_color) == 3:
                track_color = (*track_color, 220)
            track_width = int(cfg.get("track_width", 3))
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
            )
            renderers[cache_key] = renderer
            renderer._is_first_render = True
            renderer.background_precache(margin=2, zooms=[effective_zoom])

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

        dl_missing = getattr(renderer, '_is_first_render', False)
        map_img = renderer.render(
            ts, working_size, working_size,
            download_missing=dl_missing,
            draw_track=not bool(cfg.get("hide_track", False)),
            draw_marker=not bool(cfg.get("hide_marker", False)),
        )
        renderer._is_first_render = False
        map_img = apply_map_shape(map_img, cfg.get("map_shape", "square"))
        rx = s(cfg["x"], canvas_w)
        ry = s(cfg["y"], canvas_h)
        dst_bbox = (int(rx - map_w // 2), int(ry - map_w // 2), int(map_w), int(map_w))
        return map_img, dst_bbox
    except Exception:
        return None, None


# The GUI renders its interactive preview at this logical width.  A map zoom
# selected there describes a geographic viewport in logical preview pixels,
# not in final-export device pixels.  Higher-resolution exports therefore use
# higher-resolution map tiles while preserving the same geographic bounds.
MAP_ZOOM_REFERENCE_CANVAS_WIDTH = 960


def _map_render_plan(canvas_w: int, output_size: int, configured_zoom: int) -> dict:
    """Return a resolution-independent tile/crop plan for ``track_map``.

    Web-map zoom levels double their world-pixel density.  Merely enlarging
    ``output_size`` while keeping ``configured_zoom`` fixed enlarges the
    geographic viewport (the Preview/Export mismatch fixed by ETAP 5C
    precheck).  The integer zoom offset supplies native tile detail; a small
    residual resize handles non-power-of-two canvas scales.
    """
    canvas_scale = max(1.0 / MAP_ZOOM_REFERENCE_CANVAS_WIDTH,
                       float(canvas_w) / MAP_ZOOM_REFERENCE_CANVAS_WIDTH)
    zoom_offset = math.floor(math.log2(canvas_scale))
    effective_zoom = max(0, min(22, int(configured_zoom) + zoom_offset))
    applied_zoom_offset = effective_zoom - int(configured_zoom)
    tile_density_scale = 2.0 ** applied_zoom_offset
    # ETAP 8U-C: Universal Exact-Size Map rendering.
    # For ANY resolution (4K, 1080p, 720p, 480p, etc.) and ANY configured user size (0.08 .. 0.35+),
    # the CPU raster is rendered directly at output_size (desired_px), so working_size == output_size
    # and output_resize_scale == 1.0. This achieves 100% Direct 1:1 GPU Blend coverage.
    working_size = max(1, int(round(output_size)))
    logical_size = max(1, int(round(float(working_size) / canvas_scale)))
    return {
        "canvas_scale": canvas_scale,
        "configured_zoom": int(configured_zoom),
        "effective_zoom": effective_zoom,
        "zoom_offset": applied_zoom_offset,
        "logical_size": logical_size,
        "working_size": working_size,
        "output_size": int(output_size),
        "output_resize_scale": 1.0,
    }


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
        map_w = size_px
        map_h = map_w  # kwadrat / średnica okręgu (kształt z zakładki Shape)
        render_plan = _map_render_plan(canvas_w, map_w, zoom)
        effective_zoom = render_plan["effective_zoom"]
        working_size = render_plan["working_size"]
        map_style = cfg.get("map_style", "light_all")
        cache_key = (track_id, effective_zoom, map_style)
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
                gps_track, zoom=effective_zoom, style=map_style,
                marker_color=_parse_marker_color(cfg.get("marker_color", "#FFFFFF")),
                marker_radius=max(1, int(round(
                    float(cfg.get("marker_size", 7)) * (2.0 ** render_plan["zoom_offset"])
                ))),
                track_color=track_color,
                track_width=max(1, int(round(
                    track_width * (2.0 ** render_plan["zoom_offset"])
                ))),
            )
            _cache[cache_key] = renderer
            renderer._is_first_render = True
            
            # Precache common zoom levels to make slider smoother
            zooms_to_cache = list(range(13, 19))
            if effective_zoom not in zooms_to_cache:
                zooms_to_cache.append(effective_zoom)
            zooms_to_cache.sort(key=lambda z: abs(z - effective_zoom))
            
            renderer.background_precache(margin=2, zooms=zooms_to_cache)
        else:
            renderer = _cache[cache_key]
            # Update renderer properties that can change dynamically
            renderer._trk_color = track_color
            renderer._trk_width = max(1, int(round(
                track_width * (2.0 ** render_plan["zoom_offset"])
            )))
            renderer._mkr_color = _parse_marker_color(cfg.get("marker_color", "#FFFFFF"))
            renderer._mkr_radius = max(1, int(round(
                float(cfg.get("marker_size", 7)) * (2.0 ** render_plan["zoom_offset"])
            )))
        if target_dt is not None:
            gps0 = gps_track[0][0]
            if hasattr(gps0, 'timestamp'):
                # Normalise BOTH timestamps to consistent UTC epochs, otherwise
                # a naive target_dt would be interpreted as local time while the
                # track start is read as UTC — shifting the marker by the local
                # UTC offset (e.g. 2 h) and pinning it to the start of the route.
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
        
        dl_missing = getattr(renderer, '_is_first_render', False)
        hide_marker = bool(cfg.get("hide_marker", False))
        hide_track = bool(cfg.get("hide_track", False))
        
        map_img = renderer.render(
            ts, working_size, working_size,
            download_missing=False,
            draw_track=not hide_track,
            draw_marker=not hide_marker
        )
        renderer._is_first_render = False
        if map_img.size != (map_w, map_h):
            map_img = map_img.resize((map_w, map_h), Image.Resampling.LANCZOS)
        # Kształt mapy: kwadrat (domyślnie) lub okrąg — z zakładki Shape
        map_img = apply_map_shape(map_img, cfg.get("map_shape", "square"))
        return map_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
    except Exception:
        return None, 0, 0, None
