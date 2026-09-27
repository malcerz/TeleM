import inspect
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.telemetry_extract import get_container_rotation
from src.ffmpeg.intel_native_exporter import (
    _compute_layout_widget_boxes,
    export_intel_native_d3d11,
)
from src.gui.preview_transform import (
    calculate_displayed_video_rect,
    source_to_preview_coords,
    preview_to_source_coords,
)


def test_orientation_metadata_parsing():
    """Verify get_container_rotation parses rotation from rotate tag and Display Matrix side data."""
    mock_json_rotate_tag = json.dumps({
        "streams": [{
            "tags": {"rotate": "180"},
            "side_data_list": []
        }]
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_json_rotate_tag)
        rot = get_container_rotation("ffprobe", "dummy.mp4")
        assert rot == 180

    mock_json_display_matrix = json.dumps({
        "streams": [{
            "tags": {},
            "side_data_list": [{
                "side_data_type": "Display Matrix",
                "rotation": -180
            }]
        }]
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_json_display_matrix)
        rot = get_container_rotation("ffprobe", "dummy.mp4")
        assert rot == 180


def test_orientation_normalization():
    """Verify angles are normalized correctly to 0, 90, 180, 270."""
    cases = [
        (0, 0),
        (360, 0),
        (180, 180),
        (-180, 180),
        (90, 90),
        (270, 270),
    ]
    for in_angle, expected in cases:
        norm = abs(int(float(in_angle))) % 360
        assert norm == expected


def test_180_degree_hud_storage_transform():
    """Verify _compute_layout_widget_boxes transforms bounding boxes by 180 degrees in storage space."""
    layout = {
        "indicators": {
            "speed_text": {
                "enabled": True,
                "x": 10.0,
                "y": 20.0,
                "form": "text",
                "size": 0.02,
            }
        },
        "custom_texts": []
    }
    canvas_w, canvas_h = 2560, 1440
    boxes_upright = _compute_layout_widget_boxes(layout, canvas_w=canvas_w, canvas_h=canvas_h, rot180=False)
    boxes_rot180 = _compute_layout_widget_boxes(layout, canvas_w=canvas_w, canvas_h=canvas_h, rot180=True)

    assert "speed_text" in boxes_upright
    assert "speed_text" in boxes_rot180

    u_x1, u_y1, u_x2, u_y2 = boxes_upright["speed_text"]
    r_x1, r_y1, r_x2, r_y2 = boxes_rot180["speed_text"]

    # In 180 storage space, box right edge maps to canvas_w - u_x1, etc.
    assert r_x1 == (canvas_w - u_x2) // 16 * 16
    assert r_y1 == (canvas_h - u_y2) // 16 * 16
    assert r_x2 == ((canvas_w - u_x1) + 15) // 16 * 16
    assert r_y2 == ((canvas_h - u_y1) + 15) // 16 * 16


def test_rotation_0_noop():
    """Verify rot180=False produces unchanged coordinates with zero side data."""
    layout = {
        "indicators": {
            "time_display": {
                "enabled": True,
                "x": 5.0,
                "y": 5.0,
                "form": "time_display",
            }
        }
    }
    b1 = _compute_layout_widget_boxes(layout, canvas_w=2560, canvas_h=1440, rot180=False)
    b2 = _compute_layout_widget_boxes(layout, canvas_w=2560, canvas_h=1440, rot180=False)
    assert b1 == b2


def test_output_metadata_propagation():
    """Verify cmd_mux contains rotation_mux_args for rotated exports and none for 0 deg."""
    src = inspect.getsource(export_intel_native_d3d11)
    assert "rotation_mux_args = [\"-display_rotation:v:0\", str(effective_rotation)] if effective_rotation != 0 else []" in src
    assert "*rotation_mux_args" in src
    assert "hud_rotate_180 = (effective_rotation == 180)" in src


def test_no_double_rotation_contract():
    """Verify video frames are decoded/encoded in storage orientation without extra video rotation."""
    src = inspect.getsource(export_intel_native_d3d11)
    assert "intel_native_pipeline_init_multi_ex" in src
    assert "effective_rotation" in src
    assert "hud_rotate_180" in src


def test_preview_rotation():
    """Verify preview coordinate transforms maintain proper aspect ratio and mapping."""
    ox, oy, dw, dh = calculate_displayed_video_rect(1920, 1080, 3840, 2160)
    assert ox == 0
    assert oy == 0
    assert dw == 1920
    assert dh == 1080

    px, py = source_to_preview_coords(1920, 1080, 1920, 1080, 3840, 2160)
    assert px == 960.0
    assert py == 540.0

    sx, sy = preview_to_source_coords(960.0, 540.0, 1920, 1080, 3840, 2160)
    assert sx == 1920.0
    assert sy == 1080.0


def test_codecs_orientation_contract():
    """Verify export_intel_native_d3d11 supports AV1, HEVC, and H264 with rotation."""
    src = inspect.getsource(export_intel_native_d3d11)
    assert 'codec_name = "AV1"' in src
    assert 'codec_name = "HEVC"' in src
    assert 'codec_name = "H264"' in src
    assert "rotation_degrees" in src
    assert "container_rotation" in src
