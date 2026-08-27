"""ETAP 5D - real GUI regression tests.

Covers the three regressions found only in a REAL GUI run:
A) REGION decision for the real nested GUI layout shape (form=map/lean/text)
   and for rotated sources under the ETAP 5D autorotate contract,
B) telemetry precompute with an AWARE UTC anchor + naive-UTC VideoTimeline
   (the offset-naive/aware crash that silently disabled precompute),
plus the rotation command-contract policy for the Intel CPU_REFERENCE path.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]


# ── A: REGION decision on the real GUI layout shape ─────────────────────────
def _real_gui_layout_corner() -> dict:
    """Real def_layout.json *shape* (form=..., percent coords), clustered so
    the geometric bbox is materially smaller than the canvas."""
    return {"indicators": {
        "time_display": {"enabled": True, "x": 2.0, "y": 4.0,
                         "form": "time_display", "font_size": 1.8},
        "speed_text": {"enabled": True, "x": 3.0, "y": 88.0,
                       "font_size": 2.5},
        "alt_text": {"enabled": True, "x": 4.0, "y": 78.0,
                     "font_size": 2.2},
        "lean_indicator": {"enabled": True, "x": 12.0, "y": 30.0,
                           "form": "lean", "size": 6.0},
        "track_map": {"enabled": True, "x": 10.0, "y": 40.0,
                      "form": "map", "size": 14.0},
    }}


def _real_gui_layout_full_span() -> dict:
    """Same shape, but indicators spread across the whole frame (like the
    current user layout) -- FULL_CANVAS is then the CORRECT decision."""
    base = _real_gui_layout_corner()["indicators"]
    base["time_display"]["x"] = 0.7
    base["iso_text"] = {"enabled": True, "x": 0.77, "y": 53.74,
                        "font_size": 1.9}
    base["alt_text"]["x"] = 93.93
    base["alt_text"]["y"] = 52.59
    return {"indicators": base}


def test_region_selected_for_real_nested_layout_on_rotated_source():
    """ETAP 5D: rotated source + Intel autorotate contract must NOT force
    FULL_CANVAS anymore; a clustered real-shape layout yields REGION."""
    from src.ffmpeg.streaming import (
        _intel_hud_region_decision,
        _intel_hud_region_gate,
    )

    assert _intel_hud_region_gate(
        False, 180, 180, encoder="intel") is True
    hud_x, hud_y, w, h, ratio, mode = _intel_hud_region_decision(
        _real_gui_layout_corner(), 3840, 2160)
    assert mode == "region"
    assert (w, h) != (3840, 2160)
    assert ratio < 0.85
    assert hud_x % 2 == 0 and hud_y % 2 == 0
    assert hud_x + w <= 3840 and hud_y + h <= 2160


def test_full_canvas_for_full_span_real_layout():
    """A layout whose enabled indicators span the whole canvas legitimately
    selects FULL_CANVAS -- with an explicit reason, not a silent fallback."""
    from src.ffmpeg.streaming import _intel_hud_region_decision

    _, _, w, h, ratio, mode = _intel_hud_region_decision(
        _real_gui_layout_full_span(), 3840, 2160)
    assert mode in ("full_threshold", "full_geometry")
    assert ratio >= 0.85


def test_non_intel_encoders_keep_unrotated_only_region_rule():
    from src.ffmpeg.streaming import _intel_hud_region_gate as gate
    # legacy call shape (no encoder=): rotation still blocks CPU_REF REGION
    assert gate(False, 180, 180) is False


def test_def_layout_json_bbox_matches_real_shape():
    """The actual repository default layout parses and produces a sane bbox
    (guards against future key/shape drift between GUI and bbox code)."""
    from src.ffmpeg.command_builder import get_layout_hud_bbox

    layout = json.loads((REPO / "def_layout.json").read_text(encoding="utf-8"))
    bx, by, bw, bh = get_layout_hud_bbox(layout, 3840, 2160)
    assert 0 <= bx < 3840 and 0 <= by < 2160
    assert bw >= 2 and bh >= 2


# ── B: telemetry precompute datetime contract ────────────────────────────────
def test_precompute_with_aware_anchor_and_naive_timeline():
    """Real GUI combination: AWARE UTC project anchor + naive-UTC timeline.
    Must not raise offset-naive/aware and must keep elapsed semantics."""
    from src.telemetry_precompute import build_telemetry_cache
    from src.multifile import VideoClip, VideoTimeline

    start = datetime(2026, 8, 11, 4, 27, 21, tzinfo=timezone.utc)
    fps = 30000 / 1001
    clip = VideoClip(path=REPO / "Video" / "GX020079.MP4",
                     duration_s=37.738, fps=fps, width=3840, height=2160,
                     absolute_start_dt=start)
    tl = VideoTimeline.from_clips([clip], base_dt=start)
    samples = [(start + timedelta(seconds=i * 1001 / 30000), 10.0 + i)
               for i in range(400)]
    cache = build_telemetry_cache(
        layout={"indicators": {"speed_text": {
            "type": "speed_text", "x": 5, "y": 5, "width": 10,
            "height": 4, "enabled": True}}},
        base_dt=start, tz_offset_hours=2, start_dt_utc=start,
        speed_samples=samples, track_samples=[], alt_samples=[],
        total_frames=30, target_fps=fps, video_timeline=tl)
    recs = cache.records
    assert len(recs) == 30
    assert recs[0].elapsed_seconds == 0.0
    assert recs[1].elapsed_seconds > recs[0].elapsed_seconds
    expected_first = float(np.interp(0.0, [0.0, 400 * 1001 / 30000],
                                     [10.0, 409.0]))
    assert abs(recs[0].speed_value - expected_first) < 0.51
    # local wall clock = UTC + tz offset
    assert recs[0].time_text == "06:27:21"


def test_precompute_pure_aware_inputs_still_match():
    """No-timeline path with fully aware inputs keeps identical semantics."""
    from src.telemetry_precompute import build_telemetry_cache

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    samples = [(start + timedelta(seconds=i), float(i)) for i in range(60)]
    cache = build_telemetry_cache(
        layout={"indicators": {}}, base_dt=start, tz_offset_hours=0,
        start_dt_utc=start, speed_samples=samples, track_samples=[],
        alt_samples=[], total_frames=10, target_fps=1.0, video_timeline=None)
    assert cache.records[7].elapsed_seconds == 7.0
    assert cache.records[7].speed_value == 7.0


# ── C: rotation command-contract policy ──────────────────────────────────────
def test_intel_hdr_sw_decode_rotated_graph_has_no_baked_flips():
    from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd

    cmd, fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=180, container_rotation=180,
        stream_w=3840, stream_h=2160,
        intel_gpu_resident=False,
        intel_cpu_software_decode=True,
        intel_cpu_download_format="p010le",
        generation_fps=30000 / 1001,
        resolution_name="source",
        ffmpeg_exe="ffmpeg", input_args=["-i", "in.mp4"],
        output_file="out.mp4",
    )
    assert "vflip" not in fc and "hflip" not in fc and "transpose" not in fc
    assert "format=p010le[base]" in fc

