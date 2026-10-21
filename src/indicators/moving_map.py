"""Moving-map indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

import os
import math
from datetime import timezone
from src.map_providers import MapProviderRegistry
from src.map_attribution import apply_map_attribution

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

from src.indicators.helpers import (
    _parse_marker_color,
    s,
    apply_map_shape,
    apply_map_opacity,
    apply_map_pitch,
)


def _shared_map_renderers() -> dict:
    """Shared per-(track,zoom,style) MovingMapRenderer cache used by both the
    indicator path and the ETAP 5G GPU upload helper, so exactly one renderer
    (and one cached tile grid) exists per export."""
    if not hasattr(_render_moving_map_indicator, "_map_renderers"):
        _render_moving_map_indicator._map_renderers = {}
    return _render_moving_map_indicator._map_renderers


def clear_moving_map_cache() -> None:
    """Clear cached MovingMapRenderer instances."""
    if hasattr(_render_moving_map_indicator, "_map_renderers"):
        _render_moving_map_indicator._map_renderers.clear()


def map_required_tile_margin(canvas_w: int, map_w: int, track_up: bool = True) -> int:
    """Return the tile margin required by the renderer geometry."""
    from src.moving_map import track_up_working_size, TILE_SIZE
    working_size = track_up_working_size(map_w) if track_up else map_w
    half_tiles = int(math.ceil(working_size / 2 / TILE_SIZE)) + 1
    return max(2, half_tiles)


def ensure_map_tiles_cached(
    canvas_w: int,
    canvas_h: int,
    layout: dict,
    key: str = "track_map",
    gps_track: list | None = None,
    progress_cb: Any = None,
    cancel_event: Any = None,
    start_time_s: float = 0.0,
    duration_s: float | None = None,
    initial_preload_seconds: float = 12.0,
) -> dict[str, Any]:
    """Ensure map tiles are prepared for video export without multi-minute blocking.

    Architecture:
    1. Fast batch check (SQLite chunked IN, ~5ms) of route tiles in the export window.
    2. Synchronously pre-download only the startup fragment (~25-35 tiles, ~3-4s) before frame 0.
    3. Launch RouteTilePrefetcher in the background to stream subsequent tiles in chronological
       route order while rendering.
    4. Controlled priority wait on any uncached tile so grey patches are NEVER rendered.
    """
    if not gps_track or len(gps_track) < 2:
        return {"required": 0, "cached": 0, "downloaded": 0, "missing": 0}

    cfg = layout.get("indicators", {}).get(key, {})
    if not cfg or not cfg.get("enabled", True):
        return {"required": 0, "cached": 0, "downloaded": 0, "missing": 0}

    import time
    from src.moving_map import (
        _download_tile_raw, get_shared_tile_cache, iter_route_tiles_chronological,
        track_up_working_size, RouteTilePrefetcher, set_active_route_prefetcher,
    )
    raw_map_w = s(cfg.get("size", 0.1), canvas_w)
    # AMD's aligned working raster may be a few pixels larger than the normal
    # CPU size.  Prefetch the larger footprint so both consumers share cover.
    aligned_map_w = _quantize_map_val(
        int(raw_map_w), os.environ.get("AMD_MAP_ALIGN", "1"),
    )
    map_w = max(raw_map_w, aligned_map_w)
    render_plan = _map_render_plan(canvas_w, map_w, int(cfg.get("zoom", 14)))
    effective_zoom = render_plan["effective_zoom"]
    map_style = cfg.get("map_style", "light_all")
    is_track_up = str(cfg.get("map_orientation", "north_up")).strip().lower() == "track_up"
    render_size = track_up_working_size(map_w) if is_track_up else map_w
    margin = map_required_tile_margin(canvas_w, map_w, is_track_up)

    dur_total = (gps_track[-1][0].timestamp() - gps_track[0][0].timestamp()) if hasattr(gps_track[0][0], "timestamp") else 0.0
    s_ts = max(0.0, float(start_time_s))
    e_ts = dur_total if duration_s is None or duration_s <= 0 else min(dur_total, s_ts + float(duration_s))

    # 1. Full export window route tiles in chronological order
    route_tiles = iter_route_tiles_chronological(
        gps_track, effective_zoom, render_size, start_ts=s_ts, end_ts=e_ts,
    )
    total_route_tiles = len(route_tiles)

    # 2. Startup fragment (startup window from s_ts)
    startup_e_ts = min(e_ts, s_ts + max(1.0, float(initial_preload_seconds)))
    startup_tiles = iter_route_tiles_chronological(
        gps_track, effective_zoom, render_size, start_ts=s_ts, end_ts=startup_e_ts,
    )

    # 3. Fast batch cache check
    t_chk0 = time.perf_counter()
    cache = get_shared_tile_cache()
    if hasattr(cache, "has_many"):
        cached_set = cache.has_many(route_tiles, map_style)
    else:
        cached_set = {t for t in route_tiles if cache.has(t[0], t[1], t[2], map_style)}
    cache_check_ms = (time.perf_counter() - t_chk0) * 1000.0

    cached_count = len(cached_set)
    missing_route = [t for t in route_tiles if t not in cached_set]
    startup_missing = [t for t in startup_tiles if t not in cached_set]

    from src.map_providers import MapProviderRegistry
    if not MapProviderRegistry.can_prefetch(map_style):
        print(
            f"[MAP POLICY] Route prefetch disabled for '{map_style}' (prefetch prohibited by provider policy). Skipping background prefetch.",
            flush=True,
        )
        set_active_route_prefetcher(None)
        return {
            "required": total_route_tiles,
            "cached": cached_count,
            "downloaded": 0,
            "missing": len(missing_route),
            "cache_check_ms": round(cache_check_ms, 2),
            "initial_preload_ms": 0.0,
            "render_size": render_size,
            "prefetcher": None,
            "prefetch_allowed": False,
        }

    # 4. Synchronously pre-download startup fragment before frame 0
    initial_downloaded = 0
    t_pre0 = time.perf_counter()
    if startup_missing:
        print(
            f"[Map Preload] Pre-caching startup fragment: {len(startup_missing)}/{len(startup_tiles)} tiles "
            f"(export window: {len(missing_route)}/{total_route_tiles} missing, provider={map_style}, zoom={effective_zoom})...",
            flush=True,
        )
        for i, (z, x, y) in enumerate(startup_missing, 1):
            if cancel_event is not None and cancel_event.is_set():
                break
            d = _download_tile_raw(z, x, y, map_style)
            if d:
                cache.put(z, x, y, map_style, d)
                initial_downloaded += 1
                cached_set.add((z, x, y))
            if progress_cb is not None:
                try:
                    progress_cb(i, len(startup_missing), f"Preload mapy: {i}/{len(startup_missing)}")
                except Exception:
                    pass
    initial_preload_ms = (time.perf_counter() - t_pre0) * 1000.0

    # 5. Remaining tiles for background prefetcher
    remaining_missing = [t for t in missing_route if t not in cached_set]
    prefetcher = None
    if remaining_missing:
        print(
            f"[Map Streaming] Spawning RouteTilePrefetcher for {len(remaining_missing)} upcoming tiles...",
            flush=True,
        )
        prefetcher = RouteTilePrefetcher(remaining_missing, map_style, cache=cache, cancel_event=cancel_event)
        set_active_route_prefetcher(prefetcher)
        prefetcher.start()
    else:
        set_active_route_prefetcher(None)

    return {
        "required": total_route_tiles,
        "cached": cached_count,
        "downloaded": initial_downloaded,
        "missing": len(remaining_missing),
        "cache_check_ms": round(cache_check_ms, 2),
        "initial_preload_ms": round(initial_preload_ms, 2),
        "provider": map_style,
        "zoom": effective_zoom,
        "margin": margin,
        "render_size": render_size,
        "prefetcher": prefetcher,
    }


def render_map_working_image(
    canvas_w: int,
    canvas_h: int,
    layout: dict,
    key: str,
    gps_track,
    target_dt=None,
    current_position=None,
    map_heading=None,
    apply_style=True,
    apply_pitch: bool = True,
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
        from src.moving_map import MovingMapRenderer, is_map_network_allowed

        cfg = layout["indicators"].get(key)
        if not cfg or not cfg.get("enabled", True):
            return None, None
        avail = layout.get("_indicator_availability")
        if avail is not None and not avail.get(key, True):
            return None, None
        map_w = s(cfg.get("size", 0.1), canvas_w)
        render_plan = _map_render_plan(canvas_w, map_w, int(cfg.get("zoom", 16)))
        working_size = render_plan["working_size"]
        effective_zoom = render_plan["effective_zoom"]
        map_style = cfg.get("map_style", "light_all")
        marker_style = str(cfg.get("map_marker_style", "dot")).strip().lower()
        if bool(cfg.get("arrow_marker", False)) and marker_style == "dot":
            marker_style = "directional"
        track_color = _parse_marker_color(cfg.get("track_color", "#FF3C1E"))
        if len(track_color) == 3:
            track_color = (*track_color, 220)
        track_width = int(cfg.get("track_width", 3))
        track_aa = max(1, min(8, int(cfg.get("track_antialiasing", 1) or 1)))
        track_outline_w = max(0, int(cfg.get("track_outline_width", 0) or 0))
        track_outline_color = _parse_marker_color(cfg.get("track_outline_color", "#000000"))
        cache_key = (
            id(gps_track), effective_zoom, map_style, marker_style, MapProviderRegistry.cache_generation(map_style),
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
            is_track_up = str(cfg.get("map_orientation", "north_up")).strip().lower() == "track_up"
            margin = map_required_tile_margin(canvas_w, map_w, is_track_up)
            from src.moving_map import get_active_route_prefetcher
            if get_active_route_prefetcher() is None:
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

        dl_missing = is_map_network_allowed()
        draw_track = not bool(cfg.get("hide_track", False))
        draw_marker = not bool(cfg.get("hide_marker", False))
        if str(cfg.get("map_orientation", "north_up")).strip().lower() == "track_up":
            map_img = renderer.render_track_up(
                ts, working_size, heading=map_heading,
                download_missing=dl_missing,
                draw_track=draw_track,
                draw_marker=draw_marker,
            )
        else:
            map_img = renderer.render(
                ts, working_size, working_size,
                download_missing=dl_missing,
                draw_track=draw_track,
                draw_marker=draw_marker,
            )
        renderer._is_first_render = False
        # Pitch first (fills the map box), then the selected shape/border on the final image.
        if apply_pitch:
            map_img = apply_map_pitch(map_img, cfg.get("pitch"))
        if apply_style:
            map_img = apply_map_shape(map_img, cfg.get("map_shape", "square"),
                                      cfg.get("map_corner_radius", 16), cfg.get("map_border_width", 0),
                                      cfg.get("map_border_color", "#FFFFFF"), min(canvas_w, canvas_h) / 1080.)
        if apply_style:
            map_img = apply_map_attribution(map_img, map_style, cfg, shape_scale=min(canvas_w, canvas_h) / 1080.)
        map_img = apply_map_opacity(map_img, cfg.get("opacity"))
        from src.indicators.compositor import _effective_indicator_cfg
        eff_cfg = _effective_indicator_cfg(key, cfg)
        rx = s(eff_cfg["x"], canvas_w)
        ry = s(eff_cfg["y"], canvas_h)
        dst_bbox = (int(round(rx)), int(round(ry)), int(map_w), int(map_w))
        return map_img, dst_bbox
    except Exception:
        return None, None


def build_static_map_marker_tile(
    output_size: int,
    marker_radius: int,
    marker_style: str = "directional",
    marker_color: tuple = (255, 255, 255, 255),
) -> tuple[Any, tuple[int, int, int, int]]:
    """Build the static directional marker tile for GPU Track-Up blending."""
    if marker_style != "directional":
        return None, (0, 0, 0, 0)
    try:
        from PIL import Image, ImageDraw
        size = output_size
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        c = size / 2.0
        r = marker_radius
        tip = (c, c - r * 1.8)
        left = (c - r * 0.65, c + r * 0.75)
        right = (c + r * 0.65, c + r * 0.75)
        d.polygon((tip, left, right), fill=marker_color, outline=(0, 0, 0, 220))
        bbox = img.getbbox()
        if not bbox:
            return None, (0, 0, 0, 0)
        x1, y1, x2, y2 = bbox
        cropped = img.crop((x1, y1, x2, y2))
        return cropped, (x1, y1, x2 - x1, y2 - y1)
    except Exception:
        return None, (0, 0, 0, 0)


def _quantize_map_val(val: int, align_spec: str) -> int:
    spec = str(align_spec).strip().upper()
    if spec in ("1", "0", "EXACT", "NONE", "OFF", ""):
        return val
    if spec.startswith("16_FLOOR"):
        return (val // 16) * 16
    elif spec.startswith("16_CEIL"):
        return ((val + 15) // 16) * 16
    elif spec.startswith("16"):
        return int(round(val / 16.0)) * 16
    elif spec.startswith("8_FLOOR"):
        return (val // 8) * 8
    elif spec.startswith("8_CEIL"):
        return ((val + 7) // 8) * 8
    elif spec.startswith("8"):
        return int(round(val / 8.0)) * 8
    return val


def render_map_unrotated_working_image(
    canvas_w: int,
    canvas_h: int,
    layout: dict,
    key: str,
    gps_track,
    target_dt=None,
    current_position=None,
    map_heading=None,
    apply_pitch: bool = True,
):
    """Render the UNROTATED working map image (e.g. 978x978 for 4K) on CPU for GPU Track-Up.

    Eliminates the expensive per-frame Pillow rotate(BICUBIC) from the CPU thread.
    Returns (unrotated_working_image_RGBA, map_heading, dst_bbox, working_size).
    """
    if not gps_track or len(gps_track) < 2:
        return None, 0.0, None, 0
    try:
        from src.moving_map import (
            MovingMapRenderer, is_map_network_allowed, track_up_working_size,
            track_up_rotation_degrees,
        )

        cfg = layout["indicators"].get(key)
        if not cfg or not cfg.get("enabled", True):
            return None, 0.0, None, 0
        avail = layout.get("_indicator_availability")
        if avail is not None and not avail.get(key, True):
            return None, 0.0, None, 0
        raw_map_w = s(cfg.get("size", 0.1), canvas_w)
        align_spec = os.environ.get("AMD_MAP_ALIGN", "1")
        map_w = _quantize_map_val(int(raw_map_w), align_spec)
        render_plan = _map_render_plan(canvas_w, map_w, int(cfg.get("zoom", 16)))
        effective_zoom = render_plan["effective_zoom"]
        raw_working_size = track_up_working_size(map_w)
        working_size = _quantize_map_val(int(raw_working_size), align_spec)
        map_style = cfg.get("map_style", "light_all")
        marker_style = str(cfg.get("map_marker_style", "dot")).strip().lower()
        if bool(cfg.get("arrow_marker", False)) and marker_style == "dot":
            marker_style = "directional"
        track_color = _parse_marker_color(cfg.get("track_color", "#FF3C1E"))
        if len(track_color) == 3:
            track_color = (*track_color, 220)
        track_width = int(cfg.get("track_width", 3))
        track_aa = max(1, min(8, int(cfg.get("track_antialiasing", 1) or 1)))
        track_outline_w = max(0, int(cfg.get("track_outline_width", 0) or 0))
        track_outline_color = _parse_marker_color(cfg.get("track_outline_color", "#000000"))
        cache_key = (
            id(gps_track), effective_zoom, map_style, marker_style, MapProviderRegistry.cache_generation(map_style),
            track_color, track_width, track_aa, track_outline_w, track_outline_color,
            map_w, working_size,
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
            from src.moving_map import get_active_route_prefetcher
            if get_active_route_prefetcher() is None:
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

        dl_missing = is_map_network_allowed()
        draw_track = not bool(cfg.get("hide_track", False))
        angle = track_up_rotation_degrees(map_heading)
        if angle == 0.0 and apply_pitch:
            render_w = map_w
            draw_marker = not bool(cfg.get("hide_marker", False))
            heading_val = 0.0
            marker_heading = 0.0 if map_heading is not None else None
        else:
            render_w = working_size
            if not apply_pitch and marker_style == "directional":
                draw_marker = not bool(cfg.get("hide_marker", False))
                marker_heading = map_heading if map_heading is not None else 0.0
            else:
                draw_marker = not bool(cfg.get("hide_marker", False)) and marker_style != "directional"
                marker_heading = 0.0 if map_heading is not None else None
            heading_val = float(map_heading) if map_heading is not None else 0.0

        map_img = renderer.render(
            ts, render_w, render_w,
            download_missing=dl_missing,
            draw_track=draw_track,
            draw_marker=draw_marker,
            heading=marker_heading,
        )
        map_img = apply_map_opacity(map_img, cfg.get("opacity"))
        if apply_pitch:
            map_img = apply_map_pitch(map_img, cfg.get("pitch"))
        renderer._is_first_render = False
        crop_key = getattr(renderer, "_last_crop_key", None)
        if map_img is not None and crop_key is not None:
            try:
                setattr(map_img, "_crop_key", crop_key)
            except Exception:
                pass
        from src.indicators.compositor import _effective_indicator_cfg
        eff_cfg = _effective_indicator_cfg(key, cfg)
        rx = s(eff_cfg["x"], canvas_w)
        ry = s(eff_cfg["y"], canvas_h)
        dst_x = _quantize_map_val(int(round(rx)), align_spec)
        dst_y = _quantize_map_val(int(round(ry)), align_spec)
        dst_bbox = (dst_x, dst_y, int(map_w), int(map_w))
        return map_img, heading_val, dst_bbox, working_size
    except Exception:
        return None, 0.0, None, 0


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


def _sync_map_ts(gps_track, target_dt, current_position) -> float:
    """Resolve the renderer timestamp (seconds from track start)."""
    if target_dt is not None:
        gps0 = gps_track[0][0]
        if hasattr(gps0, "timestamp"):
            target_epoch = (target_dt.timestamp()
                            if target_dt.tzinfo is not None
                            else target_dt.replace(tzinfo=timezone.utc).timestamp())
            gps0_ts = (gps0.timestamp()
                       if gps0.tzinfo is not None
                       else gps0.replace(tzinfo=timezone.utc).timestamp())
            return target_epoch - gps0_ts
        return 0.0
    dur = (gps_track[-1][0].timestamp() - gps_track[0][0].timestamp())
    return (current_position if current_position is not None else 0.0) * dur


def _latlon_at_ts(gps_track, ts: float):
    """Interpolate (lat, lon) at *ts* seconds from track start."""
    if not gps_track:
        return None
    n = len(gps_track)
    if n == 1 or ts <= 0.0:
        return gps_track[0][1], gps_track[0][2]
    if ts >= (gps_track[-1][0].timestamp() - gps_track[0][0].timestamp()):
        return gps_track[-1][1], gps_track[-1][2]
    t0 = gps_track[0][0].timestamp()
    target = t0 + ts
    for i in range(1, n):
        if gps_track[i][0].timestamp() >= target:
            a = gps_track[i - 1]
            b = gps_track[i]
            span = b[0].timestamp() - a[0].timestamp()
            frac = (target - a[0].timestamp()) / span if span > 0 else 0.0
            lat = a[1] + (b[1] - a[1]) * frac
            lon = a[2] + (b[2] - a[2]) * frac
            return lat, lon
    return gps_track[-1][1], gps_track[-1][2]


def _render_moving_map_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    gps_track=None, target_dt=None, current_position=None,
    map_heading=None, async_map=False,
):
    """Render a moving-map indicator.

    ``async_map=True`` always draws the viewport, route and marker from cache;
    missing tiles load through one deduplicated background worker.
    ``async_map=False`` (final render / AMD helpers) keeps the original
    synchronous behaviour unchanged.
    """
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
        marker_style = str(cfg.get("map_marker_style", "dot")).strip().lower()
        if bool(cfg.get("arrow_marker", False)) and marker_style == "dot":
            marker_style = "directional"
        cache_key = (track_id, effective_zoom, map_style, marker_style, MapProviderRegistry.cache_generation(map_style))
        if not hasattr(_render_moving_map_indicator, "_map_renderers"):
            _render_moving_map_indicator._map_renderers = {}
        _cache = _render_moving_map_indicator._map_renderers

        track_color_cfg = cfg.get("track_color", "#FF3C1E")
        track_color = _parse_marker_color(track_color_cfg)
        if len(track_color) == 3:
            track_color = (*track_color, 220)
        track_width = int(cfg.get("track_width", 3))
        # ETAP 10T: track antialiasing + outline (defaults preserve legacy look).
        track_aa = max(1, min(8, int(cfg.get("track_antialiasing", 1) or 1)))
        track_outline_w = max(0, int(cfg.get("track_outline_width", 0) or 0))
        track_outline_color = _parse_marker_color(cfg.get("track_outline_color", "#000000"))

        # ETAP 3A Diagnostic: Frozen Map
        if os.environ.get("TELEM_MAP_FROZEN") == "1":
            if not hasattr(_render_moving_map_indicator, "_frozen_map_cache"):
                _render_moving_map_indicator._frozen_map_cache = {}
            if cache_key in _render_moving_map_indicator._frozen_map_cache:
                c_img, cx, cy, cextra = _render_moving_map_indicator._frozen_map_cache[cache_key]
                return c_img, cx, cy, cextra

        # ETAP 3B GPU Map Prototype Bypass: CPU leaves map area transparent
        if not async_map and os.environ.get("TELEM_INTEL_GPU_MAP") == "1":
            pos_x = s(cfg["x"], canvas_w)
            pos_y = s(cfg["y"], canvas_h)
            blank_map = Image.new("RGBA", (map_w, map_h), (0, 0, 0, 0))
            return blank_map, pos_x, pos_y, None

        if os.environ.get("TELEM_MAP_FROZEN_ROTATION") == "1":
            map_heading = 0.0

        if async_map:
            # ── Async path (GUI preview) — never blocks ───────────────────
            ts = _sync_map_ts(gps_track, target_dt, current_position)
            _pos_xy = s(cfg["x"], canvas_w), s(cfg["y"], canvas_h)

            # Local Cache First: build/get renderer and check if local cache already has tiles
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
                    marker_style=marker_style,
                    track_antialiasing=track_aa,
                    track_outline_width=track_outline_w,
                    track_outline_color=track_outline_color,
                )
                _cache[cache_key] = renderer
                renderer._is_first_render = False
            else:
                renderer = _cache[cache_key]
                renderer._trk_color = track_color
                renderer._trk_width = max(1, int(round(
                    track_width * (2.0 ** render_plan["zoom_offset"])
                )))
                renderer._mkr_color = _parse_marker_color(cfg.get("marker_color", "#FFFFFF"))
                renderer._mkr_radius = max(1, int(round(
                    float(cfg.get("marker_size", 7)) * (2.0 ** render_plan["zoom_offset"])
                )))
                renderer._mkr_style = marker_style
                renderer._track_aa = track_aa
                renderer._track_outline_w = track_outline_w
                renderer._track_outline_color = track_outline_color

            from src.moving_map import track_up_working_size, TileCache
            prefetch_size = (
                track_up_working_size(working_size)
                if str(cfg.get("map_orientation", "north_up")).strip().lower() == "track_up"
                else working_size
            )
            coverage = renderer.viewport_tile_coverage(ts, prefetch_size, prefetch_size)
            draw_track = not bool(cfg.get("hide_track", False))
            draw_marker = not bool(cfg.get("hide_marker", False))

            # Non-blocking background precache for missing tiles
            from src.gui.map_viewport_prefetch import preview_viewport_prefetch
            if coverage < 1.0:
                def _detail_fill():
                    try:
                        renderer.viewport_precache(ts, prefetch_size, prefetch_size, max_tiles=25)
                    except Exception:
                        pass
                viewport_key = (cache_key, renderer._viewport_range(ts, prefetch_size, prefetch_size))
                preview_viewport_prefetch.schedule(viewport_key, _detail_fill)

            # A completed tile job invalidates the assembled preview grid, so
            # newly downloaded tiles appear even while paused at the same point.
            revision = (preview_viewport_prefetch.revision, TileCache.content_revision())
            if getattr(renderer, "_preview_tiles_revision", None) != revision:
                renderer._grid_cache_key = None
                renderer._preview_tiles_revision = revision

            # Always render the moving map (parity with final render: cached tiles
            # appear immediately, uncached areas stay neutral grey, route and position
            # marker are always drawn, GUI never blocks).
            if str(cfg.get("map_orientation", "north_up")).strip().lower() == "track_up":
                map_img = renderer.render_track_up(
                    ts, working_size, heading=map_heading,
                    download_missing=False,
                    draw_track=draw_track, draw_marker=draw_marker,
                )
            else:
                map_img = renderer.render(
                    ts, working_size, working_size,
                    download_missing=False,
                    draw_track=draw_track, draw_marker=draw_marker,
                    heading=map_heading,
                )
            if map_img.size != (map_w, map_h):
                map_img = map_img.resize((map_w, map_h), Image.Resampling.LANCZOS)
            map_img = apply_map_pitch(map_img, cfg.get("pitch"))
            map_img = apply_map_shape(map_img, cfg.get("map_shape", "square"),
                                  cfg.get("map_corner_radius", 16), cfg.get("map_border_width", 0),
                                  cfg.get("map_border_color", "#FFFFFF"), min(canvas_w, canvas_h) / 1080.)
            map_img = apply_map_attribution(map_img, map_style, cfg, shape_scale=min(canvas_w, canvas_h) / 1080.)
            map_img = apply_map_opacity(map_img, cfg.get("opacity"))
            return map_img, _pos_xy[0], _pos_xy[1], None

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
                marker_style=marker_style,
                track_antialiasing=track_aa,
                track_outline_width=track_outline_w,
                track_outline_color=track_outline_color,
            )
            _cache[cache_key] = renderer
            renderer._is_first_render = True


            # Precache common zoom levels only in interactive preview (async_map=True).
            # In synchronous worker export (async_map=False), do NOT launch multi-zoom
            # background precache across the entire track (avoids multi-GiB memory surge).
            if async_map:
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
            renderer._mkr_style = marker_style
            renderer._track_aa = track_aa
            renderer._track_outline_w = track_outline_w
            renderer._track_outline_color = track_outline_color
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
        
        draw_track = not hide_track
        draw_marker = not hide_marker
        if str(cfg.get("map_orientation", "north_up")).strip().lower() == "track_up":
            map_img = renderer.render_track_up(
                ts, working_size, heading=map_heading,
                download_missing=dl_missing,
                draw_track=draw_track,
                draw_marker=draw_marker,
            )
        else:
            map_img = renderer.render(
                ts, working_size, working_size,
                download_missing=dl_missing,
                draw_track=draw_track,
                draw_marker=draw_marker,
                heading=map_heading,
            )
        renderer._is_first_render = False
        if map_img.size != (map_w, map_h):
            map_img = map_img.resize((map_w, map_h), Image.Resampling.LANCZOS)
        # Kształt mapy: kwadrat (domyślnie) lub okrąg — z zakładki Shape
        map_img = apply_map_pitch(map_img, cfg.get("pitch"))
        map_img = apply_map_shape(map_img, cfg.get("map_shape", "square"),
                                  cfg.get("map_corner_radius", 16), cfg.get("map_border_width", 0),
                                  cfg.get("map_border_color", "#FFFFFF"), min(canvas_w, canvas_h) / 1080.)
        map_img = apply_map_attribution(map_img, map_style, cfg, shape_scale=min(canvas_w, canvas_h) / 1080.)
        map_img = apply_map_opacity(map_img, cfg.get("opacity"))
        map_tuple = (map_img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None)
        if os.environ.get("TELEM_MAP_FROZEN") == "1":
            if not hasattr(_render_moving_map_indicator, "_frozen_map_cache"):
                _render_moving_map_indicator._frozen_map_cache = {}
            _render_moving_map_indicator._frozen_map_cache[cache_key] = map_tuple
        return map_tuple
    except Exception:
        return None, 0, 0, None
