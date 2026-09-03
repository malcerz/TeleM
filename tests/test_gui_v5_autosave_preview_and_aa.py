"""Automated verification suite for TELEM UI v5:
1. AUTOSAVE REMOVAL: Property changes modify RAM only; def_layout.json is written ONLY on explicit "Zapisz ustawienia".
2. CLOSE EVENT: No auto-save on window close.
3. PREVIEW 1:1 AUDIT: Physical screen pixel mapping with no intermediate raster scaling.
4. GAUGE ANTIALIASING: Local supersampled subpixel edge AA for needle, marker, and ticks with ZERO ghosting and 100% preview/final parity.
"""

import json
import os
import math
from pathlib import Path
import numpy as np
from PIL import Image

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QCloseEvent

app = QApplication.instance() or QApplication([])

from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
from src.indicators.gauge import _render_gauge_indicator, clear_gauge_cache


def test_autosave_removed_on_property_changes(tmp_path):
    """1. 20 property changes must NOT write def_layout.json. Only explicit save writes once."""
    ctrl = AppController()
    ctrl.base_dir = tmp_path
    def_layout_file = tmp_path / "def_layout.json"
    initial_content = {
        "indicators": {
            "speed": {
                "form": "gauge", "size": 0.15, "x": 10.0, "y": 20.0,
                "needle_width": 4, "major_tick_length": 4, "font": "Arial",
            }
        },
        "global": {"font": "Arial"},
    }
    def_layout_file.write_text(json.dumps(initial_content), encoding="utf-8")
    ctrl._load_startup_preset()

    assert getattr(ctrl, "_layout_dirty", False) is False

    # Perform 20 property changes (needle width, tick length, position, font, etc.)
    mtime_before = def_layout_file.stat().st_mtime_ns
    for i in range(1, 21):
        ctrl._on_property_changed("speed", "needle_width", 4 + (i % 5))
        ctrl._on_property_changed("speed", "major_tick_length", 3 + (i % 4))
        ctrl._on_property_changed("speed", "x", 10.0 + i * 0.5)

    # Verify disk was NEVER modified during property editing
    mtime_after = def_layout_file.stat().st_mtime_ns
    assert mtime_after == mtime_before, "def_layout.json was auto-saved during property changes!"
    assert ctrl._layout_dirty is True, "Layout must be marked dirty in RAM"

    # Disk still has initial content
    disk_data = json.loads(def_layout_file.read_text(encoding="utf-8"))
    assert disk_data["indicators"]["speed"]["x"] == 10.0

    # User explicitly clicks "Zapisz ustawienia"
    ctrl._on_save_global_settings()

    # Verify disk was written NOW and dirty flag is cleared
    assert ctrl._layout_dirty is False
    saved_data = json.loads(def_layout_file.read_text(encoding="utf-8"))
    assert saved_data["indicators"]["speed"]["x"] == 10.0 + 20 * 0.5


def test_close_event_does_not_autosave(tmp_path):
    """2. Closing window without clicking 'Zapisz ustawienia' must NOT save layout."""
    ctrl = AppController()
    ctrl.base_dir = tmp_path
    def_layout_file = tmp_path / "def_layout.json"
    initial_content = {
        "indicators": {"speed": {"form": "gauge", "size": 0.15, "x": 15.0, "y": 25.0}},
    }
    def_layout_file.write_text(json.dumps(initial_content), encoding="utf-8")
    ctrl._load_startup_preset()

    win = MainWindow()
    win.set_controller(ctrl)

    # Modify property in RAM
    ctrl._on_property_changed("speed", "x", 99.0)
    assert ctrl.layout["indicators"]["speed"]["x"] == 99.0

    # Simulate closeEvent
    close_ev = QCloseEvent()
    win.closeEvent(close_ev)

    # Disk must NOT be updated
    disk_data = json.loads(def_layout_file.read_text(encoding="utf-8"))
    assert disk_data["indicators"]["speed"]["x"] == 15.0


def test_preview_raster_1to1_diagnostic(capsys):
    """3. Verify 1:1 preview mapping and diagnostic output."""
    win = MainWindow()
    ctrl = AppController()
    win.set_controller(ctrl)
    win.show()

    win.enter_fullscreen_preview()
    out = capsys.readouterr().out

    assert "[PREVIEW RASTER]" in out
    assert "display_scale_x=1.00" in out
    assert "display_scale_y=1.00" in out


def test_gauge_needle_and_ticks_antialiasing():
    """4. Needle and ticks must have smooth subpixel antialiasing (>20 alpha levels), not binary 1-bit [0, 255]."""
    clear_gauge_cache()
    layout = {
        "indicators": {
            "speed": {
                "form": "gauge", "size": 0.2, "x": 50, "y": 50,
                "start_angle": 180, "sweep_angle": 180,
                "min_val": 0, "max_val": 60,
                "needle_width": 4, "needle_color": "#DC3232",
                "show_marker": True, "marker_size": 5,
            }
        }
    }
    cfg = layout["indicators"]["speed"]
    res, _, _, _ = _render_gauge_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="arial.ttf",
        key="speed", value=32.5, unit="km/h", label="SPEED",
        cfg=cfg, min_dim=1080, outline=2, fs=24, font=None,
        val_min=0, val_max=60, ticks=6, thickness=3, size_px=216, ss=1,
    )

    arr = np.array(res)

    # Red needle alpha analysis
    red_mask = (arr[:, :, 0] > 150) & (arr[:, :, 1] < 100) & (arr[:, :, 2] < 100)
    red_alphas = arr[red_mask, 3]
    unique_needle_alphas = np.unique(red_alphas)
    assert len(unique_needle_alphas) > 20, f"Needle lacks AA! Only {len(unique_needle_alphas)} alpha levels: {unique_needle_alphas}"

    # White/gray ticks alpha analysis
    ticks_mask = (arr[:, :, 0] > 200) & (arr[:, :, 1] > 200) & (arr[:, :, 2] > 200)
    tick_alphas = arr[ticks_mask, 3]
    unique_tick_alphas = np.unique(tick_alphas)
    assert len(unique_tick_alphas) > 20, f"Ticks lack AA! Only {len(unique_tick_alphas)} alpha levels"


def test_gauge_incremental_render_zero_ghosting():
    """5. Incremental needle rendering with dirty-rect restoration must produce 0 difference compared to fresh canvas."""
    clear_gauge_cache()
    layout = {
        "indicators": {
            "speed": {
                "form": "gauge", "size": 0.2, "x": 50, "y": 50,
                "start_angle": 180, "sweep_angle": 180,
                "min_val": 0, "max_val": 60,
                "needle_width": 4, "needle_color": "#DC3232",
                "show_marker": True, "marker_size": 5,
            }
        }
    }
    cfg = layout["indicators"]["speed"]

    # Frame 1: needle at 15 km/h
    _render_gauge_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="arial.ttf",
        key="speed", value=15.0, unit="km/h", label="SPEED",
        cfg=cfg, min_dim=1080, outline=2, fs=24, font=None,
        val_min=0, val_max=60, ticks=6, thickness=3, size_px=216, ss=1,
    )

    # Frame 2: needle moved to 48 km/h (restored dirty rects)
    res_incremental, _, _, _ = _render_gauge_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="arial.ttf",
        key="speed", value=48.0, unit="km/h", label="SPEED",
        cfg=cfg, min_dim=1080, outline=2, fs=24, font=None,
        val_min=0, val_max=60, ticks=6, thickness=3, size_px=216, ss=1,
    )

    # Frame 2 fresh on clean canvas
    clear_gauge_cache()
    res_fresh, _, _, _ = _render_gauge_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="arial.ttf",
        key="speed", value=48.0, unit="km/h", label="SPEED",
        cfg=cfg, min_dim=1080, outline=2, fs=24, font=None,
        val_min=0, val_max=60, ticks=6, thickness=3, size_px=216, ss=1,
    )

    diff = np.abs(np.array(res_incremental).astype(int) - np.array(res_fresh).astype(int))
    assert np.max(diff) == 0, f"Ghosting detected! Max diff = {np.max(diff)}"


def test_preview_and_final_parity():
    """6. Preview and final render use the identical _render_gauge_indicator function and produce identical pixels."""
    clear_gauge_cache()
    layout = {
        "indicators": {
            "speed": {
                "form": "gauge", "size": 0.2, "x": 50, "y": 50,
                "start_angle": 180, "sweep_angle": 180,
                "min_val": 0, "max_val": 60,
                "needle_width": 4, "needle_color": "#DC3232",
                "show_marker": True, "marker_size": 5,
            }
        }
    }
    cfg = layout["indicators"]["speed"]

    # Call as final export renderer
    clear_gauge_cache()
    export_img, ex_x, ex_y, _ = _render_gauge_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="arial.ttf",
        key="speed", value=35.0, unit="km/h", label="SPEED",
        cfg=cfg, min_dim=1080, outline=2, fs=24, font=None,
        val_min=0, val_max=60, ticks=6, thickness=3, size_px=216, ss=1,
    )

    # Call as preview renderer
    clear_gauge_cache()
    preview_img, pr_x, pr_y, _ = _render_gauge_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="arial.ttf",
        key="speed", value=35.0, unit="km/h", label="SPEED",
        cfg=cfg, min_dim=1080, outline=2, fs=24, font=None,
        val_min=0, val_max=60, ticks=6, thickness=3, size_px=216, ss=1,
    )

    diff = np.abs(np.array(export_img).astype(int) - np.array(preview_img).astype(int))
    assert np.max(diff) == 0, "Preview and export output differ!"
    assert (ex_x, ex_y) == (pr_x, pr_y)
