"""Shared helper utilities for indicator rendering.

These are extracted from ``overlay_renderer.py`` so that per-form
indicator modules can import them without circular dependencies.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

try:
    from PIL import Image, ImageFont
except ImportError:
    Image = None  # type: ignore
    ImageFont = None  # type: ignore


# ── Font cache ──────────────────────────────────────────────────────────────

FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FONT_PATH_CACHE: dict[tuple[str, str], str] = {}
_SYSTEM_FONT_MAP_CACHE: Optional[dict[str, str]] = None
PREVIEW_VIDEO_BRIGHTNESS = 0.55
_PREVIEW_DIM_LUT_CACHE: dict[float, tuple[int, ...]] = {}


def resolve_decimal_places(cfg: dict[str, Any], default: int = 1, field: str | None = None) -> int:
    """Resolve displayed numeric precision without changing source values.

    ``decimal_places`` is canonical for charts.  ``decimals`` remains a
    compatibility alias used by older indicator forms and saved presets.
    Presence is tested explicitly so that a configured value of zero is kept.
    For integer-only semantic fields, returns strictly 0.
    """
    from src.telemetry_resolver import resolve_presentation_precision
    return resolve_presentation_precision(cfg, default, field=field)


def config_decimals(cfg: dict[str, Any], default: int = 1) -> int:
    """Configured precision with the shared key precedence, without field semantics.

    Used where a renderer formats its own numbers (range labels, fallback value
    text); ``decimals``/``decimal_places`` precedence and the 0..2 clamp come
    from ``telemetry_resolver.configured_precision``.
    """
    from src.telemetry_resolver import configured_precision
    return configured_precision(cfg, default)


def dim_preview_video(img, brightness: float = PREVIEW_VIDEO_BRIGHTNESS):
    """Dim only preview-video RGB channels and preserve alpha byte-for-byte."""
    if img is None:
        return None
    try:
        factor = max(0.0, min(1.0, float(brightness)))
    except (TypeError, ValueError):
        factor = PREVIEW_VIDEO_BRIGHTNESS
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    lut_key = round(factor, 6)
    lut = _PREVIEW_DIM_LUT_CACHE.get(lut_key)
    if lut is None:
        channel_lut = tuple(int(i * factor) for i in range(256))
        lut = channel_lut * 3
        _PREVIEW_DIM_LUT_CACHE[lut_key] = lut
    rgb = rgba.convert("RGB").point(lut)
    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    return result


def _build_windows_font_map() -> dict[str, str]:
    """Build a mapping from lower-case font names/families to absolute file paths."""
    import os
    import re
    font_map: dict[str, str] = {}
    if os.name != "nt":
        return font_map

    win_dir = Path(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    local_dir = Path(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts")
    search_dirs = [local_dir, win_dir]

    # 1. Scan registry (HKCU first for user overrides, then HKLM)
    try:
        import winreg
        reg_keys = [
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        ]
        for root_h, subkey in reg_keys:
            try:
                with winreg.OpenKey(root_h, subkey) as k:
                    count = winreg.QueryInfoKey(k)[1]
                    for i in range(count):
                        raw_name, raw_val, _ = winreg.EnumValue(k, i)
                        val_str = str(raw_val).strip()
                        if not val_str:
                            continue

                        val_path = Path(val_str)
                        resolved_file: Optional[Path] = None
                        if val_path.is_absolute() and val_path.is_file():
                            resolved_file = val_path
                        else:
                            for sdir in search_dirs:
                                cand = sdir / val_str
                                if cand.is_file():
                                    resolved_file = cand
                                    break

                        if not resolved_file:
                            continue

                        file_str = str(resolved_file.resolve())
                        clean_name = re.sub(r"\s*\([^)]*\)$", "", raw_name).strip().lower()
                        if clean_name and clean_name not in font_map:
                            font_map[clean_name] = file_str

                        stem = resolved_file.stem.lower()
                        if stem not in font_map:
                            font_map[stem] = file_str
                        raw_lower = raw_name.strip().lower()
                        if raw_lower not in font_map:
                            font_map[raw_lower] = file_str
            except Exception:
                pass
    except Exception:
        pass

    # 2. Also scan font directories directly
    for sdir in search_dirs:
        if sdir.exists():
            try:
                for p in sdir.glob("*.*"):
                    if p.suffix.lower() in {".ttf", ".otf", ".ttc"}:
                        stem = p.stem.lower()
                        if stem not in font_map:
                            font_map[stem] = str(p.resolve())
            except Exception:
                pass

    return font_map


def resolve_font_file(
    raw_value: str,
    default: str = "",
    project_root: Path | None = None,
) -> tuple[str, Optional[str]]:
    """Resolve a raw font string (file path or family name) to a validated font path.

    Returns ``(effective_path, fallback_reason)``, where ``fallback_reason`` is
    ``None`` on successful resolution or a descriptive string on fallback.
    """
    import os
    global _SYSTEM_FONT_MAP_CACHE
    raw = str(raw_value or "").strip()
    if not raw:
        return default, "empty font value"

    root = project_root if project_root is not None else PROJECT_ROOT

    # A. Check as direct file path (relative to project root or absolute)
    candidate = Path(raw)
    if not candidate.is_absolute():
        rel_cand = root / candidate
        if rel_cand.is_file() and rel_cand.suffix.lower() in {".ttf", ".otf", ".ttc"}:
            candidate = rel_cand

    if candidate.is_file() and candidate.suffix.lower() in {".ttf", ".otf", ".ttc"}:
        try:
            if ImageFont is not None:
                ImageFont.truetype(str(candidate), size=8)
            return str(candidate.resolve()), None
        except Exception as e:
            return default, f"failed to load file '{candidate}': {e}"

    # B. Check Windows system/user font map (family name or stem)
    if os.name == "nt":
        if _SYSTEM_FONT_MAP_CACHE is None:
            _SYSTEM_FONT_MAP_CACHE = _build_windows_font_map()

        raw_lower = raw.lower()
        matched_file: Optional[str] = _SYSTEM_FONT_MAP_CACHE.get(raw_lower)
        if not matched_file:
            for k, v in _SYSTEM_FONT_MAP_CACHE.items():
                if k.startswith(raw_lower) or raw_lower.startswith(k):
                    matched_file = v
                    break

        if not matched_file:
            win_dir = Path(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
            local_dir = Path(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts")
            for sdir in [local_dir, win_dir]:
                for ext in (".ttf", ".otf", ".ttc"):
                    cand = sdir / f"{raw}{ext}"
                    if cand.is_file():
                        matched_file = str(cand.resolve())
                        break
                if matched_file:
                    break

        if matched_file:
            try:
                if ImageFont is not None:
                    ImageFont.truetype(matched_file, size=8)
                return matched_file, None
            except Exception as e:
                return default, f"failed to load system font '{matched_file}': {e}"

    return default, f"font '{raw}' not found"


def resolve_indicator_font_path(
    font_value: Any,
    default_font_path: str | Path | None,
    project_root: str | Path | None = None,
) -> str:
    """Resolve a per-indicator ``font`` override without changing legacy defaults.

    ``font`` supports:
    - Absolute or project-relative paths to .ttf, .otf, .ttc files
    - Installed Windows font family names (e.g. 'Digital-7', 'IONA-U1', 'Comic Sans MS')

    Fallback to ``default_font_path`` is preserved for missing/unreadable fonts.
    Diagnostic log is emitted once per unique resolution / cache miss.
    """
    default = str(default_font_path or "")
    raw = "" if font_value is None else str(font_value).strip()
    if not raw:
        return default
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    cache_key = (raw, f"{default}|{root}")
    cached = _FONT_PATH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    resolved, fallback_reason = resolve_font_file(raw, default=default, project_root=root)
    if fallback_reason is None:
        print(f"[FONT RESOLVER] requested='{raw}' -> resolved='{resolved}'")
    else:
        print(f"[FONT RESOLVER] requested='{raw}' -> fallback='{default}' reason='{fallback_reason}'")

    _FONT_PATH_CACHE[cache_key] = resolved
    return resolved


def indicator_font_path(
    layout: dict[str, Any], key: str, default_font_path: str | Path | None
) -> str:
    """Return the effective font for one layout indicator."""
    cfg = layout.get("indicators", {}).get(key, {})
    return resolve_indicator_font_path(
        cfg.get("font") if isinstance(cfg, dict) else None,
        default_font_path,
    )


def load_font_cache_small(size: int) -> Optional[ImageFont.ImageFont]:
    """Return the default PIL font at the given size (cached). Used for chart axis labels."""
    key = ("__builtin_default__", int(size))
    if key in FONT_CACHE:
        return FONT_CACHE[key]  # type: ignore[return-value]
    try:
        font = ImageFont.load_default()
        FONT_CACHE[key] = font
        return font
    except Exception:
        return None


# ── Colour parsing ─────────────────────────────────────────────────────────

def parse_hex_color(hex_str: Any) -> Optional[tuple[int, int, int]]:
    """Convert a hex colour string (e.g. '#FF3232' or 'FF3232') to an RGB tuple.
    Returns None on failure."""
    if not hex_str or not isinstance(hex_str, str):
        return None
    s = hex_str.strip().lstrip("#")
    try:
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        elif len(s) == 3:
            return (int(s[0], 16) * 17, int(s[1], 16) * 17, int(s[2], 16) * 17)
    except Exception:
        pass
    return None


def _parse_marker_color(hex_color: str) -> tuple[int, int, int, int]:
    """Convert '#RRGGBB' or '#RRGGBBAA' hex to RGBA tuple.
    Falls back to white on failure."""
    if not hex_color or not isinstance(hex_color, str):
        return (255, 255, 255, 255)
    s = hex_color.strip().lstrip("#")
    try:
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)
        elif len(s) == 8:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16))
    except Exception:
        pass
    return (255, 255, 255, 255)


# ── Scaling ────────────────────────────────────────────────────────────────

def s(value: float, base: int) -> int:
    """Scale a relative percentage value (0.0-100.0 range, where 50 is center/50%) to an absolute pixel size."""
    try:
        val = float(value)
    except (TypeError, ValueError):
        val = 0.0
    if val <= 0.0:
        return int(round((val / 100.0) * base))
    return max(1, int(round((val / 100.0) * base)))



# ── Font loading ───────────────────────────────────────────────────────────

def load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font from cache or disk. Falls back to default PIL font on failure."""
    from src.indicators.profiling import get_overlay_profiler
    profiler = get_overlay_profiler()
    lookup_started = time.perf_counter()
    key = (str(font_path), int(size))
    font = FONT_CACHE.get(key)
    if font is not None:
        profiler.record_operation(
            "font cache lookup", (time.perf_counter() - lookup_started) * 1000.0
        )
        return font

    actual_path = str(font_path) if font_path else ""
    if actual_path and not Path(actual_path).is_file():
        resolved = resolve_indicator_font_path(actual_path, actual_path)
        if resolved and Path(resolved).is_file():
            actual_path = resolved

    try:
        font = ImageFont.truetype(actual_path, size=int(size))
        # ETAP 5X: substitute only glyphs the primary font lacks (Polish letters).
        from src.indicators.font_fallback import with_glyph_fallback
        font = with_glyph_fallback(font, actual_path, int(size))
    except Exception:
        try:
            font = ImageFont.load_default(size=int(size))
        except Exception:
            font = ImageFont.load_default()
    FONT_CACHE[key] = font
    profiler.record_operation(
        "font cache lookup", (time.perf_counter() - lookup_started) * 1000.0
    )
    return font


# ── Static background cache ────────────────────────────────────────────────

class _BoundedStaticCache(OrderedDict):
    """Worker-local LRU for static indicator rasters and immutable tiles."""

    def __init__(self, max_entries: int = 128):
        super().__init__()
        self.max_entries = max(1, int(max_entries))
        self.hits = 0
        self.misses = 0

    def get(self, key, default=None):
        if key in self:
            self.hits += 1
            value = super().__getitem__(key)
            self.move_to_end(key)
            return value
        self.misses += 1
        return default

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self.max_entries:
            self.popitem(last=False)

    def stats(self) -> dict[str, int]:
        return {
            "hits": int(self.hits),
            "misses": int(self.misses),
            "entries": len(self),
            "max_entries": self.max_entries,
        }

    def clear(self):
        super().clear()
        self.hits = 0
        self.misses = 0


_STATIC_CACHE = _BoundedStaticCache(max_entries=128)
"""Bounded cache for static indicator rasters and immutable text tiles."""


def get_static_cache_stats() -> dict[str, int]:
    """Return cache diagnostics without emitting per-frame production logs."""
    return _STATIC_CACHE.stats()


def _static_cache_key(*args) -> tuple:
    """Build a hashable cache key from a set of static parameters."""
    return args


# ── ETAP 5Q compose optimization toggle ────────────────────────────────────
_COMPOSE_5Q: Optional[bool] = None


def compose_5q_optimized() -> bool:
    """ETAP 5Q: are the CPU compose optimizations enabled?

    Reads ``AMD_COMPOSE_5Q`` once per process (REFERENCE = current code,
    OPTIMIZED = value-keyed text-tile caches).  Default OPTIMIZED since ETAP
    5W: it is byte-exact (pixel-exact gate), its caches are bounded per source
    (verified constant across a 20-export soak), and at the pool8 production
    config it is faster (REF ~34.9 FPS vs OPT ~37.5 FPS).  AMD_COMPOSE_5Q
    override (REFERENCE) remains honored.
    """
    global _COMPOSE_5Q
    if _COMPOSE_5Q is None:
        import os
        _COMPOSE_5Q = os.environ.get(
            "AMD_COMPOSE_5Q", "OPTIMIZED"
        ).strip().upper() == "OPTIMIZED"
    return _COMPOSE_5Q


from functools import lru_cache


@lru_cache(maxsize=32)
def _map_style_layers(size, shape, radius, width, color):
    """Cached destination-space coverage and border; borrowed, read-only images."""
    from PIL import ImageChops, ImageDraw

    w, h = size
    aa = 4
    radius = min(max(0., radius), min(w, h) / 2.)
    width = min(max(0., width), min(w, h) / 2.)
    def coverage(inset):
        mask = Image.new("L", (w * aa, h * aa), 0)
        box = (inset * aa, inset * aa, (w - inset) * aa - 1, (h - inset) * aa - 1)
        if box[2] < box[0] or box[3] < box[1]:
            return mask.resize(size, Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(mask)
        if shape in ("round", "circle"):
            draw.ellipse(box, fill=255)
        elif shape == "rounded":
            draw.rounded_rectangle(box, radius=max(0., radius - inset) * aa, fill=255)
        else:
            draw.rectangle(box, fill=255)
        return mask.resize(size, Image.Resampling.LANCZOS)
    outer = coverage(0)
    ring = ImageChops.subtract(outer, coverage(width)) if width else Image.new("L", size, 0)
    border = Image.new("RGBA", size, color)
    border.putalpha(ring.point(lambda p: p * color[3] // 255))
    # R = outer coverage, G = border coverage; public bytes API for native upload.
    texture = Image.merge("RGBA", (outer, ring, Image.new("L", size, 0), Image.new("L", size, 255)))
    return outer, border, texture.tobytes(), color


def map_style_layers(size, shape="square", corner_radius=16., border_width=0., border_color="#FFFFFF", scale=1.):
    """Resolve persisted shape names; dimensions are logical pixels at 1080p."""
    from PIL import ImageColor
    shape = str(shape).lower()
    if shape not in ("round", "circle", "rounded") and float(border_width or 0) <= 0:
        return None
    color = ImageColor.getcolor(str(border_color or "#FFFFFF"), "RGBA")
    return _map_style_layers(tuple(size), shape, float(corner_radius or 0) * scale,
                             float(border_width or 0) * scale, color)


def apply_map_shape(img, shape: str, corner_radius=16., border_width=0., border_color="#FFFFFF", scale=1.):
    """Style the final viewport, after rotation/resize, without mutating its source."""
    if img is None:
        return img
    layers = map_style_layers(img.size, shape, corner_radius, border_width, border_color, scale)
    if layers is None:
        return img
    from PIL import ImageChops
    outer, border, _, _ = layers
    styled = img.convert("RGBA").copy()
    styled.putalpha(ImageChops.multiply(styled.getchannel("A"), outer))
    return Image.alpha_composite(styled, border)


def apply_map_opacity(img, raw_opacity: Any):
    """Apply opacity (0.0..1.0) to a rendered map image.

    Normalizes legacy 1.0..10.0 or percentage (10..100) ranges cleanly.
    """
    if img is None or raw_opacity is None:
        return img
    try:
        op = float(raw_opacity)
        if op > 1.0 and op <= 10.0:
            op = op / 10.0
        elif op > 10.0 and op <= 100.0:
            op = op / 100.0
        op = max(0.0, min(1.0, op))
        if op < 1.0:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            r, g, b, a = img.split()
            a = a.point(lambda p: int(round(p * op)))
            return Image.merge("RGBA", (r, g, b, a))
    except Exception:
        pass
    return img


def _find_perspective_coeffs(pa, pb):
    """Solve 8 perspective matrix coefficients using pure-Python Gaussian elimination."""
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0]*p1[0], -p2[0]*p1[1], p2[0]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1]*p1[0], -p2[1]*p1[1], p2[1]])

    n = 8
    for i in range(n):
        max_el = abs(matrix[i][i])
        max_row = i
        for k in range(i + 1, n):
            if abs(matrix[k][i]) > max_el:
                max_el = abs(matrix[k][i])
                max_row = k
        matrix[i], matrix[max_row] = matrix[max_row], matrix[i]
        for k in range(i + 1, n):
            c = -matrix[k][i] / matrix[i][i]
            for j in range(i, n + 1):
                if i == j:
                    matrix[k][j] = 0
                else:
                    matrix[k][j] += c * matrix[i][j]

    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = matrix[i][n] / matrix[i][i]
        for k in range(i - 1, -1, -1):
            matrix[k][n] -= matrix[k][i] * x[i]
    return x


_MAP_PITCH_CACHE: dict[tuple[int, int, float], tuple[Any, Any, list[tuple[float, float]]]] = {}


def compute_map_pitch_quad(w: int, h: int, raw_pitch: Any) -> list[tuple[float, float]]:
    """Compute 2D destination quadrilateral for a 3D perspective pitch tilt.

    Returns 4 corner points: [top_left, top_right, bottom_right, bottom_left].
    For pitch <= 0.001 deg, returns the exact rectangular bounds.
    """
    if w <= 0 or h <= 0:
        return [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)]
    try:
        pitch_deg = float(raw_pitch or 0.0)
    except Exception:
        pitch_deg = 0.0

    if pitch_deg <= 0.001:
        return [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]

    import math
    pitch_deg = min(70.0, max(0.0, pitch_deg))
    d = 1.2 * max(w, h)
    theta = math.radians(pitch_deg)
    sin_t = math.sin(theta)
    cos_t = math.cos(theta)

    z_top = d + h * sin_t
    w_top = w * (d / z_top)
    x_tl = (w - w_top) / 2.0
    x_tr = (w + w_top) / 2.0
    dy_top = (h * d * cos_t) / z_top
    y_top = h - dy_top

    return [
        (float(x_tl), float(y_top)),
        (float(x_tr), float(y_top)),
        (float(w), float(h)),
        (0.0, float(h)),
    ]


def _get_map_pitch_transforms(w: int, h: int, pitch_deg: float):
    """Retrieve or compute cached OpenCV homography and Pillow perspective coefficients."""
    cache_key = (w, h, round(pitch_deg, 2))
    cached = _MAP_PITCH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    quad = compute_map_pitch_quad(w, h, pitch_deg)
    src_pts = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
    # The tilted map plane projects to a trapezoid.  The perspective acts on the
    # content only: scale the trapezoid about the box so its largest inscribed
    # axis-aligned rectangle (narrow far edge x full depth) fills the whole box.
    # The map box therefore stays fully covered and the selected shape (square,
    # rounded, circle) is applied to the final image without trapezoid corners.
    (x_tl, y_top), (x_tr, _), _, _ = quad
    sx = float(w) / max(1e-6, x_tr - x_tl)
    sy = float(h) / max(1e-6, float(h) - y_top)
    dst_pts = [((x - x_tl) * sx, (y - y_top) * sy) for x, y in quad]

    cv2_M = None
    pil_coeffs = None

    try:
        import cv2
        import numpy as np
        cv2_M = cv2.getPerspectiveTransform(
            np.float32(src_pts),
            np.float32(dst_pts),
        )
        M_inv = np.linalg.inv(cv2_M)
        M_inv /= M_inv[2, 2]
        pil_coeffs = tuple(float(x) for x in M_inv.flatten()[:8])
    except Exception:
        pass

    if pil_coeffs is None:
        # Pure Python fallback
        pil_coeffs = tuple(_find_perspective_coeffs(dst_pts, src_pts))

    result = (cv2_M, pil_coeffs, quad)
    if len(_MAP_PITCH_CACHE) > 128:
        _MAP_PITCH_CACHE.clear()
    _MAP_PITCH_CACHE[cache_key] = result
    return result


def apply_map_pitch(img, raw_pitch: Any):
    """Apply true 3D perspective pitch tilt (0..70 degrees) to a rendered map image.

    Models the map as a flat 3D plane viewed at a pitch angle by a camera.  The result
    always covers the full map box (perspective inside, no trapezoid outline), so the
    map shape/border must be applied AFTER this call.
    For pitch == 0, returns the exact legacy unwarped image without any overhead.
    """
    if img is None or raw_pitch is None:
        return img
    try:
        pitch_deg = float(raw_pitch)
    except (ValueError, TypeError):
        return img

    if pitch_deg <= 0.001:
        return img

    pitch_deg = min(70.0, max(0.0, pitch_deg))
    w, h = img.size
    if w <= 0 or h <= 0:
        return img

    try:
        cv2_M, pil_coeffs, _ = _get_map_pitch_transforms(w, h, pitch_deg)

        if img.mode != "RGBA":
            img = img.convert("RGBA")

        if cv2_M is not None:
            try:
                import cv2
                import numpy as np
                arr = np.array(img)
                warped = cv2.warpPerspective(
                    arr,
                    cv2_M,
                    (w, h),
                    flags=cv2.INTER_LINEAR,
                    # The warped content covers the whole box; replicate the edge so
                    # bilinear sampling never leaves a transparent outer row/column.
                    borderMode=cv2.BORDER_REPLICATE,
                )
                return Image.fromarray(warped)
            except Exception:
                pass

        return img.transform(
            (w, h),
            Image.PERSPECTIVE,
            pil_coeffs,
            Image.BILINEAR,
            fillcolor=(0, 0, 0, 0),
        )
    except Exception:
        return img


def get_arial_fallback_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Legacy helper: returns Arial font (kept for backwards compatibility; degree rendering now uses vector graphics)."""
    return load_font("arial", max(8, int(size)))


def get_graphic_degree_metrics(
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    stroke_width: int = 0,
) -> dict[str, float]:
    """Calculate geometric metrics for drawing the vector degree ring next to text.

    Dimensions are proportional to the font's digit cap-height and stroke width.
    """
    sw = max(0, int(stroke_width))
    try:
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
        ref_box = probe.textbbox((0, 0), "0", font=font, anchor="la")
        cap_top = float(ref_box[1])
        cap_bottom = float(ref_box[3])
        cap_h = max(8.0, cap_bottom - cap_top)
    except Exception:
        size = float(getattr(font, "size", 16))
        cap_h = max(8.0, size * 0.72)
        cap_top = size * 0.28
        cap_bottom = cap_top + cap_h

    # Degree circle diameter: ~28% of digit cap-height
    diameter = max(3.0, round(cap_h * 0.28))
    # Line thickness of the degree ring: ~22% of diameter, minimum 1 px
    thickness = max(1, int(round(diameter * 0.22)))
    # Advance padding around the circle
    gap_before = max(1.0, round(cap_h * 0.08))
    gap_after = max(1.0, round(cap_h * 0.06))
    advance = gap_before + diameter + gap_after
    # Vertical placement: superscript aligned with upper portion of digit cap-height
    deg_top = cap_top + round(cap_h * 0.04)

    return {
        "cap_h": cap_h,
        "cap_top": cap_top,
        "diameter": float(diameter),
        "thickness": float(thickness),
        "gap_before": float(gap_before),
        "gap_after": float(gap_after),
        "advance": float(advance),
        "deg_top": float(deg_top),
        "sw": float(sw),
    }


def split_text_degree_chunks(
    text: str,
    main_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> list[tuple[str, Any]]:
    """Dzieli tekst na segmenty tekstu oraz znaki stopnia '°'.

    Dla segmentów tekstowych zwraca (tekst, main_font).
    Dla symbolu stopnia '°' zwraca ('°', None), co oznacza rysowanie
    graficznego kółka stopnia bez użycia żadnego glifu fontowego.
    """
    if not text:
        return []
    if "°" not in text:
        return [(text, main_font)]

    chunks: list[tuple[str, Any]] = []
    current_buf: list[str] = []
    for ch in text:
        if ch == "°":
            if current_buf:
                chunks.append(("".join(current_buf), main_font))
                current_buf = []
            chunks.append(("°", None))
        else:
            current_buf.append(ch)
    if current_buf:
        chunks.append(("".join(current_buf), main_font))
    return chunks


def draw_graphic_degree_symbol(
    draw: ImageDraw.ImageDraw,
    rect: tuple[float, float, float, float],
    thickness: int = 1,
    fill: Any = None,
    stroke_width: int = 0,
    stroke_fill: Any = None,
) -> tuple[float, float, float, float]:
    """Rysuje graficzne, wektorowe kółko stopnia (okrąg/ring) niezależnie od fontu.

    Obsługuje obrys (stroke_width, stroke_fill) oraz kolor wypełnienia/linii znaku.
    Zwraca rzeczywisty bounding box wyrenderowanego kółka z uwzględnieniem obrysu.
    """
    x0, y0, x1, y1 = rect
    sw = max(0, int(stroke_width))
    th = max(1, int(thickness))
    fill_col = fill if fill is not None else (255, 255, 255, 255)

    # 1. Stroke / outline pass (outer ring contour)
    if sw > 0 and stroke_fill is not None:
        s_th = max(1, min(int(round(th + 2 * sw)), int(round((x1 - x0) + 2 * sw))))
        draw.ellipse(
            [int(round(x0 - sw)), int(round(y0 - sw)), int(round(x1 + sw)), int(round(y1 + sw))],
            fill=None,
            outline=stroke_fill,
            width=s_th,
        )

    # 2. Main inner ring pass
    r_th = max(1, min(th, int(round(x1 - x0))))
    draw.ellipse(
        [int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))],
        fill=None,
        outline=fill_col,
        width=r_th,
    )

    return (float(x0 - sw), float(y0 - sw), float(x1 + sw), float(y1 + sw))


def measure_text_with_graphic_degree(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    stroke_width: int = 0,
    anchor: str | None = None,
) -> tuple[float, float, tuple[float, float, float, float]]:
    """Mierzy łączną szerokość advance, wysokość oraz bounding box tekstu z graficznym symbolem '°'.

    Zwraca: (total_advance_width, total_height, (min_x, min_y, max_x, max_y))
    """
    text_str = str(text or "")
    if not text_str:
        return 0.0, 0.0, (0.0, 0.0, 0.0, 0.0)

    if "°" not in text_str:
        kwargs: dict[str, Any] = {"font": font, "stroke_width": int(stroke_width)}
        if anchor is not None:
            kwargs["anchor"] = anchor
        bbox = draw.textbbox((0, 0), text_str, **kwargs)
        length = draw.textlength(text_str, font=font)
        w = max(length, bbox[2] - bbox[0])
        h = max(0.0, bbox[3] - bbox[1])
        return float(w), float(h), (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))

    chunks = split_text_degree_chunks(text_str, font)
    if not chunks:
        return 0.0, 0.0, (0.0, 0.0, 0.0, 0.0)

    curr_x = 0.0
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    m = get_graphic_degree_metrics(font, stroke_width=stroke_width)
    sw = m["sw"]

    for chunk_text, _ in chunks:
        if chunk_text == "°":
            x0 = curr_x + m["gap_before"]
            y0 = m["deg_top"]
            x1 = x0 + m["diameter"]
            y1 = y0 + m["diameter"]
            c_bbox = (x0 - sw, y0 - sw, x1 + sw, y1 + sw)
            c_len = m["advance"]
        else:
            c_bbox = draw.textbbox((curr_x, 0), chunk_text, font=font, stroke_width=int(stroke_width), anchor="la")
            c_len = draw.textlength(chunk_text, font=font)

        min_x = min(min_x, c_bbox[0])
        min_y = min(min_y, c_bbox[1])
        max_x = max(max_x, c_bbox[2], curr_x + c_len)
        max_y = max(max_y, c_bbox[3])
        curr_x += c_len

    total_w = max(curr_x, max_x - min_x)
    total_h = max_y - min_y if max_y > min_y else 0.0

    if anchor is not None:
        anchor_str = str(anchor).lower()
        ax = anchor_str[0] if anchor_str else "l"
        ay = anchor_str[1] if len(anchor_str) > 1 else "a"
        shift_x = 0.0 if ax == "l" else (-total_w / 2.0 if ax in ("m", "c") else -total_w)
        shift_y = (
            0.0
            if ay == "a"
            else (-min_y if ay == "t" else (-(min_y + max_y) / 2.0 if ay in ("m", "c") else -max_y))
        )
        return (
            float(total_w),
            float(total_h),
            (float(min_x + shift_x), float(min_y + shift_y), float(max_x + shift_x), float(max_y + shift_y)),
        )

    return float(total_w), float(total_h), (float(min_x), float(min_y), float(max_x), float(max_y))


def draw_text_with_graphic_degree(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: Any = None,
    stroke_width: int = 0,
    stroke_fill: Any = None,
    anchor: str | None = None,
) -> tuple[float, float, float, float]:
    """Rysuje tekst z graficznym symbolem '°' renderowanym jako wektorowy okrąg.

    Zachowuje wybrany font dla wszystkich znaków poza stopniem, gwarantując
    idealne renderowanie symbolu stopni niezależnie od rodziny i metryk fontu.
    Zwraca rzeczywisty bounding box wyrenderowanego tekstu: (left, top, right, bottom).
    """
    text_str = str(text or "")
    if not text_str:
        return (float(xy[0]), float(xy[1]), float(xy[0]), float(xy[1]))

    if "°" not in text_str:
        kwargs: dict[str, Any] = {"font": font, "fill": fill}
        if stroke_width > 0:
            kwargs["stroke_width"] = int(stroke_width)
            if stroke_fill is not None:
                kwargs["stroke_fill"] = stroke_fill
        if anchor is not None:
            kwargs["anchor"] = anchor
        draw.text(xy, text_str, **kwargs)
        try:
            bbox = draw.textbbox(xy, text_str, font=font, anchor=anchor, stroke_width=int(stroke_width))
        except TypeError:
            bbox = draw.textbbox(xy, text_str, font=font, stroke_width=int(stroke_width))
        return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))

    chunks = split_text_degree_chunks(text_str, font)
    chunk_metrics = []
    curr_x = 0.0
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    m = get_graphic_degree_metrics(font, stroke_width=stroke_width)
    sw = m["sw"]

    for chunk_text, _ in chunks:
        if chunk_text == "°":
            x0 = curr_x + m["gap_before"]
            y0 = m["deg_top"]
            x1 = x0 + m["diameter"]
            y1 = y0 + m["diameter"]
            c_bbox = (x0 - sw, y0 - sw, x1 + sw, y1 + sw)
            c_len = m["advance"]
            chunk_metrics.append(("°", None, curr_x, c_len, c_bbox, m))
        else:
            c_bbox = draw.textbbox((curr_x, 0), chunk_text, font=font, stroke_width=int(stroke_width), anchor="la")
            c_len = draw.textlength(chunk_text, font=font)
            chunk_metrics.append((chunk_text, font, curr_x, c_len, c_bbox, None))

        min_x = min(min_x, c_bbox[0])
        min_y = min(min_y, c_bbox[1])
        max_x = max(max_x, c_bbox[2], curr_x + c_len)
        max_y = max(max_y, c_bbox[3])
        curr_x += c_len

    total_w = curr_x
    total_h = max_y - min_y if max_y > min_y else 0.0

    ox, oy = float(xy[0]), float(xy[1])
    anchor_str = str(anchor or "la").lower()

    ax = anchor_str[0] if anchor_str else "l"
    ay = anchor_str[1] if len(anchor_str) > 1 else "a"

    if ax == "l":
        shift_x = 0.0
    elif ax in ("m", "c"):
        shift_x = -total_w / 2.0
    elif ax == "r":
        shift_x = -total_w
    else:
        shift_x = 0.0

    if ay == "a":
        shift_y = 0.0
    elif ay == "t":
        shift_y = -min_y
    elif ay in ("m", "c"):
        shift_y = -(min_y + max_y) / 2.0
    elif ay in ("b", "d"):
        shift_y = -max_y
    else:
        shift_y = 0.0

    drawn_boxes = []
    for c_text, c_font, c_offset_x, _, _, c_m in chunk_metrics:
        if c_text == "°":
            x0 = ox + shift_x + c_offset_x + c_m["gap_before"]
            y0 = oy + shift_y + c_m["deg_top"]
            x1 = x0 + c_m["diameter"]
            y1 = y0 + c_m["diameter"]
            b = draw_graphic_degree_symbol(
                draw,
                (x0, y0, x1, y1),
                thickness=int(c_m["thickness"]),
                fill=fill,
                stroke_width=int(c_m["sw"]),
                stroke_fill=stroke_fill,
            )
            drawn_boxes.append(b)
        else:
            pos = (ox + shift_x + c_offset_x, oy + shift_y)
            kwargs = {"font": c_font, "fill": fill, "anchor": "la"}
            if stroke_width > 0:
                kwargs["stroke_width"] = int(stroke_width)
                if stroke_fill is not None:
                    kwargs["stroke_fill"] = stroke_fill
            try:
                draw.text(pos, c_text, **kwargs)
                b = draw.textbbox(pos, c_text, font=c_font, stroke_width=int(stroke_width), anchor="la")
            except TypeError:
                kwargs.pop("anchor", None)
                draw.text(pos, c_text, **kwargs)
                b = draw.textbbox(pos, c_text, font=c_font, stroke_width=int(stroke_width))
            drawn_boxes.append(b)

    if drawn_boxes:
        return (
            min(b[0] for b in drawn_boxes),
            min(b[1] for b in drawn_boxes),
            max(b[2] for b in drawn_boxes),
            max(b[3] for b in drawn_boxes),
        )
    return (ox, oy, ox + total_w, oy + total_h)


# Compatibility aliases
measure_text_with_degree_fallback = measure_text_with_graphic_degree
draw_text_with_degree_fallback = draw_text_with_graphic_degree


