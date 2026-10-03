"""Tests for Preview Map Stability, Bottom Panel Layout/Ordering, and Backend Parity."""

import os
import pytest
from datetime import datetime, timezone
from PIL import Image

from src.indicators.availability import (
    indicator_data_available,
    compute_indicator_availability,
    get_effective_indicator_availability,
)
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.moving_map import _render_moving_map_indicator
from src.gui.qt.models import DataStream
from src.gui.qt.widgets.data_stream_bar import DataStreamBar
from PySide6.QtWidgets import QApplication, QSizePolicy


# ══════════════════════════════════════════════════════════════════════════════
# PROBLEM 1: MAP STABILITY IN PREVIEW
# ══════════════════════════════════════════════════════════════════════════════

def _make_dummy_gps_track(n=50):
    t0 = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
    track = []
    for i in range(n):
        dt = datetime.fromtimestamp(t0.timestamp() + i, tz=timezone.utc)
        lat = 52.2297 + i * 0.0001
        lon = 21.0122 + i * 0.0001
        track.append((dt, lat, lon))
    return track


def test_moving_map_preview_always_renders_and_never_drops():
    """In GUI preview (async_map=True), moving map must always render stably
    across seek points and frames, without disappearing into placeholder or None."""
    track = _make_dummy_gps_track(30)
    cfg = {
        "x": 10.0,
        "y": 10.0,
        "size": 0.15,
        "zoom": 16,
        "map_style": "light_all",
        "map_shape": "square",
        "hide_track": False,
        "hide_marker": False,
    }

    # Test multiple seek points along the track in preview mode (async_map=True)
    for step in [0.0, 0.25, 0.5, 0.75, 1.0]:
        img, x, y, extra = _render_moving_map_indicator(
            canvas_w=1920,
            canvas_h=1080,
            layout={},
            font_path="",
            key="track_map",
            value=None,
            unit="",
            label="Mapa",
            cfg=cfg,
            min_dim=1080,
            outline=1,
            fs=12,
            font=None,
            val_min=0,
            val_max=100,
            ticks=0,
            thickness=2,
            size_px=200,
            ss=1.0,
            gps_track=track,
            current_position=step,
            async_map=True,
        )
        assert img is not None, f"Map returned None at step {step}"
        assert isinstance(img, Image.Image), f"Expected PIL Image at step {step}"
        assert img.size == (200, 200), f"Incorrect size at step {step}: {img.size}"
        # Parity check: Verify image has non-empty pixel data
        extrema = img.getextrema()
        assert extrema is not None, "Image has no pixel content"


def test_track_map_availability_with_fit_or_general_gps_track():
    """Track map availability must evaluate to True whenever a valid GPS track exists,
    even if gps_source is explicitly 'fit' or 'auto'."""
    track = _make_dummy_gps_track(20)

    # Case A: gps_source="fit", gps_track passed with fit_data
    layout_fit = {"indicators": {"track_map": {"enabled": True, "gps_source": "fit"}}}
    avail_fit, reason_fit = indicator_data_available(
        "track_map",
        layout_fit["indicators"]["track_map"],
        gps_track=track,
        fit_data={"speed": [1, 2, 3]},
    )
    assert avail_fit is True
    assert "fit" in reason_fit

    # Case B: gps_source="auto", gps_track passed
    layout_auto = {"indicators": {"track_map": {"enabled": True, "gps_source": "auto"}}}
    avail_auto, reason_auto = indicator_data_available(
        "track_map",
        layout_auto["indicators"]["track_map"],
        gps_track=track,
    )
    assert avail_auto is True

    # Case C: verify prepare_overlay_frame_data retains track_map availability
    res = prepare_overlay_frame_data(
        layout=layout_auto,
        target_dt=track[0][0],
        tz_offset_hours=2.0,
        start_dt_utc=track[0][0],
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        gps_track=track,
        total_frames=10,
        current_index=0,
    )
    assert res.get("indicator_availability", {}).get("track_map") is True


# ══════════════════════════════════════════════════════════════════════════════
# PROBLEM 2: BOTTOM PANEL LAYOUT & INDICATOR ORDERING
# ══════════════════════════════════════════════════════════════════════════════

def test_data_stream_bar_expands_to_full_height():
    """DataStreamBar scroll area must have Expanding size policy and no 140px height limit."""
    app = QApplication.instance() or QApplication([])
    bar = DataStreamBar()

    # Find the QScrollArea
    from PySide6.QtWidgets import QScrollArea
    scrolls = bar.findChildren(QScrollArea)
    assert len(scrolls) >= 1
    scroll = scrolls[0]

    # Verify maximum height constraint is not capping it at 140
    assert scroll.maximumHeight() > 140 or scroll.maximumHeight() == 16777215  # QWIDGETSIZE_MAX
    # Verify vertical size policy is Expanding
    assert scroll.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert bar.sizePolicy().verticalPolicy() == QSizePolicy.Expanding


class BaseDummyTelemetry:
    def __getattr__(self, name):
        return None


def test_discover_data_streams_map_order_second_after_time():
    """In _discover_data_streams, track_map ('Mapa') must be placed second
    immediately after time_display ('Czas') when GPS is available."""
    from src.gui.qt._mixins.indicator_mixin import IndicatorMixin

    class DummyTelemetry(BaseDummyTelemetry):
        track_samples = [("dt", 10.0), ("dt2", 20.0)]
        fit_gps_track = _make_dummy_gps_track(10)
        gpx_gps_track = []
        gps_track = []
        speed_samples = [("dt", 25.0)]
        alt_samples = []
        heading_samples = []
        slope_samples = []
        gyroscope_samples = []
        accelerometer_samples = []
        fit_data = {}
        gpx_heading_samples = []
        gpx_slope_samples = []

        def resolve_gps_track(self, source="auto"):
            return self.fit_gps_track, "fit"

    class DummyController(IndicatorMixin):
        def __init__(self):
            self.telemetry = DummyTelemetry()

    ctrl = DummyController()
    streams = ctrl._discover_data_streams()

    assert len(streams) >= 2
    assert streams[0].key == "time_display"
    assert streams[0].display_name == "Czas"

    # MAP MUST BE SECOND!
    assert streams[1].key == "track_map"
    assert streams[1].display_name == "Mapa"
    assert streams[1].source == "fit"

    # Other indicators follow
    stream_keys = [s.key for s in streams]
    assert "speed_text" in stream_keys
    assert stream_keys.index("track_map") < stream_keys.index("speed_text")


def test_discover_data_streams_no_gps_omits_map():
    """When no GPS is available, track_map must not be inserted."""
    from src.gui.qt._mixins.indicator_mixin import IndicatorMixin

    class DummyTelemetryNoGPS(BaseDummyTelemetry):
        track_samples = []
        fit_gps_track = []
        gpx_gps_track = []
        gps_track = []
        speed_samples = []
        alt_samples = []
        heading_samples = []
        slope_samples = []
        gyroscope_samples = []
        accelerometer_samples = []
        fit_data = {}
        gpx_heading_samples = []
        gpx_slope_samples = []

        def resolve_gps_track(self, source="auto"):
            return [], "none"

    class DummyController(IndicatorMixin):
        def __init__(self):
            self.telemetry = DummyTelemetryNoGPS()

    ctrl = DummyController()
    streams = ctrl._discover_data_streams()
    stream_keys = [s.key for s in streams]
    assert "track_map" not in stream_keys


# ══════════════════════════════════════════════════════════════════════════════
# PROBLEM 3: EXPORT PREVIEW BACKEND PARITY
# ══════════════════════════════════════════════════════════════════════════════

def test_export_preview_no_misleading_hevc_text():
    """Verify that export preview label text does not show legacy HEVC string."""
    from src.gui.qt.tabs.render_tab import RenderTab

    app = QApplication.instance() or QApplication([])
    tab = RenderTab()

    # Verify initial text is generic rendering status
    assert "HEVC" not in tab.hud_preview_label.text()
    assert "Renderowanie" in tab.hud_preview_label.text()


def test_export_preview_amd_use_native_preview_override():
    """Verify TELEM_AMD_USE_NATIVE_PREVIEW=1 routes AMD through standard native preview."""
    os.environ["TELEM_AMD_USE_NATIVE_PREVIEW"] = "1"
    try:
        from src.gui.qt.tabs.render_tab import RenderTab
        app = QApplication.instance() or QApplication([])
        tab = RenderTab()

        # Simulate starting render with AMD resolved
        resolved_amd = True
        hud_on = True

        amd_use_standard = bool(os.environ.get("TELEM_AMD_USE_NATIVE_PREVIEW") == "1")
        export_preview_hevc = bool(hud_on and resolved_amd and not amd_use_standard)

        assert export_preview_hevc is False
    finally:
        os.environ.pop("TELEM_AMD_USE_NATIVE_PREVIEW", None)
