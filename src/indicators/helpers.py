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


def resolve_decimal_places(cfg: dict[str, Any], default: int = 1) -> int:
    """Resolve displayed numeric precision without changing source values.

    ``decimal_places`` is canonical for charts.  ``decimals`` remains a
    compatibility alias used by older indicator forms and saved presets.
    Presence is tested explicitly so that a configured value of zero is kept.
    """
    from src.telemetry_resolver import resolve_presentation_precision
    return resolve_presentation_precision(cfg, default)


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
    return max(1, int(round((value / 100.0) * base)))



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


_MAP_MASK_CACHE: dict[tuple[int, int], Image.Image] = {}


def apply_map_shape(img, shape: str):
    """Apply the configured map shape to a rendered map image.

    - ``"round"`` (or ``"circle"``) → circular crop (alpha mask).
    - anything else → square (the map is already rendered square).

    Returns the (possibly modified) image.
    """
    if img is None:
        return img
    if str(shape).lower() not in ("round", "circle"):
        return img
    try:
        from PIL import ImageDraw

        w, h = img.size
        mask_key = (w, h)
        mask = _MAP_MASK_CACHE.get(mask_key)
        if mask is None:
            mask = Image.new("L", (w, h), 0)
            d = ImageDraw.Draw(mask)
            d.ellipse((0, 0, w - 1, h - 1), fill=255)
            _MAP_MASK_CACHE[mask_key] = mask
        img = img.copy()
        img.putalpha(mask)
    except Exception:
        pass
    return img


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
    dst_pts = quad

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

    Models the map as a flat 3D quadrilateral viewed at a pitch angle by a camera.
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
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=(0, 0, 0, 0),
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
