"""Intel Core Ultra 225U: Multi-Rect HUD Upload Planner & Merge Policies.

Implements Phases 4, 6, 7, 8, 9 dirty rectangle determination,
state-equality change tracking, and merge policies (None, Overlap, 8px, 16px, 32px, Cost-based).
"""

from __future__ import annotations
import os
import math
from typing import Any, Optional

def rect_intersects(r1: tuple[int, int, int, int], r2: tuple[int, int, int, int], margin: int = 0) -> bool:
    """Return True if two rectangles [l, t, r, b] intersect or are within margin pixels."""
    l1, t1, r1_x, b1 = r1
    l2, t2, r2_x, b2 = r2
    return not (r1_x + margin < l2 or r2_x + margin < l1 or b1 + margin < t2 or b2 + margin < t1)

def union_rects(r1: tuple[int, int, int, int], r2: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Return bounding box union of two rectangles."""
    return (min(r1[0], r2[0]), min(r1[1], r2[1]), max(r1[2], r2[2]), max(r1[3], r2[3]))

def rect_area(r: tuple[int, int, int, int]) -> int:
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])

def merge_rects_policy(
    rects: list[tuple[int, int, int, int]],
    policy: str = "COST",
    canvas_w: int = 2560,
    canvas_h: int = 1440,
    align: int = 16,
    overhead_bytes_equiv: int = 131072, # ~131KB transfer cost ~= 12-15us driver call overhead
) -> list[tuple[int, int, int, int]]:
    """Merge dirty rectangles based on specified policy.

    Policies:
      - 'NONE': No merging.
      - 'OVERLAP': Merge intersecting only.
      - '8PX': Merge if within 8 pixels.
      - '16PX': Merge if within 16 pixels.
      - '32PX': Merge if within 32 pixels.
      - 'COST': Merge if extra transferred bytes < overhead_bytes_equiv.
    """
    if not rects:
        return []

    # Clean & clip input rects
    valid = []
    for r in rects:
        l = max(0, min(canvas_w, r[0]))
        t = max(0, min(canvas_h, r[1]))
        rx = max(0, min(canvas_w, r[2]))
        b = max(0, min(canvas_h, r[3]))
        if rx > l and b > t:
            valid.append((l, t, rx, b))

    if not valid:
        return []

    pol = policy.upper().strip()
    if pol == "NONE":
        # Align each to 16
        res = []
        for r in valid:
            l = max(0, (r[0] // align) * align)
            t = max(0, (r[1] // align) * align)
            rx = min(canvas_w, ((r[2] + align - 1) // align) * align)
            b = min(canvas_h, ((r[3] + align - 1) // align) * align)
            res.append((l, t, rx, b))
        return res

    margin = 0
    if pol == "8PX":
        margin = 8
    elif pol == "16PX":
        margin = 16
    elif pol == "32PX":
        margin = 32

    clusters = list(valid)
    changed = True
    while changed:
        changed = False
        n = len(clusters)
        if n <= 1:
            break

        best_i = -1
        best_j = -1
        best_metric = float("inf")

        for i in range(n):
            for j in range(i + 1, n):
                r1 = clusters[i]
                r2 = clusters[j]
                u = union_rects(r1, r2)
                extra_bytes = (rect_area(u) - (rect_area(r1) + rect_area(r2))) * 4

                if pol in ("OVERLAP", "8PX", "16PX", "32PX"):
                    if rect_intersects(r1, r2, margin=margin):
                        # Intersecting or within distance: merge!
                        best_i = i
                        best_j = j
                        changed = True
                        break
                elif pol in ("COST", "COST_BASED"):
                    # If they overlap, extra_bytes <= 0 -> always merge!
                    # If they don't overlap, merge only if extra_bytes < overhead_bytes_equiv
                    if rect_intersects(r1, r2, margin=0):
                        best_i = i
                        best_j = j
                        changed = True
                        break
                    elif extra_bytes < overhead_bytes_equiv and extra_bytes < best_metric:
                        best_metric = extra_bytes
                        best_i = i
                        best_j = j

            if changed and pol != "COST" and pol != "COST_BASED":
                break

        if best_i >= 0 and best_j >= 0:
            merged = union_rects(clusters[best_i], clusters[best_j])
            clusters.pop(best_j)
            clusters.pop(best_i)
            clusters.append(merged)
            changed = True

    # Final 16-alignment
    out = []
    for c in clusters:
        l = max(0, (c[0] // align) * align)
        t = max(0, (c[1] // align) * align)
        rx = min(canvas_w, ((c[2] + align - 1) // align) * align)
        b = min(canvas_h, ((c[3] + align - 1) // align) * align)
        out.append((l, t, rx, b))
    return out


class TelemetryDirtyTracker:
    """Tracks state equality across consecutive frames to skip unchanged widgets."""

    def __init__(self, layout: dict[str, Any], widget_boxes: dict[str, tuple[int, int, int, int]]):
        self.layout = layout
        self.widget_boxes = widget_boxes
        self.prev_states: dict[str, Any] = {}
        self.total_evals = 0
        self.total_skips = 0

    def get_dirty_rects(
        self,
        frame_idx: int,
        target_fps: float,
        speed_samples: Optional[list],
        track_samples: Optional[list],
        alt_samples: Optional[list],
        field_samples: dict[str, Any],
        gps_track: Optional[list],
        policy: str = "COST"
    ) -> list[tuple[int, int, int, int]]:
        """Return list of dirty rectangles for the given frame."""
        if frame_idx == 0:
            # Frame 0: Full HUD upload initializes persistent texture
            return [(0, 0, 2560, 1440)]

        skip_heuristic = os.environ.get("TELEM_INTEL_MULTIRECT_SKIP_UNCHANGED", "0").strip() == "1"
        if not skip_heuristic:
            # All active layout widget boxes are updated to guarantee
            # bit-exact visual parity across every frame (violations=0, diff_pixels=0)
            return merge_rects_policy(list(self.widget_boxes.values()), policy=policy)

        dirty_rects: list[tuple[int, int, int, int]] = []
        cur_time_s = frame_idx / target_fps if target_fps > 0 else 0.0

        for key, box in self.widget_boxes.items():
            self.total_evals += 1
            cfg = self.layout.get("indicators", {}).get(key, {})
            form = cfg.get("form", "")

            # 1. Moving map: changes if gps_track has speed/motion
            if "map" in key or form in ("map", "moving_map", "static_map"):
                # Moving map: if moving, mark dirty
                # In Phase 2 we saw map is stationary at start; check speed
                if speed_samples:
                    # check if current speed > 0.1
                    s_idx = min(len(speed_samples) - 1, max(0, int(cur_time_s)))
                    spd = speed_samples[s_idx] if isinstance(speed_samples[s_idx], (int, float)) else (speed_samples[s_idx][1] if len(speed_samples[s_idx]) > 1 else 0)
                    if spd > 0.2:
                        dirty_rects.append(box)
                        continue
                    else:
                        self.total_skips += 1
                        continue
                else:
                    dirty_rects.append(box)
                    continue

            # 2. Charts: HR and Cadence plot rolling curves
            if form == "chart" or "chart" in key:
                # Rolling window charts update every frame
                dirty_rects.append(box)
                continue

            # 3. Speed gauge / needle
            if form == "gauge" or "speed" in key:
                # Gauge updates needle every frame when speed fluctuates
                dirty_rects.append(box)
                continue

            # 4. Text and bar widgets: check if formatted value changed
            # Extract sample value
            field_name = cfg.get("field", key.replace("fit_", "").replace("_text", ""))
            sample_list = field_samples.get(f"{field_name}_samples") or field_samples.get(field_name)
            
            val = None
            if sample_list and len(sample_list) > 0:
                s_idx = min(len(sample_list) - 1, max(0, int(cur_time_s)))
                item = sample_list[s_idx]
                val = item if isinstance(item, (int, float)) else (item[1] if len(item) > 1 else None)

            # For time_display: changes every 1s (or frame if elapsed has subseconds)
            if key == "time_display" or "time" in key:
                cur_sec = int(cur_time_s)
                if self.prev_states.get(key) != cur_sec:
                    self.prev_states[key] = cur_sec
                    dirty_rects.append(box)
                else:
                    self.total_skips += 1
                continue

            # For numeric fields: round according to decimals
            dec = cfg.get("decimals", 1)
            val_rounded = round(val, dec) if isinstance(val, (int, float)) else val

            if key not in self.prev_states or self.prev_states[key] != val_rounded:
                self.prev_states[key] = val_rounded
                dirty_rects.append(box)
            else:
                self.total_skips += 1

        # Apply merge policy
        return merge_rects_policy(dirty_rects, policy=policy)
