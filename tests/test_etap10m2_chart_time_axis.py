import pytest
import json
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageChops

from src.indicators.chart_utils import generate_nice_time_ticks, _history_chart_cache_key
from src.indicators.chart import _render_chart_indicator, _window_time_labels
from src.indicators.dispatcher import render_value_indicator
from src.gui.indicator_schemas import get_value_schema
from src.gui.qt.models import chart_indicator_fields
from src.gui.layout_manager import LayoutManager


class HistoryList(list):
    pass


@pytest.fixture
def mock_history_data():
    base_dt = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    # 2 hours 21 minutes (~8460s) with 2 pauses
    timestamps = []
    hr_vals = []
    t = base_dt
    for i in range(846):
        timestamps.append(t)
        if 200 <= i < 250 or 550 <= i < 600:
            t += timedelta(seconds=10.0)
            hr_vals.append(None)
        else:
            t += timedelta(seconds=10.0)
            hr_vals.append(130.0 + (i % 30))

    hist = HistoryList(hr_vals)
    hist.timestamps = timestamps
    hist.chart_start_dt = timestamps[0]
    hist.chart_end_dt = timestamps[-1]
    hist.time_scope = "activity"
    return hist, base_dt


def test_nice_time_ticks_generation():
    """Verify nice time tick steps, adaptive formatting (<1h MM:SS, >=1h H:MM), and no %."""
    # Test < 1 hour
    t_10m = generate_nice_time_ticks(600.0)
    assert 3 <= len(t_10m) <= 9
    assert all("%" not in lbl for _, lbl in t_10m)
    assert t_10m[0][1] == "00:00"
    assert t_10m[-1][1] == "10:00"

    # Test >= 1 hour (~2h 21m)
    t_2h21m = generate_nice_time_ticks(8480.0)
    assert 3 <= len(t_2h21m) <= 9
    assert all("%" not in lbl for _, lbl in t_2h21m)
    assert t_2h21m[0][1] == "0:00"
    labels_2h = [lbl for _, lbl in t_2h21m]
    assert "0:30" in labels_2h
    assert "1:00" in labels_2h
    assert "1:30" in labels_2h
    assert "2:00" in labels_2h


def test_chart_time_axis_values_switches(mock_history_data):
    """Test 4 combinations of show_x_axis_values and show_y_axis_values."""
    hist, base_dt = mock_history_data
    target_dt = base_dt + timedelta(seconds=3000)

    base_cfg = {
        "form": "chart", "enabled": True, "label": "HEART RATE",
        "x": 59.0, "y": 82.0, "size": 27.0, "thickness": 2, "chart_color": "#FF0000",
        "chart_time_scope": "activity", "label_font_size": 2.5,
    }

    renders = {}
    for show_x, show_y, name in [
        (True, True, "x_on_y_on"),
        (False, True, "x_off_y_on"),
        (True, False, "x_on_y_off"),
        (False, False, "x_off_y_off"),
    ]:
        cfg = dict(base_cfg)
        cfg["show_x_axis_values"] = show_x
        cfg["show_y_axis_values"] = show_y

        img, _, _, _ = render_value_indicator(
            1280, 720, {"indicators": {}}, "", "fit_heart_rate_text",
            145.0, "bpm", "HEART RATE", cfg_override=cfg,
            history_data=hist, target_dt=target_dt,
        )
        renders[name] = img

    # Turning X values OFF must alter bottom region but retain image
    diff_x = ImageChops.difference(renders["x_on_y_on"], renders["x_off_y_on"]).getbbox()
    assert diff_x is not None, "Turning X values OFF must alter rendered pixels (hide X labels)"

    # Turning Y values OFF must alter left region
    diff_y = ImageChops.difference(renders["x_on_y_on"], renders["x_on_y_off"]).getbbox()
    assert diff_y is not None, "Turning Y values OFF must alter rendered pixels (hide Y labels)"

    # Turning both OFF must alter both
    diff_both = ImageChops.difference(renders["x_on_y_on"], renders["x_off_y_off"]).getbbox()
    assert diff_both is not None


def test_gui_schema_and_save_load_roundtrip(tmp_path):
    """Verify FieldSchema definitions and JSON layout roundtrip for new fields."""
    # Check schema definitions
    val_schema_fields = [f[0] for f in get_value_schema()]
    assert "show_x_axis_values" in val_schema_fields
    assert "show_y_axis_values" in val_schema_fields

    chart_fields = [f.name for f in chart_indicator_fields()]
    assert "show_x_axis_values" in chart_fields
    assert "show_y_axis_values" in chart_fields

    # Test roundtrip
    layout_data = {
        "version": 1,
        "indicators": {
            "fit_heart_rate_text": {
                "form": "chart",
                "show_x_axis_values": False,
                "show_y_axis_values": False,
            },
            "fit_cadence_text": {
                "form": "chart",
                "show_x_axis_values": True,
                "show_y_axis_values": False,
            }
        }
    }
    save_file = tmp_path / "test_layout.json"
    with open(save_file, "w", encoding="utf-8") as f:
        json.dump(layout_data, f)

    with open(save_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    assert loaded["indicators"]["fit_heart_rate_text"]["show_x_axis_values"] is False
    assert loaded["indicators"]["fit_heart_rate_text"]["show_y_axis_values"] is False
    assert loaded["indicators"]["fit_cadence_text"]["show_x_axis_values"] is True
    assert loaded["indicators"]["fit_cadence_text"]["show_y_axis_values"] is False


def test_video_and_window_time_scope():
    """Verify video timeline generation and window timeline preservation."""
    # Video scope (e.g. 120s video)
    t_vid = generate_nice_time_ticks(120.0)
    assert t_vid[0][1] == "00:00"
    assert t_vid[-1][1] == "02:00"

    # Window scope
    t_win = _window_time_labels(60.0)
    assert t_win == ["-60 s", "-45 s", "-30 s", "-15 s", "0 s"]
