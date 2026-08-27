import math
import pytest
import numpy as np
from PIL import Image

from src.indicators.lean import (
    _render_lean_indicator,
    _load_lean_graphic,
    _graphic_pivot,
    _rotate_paste_params,
    lean_angle,
)

def _render_lean_ref(
    canvas_w: int, canvas_h: int, layout: dict, font_path: str, key: str,
    value: float, unit: str, label: str, cfg: dict, min_dim: int, outline: int,
    fs: int, font, val_min: float, val_max: float, ticks: int, thickness: int,
    size_px: int, ss: int, formatted_val: str | None = None,
):
    # Reference implementation with 2*max(gw, gh) pad rotation
    from src.indicators.helpers import s, load_font, _static_cache_key, _BoundedStaticCache
    from src.indicators.lean import _text_size, _draw_text_bounded, _draw_text_bounded_cached, _rgba, _clamp
    
    ss = max(1, int(ss))
    pad = 8 * ss
    g = max(32 * ss, int(size_px * ss))
    show_label = bool(cfg.get("show_label", True))
    show_value = bool(cfg.get("show_value", True))
    show_reference = bool(cfg.get("show_reference", True))
    show_ticks = bool(cfg.get("show_ticks", True))
    uppercase_title = bool(cfg.get("uppercase_title", True))
    decimals = max(0, int(cfg.get("decimals", 0)))
    max_angle = abs(float(cfg.get("max_angle", 30.0)))
    angle = lean_angle(value, cfg)
    missing = value is None

    title_fs = max(8 * ss, int(round(float(cfg.get("title_font_scale", 1.0)) * fs * ss)))
    value_fs = max(8 * ss, int(round(float(cfg.get("value_font_scale", 0.9)) * fs * ss)))
    title_font = load_font(font_path, title_fs)
    value_font = load_font(font_path, value_fs)
    text_stroke = max(0, int(round(max(1, outline) * ss)))

    raw_title = str(cfg.get("title_text", label or "")).strip()
    title = raw_title.upper() if uppercase_title else raw_title
    value_text = f"{angle:+.{decimals}f}\u00b0" if (show_value and not missing) else ""

    from PIL import ImageDraw
    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    title_h = _text_size(dd, title, title_font, text_stroke)[1] if show_label and title else 0
    value_w = _text_size(dd, value_text, value_font, text_stroke)[0] if value_text else 0
    value_h = _text_size(dd, value_text, value_font, text_stroke)[1] if value_text else 0
    title_gap = 5 * ss if title_h else 0
    value_gap = 4 * ss if value_h else 0

    ref_color = _rgba(cfg.get("track_color", "#FFFFFF"), (255, 255, 255), int(255 * 0.55))
    tick_color = _rgba(cfg.get("tick_color", cfg.get("track_color", "#FFFFFF")),
                       (255, 255, 255), int(255 * 0.35))

    raster_w = max(g + 2 * pad, value_w + 2 * pad, 2 * pad + 40)
    top = pad + title_h + title_gap
    center_y = top + g / 2.0
    raster_h = int(top + g + value_gap + value_h + pad)

    base = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    cx = raster_w / 2.0
    if show_label and title:
        _draw_text_bounded(d, (raster_w / 2, pad), title, font=title_font, fill=(255, 255, 255, 255), stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230), bounds=(raster_w, raster_h), anchor="ma")
    if show_reference:
        d.line((pad, center_y, raster_w - pad, center_y), fill=ref_color, width=max(1, int(round(1.4 * ss))))
    if show_ticks:
        step = 10.0
        tick_range = min(max_angle, 90.0)
        t = -tick_range
        while t <= tick_range + 1e-6:
            frac = _clamp(t / max(1.0, max_angle), -1.0, 1.0)
            x = cx + frac * (g / 2.0 - 4 * ss)
            tl = (4 * ss) if abs(abs(t) - tick_range) < 1e-6 else (3 * ss)
            d.line((x, center_y - tl, x, center_y + tl), fill=tick_color, width=max(1, int(round(1.0 * ss))))
            t += step

    img = base.copy()
    graphic = _load_lean_graphic(cfg, g)
    if graphic is not None:
        gw, gh = graphic.size
        pivot_px, pivot_py = _graphic_pivot(cfg, gw, gh)
        pad_size, paste_x, paste_y, _sx, _sy = _rotate_paste_params(gw, gh, pivot_px, pivot_py, raster_w, center_y)
        pad_img = Image.new("RGBA", (pad_size, pad_size), (0, 0, 0, 0))
        pad_img.alpha_composite(
            graphic,
            (int(round(pad_size / 2.0 - pivot_px)), int(round(pad_size / 2.0 - pivot_py))),
        )
        rotated = pad_img.rotate(
            angle,
            resample=Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC,
        )
        img.alpha_composite(rotated, (int(round(paste_x)), int(round(paste_y))))

    if value_text:
        _draw_text_bounded_cached(
            img, (raster_w / 2, top + g + value_gap), value_text,
            font=value_font, font_path=font_path, fill=(255, 255, 255, 255),
            stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
            bounds=(raster_w, raster_h), anchor="ma",
        )

    return img, s(cfg.get("x", 0.5), canvas_w), s(cfg.get("y", 0.5), canvas_h), None


def _make_args(cfg_overrides=None, value=12.0):
    cfg = {
        "form": "lean", "enabled": True, "source": "gyro", "axis": "x",
        "graphic": "bike", "size": 0.08, "x": 0.5, "y": 0.5,
        "pivot_x": 0.5, "pivot_y": 1.0, "max_angle": 30.0,
    }
    if cfg_overrides:
        cfg.update(cfg_overrides)
    return dict(
        canvas_w=3840, canvas_h=2160, layout={"indicators": {"lean_indicator": cfg}},
        font_path="arial.ttf", key="lean_indicator", value=value, unit="°",
        label="PRZECHYŁ", cfg=cfg, min_dim=2160, outline=3, fs=28,
        font=None, val_min=0.0, val_max=100.0, ticks=0, thickness=2,
        size_px=307, ss=1,
    )


@pytest.mark.parametrize("angle", [-25.0, -14.35, -5.0, 0.0, 5.0, 15.0, 23.65, 28.0])
def test_lean_tight_rotation_exact_parity(angle):
    args = _make_args(value=angle)
    cand_img, cx, cy, _ = _render_lean_indicator(**args)
    ref_img, rx, ry, _ = _render_lean_ref(**args)
    
    assert (cx, cy) == (rx, ry)
    assert cand_img.size == ref_img.size
    
    cand_arr = np.array(cand_img)
    ref_arr = np.array(ref_img)
    diff = np.abs(cand_arr.astype(int) - ref_arr.astype(int))
    max_d = np.max(diff)
    diff_cnt = np.count_nonzero(diff)
    
    assert max_d == 0, f"Angle {angle} had max_diff={max_d}"
    assert diff_cnt == 0, f"Angle {angle} had diff_pixels={diff_cnt}"


@pytest.mark.parametrize("graphic_type", ["bike", "beam"])
@pytest.mark.parametrize("size_px", [80, 200, 307, 450])
def test_lean_different_sizes_and_graphics(graphic_type, size_px):
    args = _make_args(cfg_overrides={"graphic": graphic_type}, value=17.5)
    args["size_px"] = size_px
    cand_img, _, _, _ = _render_lean_indicator(**args)
    ref_img, _, _, _ = _render_lean_ref(**args)
    
    diff = np.abs(np.array(cand_img).astype(int) - np.array(ref_img).astype(int))
    assert np.max(diff) == 0
    assert np.count_nonzero(diff) == 0


@pytest.mark.parametrize("pivot_x, pivot_y", [(0.5, 1.0), (0.5, 0.5), (0.0, 0.0), (0.25, 0.75)])
def test_lean_pivot_exact_parity(pivot_x, pivot_y):
    args = _make_args(cfg_overrides={"pivot_x": pivot_x, "pivot_y": pivot_y}, value=-12.5)
    cand_img, _, _, _ = _render_lean_indicator(**args)
    ref_img, _, _, _ = _render_lean_ref(**args)
    
    diff = np.abs(np.array(cand_img).astype(int) - np.array(ref_img).astype(int))
    assert np.max(diff) == 0
    assert np.count_nonzero(diff) == 0
