import json
import pytest
from pathlib import Path
from datetime import datetime

from telemetry_fit import parse_fit, sync_fit_to_video
from src.gui.telemetry_manager import TelemetryDataManager
from src.gui.qt._mixins.indicator_mixin import IndicatorMixin
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    ensure_records_list, extract_gps_track,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, load_json_with_fallback,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

root = Path(__file__).resolve().parents[1]
video_path = root / "Video" / "GX010115.MP4"
json_path = root / "Video" / "GX010115.json"
fit_path = root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"


class DummyGUI(IndicatorMixin):
    def __init__(self, telemetry_mgr):
        self.telemetry = telemetry_mgr
        self.layout = {"indicators": {}}
        self._selected_stream_key = ""


@pytest.fixture(scope="module")
def loaded_telemetry():
    tm = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
        get_rotation_meta_fn=get_rotation_from_metadata,
        get_container_rotation_fn=get_container_rotation,
        find_meta_json_fn=find_metadata_json,
        find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
        load_telemetry_fn=lambda *a: None,
        ensure_records_fn=ensure_records_list,
        load_json_fallback_fn=load_json_with_fallback,
        write_records_fn=lambda p, r: None,
        extract_samples_exiftool_fn=lambda f: [],
        extract_altitude_exiftool_fn=lambda f: [],
        extract_gps_track_fn=extract_gps_track,
        find_gps_anchor_fn=lambda r: None,
        smooth_values_fn=smooth_speed_values,
        extract_accelerometer_fn=extract_accelerometer_samples,
        extract_gyroscope_fn=extract_gyroscope_samples,
    )
    with open(json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    records = ensure_records_list(meta)
    tm.load_gpmf_records(records)
    tm.load_gps_track(records)
    tm.load_fit(video_path, tm.start_dt_utc, manual_path=fit_path)
    return tm


def test_standard_fit_fields_inventory():
    """Verify all standard FIT numeric record fields are present in parser and catalog."""
    records = parse_fit(fit_path)
    assert records is not None
    assert len(records) == 4299

    expected_standard_fields = [
        "heart_rate", "cadence", "distance", "temperature",
        "enhanced_speed", "enhanced_altitude", "fractional_cadence"
    ]
    for field in expected_standard_fields:
        assert field in records.field_catalog, f"Field '{field}' missing from FitRecords.field_catalog"
        entry = records.field_catalog[field]
        assert entry["occurred"] is True
        assert len(entry["samples"]) > 0

    # Enhanced speed stats in parser
    speed_entry = records.field_catalog["enhanced_speed"]
    assert speed_entry["unit"] == "km/h"
    vals = [v for _, v in speed_entry["samples"]]
    assert len(vals) == 4293
    assert min(vals) >= 0.0
    assert max(vals) == pytest.approx(45.684, abs=0.01)  # 12.69 m/s * 3.6


def test_fit_dataset_contains_enhanced_speed_and_altitude(loaded_telemetry):
    """FitDataset must contain synchronized enhanced_speed and enhanced_altitude."""
    ds = loaded_telemetry.fit_data
    assert "enhanced_speed" in ds
    assert "enhanced_altitude" in ds
    assert len(ds["enhanced_speed"]) == 4293
    assert len(ds["enhanced_altitude"]) == 4299

    cat_speed = ds.catalog("enhanced_speed")
    assert cat_speed is not None
    assert cat_speed["source"] == "fit"
    assert cat_speed["unit"] == "km/h"


def test_gui_discovery_both_gpmf_and_fit_speed(loaded_telemetry):
    """GUI discovery must expose both GPMF speed and FIT speed with distinct keys and sources."""
    gui = DummyGUI(loaded_telemetry)
    streams = gui._discover_data_streams()
    stream_dict = {s.key: s for s in streams}

    # GPMF speed
    assert "speed_text" in stream_dict
    gpmf_speed = stream_dict["speed_text"]
    assert gpmf_speed.source == "gpmf"
    assert gpmf_speed.unit == "km/h"

    # FIT speed
    assert "fit_enhanced_speed_text" in stream_dict
    fit_speed = stream_dict["fit_enhanced_speed_text"]
    assert fit_speed.source == "fit"
    assert fit_speed.unit == "km/h"
    assert fit_speed.suggested_form == "gauge"
    assert "FIT" in fit_speed.display_name

    # FIT altitude
    assert "fit_enhanced_altitude_text" in stream_dict
    fit_alt = stream_dict["fit_enhanced_altitude_text"]
    assert fit_alt.source == "fit"
    assert fit_alt.unit == "m"


def test_create_indicator_fit_speed(loaded_telemetry):
    """Creating fit_enhanced_speed_text indicator sets source=fit and field=enhanced_speed."""
    gui = DummyGUI(loaded_telemetry)
    gui._create_indicator("fit_enhanced_speed_text")

    cfg = gui.layout["indicators"]["fit_enhanced_speed_text"]
    assert cfg["source"] == "fit"
    assert cfg["field"] == "enhanced_speed"
    assert cfg["unit"] == "km/h"
    assert cfg["form"] == "gauge"
    assert cfg["label"] == "Speed"


def test_simultaneous_gpmf_and_fit_speed_coexistence(loaded_telemetry):
    """GPMF speed and FIT speed coexist in the same layout and resolve independently."""
    layout = {
        "indicators": {
            "speed_text": {
                "source": "gpmf", "field": "speed", "form": "gauge",
                "label": "GPMF Speed", "unit": "km/h", "enabled": True
            },
            "fit_enhanced_speed_text": {
                "source": "fit", "field": "enhanced_speed", "form": "gauge",
                "label": "FIT Speed", "unit": "km/h", "enabled": True
            }
        }
    }
    # Resolve frame at target time
    t_target = loaded_telemetry.start_dt_utc
    fd = prepare_overlay_frame_data(
        target_dt=t_target,
        start_dt_utc=loaded_telemetry.start_dt_utc,
        tz_offset_hours=2.0,
        layout=layout,
        speed_samples=loaded_telemetry.speed_samples,
        track_samples=loaded_telemetry.track_samples,
        alt_samples=loaded_telemetry.alt_samples,
        iso_samples=loaded_telemetry.iso_samples,
        exposure_samples=loaded_telemetry.exposure_samples,
        temperature_samples=loaded_telemetry.temperature_samples,
        fit_data=loaded_telemetry.fit_data,
        gps_track=loaded_telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, dt, ind=None: loaded_telemetry.resolve_value(k, dt, source=src),
    )
    assert "fit_enhanced_speed_text" in fd["extra_indicators"]
    fit_val, fit_unit, fit_label = fd["extra_indicators"]["fit_enhanced_speed_text"]
    assert fit_unit == "km/h"
    assert fit_val is not None


def test_save_and_reload_fit_speed_identity(tmp_path, loaded_telemetry):
    """Layout serialization and deserialization preserves source=fit and field=enhanced_speed."""
    layout = {
        "indicators": {
            "fit_enhanced_speed_text": {
                "source": "fit", "field": "enhanced_speed", "form": "gauge",
                "label": "Speed", "unit": "km/h", "enabled": True, "size": 12.0
            }
        }
    }
    layout_file = tmp_path / "test_fit_speed_layout.json"
    with open(layout_file, "w", encoding="utf-8") as f:
        json.dump(layout, f)

    with open(layout_file, "r", encoding="utf-8") as f:
        reloaded = json.load(f)

    ind = reloaded["indicators"]["fit_enhanced_speed_text"]
    assert ind["source"] == "fit"
    assert ind["field"] == "enhanced_speed"
    assert ind["unit"] == "km/h"
    assert ind["form"] == "gauge"
