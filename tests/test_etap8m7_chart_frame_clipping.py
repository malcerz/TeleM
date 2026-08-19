"""
ETAP 8M.7 Tests: Chart Frame Bottom Clipping & Visual BBox Contract.
"""
import sys, math
from pathlib import Path
import pytest
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout, resolve_font_path
from src.indicators.helpers import s, load_font
from src.indicators.dispatcher import render_value_indicator
from src.indicators.compositor import compose_overlay
from src.indicators.chart import ChartSplit

LAYOUT_PATH = root / "def_layout.json"
FONT_PATH = resolve_font_path("Arial")


def _get_chart_bbox(canvas_w, canvas_h, key, y_pct=None):
    layout = normalize_layout(LAYOUT_PATH, canvas_w, canvas_h)
    cfg = layout["indicators"][key].copy()
    if y_pct is not None:
        cfg["y"] = y_pct
    img, rx, ry, _ = render_value_indicator(
        canvas_w=canvas_w, canvas_h=canvas_h,
        layout=layout, font_path=FONT_PATH,
        key=key, value=95.0, unit="rpm", label="Cadence",
        cfg_override=cfg, history_data=[80.0, 90.0, 95.0, 100.0],
    )
    assert img is not None
    local_w, local_h = img.size
    final_left = int(round(rx - local_w / 2.0))
    final_top = int(round(ry - local_h / 2.0))
    final_right = final_left + local_w
    final_bottom = final_top + local_h
    return {
        "img": img,
        "local_w": local_w,
        "local_h": local_h,
        "final_left": final_left,
        "final_top": final_top,
        "final_right": final_right,
        "final_bottom": final_bottom,
        "rx": rx,
        "ry": ry,
    }


def test_chart_visual_bbox_inside_frame_bottom():
    """Verify that default layout chart visual bboxes are strictly inside the frame bottom."""
    for w, h in [(3840, 2160), (1920, 1080), (1280, 720), (854, 480)]:
        for key in ["fit_cadence_text", "fit_heart_rate_text"]:
            info = _get_chart_bbox(w, h, key)
            assert info["final_bottom"] <= h, f"[{w}x{h}] {key} bottom={info['final_bottom']} > frame height {h}"
            assert info["final_top"] >= 0, f"[{w}x{h}] {key} top={info['final_top']} < 0"


def test_chart_bottom_labels_global_bbox():
    """Verify that X-axis labels (0%..100%) have global text_bottom <= output_height."""
    for w, h in [(3840, 2160), (1920, 1080), (1280, 720), (854, 480)]:
        for key in ["fit_cadence_text", "fit_heart_rate_text"]:
            info = _get_chart_bbox(w, h, key)
            # Check bottom of local image: inside local image, lowest non-transparent pixel is <= local_h
            alpha = info["img"].getchannel("A")
            bbox = alpha.getbbox()
            assert bbox is not None
            # Local lowest pixel
            local_bottom = bbox[3]
            global_bottom = info["final_top"] + local_bottom
            assert global_bottom <= h, f"[{w}x{h}] {key} global_bottom={global_bottom} > frame height {h}"


def test_chart_bottom_edge_no_crop():
    """Verify that even when placed at y=95% near the bottom edge, chart is not clipped."""
    for w, h in [(1280, 720), (854, 480)]:
        for key in ["fit_cadence_text", "fit_heart_rate_text"]:
            info = _get_chart_bbox(w, h, key, y_pct=95.0)
            assert info["final_bottom"] <= h, f"[{w}x{h}] near bottom edge: bottom={info['final_bottom']} > {h}"
            assert info["final_top"] >= 0


def test_chart_static_upload_preserves_bottom_labels():
    """Verify that split_mode ChartSplit static layer includes full labels and fits frame."""
    layout = normalize_layout(LAYOUT_PATH, 1280, 720)
    cfg = layout["indicators"]["fit_cadence_text"]
    split_res, rx, ry, _ = render_value_indicator(
        canvas_w=1280, canvas_h=720,
        layout=layout, font_path=FONT_PATH,
        key="fit_cadence_text", value=95.0, unit="rpm", label="Cadence",
        cfg_override=cfg, history_data=[80.0, 90.0, 95.0, 100.0],
        split_chart_keys={"fit_cadence_text"},
    )
    assert isinstance(split_res, ChartSplit)
    static_img = split_res.static
    local_w, local_h = static_img.size
    final_bottom = int(round(ry - local_h / 2.0)) + local_h
    assert final_bottom <= 720
    # Check that static image has non-transparent pixels in the lower quarter (where X labels reside)
    bottom_crop = static_img.crop((0, int(local_h * 0.75), local_w, local_h))
    assert bottom_crop.getchannel("A").getbbox() is not None


def test_chart_dynamic_global_coordinates():
    """Verify dynamic tile offsets correctly map to global frame inside canvas."""
    layout = normalize_layout(LAYOUT_PATH, 1280, 720)
    cfg = layout["indicators"]["fit_cadence_text"]
    split_res, rx, ry, _ = render_value_indicator(
        canvas_w=1280, canvas_h=720,
        layout=layout, font_path=FONT_PATH,
        key="fit_cadence_text", value=95.0, unit="rpm", label="Cadence",
        cfg_override=cfg, history_data=[80.0, 90.0, 95.0, 100.0],
        split_chart_keys={"fit_cadence_text"},
    )
    assert isinstance(split_res, ChartSplit)
    paste_x = int(round(rx - split_res.width / 2.0))
    paste_y = int(round(ry - split_res.height / 2.0))
    
    if split_res.value_tile:
        vx, vy = split_res.value_local
        vw, vh = split_res.value_tile.size
        assert paste_x + vx >= 0
        assert paste_y + vy >= 0
        assert paste_x + vx + vw <= 1280
        assert paste_y + vy + vh <= 720

    if split_res.cursor_tile:
        cx, cy = split_res.cursor_local
        cw, ch = split_res.cursor_tile.size
        assert paste_x + cx >= 0
        assert paste_y + cy >= 0
        assert paste_x + cx + cw <= 1280
        assert paste_y + cy + ch <= 720


def test_chart_outer_geometry_stable_after_padding():
    """Verify that outer widget size stays stable and does not arbitrarily expand."""
    for w, h in [(3840, 2160), (1920, 1080), (1280, 720), (854, 480)]:
        layout = normalize_layout(LAYOUT_PATH, w, h)
        cfg = layout["indicators"]["fit_cadence_text"]
        info = _get_chart_bbox(w, h, "fit_cadence_text")
        chart_w = s(cfg["size"], w)
        min_dim = min(w, h)
        fs_val = cfg.get("font_size") if "font_size" in cfg else cfg.get("size", 0.02)
        fs = max(8, s(fs_val, min_dim))
        outline_raw = int(layout.get("global", {}).get("text_outline", 3))
        outline = max(0, int(round(outline_raw * min_dim / 1000)))
        expected_h = max(40, int(chart_w * 0.4)) + (fs + 8 + outline) + 4
        expected_w = chart_w + 8
        assert info["local_w"] == expected_w
        assert info["local_h"] == expected_h


def test_chart_edge_geometry_4k():
    """Verify edge geometry bounds at 4K (3840x2160)."""
    for y_val in [1.0, 50.0, 85.36, 95.0, 99.0]:
        info = _get_chart_bbox(3840, 2160, "fit_cadence_text", y_pct=y_val)
        assert info["final_top"] >= 0
        assert info["final_bottom"] <= 2160
        assert info["final_left"] >= 0
        assert info["final_right"] <= 3840


def test_chart_edge_geometry_1080p():
    """Verify edge geometry bounds at 1080p (1920x1080)."""
    for y_val in [1.0, 50.0, 85.36, 95.0, 99.0]:
        info = _get_chart_bbox(1920, 1080, "fit_cadence_text", y_pct=y_val)
        assert info["final_top"] >= 0
        assert info["final_bottom"] <= 1080
        assert info["final_left"] >= 0
        assert info["final_right"] <= 1920


def test_chart_edge_geometry_720p():
    """Verify edge geometry bounds at 720p (1280x720)."""
    for y_val in [1.0, 50.0, 85.36, 95.0, 99.0]:
        info = _get_chart_bbox(1280, 720, "fit_cadence_text", y_pct=y_val)
        assert info["final_top"] >= 0
        assert info["final_bottom"] <= 720
        assert info["final_left"] >= 0
        assert info["final_right"] <= 1280


def test_chart_edge_geometry_480p():
    """Verify edge geometry bounds at 480p (854x480)."""
    for y_val in [1.0, 50.0, 85.36, 95.0, 99.0]:
        info = _get_chart_bbox(854, 480, "fit_cadence_text", y_pct=y_val)
        assert info["final_top"] >= 0
        assert info["final_bottom"] <= 480
        assert info["final_left"] >= 0
        assert info["final_right"] <= 854
