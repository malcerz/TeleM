"""Opt-in ETAP 5A instrumentation for the production Pillow HUD path.

The profiler is deliberately observational: when ``AMD_OVERLAY_PROFILE`` is
off all helpers are no-ops, and when it is on wrappers forward the original
arguments and return values unchanged.
"""

from __future__ import annotations

import contextlib
import os
import statistics
import threading
import time
from collections import defaultdict
from typing import Any, Iterator


def _enabled_from_env() -> bool:
    return os.environ.get("AMD_OVERLAY_PROFILE", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


class OverlayProfiler:
    def __init__(self) -> None:
        self.enabled = _enabled_from_env()
        self._local = threading.local()
        self._frames: list[dict[str, dict[str, float]]] = []
        self._geometries: dict[str, list[dict[str, float | int | str]]] = defaultdict(list)
        self._previous_bboxes: dict[str, tuple[int, int, int, int]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._hooks_installed = False

    @property
    def active(self) -> bool:
        return self.enabled and getattr(self._local, "frame", None) is not None

    def install_pillow_hooks(self) -> None:
        if not self.enabled or self._hooks_installed:
            return
        from PIL import Image, ImageDraw, ImageFont

        self._hooks_installed = True

        original_new = Image.new

        def profiled_new(*args, **kwargs):
            started = time.perf_counter()
            result = original_new(*args, **kwargs)
            elapsed = (time.perf_counter() - started) * 1000.0
            size = getattr(result, "size", (0, 0))
            self.record_operation("Image.new", elapsed, int(size[0]) * int(size[1]))
            return result

        Image.new = profiled_new

        def wrap_image_method(name: str) -> None:
            original = getattr(Image.Image, name)

            def wrapped(image, *args, **kwargs):
                started = time.perf_counter()
                result = original(image, *args, **kwargs)
                elapsed = (time.perf_counter() - started) * 1000.0
                pixels = int(image.width) * int(image.height)
                self.record_operation(name, elapsed, pixels)
                return result

            setattr(Image.Image, name, wrapped)

        for method in (
            "resize", "rotate", "transform", "paste", "alpha_composite",
            "crop", "copy", "getbbox", "filter", "transpose",
        ):
            wrap_image_method(method)

        original_alpha_composite = Image.alpha_composite

        def profiled_alpha_composite(*args, **kwargs):
            started = time.perf_counter()
            result = original_alpha_composite(*args, **kwargs)
            elapsed = (time.perf_counter() - started) * 1000.0
            size = getattr(result, "size", (0, 0))
            self.record_operation(
                "alpha_composite", elapsed, int(size[0]) * int(size[1])
            )
            return result

        Image.alpha_composite = profiled_alpha_composite

        original_draw = ImageDraw.Draw

        def profiled_draw(*args, **kwargs):
            started = time.perf_counter()
            result = original_draw(*args, **kwargs)
            self.record_operation(
                "ImageDraw", (time.perf_counter() - started) * 1000.0
            )
            return result

        ImageDraw.Draw = profiled_draw

        def wrap_draw_method(name: str, operation: str) -> None:
            original = getattr(ImageDraw.ImageDraw, name)

            def wrapped(draw, *args, **kwargs):
                started = time.perf_counter()
                result = original(draw, *args, **kwargs)
                self.record_operation(
                    operation, (time.perf_counter() - started) * 1000.0
                )
                return result

            setattr(ImageDraw.ImageDraw, name, wrapped)

        wrap_draw_method("text", "text drawing")
        wrap_draw_method("textbbox", "textbbox/getbbox")
        for method in ("line", "polygon", "ellipse", "rectangle", "arc"):
            if hasattr(ImageDraw.ImageDraw, method):
                wrap_draw_method(method, "ImageDraw primitives")

        original_truetype = ImageFont.truetype

        def profiled_truetype(*args, **kwargs):
            started = time.perf_counter()
            result = original_truetype(*args, **kwargs)
            self.record_operation(
                "font lookup/load", (time.perf_counter() - started) * 1000.0
            )
            return result

        ImageFont.truetype = profiled_truetype

        for font_class in (ImageFont.FreeTypeFont, ImageFont.ImageFont):
            if not hasattr(font_class, "getbbox"):
                continue
            original_getbbox = font_class.getbbox

            def profiled_getbbox(font, *args, __original=original_getbbox, **kwargs):
                started = time.perf_counter()
                result = __original(font, *args, **kwargs)
                self.record_operation(
                    "textbbox/getbbox", (time.perf_counter() - started) * 1000.0
                )
                return result

            font_class.getbbox = profiled_getbbox

    def start_frame(self, frame_index: int, canvas_w: int, canvas_h: int) -> None:
        if not self.enabled:
            return
        self.install_pillow_hooks()
        self._local.frame = {
            "frame_index": frame_index,
            "canvas_w": canvas_w,
            "canvas_h": canvas_h,
            "metrics": defaultdict(float),
            "calls": defaultdict(float),
            "pixels": defaultdict(float),
        }
        self._local.indicator = None

    def finish_frame(self) -> None:
        if not self.active:
            return
        frame = self._local.frame
        self._frames.append({
            "metrics": dict(frame["metrics"]),
            "calls": dict(frame["calls"]),
            "pixels": dict(frame["pixels"]),
        })
        self._local.frame = None
        self._local.indicator = None

    def record(self, name: str, elapsed_ms: float, calls: float = 1.0) -> None:
        if not self.active:
            return
        frame = self._local.frame
        frame["metrics"][name] += float(elapsed_ms)
        frame["calls"][name] += float(calls)
        indicator = getattr(self._local, "indicator", None)
        if indicator and (name.startswith("map.") or name.startswith("graph.")):
            indicator_name = f"indicator.{indicator}.{name}"
            frame["metrics"][indicator_name] += float(elapsed_ms)
            frame["calls"][indicator_name] += float(calls)

    def record_operation(self, operation: str, elapsed_ms: float, pixels: int = 0) -> None:
        if not self.active:
            return
        global_name = f"pillow.{operation}"
        self.record(global_name, elapsed_ms)
        if pixels:
            self._local.frame["pixels"][global_name] += float(pixels)
        indicator = getattr(self._local, "indicator", None)
        if indicator:
            indicator_name = f"indicator.{indicator}.pillow.{operation}"
            self.record(indicator_name, elapsed_ms)
            if pixels:
                self._local.frame["pixels"][indicator_name] += float(pixels)

    @contextlib.contextmanager
    def measure(self, name: str) -> Iterator[None]:
        if not self.active:
            yield
            return
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record(name, (time.perf_counter() - started) * 1000.0)

    @contextlib.contextmanager
    def indicator(self, key: str) -> Iterator[None]:
        if not self.active:
            yield
            return
        previous = getattr(self._local, "indicator", None)
        self._local.indicator = key
        try:
            yield
        finally:
            self._local.indicator = previous

    def set_indicator_metadata(self, key: str, **metadata: Any) -> None:
        if self.enabled:
            self._metadata.setdefault(key, {}).update(metadata)

    @staticmethod
    def _clip_with_pad(
        bbox: tuple[int, int, int, int], width: int, height: int, pad: int = 40
    ) -> tuple[int, int, int, int] | None:
        x, y, w, h = bbox
        left = max(0, x - pad)
        top = max(0, y - pad)
        right = min(width, x + w + pad)
        bottom = min(height, y + h + pad)
        if right <= left or bottom <= top:
            return None
        return left, top, right - left, bottom - top

    def record_indicator_geometry(
        self,
        key: str,
        bbox: tuple[int, int, int, int],
        render_size: tuple[int, int],
        canvas_size: tuple[int, int],
        supersample: int,
        form: str,
    ) -> None:
        if not self.active:
            return
        canvas_w, canvas_h = canvas_size
        current_dirty = self._clip_with_pad(bbox, canvas_w, canvas_h)
        previous = self._previous_bboxes.get(key)
        previous_dirty = (
            self._clip_with_pad(previous, canvas_w, canvas_h) if previous else None
        )
        dirty_rects = [rect for rect in (current_dirty, previous_dirty) if rect]
        if dirty_rects:
            left = min(rect[0] for rect in dirty_rects)
            top = min(rect[1] for rect in dirty_rects)
            right = max(rect[0] + rect[2] for rect in dirty_rects)
            bottom = max(rect[1] + rect[3] for rect in dirty_rects)
            dirty_area = (right - left) * (bottom - top)
        else:
            dirty_area = 0
        render_area = max(0, render_size[0]) * max(0, render_size[1])
        canvas_area = canvas_w * canvas_h
        self._geometries[key].append({
            "render_width": render_size[0],
            "render_height": render_size[1],
            "render_area_px": render_area,
            "dirty_area_px": dirty_area,
            "render_canvas_pct": 100.0 * render_area / max(1, canvas_area),
            "dirty_canvas_pct": 100.0 * dirty_area / max(1, canvas_area),
            "supersample": supersample,
            "form": form,
        })
        self._previous_bboxes[key] = bbox

    def record_full_canvas(self, operation: str, elapsed_ms: float, reason: str) -> None:
        self.record(f"full_canvas.{operation}", elapsed_ms)
        if self.active:
            self._metadata.setdefault("__full_canvas__", {}).setdefault(
                operation, reason
            )

    @staticmethod
    def _summary(values: list[float], calls: list[float], pixels: list[float]) -> dict[str, Any]:
        return {
            "frames": len(values),
            "avg_ms": statistics.fmean(values) if values else 0.0,
            "median_ms": statistics.median(values) if values else 0.0,
            "p95_ms": _percentile(values, 0.95),
            "p99_ms": _percentile(values, 0.99),
            "total_calls": int(round(sum(calls))),
            "avg_calls_per_frame": statistics.fmean(calls) if calls else 0.0,
            "avg_pixels_per_frame": statistics.fmean(pixels) if pixels else 0.0,
            "p95_pixels_per_frame": _percentile(pixels, 0.95),
        }

    def summary(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        metric_keys = sorted({
            key for frame in self._frames for key in frame["metrics"]
        })
        metrics: dict[str, Any] = {}
        for key in metric_keys:
            values = [frame["metrics"].get(key, 0.0) for frame in self._frames]
            calls = [frame["calls"].get(key, 0.0) for frame in self._frames]
            pixels = [frame["pixels"].get(key, 0.0) for frame in self._frames]
            metrics[key] = self._summary(values, calls, pixels)

        geometry_summary: dict[str, Any] = {}
        for key, entries in self._geometries.items():
            def avg(field: str) -> float:
                return statistics.fmean(float(entry[field]) for entry in entries)

            geometry_summary[key] = {
                "frames": len(entries),
                "render_width": int(round(avg("render_width"))),
                "render_height": int(round(avg("render_height"))),
                "render_area_avg_px": avg("render_area_px"),
                "dirty_area_avg_px": avg("dirty_area_px"),
                "render_canvas_avg_pct": avg("render_canvas_pct"),
                "dirty_canvas_avg_pct": avg("dirty_canvas_pct"),
                "supersample": int(round(avg("supersample"))),
                "form": entries[0]["form"],
            }
        return {
            "enabled": True,
            "frames": len(self._frames),
            "metrics": metrics,
            "geometry": geometry_summary,
            "metadata": self._metadata,
        }


_PROFILER = OverlayProfiler()


def get_overlay_profiler() -> OverlayProfiler:
    return _PROFILER


def profile_scope(name: str):
    return _PROFILER.measure(name)


def indicator_scope(key: str):
    return _PROFILER.indicator(key)
