#!/usr/bin/env python3
"""FIT (Garmin) file handling for TeleM – parsing and video timeline synchronisation.

Reads all numeric fields from FIT 'record' messages dynamically instead of
using hardcoded field names.  Every discovered scalar field becomes a sample
stream that the overlay can display.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Mapping

from src.render_logging import render_print

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
    ) -> None:
        super().__init__(records or [])
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
    ) -> None:
        super().__init__(fields or {})
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

    return FitRecords(deduped, catalog=field_metadata)


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

    catalog = getattr(records, "field_catalog", None)
    print(
        f"[FIT] Synchro: {len(result)} field(s) – { {k: len(v) for k, v in result.items()} }",
        flush=True,
    )

    return FitDataset(result, catalog=catalog)


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


def find_fit_for_video(video_path: Path | str) -> Path | None:
    """Look for a .fit file with the same base name as the video."""
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
    fits = sorted(video_path.parent.glob("*.fit")) + sorted(video_path.parent.glob("*.FIT"))
    if fits:
        print(f"[FIT] No matching FIT found, using: {fits[0]}", flush=True)
        return fits[0]
    return None


def process_fit(
    video_path: Path | str,
    video_start_dt: datetime | None = None,
) -> FitDataset | None:
    """Convenience: find FIT file, parse and synchronise in one call."""
    fit_path = find_fit_for_video(video_path)
    if fit_path is None:
        return None
    records = parse_fit(fit_path)
    if records is None:
        return None
    return sync_fit_to_video(records, video_start_dt)
