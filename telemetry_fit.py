#!/usr/bin/env python3
"""FIT (Garmin) file handling for TeleM – parsing and video timeline synchronisation.

Reads all numeric fields from FIT 'record' messages dynamically instead of
using hardcoded field names.  Every discovered scalar field becomes a sample
stream that the overlay can display.
"""

from __future__ import annotations

import math
import struct
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Mapping

from src.render_logging import render_print
from src.telemetry_resolver import normalize_fit_recorded_distance

print = render_print

try:
    import fitparse
except ImportError:
    fitparse = None  # type: ignore[assignment]


# Semicircles → degrees conversion
_SEMICIRC_DEG: float = 180.0 / 2 ** 31

# Fields that are NOT telemetry data — skipped when building per-field samples.
_EXCLUDED_FIELDS: set[str] = {
    "timestamp",
    "position_lat",
    "position_long",
    "unknown_107",
    "unknown_108",
    "unknown_114",
    "unknown_115",
    "unknown_137",
    "unknown_138",
    "unknown_144",
}

RecordDict = dict[str, Any]
Sample = tuple[datetime, float]


class FitRecords(list[RecordDict]):
    """Parsed FIT records with an activity-wide, generic field catalog."""

    source = "fit"

    def __init__(
        self,
        records: list[RecordDict] | None = None,
        catalog: dict[str, dict[str, Any]] | None = None,
        active_time_mapper: Any = None,
        timezone_offset_hours: float | None = None,
        session_total_distance: float | None = None,
        lap_summaries: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(records or [])
        self.active_time_mapper = active_time_mapper
        self.timezone_offset_hours = timezone_offset_hours
        self.session_total_distance = session_total_distance
        self.lap_summaries = list(lap_summaries or [])
        if catalog is not None:
            self.field_catalog = dict(catalog)
        else:
            self.field_catalog = {}

        # Populate samples in catalog
        for record in self:
            timestamp = record.get("timestamp")
            if timestamp is None:
                continue
            for name, value in record.items():
                if name == "timestamp" or value is None:
                    continue
                if name not in self.field_catalog:
                    self.field_catalog[name] = {
                        "name": name,
                        "field_name": name,
                        "source": self.source,
                        "display_name": name.replace("_", " ").title(),
                        "unit": "",
                        "samples": [],
                        "occurred": False,
                    }
                entry = self.field_catalog[name]
                if "samples" not in entry:
                    entry["samples"] = []
                entry["samples"].append((timestamp, value))

        for field in self.field_catalog.values():
            field["occurred"] = bool(field.get("samples"))

        self.available_fit_fields = frozenset(self.field_catalog)


class FitDataset(dict[str, list[Sample]]):
    """All synchronized FIT fields plus a generic activity-wide field catalog.

    The mapping remains backward-compatible with the existing ``fit_data``
    API.  ``available_fit_fields`` and ``field_catalog`` are derived from the
    complete synchronized sample mapping, never from the first FIT record.
    """

    source = "fit"

    def __init__(
        self,
        fields: Mapping[str, list[Sample]] | None = None,
        catalog: dict[str, dict[str, Any]] | None = None,
        active_time_mapper: Any = None,
        timezone_offset_hours: float | None = None,
        session_total_distance: float | None = None,
        lap_summaries: list[dict[str, Any]] | None = None,
        distance_normalization: Any = None,
    ) -> None:
        super().__init__(fields or {})
        self.active_time_mapper = active_time_mapper
        self.timezone_offset_hours = timezone_offset_hours
        self.session_total_distance = session_total_distance
        self.lap_summaries = list(lap_summaries or [])
        self.distance_normalization = distance_normalization
        self.available_fit_fields: frozenset[str] = frozenset(
            name for name, samples in self.items() if samples
        )
        base_cat = dict(catalog) if catalog is not None else {}
        self.field_catalog: dict[str, dict[str, Any]] = {}

        for name, samples in self.items():
            meta = base_cat.get(name, {})
            self.field_catalog[name] = {
                "name": name,
                "field_name": meta.get("field_name", name),
                "source": self.source,
                "is_dev": meta.get("is_dev", False),
                "dev_data_index": meta.get("dev_data_index"),
                "field_def_num": meta.get("field_def_num"),
                "display_name": meta.get("display_name", name.replace("_", " ").title()),
                "unit": meta.get("unit", ""),
                "samples": samples,
                "occurred": bool(samples),
            }

    def catalog(self, field_name: str) -> dict[str, Any] | None:
        """Return metadata for one field, or ``None`` if it never occurred."""
        return self.field_catalog.get(field_name)


def parse_fit(fit_path: Path | str) -> FitRecords | None:
    """Parse a FIT file and return a list of record dicts.

    Each dict contains:
      - ``timestamp`` (datetime UTC, naive)
      - ``lat`` / ``lon`` (decimal degrees, or None)
      - ``alt`` (metres, from enhanced_altitude)
      - ``speed`` (km/h, converted from m/s)
      - Every other discovered scalar field with its original FIT name or unique key.

    Returns ``None`` on failure.
    """
    if fitparse is None:
        print("[FIT] fitparse library not available. Install: pip install fitparse", flush=True)
        return None

    try:
        fitfile = fitparse.FitFile(str(fit_path))
    except Exception as exc:
        print(f"[FIT] Error opening file: {exc}", flush=True)
        return None

    # 1. Discover developer field descriptions from field_description messages
    dev_field_defs: dict[tuple[int, int], dict[str, Any]] = {}
    for msg in fitfile.get_messages("field_description"):
        vals = {f.name: f.value for f in msg.fields}
        dev_idx = vals.get("developer_data_index")
        f_num = vals.get("field_definition_number")
        fname = vals.get("field_name")
        funits = vals.get("units")
        if dev_idx is not None and f_num is not None and fname:
            funits_str = str(funits) if funits else ""
            if funits_str == "watts":
                funits_str = "W"
            elif funits_str == "%d":
                funits_str = ""
            elif funits_str == "C":
                funits_str = "°C"
            dev_field_defs[(dev_idx, f_num)] = {
                "field_name": str(fname),
                "units": funits_str,
                "dev_data_index": dev_idx,
                "field_def_num": f_num,
            }

    # 2. Discover developer fields present in record messages to check for duplicate names
    name_to_dev_tuples: dict[str, set[tuple[int, int]]] = {}
    dev_key_names: dict[tuple[int, int], str] = {}
    field_metadata: dict[str, dict[str, Any]] = {}

    for msg in fitfile.get_messages("record"):
        for f in msg.fields:
            fd = getattr(f, "field_def", None)
            is_dev = isinstance(fd, fitparse.records.DevFieldDefinition)
            if is_dev:
                dev_idx = getattr(fd, "dev_data_index", None)
                def_num = getattr(fd, "def_num", None)
                if dev_idx is not None and def_num is not None:
                    raw_name = f.name or dev_field_defs.get((dev_idx, def_num), {}).get(
                        "field_name", f"dev_{dev_idx}_{def_num}"
                    )
                    name_to_dev_tuples.setdefault(raw_name, set()).add((dev_idx, def_num))

    for raw_name, dev_tuples in name_to_dev_tuples.items():
        if len(dev_tuples) > 1:
            for dev_idx, def_num in sorted(dev_tuples):
                ukey = f"{raw_name}_{dev_idx}_{def_num}"
                dev_key_names[(dev_idx, def_num)] = ukey
                units = dev_field_defs.get((dev_idx, def_num), {}).get("units", "")
                field_metadata[ukey] = {
                    "name": ukey,
                    "field_name": raw_name,
                    "source": "fit",
                    "is_dev": True,
                    "dev_data_index": dev_idx,
                    "field_def_num": def_num,
                    "display_name": f"{raw_name.replace('_', ' ').title()} [Dev {dev_idx}:{def_num}]",
                    "unit": units,
                }
        else:
            dev_idx, def_num = next(iter(dev_tuples))
            dev_key_names[(dev_idx, def_num)] = raw_name
            units = dev_field_defs.get((dev_idx, def_num), {}).get("units", "")
            field_metadata[raw_name] = {
                "name": raw_name,
                "field_name": raw_name,
                "source": "fit",
                "is_dev": True,
                "dev_data_index": dev_idx,
                "field_def_num": def_num,
                "display_name": raw_name.replace("_", " ").title(),
                "unit": units,
            }

    records: list[RecordDict] = []
    for msg in fitfile.get_messages("record"):
        timestamp = None
        lat = None
        lon = None
        alt = None
        speed_ms = None
        enhanced_ms = None

        scalar_fields: dict[str, float] = {}
        for f in msg.fields:
            fname = f.name
            fd = getattr(f, "field_def", None)
            is_dev = isinstance(fd, fitparse.records.DevFieldDefinition)
            if is_dev:
                dev_idx = getattr(fd, "dev_data_index", None)
                def_num = getattr(fd, "def_num", None)
                ukey = dev_key_names.get((dev_idx, def_num), fname)
                num = _try_float(f.value)
                if num is not None and ukey not in _EXCLUDED_FIELDS:
                    scalar_fields[ukey] = num
            else:
                if fname == "timestamp":
                    timestamp = f.value
                elif fname == "position_lat":
                    lat = f.value
                elif fname == "position_long":
                    lon = f.value
                elif fname in ("enhanced_altitude", "altitude"):
                    if alt is None:
                        alt = f.value
                    val = _try_float(f.value)
                    if val is not None and fname not in _EXCLUDED_FIELDS:
                        scalar_fields[fname] = val
                        if fname not in field_metadata:
                            units = getattr(f, "units", "") or "m"
                            disp = "Altitude (FIT)" if fname in ("altitude", "enhanced_altitude") else fname.replace("_", " ").title()
                            field_metadata[fname] = {
                                "name": fname,
                                "field_name": fname,
                                "source": "fit",
                                "is_dev": False,
                                "display_name": disp,
                                "unit": units,
                            }
                elif fname in ("enhanced_speed", "speed"):
                    if speed_ms is None:
                        speed_ms = f.value
                    val = _try_float(f.value, scale=3.6)
                    if val is not None and fname not in _EXCLUDED_FIELDS:
                        scalar_fields[fname] = val
                        if fname not in field_metadata:
                            disp = "Speed (FIT)" if fname in ("speed", "enhanced_speed") else fname.replace("_", " ").title()
                            field_metadata[fname] = {
                                "name": fname,
                                "field_name": fname,
                                "source": "fit",
                                "is_dev": False,
                                "display_name": disp,
                                "unit": "km/h",
                            }
                elif fname not in _EXCLUDED_FIELDS:
                    num = _try_float(f.value)
                    if num is not None:
                        scalar_fields[fname] = num
                        if fname not in field_metadata:
                            units = getattr(f, "units", "") or ""
                            if units == "C":
                                units = "°C"
                            field_metadata[fname] = {
                                "name": fname,
                                "field_name": fname,
                                "source": "fit",
                                "is_dev": False,
                                "display_name": fname.replace("_", " ").title(),
                                "unit": units,
                            }

        if timestamp is None:
            continue

        if isinstance(timestamp, datetime):
            dt = (
                timestamp.replace(tzinfo=timezone.utc)
                if timestamp.tzinfo is None
                else timestamp.astimezone(timezone.utc)
            )
        else:
            dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)

        rec: RecordDict = {"timestamp": dt.replace(tzinfo=None)}

        # GPS semicircles → degrees
        rec["lat"] = lat * _SEMICIRC_DEG if lat is not None else None
        rec["lon"] = lon * _SEMICIRC_DEG if lon is not None else None
        if rec["lat"] is not None and rec["lon"] is not None:
            if not (-90 <= rec["lat"] <= 90 and -180 <= rec["lon"] <= 180):
                rec["lat"] = rec["lon"] = None

        # Altitude
        rec["alt"] = _try_float(alt)

        # Speed: m/s → km/h (enhanced_speed preferred, GPS speed fallback)
        rec["speed"] = _try_float(speed_ms, scale=3.6)

        for k, v in scalar_fields.items():
            rec[k] = v

        # Alias for duplicate field names if raw name not yet set (e.g. battery_pct -> battery_pct_3_2)
        for raw_name, dev_tuples in name_to_dev_tuples.items():
            if len(dev_tuples) > 1 and raw_name not in rec:
                for dev_idx, def_num in sorted(dev_tuples, reverse=True):
                    ukey = dev_key_names.get((dev_idx, def_num))
                    if ukey in rec:
                        rec[raw_name] = rec[ukey]
                        break

        records.append(rec)

    # 3. Discover device_status (message 104 / unknown_104) messages (Garmin Edge battery voltage, level, temperature)
    GARMIN_EPOCH = datetime(1989, 12, 31, 0, 0, 0, tzinfo=timezone.utc)
    dev_status_msgs = list(fitfile.get_messages("unknown_104")) + list(fitfile.get_messages("device_status"))
    if dev_status_msgs:
        field_metadata.setdefault("garmin_battery_voltage", {
            "name": "garmin_battery_voltage",
            "field_name": "garmin_battery_voltage",
            "source": "fit",
            "is_dev": False,
            "display_name": "Garmin Battery Voltage",
            "unit": "V",
        })
        field_metadata.setdefault("garmin_battery_percent", {
            "name": "garmin_battery_percent",
            "field_name": "garmin_battery_percent",
            "source": "fit",
            "is_dev": False,
            "display_name": "Garmin Battery %",
            "unit": "%",
        })
        field_metadata.setdefault("garmin_temperature", {
            "name": "garmin_temperature",
            "field_name": "garmin_temperature",
            "source": "fit",
            "is_dev": False,
            "display_name": "Garmin Temperature",
            "unit": "°C",
        })

    for msg in dev_status_msgs:
        ts_val = None
        v_val = None
        pct_val = None
        temp_val = None

        for f in msg.fields:
            fname = str(f.name)
            fd = getattr(f, "field_def", None)
            def_num = getattr(fd, "def_num", None)

            if fname in ("timestamp", "unknown_253") or def_num == 253:
                if isinstance(f.value, datetime):
                    ts_val = f.value
                elif isinstance(f.value, (int, float)):
                    ts_val = GARMIN_EPOCH + timedelta(seconds=f.value)

            elif fname in ("battery_voltage", "voltage", "unknown_0") or def_num == 0:
                num = _try_float(f.value)
                if num is not None:
                    if num > 100.0:
                        num = num / 1000.0
                    v_val = num

            elif fname in ("battery_level", "battery_percent", "battery_pct", "battery_soc", "battery", "unknown_2") or def_num == 2:
                num = _try_float(f.value)
                if num is not None:
                    pct_val = num

            elif fname in ("temperature", "device_temperature", "unknown_3") or def_num == 3:
                num = _try_float(f.value)
                if num is not None:
                    temp_val = num

        if ts_val is not None and (v_val is not None or pct_val is not None or temp_val is not None):
            dt = (
                ts_val.replace(tzinfo=timezone.utc)
                if ts_val.tzinfo is None
                else ts_val.astimezone(timezone.utc)
            )
            rec_dt = dt.replace(tzinfo=None)
            dev_rec: RecordDict = {"timestamp": rec_dt}
            if v_val is not None:
                dev_rec["garmin_battery_voltage"] = v_val
            if pct_val is not None:
                dev_rec["garmin_battery_percent"] = pct_val
            if temp_val is not None:
                dev_rec["garmin_temperature"] = temp_val
            records.append(dev_rec)

    if not records:
        print("[FIT] No 'record' messages found in FIT file.", flush=True)
        return None

    records.sort(key=lambda r: r["timestamp"])

    # Deduplicate by timestamp
    deduped: list[RecordDict] = []
    for rec in records:
        if not deduped or rec["timestamp"] != deduped[-1]["timestamp"]:
            deduped.append(rec)
        else:
            merged = dict(deduped[-1])
            for k, v in rec.items():
                if v is not None:
                    merged[k] = v
            deduped[-1] = merged

    print(f"[FIT] Loaded {len(deduped)} points from {Path(fit_path).name}", flush=True)

    discovered: set[str] = set()
    for rec in deduped:
        for k, v in rec.items():
            if k != "timestamp" and v is not None:
                discovered.add(k)
    if discovered:
        print(f"[FIT] Fields discovered: {sorted(discovered)}", flush=True)

    # 4. Discover timer events and session to build ActiveTimeMapper (CEL 3 & CEL 4)
    active_mapper = None
    session_dict: dict[str, Any] = {}
    lap_summaries: list[dict[str, Any]] = []
    try:
        from src.telemetry_active_time import build_active_time_mapper_from_events
        events_list: list[dict[str, Any]] = []
        for msg in fitfile.get_messages("event"):
            events_list.append({f.name: f.value for f in msg.fields})
        session_msg = next(fitfile.get_messages("session"), None)
        if session_msg:
            session_dict = {f.name: f.value for f in session_msg.fields}
        for lap_msg in fitfile.get_messages("lap"):
            lap_values = {f.name: f.value for f in lap_msg.fields}
            lap_summaries.append({
                "start_time": lap_values.get("start_time"),
                "total_distance": _try_float(lap_values.get("total_distance")),
            })
        active_mapper = build_active_time_mapper_from_events(
            events_list, records=deduped, session=session_dict
        )
    except Exception as exc:
        print(f"[FIT] Warning: active_time_mapper build failed: {exc}", flush=True)

    # 5. Discover activity message for local time / timezone offset (e.g. Garmin Edge local_timestamp)
    fit_tz_offset_hours = None
    try:
        activity_msg = next(fitfile.get_messages("activity"), None)
        if activity_msg:
            vals = {f.name: f.value for f in activity_msg.fields}
            ts = vals.get("timestamp")
            lts = vals.get("local_timestamp")
            if isinstance(ts, datetime) and isinstance(lts, datetime):
                fit_tz_offset_hours = (lts - ts).total_seconds() / 3600.0
    except Exception:
        pass

    return FitRecords(
        deduped,
        catalog=field_metadata,
        active_time_mapper=active_mapper,
        timezone_offset_hours=fit_tz_offset_hours,
        session_total_distance=_try_float(session_dict.get("total_distance")),
        lap_summaries=lap_summaries,
    )


def sync_fit_to_video(
    records: list[RecordDict],
    video_start_dt: datetime | None,
) -> FitDataset:
    """Synchronise FIT records to the video timeline.

    Every numeric field becomes a key in the returned dict:
      - ``speed`` – km/h (with GPS-fallback computation)
      - ``track`` – cumulative distance in metres
      - ``alt``   – altitude in metres
      - All other discovered fields keep their original FIT name or unique key.

    Returns:
        FitDataset mapping field-name to list of (datetime, value) pairs.
    """
    if not records:
        return FitDataset()

    if video_start_dt is None:
        video_start_dt = records[0]["timestamp"]
    if video_start_dt.tzinfo is not None:
        video_start_dt = video_start_dt.replace(tzinfo=None)

    pts: list[RecordDict] = []
    for rec in records:
        r = dict(rec)
        t = r["timestamp"]
        if t.tzinfo is not None:
            r["timestamp"] = t.replace(tzinfo=None)
        pts.append(r)

    result: dict[str, list[Sample]] = {}

    # --- speed ---
    speed_samples = [
        (r["timestamp"], r["speed"]) for r in pts if r.get("speed") is not None
    ]
    if not speed_samples:
        for i in range(1, len(pts)):
            t1, lat1, lon1 = pts[i - 1]["timestamp"], pts[i - 1].get("lat"), pts[i - 1].get("lon")
            t2, lat2, lon2 = pts[i]["timestamp"], pts[i].get("lat"), pts[i].get("lon")
            if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
                continue
            dt_delta = (t2 - t1).total_seconds()
            if dt_delta <= 0:
                continue
            dist_m = _haversine(lat1, lon1, lat2, lon2)
            speed_samples.append((t2, dist_m / dt_delta * 3.6))
    if speed_samples:
        result["speed"] = speed_samples

    # --- track (cumulative distance) ---
    track: list[Sample] = []
    total_m = 0.0
    for i, rec in enumerate(pts):
        lat, lon = rec.get("lat"), rec.get("lon")
        if lat is None or lon is None:
            if track:
                track.append((rec["timestamp"], total_m))
            continue
        if i > 0:
            pl, po = pts[i - 1].get("lat"), pts[i - 1].get("lon")
            if pl is not None and po is not None:
                total_m += _haversine(pl, po, lat, lon)
        track.append((rec["timestamp"], total_m))
    if track:
        result["track"] = track

    # --- altitude ---
    alt = [(r["timestamp"], r["alt"]) for r in pts if r.get("alt") is not None]
    if alt:
        result["alt"] = alt

    # --- all other numeric fields ---
    field_keys: set[str] = set()
    for rec in pts:
        for k in rec:
            if k not in ("timestamp", "lat", "lon", "alt", "speed"):
                field_keys.add(k)

    for key in sorted(field_keys):
        samples = [(r["timestamp"], r[key]) for r in pts if r.get(key) is not None]
        if samples:
            result[key] = samples

    session_total_distance = getattr(records, "session_total_distance", None)
    distance_normalization = None
    raw_recorded_distance = result.get("distance", [])
    if raw_recorded_distance:
        canonical_distance = normalize_fit_recorded_distance(
            raw_recorded_distance,
            session_total=session_total_distance,
            emit_diagnostic=True,
        )
        if canonical_distance:
            result["distance"] = canonical_distance
            distance_normalization = canonical_distance.normalization

    catalog = getattr(records, "field_catalog", None)
    active_mapper = getattr(records, "active_time_mapper", None)
    tz_offset = getattr(records, "timezone_offset_hours", None)
    print(
        f"[FIT] Synchro: {len(result)} field(s) – { {k: len(v) for k, v in result.items()} }",
        flush=True,
    )

    return FitDataset(
        result,
        catalog=catalog,
        active_time_mapper=active_mapper,
        timezone_offset_hours=tz_offset,
        session_total_distance=session_total_distance,
        lap_summaries=getattr(records, "lap_summaries", None),
        distance_normalization=distance_normalization,
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _try_float(value: Any, scale: float = 1.0) -> float | None:
    """Safely convert a value to float, optionally scaling it."""
    if value is None:
        return None
    try:
        return float(value) * scale
    except (ValueError, TypeError):
        return None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two GPS coordinates."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


_FIT_PROBE_CACHE: dict[tuple[str, int, float], tuple[datetime, datetime, float]] = {}


def probe_fit_time_range(fit_path: Path | str) -> tuple[datetime, datetime, float] | None:
    """Read lightweight time metadata from a FIT file in milliseconds.

    Returns (start_utc, end_utc, duration_s) or None if invalid.
    """
    path = Path(fit_path)
    if not path.exists():
        return None
    try:
        st = path.stat()
        cache_key = (str(path.resolve()), st.st_size, st.st_mtime)
        if cache_key in _FIT_PROBE_CACHE:
            return _FIT_PROBE_CACHE[cache_key]
    except OSError:
        cache_key = None

    sess_start: datetime | None = None
    sess_end: datetime | None = None
    sess_elapsed: float | None = None

    # 1. Fast binary scanner (typically ~10-20ms, seeks past records)
    try:
        with open(path, "rb") as f:
            header = f.read(14)
            if len(header) >= 14 and header[8:12] == b".FIT":
                data_size = struct.unpack("<I", header[4:8])[0]
                end_pos = 14 + data_size
                defs: dict[int, tuple[int, list, int, str]] = {}
                while f.tell() < end_pos:
                    rec_hdr_b = f.read(1)
                    if not rec_hdr_b:
                        break
                    rec_hdr = rec_hdr_b[0]
                    if (rec_hdr & 0x80) != 0:
                        local_id = (rec_hdr >> 5) & 0x03
                        if local_id in defs:
                            f.seek(defs[local_id][2], 1)
                        continue
                    is_def = bool(rec_hdr & 0x40)
                    has_dev = bool(rec_hdr & 0x20)
                    local_id = rec_hdr & 0x0F
                    if is_def:
                        fixed = f.read(5)
                        if len(fixed) < 5:
                            break
                        endian = "<" if fixed[1] == 0 else ">"
                        global_num = struct.unpack(endian + "H", fixed[2:4])[0]
                        num_fields = fixed[4]
                        field_bytes = f.read(num_fields * 3)
                        fields = []
                        total_size = 0
                        for i in range(num_fields):
                            f_def_num = field_bytes[i * 3]
                            f_size = field_bytes[i * 3 + 1]
                            f_base_type = field_bytes[i * 3 + 2]
                            fields.append((f_def_num, f_size, f_base_type))
                            total_size += f_size
                        if has_dev:
                            dev_hdr = f.read(1)
                            if dev_hdr:
                                num_dev = dev_hdr[0]
                                dev_bytes = f.read(num_dev * 3)
                                for i in range(num_dev):
                                    total_size += dev_bytes[i * 3 + 1]
                        defs[local_id] = (global_num, fields, total_size, endian)
                    else:
                        if local_id not in defs:
                            break
                        global_num, fields, total_size, endian = defs[local_id]
                        if global_num in (18, 34):  # session=18, activity=34
                            data = f.read(total_size)
                            offset = 0
                            for f_num, f_sz, _ in fields:
                                raw = data[offset : offset + f_sz]
                                offset += f_sz
                                if f_num == 2 and f_sz == 4:  # start_time
                                    val = struct.unpack(endian + "I", raw)[0]
                                    if val < 0xFFFFFFFF:
                                        sess_start = datetime.fromtimestamp(val + 631065600, timezone.utc)
                                elif f_num == 253 and f_sz == 4:  # timestamp
                                    val = struct.unpack(endian + "I", raw)[0]
                                    if val < 0xFFFFFFFF:
                                        sess_end = datetime.fromtimestamp(val + 631065600, timezone.utc)
                                elif f_num == 7 and f_sz == 4:  # total_elapsed_time
                                    val = struct.unpack(endian + "I", raw)[0]
                                    if val < 0xFFFFFFFF:
                                        sess_elapsed = val / 1000.0
                        else:
                            f.seek(total_size, 1)
    except Exception:
        pass

    # 2. Fallback to fitparse if needed
    if sess_start is None and fitparse is not None:
        try:
            fit = fitparse.FitFile(path, check_crc=False)
            for msg in fit.get_messages(["session", "activity"]):
                vals = {f.name: f.value for f in msg.fields}
                if sess_start is None and vals.get("start_time"):
                    st_val = vals["start_time"]
                    if isinstance(st_val, datetime):
                        sess_start = st_val if st_val.tzinfo else st_val.replace(tzinfo=timezone.utc)
                if sess_end is None and vals.get("timestamp"):
                    ts_val = vals["timestamp"]
                    if isinstance(ts_val, datetime):
                        sess_end = ts_val if ts_val.tzinfo else ts_val.replace(tzinfo=timezone.utc)
                if sess_elapsed is None and vals.get("total_elapsed_time"):
                    sess_elapsed = float(vals["total_elapsed_time"])
                if sess_start is not None and (sess_end is not None or sess_elapsed is not None):
                    break
        except Exception:
            pass

    if sess_start is None and sess_end is None:
        return None

    if sess_start is not None:
        start_utc = sess_start
        if sess_elapsed is not None and sess_elapsed > 0:
            end_utc = start_utc + timedelta(seconds=sess_elapsed)
            dur = sess_elapsed
        elif sess_end is not None and sess_end > start_utc:
            end_utc = sess_end
            dur = (end_utc - start_utc).total_seconds()
        else:
            end_utc = sess_end or start_utc
            dur = max(0.0, (end_utc - start_utc).total_seconds())
    else:
        end_utc = sess_end  # type: ignore[assignment]
        dur = sess_elapsed or 0.0
        start_utc = end_utc - timedelta(seconds=dur)

    res = (start_utc, end_utc, dur)
    if cache_key is not None:
        _FIT_PROBE_CACHE[cache_key] = res
    return res


_FIT_TZ_CACHE: dict[tuple[str, int, float], float | None] = {}


def probe_fit_timezone_offset(fit_path: Path | str) -> float | None:
    """Fast probe of timezone offset in hours from the FIT activity message."""
    path = Path(fit_path)
    if not path.is_file():
        return None
    try:
        st = path.stat()
        cache_key = (str(path.resolve()), st.st_size, st.st_mtime)
        if cache_key in _FIT_TZ_CACHE:
            return _FIT_TZ_CACHE[cache_key]
    except Exception:
        cache_key = None

    offset_hours = None
    if fitparse is not None:
        try:
            fit = fitparse.FitFile(str(path), check_crc=False)
            for msg in fit.get_messages("activity"):
                vals = {f.name: f.value for f in msg.fields}
                ts = vals.get("timestamp")
                lts = vals.get("local_timestamp")
                if isinstance(ts, datetime) and isinstance(lts, datetime):
                    offset_hours = (lts - ts).total_seconds() / 3600.0
                    break
        except Exception:
            pass

    if cache_key is not None:
        _FIT_TZ_CACHE[cache_key] = offset_hours
    return offset_hours


def find_best_fit_match(
    mp4_intervals: list[tuple[datetime, datetime]],
    directory: Path | str,
    max_tolerance_s: float = 1800.0,
) -> tuple[Path | None, dict[str, Any]]:
    """Scan directory for matching .fit files based on UTC time overlap and start diff.

    Returns (matched_path, diagnostics_dict).
    If no match or ambiguous match (tie), matched_path is None.
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return None, {"status": "no_dir", "reason": f"Directory not found: {directory}"}

    if not mp4_intervals:
        return None, {"status": "no_intervals", "reason": "No MP4 intervals provided"}

    norm_intervals: list[tuple[datetime, datetime]] = []
    has_degraded = False
    for item in mp4_intervals:
        s = item[0]
        e = item[1] if len(item) > 1 else None
        s_utc = s if s.tzinfo is not None else s.replace(tzinfo=timezone.utc)
        if e is None:
            e = s + timedelta(seconds=600)
            has_degraded = True
        e_utc = e if e.tzinfo is not None else e.replace(tzinfo=timezone.utc)
        norm_intervals.append((s_utc, e_utc))

    mp4_earliest = min(s for s, _ in norm_intervals)
    mp4_latest = max(e for _, e in norm_intervals)
    total_mp4_duration = sum(max(0.0, (e - s).total_seconds()) for s, e in norm_intervals)

    fit_candidates = sorted(dir_path.glob("*.fit")) + sorted(dir_path.glob("*.FIT"))
    seen_paths = set()
    unique_fits = []
    for p in fit_candidates:
        can = str(p.resolve())
        if can not in seen_paths:
            seen_paths.add(can)
            unique_fits.append(p)

    if not unique_fits:
        return None, {"status": "no_fit_files", "reason": "No .fit files found in directory"}

    scored_candidates = []
    for p in unique_fits:
        probe = probe_fit_time_range(p)
        if probe is None:
            continue
        fit_start, fit_end, fit_dur = probe
        total_overlap = 0.0
        for c_start, c_end in norm_intervals:
            ov = (min(c_end, fit_end) - max(c_start, fit_start)).total_seconds()
            if ov > 0:
                total_overlap += ov

        start_diff = abs((mp4_earliest - fit_start).total_seconds())

        is_acceptable = False
        if total_overlap > 0.0:
            is_acceptable = True
        elif start_diff <= max_tolerance_s:
            if fit_start <= mp4_latest and fit_end >= mp4_earliest:
                is_acceptable = True
            elif fit_start > mp4_latest and (fit_start - mp4_latest).total_seconds() <= max_tolerance_s:
                is_acceptable = True
            elif mp4_earliest > fit_end and (mp4_earliest - fit_end).total_seconds() <= max_tolerance_s:
                is_acceptable = True

        if not is_acceptable:
            continue

        coverage = total_overlap / total_mp4_duration if total_mp4_duration > 0 else 0.0
        scored_candidates.append({
            "path": p,
            "fit_start": fit_start,
            "fit_end": fit_end,
            "fit_dur": fit_dur,
            "total_overlap": total_overlap,
            "coverage": coverage,
            "start_diff": start_diff,
        })

    if not scored_candidates:
        return None, {"status": "no_match", "reason": "No FIT candidates met tolerance"}

    scored_candidates.sort(
        key=lambda c: (c["total_overlap"], -c["start_diff"], c["coverage"]),
        reverse=True,
    )

    if len(scored_candidates) >= 2:
        top = scored_candidates[0]
        second = scored_candidates[1]
        overlap_diff = abs(top["total_overlap"] - second["total_overlap"])
        start_diff_diff = abs(top["start_diff"] - second["start_diff"])
        if overlap_diff < 1.0 and start_diff_diff < 5.0:
            print(
                f"[AutoFIT] Ambiguous match between {top['path'].name} and {second['path'].name}; leaving selection empty",
                flush=True,
            )
            return None, {
                "status": "ambiguous",
                "candidates": [top, second],
            }

    best = scored_candidates[0]
    confidence = "degraded" if has_degraded else "exact"
    diag = {
        "status": "matched",
        "fit_path": best["path"],
        "mp4_start": mp4_earliest,
        "fit_range": (best["fit_start"], best["fit_end"]),
        "overlap": best["total_overlap"],
        "start_diff": best["start_diff"],
        "coverage": best["coverage"],
        "confidence": confidence,
    }
    print(f"[AutoFIT] matched: {best['path'].name}", flush=True)
    print(f"[AutoFIT] MP4 start: {mp4_earliest.isoformat()}", flush=True)
    print(f"[AutoFIT] FIT range: {best['fit_start'].isoformat()} - {best['fit_end'].isoformat()}", flush=True)
    print(f"[AutoFIT] overlap: {best['total_overlap']:.1f}s, coverage: {best['coverage']:.3f}, confidence: {confidence}", flush=True)
    return best["path"], diag


def find_fit_for_video(video_path: Path | str, video_start_dt: datetime | None = None) -> Path | None:
    """Look for a .fit file matching the video by time or base name."""
    video_path = Path(video_path)
    stem = video_path.stem
    candidates = [
        video_path.with_suffix(".fit"),
        video_path.with_suffix(".FIT"),
        video_path.parent / (stem.lower() + ".fit"),
        video_path.parent / (stem.upper() + ".FIT"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    if video_start_dt is not None:
        try:
            from src.multifile import probe_clip_time_interval
            s, e, dur, conf = probe_clip_time_interval(video_path)
            if s is not None and e is not None:
                interval = (s, e, dur, conf)
            else:
                interval = (video_start_dt, video_start_dt + timedelta(seconds=600), 600.0, "degraded")
        except Exception:
            interval = (video_start_dt, video_start_dt + timedelta(seconds=600), 600.0, "degraded")
        matched, _ = find_best_fit_match(
            [interval],
            video_path.parent,
        )
        if matched is not None:
            return matched

    return None


def process_fit(
    video_path: Path | str,
    video_start_dt: datetime | None = None,
) -> FitDataset | None:
    """Convenience: find FIT file, parse and synchronise in one call."""
    fit_path = find_fit_for_video(video_path, video_start_dt=video_start_dt)
    if fit_path is None:
        return None
    records = parse_fit(fit_path)
    if records is None:
        return None
    return sync_fit_to_video(records, video_start_dt)
