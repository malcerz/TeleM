"""Unit and integration tests for fast rate-aware vectorized telemetry states precomputation."""

import pytest
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

from src.gui.telemetry_manager import TelemetryDataManager
from src.gui.layout_manager import normalize_layout
from src.multifile import build_timeline_from_paths
from src.ffmpeg.nvidia_config import TelemFrameState
from src.telemetry_states_fast import compute_fast_telemetry_states

BASE_DIR = Path(__file__).resolve().parent.parent

@pytest.fixture(scope="module")
def benchmark_data():
    fit_path = str(BASE_DIR / "Video" / "20260911.fit")
    v1 = str(BASE_DIR / "Video" / "GX010290.MP4")
    v2 = str(BASE_DIR / "Video" / "GX010291.mp4")
    v3 = str(BASE_DIR / "Video" / "GX020291.mp4")
    layout_path = str(BASE_DIR / "def_layout.json")

    tm = TelemetryDataManager()
    tm.load_fit(fit_path)
    layout = normalize_layout(layout_path, 3840, 2160)
    timeline = build_timeline_from_paths([v1, v2, v3], base_dt=tm.start_dt_utc)
    return tm, layout, timeline


def test_fast_telemetry_states_allocation_and_speed(benchmark_data):
    tm, layout, timeline = benchmark_data
    export_frames = 63391
    fps = 30000 / 1001.0

    states = compute_fast_telemetry_states(tm, timeline, export_frames, fps)
    assert len(states) == export_frames
    assert states[0].frame_index == 0
    assert states[export_frames - 1].frame_index == export_frames - 1


def test_fast_telemetry_states_parity_sample(benchmark_data):
    tm, layout, timeline = benchmark_data
    fps = 30000 / 1001.0
    export_frames = 500

    states = compute_fast_telemetry_states(tm, timeline, export_frames, fps)

    # Initial backfill frames (f0, f10): speed is held to first valid sample (5.508 km/h)
    for f in [0, 10]:
        st = states[f]
        assert abs(st.speed_kmh - 5.508) <= 1e-3
        assert st.speed_str == b"5.5"
        assert st.garmin_battery_str == b"69.00"

    from src.telemetry_resolver import battery_presentation_plan
    base_dt = getattr(tm, "start_dt_utc", None)
    plan_tl = battery_presentation_plan(tm.resolve_samples("garmin_battery_percent", "fit"), coverage_start=base_dt, timeline=timeline)

    # Outside initial backfill window: 100% exact parity with resolver
    for f in [50, 100, 250, 499]:
        t_global = f / fps
        c_idx, local_s = timeline.global_to_clip(t_global)
        cur_dt = timeline.clip_local_to_absolute(c_idx, local_s, base_dt=base_dt)

        st = states[f]
        leg_spd = float(tm.resolve_value("speed", cur_dt, source="fit") or 0.0)
        leg_hr = float(tm.resolve_value("heart_rate", cur_dt, source="fit") or 0.0)
        leg_cad = float(tm.resolve_value("cadence", cur_dt, source="fit") or 0.0)
        leg_pwr = float(tm.resolve_value("curVpower", cur_dt, source="fit") or 0.0)
        leg_dist = float(tm.resolve_value("distance", cur_dt, source="fit") or 0.0) / 1000.0
        leg_bat = float(plan_tl.value_at(cur_dt, active_time_mapper=timeline) or 0.0)

        # Compare with 32-bit float quantization as stored in TelemFrameState struct
        assert abs(st.speed_kmh - float(np.float32(leg_spd))) <= 1e-6
        assert abs(st.heart_rate_bpm - float(np.float32(leg_hr))) <= 1e-6
        assert abs(st.cadence_rpm - float(np.float32(leg_cad))) <= 1e-6
        assert abs(st.power_w - float(np.float32(leg_pwr))) <= 1e-6
        assert abs(st.distance_km - float(np.float32(leg_dist))) <= 1e-6
        assert abs(st.garmin_battery_pct - float(np.float32(leg_bat))) <= 1e-6

        # String representations
        assert st.hr_str == f"{int(round(leg_hr))}".encode("ascii")
        assert st.cad_str == f"{int(round(leg_cad))}".encode("ascii")
        assert st.power_str == f"{int(round(leg_pwr))}".encode("ascii")
        assert st.speed_str == f"{float(np.float32(leg_spd)):.1f}".encode("ascii")
        assert st.distance_str == f"{float(np.float32(leg_dist)):.2f}".encode("ascii")
        assert st.garmin_battery_str == f"{float(np.float32(leg_bat)):.2f}".encode("ascii")
