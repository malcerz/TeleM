import json
from datetime import timedelta
from pathlib import Path
from statistics import median

from telemetry_fit import parse_fit
from src.indicators.frame_data import build_active_fit_field_plan, prepare_overlay_frame_data
from src.telemetry_extract import interpolate_value
from src.telemetry_precompute import build_telemetry_cache
from src.telemetry_resolver import resolve_samples_from_sources


ROOT = Path(__file__).resolve().parents[1]
FIT_PATH = ROOT / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"


def _dataset():
    parsed = parse_fit(FIT_PATH)
    assert parsed is not None
    samples = {name: meta["samples"] for name, meta in parsed.field_catalog.items()}
    return parsed, samples


def _resolve(samples, field, source, target_dt, indicator_key=None):
    del indicator_key
    selected = resolve_samples_from_sources(
        field, source, gpmf=None, fit_data=samples, gpx=None
    )
    return interpolate_value(selected, target_dt) if selected else None


def test_solar_pct_exists_with_confirmed_fit_metadata():
    parsed, samples = _dataset()
    assert "solar_pct" in parsed.available_fit_fields
    assert "solar_pct" in samples
    assert parsed.field_catalog["solar_pct"]["source"] == "fit"
    assert len(samples["solar_pct"]) == 2340
    assert all(0 <= value <= 100 for _, value in samples["solar_pct"])


def test_solar_pct_units_and_cadence_are_percentage_step_samples():
    parsed, samples = _dataset()
    del parsed
    solar = samples["solar_pct"]
    intervals = [(b[0] - a[0]).total_seconds() for a, b in zip(solar, solar[1:])]
    assert median(intervals) == 1.0
    assert interpolate_value(solar, solar[0][0]) == solar[0][1]
    assert interpolate_value(solar, solar[0][0] + timedelta(milliseconds=500)) == solar[0][1]


def test_zero_is_value_and_missing_is_none():
    _, samples = _dataset()
    solar = samples["solar_pct"]
    zero_time = next(dt for dt, value in solar if value == 0)
    assert interpolate_value(solar, zero_time) == 0.0
    assert interpolate_value([], zero_time) is None


def test_solar_pct_is_not_aliased_to_solar():
    _, samples = _dataset()
    solar_pct = samples["solar_pct"]
    solar = samples["solar"]
    differing = next(
        dt for dt, value in solar_pct
        if _resolve(samples, "solar", "fit", dt) != value
    )
    assert _resolve(samples, "solar_pct", "fit", differing) != _resolve(samples, "solar", "fit", differing)


def test_frame_data_and_precompute_use_the_same_solar_pct_step_value():
    _, samples = _dataset()
    layout = json.loads((ROOT / "presets" / "cycling_dashboard_v10.json").read_text(encoding="utf-8"))
    plan = build_active_fit_field_plan(layout, samples.keys())
    target_dt = samples["solar_pct"][300][0]
    resolver = lambda field, source, dt, key=None: _resolve(samples, field, source, dt, key)

    frame = prepare_overlay_frame_data(
        layout=layout, target_dt=target_dt, tz_offset_hours=0,
        start_dt_utc=samples["solar_pct"][0][0], speed_samples=[],
        track_samples=[], alt_samples=[], fit_data=samples,
        fit_field_plan=plan, resolve_cache_value=resolver,
    )
    frame_value = frame["extra_indicators"]["fit_solar_pct_text"][0]

    cache = build_telemetry_cache(
        layout=layout, base_dt=target_dt, tz_offset_hours=0,
        start_dt_utc=samples["solar_pct"][0][0], speed_samples=[],
        track_samples=[], alt_samples=[], fit_data=samples,
        fit_field_plan=plan, resolve_cache_value=resolver,
        total_frames=1, target_fps=1.0,
    )
    cached_value = cache.lookup(0)["extra_indicators"]["fit_solar_pct_text"][0]
    assert frame_value == cached_value == _resolve(samples, "solar_pct", "fit", target_dt)


def test_v9_unchanged_and_v10_binds_solar_pct_percentage_range():
    v9 = json.loads((ROOT / "presets" / "cycling_dashboard_v9.json").read_text(encoding="utf-8"))
    v10 = json.loads((ROOT / "presets" / "cycling_dashboard_v10.json").read_text(encoding="utf-8"))
    assert "fit_solar_text" in v9["indicators"]
    assert "fit_solar_pct_text" not in v9["indicators"]
    solar = v10["indicators"]["fit_solar_pct_text"]
    assert solar["field"] == "solar_pct"
    assert solar["source"] == "fit"
    assert solar["unit"] == "%"
    assert solar["min_val"] == 0.0 and solar["max_val"] == 100.0
    assert solar["icon"] == "solar"
