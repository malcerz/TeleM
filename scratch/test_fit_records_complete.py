import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitparse
from datetime import datetime, timezone
from typing import Any, Mapping

_SEMICIRC_DEG = 180.0 / 2 ** 31

_EXCLUDED_FIELDS = {
    "timestamp", "position_lat", "position_long",
    "unknown_107", "unknown_108", "unknown_114", "unknown_115",
    "unknown_137", "unknown_138", "unknown_144",
}

def _try_float(val, scale=1.0):
    if val is None:
        return None
    try:
        return float(val) * scale
    except (ValueError, TypeError):
        return None

def test_parse_fit(fit_path):
    fitfile = fitparse.FitFile(str(fit_path))
    
    # 1. Scan developer field descriptions
    dev_field_defs: dict[tuple[int, int], dict[str, Any]] = {}
    for msg in fitfile.get_messages("field_description"):
        vals = {f.name: f.value for f in msg.fields}
        dev_idx = vals.get("developer_data_index")
        f_num = vals.get("field_definition_number")
        fname = vals.get("field_name")
        funits = vals.get("units")
        if dev_idx is not None and f_num is not None and fname:
            dev_field_defs[(dev_idx, f_num)] = {
                "field_name": str(fname),
                "units": str(funits) if funits else "",
                "dev_data_index": dev_idx,
                "field_def_num": f_num,
            }
            
    # 2. First pass: count field occurrences in record messages
    dev_key_names: dict[tuple[int, int], str] = {}
    name_to_dev_tuples: dict[str, set[tuple[int, int]]] = {}
    
    for msg in fitfile.get_messages("record"):
        for f in msg.fields:
            fd = getattr(f, "field_def", None)
            is_dev = isinstance(fd, fitparse.records.DevFieldDefinition)
            if is_dev:
                dev_idx = getattr(fd, "dev_data_index", None)
                def_num = getattr(fd, "def_num", None)
                if dev_idx is not None and def_num is not None:
                    raw_name = f.name or dev_field_defs.get((dev_idx, def_num), {}).get("field_name", f"dev_{dev_idx}_{def_num}")
                    name_to_dev_tuples.setdefault(raw_name, set()).add((dev_idx, def_num))

    # Resolve unique keys for developer fields
    field_metadata: dict[str, dict[str, Any]] = {}
    
    for raw_name, dev_tuples in name_to_dev_tuples.items():
        if len(dev_tuples) > 1:
            for (dev_idx, def_num) in sorted(dev_tuples):
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
            (dev_idx, def_num) = next(iter(dev_tuples))
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

    # 3. Parse records
    records = []
    for msg in fitfile.get_messages("record"):
        timestamp = None
        lat = None
        lon = None
        alt = None
        speed_ms = None
        enhanced_ms = None
        
        scalar_fields = {}
        for f in msg.fields:
            fname = f.name
            fd = getattr(f, "field_def", None)
            is_dev = isinstance(fd, fitparse.records.DevFieldDefinition)
            if is_dev:
                dev_idx = getattr(fd, "dev_data_index", None)
                def_num = getattr(fd, "def_num", None)
                ukey = dev_key_names.get((dev_idx, def_num), fname)
                num = _try_float(f.value)
                if num is not None:
                    scalar_fields[ukey] = num
            else:
                if fname == "timestamp":
                    timestamp = f.value
                elif fname == "position_lat":
                    lat = f.value
                elif fname == "position_long":
                    lon = f.value
                elif fname in ("enhanced_altitude", "altitude") and alt is None:
                    alt = f.value
                elif fname in ("enhanced_speed", "speed") and speed_ms is None:
                    speed_ms = f.value
                elif fname == "enhanced_speed":
                    enhanced_ms = f.value
                elif fname not in _EXCLUDED_FIELDS:
                    num = _try_float(f.value)
                    if num is not None:
                        scalar_fields[fname] = num
                        if fname not in field_metadata:
                            units = getattr(f, "units", "") or ""
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
            dt = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
        else:
            dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
            
        rec = {"timestamp": dt.replace(tzinfo=None)}
        rec["lat"] = lat * _SEMICIRC_DEG if lat is not None else None
        rec["lon"] = lon * _SEMICIRC_DEG if lon is not None else None
        if rec["lat"] is not None and rec["lon"] is not None:
            if not (-90 <= rec["lat"] <= 90 and -180 <= rec["lon"] <= 180):
                rec["lat"] = rec["lon"] = None
        rec["alt"] = _try_float(alt)
        rec["speed"] = _try_float(speed_ms, scale=3.6)
        if enhanced_ms is not None:
            rec["enhanced_speed"] = _try_float(enhanced_ms, scale=3.6)
            
        for k, v in scalar_fields.items():
            rec[k] = v
            
        # Backward compatibility alias for duplicates if raw_name not directly set
        for raw_name, dev_tuples in name_to_dev_tuples.items():
            if len(dev_tuples) > 1 and raw_name not in rec:
                # pick the developer field with largest definition index or first present
                for (dev_idx, def_num) in sorted(dev_tuples, reverse=True):
                    ukey = dev_key_names.get((dev_idx, def_num))
                    if ukey in rec:
                        rec[raw_name] = rec[ukey]
                        break
        records.append(rec)
    return records, field_metadata

recs, meta = test_parse_fit("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
print(f"Loaded {len(recs)} records.")
print("\nDiscovered metadata fields in catalog:")
for k, v in sorted(meta.items()):
    print(f"  {k:20}: display='{v['display_name']}', unit='{v['unit']}', is_dev={v.get('is_dev')}")
