from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from PIL import Image
import pytest

from src.telemetry_resolver import (
    canonical_telemetry_field,
    is_integer_only_field,
    presentation_default_precision,
    resolve_presentation_precision,
    interpolate_presentation_value,
    resolve_samples_from_sources,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.gui.qt.models import indicator_default_decimals
from src.indicators.compositor import render_preview
from src.ffmpeg.worker_cache import (
    WORKER_CACHE,
    init_worker,
    _resolve_cache_value,
)


def _dt(seconds: float) -> datetime:
    return datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def test_temperature_raw_floats_preserved():
    """Verify raw float temperature (e.g. 19.2, 19.8) is preserved without truncation."""
    t0 = _dt(0)
    t1 = _dt(10)
    samples = [(t0, 19.2), (t1, 19.8)]
    val0 = interpolate_presentation_value(samples, t0, "temperature", precision=1)
    val1 = interpolate_presentation_value(samples, t1, "temperature", precision=1)
    assert val0 == pytest.approx(19.2, abs=1e-4)
    assert val1 == pytest.approx(19.8, abs=1e-4)


def test_temperature_quantized_interpolation_midpoint():
    """Verify 19.0 -> 20.0 produces midpoint 19.5 when precision >= 1."""
    t0 = _dt(0)
    t1 = _dt(10)
    samples = [(t0, 19.0), (t1, 20.0)]
    t_mid = _dt(5)
    val_mid = interpolate_presentation_value(samples, t_mid, "temperature", precision=1)
    assert val_mid == pytest.approx(19.5, abs=1e-4)


def test_temperature_plateau_change_events_battery_parity():
    """Verify temperature uses identical quantized change-event algorithm as battery."""
    raw = [(_dt(i), 19.0) for i in range(60)] + [(_dt(60 + i), 20.0) for i in range(60)]
    # Across the 19.0 plateau (0..60 s), change-event interpolation ramps smoothly:
    assert interpolate_presentation_value(raw, _dt(30), "temperature", precision=0) == 19.0
    assert interpolate_presentation_value(raw, _dt(30), "temperature", precision=1) == pytest.approx(19.5, abs=1e-4)
    assert interpolate_presentation_value(raw, _dt(15), "temperature", precision=2) == pytest.approx(19.25, abs=1e-4)
    assert interpolate_presentation_value(raw, _dt(45), "temperature", precision=2) == pytest.approx(19.75, abs=1e-4)


def test_temperature_constant_does_not_artificially_fluctuate():
    """When temperature is constant 19.0, resolver must output 19.0 without false drift."""
    samples = [(_dt(i * 5), 19.0) for i in range(10)]
    for sec in [2.5, 7.5, 15.0, 23.3]:
        val = interpolate_presentation_value(samples, _dt(sec), "temperature", precision=1)
        assert val == pytest.approx(19.0, abs=1e-5)


def test_temperature_precision_configuration():
    """Test 0, 1, and 2 decimal places configuration."""
    t0 = _dt(0)
    t1 = _dt(10)
    samples = [(t0, 19.0), (t1, 20.0)]
    t_mid = _dt(5)

    # In GUI/layout config:
    cfg_0 = {"decimals": 0}
    cfg_1 = {"decimals": 1}
    cfg_2 = {"decimals": 2}

    p0 = resolve_presentation_precision(cfg_0, default=1, field="temp_text")
    p1 = resolve_presentation_precision(cfg_1, default=1, field="temp_text")
    p2 = resolve_presentation_precision(cfg_2, default=1, field="temp_text")

    assert p0 == 0
    assert p1 == 1
    assert p2 == 2

    # Interpolated float is continuous:
    val = interpolate_presentation_value(samples, t_mid, "temperature", precision=1)
    assert f"{val:.{p0}f}" == "20"  # 19.5 rounds to 20
    assert f"{val:.{p1}f}" == "19.5"
    assert f"{val:.{p2}f}" == "19.50"


def test_temperature_long_gap_suppression():
    """Verify that gaps exceeding gap_multiplier * median interval are not linearly ramped."""
    # Cadence is 1s, but there is a 60s gap between 10s and 70s
    samples = [(_dt(0), 19.0), (_dt(1), 19.0), (_dt(2), 19.0), (_dt(70), 25.0)]
    # Target in the middle of the long gap:
    val_gap = interpolate_presentation_value(samples, _dt(35), "temperature", precision=1)
    # Must hold the left value (19.0), not ramp to ~22.0
    assert val_gap == pytest.approx(19.0, abs=1e-4)


def test_preview_final_parity():
    """Ensure preview resolver and worker_cache produce identical values."""
    t0 = _dt(0)
    t1 = _dt(10)
    samples = [(t0, 19.0), (t1, 20.0)]
    t_mid = _dt(5)

    layout = {
        "indicators": {
            "temp_text": {"source": "fit", "decimals": 1}
        }
    }

    # Worker cache simulation
    init_worker(
        320, 180, "Arial", layout, {}, fit_data={"temperature": samples}
    )

    final_val = _resolve_cache_value("temperature", "fit", t_mid, "temp_text")

    # Preview simulation via TelemetryDataManager
    manager = TelemetryDataManager()
    manager.fit_data = {"temperature": samples}
    manager.layout = layout
    preview_val = manager.resolve_value("temperature", t_mid, source="fit", indicator_key="temp_text")

    assert final_val is not None
    assert preview_val is not None
    assert final_val == pytest.approx(preview_val, abs=1e-5)
    assert final_val == pytest.approx(19.5, abs=1e-5)


def test_temperature_gui_default_decimals():
    """Verify GUI models default temperature to 1 decimal place while preserving integer fields."""
    assert indicator_default_decimals("temp_text") == 1
    assert indicator_default_decimals("atemp_text") == 1
    assert indicator_default_decimals("fit_temperature_text") == 1
    assert presentation_default_precision("temperature") == 1

    # Integer fields remain 0
    assert indicator_default_decimals("hr_text") == 0
    assert indicator_default_decimals("cad_text") == 0
    assert indicator_default_decimals("power_text") == 0
    assert indicator_default_decimals("iso_text") == 0
    assert presentation_default_precision("heart_rate") == 0
    assert presentation_default_precision("cadence") == 0
    assert presentation_default_precision("power") == 0
    assert presentation_default_precision("iso") == 0


def test_compositor_temp_text_formatting():
    """Verify compositor renders temp_text with proper decimal formatting."""
    layout = {
        "global": {"antialiasing": 1},
        "indicators": {
            "temp_text": {
                "enabled": True,
                "type": "text",
                "x": 100,
                "y": 100,
                "width": 200,
                "height": 50,
                "font_size": 20,
                "decimals": 1,
                "show_units": True,
                "color": [255, 255, 255],
            }
        }
    }
    src_img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    res_img = render_preview(
        src_img,
        layout,
        "",
        "2026-10-20",
        "12:00:05",
        speed_value=0.0,
        distance_m=0.0,
        temp_value=19.5,
    )
    assert res_img is not None
    assert res_img.size == (1920, 1080)


@pytest.mark.parametrize('policy', ['auto', 'linear'])
@pytest.mark.parametrize('decimals', [1, 2])
def test_canonical_temperature_plateau(policy, decimals):
    from src.telemetry_resolver import resolve_current_presentation
    raw=[(_dt(i),19.) for i in range(60)]+[(_dt(60),20.)]
    snapshot=list(raw)
    for sec,expected in [(0,19),(15,19.25),(30,19.5),(45,19.75),(60,20)]:
        assert resolve_current_presentation(raw,_dt(sec),'temperature',
            {'decimals':decimals,'interpolation_policy':policy}) == pytest.approx(expected)
    assert raw==snapshot


def test_explicit_step_overrides_reconstruction():
    from src.telemetry_resolver import resolve_current_presentation
    raw=[(_dt(59),19.),(_dt(60),20.)]
    assert resolve_current_presentation(raw,_dt(59.5),'temperature',
        {'decimals':1,'interpolation_policy':'step'})==19.


@pytest.mark.parametrize('policy', ['auto','linear','step'])
def test_fractional_native_samples_never_requantized(policy):
    from src.telemetry_resolver import resolve_current_presentation
    raw=[(_dt(i),v) for i,v in enumerate([19.2,19.3,19.4,19.5,19.6,19.7,19.8,21.029297,40.904297])]
    for t,v in raw:
        assert interpolate_presentation_value(raw,t,'temperature',precision=1,policy=policy)==v
        assert resolve_current_presentation(raw,t,'temperature',{'decimals':1,'interpolation_policy':policy})==v


@pytest.mark.parametrize('source,expected',[('fit',None),('gpmf',21.029297),('auto',21.029297)])
def test_source_contract_preview_final(source,expected):
    raw=[(_dt(0),21.029297),(_dt(1),21.029297)]
    layout={'indicators':{'temp_text':{'source':source,'decimals':2}}}
    init_worker(320,180,'Arial',layout,{'temperature_samples':raw},fit_data={})
    manager=TelemetryDataManager()
    manager.fit_data={}
    manager.temperature_samples=raw
    manager.layout=layout
    assert manager.resolve_value('temperature',_dt(.5),source=source,indicator_key='temp_text')==expected
    assert _resolve_cache_value('temperature',source,_dt(.5),'temp_text')==expected


@pytest.mark.parametrize('policy', ['auto','step','linear'])
@pytest.mark.parametrize('decimals', [0,1,2])
def test_gui_configuration_reaches_both_resolvers(policy, decimals):
    raw=[(_dt(i),19.) for i in range(60)]+[(_dt(60),20.)]
    cfg={'source':'fit','decimals':decimals,'interpolation_policy':policy}
    layout={'indicators':{'temp_text':cfg}}
    init_worker(320,180,'Arial',layout,{},fit_data={'temperature':raw})
    manager=TelemetryDataManager()
    manager.fit_data={'temperature':raw}
    manager.layout=layout
    expected=19. if policy=='step' or (policy=='auto' and decimals==0) else 19.5
    assert manager.resolve_value('temperature',_dt(30),source='fit',indicator_key='temp_text')==expected
    assert _resolve_cache_value('temperature','fit',_dt(30),'temp_text')==expected


def test_quantized_plan_and_canonical_share_change_timeline():
    from src.telemetry_resolver import numeric_presentation_plan, resolve_current_presentation
    raw=[(_dt(i),19.) for i in range(60)]+[(_dt(60),20.)]
    plan=numeric_presentation_plan(raw,'temperature')
    assert plan is numeric_presentation_plan(raw,'temperature')
    assert plan.value_at(_dt(30))==resolve_current_presentation(raw,_dt(30),'temperature',{'decimals':1})==19.5


def test_temperature_segments_and_missing_samples():
    from src.telemetry_resolver import resolve_current_presentation, NormalizedFitDistance
    for raw in [
        [(_dt(0),19),(_dt(1),19),(_dt(2),19),(_dt(70),20)],
        [(_dt(0),19),(_dt(1),None),(_dt(2),20)],
        NormalizedFitDistance([(_dt(0),19),(_dt(1),19),(_dt(2),20)],segment_start_indices=(2,)),
    ]:
        assert resolve_current_presentation(raw,_dt(-1),'temperature',{'decimals':1}) is None
        assert resolve_current_presentation(raw,_dt(.5),'temperature',{'decimals':1})==19


def test_temperature_no_ramp_over_real_clip_gap_or_cut():
    from src.telemetry_resolver import resolve_current_presentation
    from src.multifile import VideoClip, VideoTimeline
    from pathlib import Path
    raw=[(_dt(i),19.) for i in range(60)]+[(_dt(60),20.)]
    timeline=VideoTimeline([
        VideoClip(Path('a'),duration_s=20,absolute_start_dt=_dt(0),timestamp_reliable=True),
        VideoClip(Path('b'),duration_s=20,absolute_start_dt=_dt(40),timestamp_reliable=True)])
    assert resolve_current_presentation(raw,_dt(15),'temperature',{'decimals':1},timeline=timeline,active_time_mapper=timeline)==19.


@pytest.mark.parametrize('source,expected',[('fit',None),('auto',21.029297),('gpmf',21.029297)])
def test_legacy_final_frame_does_not_mix_sources(tmp_path,monkeypatch,source,expected):
    from src.ffmpeg import frame_renderer
    raw=[(_dt(0),21.029297),(_dt(1),21.029297)]
    layout={'indicators':{'temp_text':{'enabled':True,'source':source,'decimals':2}}}
    init_worker(320,180,'Arial',layout,{'temperature_samples':raw},fit_data={})
    seen=[]
    def compose(*args,**kwargs):
        seen.append(args[14])
        return Image.new('RGBA',(320,180))
    monkeypatch.setattr(frame_renderer,'compose_overlay',compose)
    frame_renderer.render_overlay_job((0,str(tmp_path),_dt(0),0,[],[],[],30))
    assert seen==[expected]


def test_auto_prefers_fit_and_tmpc_fractional_precision():
    from src.telemetry_resolver import resolve_current_presentation
    camera=[(_dt(0),16.910156),(_dt(1),21.029297),(_dt(2),40.904297)]
    fit=[(_dt(0),19.2),(_dt(1),20.2)]
    layout={'indicators':{'temp_text':{'source':'auto','decimals':2}}}
    init_worker(320,180,'Arial',layout,{'temperature_samples':camera},fit_data={'temperature':fit})
    manager=TelemetryDataManager()
    manager.fit_data={'temperature':fit}
    manager.temperature_samples=camera
    manager.layout=layout
    assert _resolve_cache_value('temperature','auto',_dt(0),'temp_text')==19.2
    assert manager.resolve_value('temperature',_dt(0),source='auto',indicator_key='temp_text')==19.2
    for t,v in camera:
        assert resolve_current_presentation(camera,t,'temperature',{'decimals':2})==v


def test_temperature_large_series_reuses_precomputed_event_index():
    from src.telemetry_resolver import resolve_current_presentation, _quantized_change_timeline
    raw=[(_dt(i),19.+(i//60)%2) for i in range(10000)]
    events=_quantized_change_timeline(raw,'temperature')
    for i in range(300):
        assert resolve_current_presentation(raw,_dt(i/30),'temperature',{'decimals':1}) is not None
    assert _quantized_change_timeline(raw,'temperature') is events


def test_full_frame_speed_and_temperature_share_resolver(monkeypatch):
    from src.ffmpeg import frame_renderer
    raw=[(_dt(i),19.) for i in range(60)]+[(_dt(60),20.)]
    layout={'indicators':{
        'temp_text':{'enabled':True,'source':'fit','decimals':1},
        'speed_text':{'enabled':True,'source':'fit','decimals':1}}}
    init_worker(320,180,'Arial',layout,{},fit_data={'temperature':raw,'speed':[(_dt(0),2),(_dt(60),3)]})
    seen=[]
    def compose(*args,**kwargs):
        seen.append(args[14])
        return Image.new('RGBA',(320,180))
    monkeypatch.setattr(frame_renderer,'compose_overlay',compose)
    frame_renderer.render_overlay_frame(900,_dt(0),0,[],[],[],30)
    assert seen==[19.5]
