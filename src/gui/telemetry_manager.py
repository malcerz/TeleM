"""Telemetry data manager – loads, caches and resolves telemetry data from
GPMF (ExifTool), GPX and FIT sources."""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta
from statistics import median
from pathlib import Path
from typing import Any, Callable, Optional

from src.telemetry_resolver import resolve_samples_from_sources
from src.telemetry_heading import derive_heading_samples, interpolate_heading
from src.telemetry_slope import derive_slope_from_streams, interpolate_slope

# Import telemetry modules (with fallback stubs)
try:
    from telemetry_gpx import (
        find_gpx_for_video,
        parse_gpx,
        process_gpx,
        sync_gpx_to_video,
    )
    _GPX_AVAILABLE = True
except ImportError:
    _GPX_AVAILABLE = False

    def process_gpx(video_path, video_start_dt=None):  # noqa: E302
        return None

    def find_gpx_for_video(video_path):  # noqa: E302
        return None

    def parse_gpx(path):  # noqa: E302
        return None

    def sync_gpx_to_video(points, video_start_dt):  # noqa: E302
        return None, None, None, None, None, None, None


try:
    from telemetry_fit import (
        FitDataset,
        find_fit_for_video,
        parse_fit,
        process_fit,
        sync_fit_to_video,
    )
    _FIT_AVAILABLE = True
except ImportError:
    _FIT_AVAILABLE = False

    class FitDataset(dict):  # type: ignore[no-redef]
        available_fit_fields = frozenset()
        field_catalog = {}

    def process_fit(video_path, video_start_dt=None):  # noqa: E302
        return None

    def find_fit_for_video(video_path):  # noqa: E302
        return None

    def parse_fit(path):  # noqa: E302
        return None

    def sync_fit_to_video(points, video_start_dt):  # noqa: E302
        return {}


# ---- Type aliases ----
Sample = tuple[datetime, float]
SampleList = list[Sample]

# FIT field-name lookup (used when resolving non-standard field names)
_FIT_LOOKUP: dict[str, tuple[str, ...]] = {
    "power": ("curVpower",),
    "hr": ("heart_rate",),
    "cad": ("cadence",),
    "atemp": ("temperature",),
    "battery": ("battery_soc",),
}

# GPS-related fields handled by built-in indicators (not registered as extension)
_GPS_HANDLED: set[str] = {"speed", "alt", "track", "lat", "lon", "timestamp", "heading", "slope"}

# GPMF-native field names that resolve to GPMF samples directly
_GPMF_NATIVE: set[str] = {"speed", "alt", "dist", "track", "iso", "exposure", "temperature"}

# GPX-to-source indicators that get auto-switched
_SOURCE_SWITCH_KEYS: tuple[str, ...] = (
    "speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text",
)


def _align_offset_by_track(
    records: Optional[list[dict]],
    gpmf_track: Optional[list[tuple[datetime, float, float]]],
    baseline_offset: Optional[timedelta] = None,
) -> Optional[timedelta]:
    """Find a small FIT-to-video offset from GPS points at common UTC times.

    Absolute UTC is the primary alignment.  Candidate offsets are therefore
    searched around zero, and coverage is measured over the GPMF fragment that
    actually overlaps the FIT GPS track.  The returned offset is added to FIT
    timestamps.
    """
    if not records or not gpmf_track:
        return None
    del baseline_offset  # kept only for backwards-compatible callers

    fit_pts: list[tuple[datetime, float, float]] = []
    for r in records:
        if r.get("timestamp") is None or r.get("lat") is None or r.get("lon") is None:
            continue
        dt = r["timestamp"]
        dt = dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
        fit_pts.append((dt, r["lat"], r["lon"]))
    fit_pts.sort(key=lambda p: p[0])
    if len(fit_pts) < 10 or len(gpmf_track) < 10:
        return None

    try:
        from src.telemetry_extract import haversine_m
    except ImportError:
        return None

    gpmf_pts: list[tuple[datetime, float, float]] = []
    g_step = max(1, len(gpmf_track) // 120)
    for i in range(0, len(gpmf_track), g_step):
        dt, lat, lon = gpmf_track[i]
        if lat is None or lon is None:
            continue
        dt = dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
        gpmf_pts.append((dt, lat, lon))
    if len(gpmf_pts) < 5:
        return None

    gpmf_first, gpmf_last = gpmf_pts[0][0], gpmf_pts[-1][0]
    fit_first, fit_last = fit_pts[0][0], fit_pts[-1][0]
    fit_times = [p[0] for p in fit_pts]

    def interpolate_position(target: datetime) -> Optional[tuple[float, float]]:
        right = bisect_right(fit_times, target)
        if right == 0:
            return None
        if right == len(fit_pts):
            if target == fit_pts[-1][0]:
                return fit_pts[-1][1], fit_pts[-1][2]
            return None
        left = right - 1
        t1, lat1, lon1 = fit_pts[left]
        t2, lat2, lon2 = fit_pts[right]
        span = (t2 - t1).total_seconds()
        if span <= 0:
            return lat1, lon1
        ratio = (target - t1).total_seconds() / span
        return lat1 + (lat2 - lat1) * ratio, lon1 + (lon2 - lon1) * ratio

    # ``baseline_offset`` is retained for API compatibility, but absolute UTC
    # alignment deliberately starts at zero rather than file-start alignment.
    baseline_s = 0.0

    def overlap(offset_s: float) -> Optional[tuple[datetime, datetime]]:
        start = max(gpmf_first, fit_first + timedelta(seconds=offset_s))
        end = min(gpmf_last, fit_last + timedelta(seconds=offset_s))
        return (start, end) if end > start else None

    def score(offset_s: float) -> Optional[dict[str, float]]:
        # Keep one absolute-time comparison window: otherwise a candidate can
        # improve its score by moving the FIT edge over the worst part of the
        # short GPMF clip.  The window is the real overlap at offset=0.
        if not reference_gpmf:
            return None
        errors: list[float] = []
        for gdt, glat, glon in reference_gpmf:
            fit_pos = interpolate_position(gdt - timedelta(seconds=offset_s))
            if fit_pos is not None:
                errors.append(haversine_m(glat, glon, fit_pos[0], fit_pos[1]))
        coverage = len(errors) / len(reference_gpmf)
        if len(errors) < 5 or coverage < 0.25:
            return None
        ordered = sorted(errors)
        return {
            "matched": float(len(errors)),
            "coverage": coverage,
            "median": float(median(errors)),
            "p90": float(ordered[max(0, int(len(ordered) * 0.90) - 1)]),
        }

    reference_overlap = overlap(0.0)
    if reference_overlap is None:
        return None
    reference_start, reference_end = reference_overlap
    reference_gpmf = [
        point for point in gpmf_pts
        if reference_start <= point[0] <= reference_end
    ]
    if len(reference_gpmf) < 5:
        return None

    baseline_metrics = score(0.0)
    if baseline_metrics is None:
        return None

    coarse = [i * 5.0 for i in range(-24, 25)]
    if 0.0 not in coarse:
        coarse.append(0.0)
    valid_coarse = [(s, m) for s in coarse if (m := score(s)) is not None]
    if not valid_coarse:
        return None

    def rank(item: tuple[float, dict[str, float]]) -> tuple[float, float]:
        offset_s, metrics = item
        return (
            metrics["median"] + 0.25 * metrics["p90"],
            abs(offset_s - baseline_s),
        )

    best_coarse_s, _ = min(valid_coarse, key=rank)
    fine = [i * 0.1 for i in range(-50, 51)]
    fine.extend(best_coarse_s + i * 0.1 for i in range(-50, 51))
    valid_fine = [(s, m) for s in fine if (m := score(s)) is not None]
    candidates = valid_fine or valid_coarse
    refinements = [
        item for item in candidates
        if abs(item[0]) > 1e-9
        and item[1]["coverage"] >= 0.75
        and item[1]["median"] <= baseline_metrics["median"] * 0.80
    ]
    if refinements:
        best_s, metrics = min(refinements, key=rank)
    else:
        best_s, metrics = 0.0, baseline_metrics
    if metrics["median"] > 100.0 or metrics["p90"] > 250.0:
        print(
            "[SmartSync] absolute_overlap=yes "
            "WARNING: trajectory alignment rejected: "
            f"baseline=0.000s candidate={best_s:.3f}s "
            f"matched={int(metrics['matched'])}/{len(reference_gpmf)} "
            f"coverage={metrics['coverage']:.2f} "
            f"median_error={metrics['median']:.1f}m p90_error={metrics['p90']:.1f}m",
            flush=True,
        )
        return None

    offset = timedelta(seconds=best_s)
    confidence = "high" if metrics["coverage"] >= 0.5 and metrics["p90"] <= 100.0 else "medium"
    print(
        "[SmartSync] absolute_overlap=yes "
        f"baseline=0.000s candidate={offset.total_seconds():.3f}s "
        f"matched={int(metrics['matched'])}/{len(reference_gpmf)} "
        f"median_error={metrics['median']:.1f}m "
        f"p90_error={metrics['p90']:.1f}m coverage={metrics['coverage']:.2f} "
        f"confidence={confidence} method=absolute_time_trajectory_refine "
        "result=ACCEPTED",
        flush=True,
    )
    return offset

def _compute_smart_time_offset(
    records_start_ts: datetime,
    records_end_ts: datetime,
    video_start_dt: Optional[datetime],
    records: Optional[list[dict]] = None,
    gpmf_track: Optional[list[tuple[datetime, float, float]]] = None,
) -> timedelta:
    """Compute optimal timestamp offset to align FIT/GPX timestamps with video_start_dt.

    0. GPS track alignment (most reliable — GoPro clock can drift): cross-correlate
       the video GPS track with the device GPS track.
    1. Direct match: video_start_dt falls inside FIT activity range -> 0 offset.
    2. Timezone difference (e.g. FIT in local time UTC+2, video in naive/UTC) -> integer hour offset.
    3. Unsynced/independent clocks -> offset fit_start to video_start_dt.
    """
    if video_start_dt is None:
        return timedelta(0)

    # 0. GPS-track-based alignment — ground truth when both tracks are available
    vid_dt = video_start_dt.replace(tzinfo=None) if video_start_dt.tzinfo is not None else video_start_dt
    fit_start = records_start_ts.replace(tzinfo=None) if records_start_ts.tzinfo is not None else records_start_ts
    fit_end = records_end_ts.replace(tzinfo=None) if records_end_ts.tzinfo is not None else records_end_ts

    track_offset = _align_offset_by_track(records, gpmf_track)
    if track_offset is not None:
        return track_offset

    margin = timedelta(minutes=5)

    # 1. Direct match
    if (fit_start - margin) <= vid_dt <= (fit_end + margin):
        print(
            f"[SmartSync] absolute_overlap=no method=absolute_time "
            f"offset=0.000s vid_dt={vid_dt} inside [{fit_start}..{fit_end}]",
            flush=True,
        )
        return timedelta(0)

    # 2. Integer hour timezone offset match (e.g. FIT local time vs UTC)
    for tz_h in range(-14, 15):
        if tz_h == 0:
            continue
        shifted_fit_start = fit_start - timedelta(hours=tz_h)
        shifted_fit_end = fit_end - timedelta(hours=tz_h)
        if (shifted_fit_start - margin) <= vid_dt <= (shifted_fit_end + margin):
            offset = -timedelta(hours=tz_h)
            print(
                f"[SmartSync] absolute_overlap=no method=timezone_fallback "
                f"tz_h={tz_h}h offset={offset}", flush=True,
            )
            return offset

    # 3. Fallback: if video_dt does not overlap at all, align FIT start to vid_dt
    fallback_offset = vid_dt - fit_start
    print(
        f"[SmartSync] absolute_overlap=no method=align_start_fallback "
        f"offset={fallback_offset}", flush=True,
    )
    return fallback_offset


class TelemetryDataManager:
    """Manages all telemetry data loading, caching, and source-resolution.

    Holds sample data from GPMF (GoPro), GPX, and FIT sources and provides
    methods to resolve values from an explicitly requested source.
    """

    def __init__(
        self,
        extract_speed_fn: Optional[Callable] = None,
        extract_altitude_fn: Optional[Callable] = None,
        extract_track_fn: Optional[Callable] = None,
        extract_iso_fn: Optional[Callable] = None,
        extract_exposure_fn: Optional[Callable] = None,
        extract_temperature_fn: Optional[Callable] = None,
        smooth_fn: Optional[Callable] = None,
        interpolate_fn: Optional[Callable] = None,
        get_rotation_meta_fn: Optional[Callable] = None,
        get_container_rotation_fn: Optional[Callable] = None,
        find_meta_json_fn: Optional[Callable] = None,
        find_meta_json_write_fn: Optional[Callable] = None,
        load_telemetry_fn: Optional[Callable] = None,
        ensure_records_fn: Optional[Callable] = None,
        load_json_fallback_fn: Optional[Callable] = None,
        write_records_fn: Optional[Callable] = None,
        load_exiftool_fn: Optional[Callable] = None,
        extract_samples_exiftool_fn: Optional[Callable] = None,
        extract_altitude_exiftool_fn: Optional[Callable] = None,
        extract_gps_track_fn: Optional[Callable] = None,
        find_gps_anchor_fn: Optional[Callable] = None,
        smooth_values_fn: Optional[Callable] = None,
        extract_accelerometer_fn: Optional[Callable] = None,
        extract_gyroscope_fn: Optional[Callable] = None,
    ) -> None:
        # GPMF samples
        self.records: list[dict] = []
        self.speed_samples: SampleList = []
        self.alt_samples: SampleList = []
        self.track_samples: SampleList = []
        self.iso_samples: SampleList = []
        self.exposure_samples: SampleList = []
        self.temperature_samples: SampleList = []
        self.slope_samples: list[tuple[datetime, float | None]] = []
        self.accelerometer_samples: list[tuple[datetime, tuple[float, float, float]]] = []
        self.gyroscope_samples: list[tuple[datetime, tuple[float, float, float]]] = []
        self.accel_x_samples: SampleList = []
        self.accel_y_samples: SampleList = []
        self.accel_z_samples: SampleList = []
        self.accel_magnitude_samples: SampleList = []
        self.gyro_x_samples: SampleList = []
        self.gyro_y_samples: SampleList = []
        self.gyro_z_samples: SampleList = []
        self.gyro_magnitude_samples: SampleList = []
        self.accel_unit = "m/s"
        self.gyro_unit = "rad/s"

        # GPX samples (separate from GPMF for per-indicator source selection)
        self.gpx_speed_samples: SampleList = []
        self.gpx_alt_samples: SampleList = []
        self.gpx_track_samples: SampleList = []
        self.gpx_power_samples: SampleList = []
        self.gpx_atemp_samples: SampleList = []
        self.gpx_hr_samples: SampleList = []
        self.gpx_cad_samples: SampleList = []
        self.gpx_battery_samples: SampleList = []
        self.gpx_heading_samples: list[tuple[datetime, float | None]] = []
        self.gpx_slope_samples: list[tuple[datetime, float | None]] = []

        # GPS track for map rendering (lat/lon points per source)
        self.gps_track: list[tuple[datetime, float, float]] = []
        self.gpx_gps_track: list[tuple[datetime, float, float]] = []
        self.fit_gps_track: list[tuple[datetime, float, float]] = []
        self.heading_samples: list[tuple[datetime, float | None]] = []

        # FIT samples – dict-based (matches telemetry_fit.process_fit return type)
        self.fit_data: dict[str, SampleList] = {}
        self.available_fit_fields: frozenset[str] = frozenset()

        # FIT-registered extension indicator keys (fit_*_text)
        self.fit_ext_fields: list[str] = []

        # Metadata
        self.start_dt_utc: Optional[datetime] = None
        self.meta_path: Optional[Path] = None
        self.gpx_path: Optional[Path] = None  # manually selected or auto-discovered GPX
        self.fit_path: Optional[Path] = None  # manually selected or auto-discovered FIT
        self.video_path: Optional[Path] = None
        self.video_paths_to_process: list[Path] = []

        # Video info
        self.video_duration_s: float = 0.0
        self.fps: float = 30.0

        # Tool paths
        self.ffprobe_path: Any = None
        self.ffmpeg_exe: Any = None
        self.ffprobe_exe: Any = None
        self.exiftool_path: Any = None

        # Altitude cache (for preview)
        self._alt_cache: dict[str, Any] = {}

        # Smoothing window
        self.smoothing_window: int = 5

        # Function references injected by HudTunerApp
        self._extract_speed = extract_speed_fn
        self._extract_altitude = extract_altitude_fn
        self._extract_track = extract_track_fn
        self._extract_iso = extract_iso_fn
        self._extract_exposure = extract_exposure_fn
        self._extract_temperature = extract_temperature_fn
        self._smooth_fn = smooth_fn
        self._interpolate_fn = interpolate_fn
        self._get_rotation_meta = get_rotation_meta_fn
        self._get_container_rotation = get_container_rotation_fn
        self._find_meta_json = find_meta_json_fn
        self._find_meta_json_write = find_meta_json_write_fn
        self._load_telemetry = load_telemetry_fn
        self._ensure_records = ensure_records_fn
        self._load_json_fallback = load_json_fallback_fn
        self._write_records = write_records_fn
        self._load_exiftool = load_exiftool_fn
        self._extract_samples_exiftool = extract_samples_exiftool_fn
        self._extract_altitude_exiftool = extract_altitude_exiftool_fn
        self._extract_gps_track = extract_gps_track_fn
        self._find_gps_anchor = find_gps_anchor_fn
        self._smooth_values = smooth_values_fn
        self._extract_accelerometer = extract_accelerometer_fn
        self._extract_gyroscope = extract_gyroscope_fn

        # UI callbacks (set by HudTunerApp)
        self._on_telemetry_loaded: Optional[Callable[[], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_status: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_callbacks(
        self,
        on_loaded: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_telemetry_loaded = on_loaded
        self._on_error = on_error
        self._on_status = on_status

    # ------------------------------------------------------------------
    # GPMF loading (from ExifTool flat dict + records)
    # ------------------------------------------------------------------

    def load_gpmf_from_exiftool(self, video_path: Path | str, flat: Optional[dict] = None) -> None:
        """Load GPMF speed/altitude directly from ExifTool flat output.

        Jeśli *flat* jest przekazany, pomija wywołanie ExifTool (szybsze).
        W przeciwnym razie uruchamia ExifTool na *video_path*.

        This is the primary GPMF entry point used by update_telemetry_data().
        """
        if not self._load_exiftool or not video_path:
            return

        if flat is None:
            flat = self._load_exiftool(video_path)
            if not flat:
                return
        elif not flat:
            return

        # Speed from ExifTool
        if self._extract_samples_exiftool:
            raw_speed = self._extract_samples_exiftool(flat)
            if raw_speed and self._smooth_values:
                speeds = [s for _, s in raw_speed]
                smoothed = self._smooth_values(speeds, window=5)
                self.speed_samples = [
                    (raw_speed[i][0], smoothed[i])
                    for i in range(len(raw_speed))
                ]

        if self.speed_samples:
            self.start_dt_utc = self.speed_samples[0][0]

        # Altitude from ExifTool
        if self._extract_altitude_exiftool:
            raw_alt = self._extract_altitude_exiftool(flat)
            if raw_alt and self._smooth_values:
                alts = [a for _, a in raw_alt]
                smoothed_alts = self._smooth_values(alts, window=5)
                self.alt_samples = [
                    (raw_alt[i][0], smoothed_alts[i])
                    for i in range(len(raw_alt))
                ]
            else:
                self.alt_samples = raw_alt or []

    def load_gpmf_records(self, records: list[dict]) -> None:
        """Extract track, iso, exposure, temp from records (speed/alt come from exiftool flat dict)."""
        self.records = records

        # Speed and altitude should come from ExifTool flat dict (load_gpmf_from_exiftool),
        # NOT from records. Only extract them from records if not already populated.
        if not self.speed_samples and self._extract_speed:
            self.speed_samples = self._extract_speed(records)
        if not self.alt_samples and self._extract_altitude:
            self.alt_samples = self._extract_altitude(records)
        if self._extract_track:
            self.track_samples = self._extract_track(records)
        if self._extract_iso:
            self.iso_samples = self._extract_iso(records)
        if self._extract_exposure:
            self.exposure_samples = self._extract_exposure(records)
        if self._extract_temperature:
            self.temperature_samples = self._extract_temperature(records)
        if self._extract_accelerometer:
            self.accelerometer_samples = self._extract_accelerometer(records)
            self._set_vector_series(self.accelerometer_samples, "accel")
        if self._extract_gyroscope:
            self.gyroscope_samples = self._extract_gyroscope(records)
            self._set_vector_series(self.gyroscope_samples, "gyro")

        # Determine start_dt_utc
        if self._find_gps_anchor:
            anchor = self._find_gps_anchor(records)
            if anchor:
                self.start_dt_utc = anchor
        if self.start_dt_utc is None and self.speed_samples:
            self.start_dt_utc = self.speed_samples[0][0]

        # Smooth
        self.smooth_all_gpmf()

        # Heading is derived from the GPMF GPS track only.  The explicit
        # load_gps_track call also rebuilds this stream after the track is
        # available to the map path.
        if self._extract_gps_track:
            self.heading_samples = derive_heading_samples(
                self._extract_gps_track(records), self.speed_samples
            )
        self.slope_samples = derive_slope_from_streams(
            self.track_samples, self.alt_samples
        )

    def smooth_all_gpmf(self) -> None:
        """Smooth GPMF speed and altitude samples."""
        if self._smooth_fn:
            if self.speed_samples:
                self.speed_samples = self._smooth_fn(self.speed_samples, "moving_average", self.smoothing_window)
            if self.alt_samples:
                self.alt_samples = self._smooth_fn(self.alt_samples, "moving_average", self.smoothing_window)

    def _set_vector_series(self, samples: list, prefix: str) -> None:
        """Expose one timestamped vector series as scalar and magnitude series."""
        axes = [[], [], []]
        magnitude = []
        for dt, vector in samples:
            values = tuple(float(v) for v in vector)
            if len(values) != 3:
                continue
            for i, value in enumerate(values):
                axes[i].append((dt, value))
            magnitude.append((dt, sum(v * v for v in values) ** 0.5))
        setattr(self, f"{prefix}_x_samples", axes[0])
        setattr(self, f"{prefix}_y_samples", axes[1])
        setattr(self, f"{prefix}_z_samples", axes[2])
        setattr(self, f"{prefix}_magnitude_samples", magnitude)

    # ------------------------------------------------------------------
    # GPX loading
    # ------------------------------------------------------------------

    def load_gpx(
        self,
        video_path: Path | str,
        start_dt: Optional[datetime] = None,
        manual_path: Optional[Path] = None,
    ) -> bool:
        """Load and process GPX data. Returns True if data was loaded.

        Extracts GPS track (lat/lon) for map rendering alongside the
        per-field sample streams.  GPS track is stored in ``self.gpx_gps_track``.
        """
        if not _GPX_AVAILABLE:
            return False

        # Resolve GPX file path
        gpx_path: Optional[Path] = manual_path
        if gpx_path is None:
            auto_gpx = find_gpx_for_video(video_path)
            if auto_gpx:
                gpx_path = auto_gpx
        if gpx_path is None or not Path(gpx_path).is_file():
            return False

        # Parse raw GPX points (contains lat/lon for GPS track)
        points = parse_gpx(gpx_path)
        if not points:
            return False

        # Apply smart timestamp alignment (direct match, timezone offset, or start alignment)
        # Prefer GPS-track cross-correlation when both tracks are available.
        gpx_records = [
            {"timestamp": p[0], "lat": p[1], "lon": p[2]}
            for p in points
            if p[1] is not None and p[2] is not None
        ]
        gpmf_track = self.gps_track
        if not gpmf_track and self.records and self._extract_gps_track:
            gpmf_track = self._extract_gps_track(self.records)
        offset = _compute_smart_time_offset(
            points[0][0], points[-1][0], start_dt,
            records=gpx_records, gpmf_track=gpmf_track,
        )
        if offset != timedelta(0):
            points = [
                (pt[0] + offset, pt[1], pt[2], pt[3], pt[4])
                for pt in points
            ]

        # Extract GPS track (timestamp, lat, lon) for map rendering
        # GpxPoint = tuple[datetime, float, float, float, dict]
        self.gpx_gps_track = [
            (dt, lat, lon) for dt, lat, lon, _, _ in points
            if lat is not None and lon is not None
        ]

        # Synchronise to video timeline to get sample streams
        gpx_result = sync_gpx_to_video(points, start_dt)
        if gpx_result is None:
            return False

        gpx_speed, gpx_track, gpx_alt, gpx_power, gpx_atemp, gpx_hr, gpx_cad = gpx_result

        self.gpx_speed_samples = self._smooth(gpx_speed) if gpx_speed else []
        self.gpx_track_samples = gpx_track or []
        self.gpx_alt_samples = self._smooth(gpx_alt) if gpx_alt else []
        self.gpx_power_samples = gpx_power or []
        self.gpx_atemp_samples = gpx_atemp or []
        self.gpx_hr_samples = gpx_hr or []
        self.gpx_cad_samples = gpx_cad or []
        self.gpx_heading_samples = derive_heading_samples(
            self.gpx_gps_track, self.gpx_speed_samples
        )
        self.gpx_slope_samples = derive_slope_from_streams(
            self.gpx_track_samples, self.gpx_alt_samples
        )

        if self.start_dt_utc is None and gpx_speed:
            self.start_dt_utc = gpx_speed[0][0]

        print(
            f"[TelemetryManager] GPX loaded: speed={len(self.gpx_speed_samples)}, "
            f"gps_track={len(self.gpx_gps_track)} pts",
            flush=True,
        )
        return True

    # ------------------------------------------------------------------
    # FIT loading (dict-based API matching telemetry_fit)
    # ------------------------------------------------------------------

    def load_fit(
        self,
        video_path: Path | str,
        start_dt: Optional[datetime] = None,
        manual_path: Optional[Path] = None,
    ) -> bool:
        """Load and process FIT data. Returns True if data was loaded.

        Extracts GPS track (lat/lon) for map rendering alongside the
        per-field sample dict.  GPS track is stored in ``self.fit_gps_track``.
        """
        if not _FIT_AVAILABLE:
            return False

        # A new FIT load starts a new source state. Do not retain samples or
        # dynamic availability from the previously opened file if parsing or
        # alignment fails.
        self.fit_data.clear()
        self.available_fit_fields = frozenset()
        self.fit_ext_fields.clear()
        self.fit_gps_track.clear()

        # Resolve FIT file path
        fit_path: Optional[Path] = manual_path
        if fit_path is None:
            auto_fit = find_fit_for_video(video_path)
            if auto_fit:
                fit_path = auto_fit
        if fit_path is None or not Path(fit_path).is_file():
            return False

        # Parse raw FIT records (contains lat/lon for GPS track)
        records = parse_fit(fit_path)
        if not records:
            return False

        # Apply smart timestamp alignment (direct match, timezone offset, or start alignment)
        # Prefer GPS-track cross-correlation when both tracks are available.
        gpmf_track = self.gps_track
        if not gpmf_track and self.records and self._extract_gps_track:
            gpmf_track = self._extract_gps_track(self.records)
        offset = _compute_smart_time_offset(
            records[0]["timestamp"], records[-1]["timestamp"], start_dt,
            records=records, gpmf_track=gpmf_track,
        )
        if offset != timedelta(0):
            for r in records:
                r["timestamp"] = r["timestamp"] + offset

        # Extract GPS track (timestamp, lat, lon) for map rendering
        self.fit_gps_track = [
            (r["timestamp"], r["lat"], r["lon"])
            for r in records
            if r.get("lat") is not None and r.get("lon") is not None
        ]

        # Synchronise to video timeline to get per-field sample dict
        fit_result = sync_fit_to_video(records, start_dt)
        if not fit_result:
            return False

        processed_fit: dict[str, SampleList] = {}
        for key, samples in fit_result.items():
            if key in ("speed", "alt"):
                processed_fit[key] = self._smooth(samples)
            else:
                processed_fit[key] = samples
        fit_heading = derive_heading_samples(
            self.fit_gps_track, processed_fit.get("speed", [])
        )
        if fit_heading:
            processed_fit["heading"] = fit_heading
        fit_distance = processed_fit.get("track") or processed_fit.get("distance", [])
        processed_fit["slope"] = derive_slope_from_streams(
            fit_distance, processed_fit.get("alt", [])
        )
        self.fit_data = FitDataset(
            processed_fit, catalog=getattr(fit_result, "field_catalog", None)
        )
        self.available_fit_fields = self.fit_data.available_fit_fields

        if self.start_dt_utc is None and self.fit_data.get("speed"):
            self.start_dt_utc = self.fit_data["speed"][0][0]

        print(
            f"[TelemetryManager] FIT loaded: keys={list(self.fit_data.keys())}, "
            f"gps_track={len(self.fit_gps_track)} pts",
            flush=True,
        )
        return True

    # ------------------------------------------------------------------
    # Clearing
    # ------------------------------------------------------------------

    def clear_source(self, source: str) -> None:
        """Clear samples for a specific source type."""
        if source == "gpx":
            self.gpx_speed_samples.clear()
            self.gpx_alt_samples.clear()
            self.gpx_track_samples.clear()
            self.gpx_power_samples.clear()
            self.gpx_atemp_samples.clear()
            self.gpx_hr_samples.clear()
            self.gpx_cad_samples.clear()
            self.gpx_battery_samples.clear()
            self.gpx_heading_samples.clear()
            self.gpx_slope_samples.clear()
            self.gpx_gps_track.clear()
            self.gpx_path = None
        elif source == "fit":
            self.fit_data.clear()
            self.available_fit_fields = frozenset()
            self.fit_ext_fields.clear()
            self.fit_gps_track.clear()
            self.fit_path = None

    def clear_all(self) -> None:
        """Clear all telemetry data."""
        self.records.clear()
        self.speed_samples.clear()
        self.alt_samples.clear()
        self.track_samples.clear()
        self.iso_samples.clear()
        self.exposure_samples.clear()
        self.temperature_samples.clear()
        self.heading_samples.clear()
        self.slope_samples.clear()
        self.accelerometer_samples.clear()
        self.gyroscope_samples.clear()
        for name in (
            "accel_x_samples", "accel_y_samples", "accel_z_samples",
            "accel_magnitude_samples", "gyro_x_samples", "gyro_y_samples",
            "gyro_z_samples", "gyro_magnitude_samples",
        ):
            getattr(self, name).clear()
        self.clear_source("gpx")
        self.clear_source("fit")
        self.start_dt_utc = None
        self.meta_path = None
        self.video_duration_s = 0.0
        self._alt_cache.clear()

    # ------------------------------------------------------------------
    # Smoothing helper
    # ------------------------------------------------------------------

    def _smooth(self, samples: SampleList) -> SampleList:
        if self._smooth_fn and samples:
            return self._smooth_fn(samples, "moving_average", self.smoothing_window)
        return samples or []

    # ------------------------------------------------------------------
    # GPS track (for map rendering)
    # ------------------------------------------------------------------

    def load_gps_track(self, records: list[dict]) -> None:
        """Extract raw GPS lat/lon track from GPMF records for map rendering."""
        if self._extract_gps_track:
            self.gps_track = self._extract_gps_track(records)
            self.heading_samples = derive_heading_samples(
                self.gps_track, self.speed_samples
            )
        else:
            self.gps_track = []
            self.heading_samples = []

    def get_gps_track_for_source(self, source_type: str) -> list[tuple[datetime, float, float]]:
        """Return GPS track (lat/lon) for exactly the requested source."""
        if source_type == "gpx":
            return self.gpx_gps_track
        if source_type == "fit":
            return self.fit_gps_track
        if source_type == "gpmf":
            return self.gps_track
        return []

    # ------------------------------------------------------------------
    # Source resolution (per-indicator source selection)
    # ------------------------------------------------------------------

    def get_samples_for_source(self, source_type: str) -> tuple[SampleList, SampleList, SampleList]:
        """Return (speed, track, alt) for exactly *source_type*."""
        return (
            resolve_samples_from_sources("speed", source_type, gpmf=self, fit_data=self.fit_data, gpx=self),
            resolve_samples_from_sources("track", source_type, gpmf=self, fit_data=self.fit_data, gpx=self),
            resolve_samples_from_sources("alt", source_type, gpmf=self, fit_data=self.fit_data, gpx=self),
        )

    def resolve_value(
        self, field_name: str, target_dt: datetime, prefer: str = "fit",
        source: Optional[str] = None, indicator_key: Optional[str] = None,
    ) -> Optional[float]:
        """Resolve an interpolated value from one explicit source.

        ``prefer`` remains as a compatibility parameter for old external
        callers; it is treated as the requested source and never as a
        priority chain.
        """
        del indicator_key
        samples = self.resolve_samples(field_name, source or prefer)
        if not samples:
            return None
        return self._interpolate_field(samples, target_dt, field_name)

    def _interpolate_field(
        self, samples: SampleList, target_dt: datetime, field_name: str
    ) -> Optional[float]:
        """Linear interpolation for speed/distance/altitude fields, step for the rest.

        Only speed and distance (and altitude, consistent with the main alt
        indicators) are interpolated linearly so they update smoothly on every
        frame; the remaining FIT/GPX fields (HR, power, cadence, temperature,
        battery, ...) keep step interpolation (~1 s for Garmin FIT).
        """
        try:
            from src.telemetry_extract import (
                interpolate_speed, interpolate_distance, interpolate_altitude,
            )
        except ImportError:
            return self._interpolate(samples, target_dt)

        if field_name in ("speed", "enhanced_speed"):
            return interpolate_speed(samples, target_dt)
        if field_name in ("distance", "dist", "track"):
            return interpolate_distance(samples, target_dt)
        if field_name in ("alt", "enhanced_altitude", "altitude"):
            return interpolate_altitude(samples, target_dt)
        if field_name == "heading":
            return interpolate_heading(samples, target_dt)
        if field_name == "slope":
            return interpolate_slope(samples, target_dt)
        return self._interpolate(samples, target_dt)

    def resolve_samples(
        self, field_name: str, source: str = "fit",
        indicator_key: Optional[str] = None,
    ) -> SampleList:
        """Return raw samples from exactly ``source``; never cross-fallback."""
        del indicator_key
        return resolve_samples_from_sources(
            field_name, source, gpmf=self, fit_data=self.fit_data, gpx=self
        )

    def _resolve_samples(self, field_name: str, prefer: str) -> SampleList:
        """Compatibility adapter for legacy internal callers."""
        return self.resolve_samples(field_name, prefer)

    def _interpolate(self, samples: SampleList, target_dt: datetime) -> Optional[float]:
        if self._interpolate_fn:
            return self._interpolate_fn(samples, target_dt)
        try:
            from src.telemetry_extract import interpolate_value
            return interpolate_value(samples, target_dt)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Altitude cache (for preview rendering)
    # ------------------------------------------------------------------

    def get_alt_range(self, alt_source: str) -> tuple[Optional[float], Optional[float]]:
        """Return (min_alt, max_alt) for the given source, with caching."""
        if self._alt_cache.get("src") == alt_source and "min" in self._alt_cache:
            return self._alt_cache["min"], self._alt_cache["max"]

        _, _, alt_s = self.get_samples_for_source(alt_source)
        min_alt = None
        max_alt = None
        if alt_s:
            alts = [a for _, a in alt_s]
            if alts:
                min_alt = min(alts)
                max_alt = max(alts)
        self._alt_cache = {"min": min_alt, "max": max_alt, "src": alt_source}
        return min_alt, max_alt

    def invalidate_alt_cache(self) -> None:
        self._alt_cache.clear()

    # ------------------------------------------------------------------
    # FIT field registration (creates fit_*_text indicators in layout)
    # ------------------------------------------------------------------

    def register_fit_fields(
        self,
        layout: dict[str, Any],
        builtin_fields: dict[str, Any],
        get_value_schema_fn: Optional[Callable[[], list]] = None,
    ) -> list[str]:
        """Create ``fit_*_text`` indicators for every non-GPS FIT field.

        Args:
            layout: The layout dict (modified in place).
            builtin_fields: The BUILTIN_FIELDS dict (modified in place).
            get_value_schema_fn: Function returning default schema for new indicators.

        Returns:
            List of newly registered ``fit_*_text`` keys.
        """
        if not self.fit_data:
            return []

        indicators = layout.setdefault("indicators", {})
        new_keys: list[str] = []

        for field_name in sorted(self.fit_data.keys()):
            try:
                if field_name in _GPS_HANDLED:
                    continue
                key = f"fit_{field_name}_text"
                if key in indicators:
                    new_keys.append(key)
                    continue

                samples = self.fit_data[field_name]
                vals = [v for _, v in samples if v is not None]
                max_val = max(vals) if vals else 100
                min_val = min(vals) if vals else 0

                catalog = getattr(self.fit_data, "field_catalog", {}) or {}
                meta = catalog.get(field_name, {})
                label = meta.get("display_name") or field_name.replace("_", " ").title()
                unit = meta.get("unit") or ""

                indicators[key] = {
                    "enabled": False,
                    "label": label,
                    "x": 50.0, "y": 8.0, "rotation": 0,
                    "form": "text",
                    "font_size": 2.5, "size": 2.5, "thickness": 1,
                    "min_val": min_val, "max_val": max(max_val, min_val + 1),
                    "ticks": 0, "source": "fit",
                    "unit": unit,
                }
                if get_value_schema_fn:
                    builtin_fields[key] = get_value_schema_fn()

                new_keys.append(key)
            except Exception:
                continue

        return new_keys

    # ------------------------------------------------------------------
    # Auto-switch indicators to preferred source
    # ------------------------------------------------------------------

    def auto_switch_source(self, layout: dict[str, Any], source: str) -> None:
        """Switch GPS-related indicators to *source* (gpx/fit)."""
        indicators = layout.get("indicators", {})
        for ind_key in _SOURCE_SWITCH_KEYS:
            if ind_key in indicators:
                indicators[ind_key]["source"] = source

    # ------------------------------------------------------------------
    # Rotation helpers
    # ------------------------------------------------------------------

    def get_rotation_from_metadata(self) -> int:
        if self._get_rotation_meta and self.records:
            return self._get_rotation_meta(self.records)
        return 0

    def get_container_rotation(self) -> int:
        if self._get_container_rotation and self.ffprobe_exe and self.video_path:
            return self._get_container_rotation(self.ffprobe_exe, self.video_path)
        return 0

    # ------------------------------------------------------------------
    # Metadata JSON generation
    # ------------------------------------------------------------------

    def generate_meta_json(
        self,
        video_paths: Optional[list[Path]] = None,
        exiftool_path: str | Path = "exiftool",
        silent: bool = False,
    ) -> Optional[Path]:
        """Generate metadata JSON from video files using ExifTool.

        Returns the path to the generated JSON file, or None on failure.
        """
        paths = video_paths or self.video_paths_to_process
        video_path = paths[0] if paths else None
        if not video_path:
            return None

        if self._find_meta_json:
            meta_candidate = self._find_meta_json(video_path)
            if meta_candidate.exists() and meta_candidate.stat().st_size > 0:
                self.meta_path = meta_candidate
                if self._load_json_fallback:
                    raw = self._load_json_fallback(meta_candidate)
                    if self._ensure_records:
                        records = self._ensure_records(raw)
                        if records:
                            self.load_gpmf_records(records)
                            return meta_candidate

        if self._load_telemetry:
            meta_json = self._load_telemetry(video_path, exiftool_path)
            if meta_json and self._ensure_records:
                records = self._ensure_records(meta_json)
                if self._find_meta_json_write:
                    out_path = self._find_meta_json_write(video_path)
                    if out_path and self._write_records:
                        self._write_records(out_path, records)
                        self.meta_path = out_path
                        self.load_gpmf_records(records)
                        return out_path
        return None
