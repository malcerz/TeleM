"""Columnar telemetry cache and provider for HUD rendering (RenderTelemetryCache).

Provides zero-copy memory-mapped columnar access to per-frame telemetry values,
avoiding scalar Python resolver loops and massive IPC serialization across spawn.
100% data and visual parity with legacy TelemetryFrameCache.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Union

import numpy as np


@dataclass(slots=True)
class RenderTelemetryStatic:
    """Per-export (frame-independent) telemetry values and metadata."""
    max_distance_m: Optional[float] = None
    max_speed_kmh: Optional[float] = None
    min_alt: Optional[float] = None
    max_alt: Optional[float] = None
    chart_data: dict[str, list[float]] = field(default_factory=dict)
    gps_track: list[Any] = field(default_factory=list)
    start_dt_utc: Optional[datetime] = None
    fit_keys: tuple[str, ...] = ()
    fit_units: dict[str, str] = field(default_factory=dict)
    fit_labels: dict[str, str] = field(default_factory=dict)
    remaining_extra: dict[str, tuple[Any, str, str]] = field(default_factory=dict)
    dynamic_keys: tuple[str, ...] = ()
    dynamic_meta: dict[str, tuple[str, str]] = field(default_factory=dict)
    lean_keys: tuple[str, ...] = ()
    lean_units: dict[str, str] = field(default_factory=dict)
    lean_labels: dict[str, str] = field(default_factory=dict)
    std_names: tuple[str, ...] = ()
    heading_keys: tuple[str, ...] = ()
    heading_units: dict[str, str] = field(default_factory=dict)
    heading_labels: dict[str, str] = field(default_factory=dict)
    slope_keys: tuple[str, ...] = ()
    slope_units: dict[str, str] = field(default_factory=dict)
    slope_labels: dict[str, str] = field(default_factory=dict)
    auto_ranges: Optional[dict[str, tuple[float, float]]] = None
    indicator_availability: Optional[dict[str, bool]] = None

    def to_dict(self) -> dict[str, Any]:
        serialized_chart_data = {}
        for k, v in (self.chart_data or {}).items():
            if hasattr(v, "timestamps") and hasattr(v, "chart_start_dt"):
                serialized_chart_data[k] = {
                    "__chart_history__": True,
                    "values": [float(x) for x in v],
                    "timestamps": [t.isoformat() if hasattr(t, "isoformat") else str(t) for t in getattr(v, "timestamps", [])],
                    "chart_start_dt": v.chart_start_dt.isoformat() if getattr(v, "chart_start_dt", None) else None,
                    "chart_end_dt": v.chart_end_dt.isoformat() if getattr(v, "chart_end_dt", None) else None,
                    "time_scope": getattr(v, "time_scope", "activity"),
                    "window_s": getattr(v, "window_s", None),
                }
            elif isinstance(v, (list, tuple)):
                serialized_chart_data[k] = [float(x) for x in v]
            else:
                serialized_chart_data[k] = v

        serialized_gps_track = []
        for p in (self.gps_track or []):
            if isinstance(p, (list, tuple)) and len(p) >= 3:
                ts = p[0].isoformat() if hasattr(p[0], "isoformat") else p[0]
                serialized_gps_track.append([ts] + list(p[1:]))
            else:
                serialized_gps_track.append(p)

        return {
            "max_distance_m": self.max_distance_m,
            "max_speed_kmh": self.max_speed_kmh,
            "min_alt": self.min_alt,
            "max_alt": self.max_alt,
            "chart_data": serialized_chart_data,
            "gps_track": serialized_gps_track,
            "start_dt_utc": self.start_dt_utc.isoformat() if self.start_dt_utc else None,
            "fit_keys": list(self.fit_keys),
            "fit_units": self.fit_units,
            "fit_labels": self.fit_labels,
            "remaining_extra": {k: [v[0], v[1], v[2]] for k, v in self.remaining_extra.items()},
            "dynamic_keys": list(self.dynamic_keys),
            "dynamic_meta": {k: list(v) for k, v in self.dynamic_meta.items()},
            "lean_keys": list(self.lean_keys),
            "lean_units": self.lean_units,
            "lean_labels": self.lean_labels,
            "std_names": list(self.std_names),
            "heading_keys": list(self.heading_keys),
            "heading_units": self.heading_units,
            "heading_labels": self.heading_labels,
            "slope_keys": list(self.slope_keys),
            "slope_units": self.slope_units,
            "slope_labels": self.slope_labels,
            "auto_ranges": {k: list(v) for k, v in (self.auto_ranges or {}).items()},
            "indicator_availability": self.indicator_availability,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RenderTelemetryStatic":
        start_dt = None
        if d.get("start_dt_utc"):
            try:
                start_dt = datetime.fromisoformat(d["start_dt_utc"])
            except Exception:
                start_dt = None

        raw_track = d.get("gps_track", [])
        reconstructed_track = []
        for p in raw_track:
            if isinstance(p, (list, tuple)) and len(p) >= 3:
                ts = p[0]
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except Exception:
                        pass
                reconstructed_track.append(tuple([ts] + list(p[1:])))
            else:
                reconstructed_track.append(p)

        rem_extra = {}
        for k, v in d.get("remaining_extra", {}).items():
            if isinstance(v, (list, tuple)) and len(v) >= 3:
                rem_extra[k] = (v[0], str(v[1]), str(v[2]))

        dyn_meta = {}
        for k, v in d.get("dynamic_meta", {}).items():
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                dyn_meta[k] = (str(v[0]), str(v[1]))

        auto_rng = None
        if "auto_ranges" in d and d["auto_ranges"] is not None:
            auto_rng = {k: (float(v[0]), float(v[1])) for k, v in d["auto_ranges"].items() if isinstance(v, (list, tuple)) and len(v) >= 2}

        raw_cd = d.get("chart_data", {})
        reconstructed_cd = {}
        for k, v in (raw_cd or {}).items():
            if isinstance(v, dict) and v.get("__chart_history__"):
                from src.indicators.chart_builder import ChartHistory
                ts_list = [datetime.fromisoformat(t) for t in v.get("timestamps", [])]
                s_dt = datetime.fromisoformat(v["chart_start_dt"]) if v.get("chart_start_dt") else None
                e_dt = datetime.fromisoformat(v["chart_end_dt"]) if v.get("chart_end_dt") else None
                reconstructed_cd[k] = ChartHistory(
                    values=v.get("values", []),
                    timestamps=ts_list,
                    chart_start_dt=s_dt,
                    chart_end_dt=e_dt,
                    time_scope=v.get("time_scope", "activity"),
                    window_s=v.get("window_s"),
                )
            else:
                reconstructed_cd[k] = v

        return cls(
            max_distance_m=d.get("max_distance_m"),
            max_speed_kmh=d.get("max_speed_kmh"),
            min_alt=d.get("min_alt"),
            max_alt=d.get("max_alt"),
            chart_data=reconstructed_cd,
            gps_track=reconstructed_track,
            start_dt_utc=start_dt,
            fit_keys=tuple(d.get("fit_keys", ())),
            fit_units=d.get("fit_units", {}),
            fit_labels=d.get("fit_labels", {}),
            remaining_extra=rem_extra,
            dynamic_keys=tuple(d.get("dynamic_keys", ())),
            dynamic_meta=dyn_meta,
            lean_keys=tuple(d.get("lean_keys", ())),
            lean_units=d.get("lean_units", {}),
            lean_labels=d.get("lean_labels", {}),
            std_names=tuple(d.get("std_names", ())),
            heading_keys=tuple(d.get("heading_keys", ())),
            heading_units=d.get("heading_units", {}),
            heading_labels=d.get("heading_labels", {}),
            slope_keys=tuple(d.get("slope_keys", ())),
            slope_units=d.get("slope_units", {}),
            slope_labels=d.get("slope_labels", {}),
            auto_ranges=auto_rng,
            indicator_availability=d.get("indicator_availability"),
        )


class _FrameRecordSequence(Sequence):
    """Lazy sequence that allows legacy code to do len(cache.records) or cache.records[idx]."""
    __slots__ = ("_cache",)

    def __init__(self, cache: "RenderTelemetryCache") -> None:
        self._cache = cache

    def __len__(self) -> int:
        return self._cache.frames

    def __getitem__(self, idx: int) -> dict[str, Any]:
        if idx < 0 or idx >= self._cache.frames:
            raise IndexError(f"Frame index {idx} out of range [0, {self._cache.frames})")
        return self._cache.lookup(idx)


def _scalar_val(arr: Optional[np.ndarray], idx: int) -> Optional[float]:
    """Ultra-fast scalar extraction with IEEE 754 NaN check and zero allocations."""
    if arr is None or idx >= len(arr):
        return None
    v = float(arr[idx])
    return None if v != v else v


class RenderTelemetryCache:
    """Unified columnar precomputed telemetry cache for HUD rendering.
    
    Compatible drop-in replacement for TelemetryFrameCache.
    Provides instant lookup(frame_idx), disk memmap loading (<10 ms), and
    vectorized channel access (get_vector, get_scalar).
    """

    __slots__ = (
        "frames",
        "fps",
        "base_dt",
        "tz_offset_hours",
        "columns",
        "string_tables",
        "static",
        "cache_key",
        "cache_dir",
        "manifest_path",
        "is_hit",
        "build_ms",
        "memory_bytes",
        "resolver_calls",
        "interpolation_calls",
        "gpmf_lookups",
        "_records_proxy",
        "_date_cache",
        "_time_cache",
        "_sec_indices",
        "_target_dts",
        "_chart_data_clipped",
        "_dates_list",
        "_times_list",
        "_col_speed",
        "_col_dist",
        "_col_alt",
        "_col_iso",
        "_col_exp",
        "_col_temp",
        "_col_heading",
        "_col_map_heading",
        "_col_slope",
        "_col_power",
        "_col_atemp",
        "_col_hr",
        "_col_cad",
        "_col_battery",
        "_col_cur_pos",
        "_col_elapsed",
        "_col_avg_spd",
        "_col_target_ts",
        "_fit_items",
        "_dyn_items",
        "_lean_items",
        "_heading_items",
        "_slope_items",
        "_ind_items",
        "_has_window_charts",
    )

    def __init__(
        self,
        *,
        frames: int,
        fps: float,
        base_dt: datetime,
        tz_offset_hours: float,
        columns: dict[str, np.ndarray],
        string_tables: dict[str, list[str]],
        static: RenderTelemetryStatic,
        cache_key: str = "",
        cache_dir: Optional[Path] = None,
        manifest_path: Optional[Path] = None,
        is_hit: bool = False,
        build_ms: float = 0.0,
        memory_bytes: int = 0,
        resolver_calls: int = 0,
        interpolation_calls: int = 0,
        gpmf_lookups: int = 0,
    ) -> None:
        self.frames = int(frames)
        self.fps = float(fps)
        self.base_dt = base_dt
        self.tz_offset_hours = float(tz_offset_hours)
        self.columns = columns
        self.string_tables = string_tables
        self.static = static
        self.cache_key = cache_key
        self.cache_dir = cache_dir
        self.manifest_path = manifest_path
        self.is_hit = bool(is_hit)
        self.build_ms = float(build_ms)
        self.memory_bytes = int(memory_bytes)
        self.resolver_calls = int(resolver_calls)
        self.interpolation_calls = int(interpolation_calls)
        self.gpmf_lookups = int(gpmf_lookups)
        self._records_proxy = _FrameRecordSequence(self)

        self._date_cache = string_tables.get("date_cache", [])
        self._time_cache = string_tables.get("time_cache", [])
        self._sec_indices = columns.get("sec_indices")
        self._target_dts = None
        self._chart_data_clipped = {}

        self._col_speed = columns.get("speed")
        self._col_dist = columns.get("dist")
        self._col_alt = columns.get("alt")
        self._col_iso = columns.get("iso")
        self._col_exp = columns.get("exposure")
        self._col_temp = columns.get("temp")
        self._col_heading = columns.get("heading")
        self._col_map_heading = columns.get("map_heading")
        self._col_slope = columns.get("slope")
        self._col_power = columns.get("std_power")
        self._col_atemp = columns.get("std_atemp")
        self._col_hr = columns.get("std_hr")
        self._col_cad = columns.get("std_cad")
        self._col_battery = columns.get("std_battery")
        self._col_cur_pos = columns.get("current_position")
        self._col_elapsed = columns.get("elapsed_seconds")
        self._col_avg_spd = columns.get("avg_speed_kmh")
        self._col_target_ts = columns.get("target_ts")

        self._fit_items = [
            (k, columns.get(f"fit_{k}"), static.fit_units.get(k, ""), static.fit_labels.get(k, k))
            for k in static.fit_keys
        ]
        self._dyn_items = [
            (k, columns.get(f"dyn_{k}"), static.dynamic_meta.get(k, ("", k))[0], static.dynamic_meta.get(k, ("", k))[1])
            for k in static.dynamic_keys
        ]
        self._lean_items = [
            (k, columns.get(f"lean_{k}"), static.lean_units.get(k, "\u00b0"), static.lean_labels.get(k, "Lean"))
            for k in static.lean_keys
        ]
        self._heading_items = [
            (k, (k == "track_map"), static.heading_units.get(k, "deg"), static.heading_labels.get(k, "Heading"))
            for k in static.heading_keys
        ]
        self._slope_items = [
            (k, static.slope_units.get(k, "%"), static.slope_labels.get(k, "Slope"))
            for k in static.slope_keys
        ]
        ind_keys = string_tables.get("ind_keys", [])
        self._ind_items = [(k, columns.get(f"ind_{k}")) for k in ind_keys if f"ind_{k}" in columns]

        self._dates_list = string_tables.get("dates") or []
        self._times_list = string_tables.get("times") or []

        self._has_window_charts = bool(
            static.chart_data and any(
                getattr(v, "time_scope", "activity") == "window"
                for v in static.chart_data.values()
            )
        )

    @property
    def records(self) -> _FrameRecordSequence:
        """Compatibility accessor for legacy len(telemetry_cache.records) callers."""
        return self._records_proxy

    def get_vector(self, channel: str) -> Optional[np.ndarray]:
        """Return 1D numpy array for *channel* across all frames, or None."""
        return self.columns.get(channel)

    def get_scalar(self, channel: str, frame_idx: int) -> Any:
        """Return scalar value for *channel* at *frame_idx*."""
        arr = self.columns.get(channel)
        if arr is None or frame_idx < 0 or frame_idx >= self.frames:
            return None
        val = arr[frame_idx]
        if isinstance(val, (float, np.floating)):
            return None if np.isnan(val) else float(val)
        return val

    def get_slice(self, channel: str, start: int, end: int) -> Optional[np.ndarray]:
        """Return a slice of *channel* across [start:end]."""
        arr = self.columns.get(channel)
        if arr is None:
            return None
        return arr[start:end]

    def has_channel(self, channel: str) -> bool:
        """Check if *channel* is present in this cache."""
        return channel in self.columns

    def lookup(self, frame_idx: int) -> dict[str, Any]:
        """Return the exact frame_kwargs dict expected by compose_overlay.
        
        Zero scalar resolver calls; instant lookup from columnar memory.
        """
        if frame_idx < 0 or frame_idx >= self.frames:
            raise IndexError(f"Frame {frame_idx} out of range [0, {self.frames})")

        st = self.static

        # Date and time text
        if self._sec_indices is not None and frame_idx < len(self._sec_indices):
            s_idx = int(self._sec_indices[frame_idx])
            date_text = self._date_cache[s_idx] if s_idx < len(self._date_cache) else ""
            time_text = self._time_cache[s_idx] if s_idx < len(self._time_cache) else ""
        else:
            date_text = self._dates_list[frame_idx] if frame_idx < len(self._dates_list) else ""
            time_text = self._times_list[frame_idx] if frame_idx < len(self._times_list) else ""

        speed_val = _scalar_val(self._col_speed, frame_idx)
        dist_m = _scalar_val(self._col_dist, frame_idx)
        alt_val = _scalar_val(self._col_alt, frame_idx)
        iso_val = _scalar_val(self._col_iso, frame_idx)
        exp_val = _scalar_val(self._col_exp, frame_idx)
        temp_val = _scalar_val(self._col_temp, frame_idx)
        heading_val = _scalar_val(self._col_heading, frame_idx)
        map_heading_val = _scalar_val(self._col_map_heading, frame_idx)
        slope_val = _scalar_val(self._col_slope, frame_idx)

        # Standard indicators (power, atemp, hr, cad, battery)
        pwr_val = _scalar_val(self._col_power, frame_idx)
        atemp_val = _scalar_val(self._col_atemp, frame_idx)
        hr_val = _scalar_val(self._col_hr, frame_idx)
        cad_val = _scalar_val(self._col_cad, frame_idx)
        bat_val = _scalar_val(self._col_battery, frame_idx)

        cur_pos = _scalar_val(self._col_cur_pos, frame_idx)
        if cur_pos is None:
            cur_pos = frame_idx / max(1, self.frames - 1) if self.frames > 1 else 0.0

        elapsed_s = _scalar_val(self._col_elapsed, frame_idx) or 0.0
        avg_spd = _scalar_val(self._col_avg_spd, frame_idx) or 0.0

        # Target dt
        t_ts = _scalar_val(self._col_target_ts, frame_idx)
        if t_ts is not None:
            target_dt = self.base_dt + timedelta(seconds=t_ts)
        else:
            target_dt = self.base_dt + timedelta(seconds=frame_idx / self.fps if self.fps > 0 else 0.0)

        # Extra indicators
        extra_indicators: dict[str, tuple[Any, str, str]] = {}
        for k, arr, unit, label in self._fit_items:
            extra_indicators[k] = (_scalar_val(arr, frame_idx), unit, label)
        for k, arr, unit, label in self._dyn_items:
            extra_indicators[k] = (_scalar_val(arr, frame_idx), unit, label)
        for k, arr, unit, label in self._lean_items:
            extra_indicators[k] = (_scalar_val(arr, frame_idx), unit, label)
        for k, is_map, unit, label in self._heading_items:
            extra_indicators[k] = (map_heading_val if is_map else heading_val, unit, label)
        for k, unit, label in self._slope_items:
            extra_indicators[k] = (slope_val, unit, label)

        if st.remaining_extra:
            extra_indicators.update(st.remaining_extra)

        # Indicator values map
        ind_vals: dict[str, float] = {}
        for k, arr in self._ind_items:
            iv = _scalar_val(arr, frame_idx)
            if iv is not None:
                ind_vals[k] = iv

        # Chart data
        if self._has_window_charts:
            from src.indicators.chart_builder import clip_chart_data_for_target
            c_data = clip_chart_data_for_target(st.chart_data, target_dt)
        else:
            c_data = st.chart_data

        return {
            "date_text": date_text,
            "time_text": time_text,
            "speed_value": speed_val,
            "distance_m": dist_m,
            "max_distance_m": st.max_distance_m,
            "alt_value": alt_val,
            "min_alt": st.min_alt,
            "max_alt": st.max_alt,
            "iso_value": iso_val,
            "exposure_value": exp_val,
            "temp_value": temp_val,
            "indicator_values": ind_vals,
            "max_speed_kmh": st.max_speed_kmh,
            "power_value": pwr_val,
            "atemp_value": atemp_val,
            "hr_value": hr_val,
            "cad_value": cad_val,
            "battery_value": bat_val,
            "chart_data": c_data,
            "current_position": cur_pos,
            "extra_indicators": extra_indicators,
            "gps_track": st.gps_track,
            "map_heading": map_heading_val,
            "target_dt": target_dt,
            "start_dt_utc": st.start_dt_utc,
            "elapsed_seconds": elapsed_s,
            "avg_speed_kmh": avg_spd,
            "auto_ranges": st.auto_ranges,
            "indicator_availability": st.indicator_availability,
        }

    def save(self, cache_dir: Path | str) -> Path:
        """Persist cache to disk (manifest.json + individual .npy channel files for mmap)."""
        cdir = Path(cache_dir)
        cdir.mkdir(parents=True, exist_ok=True)
        ch_dir = cdir / "channels"
        ch_dir.mkdir(parents=True, exist_ok=True)

        channel_files: dict[str, str] = {}
        for col_name, arr in self.columns.items():
            if not isinstance(arr, np.ndarray):
                arr = np.array(arr)
            fn = f"{col_name}.npy"
            p = ch_dir / fn
            np.save(p, arr)
            channel_files[col_name] = f"channels/{fn}"

        # Fast single-file archive for ultra-fast single-call load
        npz_path = cdir / "columns.npz"
        try:
            np.savez(npz_path, **{k: (v if isinstance(v, np.ndarray) else np.array(v)) for k, v in self.columns.items()})
        except Exception:
            pass

        manifest = {
            "version": 2,
            "cache_key": self.cache_key,
            "frames": self.frames,
            "fps": self.fps,
            "base_dt": self.base_dt.isoformat(),
            "tz_offset_hours": self.tz_offset_hours,
            "build_ms": self.build_ms,
            "memory_bytes": self.memory_bytes,
            "resolver_calls": self.resolver_calls,
            "interpolation_calls": self.interpolation_calls,
            "gpmf_lookups": self.gpmf_lookups,
            "string_tables": self.string_tables,
            "static": self.static.to_dict(),
            "channel_files": channel_files,
            "npz_file": "columns.npz" if npz_path.exists() else None,
        }

        m_path = cdir / "manifest.json"
        with m_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        self.cache_dir = cdir
        self.manifest_path = m_path
        return m_path

    @classmethod
    def load(cls, manifest_path: Path | str, mmap: bool = True) -> "RenderTelemetryCache":
        """Load cache from manifest file via fast npz or zero-copy memory mapping."""
        m_p = Path(manifest_path)
        if not m_p.exists():
            raise FileNotFoundError(f"RenderTelemetryCache manifest not found: {m_p}")

        with m_p.open("r", encoding="utf-8") as f:
            manifest = json.load(f)

        cdir = m_p.parent
        frames = int(manifest["frames"])
        fps = float(manifest["fps"])
        base_dt = datetime.fromisoformat(manifest["base_dt"])
        tz_offset = float(manifest.get("tz_offset_hours", 2.0))
        string_tables = manifest.get("string_tables", {})
        static = RenderTelemetryStatic.from_dict(manifest.get("static", {}))
        channel_files = manifest.get("channel_files", {})
        npz_rel = manifest.get("npz_file")

        columns: dict[str, np.ndarray] = {}
        # Priority 1: If mmap is requested and channel_files are available, load each channel with mmap_mode="r"
        if mmap and channel_files:
            mmap_mode = "r"
            for col_name, rel_path in channel_files.items():
                col_path = cdir / rel_path
                if col_path.exists():
                    try:
                        columns[col_name] = np.load(col_path, mmap_mode=mmap_mode)
                    except Exception as exc:
                        print(f"[RENDER TELEM CACHE] Failed to mmap load {col_name}: {exc}", flush=True)

        # Priority 2: Fall back to npz if not mmap or channel_files failed
        if not columns and npz_rel:
            npz_p = cdir / npz_rel
            if npz_p.exists():
                try:
                    npz_data = np.load(npz_p)
                    for k in npz_data.files:
                        columns[k] = npz_data[k]
                except Exception as exc:
                    print(f"[RENDER TELEM CACHE] Failed to load npz: {exc}", flush=True)

        # Priority 3: Fall back to regular .npy load if mmap=False
        if not columns and channel_files:
            for col_name, rel_path in channel_files.items():
                col_path = cdir / rel_path
                if col_path.exists():
                    try:
                        columns[col_name] = np.load(col_path)
                    except Exception as exc:
                        print(f"[RENDER TELEM CACHE] Failed to load {col_name}: {exc}", flush=True)

        return cls(
            frames=frames,
            fps=fps,
            base_dt=base_dt,
            tz_offset_hours=tz_offset,
            columns=columns,
            string_tables=string_tables,
            static=static,
            cache_key=manifest.get("cache_key", ""),
            cache_dir=cdir,
            manifest_path=m_p,
            is_hit=True,
            build_ms=float(manifest.get("build_ms", 0.0)),
            memory_bytes=int(manifest.get("memory_bytes", 0)),
            resolver_calls=int(manifest.get("resolver_calls", 0)),
            interpolation_calls=int(manifest.get("interpolation_calls", 0)),
            gpmf_lookups=int(manifest.get("gpmf_lookups", 0)),
        )

    def stats(self) -> dict[str, Any]:
        return {
            "frames": self.frames,
            "build_ms": self.build_ms,
            "memory_bytes": self.memory_bytes,
            "memory_mib": self.memory_bytes / (1024.0 * 1024.0),
            "is_hit": self.is_hit,
            "cache_key": self.cache_key,
            "columns_count": len(self.columns),
            "resolver_calls_per_frame": self.resolver_calls / max(1, self.frames),
            "interpolation_calls_per_frame": self.interpolation_calls / max(1, self.frames),
            "gpmf_lookups_per_frame": self.gpmf_lookups / max(1, self.frames),
            "structure": "columnar-mmap-RenderTelemetryCache",
        }


class RenderTelemetryProvider:
    """Read-only columnar adapter providing channels and views to renderers."""

    def __init__(self, cache: RenderTelemetryCache) -> None:
        self._cache = cache

    @property
    def frames(self) -> int:
        return self._cache.frames

    @property
    def fps(self) -> float:
        return self._cache.fps

    @property
    def is_hit(self) -> bool:
        return self._cache.is_hit

    def get_scalar(self, channel: str, frame_idx: int) -> Any:
        return self._cache.get_scalar(channel, frame_idx)

    def get_vector(self, channel: str) -> Optional[np.ndarray]:
        return self._cache.get_vector(channel)

    def get_slice(self, channel: str, start: int, end: int) -> Optional[np.ndarray]:
        return self._cache.get_slice(channel, start, end)

    def has_channel(self, channel: str) -> bool:
        return self._cache.has_channel(channel)

    def lookup(self, frame_idx: int) -> dict[str, Any]:
        return self._cache.lookup(frame_idx)
