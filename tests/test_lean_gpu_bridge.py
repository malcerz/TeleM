import ctypes
import os
import pytest
from PIL import Image

from src.indicators.lean import (
    _render_lean_indicator,
    get_lean_gpu_transform_info,
    _load_lean_rotation_source,
)


def test_lean_gpu_transform_info_geometry():
    layout = {"font_path": "assets/fonts/Roboto-Bold.ttf"}
    cfg = {
        "x": 0.5,
        "y": 0.5,
        "size": 120,
        "show_label": True,
        "show_value": True,
        "title_text": "LEAN",
        "pivot_x": 0.5,
        "pivot_y": 1.0,
    }
    info = get_lean_gpu_transform_info(
        canvas_w=3840,
        canvas_h=2160,
        layout=layout,
        key="lean_indicator",
        value=15.0,
        cfg=cfg,
        min_dim=2160,
        fs=24,
        outline=2,
        thickness=4,
        size_px=120,
        ss=1,
    )
    assert info is not None
    angle, graphic, piv_x, piv_y, scr_piv_x, scr_piv_y, dst_x, dst_y, tw, th = info
    assert angle == 15.0
    assert isinstance(graphic, Image.Image)
    assert piv_x == pytest.approx(graphic.width / 2.0, abs=1.0)
    assert piv_y == pytest.approx(graphic.height, abs=1.0)
    assert tw > 0
    assert th > 0
    assert dst_x > 0
    assert dst_y > 0


def test_lean_skip_dynamic_graphic_rendering():
    layout = {"font_path": "assets/fonts/Roboto-Bold.ttf"}
    cfg_normal = {
        "x": 0.5,
        "y": 0.5,
        "size": 120,
        "show_label": True,
        "show_value": True,
        "title_text": "LEAN",
    }
    cfg_skip = dict(cfg_normal)
    cfg_skip["_skip_dynamic_graphic"] = True

    img_normal, _, _, _ = _render_lean_indicator(
        canvas_w=3840, canvas_h=2160, layout=layout, font_path="assets/fonts/Roboto-Bold.ttf",
        key="lean_indicator", value=15.0, unit="°", label="LEAN",
        cfg=cfg_normal, min_dim=2160, outline=2, fs=24, font=None,
        val_min=-30.0, val_max=30.0, ticks=5, thickness=4, size_px=120, ss=1
    )

    img_skip, _, _, _ = _render_lean_indicator(
        canvas_w=3840, canvas_h=2160, layout=layout, font_path="assets/fonts/Roboto-Bold.ttf",
        key="lean_indicator", value=15.0, unit="°", label="LEAN",
        cfg=cfg_skip, min_dim=2160, outline=2, fs=24, font=None,
        val_min=-30.0, val_max=30.0, ticks=5, thickness=4, size_px=120, ss=1
    )

    assert img_normal.size == img_skip.size
    # img_skip should have fewer non-zero alpha pixels because bike icon is omitted
    a_norm = list(img_normal.getchannel("A").getdata())
    a_skip = list(img_skip.getchannel("A").getdata())
    count_norm = sum(1 for p in a_norm if p > 0)
    count_skip = sum(1 for p in a_skip if p > 0)
    assert count_skip < count_norm
    assert count_skip > 0  # title and text and ruler still drawn


def test_native_dll_lean_exports():
    dll_path = os.path.abspath("native/d3d11_amf_pipeline/bin/telem_amd_native.dll")
    if not os.path.exists(dll_path):
        pytest.skip("Native DLL not found at expected path")

    if os.path.isdir(r"C:\tools\mingw64\bin"):
        try:
            os.add_dll_directory(r"C:\tools\mingw64\bin")
        except Exception:
            pass

    dll = ctypes.CDLL(dll_path)
    assert hasattr(dll, "telem_amd_set_lean_gpu_mode")
    assert hasattr(dll, "telem_amd_update_lean_static_texture")
    assert hasattr(dll, "telem_amd_set_lean_transform")
    assert hasattr(dll, "telem_amd_get_lean_stats")
