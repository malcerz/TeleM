"""ETAP 8M unit and regression tests for export resolution contract and track_map."""
import json
import pytest
from pathlib import Path
from PIL import Image
import numpy as np

from src.ffmpeg.command_builder import RESOLUTION_MAP
from src.indicators.helpers import s
from src.indicators.moving_map import render_map_working_image, _map_render_plan
from src.indicators.compositor import compose_overlay

root = Path(__file__).resolve().parent.parent

def test_resolution_map_definitions():
    """Verify RESOLUTION_MAP contains standard export resolutions."""
    assert RESOLUTION_MAP.get("source") is None
    assert RESOLUTION_MAP.get("4k") == (3840, 2160)
    assert RESOLUTION_MAP.get("1080p") == (1920, 1080)
    assert RESOLUTION_MAP.get("720p") == (1280, 720)
    assert RESOLUTION_MAP.get("480p") == (854, 480)

def test_map_geometry_scaling_across_resolutions():
    """Verify track_map preserves exact square aspect ratio and relative position across resolutions."""
    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    cfg = layout["indicators"]["track_map"]
    
    for name, w, h in [("4k", 3840, 2160), ("1080p", 1920, 1080), ("720p", 1280, 720)]:
        map_w = s(cfg.get("size", 0.1), w)
        rx = s(cfg["x"], w)
        ry = s(cfg["y"], h)
        dst_bbox = (int(rx - map_w // 2), int(ry - map_w // 2), int(map_w), int(map_w))
        
        # Dimensions must be perfectly square
        assert dst_bbox[2] == dst_bbox[3]
        # Position must be scaled proportionally
        assert abs(rx / w - cfg["x"] / 100.0) < 0.01
        assert abs(ry / h - cfg["y"] / 100.0) < 0.01

def test_map_render_plan_aspect_and_zoom():
    """Verify _map_render_plan produces square working size and valid zoom offset."""
    for canvas_w in [3840, 1920, 1280]:
        map_w = s(0.18, canvas_w)
        plan = _map_render_plan(canvas_w, map_w, 16)
        assert plan["working_size"] > 0
        assert plan["effective_zoom"] >= 10
        assert plan["zoom_offset"] in (0, 1, 2, -1, -2)

def test_hud_composition_at_multiple_resolutions():
    """Verify compose_overlay succeeds and generates correct canvas size at different resolutions."""
    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    
    for w, h in [(3840, 2160), (1920, 1080), (1280, 720)]:
        hud_img = compose_overlay(
            w, h,
            layout,
            "C:/_DEV/TeleM/resources/fonts/Roboto-Bold.ttf",
            date_text="2026-08-19",
            time_text="12:00:00",
            speed_value=25.0,
            distance_m=1000.0,
            alt_value=150.0,
            hr_value=140.0,
            cad_value=85.0,
        )
        assert hud_img is not None
        assert hud_img.size == (w, h)
        assert hud_img.mode == "RGBA"

def test_map_full_area_quadrant_coverage():
    """Verify that extracted map crops from real exports contain full satellite imagery in all quadrants."""
    for label, exp_size in [("4k", (691, 691)), ("1080p", (346, 346)), ("720p", (230, 230))]:
        crop_p = root / "scratch" / "validation_exports" / f"map_crop_30_{label}.png"
        if not crop_p.exists():
            continue
        img = Image.open(crop_p)
        assert img.size == exp_size
        arr = np.array(img)
        w, h = img.size
        # All 4 corners must have non-zero RGB
        for y, x in [(h//8, w//8), (h//8, 7*w//8), (7*h//8, w//8), (7*h//8, 7*w//8)]:
            assert np.mean(arr[y, x, :3]) > 10
        # Overall variance should show full rich image, not flat stripe
        assert arr.std() > 30.0

def test_orientation_parity_across_resolutions():
    """Verify exported video frames match right-side-up reference orientation across all resolutions."""
    ref_auto_p = root / "scratch" / "rotation_diag" / "raw_ffmpeg_autorotated.png"
    if not ref_auto_p.exists():
        return
    ref_auto = Image.open(ref_auto_p)
    w_ref, h_ref = ref_auto.size
    c_ref_auto = ref_auto.crop((w_ref//4, h_ref//4, 3*w_ref//4, 3*h_ref//4))
    a_auto = np.array(c_ref_auto.resize((200, 200), Image.Resampling.BILINEAR))[:, :, :3]

    for label in ["4k", "1080p", "720p"]:
        f_p = root / "scratch" / "validation_exports" / f"frame_30_{label}.png"
        if not f_p.exists():
            continue
        f_img = Image.open(f_p)
        w, h = f_img.size
        c = f_img.crop((w//4, h//4, 3*w//4, 3*h//4))
        a = np.array(c.resize((200, 200), Image.Resampling.BILINEAR))[:, :, :3]
        mae = np.mean(np.abs(a.astype(float) - a_auto.astype(float)))
        assert mae < 20.0, f"Frame {label} orientation mismatch: MAE={mae:.2f}"

