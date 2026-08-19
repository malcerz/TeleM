"""ETAP 8M.3: Regression tests for runtime layout, GPMF indicators, and canvas isolation."""
import json
import pytest
from pathlib import Path
from PIL import Image
import numpy as np
from datetime import datetime, timezone, timedelta

from src.gui.layout_manager import normalize_layout, resolve_font_path
from src.indicators.frame_data import prepare_overlay_frame_data
from src.overlay_renderer import compose_overlay, render_preview
from src.ffmpeg.worker_cache import init_worker, _resolve_cache_samples, _resolve_cache_value, WORKER_CACHE
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts

def test_worker_cache_gpmf_resolution():
    """Verify that _resolve_cache_samples and _resolve_cache_value resolve GPMF camera fields."""
    dt0 = datetime(2026, 8, 18, 4, 46, 25, tzinfo=timezone.utc)
    iso_data = [(dt0 + timedelta(seconds=i), 100 + i * 5) for i in range(10)]
    exp_data = [(dt0 + timedelta(seconds=i), 200 + i * 10) for i in range(10)]
    tmp_data = [(dt0 + timedelta(seconds=i), 30.0 + i * 0.1) for i in range(10)]
    
    init_worker(
        video_width=1280,
        video_height=720,
        font_path="",
        layout={},
        field_samples=None,
        iso_samples=iso_data,
        exposure_samples=exp_data,
        temperature_samples=tmp_data,
        start_dt_utc=dt0,
    )
    
    # Check that _resolve_cache_samples finds the samples directly from WORKER_CACHE
    iso_res = _resolve_cache_samples("iso", "gpmf")
    assert len(iso_res) == 10
    assert iso_res[0][1] == 100
    
    exp_res = _resolve_cache_samples("exposure", "gpmf")
    assert len(exp_res) == 10
    assert exp_res[0][1] == 200
    
    tmp_res = _resolve_cache_samples("temperature", "gpmf")
    assert len(tmp_res) == 10
    assert tmp_res[0][1] == 30.0
    
    # Check interpolated cache values
    val_iso = _resolve_cache_value("iso", "gpmf", dt0 + timedelta(seconds=2.0))
    assert val_iso == 110

def test_canvas_isolation_between_below_and_above_map():
    """Verify that above_full compose_overlay does not clobber below-map indicators."""
    font_path = resolve_font_path("Arial")
    dt0 = datetime(2026, 8, 18, 4, 46, 25, tzinfo=timezone.utc)
    layout = json.load(open("def_layout.json", "r", encoding="utf-8"))
    
    below_layout, above_layout, _ = _ordered_map_layout_parts(layout)
    
    frame_kwargs = {
        "date_text": "2026-08-18",
        "time_text": "06:46:25",
        "speed_value": 25.0,
        "distance_m": 1000.0,
        "max_distance_m": 5000.0,
        "alt_value": 150.0,
        "min_alt": 100.0,
        "max_alt": 200.0,
        "iso_value": 100.0,
        "exposure_value": 250.0,
        "temp_value": 30.0,
        "indicator_values": {},
        "max_speed_kmh": 60.0,
        "power_value": None,
        "atemp_value": None,
        "hr_value": None,
        "cad_value": None,
        "battery_value": None,
        "chart_data": {},
        "current_position": 0.1,
        "extra_indicators": {},
        "gps_track": [],
        "target_dt": dt0,
        "start_dt_utc": dt0,
        "elapsed_seconds": 1.0,
        "avg_speed_kmh": 25.0,
    }
    
    # Step 1: Render below layout
    _bboxes = {}
    composed_img = compose_overlay(
        canvas_w=1280, canvas_h=720,
        layout=below_layout, font_path=font_path,
        _bboxes=_bboxes,
        gpu_capture_keys=set(),
        reuse_canvas=True,
        **frame_kwargs
    )
    
    # Check that time_block has non-zero alpha in composed_img
    crop_before = composed_img.crop((21, 22, 21 + 76, 22 + 46))
    alpha_before = np.count_nonzero(np.asarray(crop_before)[:, :, 3])
    assert alpha_before > 0, "time_block must have non-zero alpha before above_map render"
    
    # Step 2: Render above layout with reuse_canvas=False (as in amd_native_exporter.py)
    above_bboxes = {}
    above_full = compose_overlay(
        canvas_w=1280, canvas_h=720,
        layout=above_layout, font_path=font_path,
        _bboxes=above_bboxes,
        gpu_capture_keys=set(),
        reuse_canvas=False,
        **frame_kwargs
    )
    
    # Check that composed_img STILL has time_block alpha intact!
    crop_after = composed_img.crop((21, 22, 21 + 76, 22 + 46))
    alpha_after = np.count_nonzero(np.asarray(crop_after)[:, :, 3])
    assert alpha_after == alpha_before, f"composed_img must not be modified by above_full: {alpha_after} vs {alpha_before}"

def test_time_block_defensive_outline():
    """Verify render_time_block handles missing global section defensively."""
    from src.indicators.time_block import render_time_block
    font_path = resolve_font_path("Arial")
    layout_no_global = {
        "indicators": {
            "time_block": {
                "enabled": True, "label": "Czas", "x": 1.6, "y": 3.1,
                "font_label": 1.25, "font_date": 2.0, "font_time": 2.0
            }
        }
    }
    tb, x, y = render_time_block(1280, 720, layout_no_global, font_path, "2026-08-18", "06:46:25")
    assert tb is not None
    assert tb.size == (76, 46) or (tb.width > 0 and tb.height > 0)
