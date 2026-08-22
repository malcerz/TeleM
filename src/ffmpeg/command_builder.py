"""FFmpeg command line arguments builder.
"""

from __future__ import annotations

import os
from typing import Any
from src.ffmpeg.detection import _test_encoder

RESOLUTION_MAP: dict[str, tuple[int, int] | None] = {
    "source": None,
    "8k": (7680, 4320),
    "5.3k": (5312, 2988),
    "4k": (3840, 2160),
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "480p": (854, 480),
}

# NVIDIA rotation=180 CUDA fast-path (production default).
#
# For encoder == "nv" and effective rotation == 180 the CUDA fast-path
# (scale_cuda / overlay_cuda / -pix_fmt cuda, HUD canvas rotated 180 deg in
# Python, displaymatrix rotate=180 injected into the container) is the DEFAULT
# production path. It is NOT gated by an enable flag.
#
# Legacy opt-out (forces the old CPU path: vflip,hflip + software scale/overlay
# + hevc_nvenc yuv420p): TELEM_NV_ROT180_CPU_FALLBACK=1 (truthy, case/whitespace-
# insensitive). Unset/""/"0"/"false"/"no" → CUDA fast-path stays active.
# rotation 0 / 90 / 270 and non-NVIDIA encoders are unaffected.
NV_ROT180_CPU_FALLBACK_ENV = "TELEM_NV_ROT180_CPU_FALLBACK"
_NV_ROT180_ON_VALUES = {"1", "true", "yes", "on"}


def _env_flag_on(name: str) -> bool:
    """True only when the env var is explicitly in the ON set (default OFF)."""
    return os.environ.get(name, "").strip().lower() in _NV_ROT180_ON_VALUES


def is_nv_rot180_cuda(
    encoder: str,
    rotation_degrees: int,
    container_rotation: int = 0,
) -> bool:
    """Return True when NVIDIA rotation=180 uses the CUDA fast-path.

    Default ON for encoder == "nv" and effective rotation == 180.
    Opt-out: TELEM_NV_ROT180_CPU_FALLBACK truthy forces the legacy CPU path.
    rotation 0 / 90 / 270 and non-NVIDIA encoders are unaffected.
    """
    if encoder != "nv":
        return False
    effective = container_rotation if container_rotation != 0 else rotation_degrees
    if effective != 180:
        return False
    return not _env_flag_on(NV_ROT180_CPU_FALLBACK_ENV)



def scale_filter_for_resolution(resolution_name: str) -> str:
    """Return an ffmpeg scale filter string for the given resolution name."""
    target = RESOLUTION_MAP.get(resolution_name)
    if not target:
        return "[0:v]null[base]"
    w, h = target
    return f"[0:v]scale={w}:{h}:flags=lanczos[base]"


def append_bitrate_args(cmd: list[str], encoder: str, video_bitrate: str) -> list[str]:
    """Append bitrate arguments to an ffmpeg command."""
    if not video_bitrate:
        return cmd
    if encoder in ("nv", "amd"):
        cmd.extend(["-b:v", video_bitrate, "-maxrate", video_bitrate])
        bufsize = video_bitrate
        try:
            if video_bitrate.lower().endswith("m"):
                bufsize = f"{float(video_bitrate[:-1]) * 2:g}M"
            elif video_bitrate.lower().endswith("k"):
                bufsize = f"{float(video_bitrate[:-1]) * 2:g}k"
        except Exception:
            pass
        cmd.extend(["-bufsize", bufsize])
    else:
        cmd.extend(["-b:v", video_bitrate])
    return cmd


def get_layout_hud_bbox(layout: dict[str, Any], canvas_w: int, canvas_h: int) -> tuple[int, int, int, int]:
    """Compute combined bounding box (x, y, w, h) of enabled indicators in layout."""
    indicators = layout.get("indicators", {})
    custom_texts = layout.get("custom_texts", [])

    enabled_indicators = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}
    if not enabled_indicators and not custom_texts:
        return 0, 0, 2, 2

    min_x, min_y = canvas_w, canvas_h
    max_x, max_y = 0, 0
    has_any = False
    min_dim = min(canvas_w, canvas_h)

    for key, cfg in enabled_indicators.items():
        lx = cfg.get("x", 0.0)
        ly = cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        rot = int(cfg.get("rotation", 0)) % 360

        form = cfg.get("form", "text")
        if form == "gauge":
            sz = cfg.get("size", 0.1)
            size_px = int(round(sz * min_dim)) if sz <= 1.0 else int(round((sz / 100.0) * min_dim))
            radius = int(size_px * 1.35)
            x1, y1 = px - radius, py - radius
            x2, y2 = px + radius, py + radius
        elif form in ("bar", "segment_bar"):
            sz = cfg.get("size", 0.2)
            size_px = int(round(sz * canvas_w)) if sz <= 1.0 else int(round((sz / 100.0) * canvas_w))
            if str(cfg.get("bar_style", "")).strip().lower() in ("slope", "grade", "vertical_slope"):
                # Slope is a vertical bar/ruler with a taller local raster.
                # Keep this estimate deliberately generous for labels/ticks;
                # ordinary ruler and segment geometry remains unchanged.
                bar_w = max(180, int(size_px * 0.30)) + 80
                bar_h = size_px + 100
            else:
                bar_w = size_px + 80
                bar_h = max(60, int(size_px * 0.35)) + 50
            if rot in (90, 270):
                w_bar, h_bar = bar_h, bar_w
            else:
                w_bar, h_bar = bar_w, bar_h
            x1 = px - w_bar // 2 - 30
            y1 = py - h_bar // 2 - 30
            x2 = px + w_bar // 2 + 30
            y2 = py + h_bar // 2 + 30
        elif form in ("moving_map", "static_map", "map"):
            # Map renderers produce a square tile (the configured ``size`` is
            # its side), unlike charts whose height is intentionally shorter.
            # The old shared estimate used the chart aspect ratio and left the
            # lower part of the map outside the packed source region.
            sz = cfg.get("size", cfg.get("w", 0.3))
            size_px = int(round(sz * canvas_w)) if sz <= 1.0 else int(round((sz / 100.0) * canvas_w))
            cw = size_px + 60
            ch = size_px + 60
            x1 = px - cw // 2 - 20
            y1 = py - ch // 2 - 20
            x2, y2 = x1 + cw, y1 + ch
        elif form == "chart":
            cw = cfg.get("w", 0.35)
            ch = cfg.get("h", 0.25)
            w_px = int(round(cw * canvas_w)) if cw <= 1.0 else int(round((cw / 100.0) * canvas_w))
            h_px = int(round(ch * canvas_h)) if ch <= 1.0 else int(round((ch / 100.0) * canvas_h))
            w_px = max(w_px, int(canvas_w * 0.25))
            h_px = max(h_px, int(canvas_h * 0.20))
            x1, y1 = px - 40, py - 40
            x2, y2 = px + w_px + 60, py + h_px + 60
        elif key in ("time_block", "time_display") or "time" in key:
            x1, y1 = px - 40, py - 40
            x2, y2 = px + int(canvas_w * 0.25) + 40, py + int(canvas_h * 0.15) + 40
        else:
            # text indicator
            fs_val = cfg.get("font_size", cfg.get("size", 0.02))
            fs = max(10, int(round(fs_val * min_dim)) if fs_val <= 1.0 else int(round((fs_val / 100.0) * min_dim)))
            text_w = max(int(canvas_w * 0.20), fs * 16)
            text_h = max(int(canvas_h * 0.08), fs * 3)
            x1 = px - 40
            y1 = py - 40
            x2 = px + text_w + 40
            y2 = py + text_h + 40

        min_x = min(min_x, max(0, x1))
        min_y = min(min_y, max(0, y1))
        max_x = max(max_x, min(canvas_w, x2))
        max_y = max(max_y, min(canvas_h, y2))
        has_any = True

    for ct_cfg in custom_texts:
        lx = ct_cfg.get("x", 0.0)
        ly = ct_cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        min_x = min(min_x, max(0, px - 40))
        min_y = min(min_y, max(0, py - 40))
        max_x = max(max_x, min(canvas_w, px + int(canvas_w * 0.35) + 40))
        max_y = max(max_y, min(canvas_h, py + int(canvas_h * 0.15) + 40))
        has_any = True

    if not has_any:
        return 0, 0, 2, 2

    # Round to even coordinates and dimensions
    min_x = max(0, min_x)
    min_y = max(0, min_y)
    max_x = min(canvas_w, max_x)
    max_y = min(canvas_h, max_y)

    if min_x % 2 != 0:
        min_x -= 1
    if min_y % 2 != 0:
        min_y -= 1
    w = max_x - min_x
    h = max_y - min_y
    if w % 2 != 0:
        w += 1
    if h % 2 != 0:
        h += 1
    w = min(w, canvas_w - min_x)
    h = min(h, canvas_h - min_y)
    if w % 2 != 0:
        w -= 1
    if h % 2 != 0:
        h -= 1
    return min_x, min_y, max(2, w), max(2, h)

def _numeric_sample_values(samples: Any) -> list[float]:
    values: list[float] = []
    for sample in samples or []:
        raw = sample[1] if isinstance(sample, (tuple, list)) and len(sample) >= 2 else sample
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            values.append(float(raw))
    return values


def build_text_bbox_context(
    layout: dict[str, Any],
    *,
    fit_data: dict[str, list] | None = None,
    speed_samples: list | None = None,
    track_samples: list | None = None,
    alt_samples: list | None = None,
    iso_samples: list | None = None,
    exposure_samples: list | None = None,
    temperature_samples: list | None = None,
    gpx_speed_samples: list | None = None,
    gpx_track_samples: list | None = None,
    gpx_alt_samples: list | None = None,
    gpx_power_samples: list | None = None,
    gpx_atemp_samples: list | None = None,
    gpx_hr_samples: list | None = None,
    gpx_cad_samples: list | None = None,
) -> dict[str, Any]:
    """Build one-shot text geometry candidates from the selected source data.

    This is deliberately a planning helper: it does not change telemetry
    resolution or presentation semantics.  Values are only used to enumerate
    the maximum string extents that the existing text renderer must support.
    """
    fit = fit_data or {}
    source_samples = {
        "gpmf": {
            "speed": speed_samples, "track": track_samples, "alt": alt_samples,
            "dist": track_samples, "iso": iso_samples, "exposure": exposure_samples,
            "temperature": temperature_samples,
        },
        "gpx": {
            "speed": gpx_speed_samples, "track": gpx_track_samples, "alt": gpx_alt_samples,
            "dist": gpx_track_samples, "power": gpx_power_samples, "atemp": gpx_atemp_samples,
            "hr": gpx_hr_samples, "cad": gpx_cad_samples,
        },
    }
    fit_aliases = {
        "power": ("power", "curVpower"), "hr": ("hr", "heart_rate"),
        "cad": ("cad", "cadence"), "atemp": ("atemp", "temperature"),
        "battery": ("battery", "battery_soc"),
    }

    def values_for(key: str, cfg: dict[str, Any]) -> list[float]:
        source = str(cfg.get("source", "gpmf")).lower()
        if key.startswith("fit_") and key.endswith("_text"):
            field = key[4:-5]
            names = fit_aliases.get(field, (field,))
            for name in names:
                values = _numeric_sample_values(fit.get(name))
                if values:
                    return values
            return []
        field_map = {
            "speed_text": "speed", "dist_text": "dist", "alt_text": "alt",
            "iso_text": "iso", "exposure_text": "exposure", "temp_text": "temperature",
            "power_text": "power", "atemp_text": "atemp", "hr_text": "hr",
            "cad_text": "cad", "battery_text": "battery",
        }
        field = field_map.get(key)
        if field is None:
            return []
        if source == "fit":
            names = fit_aliases.get(field, (field,))
            for name in names:
                values = _numeric_sample_values(fit.get(name))
                if values:
                    return values
            return []
        return _numeric_sample_values((source_samples.get(source) or {}).get(field))

    unit_hints = {
        "speed": "km/h", "enhanced_speed": "km/h", "distance": "km",
        "altitude": "m", "heart_rate": "BPM", "cadence": "rpm",
        "power": "W", "temperature": "°C",
    }
    candidates: dict[str, dict[str, Any]] = {}
    phantom_keys: set[str] = set()
    for key, cfg in layout.get("indicators", {}).items():
        if not isinstance(cfg, dict) or not cfg.get("enabled", True):
            continue
        form = cfg.get("form", "text")
        if form != "text":
            continue
        values = values_for(key, cfg)
        if key.startswith("fit_") and key.endswith("_text") and not values:
            phantom_keys.add(key)
        if key in {"iso_text", "exposure_text", "temp_text", "speed_text", "dist_text", "alt_text",
                   "power_text", "atemp_text", "hr_text", "cad_text", "battery_text"} and not values:
            source = str(cfg.get("source", "gpmf")).lower()
            if source in {"fit", "gpx", "gpmf"}:
                phantom_keys.add(key)

        field = key[4:-5] if key.startswith("fit_") and key.endswith("_text") else key
        decimals_default = 0 if key in {"iso_text", "exposure_text", "temp_text", "atemp_text", "power_text", "hr_text", "cad_text", "battery_text"} or key.startswith("fit_") else 1
        decimals = int(cfg.get("decimals", decimals_default))
        numbers = list(values)
        if "min_val" in cfg:
            try:
                numbers.extend((float(cfg["min_val"]), float(cfg["max_val"])))
            except (TypeError, ValueError):
                pass
        if numbers:
            numbers.extend((min(numbers), max(numbers), 0.0))
        formatted: set[str] = set()
        for value in numbers:
            if key == "exposure_text":
                value_text = f"1/{int(value)}" if value and int(value) > 0 else ""
            else:
                value_text = f"{value:.{decimals}f}"
            if cfg.get("show_units", True):
                unit = cfg.get("unit") or unit_hints.get(field, "")
                if key in {"temp_text", "atemp_text"}:
                    value_text = f"{value_text}°C"
                elif key == "power_text":
                    value_text = f"{value_text}W"
                elif key == "hr_text":
                    value_text = f"{value_text} BPM"
                elif key == "cad_text":
                    value_text = f"{value_text} RPM"
                elif key == "battery_text":
                    value_text = f"{value_text}%"
                elif key != "iso_text" and unit:
                    value_text = f"{value_text} {unit}"
            formatted.add(value_text)
        if not formatted:
            formatted.add("")
        candidates[key] = {"formatted_values": sorted(formatted), "phantom": key in phantom_keys}
    return {"text_candidates": candidates, "phantom_keys": phantom_keys}


def _precise_text_box(
    layout: dict[str, Any], key: str, cfg: dict[str, Any], canvas_w: int, canvas_h: int,
    text_candidates: dict[str, Any] | None, font_path: str,
) -> tuple[int, int, int, int] | None:
    """Measure candidate strings with the existing renderer, once per plan."""
    if key == "time_block":
        from src.indicators.time_block import render_time_block
        images = []
        for date_text in ("0000-00-00", "8888-88-88", "9999-99-99"):
            for time_text in ("00:00:00", "88:88:88", "99:99:99"):
                image, _, _ = render_time_block(canvas_w, canvas_h, layout, font_path, date_text, time_text)
                if image is not None:
                    images.append(image)
        if not images:
            return None
        width, height = max(i.width for i in images), max(i.height for i in images)
        rotation = int(cfg.get("rotation", 0)) % 360
        if rotation in (90, 270):
            width, height = height, width
        px = int(round((cfg.get("x", 0.0) / 100.0) * canvas_w)) if cfg.get("x", 0.0) <= 100.0 else int(round(cfg.get("x", 0.0)))
        py = int(round((cfg.get("y", 0.0) / 100.0) * canvas_h)) if cfg.get("y", 0.0) <= 100.0 else int(round(cfg.get("y", 0.0)))
        margin = 2
        return max(0, px - margin), max(0, py - margin), width + 2 * margin, height + 2 * margin

    from src.indicators.dispatcher import render_value_indicator

    candidates = (text_candidates or {}).get(key, {}).get("formatted_values", [""])
    unit = cfg.get("unit", "")
    label = cfg.get("label", key)
    widths: list[int] = []
    heights: list[int] = []
    for formatted in candidates:
        image, _, _, _ = render_value_indicator(
            canvas_w, canvas_h, layout, font_path, key, 0.0, unit, label,
            cfg_override=cfg, formatted_val=formatted, supersample=1,
        )
        if image is not None:
            widths.append(image.width)
            heights.append(image.height)
    if not widths:
        return None
    margin = 2
    px = int(round((cfg.get("x", 0.0) / 100.0) * canvas_w)) if cfg.get("x", 0.0) <= 100.0 else int(round(cfg.get("x", 0.0)))
    py = int(round((cfg.get("y", 0.0) / 100.0) * canvas_h)) if cfg.get("y", 0.0) <= 100.0 else int(round(cfg.get("y", 0.0)))
    rotation = int(cfg.get("rotation", 0)) % 360
    width, height = max(widths), max(heights)
    if rotation in (90, 270):
        width, height = height, width
    return max(0, px - margin), max(0, py - margin), width + 2 * margin, height + 2 * margin


def get_layout_hud_regions(
    layout: dict[str, Any], canvas_w: int, canvas_h: int, max_regions: int = 3, padding: int = 4,
    *, text_candidates: dict[str, Any] | None = None, phantom_keys: set[str] | None = None,
    font_path: str = "",
) -> tuple[int, int, list[tuple[int, int, int, int, int, int]]]:
    """Compute compact multi-region atlas bounds for layout with exact geometry.

    Returns:
        atlas_w, atlas_h, regions
        where regions is a list of (dest_x, dest_y, atlas_x, atlas_y, region_w, region_h)
    """
    import itertools

    indicators = layout.get("indicators", {})
    custom_texts = layout.get("custom_texts", [])
    enabled_indicators = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}

    if not enabled_indicators and not custom_texts:
        return 2, 2, [(0, 0, 0, 0, 2, 2)]

    min_dim = min(canvas_w, canvas_h)
    boxes = []

    for key, cfg in enabled_indicators.items():
        if key in (phantom_keys or set()):
            continue
        lx = cfg.get("x", 0.0)
        ly = cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        rot = int(cfg.get("rotation", 0)) % 360

        form = cfg.get("form", "text")
        if form == "text" and text_candidates is not None:
            precise = _precise_text_box(layout, key, cfg, canvas_w, canvas_h, text_candidates, font_path)
            if precise is None:
                continue
            x1, y1, w_precise, h_precise = precise
            x2, y2 = x1 + w_precise, y1 + h_precise
        elif form == "gauge":
            sz = cfg.get("size", 0.1)
            size_px = int(round(sz * min_dim)) if sz <= 1.0 else int(round((sz / 100.0) * min_dim))
            radius = int(size_px * 1.35)
            x1, y1 = px - radius - 10, py - radius - 10
            x2, y2 = px + radius + 10, py + radius + 10
        elif form in ("bar", "segment_bar"):
            sz = cfg.get("size", 0.2)
            size_px = int(round(sz * canvas_w)) if sz <= 1.0 else int(round((sz / 100.0) * canvas_w))
            if str(cfg.get("bar_style", "")).strip().lower() in ("slope", "grade", "vertical_slope"):
                bar_w = max(180, int(size_px * 0.30)) + 80
                bar_h = size_px + 100
            else:
                bar_w = size_px + 80
                bar_h = max(60, int(size_px * 0.35)) + 50
            if rot in (90, 270):
                w_bar, h_bar = bar_h, bar_w
            else:
                w_bar, h_bar = bar_w, bar_h
            x1 = px - w_bar // 2 - 20
            y1 = py - h_bar // 2 - 20
            x2 = px + w_bar // 2 + 20
            y2 = py + h_bar // 2 + 20
        elif form in ("moving_map", "static_map", "map"):
            # Map renderers produce a square tile (the configured ``size`` is
            # its side), unlike charts whose height is intentionally shorter.
            # Keep the packed source region large enough for the full tile.
            sz = cfg.get("size", cfg.get("w", 0.3))
            size_px = int(round(sz * canvas_w)) if sz <= 1.0 else int(round((sz / 100.0) * canvas_w))
            cw = size_px + 60
            ch = size_px + 60
            x1 = px - cw // 2 - 20
            y1 = py - ch // 2 - 20
            x2, y2 = x1 + cw, y1 + ch
        elif form == "chart":
            sz = cfg.get("size", cfg.get("w", 0.3))
            size_px = int(round(sz * canvas_w)) if sz <= 1.0 else int(round((sz / 100.0) * canvas_w))
            cw = size_px + 60
            ch = max(50, int(size_px * 0.45)) + 50
            x1 = px - cw // 2 - 20
            y1 = py - ch // 2 - 20
            x2 = px + cw // 2 + 20
            y2 = py + ch // 2 + 20
        elif key in ("time_block", "time_display") or "time" in key:
            x1 = px - 20
            y1 = py - 20
            x2 = px + int(canvas_w * 0.20) + 20
            y2 = py + int(canvas_h * 0.12) + 20
        else:
            # text indicator
            fs_val = cfg.get("font_size", cfg.get("size", 0.02))
            fs = max(10, int(round(fs_val * min_dim)) if fs_val <= 1.0 else int(round((fs_val / 100.0) * min_dim)))
            text_w = max(int(canvas_w * 0.12), fs * 12)
            text_h = max(int(canvas_h * 0.06), fs * 3 + 20)
            x1 = px - 20
            y1 = py - 20
            x2 = px + text_w + 20
            y2 = py + text_h + 20

        boxes.append([max(0, x1), max(0, y1), min(canvas_w, x2), min(canvas_h, y2)])

    for ct_cfg in custom_texts:
        if not ct_cfg.get("enabled", True):
            continue
        lx = ct_cfg.get("x", 0.0)
        ly = ct_cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        boxes.append([max(0, px - 20), max(0, py - 20), min(canvas_w, px + int(canvas_w * 0.30) + 20), min(canvas_h, py + int(canvas_h * 0.10) + 20)])

    if not boxes:
        return 2, 2, [(0, 0, 0, 0, 2, 2)]

    # Hierarchical clustering to at most max_regions
    clusters = [[b[0], b[1], b[2], b[3]] for b in boxes]
    while len(clusters) > max_regions:
        best_pair = None
        best_waste = float("inf")
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                b1, b2 = clusters[i], clusters[j]
                mb = [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]
                ma = (mb[2] - mb[0]) * (mb[3] - mb[1])
                a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
                a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
                waste = ma - (a1 + a2)
                if waste < best_waste:
                    best_waste = waste
                    best_pair = (i, j)

        if best_pair is None:
            break
        i, j = best_pair
        b1, b2 = clusters[i], clusters[j]
        mb = [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]
        clusters.pop(j)
        clusters.pop(i)
        clusters.append(mb)

    # Format even dimensions
    clean_clusters = []
    for c in clusters:
        x1, y1, x2, y2 = c
        if x1 % 2 != 0: x1 -= 1
        if y1 % 2 != 0: y1 -= 1
        w = max(2, x2 - x1)
        h = max(2, y2 - y1)
        if w % 2 != 0: w += 1
        if h % 2 != 0: h += 1
        w = min(canvas_w - x1, w)
        h = min(canvas_h - y1, h)
        clean_clusters.append((x1, y1, w, h))

    best_area = float("inf")
    best_res = None

    for order in itertools.permutations(clean_clusters):
        shelf_x = 0
        shelf_y = 0
        row_h = 0
        max_x = 0
        regions = []
        for c in order:
            x1, y1, w, h = c
            if shelf_x + w > canvas_w and shelf_x > 0:
                shelf_x = 0
                shelf_y += row_h + padding
                if shelf_y % 2 != 0: shelf_y += 1
                row_h = 0
            regions.append((x1, y1, shelf_x, shelf_y, w, h))
            shelf_x += w + padding
            if shelf_x % 2 != 0: shelf_x += 1
            row_h = max(row_h, h)
            max_x = max(max_x, shelf_x)
        aw = max_x if max_x % 2 == 0 else max_x + 1
        ah = shelf_y + row_h
        if ah % 2 != 0: ah += 1
        area = aw * ah
        if area < best_area:
            best_area = area
            best_res = (aw, ah, regions)

    return best_res


def _build_stream_ffmpeg_cmd(
    ffmpeg_exe: str,
    input_args: list[str],
    output_file: str,
    canvas_w: int = 1920,
    canvas_h: int = 1080,
    stream_w: int = 1920,
    stream_h: int = 1080,
    generation_fps: float = 30.0,
    encoder: str = "cpu",
    gpu: int = 0,
    video_bitrate: str = "25M",
    render_w: int = 3840,
    render_h: int = 2160,
    resolution_name: str = "4k",
    container_rotation: int = 0,
    rotation_degrees: int = 0,
    hwaccel: str | None = None,
    cut_regions: list[tuple[float, float]] | None = None,
    audio_input_args: list[str] | None = None,
    hud_x: int = 0,
    hud_y: int = 0,
    is_no_hud: bool = False,
    hud_regions: list[tuple[int, int, int, int, int, int]] | None = None,
    overlay_w: int | None = None,
    overlay_h: int | None = None,
    use_gpu_compositor: bool = False,
) -> tuple[list[str], str]:
    if overlay_w is not None:
        canvas_w = overlay_w
        if stream_w == 1920 and overlay_w != 1920:
            stream_w = overlay_w
    if overlay_h is not None:
        canvas_h = overlay_h
        if stream_h == 1080 and overlay_h != 1080:
            stream_h = overlay_h
    """Build the ffmpeg command for the streaming pipeline.

    When *hwaccel* is ``"cuda"`` and no rotation is needed, the GPU
    ``overlay_cuda`` filter is used so that compositing runs on the GPU.
    When manual rotation (90/180/270) is required, the whole chain falls
    back to the CPU (CPU scaling, ``overlay``, CPU rotation filters) so
    that CUDA hardware frames never reach CPU-only filters like
    ``vflip``/``transpose``, which cannot convert them.
    """
    target_res = RESOLUTION_MAP.get(resolution_name)
    nv_rot180_cuda = is_nv_rot180_cuda(encoder, rotation_degrees, container_rotation)
    needs_cpu_rotation = rotation_degrees in (90, 180, 270)
    if nv_rot180_cuda:
        # NVIDIA rotation=180: handled on the CUDA path (HUD canvas rotated in
        # Python), so it is NOT treated as a CPU-rotation case for the NVIDIA branch.
        needs_cpu_rotation = False
    has_cuts = bool(cut_regions and len(cut_regions) > 0)
    effective_rotation = container_rotation if container_rotation != 0 else rotation_degrees

    no_res_change = not target_res or (render_w == canvas_w and render_h == canvas_h)
    if is_no_hud and encoder == "amd" and not needs_cpu_rotation and no_res_change and not has_cuts:
        amf_encoder = "hevc_amf" if _test_encoder("hevc_amf") else "h264_amf"
        cmd = [ffmpeg_exe, "-y", *input_args]
        if audio_input_args:
            cmd.extend(audio_input_args)
        audio_idx = "2" if audio_input_args else "0"
        cmd.extend([
            "-map", "0:v",
            "-map", f"{audio_idx}:a?",
            "-map_metadata", "-1",
            "-metadata:s:v:0", f"rotate={effective_rotation}",
            "-c:v", amf_encoder,
            "-usage", "transcoding",
            "-quality", "speed",
            "-rc", "cbr",
            "-pix_fmt", "nv12",
        ])
        cmd = append_bitrate_args(cmd, encoder, video_bitrate)
        cmd.extend(["-c:a", "copy", output_file])
        return cmd, "direct_gpu_passthrough (zero hwdownload)"

    # ── Base filter (video scaling & format conversion) ───────────────────
    if encoder == "nv" and not needs_cpu_rotation:
        if hwaccel == "cuda":
            if target_res:
                base_filter = f"[0:v]scale_cuda={render_w}:{render_h}:format=yuv420p[base]"
            else:
                base_filter = "[0:v]scale_cuda=format=yuv420p[base]"
        else:
            if target_res:
                base_filter = f"[0:v]hwupload_cuda,scale_cuda={render_w}:{render_h}:format=yuv420p[base]"
            else:
                base_filter = "[0:v]hwupload_cuda,scale_cuda=format=yuv420p[base]"
    elif encoder == "amd" and not needs_cpu_rotation:
        if effective_rotation == 180:
            base_filter = "[0:v]format=nv12,vflip,hflip[base]"
        elif effective_rotation == 90:
            base_filter = "[0:v]format=nv12,transpose=1[base]"
        elif effective_rotation == 270:
            base_filter = "[0:v]format=nv12,transpose=2[base]"
        else:
            base_filter = "[0:v]format=nv12[base]"
    elif target_res:
        if effective_rotation == 180:
            base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos,vflip,hflip[base]"
        elif effective_rotation == 90:
            base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos,transpose=1[base]"
        elif effective_rotation == 270:
            base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos,transpose=2[base]"
        else:
            base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos[base]"
    else:
        if effective_rotation == 180:
            base_filter = "[0:v]vflip,hflip[base]"
        elif effective_rotation == 90:
            base_filter = "[0:v]transpose=1[base]"
        elif effective_rotation == 270:
            base_filter = "[0:v]transpose=2[base]"
        else:
            base_filter = "[0:v]null[base]"

    scale_x = render_w / canvas_w if canvas_w > 0 else 1.0
    scale_y = render_h / canvas_h if canvas_h > 0 else 1.0

    # ── Overlay stream & operator ───────────────────────────────────────
    if encoder == "nv" and not needs_cpu_rotation:
        if hud_regions and len(hud_regions) > 1:
            n_reg = len(hud_regions)
            split_labels = "".join([f"[ov_raw_{i}]" for i in range(n_reg)])
            ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,split={n_reg}{split_labels}"

            crop_ops = []
            overlay_ops = []
            curr_base = "[base]"
            for i, r in enumerate(hud_regions):
                dest_x, dest_y, atlas_x, atlas_y, rw, rh = r
                s_rw = int(round(rw * scale_x))
                s_rh = int(round(rh * scale_y))
                if s_rw % 2 != 0:
                    s_rw += 1
                if s_rh % 2 != 0:
                    s_rh += 1
                if nv_rot180_cuda:
                    eff_dest_x = canvas_w - (dest_x + rw)
                    eff_dest_y = canvas_h - (dest_y + rh)
                else:
                    eff_dest_x = dest_x
                    eff_dest_y = dest_y
                s_dest_x = int(round(eff_dest_x * scale_x))
                s_dest_y = int(round(eff_dest_y * scale_y))

                if scale_x != 1.0 or scale_y != 1.0:
                    crop_ops.append(
                        f"[ov_raw_{i}]crop={rw}:{rh}:{atlas_x}:{atlas_y},scale={s_rw}:{s_rh}:flags=bilinear,format=yuva420p,hwupload_cuda[ov_{i}]"
                    )
                else:
                    crop_ops.append(
                        f"[ov_raw_{i}]crop={rw}:{rh}:{atlas_x}:{atlas_y},format=yuva420p,hwupload_cuda[ov_{i}]"
                    )

                next_base = f"[v_step_{i}]" if i < n_reg - 1 else "[vtemp]"
                overlay_ops.append(
                    f"{curr_base}[ov_{i}]overlay_cuda=x={s_dest_x}:y={s_dest_y}{next_base}"
                )
                curr_base = next_base

            filter_complex = (
                f"{base_filter};{ov_input};" + ";".join(crop_ops) + ";" + ";".join(overlay_ops)
            )
        else:
            scaled_stream_w = int(round(stream_w * scale_x))
            scaled_stream_h = int(round(stream_h * scale_y))
            if scaled_stream_w % 2 != 0:
                scaled_stream_w += 1
            if scaled_stream_h % 2 != 0:
                scaled_stream_h += 1
            if nv_rot180_cuda:
                eff_hud_x = canvas_w - hud_x - stream_w
                eff_hud_y = canvas_h - hud_y - stream_h
            else:
                eff_hud_x = hud_x
                eff_hud_y = hud_y
            scaled_hud_x = int(round(eff_hud_x * scale_x))
            scaled_hud_y = int(round(eff_hud_y * scale_y))

            if scale_x != 1.0 or scale_y != 1.0:
                ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,scale={scaled_stream_w}:{scaled_stream_h}:flags=bilinear,format=yuva420p,hwupload_cuda[ov]"
            else:
                ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba,format=yuva420p,hwupload_cuda[ov]"
            ov_op = f"overlay_cuda=x={scaled_hud_x}:y={scaled_hud_y}"
            filter_complex = f"{base_filter};{ov_input};[base][ov]{ov_op}[vtemp]"
    elif encoder == "amd" and use_gpu_compositor and not needs_cpu_rotation:
        if "-init_hw_device" not in input_args:
            input_args = ["-init_hw_device", "opencl=ocl", "-filter_hw_device", "ocl", *input_args]

        if effective_rotation == 180:
            base_filter = "[0:v]format=nv12,vflip,hflip,hwupload[base]"
        elif effective_rotation == 90:
            base_filter = "[0:v]format=nv12,transpose=1,hwupload[base]"
        elif effective_rotation == 270:
            base_filter = "[0:v]format=nv12,transpose=2,hwupload[base]"
        else:
            base_filter = "[0:v]format=nv12,hwupload[base]"

        if stream_w != render_w or stream_h != render_h:
            ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,scale={render_w}:{render_h}:flags=bilinear,hwupload[ov]"
        else:
            ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba,hwupload[ov]"

        filter_complex = f"{base_filter};{ov_input};[base][ov]overlay_opencl[v_ocl];[v_ocl]hwdownload,format=nv12[vtemp]"
    elif hud_regions and len(hud_regions) > 1:
        n_reg = len(hud_regions)
        split_labels = "".join([f"[ov_raw_{i}]" for i in range(n_reg)])
        ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,split={n_reg}{split_labels}"

        crop_ops = []
        overlay_ops = []
        curr_base = "[base]"
        for i, r in enumerate(hud_regions):
            dest_x, dest_y, src_x, src_y, rw, rh = r
            s_dest_x = int(round(dest_x * scale_x))
            s_dest_y = int(round(dest_y * scale_y))
            s_src_x = src_x
            s_src_y = src_y
            s_rw = int(round(rw * scale_x))
            s_rh = int(round(rh * scale_y))
            if s_rw % 2 != 0: s_rw += 1
            if s_rh % 2 != 0: s_rh += 1

            if scale_x != 1.0 or scale_y != 1.0:
                crop_ops.append(f"[ov_raw_{i}]crop={rw}:{rh}:{src_x}:{src_y},scale={s_rw}:{s_rh}:flags=bilinear[ov_{i}]")
            else:
                crop_ops.append(f"[ov_raw_{i}]crop={rw}:{rh}:{src_x}:{src_y}[ov_{i}]")

            next_base = f"[v_step_{i}]" if i < n_reg - 1 else "[vtemp]"
            overlay_ops.append(
                f"{curr_base}[ov_{i}]overlay={s_dest_x}:{s_dest_y}{':shortest=1' if i == n_reg - 1 else ''}{next_base}"
            )
            curr_base = next_base

        filter_complex = (
            f"{base_filter};{ov_input};" + ";".join(crop_ops) + ";" + ";".join(overlay_ops)
        )
    else:
        s_hud_x = int(round(hud_x * scale_x))
        s_hud_y = int(round(hud_y * scale_y))
        if scale_x != 1.0 or scale_y != 1.0:
            s_stream_w = int(round(stream_w * scale_x))
            s_stream_h = int(round(stream_h * scale_y))
            if s_stream_w % 2 != 0: s_stream_w += 1
            if s_stream_h % 2 != 0: s_stream_h += 1
            ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,scale={s_stream_w}:{s_stream_h}:flags=bilinear[ov]"
        else:
            ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba[ov]"
        ov_op = f"overlay={s_hud_x}:{s_hud_y}:shortest=1"
        filter_complex = f"{base_filter};{ov_input};[base][ov]{ov_op}[vtemp]"

    # ── Cut region drop (select filter) ────────────────────────────────
    has_cuts = bool(cut_regions and len(cut_regions) > 0)
    if has_cuts:
        # Build select/aselect expression: drop frames in cut regions
        parts = []
        for cs, ce in cut_regions:
            parts.append(f"between(t,{cs},{ce})")
        select_expr = "not(" + "+".join(parts) + ")"
        filter_complex += (
            f";[vtemp]select='{select_expr}',setpts=N/FRAME_RATE/TB[vtemp2]"
        )
        # Audio: aselect – tnie ścieżkę audio tak samo jak wideo
        audio_idx = "2" if audio_input_args else "0"
        filter_complex += (
            f";[{audio_idx}:a]aselect='{select_expr}',asetpts=N/SR/TB[aout]"
        )
        print(f"[CUT] select filter: {select_expr}", flush=True)
        v_last = "[vtemp2]"
    else:
        filter_complex += ";[vtemp]null[vtemp2]"
        v_last = "[vtemp2]"

    filter_complex += f";{v_last}null[vout]"

    cmd: list[str] = [
        ffmpeg_exe, "-y",
        *input_args,
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{stream_w}x{stream_h}",
        "-r", str(generation_fps),
        "-i", "pipe:0",
    ]
    if audio_input_args:
        cmd.extend(audio_input_args)
    # NV1: NVIDIA-only filter_complex_threads override.
    # Set TELEM_NV_FILTER_COMPLEX_THREADS=2 or =4 to A/B test.
    # Has NO effect for encoder != "nv".
    _nv_fct_raw = os.environ.get("TELEM_NV_FILTER_COMPLEX_THREADS", "").strip()
    _nv_fct: int | None = None
    if encoder == "nv" and _nv_fct_raw:
        try:
            _nv_fct = int(_nv_fct_raw)
            if _nv_fct < 1:
                _nv_fct = None
        except ValueError:
            _nv_fct = None

    if _nv_fct is not None:
        cmd.extend(["-filter_complex_threads", str(_nv_fct)])
        print(f"[NV1] filter_complex_threads={_nv_fct}", flush=True)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]",
    ])

    if has_cuts:
        # Gdy są cięcia – audio przechodzi przez aselect, potrzebuje re-encoda
        cmd.extend(["-map", "[aout]?"])
    else:
        # Bez cięć – audio kopiowane wprost z pliku
        audio_idx = "2" if audio_input_args else "0"
        cmd.extend(["-map", f"{audio_idx}:a?"])

    # Metadane obrotu: normalnie obrót jest fizycznie zaaplikowany w base_filter,
    # więc w metadanych piszemy rotate=0. W CUDA ROT180 (NVIDIA rotation=180)
    # obraz pozostaje fizycznie nieobrócony (base video + HUD obrócony 180 w
    # Pythonie), a poprawny displaymatrix rotate=180 jest wstrzykiwany do
    # kontenera po zakończeniu (src.ffmpeg.displaymatrix) — tag rotate=180 pełni
    # rolę zapasową.
    out_rotation = 180 if nv_rot180_cuda else 0
    cmd.extend([
        "-map_metadata", "-1", "-metadata:s:v:0", f"rotate={out_rotation}",
    ])

    if encoder == "nv":
        cmd.extend([
            "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
            "-cq", "24",
            "-pix_fmt", "cuda" if (hwaccel == "cuda" and not needs_cpu_rotation) else "yuv420p",
            "-gpu", str(gpu),
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])
    elif encoder == "amd":
        amf_encoder = "hevc_amf" if _test_encoder("hevc_amf") else "h264_amf"
        cmd.extend([
            "-c:v", amf_encoder, "-usage", "transcoding", "-quality", "speed",
            "-rc", "cbr", "-pix_fmt", "nv12",
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])
    elif encoder == "intel":
        cmd.extend([
            "-c:v", "hevc_qsv", "-preset", "veryfast",
            "-global_quality", "24", "-look_ahead", "0",
            "-async_depth", "4", "-pix_fmt", "nv12",
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])
    else:
        cmd.extend([
            "-c:v", "libx265", "-preset", "medium", "-crf", "24",
            "-pix_fmt", "yuv420p",
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])

    cmd = append_bitrate_args(cmd, encoder, video_bitrate)
    cmd.append(str(output_file))
    cmd.extend(["-progress", "pipe:1", "-nostats", "-loglevel", "error"])
    return cmd, filter_complex
