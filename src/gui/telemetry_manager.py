"""Telemetry data manager – loads, caches and resolves telemetry data from
GPMF (ExifTool), GPX and FIT sources."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

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
        find_fit_for_video,
        parse_fit,
        process_fit,
        sync_fit_to_video,
    )
    _FIT_AVAILABLE = True
except ImportError:
    _FIT_AVAILABLE = False

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
_GPS_HANDLED: set[str] = {"speed", "alt", "track", "lat", "lon", "timestamp"}

# GPMF-native field names that resolve to GPMF samples directly
_GPMF_NATIVE: set[str] = {"speed", "alt", "dist", "track", "iso", "exposure", "temperature"}

# GPX-to-source indicators that get auto-switched
_SOURCE_SWITCH_KEYS: tuple[str, ...] = (
    "speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text",
)


class TelemetryDataManager:
    """Manages all telemetry data loading, caching, and source-resolution.

    Holds sample data from GPMF (GoPro), GPX, and FIT sources and provides
    methods to resolve values with configurable priority (FIT > GPX > GPMF).
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
    ) -> None:
        # GPMF samples
        self.records: list[dict] = []
        self.speed_samples: SampleList = []
        self.alt_samples: SampleList = []
        self.track_samples: SampleList = []
        self.iso_samples: SampleList = []
        self.exposure_samples: SampleList = []
        self.temperature_samples: SampleList = []

        # GPX samples (separate from GPMF for per-indicator source selection)
        self.gpx_speed_samples: SampleList = []
        self.gpx_alt_samples: SampleList = []
        self.gpx_track_samples: SampleList = []
        self.gpx_power_samples: SampleList = []
        self.gpx_atemp_samples: SampleList = []
        self.gpx_hr_samples: SampleList = []
        self.gpx_cad_samples: SampleList = []

        # GPS track for map rendering (lat/lon points per source)
        self.gps_track: list[tuple[datetime, float, float]] = []
        self.gpx_gps_track: list[tuple[datetime, float, float]] = []
        self.fit_gps_track: list[tuple[datetime, float, float]] = []

        # FIT samples – dict-based (matches telemetry_fit.process_fit return type)
        self.fit_data: dict[str, SampleList] = {}

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

        # Determine start_dt_utc
        if self._find_gps_anchor:
            anchor = self._find_gps_anchor(records)
            if anchor:
                self.start_dt_utc = anchor
        if self.start_dt_utc is None and self.speed_samples:
            self.start_dt_utc = self.speed_samples[0][0]

        # Smooth
        self.smooth_all_gpmf()

    def smooth_all_gpmf(self) -> None:
        """Smooth GPMF speed and altitude samples."""
        if self._smooth_fn:
            if self.speed_samples:
                self.speed_samples = self._smooth_fn(self.speed_samples, "moving_average", self.smoothing_window)
            if self.alt_samples:
                self.alt_samples = self._smooth_fn(self.alt_samples, "moving_average", self.smoothing_window)

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

        # Extract GPS track (timestamp, lat, lon) for map rendering
        # — synchronize timestamps to video start so they match start_dt_utc
        if start_dt is not None and records:
            # FIT timestamps są naive UTC (parse_fit zdejmuje timezone),
            # start_dt może być aware UTC. Sprowadź do naive UTC.
            first_ts = records[0]["timestamp"]
            if start_dt.tzinfo is not None:
                start_dt_naive = start_dt.replace(tzinfo=None)
            else:
                start_dt_naive = start_dt
            offset = start_dt_naive - first_ts
            self.fit_gps_track = [
                (r["timestamp"] + offset, r["lat"], r["lon"])
                for r in records
                if r.get("lat") is not None and r.get("lon") is not None
            ]
        elif records:
            self.fit_gps_track = [
                (r["timestamp"], r["lat"], r["lon"])
                for r in records
                if r.get("lat") is not None and r.get("lon") is not None
            ]

        # Synchronise to video timeline to get per-field sample dict
        fit_result = sync_fit_to_video(records, start_dt)
        if not fit_result:
            return False

        # Przesuń timestampy fit_data o ten sam offset co fit_gps_track
        # (sync_fit_to_video zwraca surowe czasy FIT bez przesunięcia)
        if start_dt is not None and records:
            first_ts = records[0]["timestamp"]
            if start_dt.tzinfo is not None:
                start_dt_naive = start_dt.replace(tzinfo=None)
            else:
                start_dt_naive = start_dt
            offset = start_dt_naive - first_ts
            shifted: dict[str, list[tuple[datetime, float]]] = {}
            for key, samples in fit_result.items():
                shifted[key] = [(ts + offset, v) for ts, v in samples]
            fit_result = shifted

        self.fit_data = {}
        for key, samples in fit_result.items():
            if key in ("speed", "alt"):
                self.fit_data[key] = self._smooth(samples)
            else:
                self.fit_data[key] = samples

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
            self.gpx_gps_track.clear()
            self.gpx_path = None
        elif source == "fit":
            self.fit_data.clear()
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

    def get_gps_track_for_source(self, source_type: str) -> list[tuple[datetime, float, float]]:
        """Return GPS track (lat/lon) for the given source, falling back to GPMF."""
        if source_type == "gpx":
            return self.gpx_gps_track or self.gps_track
        if source_type == "fit":
            return self.fit_gps_track or self.gps_track
        return self.gps_track

    # ------------------------------------------------------------------
    # Source resolution (per-indicator source selection)
    # ------------------------------------------------------------------

    def get_samples_for_source(self, source_type: str) -> tuple[SampleList, SampleList, SampleList]:
        """Return (speed, track, alt) for *source_type*, falling back to GPMF."""
        if source_type == "gpx":
            return (
                self.gpx_speed_samples or self.speed_samples,
                self.gpx_track_samples or self.track_samples,
                self.gpx_alt_samples or self.alt_samples,
            )
        if source_type == "fit":
            return (
                self.fit_data.get("speed") or self.speed_samples,
                self.fit_data.get("track") or self.track_samples,
                self.fit_data.get("alt") or self.alt_samples,
            )
        return (self.speed_samples, self.track_samples, self.alt_samples)

    def resolve_value(
        self, field_name: str, target_dt: datetime, prefer: str = "fit"
    ) -> Optional[float]:
        """Interpolated value with FIT > GPX > GPMF priority."""
        samples = self._resolve_samples(field_name, prefer)
        if not samples:
            return None
        return self._interpolate(samples, target_dt)

    def resolve_samples(self, field_name: str, prefer: str = "fit") -> SampleList:
        """Raw sample list with FIT > GPX > GPMF priority."""
        return self._resolve_samples(field_name, prefer)

    def _resolve_samples(self, field_name: str, prefer: str) -> SampleList:
        """Internal resolver with priority: prefer > alt source > GPMF fallback."""
        alt_prefix = "gpx" if prefer == "fit" else "fit"

        # Preferred source
        if prefer == "fit":
            pref = self.fit_data.get(field_name, [])
        else:
            pref = getattr(self, f"gpx_{field_name}_samples", []) or []

        # Alternative source
        if alt_prefix == "fit":
            alt = self.fit_data.get(field_name, [])
        else:
            alt = getattr(self, f"gpx_{field_name}_samples", []) or []

        samples: SampleList = pref or alt

        # FIT field-name fallback (e.g. "power" -> "curVpower")
        if not samples and prefer == "fit":
            for alias in _FIT_LOOKUP.get(field_name, ()):
                samples = self.fit_data.get(alias, [])
                if samples:
                    break

        # GPMF fallback
        if not samples and field_name in _GPMF_NATIVE:
            gpmf_attr = "track_samples" if field_name in ("dist", "track") else f"{field_name}_samples"
            samples = getattr(self, gpmf_attr, []) or []

        return samples

    def _interpolate(self, samples: SampleList, target_dt: datetime) -> Optional[float]:
        if self._interpolate_fn:
            return self._interpolate_fn(samples, target_dt)
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

                indicators[key] = {
                    "enabled": False,
                    "label": field_name.replace("_", " ").title(),
                    "x": 0.5, "y": 0.08, "rotation": 0,
                    "form": "text",
                    "font_size": 0.018, "size": 0.1, "thickness": 0.001,
                    "min_val": min_val, "max_val": max(max_val, min_val + 1),
                    "ticks": 0, "source": "fit",
                    "unit": "",
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
