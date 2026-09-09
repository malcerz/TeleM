from datetime import datetime, timedelta
import pytest
from src.telemetry_resolver import (
    canonical_telemetry_field, field_semantics, resolve_current_presentation,
    _presentation_meta, interpolate_presentation_value, presentation_value,
)
from src.ffmpeg import worker_cache
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache
from src.telemetry_active_time import ActiveTimeMapper
from src.telemetry_resolver import NormalizedFitDistance
from src.telemetry_resolver import build_battery_presentation_plan, numeric_presentation_plan

BASE = datetime(2026, 9, 2, 4, 34, 57)
KEY = 'fit_garmin_battery_percent_text'


@pytest.mark.parametrize('name', ['garmin_battery_percent', 'garmin_battery_voltage',
    'temperature', 'curVpower', 'solar_pct', 'solar', 'fractional_cadence'])
def test_dynamic_registry(name):
    assert canonical_telemetry_field(f'fit_{name}_text') == name
    assert field_semantics(f'fit_{name}_text').semantic_type == 'continuous'


@pytest.mark.parametrize('field', ['iso', 'shut', 'exposure', 'gps_fix', 'status', 'mode',
                                    'id', 'device_id', 'event_count', 'unknown_numeric'])
def test_discrete_cannot_be_overridden(field):
    samples = [(BASE, 100), (BASE + timedelta(seconds=60), 200)]
    assert resolve_current_presentation(samples, BASE+timedelta(seconds=30), field,
               {'decimals': 2, 'interpolation_policy': 'linear'}) == 100


def test_cache_different_interiors_and_exact_nan_neighbor():
    # Identical first/last/count must not identify distinct sample series.
    a = [(BASE, 96), (BASE+timedelta(seconds=10), 96), (BASE+timedelta(seconds=60), 95)]
    b = [(BASE, 96), (BASE+timedelta(seconds=50), 96), (BASE+timedelta(seconds=60), 95)]
    assert resolve_current_presentation(a, BASE+timedelta(seconds=30), 'battery', {'decimals': 2}) == 95.5
    assert resolve_current_presentation(b, BASE+timedelta(seconds=30), 'battery', {'decimals': 2}) == 95.5
    assert resolve_current_presentation([(BASE, 96), (BASE+timedelta(seconds=1), float('nan'))],
                                        BASE, 'battery', {'decimals': 2}) == 96


def test_sparse_quantization_pause_and_gap():
    raw = [(BASE+timedelta(seconds=i*60), v) for i,v in enumerate([98.,98.,98.,97.])]
    assert _presentation_meta(raw, 'garmin_battery_percent') == (60, 0)
    paused = ActiveTimeMapper([(BASE, BASE+timedelta(seconds=130)),
                              (BASE+timedelta(seconds=150), BASE+timedelta(seconds=180))])
    dt = BASE+timedelta(seconds=160)
    assert resolve_current_presentation(raw, dt, 'battery', {'decimals': 2}) < 98
    assert resolve_current_presentation(raw, dt, 'battery', {'decimals': 2}, active_time_mapper=paused) == 98


@pytest.mark.parametrize('dp', [0,1,2,3])
def test_real_export_precomputed_equals_frame_data(dp):
    raw = [(BASE,96.), (BASE+timedelta(seconds=60),95.)]
    cfg = {'enabled':True, 'source':'fit', 'form':'bar', 'bar_style':'segments', 'decimals':dp}
    layout = {'indicators':{KEY:cfg}}
    fit = {'garmin_battery_percent':raw}
    worker_cache.init_worker(320,180,'Arial',layout,{},fit_data=fit,start_dt_utc=BASE)
    cache = build_telemetry_cache(layout=layout, base_dt=BASE,tz_offset_hours=0,
        start_dt_utc=BASE,speed_samples=[],track_samples=[],alt_samples=[],fit_data=fit,
        total_frames=5,target_fps=1/15,resolve_cache_value=worker_cache._resolve_cache_value)
    for i in range(5):
        dt=BASE+timedelta(seconds=i*15)
        data=prepare_overlay_frame_data(layout=layout,target_dt=dt,tz_offset_hours=0,
            start_dt_utc=BASE,speed_samples=[],track_samples=[],alt_samples=[],fit_data=fit,
            resolve_cache_value=worker_cache._resolve_cache_value)
        actual=data['extra_indicators'][KEY][0]
        assert cache.lookup(i)['extra_indicators'][KEY][0] == actual
        assert actual == (96-i*.25 if dp else (95 if i==4 else 96))


def test_no_full_series_copy_on_warm_lookup():
    class Counted(list):
        def __iter__(self):
            self.scans = getattr(self, 'scans', 0)+1
            return super().__iter__()
    raw=Counted((BASE+timedelta(seconds=i), 96-i//500) for i in range(1000))
    for i in range(100):
        resolve_current_presentation(raw,BASE+timedelta(seconds=499,microseconds=i*1000),
                                     'battery',{'decimals':2})
    assert raw.scans <= 2  # one metadata pass and one change-event index pass


def test_real_gap_and_merged_cut_boundary_never_create_a_false_ramp():
    # A missing 10-minute interval is data absence, not a smooth physical
    # transition.  A merged FIT distance reset uses the same contract.
    sparse = [(BASE, 96.), (BASE + timedelta(seconds=60), 95.),
              (BASE + timedelta(seconds=660), 94.)]
    assert resolve_current_presentation(sparse, BASE + timedelta(seconds=300),
                                        'battery', {'decimals': 2}) == 95.
    merged = NormalizedFitDistance([(BASE, 100.), (BASE + timedelta(seconds=60), 120.),
                                    (BASE + timedelta(seconds=120), 120.)],
                                   segment_start_indices=(2,))
    assert resolve_current_presentation(merged, BASE + timedelta(seconds=90),
                                        'distance', {'decimals': 2}) == 120.


def test_segment_bar_receives_full_presentation_float_not_segment_count(monkeypatch):
    from src.indicators import bar
    observed = []
    real = bar._render_segments
    def capture(**kwargs):
        observed.append(kwargs['value'])
        return real(**kwargs)
    monkeypatch.setattr(bar, '_render_segments', capture)
    cfg = {'x': 50, 'y': 50, 'size': 25, 'form': 'bar', 'bar_style': 'segments',
           'min_val': 0, 'max_val': 100, 'segments': 10, 'decimals': 2,
           'show_value': True, 'show_label': False}
    bar._render_bar_indicator(640, 360, {'indicators': {}}, 'Arial', 'battery',
                              95.437284, '%', '', cfg, 360, 0, 20, 'Arial',
                              0, 100, 0, 1, 160, 1)
    assert observed == [95.437284]


def test_change_event_interpolation_spans_repeated_plateaus_and_both_directions():
    values = [98, 98, 98, 98, 97, 96, 96, 96, 95]
    raw = [(BASE + timedelta(seconds=i * 60), value) for i, value in enumerate(values)]
    assert resolve_current_presentation(raw, BASE + timedelta(seconds=60),
                                        'battery', {'decimals': 2}) == 97.75
    assert resolve_current_presentation(raw, BASE + timedelta(seconds=120),
                                        'battery', {'decimals': 2}) == 97.5
    assert resolve_current_presentation(raw, BASE + timedelta(seconds=180),
                                        'battery', {'decimals': 2}) == 97.25
    assert resolve_current_presentation(raw, BASE + timedelta(seconds=240),
                                        'battery', {'decimals': 2}) == 97.0
    assert resolve_current_presentation(raw, BASE + timedelta(seconds=360),
                                        'battery', {'decimals': 2}) == 95.66666666666667
    rising = [(BASE + timedelta(seconds=i * 60), value)
              for i, value in enumerate([20, 20, 21, 21, 22])]
    assert resolve_current_presentation(rising, BASE + timedelta(seconds=60),
                                        'battery', {'decimals': 2}) == 20.5


def test_last_quantized_plateau_holds_without_extrapolation():
    raw = [(BASE, 96), (BASE + timedelta(seconds=60), 96)]
    assert resolve_current_presentation(raw, BASE + timedelta(seconds=30),
                                        'battery', {'decimals': 2}) == 96
    assert resolve_current_presentation(raw, BASE + timedelta(seconds=600),
                                        'battery', {'decimals': 2}) == 96


def test_battery_plan_back_predicts_first_drop_and_open_tail():
    raw = [(BASE + timedelta(seconds=i * 60), value)
           for i, value in enumerate([98, 98, 98, 97, 97, 96, 96])]
    plan = build_battery_presentation_plan(raw, coverage_start=BASE,
                                           coverage_end=BASE + timedelta(seconds=420))
    assert [segment.kind for segment in plan.segments] == [
        'back_predicted_first_transition', 'observed_transition', 'open_tail_estimate']
    assert plan.segments[0].start_time == BASE + timedelta(seconds=60)
    assert plan.value_at(BASE + timedelta(seconds=120)) == pytest.approx(97.5)
    assert plan.value_at(BASE + timedelta(seconds=360)) == pytest.approx(95.505)
    assert plan.value_at(BASE + timedelta(seconds=420)) == pytest.approx(95.01)


def test_single_state_and_two_state_plans_have_deterministic_tails():
    one = [(BASE, 90), (BASE + timedelta(seconds=60), 90)]
    one_plan = build_battery_presentation_plan(one, coverage_start=BASE,
                                               coverage_end=BASE + timedelta(seconds=120))
    assert one_plan.value_at(BASE) == 90
    assert one_plan.value_at(BASE + timedelta(seconds=120)) == pytest.approx(89.01)
    two = [(BASE, 90), (BASE + timedelta(seconds=60), 89)]
    two_plan = build_battery_presentation_plan(two, coverage_start=BASE,
                                               coverage_end=BASE + timedelta(seconds=120))
    assert two_plan.value_at(BASE + timedelta(seconds=30)) == pytest.approx(89.5)
    assert two_plan.value_at(BASE + timedelta(seconds=120)) == pytest.approx(88.01)


def test_generic_numeric_plan_is_decimal_independent_and_linear_for_continuous_fields():
    raw = [(BASE, 10.0), (BASE + timedelta(seconds=10), 11.0)]
    plan = numeric_presentation_plan(raw, 'speed')
    assert plan.strategy == 'linear'
    assert plan.value_at(BASE + timedelta(seconds=5)) == pytest.approx(10.5)
    # Precision belongs to formatting; the planner returns one canonical float.
    assert [plan.value_at(BASE + timedelta(seconds=5)) for _ in range(4)] == [10.5] * 4
    assert presentation_value(raw, BASE + timedelta(seconds=5), 'speed',
                              effective_precision=0) == pytest.approx(10.5)


def test_generic_plan_preserves_gap_and_cut_boundaries():
    raw = NormalizedFitDistance([
        (BASE, 100.0), (BASE + timedelta(seconds=10), 120.0),
        (BASE + timedelta(seconds=20), 140.0),
    ], segment_start_indices=(2,))
    plan = numeric_presentation_plan(raw, 'distance')
    assert plan.value_at(BASE + timedelta(seconds=5)) == pytest.approx(110.0)
    assert plan.value_at(BASE + timedelta(seconds=15)) == pytest.approx(120.0)


def test_generic_discrete_plan_is_step_even_when_layout_requests_linear():
    raw = [(BASE, 100), (BASE + timedelta(seconds=10), 200)]
    plan = numeric_presentation_plan(raw, 'iso')
    assert plan.strategy == 'raw_step'
    assert plan.value_at(BASE + timedelta(seconds=5)) == 100


def test_quantized_voltage_uses_plan_only_beyond_native_resolution():
    raw = [(BASE, 4.225), (BASE + timedelta(seconds=20), 4.221)]
    assert resolve_current_presentation(raw, BASE + timedelta(seconds=10),
                                        'garmin_battery_voltage', {'decimals': 2}) == pytest.approx(4.225)
    assert resolve_current_presentation(raw, BASE + timedelta(seconds=10),
                                        'garmin_battery_voltage', {'decimals': 4}) == pytest.approx(4.223)
