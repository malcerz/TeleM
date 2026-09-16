"""Indicator auto-placement helper module for TeleM.

Provides collision-free placement for newly created indicators without
modifying existing layout positions or shifting existing active widgets.
"""

from __future__ import annotations

import math
import time
from typing import Any, Optional

from src.indicators.dispatcher import render_value_indicator
from src.indicators.helpers import indicator_font_path, s
from src.indicators.time_display import render_time_display


def get_active_indicator_bboxes(
    layout: dict[str, Any],
    canvas_w: int = 3840,
    canvas_h: int = 2160,
    default_font_path: str = "C:/Windows/Fonts/arial.ttf",
) -> dict[str, tuple[int, int, int, int]]:
    """Compute axis-aligned bounding boxes (x0, y0, w, h) for all active indicators.

    Only indicators with ``enabled == True`` are included. Inactive indicators
    (``enabled == False``) do not occupy space and are excluded.
    """
    indicators = layout.get("indicators", {})
    if not isinstance(indicators, dict):
        return {}

    bboxes: dict[str, tuple[int, int, int, int]] = {}

    for key, cfg in indicators.items():
        if not isinstance(cfg, dict) or not cfg.get("enabled", True):
            continue

        bbox = compute_single_indicator_bbox(
            key, cfg, layout, canvas_w=canvas_w, canvas_h=canvas_h,
            default_font_path=default_font_path,
        )
        if bbox is not None:
            bboxes[key] = bbox

    return bboxes


def measure_indicator_dimensions(
    key: str,
    cfg: dict[str, Any],
    layout: dict[str, Any],
    canvas_w: int = 3840,
    canvas_h: int = 2160,
    default_font_path: str = "C:/Windows/Fonts/arial.ttf",
) -> tuple[int, int, str]:
    """Measure the AABB width, height and anchor type for an indicator config.

    Returns:
        (aabb_w, aabb_h, anchor) where anchor is 'top_left' or 'center'.
    """
    font_path = indicator_font_path(layout, key, default_font_path)
    form = cfg.get("form", "text")
    rot = int(cfg.get("rotation", 0)) % 360

    if key == "time_display" or form == "time_display":
        res, _, _ = render_time_display(
            canvas_w, canvas_h, layout, font_path,
            "2026-09-15", "12:00:00", 3600.0, 25.0,
        )
        if res is not None:
            w_rot, h_rot = _rotate_dimensions(res.width, res.height, rot)
            return w_rot, h_rot, "top_left"
        return int(s(0.3, canvas_w)), int(s(0.1, canvas_h)), "top_left"

    if form in ("map", "static_map"):
        map_w = int(s(cfg.get("size", 18.0), canvas_w))
        w_rot, h_rot = _rotate_dimensions(map_w, map_w, rot)
        return w_rot, h_rot, "center"

    # Dummy telemetry for geometry measurement
    val = 50.0
    unit = cfg.get("unit", "")
    label = cfg.get("label", key)
    hist = [float(i) for i in range(60)] if form == "chart" else None

    res, _, _, _ = render_value_indicator(
        canvas_w, canvas_h, layout, font_path, key, val, unit, label,
        cfg_override=cfg, formatted_val="50.0", history_data=hist,
    )

    if res is not None:
        w_rot, h_rot = _rotate_dimensions(res.width, res.height, rot)
        anchor = "top_left" if form == "text" else "center"
        return w_rot, h_rot, anchor

    # Fallback estimate if rendering returned None
    fb_w = max(50, int(s(cfg.get("size", 0.05), canvas_w)))
    fb_h = max(20, int(s(cfg.get("font_size", 0.025), canvas_h)))
    w_rot, h_rot = _rotate_dimensions(fb_w, fb_h, rot)
    anchor = "top_left" if form == "text" else "center"
    return w_rot, h_rot, anchor


def compute_single_indicator_bbox(
    key: str,
    cfg: dict[str, Any],
    layout: dict[str, Any],
    canvas_w: int = 3840,
    canvas_h: int = 2160,
    default_font_path: str = "C:/Windows/Fonts/arial.ttf",
) -> Optional[tuple[int, int, int, int]]:
    """Compute the exact AABB (x0, y0, w, h) for one indicator in pixels."""
    font_path = indicator_font_path(layout, key, default_font_path)
    form = cfg.get("form", "text")
    rot = int(cfg.get("rotation", 0)) % 360

    if key == "time_display" or form == "time_display":
        res, rx, ry = render_time_display(
            canvas_w, canvas_h, layout, font_path,
            "2026-09-15", "12:00:00", 3600.0, 25.0,
        )
        if res is not None:
            cx = rx + res.width / 2.0
            cy = ry + res.height / 2.0
            bw, bh = _rotate_dimensions(res.width, res.height, rot)
            return (int(round(cx - bw / 2.0)), int(round(cy - bh / 2.0)), int(bw), int(bh))
        return None

    if form in ("map", "static_map"):
        map_w = s(cfg.get("size", 18.0), canvas_w)
        rx = s(cfg.get("x", 0.0), canvas_w)
        ry = s(cfg.get("y", 0.0), canvas_h)
        bw, bh = _rotate_dimensions(int(map_w), int(map_w), rot)
        return (int(round(rx - bw / 2.0)), int(round(ry - bh / 2.0)), int(bw), int(bh))

    val = 50.0
    unit = cfg.get("unit", "")
    label = cfg.get("label", key)
    hist = [float(i) for i in range(60)] if form == "chart" else None

    res, rx, ry, _ = render_value_indicator(
        canvas_w, canvas_h, layout, font_path, key, val, unit, label,
        cfg_override=cfg, formatted_val="50.0", history_data=hist,
    )

    if res is not None:
        if form == "text":
            cx = rx + res.width / 2.0
            cy = ry + res.height / 2.0
        else:
            cx = rx
            cy = ry
        bw, bh = _rotate_dimensions(res.width, res.height, rot)
        return (int(round(cx - bw / 2.0)), int(round(cy - bh / 2.0)), int(bw), int(bh))

    return None


def _rotate_dimensions(w: int, h: int, rot_deg: int) -> tuple[int, int]:
    """Calculate axis-aligned bounding box width and height after rotation."""
    rot = rot_deg % 360
    if rot == 0 or rot == 180:
        return int(w), int(h)
    if rot in (90, 270):
        return int(h), int(w)
    rad = math.radians(rot)
    cos_a = abs(math.cos(rad))
    sin_a = abs(math.sin(rad))
    w_rot = int(math.ceil(w * cos_a + h * sin_a))
    h_rot = int(math.ceil(w * sin_a + h * cos_a))
    return max(1, w_rot), max(1, h_rot)


def _rects_collide(
    r1: tuple[int, int, int, int],
    r2: tuple[int, int, int, int],
    margin: int = 8,
) -> bool:
    """Return True if rectangle r1 collides with r2 considering the safety margin."""
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    return not (
        x1 + w1 + margin <= x2 or
        x2 + w2 + margin <= x1 or
        y1 + h1 + margin <= y2 or
        y2 + h2 + margin <= y1
    )


def _count_collisions(
    rect: tuple[int, int, int, int],
    active_boxes: dict[str, tuple[int, int, int, int]],
    margin: int = 8,
) -> int:
    """Count how many active indicator boxes collide with rect."""
    return sum(1 for ab in active_boxes.values() if _rects_collide(rect, ab, margin=margin))


def _calculate_total_overlap_area(
    rect: tuple[int, int, int, int],
    active_boxes: dict[str, tuple[int, int, int, int]],
    margin: int = 8,
) -> int:
    """Calculate the sum of intersection areas with active indicators."""
    x1, y1, w1, h1 = rect
    r1_x2, r1_y2 = x1 + w1, y1 + h1
    total_area = 0
    for ax, ay, aw, ah in active_boxes.values():
        ax1 = ax - margin
        ay1 = ay - margin
        ax2 = ax + aw + margin
        ay2 = ay + ah + margin
        ix1 = max(x1, ax1)
        iy1 = max(y1, ay1)
        ix2 = min(r1_x2, ax2)
        iy2 = min(r1_y2, ay2)
        if ix2 > ix1 and iy2 > iy1:
            total_area += (ix2 - ix1) * (iy2 - iy1)
    return total_area


def find_non_overlapping_position(
    layout: dict[str, Any],
    key: str,
    cfg: dict[str, Any],
    canvas_w: int = 3840,
    canvas_h: int = 2160,
    margin: int = 8,
    grid: int = 8,
    default_font_path: str = "C:/Windows/Fonts/arial.ttf",
) -> dict[str, Any]:
    """Find the nearest collision-free position for a new indicator.

    Searches outward in expanding concentric rings on the grid starting from
    the default position.

    Returns a dict containing:
        - 'x': optimal x in percent (0.0..100.0)
        - 'y': optimal y in percent (0.0..100.0)
        - 'initial_x': original default x
        - 'initial_y': original default y
        - 'initial_collisions': number of collisions at default position
        - 'final_collisions': number of collisions at chosen position (0 on success)
        - 'candidates_checked': number of candidate positions evaluated
        - 'elapsed_ms': search execution time in milliseconds
        - 'bbox': final AABB (x0, y0, w, h) in canvas pixels
    """
    t0 = time.perf_counter()

    active_boxes = get_active_indicator_bboxes(
        layout, canvas_w=canvas_w, canvas_h=canvas_h,
        default_font_path=default_font_path,
    )
    # If the key itself is already in active_boxes (e.g. overwriting), exclude it
    active_boxes.pop(key, None)

    bw, bh, anchor = measure_indicator_dimensions(
        key, cfg, layout, canvas_w=canvas_w, canvas_h=canvas_h,
        default_font_path=default_font_path,
    )

    x_pct = float(cfg.get("x", 50.0))
    y_pct = float(cfg.get("y", 50.0))
    ox = int(round(float(cfg.get("text_offset_x", 0.0)) * canvas_w))
    oy = int(round(float(cfg.get("text_offset_y", 0.0)) * canvas_h))

    if anchor == "top_left":
        px0 = s(x_pct, canvas_w) + ox
        py0 = s(y_pct, canvas_h) + oy
        bx0 = int(round(px0))
        by0 = int(round(py0))
    else:
        cx0 = s(x_pct, canvas_w)
        cy0 = s(y_pct, canvas_h)
        bx0 = int(round(cx0 - bw / 2.0))
        by0 = int(round(cy0 - bh / 2.0))

    initial_rect = (bx0, by0, bw, bh)
    initial_collisions = _count_collisions(initial_rect, active_boxes, margin=margin)

    # Check if the initial default position is already completely free and within canvas
    is_inside_canvas = (0 <= bx0 and 0 <= by0 and bx0 + bw <= canvas_w and by0 + bh <= canvas_h)
    if initial_collisions == 0 and is_inside_canvas:
        dt = (time.perf_counter() - t0) * 1000.0
        return {
            "x": x_pct,
            "y": y_pct,
            "initial_x": x_pct,
            "initial_y": y_pct,
            "initial_collisions": 0,
            "final_collisions": 0,
            "candidates_checked": 1,
            "elapsed_ms": dt,
            "bbox": initial_rect,
        }

    # Snap starting bounding box top-left to grid
    sbx0 = int(round(bx0 / grid)) * grid
    sby0 = int(round(by0 / grid)) * grid

    max_dist = max(canvas_w, canvas_h)
    max_steps = int(math.ceil(max_dist / grid))

    checked = 0
    best_pos: Optional[tuple[int, int]] = None
    min_overlap_area = float("inf")
    fallback_pos = (sbx0, sby0)

    # Expanding radial ring search
    for d in range(1, max_steps + 1):
        delta = d * grid
        pts: set[tuple[int, int]] = set()
        for step in range(-d, d + 1):
            s_px = step * grid
            pts.add((sbx0 + s_px, sby0 - delta))
            pts.add((sbx0 + s_px, sby0 + delta))
            pts.add((sbx0 - delta, sby0 + s_px))
            pts.add((sbx0 + delta, sby0 + s_px))

        # Filter strictly within canvas bounds
        valid_pts = [
            (px, py) for px, py in pts
            if 0 <= px <= canvas_w - bw and 0 <= py <= canvas_h - bh
        ]
        # Sort points in the current ring by squared Euclidean distance to (bx0, by0)
        valid_pts.sort(key=lambda p: (p[0] - bx0) ** 2 + (p[1] - by0) ** 2)

        for px, py in valid_pts:
            checked += 1
            cand_rect = (px, py, bw, bh)
            c = _count_collisions(cand_rect, active_boxes, margin=margin)
            if c == 0:
                best_pos = (px, py)
                break
            else:
                # Track minimal overlap fallback just in case canvas is 100% saturated
                area = _calculate_total_overlap_area(cand_rect, active_boxes, margin=margin)
                if area < min_overlap_area:
                    min_overlap_area = area
                    fallback_pos = (px, py)

        if best_pos is not None:
            break

    if best_pos is None:
        best_pos = fallback_pos

    final_bx, final_by = best_pos
    final_rect = (final_bx, final_by, bw, bh)
    final_collisions = _count_collisions(final_rect, active_boxes, margin=margin)

    # Convert pixel bounding box back to layout (x, y) percentages
    if anchor == "top_left":
        new_x = ((final_bx - ox) / float(canvas_w)) * 100.0
        new_y = ((final_by - oy) / float(canvas_h)) * 100.0
    else:
        new_cx = final_bx + bw / 2.0
        new_cy = final_by + bh / 2.0
        new_x = (new_cx / float(canvas_w)) * 100.0
        new_y = (new_cy / float(canvas_h)) * 100.0

    dt = (time.perf_counter() - t0) * 1000.0
    return {
        "x": round(new_x, 2),
        "y": round(new_y, 2),
        "initial_x": x_pct,
        "initial_y": y_pct,
        "initial_collisions": initial_collisions,
        "final_collisions": final_collisions,
        "candidates_checked": checked,
        "elapsed_ms": dt,
        "bbox": final_rect,
    }
