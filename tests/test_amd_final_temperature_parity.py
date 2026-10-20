"""AMD Final (render_preparation vectorized builder) vs Preview temperature parity.

The AMD final HUD reads every scalar from RenderPreparationService columns;
Preview resolves through TelemetryDataManager.resolve_value ->
resolve_current_presentation.  Both must show the same value and precision.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from src.render_preparation import RenderPreparationService
from src.telemetry_resolver import resolve_current_presentation, resolve_samples_from_sources

BASE = datetime(2026, 10, 16, 4, 22, 16)
FPS = 30.0
FRAMES = 1800


def _dt(seconds: float) -> datetime:
    return BASE + timedelta(seconds=seconds)


# Garmin FIT temperature: integer degrees, 1 s records, slow cooling.
FIT_TEMP = [(_dt(i), float(19 - i // 20)) for i in range(70)]
# GoPro TMPC: fractional camera temperature.
GPMF_TEMP = [(_dt(i * 2), 40.904297 + 0.0123 * i) for i in range(35)]
FIT_HR = [(_dt(i), float(100 + i % 7)) for i in range(70)]


def _layout(temp_source="gpmf", fit_decimals=1, temp_decimals=1):
    return {
        "indicators": {
            "temp_text": {"enabled": True, "form": "text", "source": temp_source, "decimals": temp_decimals},
            "fit_temperature_text": {"enabled": True, "form": "bar", "source": "fit",
                                     "decimals": fit_decimals, "unit": "C"},
            "fit_heart_rate_text": {"enabled": True, "form": "text", "source": "fit"},
        }
    }


def _build(layout, **kw):
    return RenderPreparationService.build_telemetry_cache_vectorized(
        layout=layout, base_dt=BASE, start_dt_utc=BASE,
        fit_data={"temperature": FIT_TEMP, "heart_rate": FIT_HR},
        temperature_samples=GPMF_TEMP, total_frames=FRAMES, target_fps=FPS, **kw)


def _frame_dt(i: int) -> datetime:
    return BASE + timedelta(seconds=round(i / FPS * 1e6) / 1e6)


def test_fit_temperature_final_equals_preview_resolver_and_keeps_decimal():
    layout = _layout()
    cache = _build(layout)
    cfg = layout["indicators"]["fit_temperature_text"]
    fractional = 0
    for i in range(0, FRAMES, 7):
        preview = resolve_current_presentation(FIT_TEMP, _frame_dt(i), "temperature", cfg)
        final = cache.lookup(i)["extra_indicators"]["fit_temperature_text"][0]
        assert final == pytest.approx(preview, abs=1e-9)
        assert f"{final:.1f}" == f"{preview:.1f}"
        fractional += abs(final - round(final)) > 1e-6
    # Before the fix the final column was a raw STEP (19.0, 18.0, ...).
    assert fractional > 0


def test_fit_temperature_decimals_zero_stays_native_step():
    cache = _build(_layout(fit_decimals=0))
    col = np.asarray(cache.columns["fit_temperature_text"], dtype=float)
    vals = col[~np.isnan(col)]
    assert np.all(np.abs(vals - np.round(vals)) < 1e-9)


@pytest.mark.parametrize("source", ["gpmf", "fit", "auto"])
def test_temp_text_final_uses_preview_source_and_presentation(source):
    layout = _layout(temp_source=source)
    cache = _build(layout)
    from types import SimpleNamespace
    samples = resolve_samples_from_sources(
        "temperature", source, gpmf=SimpleNamespace(temperature_samples=GPMF_TEMP),
        fit_data={"temperature": FIT_TEMP, "heart_rate": FIT_HR}, gpx=SimpleNamespace(gpx_atemp_samples=[]))
    expected_src = GPMF_TEMP if source == "gpmf" else FIT_TEMP
    assert samples is expected_src
    cfg = layout["indicators"]["temp_text"]
    for i in range(0, FRAMES, 11):
        preview = resolve_current_presentation(samples, _frame_dt(i), "temperature", cfg)
        assert cache.lookup(i)["temp_value"] == pytest.approx(preview, abs=1e-9)


def test_gpmf_temperature_fraction_preserved_in_final():
    cache = _build(_layout(temp_source="gpmf"))
    assert cache.lookup(0)["temp_value"] == pytest.approx(40.904297, abs=1e-6)


def test_integer_only_fields_unchanged_by_temperature_contract():
    cache = _build(_layout())
    hr = np.asarray(cache.columns["fit_heart_rate_text"], dtype=float)
    hr = hr[~np.isnan(hr)]
    assert np.all(np.abs(hr - np.round(hr)) < 1e-9)


def test_render_prep_cache_key_invalidates_pre_fix_step_caches():
    import hashlib
    kwargs = dict(video_paths=[], total_frames=FRAMES, target_fps=FPS, start_dt_utc=BASE, layout=_layout())
    key = RenderPreparationService.compute_cache_key(**kwargs)
    # Key of the pre-fix contract (no presentation_contract entry).
    data_sig = RenderPreparationService.extract_semantic_data_signature(_layout())
    legacy = {
        "version": "v2_charts_pauses_range", "v_fps": [], "t_fps": ["", ""],
        "total_frames": FRAMES, "target_fps": round(FPS, 4), "sync_offset_s": 0.0,
        "start_ts": round(BASE.timestamp(), 4), "data_sig": data_sig, "timeline": "", "skip_pauses": False,
    }
    legacy_key = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode("utf-8")).hexdigest()
    legacy["presentation_contract"] = "quantized_reconstruct_preview_timeline_v2"
    assert key == hashlib.sha256(json.dumps(legacy, sort_keys=True).encode("utf-8")).hexdigest()
    assert key != legacy_key


# ── HDR/HLG export evidence (user's real AMD exports; skipped elsewhere) ──
_FINALS = [Path(r"D:\GoPro\SCH\20261016-0620.mp4"), Path(r"D:\GoPro\SCH\20261012-1530.mp4")]


@pytest.mark.parametrize("final", _FINALS, ids=["night", "day"])
def test_amd_hlg_final_keeps_source_colour_contract(final):
    if not final.exists() or shutil.which("ffprobe") is None:
        pytest.skip("user AMD HLG export not available on this machine")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=profile,pix_fmt,color_range,color_space,color_transfer,color_primaries", "-of", "json", str(final)],
        capture_output=True, text=True, timeout=60, check=True)
    st = json.loads(out.stdout)["streams"][0]
    assert st["profile"] == "Main 10" and st["pix_fmt"] == "yuv420p10le"
    assert (st["color_transfer"], st["color_primaries"], st["color_space"], st["color_range"]) == (
        "arib-std-b67", "bt2020", "bt2020nc", "pc")


def test_range_export_uses_preview_project_timeline_for_reconstruction():
    """In/Out export: change events outside the range must still ramp like Preview."""
    from pathlib import Path as _P
    from types import SimpleNamespace
    from src.multifile import VideoClip, VideoTimeline
    project = VideoTimeline([VideoClip(_P("a.mp4"), duration_s=70.0, absolute_start_dt=BASE,
                                       timestamp_reliable=True)])
    ranged = project.subset_excluding([(0.0, 30.0), (32.0, 70.0)])  # export 30..32 s
    frames = int(round(2.0 * FPS))
    layout = _layout()
    telemetry = SimpleNamespace(timeline=project)
    cache = RenderPreparationService.build_telemetry_cache_vectorized(
        layout=layout, base_dt=BASE, start_dt_utc=BASE,
        fit_data={"temperature": FIT_TEMP, "heart_rate": FIT_HR}, temperature_samples=GPMF_TEMP,
        total_frames=frames, target_fps=FPS, video_timeline=ranged, telemetry=telemetry)
    cfg = layout["indicators"]["fit_temperature_text"]
    seen = set()
    for i in range(frames):
        dt = ranged.frame_to_absolute(i, FPS)
        preview = resolve_current_presentation(FIT_TEMP, dt, "temperature", cfg, active_time_mapper=project)
        final = cache.lookup(i)["extra_indicators"]["fit_temperature_text"][0]
        assert final == pytest.approx(preview, abs=1e-9)
        seen.add(f"{final:.1f}")
    assert len(seen) > 1  # a 20 s plateau ramps; a STEP would show one value
