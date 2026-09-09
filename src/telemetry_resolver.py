"""Shared source-aware telemetry resolution primitives.

This module deliberately contains no fallback between telemetry sources.  A
caller must choose ``gpmf``, ``fit`` or ``gpx`` explicitly; an empty result is
returned when that source has no samples.
"""

from __future__ import annotations

import math
import os
import json
from collections import OrderedDict
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


SOURCE_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "fit": {
        # FIT distance is the canonical cumulative activity stream.  ``track``
        # remains the GPS-derived fallback for files without that FIT field.
        "distance": ("distance", "track"),
        "power": ("power", "curVpower"),
        "hr": ("hr", "heart_rate"),
        "cad": ("cad", "cadence"),
        "atemp": ("atemp", "temperature", "garmin_temperature"),
        "battery": ("battery", "battery_soc", "garmin_battery_percent", "battery_pct"),
        "garmin_battery_voltage": ("garmin_battery_voltage", "battery_voltage"),
        "garmin_battery_percent": ("garmin_battery_percent", "battery_level", "battery_pct", "battery"),
        "garmin_temperature": ("garmin_temperature", "device_temperature", "temperature"),
        "heading": ("heading",),
        "slope": ("slope",),
    },
    "gpx": {
        "power": ("power",),
        "hr": ("hr",),
        "cad": ("cad",),
        "atemp": ("atemp",),
        "battery": ("battery",),
    },
}


@dataclass(frozen=True)
class FieldSemantics:
    semantic_type: str = 'discrete'
    native_resolution: float | None = None
    default_interpolation: str = 'step'
    gap_policy: str = 'never_cross_gap'
    quantized: bool = False
    presentation_strategy: str = 'raw_step'


def canonical_telemetry_field(name: str) -> str:
    """Dynamic indicator -> source field; never infer a different source."""
    name = str(name or '')
    if name.startswith('fit_') and name.endswith('_text'):
        return name[4:-5]
    return {'temp_text': 'temperature', 'atemp_text': 'atemp',
            'battery_text': 'battery', 'power_text': 'power', 'iso_text': 'iso',
            'exposure_text': 'exposure', 'speed_text': 'speed', 'speed_visual': 'speed',
            'dist_text': 'distance', 'dist_visual': 'distance', 'alt_text': 'alt',
            'alt_visual': 'alt'}.get(name, name)


# Presentation policy is deliberately backend-neutral: the same logical field
# follows the same rule whether its samples came from FIT, GPMF or GPX.
CONTINUOUS_PRESENTATION_FIELDS = frozenset({
    "battery", "battery_soc", "battery_pct", "garmin_battery_percent",
    "garmin_battery_voltage", "battery_voltage", "temperature", "atemp",
    "speed", "enhanced_speed", "ground_speed", "alt", "altitude",
    "enhanced_altitude", "distance", "dist", "track", "power",
    "solar", "solar_pct",
    "gopro_battery", "battery_level", "garmin_temperature", "device_temperature",
    "curVpower", "fractional_cadence",
})
DISCRETE_PRESENTATION_FIELDS = frozenset({
    "iso", "exposure", "shut", "gps_fix", "fix", "mode", "status",
    "id", "boolean", "enum",
})
FIELD_SEMANTICS = {
    name.lower(): FieldSemantics('continuous', default_interpolation='auto',
                                 presentation_strategy='linear')
    for name in CONTINUOUS_PRESENTATION_FIELDS
}
FIELD_SEMANTICS.update({name: FieldSemantics() for name in DISCRETE_PRESENTATION_FIELDS})
for _name in ('battery', 'battery_pct', 'battery_soc', 'garmin_battery_percent',
              'battery_level', 'gopro_battery'):
    FIELD_SEMANTICS[_name] = FieldSemantics('continuous', 1.0, 'auto', 'never_cross_gap', True, 'monotonic_depletion')
for _name in ('battery_voltage', 'garmin_battery_voltage'):
    FIELD_SEMANTICS[_name] = FieldSemantics('continuous', .001, 'auto', 'never_cross_gap', True, 'quantized_reconstruct')
for _name in ('speed', 'enhanced_speed', 'ground_speed', 'alt', 'altitude',
              'enhanced_altitude', 'distance', 'dist', 'track'):
    FIELD_SEMANTICS[_name] = FieldSemantics('continuous', default_interpolation='linear', presentation_strategy='linear')


def field_semantics(name: str) -> FieldSemantics:
    name = canonical_telemetry_field(name).lower()
    if name in FIELD_SEMANTICS:
        return FIELD_SEMANTICS[name]
    if name.endswith(('_count', '_counter')):
        return FieldSemantics('counter')
    # Unknown numeric IDs, modes, enums and unclassified developer fields are
    # conservative STEP, never continuous merely because they contain numbers.
    return FieldSemantics()


def presentation_default_precision(field: str, cfg: Mapping | None = None) -> int:
    cfg = cfg or {}
    if cfg.get('form') in ('bar', 'segment_bar', 'gauge', 'chart'):
        return 1  # form schema default
    if 'voltage' in canonical_telemetry_field(field).lower():
        return 2
    if not field.startswith('fit_') and canonical_telemetry_field(field) in (
            'speed', 'enhanced_speed', 'ground_speed', 'distance', 'dist', 'alt', 'altitude'):
        return 1
    return 0


def presentation_debug(stage: str, **values) -> None:
    if os.environ.get('TELEM_PRESENTATION_INTERP_DEBUG') == '1':
        print('[PRESENTATION] ' + json.dumps(dict(stage=stage, **values), default=str), flush=True)


# Retain the source reference alongside metadata to avoid id reuse. Metadata
# is prepared once for immutable source series; replacements have a new id.
_PRESENTATION_META_CACHE = OrderedDict()
_PRESENTATION_CHANGE_CACHE = OrderedDict()


@dataclass(frozen=True)
class QuantizedChangeTimeline:
    """Immutable change-event index for plateau-aware presentation values."""

    # Each tuple is (raw start index, raw end index, change events).  Keeping
    # raw indices makes segment/gap membership O(1) after the timestamp search.
    segments: tuple[tuple[int, int, tuple[tuple[datetime, Any], ...]], ...]


@dataclass(frozen=True)
class BatteryPlanSegment:
    start_time: datetime
    end_time: datetime
    start_value: float
    end_value: float
    kind: str


@dataclass(frozen=True)
class NumericPresentationPlan:
    """Immutable full-series presentation plan shared by numeric indicators."""

    raw_samples: tuple
    change_events: tuple[tuple[datetime, float], ...]
    observed_drop_durations: tuple[float, ...]
    segments: tuple[BatteryPlanSegment, ...]
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    strategy: str = 'linear'
    median_interval: float | None = None
    gap_multiplier: float = 5.0
    segment_start_indices: tuple[int, ...] = ()

    def value_at(self, target_dt: datetime, *, active_time_mapper: Any = None) -> float | None:
        if target_dt is None:
            return None
        target = _naive_dt(target_dt)
        if self.coverage_start is not None and target < _naive_dt(self.coverage_start):
            return None
        if not self.segments and self.raw_samples:
            idx = bisect_right(self.raw_samples, target, key=lambda item: _naive_dt(item[0]))
            if idx == 0:
                return None
            if idx >= len(self.raw_samples) or self.strategy in ('raw_step', 'hold', 'counter_step'):
                return self.raw_samples[min(idx, len(self.raw_samples)) - 1][1]
            left = self.raw_samples[idx - 1]
            right = self.raw_samples[idx]
            span = (_naive_dt(right[0]) - _naive_dt(left[0])).total_seconds()
            if span <= 0:
                return left[1]
            if (idx in self.segment_start_indices or
                    (self.median_interval is not None and
                     span > self.median_interval * max(1.0, self.gap_multiplier))):
                return left[1]
            if active_time_mapper is not None:
                active_span = (active_time_mapper.wall_to_active_seconds(right[0]) -
                               active_time_mapper.wall_to_active_seconds(left[0]))
                if active_span + 1e-6 < span:
                    return left[1]
            f = (target - _naive_dt(left[0])).total_seconds() / span
            return float(left[1]) + (float(right[1]) - float(left[1])) * f
        if not self.segments:
            return None
        if target < self.segments[0].start_time:
            return self.segments[0].start_value
        for segment in self.segments:
            if target < segment.start_time:
                continue
            if target <= segment.end_time:
                span = (segment.end_time - segment.start_time).total_seconds()
                if span <= 0:
                    return segment.end_value
                if active_time_mapper is not None:
                    active_span = (active_time_mapper.wall_to_active_seconds(segment.end_time) -
                                   active_time_mapper.wall_to_active_seconds(segment.start_time))
                    if active_span + 1e-6 < span:
                        return segment.start_value
                fraction = max(0.0, min(1.0,
                    (target - segment.start_time).total_seconds() / span))
                return segment.start_value + (segment.end_value - segment.start_value) * fraction
        # A plan normally ends in an open-tail segment. Preserve endpoint hold
        # if the caller queries beyond an explicitly bounded coverage range.
        return self.segments[-1].end_value


_BATTERY_PLAN_CACHE = OrderedDict()
_NUMERIC_PLAN_CACHE = OrderedDict()

# Compatibility name retained for existing callers and reports.
BatteryPresentationPlan = NumericPresentationPlan


def resolve_presentation_precision(config: Mapping[str, Any] | None, default: int = 0) -> int:
    """Return one effective display precision for resolver and renderer.

    ``decimals`` is the GUI property used by text/bar/gauge indicators;
    ``decimal_places`` is retained as a compatibility fallback for chart-era
    layouts.  Prefer an explicitly present ``decimals`` value, including zero,
    so a stale ``decimal_places=0`` cannot discard a user's ``decimals=1``.
    """
    cfg = config if isinstance(config, Mapping) else {}
    raw = cfg["decimals"] if "decimals" in cfg else cfg.get("decimal_places", default)
    try:
        return max(0, min(6, int(raw)))
    except (TypeError, ValueError, OverflowError):
        try:
            return max(0, min(6, int(default)))
        except (TypeError, ValueError, OverflowError):
            return 0


def interpolation_policy(field_name: str, configured: str | None = None) -> str:
    """Return ``step``, ``linear`` or ``auto`` for a logical field."""
    metadata = field_semantics(field_name)
    # Discrete camera/state fields are never numerically interpolated, even if
    # a stale layout requests ``linear``.  This keeps ISO/SHUT/status semantic
    # guarantees stronger than per-indicator presentation preferences.
    if metadata.semantic_type != 'continuous':
        return "step"
    requested = str(configured or "auto").strip().lower()
    if requested in {"step", "linear", "auto"}:
        if requested != "auto":
            return requested
    return metadata.default_interpolation


def _naive_dt(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo is not None else value


def build_battery_presentation_plan(
    samples, *, coverage_start: datetime | None = None,
    coverage_end: datetime | None = None,
) -> BatteryPresentationPlan:
    """Read one complete Battery series and create its presentation curve.

    Raw input is only referenced (never rewritten).  Identical quantized
    values are collapsed to first-change events.  The first unknown drop is
    back-predicted with the duration of the next observed transition; the
    final unconfirmed level gets an N→N-.99 open tail when coverage is known.
    """
    raw = tuple(samples or ())
    if not raw:
        return BatteryPresentationPlan((), (), (), (), coverage_start, coverage_end)
    events: list[tuple[datetime, float]] = []
    for sample in raw:
        try:
            dt, value = _naive_dt(sample[0]), float(sample[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not math.isfinite(value):
            continue
        if not events or value != events[-1][1]:
            events.append((dt, value))
    if not events:
        return BatteryPresentationPlan(raw, (), (), (), coverage_start, coverage_end)
    starts = _naive_dt(coverage_start) if coverage_start is not None else events[0][0]
    ends = _naive_dt(coverage_end) if coverage_end is not None else _naive_dt(raw[-1][0])
    durations = tuple(max(0.0, (events[i + 1][0] - events[i][0]).total_seconds())
                      for i in range(len(events) - 1))
    segments: list[BatteryPlanSegment] = []
    if len(events) == 1:
        # Explicit single-state estimate; without a known video endpoint there
        # is no safe place to invent a depletion tail.
        if coverage_end is not None and ends > starts:
            segments.append(BatteryPlanSegment(starts, ends, events[0][1],
                                               events[0][1] - .99,
                                               'single_state_estimate'))
        else:
            segments.append(BatteryPlanSegment(starts, ends, events[0][1],
                                               events[0][1], 'open_tail_hold'))
    else:
        first_start = events[0][0]
        predicted_start = first_start
        if len(events) >= 3 and durations[1] > 0:
            predicted_start = events[1][0] - (events[2][0] - events[1][0])
            first_start = predicted_start
        first_start = max(starts, first_start)
        first_value = events[0][1]
        if first_start > predicted_start and len(events) >= 3:
            full_span = (events[1][0] - predicted_start).total_seconds()
            if full_span > 0:
                first_value = events[0][1] + (events[1][1] - events[0][1]) * ((first_start - predicted_start).total_seconds() / full_span)
        # Product contract: when the first real sample visible in the video
        # explicitly reports the first integer level, begin at that level even
        # if the inferred historical ramp started before the clip.
        if coverage_start is not None:
            for sample in raw:
                try:
                    if _naive_dt(sample[0]) >= starts:
                        if float(sample[1]) == events[0][1]:
                            first_value = events[0][1]
                        break
                except (TypeError, ValueError, IndexError):
                    continue
        if first_start < events[1][0]:
            segments.append(BatteryPlanSegment(first_start, events[1][0],
                                               first_value, events[1][1],
                                               'back_predicted_first_transition' if len(events) >= 3
                                               else 'observed_transition'))
        for index in range(1, len(events) - 1):
            segments.append(BatteryPlanSegment(events[index][0], events[index + 1][0],
                                               events[index][1], events[index + 1][1],
                                               'observed_transition'))
        if coverage_end is not None and ends > events[-1][0]:
            segments.append(BatteryPlanSegment(events[-1][0], ends, events[-1][1],
                                               events[-1][1] - .99, 'open_tail_estimate'))
        elif not segments or ends > segments[-1].end_time:
            segments.append(BatteryPlanSegment(events[-1][0], ends, events[-1][1],
                                               events[-1][1], 'open_tail_hold'))
    plan = BatteryPresentationPlan(raw, tuple(events), durations, tuple(segments), starts, ends)
    if os.environ.get('TELEM_BATTERY_PLAN_DEBUG') == '1':
        print('[BatteryPlan] raw_samples=%d change_events=%d' % (len(raw), len(events)), flush=True)
        for segment in plan.segments:
            print('[BatteryPlan] SEG %s %s -> %s %.3f -> %.3f' %
                  (segment.kind, segment.start_time, segment.end_time,
                   segment.start_value, segment.end_value), flush=True)
    return plan


def battery_presentation_plan(samples, *, coverage_start=None, coverage_end=None):
    """Return the cached full-FIT Battery plan for an immutable sample series."""
    if not samples:
        return build_battery_presentation_plan(samples, coverage_start=coverage_start,
                                               coverage_end=coverage_end)
    key = (id(samples), len(samples), samples[0][0], samples[-1][0],
           _naive_dt(coverage_start) if coverage_start else None,
           _naive_dt(coverage_end) if coverage_end else None)
    cached = _BATTERY_PLAN_CACHE.get(key)
    if cached is not None:
        return cached[1]
    plan = build_battery_presentation_plan(samples, coverage_start=coverage_start,
                                           coverage_end=coverage_end)
    if len(_BATTERY_PLAN_CACHE) >= 64:
        _BATTERY_PLAN_CACHE.popitem(last=False)
    _BATTERY_PLAN_CACHE[key] = (samples, plan)
    return plan


def numeric_presentation_plan(samples, field, *, coverage_start=None, coverage_end=None):
    """Select one generic plan strategy from the field semantics registry."""
    canonical = canonical_telemetry_field(field)
    if field_semantics(canonical).presentation_strategy == 'monotonic_depletion':
        return battery_presentation_plan(samples, coverage_start=coverage_start,
                                         coverage_end=coverage_end)
    metadata = field_semantics(canonical)
    if not samples:
        return NumericPresentationPlan((), (), (), (), coverage_start, coverage_end, 'hold')
    key = (id(samples), canonical, len(samples), samples[0][0], samples[-1][0],
           _naive_dt(coverage_start) if coverage_start else None,
           _naive_dt(coverage_end) if coverage_end else None)
    cached = _NUMERIC_PLAN_CACHE.get(key)
    if cached is not None:
        return cached[1]
    strategy = metadata.presentation_strategy
    cadence, _ = _presentation_meta(samples, canonical)
    plan = NumericPresentationPlan(
        tuple(samples), (), (), (), coverage_start, coverage_end, strategy,
        cadence, 5.0, tuple(getattr(samples, 'segment_start_indices', ())),
    )
    if len(_NUMERIC_PLAN_CACHE) >= 128:
        _NUMERIC_PLAN_CACHE.popitem(last=False)
    _NUMERIC_PLAN_CACHE[key] = (samples, plan)
    return plan


def _native_decimal_places(step: float | None) -> int:
    if step is None or not math.isfinite(step) or step <= 0.0:
        return 0
    for decimals in range(0, 7):
        scaled = step * (10.0 ** decimals)
        if math.isclose(scaled, round(scaled), rel_tol=1e-7, abs_tol=1e-9):
            return decimals
    return max(0, min(6, int(math.ceil(-math.log10(step)))))


def _presentation_meta(
    samples: list, field_name: str,
) -> tuple[float | None, int]:
    """Get median cadence and observed native decimal precision once per series."""
    if not samples:
        return None, 0
    try:
        key = _presentation_series_key(samples, field_name)
        cached = _PRESENTATION_META_CACHE.get(key)
        if cached is not None:
            return cached[1]
    except Exception:
        key = None

    intervals: list[float] = []
    values: list[float] = []
    previous_t: datetime | None = None
    previous_v: float | None = None
    for sample in samples:
        try:
            dt, value = sample[0], float(sample[1])
            timestamp = _naive_dt(dt)
            if previous_t is not None and timestamp > previous_t:
                intervals.append((timestamp - previous_t).total_seconds())
            if previous_v is not None and math.isfinite(value):
                delta = abs(value - previous_v)
                if delta > 1e-9 and math.isfinite(delta):
                    values.append(delta)
            previous_t, previous_v = timestamp, value
        except (TypeError, ValueError, OverflowError, IndexError):
            continue
    cadence = None
    if intervals:
        ordered = sorted(intervals)
        # A two-interval sequence such as 60 s, 600 s must retain the normal
        # 60 s cadence; arithmetic median would turn the real outage into a
        # 330 s "normal" interval and incorrectly permit a false ramp.
        # The lower median is deliberately conservative for a gap gate.
        cadence = ordered[(len(ordered) - 1) // 2]
    # The smallest observed non-zero delta is the conservative source step.
    native_step = field_semantics(field_name).native_resolution
    if native_step is None:
        native_step = min(values) if values else None
    result = (cadence, _native_decimal_places(native_step))
    if key is not None:
        if len(_PRESENTATION_META_CACHE) >= 128:
            _PRESENTATION_META_CACHE.popitem(last=False)
        _PRESENTATION_META_CACHE[key] = (samples, result)
    return result


def _presentation_series_key(samples: list, field_name: str) -> tuple[Any, ...]:
    first = samples[0]
    last = samples[-1]
    return (
        id(samples), str(field_name).lower(), len(samples), first[0], last[0],
        first[1], last[1],
    )


def _quantized_change_timeline(samples: list, field_name: str) -> QuantizedChangeTimeline | None:
    """Build one change-event stream per continuous telemetry segment.

    Repeated quantized samples are a plateau, not new interpolation anchors.
    Segment boundaries are created by the same cadence/gap gate used by the
    scalar resolver; a real outage can therefore never be crossed by a ramp.
    """
    if not samples or not field_semantics(field_name).quantized:
        return None
    try:
        key = _presentation_series_key(samples, field_name)
        cached = _PRESENTATION_CHANGE_CACHE.get(key)
        if cached is not None:
            return cached[1]
    except Exception:
        key = None
    cadence, _ = _presentation_meta(samples, field_name)
    threshold = cadence * 5.0 if cadence is not None else None
    native = field_semantics(field_name).native_resolution
    segments: list[tuple[int, int, tuple[tuple[datetime, Any], ...]]] = []
    seg_start = 0
    events: list[tuple[datetime, Any]] = []
    previous_dt = None
    previous_bucket = None

    def finish(end_index: int) -> None:
        if events:
            segments.append((seg_start, end_index, tuple(events)))

    for index, sample in enumerate(samples):
        try:
            dt, value = sample[0], float(sample[1])
            dt_n = _naive_dt(dt)
        except (TypeError, ValueError, IndexError):
            continue
        if not math.isfinite(value):
            continue
        if previous_dt is not None and threshold is not None:
            if (dt_n - previous_dt).total_seconds() > threshold:
                finish(index)
                seg_start = index
                events = []
                previous_bucket = None
        if native is not None and native > 0:
            bucket = int(round(value / native))
        else:
            bucket = value
        if previous_bucket is None or bucket != previous_bucket:
            events.append((dt_n, sample[1]))
            previous_bucket = bucket
        previous_dt = dt_n
    finish(len(samples))
    result = QuantizedChangeTimeline(tuple(segments))
    if key is not None:
        if len(_PRESENTATION_CHANGE_CACHE) >= 128:
            _PRESENTATION_CHANGE_CACHE.popitem(last=False)
        _PRESENTATION_CHANGE_CACHE[key] = (samples, result)
    return result


def _interpolate_quantized_change_events(
    samples: list, target: datetime, field_name: str, active_time_mapper: Any = None,
) -> Any:
    timeline = _quantized_change_timeline(samples, field_name)
    if timeline is None:
        return None
    target_n = _naive_dt(target)
    previous_segment_value = None
    for start, end, events in timeline.segments:
        first_t = events[0][0]
        last_raw_t = _naive_dt(samples[end - 1][0])
        if target_n < first_t:
            return previous_segment_value
        if target_n > last_raw_t:
            previous_segment_value = events[-1][1]
            continue
        event_index = bisect_right(events, target_n, key=lambda item: item[0]) - 1
        if event_index < 0:
            return None
        left_t, left_value = events[event_index]
        if event_index + 1 >= len(events):
            return left_value
        right_t, right_value = events[event_index + 1]
        if target_n == right_t:
            return right_value
        span = (right_t - left_t).total_seconds()
        if span <= 0:
            return left_value
        if active_time_mapper is not None:
            active_span = (active_time_mapper.wall_to_active_seconds(right_t)
                           - active_time_mapper.wall_to_active_seconds(left_t))
            if active_span + 1e-6 < span:
                return left_value
        fraction = (target_n - left_t).total_seconds() / span
        return float(left_value) + (float(right_value) - float(left_value)) * fraction
    return previous_segment_value


def interpolate_presentation_value(
    samples: list,
    target_dt: datetime,
    field_name: str,
    *,
    precision: int | None = None,
    policy: str | None = None,
    gap_multiplier: float = 5.0,
    active_time_mapper: Any = None,
    indicator_config: Mapping | None = None,
) -> Any:
    """Resolve a presentation value, linearly only when policy permits.

    Raw samples are never modified.  Lookup is neighbor-based (binary search),
    and interpolation is suppressed across an unusually large cadence gap.
    """
    if not samples or target_dt is None:
        return None
    policy_name = interpolation_policy(field_name, policy)
    try:
        target = _naive_dt(target_dt)
        idx = bisect_right(samples, target, key=lambda sample: _naive_dt(sample[0]))
    except (TypeError, AttributeError, IndexError):
        return None
    if idx == 0:
        return None
    if idx >= len(samples):
        return samples[-1][1]
    left_dt, left_value = samples[idx - 1]
    right_dt, right_value = samples[idx]
    # Exact raw samples are exact for ordinary fields. Quantized duplicate
    # samples resolve against their plateau change event instead.
    if target == _naive_dt(left_dt) and not (
        field_semantics(field_name).quantized and policy_name != "step"
    ):
        return left_value
    if os.environ.get('TELEM_PRESENTATION_INTERP_DEBUG') == '1':
        cadence, native_dp = _presentation_meta(samples, field_name)
        interval = (_naive_dt(right_dt) - _naive_dt(left_dt)).total_seconds()
        presentation_debug('neighbors', field=field_name, target_dt=target_dt,
                           cfg=dict(indicator_config or {}), precision=precision,
                           policy=policy_name, previous=(left_dt, left_value),
                           next=(right_dt, right_value), interval=interval,
                           median_interval=cadence, gap_threshold=(cadence or 0)*gap_multiplier,
                           native_resolution=10**-native_dp,
                           fraction=(target-_naive_dt(left_dt)).total_seconds()/interval)
    if policy_name == "step":
        return left_value
    if policy_name == "auto":
        _cadence, native_decimals = _presentation_meta(samples, field_name)
        try:
            requested_decimals = max(0, int(precision or 0))
        except (TypeError, ValueError, OverflowError):
            requested_decimals = 0
        if requested_decimals <= native_decimals:
            return left_value
    if field_semantics(field_name).quantized:
        quantized_value = _interpolate_quantized_change_events(
            samples, target, field_name, active_time_mapper
        )
        if quantized_value is not None:
            return quantized_value
    try:
        span = (_naive_dt(right_dt) - _naive_dt(left_dt)).total_seconds()
        if span <= 0.0:
            return left_value
        if idx in getattr(samples, 'segment_start_indices', ()):
            return left_value
        if active_time_mapper is not None:
            # Compare active elapsed with wall elapsed: any timer pause inside
            # this sample pair forbids a ramp, even when the cadence is sparse.
            active_span = (active_time_mapper.wall_to_active_seconds(right_dt)
                           - active_time_mapper.wall_to_active_seconds(left_dt))
            if active_span + 1e-6 < span:
                return left_value
        cadence, _native_decimals = _presentation_meta(samples, field_name)
        if cadence is not None and span > max(1e-9, cadence * max(1.0, float(gap_multiplier))):
            return left_value
        if not (math.isfinite(float(left_value)) and math.isfinite(float(right_value))):
            return left_value
        fraction = (target - _naive_dt(left_dt)).total_seconds() / span
        return float(left_value) + (float(right_value) - float(left_value)) * fraction
    except (TypeError, ValueError, OverflowError):
        return left_value


def presentation_value(
    samples,
    target_dt: datetime,
    field: str,
    *,
    effective_precision: int = 0,
    policy: str | None = None,
    active_time_mapper: Any = None,
    coverage_start: datetime | None = None,
    coverage_end: datetime | None = None,
    indicator_config: Mapping | None = None,
) -> Any:
    """Canonical raw-series → current presentation float operation.

    The returned value is intentionally unformatted.  Preview, precompute and
    every final renderer consume this same scalar; text formatting and visual
    geometry happen only after this boundary.
    """
    canonical = canonical_telemetry_field(field)
    metadata = field_semantics(canonical)
    configured_policy = str(policy or '').strip().lower()
    use_plan = (
        metadata.semantic_type == 'continuous' and
        metadata.presentation_strategy == 'linear' and
        configured_policy != 'step'
    )
    if (metadata.presentation_strategy == 'monotonic_depletion' and
            effective_precision >= 1 and
            (canonical in ('garmin_battery_percent', 'gopro_battery') or
             coverage_start is not None)):
        # GoPro and Garmin battery streams share the same quantized continuous
        # contract.  Generic ``battery`` callers retain the legacy resolver
        # unless a coverage-aware plan is explicitly requested.
        use_plan = True
    if (metadata.presentation_strategy == 'quantized_reconstruct' and
            effective_precision > _native_decimal_places(metadata.native_resolution)):
        # Native-resolution display remains STEP; only a request for finer
        # presentation precision opts into the generic plan.
        use_plan = True
    if use_plan:
        return numeric_presentation_plan(
            samples, canonical, coverage_start=coverage_start,
            coverage_end=coverage_end,
        ).value_at(target_dt, active_time_mapper=active_time_mapper)
    return interpolate_presentation_value(
        samples, target_dt, canonical, precision=effective_precision,
        policy=policy, active_time_mapper=active_time_mapper,
        indicator_config=indicator_config,
    )


def resolve_current_presentation(samples, target_dt, field, cfg=None, *, active_time_mapper=None):
    """Canonical scalar presentation contract, shared by Preview and exports."""
    field = canonical_telemetry_field(field)
    cfg = cfg or {}
    precision = resolve_presentation_precision(cfg, presentation_default_precision(field, cfg))
    value = presentation_value(
        samples, target_dt, field, effective_precision=precision,
        policy=cfg.get('interpolation_policy'), active_time_mapper=active_time_mapper,
        coverage_start=cfg.get('_presentation_video_start'),
        coverage_end=cfg.get('_presentation_video_end'),
        indicator_config=cfg,
    )
    if value is not None and field in ('speed', 'enhanced_speed', 'ground_speed'):
        value = max(0.0, value)
    presentation_debug('resolved', field=field, target_dt=target_dt,
                       precision=precision, policy=interpolation_policy(field, cfg.get('interpolation_policy')),
                       value=value)
    return value

METERS_PER_KILOMETER = 1000.0


@dataclass(frozen=True)
class FitDistanceNormalization:
    """Summary of one recorded FIT cumulative-distance normalization."""

    segments: int
    resets: int
    segment_ends: tuple[float, ...]
    normalized_final: float | None
    session_total: float | None = None
    match: bool | None = None


class NormalizedFitDistance(list):
    """Canonical FIT distance samples with reset-boundary interpolation hints.

    ``segment_start_indices`` lets ``interpolate_distance`` hold the preceding
    cumulative value until the first record of a new merged segment.  Keeping
    the hint on the stream prevents preview, precompute and worker paths from
    inventing movement across an activity gap.
    """

    def __init__(
        self,
        samples=(),
        *,
        segment_start_indices: tuple[int, ...] = (),
        normalization: FitDistanceNormalization | None = None,
    ) -> None:
        super().__init__(samples)
        self.segment_start_indices = tuple(segment_start_indices)
        self.normalization = normalization


def distance_m_to_km(value_m: Any) -> float | None:
    """Convert the telemetry distance contract (metres) to display km once."""
    if value_m is None:
        return None
    return float(value_m) / METERS_PER_KILOMETER


def distance_range_m_to_km(
    minimum_m: Any, maximum_m: Any,
) -> tuple[float, float]:
    """Convert a telemetry distance range from metres to display kilometres."""
    minimum_km = distance_m_to_km(minimum_m)
    maximum_km = distance_m_to_km(maximum_m)
    if minimum_km is None or maximum_km is None:
        raise ValueError("distance range endpoints must not be None")
    return minimum_km, maximum_km


def _fit_distance_reset(previous: float, current: float) -> bool:
    """Detect a clear cumulative reset while ignoring ordinary FIT float noise."""
    noise_tolerance_m = max(1.0, abs(previous) * 0.001)
    return (
        previous > 0.0
        and current < previous - noise_tolerance_m
        and current <= previous * 0.5
    )


def normalize_fit_recorded_distance(
    samples: list | None,
    *,
    session_total: Any = None,
    emit_diagnostic: bool = False,
) -> NormalizedFitDistance:
    """Repair merged FIT ``record.distance`` into one monotonic metre stream.

    A clear drop to a much smaller cumulative value starts a new segment.  The
    preceding segment end becomes the new cumulative offset.  Small backwards
    float noise is clamped, not treated as a merge boundary.  Structurally
    invalid or non-finite input returns an empty stream so callers may use the
    GPS-derived FIT track as a last-resort fallback.
    """
    if isinstance(samples, NormalizedFitDistance):
        return samples
    raw = list(samples or [])
    if len(raw) < 2:
        return NormalizedFitDistance()

    normalized: list[tuple[Any, float]] = []
    segment_starts: list[int] = []
    segment_ends: list[float] = []
    offset = 0.0
    previous_local: float | None = None
    segment_peak: float | None = None
    resets = 0

    for item in raw:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            return NormalizedFitDistance()
        timestamp, raw_value = item[0], item[1]
        try:
            current_local = float(raw_value)
        except (TypeError, ValueError):
            return NormalizedFitDistance()
        if not math.isfinite(current_local) or current_local < 0.0:
            return NormalizedFitDistance()
        if normalized and timestamp < normalized[-1][0]:
            return NormalizedFitDistance()

        if previous_local is not None and _fit_distance_reset(
            previous_local, current_local
        ):
            previous_end = float(segment_peak if segment_peak is not None else previous_local)
            segment_ends.append(previous_end)
            offset += previous_end
            segment_starts.append(len(normalized))
            resets += 1
            segment_peak = current_local
        elif previous_local is not None and current_local < previous_local:
            # A tiny device/float regression is not a segment and must not make
            # cumulative distance move backwards.
            current_local = previous_local

        segment_peak = (
            current_local if segment_peak is None else max(segment_peak, current_local)
        )
        normalized.append((timestamp, offset + current_local))
        previous_local = current_local

    if segment_peak is not None:
        segment_ends.append(float(segment_peak))

    final = normalized[-1][1] if normalized else None
    try:
        session_value = float(session_total) if session_total is not None else None
        if session_value is not None and not math.isfinite(session_value):
            session_value = None
    except (TypeError, ValueError):
        session_value = None
    match = (
        math.isclose(final, session_value, rel_tol=1e-9, abs_tol=0.01)
        if final is not None and session_value is not None
        else None
    )
    summary = FitDistanceNormalization(
        segments=len(segment_ends),
        resets=resets,
        segment_ends=tuple(segment_ends),
        normalized_final=final,
        session_total=session_value,
        match=match,
    )
    result = NormalizedFitDistance(
        normalized,
        segment_start_indices=tuple(segment_starts),
        normalization=summary,
    )
    if emit_diagnostic:
        ends_text = ",".join(f"{value:.2f}" for value in summary.segment_ends)
        final_text = "None" if final is None else f"{final:.2f}"
        session_text = "None" if session_value is None else f"{session_value:.2f}"
        print("[FIT DISTANCE NORMALIZE]", flush=True)
        print(f"segments={summary.segments}", flush=True)
        print(f"resets={summary.resets}", flush=True)
        print(f"segment_ends=[{ends_text}]", flush=True)
        print(f"normalized_final={final_text}", flush=True)
        print(f"session_total={session_text}", flush=True)
        print(f"match={summary.match}", flush=True)
    return result


_GPMF_ATTRS = {
    "speed": "speed_samples",
    "alt": "alt_samples",
    "altitude": "alt_samples",
    "dist": "track_samples",
    "distance": "track_samples",
    "track": "track_samples",
    "iso": "iso_samples",
    "exposure": "exposure_samples",
    "temperature": "temperature_samples",
    "heading": "heading_samples",
    "slope": "slope_samples",
    "accel_x": "accel_x_samples",
    "accel_y": "accel_y_samples",
    "accel_z": "accel_z_samples",
    "accel_magnitude": "accel_magnitude_samples",
    "gyro_x": "gyro_x_samples",
    "gyro_y": "gyro_y_samples",
    "gyro_z": "gyro_z_samples",
    "gyro_magnitude": "gyro_magnitude_samples",
}

_GPX_ATTRS = {
    "speed": "gpx_speed_samples",
    "alt": "gpx_alt_samples",
    "altitude": "gpx_alt_samples",
    "dist": "gpx_track_samples",
    "distance": "gpx_track_samples",
    "track": "gpx_track_samples",
    "power": "gpx_power_samples",
    "hr": "gpx_hr_samples",
    "cad": "gpx_cad_samples",
    "atemp": "gpx_atemp_samples",
    "battery": "gpx_battery_samples",
    "heading": "gpx_heading_samples",
    "slope": "gpx_slope_samples",
}


def _is_usable_cumulative_distance(samples: list) -> bool:
    """Return whether *samples* can represent an activity-global distance."""
    if len(samples) < 2:
        return False
    previous = None
    try:
        for _timestamp, value in samples:
            current = float(value)
            if not math.isfinite(current):
                return False
            if previous is not None and current < previous - 1e-6:
                return False
            previous = current
    except (TypeError, ValueError):
        return False
    return True


def resolve_distance_samples(
    source: str,
    *,
    gpmf_track: list | None = None,
    fit_data: Mapping[str, list] | None = None,
    gpx_track: list | None = None,
) -> list:
    """Return the one canonical cumulative-distance stream for ``source``.

    FIT's recorded ``distance`` field is normalized into an activity-global
    monotonic stream.  The GPS-derived FIT ``track`` is an explicit fallback
    only for unusable recorded data, not a value to combine with it.  All
    returned values stay in the internal telemetry unit: metres.
    """
    source = source or "gpmf"
    if source == "fit":
        data = fit_data or {}
        recorded = data.get("distance", []) or []
        normalized = normalize_fit_recorded_distance(
            recorded,
            session_total=getattr(data, "session_total_distance", None),
        )
        if _is_usable_cumulative_distance(normalized):
            return normalized
        return list(data.get("track", []) or [])
    if source == "gpx":
        return list(gpx_track or [])
    return list(gpmf_track or [])


def distance_max_m(samples: list | None) -> float | None:
    """Return the maximum valid distance in metres from one selected stream."""
    if not samples:
        return None
    try:
        values = [float(value) for _timestamp, value in samples]
        return max(values) if values else None
    except (TypeError, ValueError):
        return None


def build_activity_range_cache(
    layout: Mapping[str, Any], *, speed_samples: list | None = None,
    track_samples: list | None = None, alt_samples: list | None = None,
    gpx_speed_samples: list | None = None,
    gpx_track_samples: list | None = None,
    gpx_alt_samples: list | None = None,
    fit_data: Mapping[str, list] | None = None,
) -> dict[str, float | None]:
    """Build source-exact HUD ranges over the whole loaded activity."""
    indicators = (layout or {}).get("indicators", {})
    fit = fit_data or {}

    def _selected_indicator(*keys: str) -> Mapping[str, Any]:
        configured = [indicators[key] for key in keys if key in indicators]
        return next(
            (cfg for cfg in configured if cfg.get("enabled", True)),
            configured[0] if configured else {},
        )

    dist_ind = _selected_indicator(
        "dist_visual", "dist_text", "fit_distance_text"
    )
    dist_source = dist_ind.get(
        "source", "fit" if "fit_distance_text" in indicators else "gpmf"
    )
    distance = resolve_distance_samples(
        dist_source, gpmf_track=track_samples, fit_data=fit,
        gpx_track=gpx_track_samples,
    )
    speed_ind = _selected_indicator(
        "speed_visual", "speed_text", "fit_speed_text",
        "fit_enhanced_speed_text",
    )
    speed_source = speed_ind.get(
        "source", "fit" if (
            "fit_speed_text" in indicators
            or "fit_enhanced_speed_text" in indicators
        ) else "gpmf",
    )
    speed = (
        gpx_speed_samples if speed_source == "gpx"
        else fit.get("speed", []) if speed_source == "fit"
        else speed_samples
    ) or []
    alt_ind = _selected_indicator(
        "alt_visual", "alt_text", "fit_altitude_text",
        "fit_enhanced_altitude_text",
    )
    alt_source = alt_ind.get(
        "source", "fit" if (
            "fit_altitude_text" in indicators
            or "fit_enhanced_altitude_text" in indicators
        ) else "gpmf",
    )
    altitude = (
        gpx_alt_samples if alt_source == "gpx"
        else fit.get("alt", []) if alt_source == "fit"
        else alt_samples
    ) or []

    def _values(samples: list) -> list[float]:
        values: list[float] = []
        for _timestamp, value in samples:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                values.append(number)
        return values

    speed_values = _values(list(speed))
    altitude_values = _values(list(altitude))
    return {
        "max_distance_m": distance_max_m(distance),
        "max_speed_kmh": max(speed_values) if speed_values else None,
        "min_alt": min(altitude_values) if altitude_values else None,
        "max_alt": max(altitude_values) if altitude_values else None,
    }


def resolve_samples_from_sources(
    logical_field: str,
    source: str,
    *,
    gpmf: Any,
    fit_data: Mapping[str, list] | None = None,
    gpx: Any = None,
) -> list:
    """Return samples for exactly ``source`` and ``logical_field``.

    ``gpmf``, ``fit_data`` and ``gpx`` are intentionally duck-typed so the
    same contract can be used by the GUI manager and FFmpeg worker cache.
    """
    source = source or "gpmf"
    if logical_field in ("distance", "dist", "track"):
        return resolve_distance_samples(
            source,
            gpmf_track=list(getattr(gpmf, "track_samples", []) or []),
            fit_data=fit_data,
            gpx_track=list(getattr(gpx, "gpx_track_samples", []) or []),
        )
    if source == "gpmf":
        attr = _GPMF_ATTRS.get(logical_field)
        return (getattr(gpmf, attr, []) or []) if attr else []

    if source == "fit":
        data = fit_data or {}
        names = SOURCE_ALIASES["fit"].get(logical_field, (logical_field,))
        for name in names:
            samples = data.get(name, []) or []
            if samples:
                return samples  # immutable source view; no O(N) copy per frame
        return []

    if source == "gpx":
        attr = _GPX_ATTRS.get(logical_field)
        return (getattr(gpx, attr, []) or []) if attr else []

    return []


def resolve_field_from_sources(
    logical_field: str,
    source: str,
    *,
    gpmf: Any,
    fit_data: Mapping[str, list] | None = None,
    gpx: Any = None,
) -> list:
    """Named alias for the sample resolver used by value and history paths."""
    return resolve_samples_from_sources(
        logical_field, source, gpmf=gpmf, fit_data=fit_data, gpx=gpx
    )
