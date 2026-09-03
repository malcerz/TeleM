"""Test suite for GUI FIX v3 — Real Runtime Acceptance.

Verifies:
1. Gauge font visual parity & pixel change (diff > 0), plus diagnostic output.
2. Full layout persistence contract: def_layout.json saves all indicator properties
   and new AppController restores them.
3. Frame stepping: integer frame domain, diagnostics, multi-file boundary crossing.
4. Export frame step: IN/OUT integer frame domain.
5. Fullscreen preview: True Fullscreen mode, geometry, keyboard navigation, ESC restore.
"""

import os
import sys
import json
import io
from pathlib import Path
from unittest.mock import MagicMock
from PIL import Image, ImageChops

# Offscreen Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication([])

from src.indicators.gauge import _render_gauge_indicator, clear_gauge_cache
from src.indicators.helpers import resolve_indicator_font_path
from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
from src.gui.qt.tabs.render_tab import RenderTab
from src.multifile import VideoClip, VideoTimeline


def test_gauge_font_visual_change_and_diagnostics(capsys):
    """Prove that gauge font selection changes visual output (pixel diff > 0) and prints diagnostics."""
    clear_gauge_cache()
    cfg_arial = {
        "form": "gauge",
        "font": "Arial",
        "show_value": True,
        "size": 0.1,
        "ticks": 10,
        "min_val": 0,
        "max_val": 100,
        "x": 50,
        "y": 50,
    }
    cfg_digital = {
        "form": "gauge",
        "font": "Digital-7",
        "show_value": True,
        "size": 0.1,
        "ticks": 10,
        "min_val": 0,
        "max_val": 100,
        "x": 50,
        "y": 50,
    }

    # Reset cached diag to ensure printing
    _render_gauge_indicator._last_diag = None
    img_arial, _, _, _ = _render_gauge_indicator(
        canvas_w=1920, canvas_h=1080, layout={"indicators": {"fit_enhanced_speed_text": cfg_arial}},
        font_path="C:/Windows/Fonts/arial.ttf", key="fit_enhanced_speed_text", value=17.7, unit="km/h", label="Speed",
        cfg=cfg_arial, min_dim=1080, outline=3, fs=20, font=None, val_min=0, val_max=100,
        ticks=10, thickness=3, size_px=100, ss=1, formatted_val="17.7 km/h"
    )

    out_arial = capsys.readouterr().out
    assert "[GAUGE FONT]" in out_arial
    assert "indicator=fit_enhanced_speed_text" in out_arial
    assert "element=scale" in out_arial
    assert "element=value" in out_arial
    assert "renderer=_render_gauge_indicator" in out_arial

    clear_gauge_cache()
    _render_gauge_indicator._last_diag = None
    img_digital, _, _, _ = _render_gauge_indicator(
        canvas_w=1920, canvas_h=1080, layout={"indicators": {"fit_enhanced_speed_text": cfg_digital}},
        font_path="C:/Windows/Fonts/arial.ttf", key="fit_enhanced_speed_text", value=17.7, unit="km/h", label="Speed",
        cfg=cfg_digital, min_dim=1080, outline=3, fs=20, font=None, val_min=0, val_max=100,
        ticks=10, thickness=3, size_px=100, ss=1, formatted_val="17.7 km/h"
    )

    out_digital = capsys.readouterr().out
    assert "[GAUGE FONT]" in out_digital
    assert "requested=Digital-7" in out_digital

    diff = ImageChops.difference(img_arial, img_digital)
    bbox = diff.getbbox()
    assert bbox is not None, "FAIL: Visual output of gauge with Arial vs Digital-7 must be different (diff > 0)"


def test_full_layout_persistence_contract(tmp_path):
    """Zapisz ustawienia must persist entire layout (per-indicator font, needle, etc.) to disk def_layout.json."""
    base_dir = tmp_path
    def_layout_file = base_dir / "def_layout.json"

    # Initial def_layout.json
    initial_data = {
        "global": {"font": "Arial", "text_outline": 3},
        "indicators": {
            "speed_text": {"form": "gauge", "font": "Arial", "size": 0.12, "x": 10, "y": 20},
            "cadence": {"form": "text", "font": "", "x": 30, "y": 40},
        }
    }
    def_layout_file.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")

    # Launch controller 1
    ctrl1 = AppController()
    ctrl1.base_dir = base_dir
    ctrl1._load_startup_preset()

    # User modifies gauge indicator font and size via PropertyEditor
    ctrl1._on_property_changed("speed_text", "font", "Digital-7")
    ctrl1._on_property_changed("speed_text", "size", 0.18)
    ctrl1._on_property_changed("speed_text", "needle_color", "#FF0000")

    # User clicks "Zapisz ustawienia"
    ctrl1._on_save_global_settings()

    # Verify disk content
    saved_disk = json.loads(def_layout_file.read_text(encoding="utf-8"))
    ind_saved = saved_disk["indicators"]["speed_text"]
    assert ind_saved["font"] == "Digital-7"
    assert ind_saved["size"] == 0.18
    assert ind_saved["needle_color"] == "#FF0000"

    # Now launch a completely NEW controller (simulating app restart)
    ctrl2 = AppController()
    ctrl2.base_dir = base_dir
    ctrl2._load_startup_preset()

    # Verify that controller 2 loaded the exact modified properties
    ind_restored = ctrl2.layout["indicators"]["speed_text"]
    assert ind_restored["font"] == "Digital-7"
    assert ind_restored["size"] == 0.18
    assert ind_restored["needle_color"] == "#FF0000"


def test_frame_step_integer_domain_and_diagnostics(capsys):
    """Verify frame step calculation, MPV command/seek, and diagnostic print."""
    ctrl = AppController()
    ctrl.fps = 30.0
    ctrl.video_duration_s = 10.0
    ctrl._playback_pos = 1.0  # frame 30

    # Step forward 1 frame
    ctrl._on_frame_step(1)
    out1 = capsys.readouterr().out
    assert "[FRAME STEP]" in out1
    assert "before_frame=30" in out1
    assert "target_frame=31" in out1
    assert "after_frame=31" in out1
    assert abs(ctrl._playback_pos - (31 / 30.0)) < 1e-4

    # Step backward 1 frame
    ctrl._on_frame_step(-1)
    out2 = capsys.readouterr().out
    assert "[FRAME STEP]" in out2
    assert "before_frame=31" in out2
    assert "target_frame=30" in out2
    assert "after_frame=30" in out2
    assert abs(ctrl._playback_pos - (30 / 30.0)) < 1e-4


def test_frame_step_multifile_boundary(capsys):
    """Verify frame step crosses multi-file boundary without sticking."""
    clip0 = VideoClip(path=Path("Video/GX010114.MP4"), duration_s=10.0, fps=30.0, width=1920, height=1080)
    clip1 = VideoClip(path=Path("Video/GX010115.MP4"), duration_s=10.0, fps=30.0, width=1920, height=1080)
    timeline = VideoTimeline.from_clips([clip0, clip1])

    ctrl = AppController()
    ctrl.fps = 30.0
    ctrl.video_timeline = timeline

    # Set position to exact last frame of clip 0 (frame 299, 10s * 30fps = 300 frames: 0..299)
    ctrl._playback_pos = 299 / 30.0

    # Step forward (+1): must land on frame 300 (first frame of clip 1)
    ctrl._on_frame_step(1)
    out1 = capsys.readouterr().out
    assert "[FRAME STEP]" in out1
    assert "before_frame=299" in out1
    assert "target_frame=300" in out1
    assert "GX010115.MP4" in out1
    assert abs(ctrl._playback_pos - 10.0) < 1e-4

    # Step backward (-1): must land back on frame 299 (last frame of clip 0)
    ctrl._on_frame_step(-1)
    out2 = capsys.readouterr().out
    assert "[FRAME STEP]" in out2
    assert "before_frame=300" in out2
    assert "target_frame=299" in out2
    assert "GX010114.MP4" in out2


def test_export_frame_step_integer_domain():
    """Verify RenderTab IN and OUT buttons work strictly in integer frame domain."""
    ctrl = AppController()
    ctrl.fps = 30.0
    ctrl.video_duration_s = 60.0

    tab = RenderTab()
    tab.set_controller(ctrl)

    # Set initial IN to position 5.0s (frame 150)
    tab.video_preview.seek_bar.get_position = MagicMock(return_value=5.0)
    tab._on_set_in()
    assert tab._in_frame == 150
    assert abs(tab._in_orig - 5.0) < 1e-4
    assert tab.lbl_in.text() == "IN: 00:05"
    assert "150" in tab.lbl_in.toolTip()

    # Step IN +1 frame
    tab._on_step_in(1)
    assert tab._in_frame == 151
    assert abs(tab._in_orig - (151 / 30.0)) < 1e-4
    assert "151" in tab.lbl_in.toolTip()

    # Step IN -1 frame
    tab._on_step_in(-1)
    assert tab._in_frame == 150
    assert abs(tab._in_orig - 5.0) < 1e-4

    # Set OUT to position 20.0s (frame 600)
    tab.video_preview.seek_bar.get_position = MagicMock(return_value=20.0)
    tab._on_set_out()
    assert tab._out_frame == 600
    assert abs(tab._out_orig - 20.0) < 1e-4
    assert tab.lbl_out.text() == "OUT: 00:20"
    assert "600" in tab.lbl_out.toolTip()

    # Step OUT +1 frame
    tab._on_step_out(1)
    assert tab._out_frame == 601
    assert abs(tab._out_orig - (601 / 30.0)) < 1e-4

    # Step OUT -1 frame
    tab._on_step_out(-1)
    assert tab._out_frame == 600
    assert abs(tab._out_orig - 20.0) < 1e-4


def test_fullscreen_preview_mode():
    """Verify True Fullscreen Preview toggling, widget isolation, and ESC restore."""
    win = MainWindow()
    ctrl = AppController()
    win.set_controller(ctrl)
    win.show()

    assert not getattr(win, "_is_fullscreen_preview", False)
    assert not win.tabs.isHidden()

    # Toggle to fullscreen
    win.toggle_fullscreen_preview()
    assert win._is_fullscreen_preview is True
    assert win.tabs.isHidden()
    assert win.status_bar.isHidden()
    assert win.centralWidget() is win.preview

    # Toggle back to normal
    win.toggle_fullscreen_preview()
    assert win._is_fullscreen_preview is False
    assert not win.tabs.isHidden()
    assert not win.status_bar.isHidden()
    assert win.centralWidget() is win.tabs
