import pytest
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_extract import (
    load_json_with_fallback, ensure_records_list,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor,
)
from src.indicators.chart_builder import build_chart_data
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache
from src.overlay_renderer import compose_overlay
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value

def test_chart_precompute_full_history_parity():
    root = Path(__file__).parents[1]
    v_file = root / "Video" / "GX030120.json"
    fit_file = root / "Video" / "Poranna_jazda_na_rowerze.fit"
    if not v_file.exists() or not fit_file.exists():
        pytest.skip("Test media not found")

    raw_records = ensure_records_list(load_json_with_fallback(v_file))
    anchor_dt = find_gps_anchor(raw_records)
    fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)

    speed_samples = extract_speed_samples(raw_records)
    alt_samples = extract_altitude_samples(raw_records)
    track_samples = extract_track_samples(raw_records)
    iso_samples = extract_iso_samples(raw_records)
    exposure_samples = extract_exposure_samples(raw_records)
    temp_samples = extract_temperature_samples(raw_records)

    field_samples = {
        "start_dt_utc": anchor_dt,
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temp_samples": temp_samples,
    }

    layout = normalize_layout("def_layout.json", 1920, 1080)
    total_frames = 5400
    fps = 29.97
    duration_s = total_frames / fps
    end_dt_utc = anchor_dt + timedelta(seconds=duration_s)
    source_ranges = {}
    if fit_data:
        all_fit_pts = [s for s in fit_data.values() if s]
        if all_fit_pts:
            source_ranges["fit"] = (
                min(s[0][0] for s in all_fit_pts),
                max(s[-1][0] for s in all_fit_pts),
            )

    def _get_src_samples(src_name: str) -> tuple[list, list, list]:
        if src_name == "gpx":
            return ([], [], [])
        if src_name == "fit":
            fit_d = fit_data or {}
            return (fit_d.get("speed", []), fit_d.get("track", []), fit_d.get("alt", []))
        return (speed_samples or [], track_samples or [], alt_samples or [])

    def _resolve_samples(field_name: str, source: str = "fit", indicator_key: str | None = None) -> list:
        if source == "fit":
            fit_d = fit_data or {}
            aliases = {
                "power": ("power", "curVpower"), "hr": ("hr", "heart_rate"),
                "cad": ("cad", "cadence"), "atemp": ("atemp", "temperature"),
                "battery": ("battery", "battery_soc"),
            }.get(field_name, (field_name,))
            for name in aliases:
                if fit_d.get(name):
                    return list(fit_d[name])
            return []
        return []

    chart_data = build_chart_data(
        layout,
        _get_src_samples,
        _resolve_samples,
        start_dt_utc=anchor_dt, end_dt_utc=end_dt_utc,
        source_activity_ranges=source_ranges,
    )

    assert "fit_cadence_text" in chart_data
    assert "fit_heart_rate_text" in chart_data
    assert len(chart_data["fit_cadence_text"]) > 1000
    assert len(chart_data["fit_heart_rate_text"]) > 1000

    init_worker(
        video_width=1920, video_height=1080,
        field_samples=field_samples,
        layout=layout,
        font_path="",
        fit_data=fit_data,
        start_dt_utc=anchor_dt,
        target_fps=fps,
        total_overlay_frames=total_frames,
        gps_track=fit_data.get("track"),
    )

    precompute_cache = build_telemetry_cache(
        layout=layout,
        base_dt=anchor_dt,
        tz_offset_hours=0.0,
        start_dt_utc=anchor_dt,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        fit_data=fit_data,
        gps_track=fit_data.get("track"),
        chart_data=chart_data,
        total_frames=total_frames,
        target_fps=fps,
    )

    # Test bit-exact pixel identity at 0%, 50%, 100%
    for frame_idx in [0, 2700, 5399]:
        target_dt = anchor_dt + timedelta(seconds=frame_idx / fps)
        fd_off = prepare_overlay_frame_data(
            layout=layout,
            target_dt=target_dt,
            tz_offset_hours=0.0,
            start_dt_utc=anchor_dt,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temp_samples,
            fit_data=fit_data,
            gps_track=fit_data.get("track"),
            total_frames=total_frames,
            current_index=frame_idx,
            chart_data=chart_data,
            resolve_cache_value=_resolve_cache_value,
            _range_cache=WORKER_CACHE.get("_prep_cache"),
        )
        fd_on = precompute_cache.lookup(frame_idx)

        img_off = compose_overlay(1920, 1080, layout, font_path="", **fd_off)
        img_on = compose_overlay(1920, 1080, layout, font_path="", **fd_on)

        arr_off = np.array(img_off)
        arr_on = np.array(img_on)
        diff = np.abs(arr_off.astype(np.int32) - arr_on.astype(np.int32))
        assert np.max(diff) == 0
        assert np.count_nonzero(diff) == 0
