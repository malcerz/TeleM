import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
from datetime import timedelta
import numpy as np
import pytest
from PIL import Image

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.indicators.lean import _render_lean_indicator, get_lean_gpu_transform_info

REPO_ROOT = Path(__file__).resolve().parents[1]
VIDEO = REPO_ROOT / "Video" / "GX030120.MP4"
FIT = REPO_ROOT / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = REPO_ROOT / "def_layout.json"
GOLDEN_DIR = REPO_ROOT / "tests" / "golden_parity"
MANIFEST_PATH = GOLDEN_DIR / "golden_manifest_frame150.json"


@pytest.fixture(scope="module")
def frame_150_context():
    tm = TelemetryDataManager()
    processed = read_processed_cache(VIDEO)
    if processed is not None:
        apply_processed_cache(tm, processed)
    else:
        tm.load_gpmf_from_exiftool(VIDEO)
    tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

    layout = json.load(open(LAYOUT_PATH, encoding="utf-8"))
    fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())

    fps = 30000.0 / 1001.0
    frame_idx = 150
    target_dt = tm.start_dt_utc + timedelta(seconds=frame_idx / fps) if tm.start_dt_utc else None

    frame_kwargs = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=2,
        start_dt_utc=tm.start_dt_utc,
        speed_samples=tm.speed_samples,
        track_samples=tm.track_samples,
        alt_samples=tm.alt_samples,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source(
            layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
        ),
        fit_field_plan=fit_field_plan,
    )

    canvas_w, canvas_h = 3840, 2160
    font_path = "arial.ttf"
    ref_bboxes = {}
    ref_tight = {}
    ref_overlay = compose_overlay(
        canvas_w=canvas_w, canvas_h=canvas_h, layout=layout, font_path=font_path,
        _bboxes=ref_bboxes, _tight_bboxes=ref_tight,
        **frame_kwargs
    )
    return {
        "layout": layout,
        "ref_bboxes": ref_bboxes,
        "ref_tight": ref_tight,
        "ref_overlay": ref_overlay,
        "frame_kwargs": frame_kwargs,
        "canvas_w": canvas_w,
        "canvas_h": canvas_h,
        "font_path": font_path,
    }


def test_golden_elements_presence_and_bboxes(frame_150_context):
    assert MANIFEST_PATH.exists(), f"Golden manifest not found at {MANIFEST_PATH}"
    manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    ref_bboxes = frame_150_context["ref_bboxes"]

    required_keys = [
        "track_map",
        "lean_indicator",
        "fit_distance_text",
        "alt_text",
        "speed_text",
        "fit_heart_rate_text",
        "fit_cadence_text",
    ]

    for key in required_keys:
        assert key in manifest, f"Key '{key}' missing from golden manifest"
        assert key in ref_bboxes, f"Key '{key}' missing from rendered overlay bboxes"
        golden_bbox = tuple(manifest[key]["bbox"])
        rendered_bbox = tuple(ref_bboxes[key])
        assert rendered_bbox == golden_bbox, (
            f"BBox for '{key}' changed from golden {golden_bbox} to {rendered_bbox}"
        )


def test_lean_visible_gap_positive(frame_150_context):
    layout = frame_150_context["layout"]
    lean_cfg = layout["indicators"]["lean_indicator"]
    font_path = frame_150_context["font_path"]
    canvas_w = frame_150_context["canvas_w"]
    canvas_h = frame_150_context["canvas_h"]
    min_dim = min(canvas_w, canvas_h)
    outline = max(0, int(round(int(layout.get("global", {}).get("text_outline", 3)) * min_dim / 1000)))
    from src.indicators.helpers import s
    fs_val = lean_cfg.get("font_size") if "font_size" in lean_cfg else lean_cfg.get("size", 0.02)
    fs = max(8, s(fs_val, min_dim))
    size_px = s(lean_cfg.get("size", 0.1), canvas_w)
    val_lean = -9.0

    # Bike only:
    cfg_bike = lean_cfg.copy()
    cfg_bike["show_value"] = False
    img_bike, _, _, _ = _render_lean_indicator(
        canvas_w=canvas_w, canvas_h=canvas_h, layout=layout, font_path=font_path,
        key="lean_indicator", value=val_lean, unit="°", label=lean_cfg.get("label", ""), cfg=cfg_bike,
        min_dim=min_dim, outline=outline, fs=fs, font=None, val_min=-30.0, val_max=30.0,
        ticks=0, thickness=4, size_px=size_px, ss=1
    )
    arr_bike = np.array(img_bike)
    bike_bottom_local = np.where(arr_bike[:, :, 3] > 0)[0].max()

    # Text only:
    cfg_text = lean_cfg.copy()
    cfg_text["_skip_dynamic_graphic"] = True
    img_text, _, _, _ = _render_lean_indicator(
        canvas_w=canvas_w, canvas_h=canvas_h, layout=layout, font_path=font_path,
        key="lean_indicator", value=val_lean, unit="°", label=lean_cfg.get("label", ""), cfg=cfg_text,
        min_dim=min_dim, outline=outline, fs=fs, font=None, val_min=-30.0, val_max=30.0,
        ticks=0, thickness=4, size_px=size_px, ss=1
    )
    arr_text = np.array(img_text)
    text_top_local = np.where((arr_text[:, :, 3] > 0) & (np.arange(img_text.height)[:, None] > 200))[0].min()

    visible_gap = text_top_local - bike_bottom_local
    assert visible_gap >= 5, f"LEAN visible gap must be >= 5px, got {visible_gap}px (overlap detected)"


def test_lean_gpu_pivot_exact_match(frame_150_context):
    layout = frame_150_context["layout"]
    lean_cfg = layout["indicators"]["lean_indicator"]
    font_path = frame_150_context["font_path"]
    canvas_w = frame_150_context["canvas_w"]
    canvas_h = frame_150_context["canvas_h"]
    min_dim = min(canvas_w, canvas_h)
    outline = max(0, int(round(int(layout.get("global", {}).get("text_outline", 3)) * min_dim / 1000)))
    from src.indicators.helpers import s
    fs_val = lean_cfg.get("font_size") if "font_size" in lean_cfg else lean_cfg.get("size", 0.02)
    fs = max(8, s(fs_val, min_dim))
    size_px = s(lean_cfg.get("size", 0.1), canvas_w)
    val_lean = -9.0

    img_ref, rx, ry, _ = _render_lean_indicator(
        canvas_w=canvas_w, canvas_h=canvas_h, layout=layout, font_path=font_path,
        key="lean_indicator", value=val_lean, unit="°", label=lean_cfg.get("label", ""), cfg=lean_cfg,
        min_dim=min_dim, outline=outline, fs=fs, font=None, val_min=-30.0, val_max=30.0,
        ticks=0, thickness=4, size_px=size_px, ss=1
    )

    info = get_lean_gpu_transform_info(
        canvas_w=canvas_w, canvas_h=canvas_h, layout=layout, key="lean_indicator",
        value=val_lean, cfg=lean_cfg, font_path=font_path, label=lean_cfg.get("label", ""),
        min_dim=min_dim, fs=fs, outline=outline, thickness=4, size_px=size_px, ss=1
    )
    assert info is not None
    angle, graphic, piv_x, piv_y, spx, spy, dx, dy, tw, th = info

    from src.indicators.lean import _load_lean_rotation_source
    rot_src = _load_lean_rotation_source(lean_cfg, size_px)
    preview_pivot_x = (rx - img_ref.width // 2) + (img_ref.width / 2.0 + (rot_src.pivot_px - rot_src.gw / 2.0))
    preview_pivot_y = (ry - img_ref.height // 2) + (8 + rot_src.gh / 2.0 + (rot_src.pivot_py - rot_src.gh / 2.0))

    assert abs(spx - preview_pivot_x) < 0.5
    assert abs(spy - preview_pivot_y) < 0.5


def test_golden_pixel_parity(frame_150_context):
    manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    ref_overlay = frame_150_context["ref_overlay"]

    for name, item in manifest.items():
        x, y, w, h = item["bbox"]
        current_crop = ref_overlay.crop((x, y, x + w, y + h))
        golden_crop_path = REPO_ROOT / item["ref_crop"]
        assert golden_crop_path.exists()
        golden_crop = Image.open(golden_crop_path)
        arr_curr = np.array(current_crop).astype(int)
        arr_gold = np.array(golden_crop).astype(int)
        max_diff = np.max(np.abs(arr_curr - arr_gold))
        assert max_diff == 0, f"Pixel difference detected for {name}: max_diff={max_diff}"
