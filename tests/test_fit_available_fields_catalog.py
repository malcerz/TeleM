from datetime import datetime, timedelta

from telemetry_fit import FitDataset, FitRecords, sync_fit_to_video


def test_fit_catalog_scans_all_records_not_first_record():
    start = datetime(2026, 1, 1, 12, 0, 0)
    records = [
        {"timestamp": start, "lat": None, "lon": None, "speed": 0.0, "late_field": None},
        {"timestamp": start + timedelta(seconds=1), "lat": None, "lon": None,
         "speed": 1.0, "late_field": 42.5},
        {"timestamp": start + timedelta(seconds=2), "lat": None, "lon": None,
         "speed": 2.0, "developer_field": 7.0},
    ]

    parsed = FitRecords(records)
    assert parsed.available_fit_fields >= {"speed", "late_field", "developer_field"}
    assert parsed.field_catalog["late_field"]["samples"] == [
        (start + timedelta(seconds=1), 42.5)
    ]

    dataset = sync_fit_to_video(parsed, start)

    assert isinstance(dataset, FitDataset)
    assert dataset.available_fit_fields >= {"speed", "late_field", "developer_field"}
    assert "never_present" not in dataset.available_fit_fields

    late = dataset.catalog("late_field")
    assert late is not None
    assert late["name"] == "late_field"
    assert late["source"] == "fit"
    assert late["occurred"] is True
    assert late["samples"] == [(start + timedelta(seconds=1), 42.5)]


def test_fit_catalog_preserves_zero_as_an_occurred_value():
    start = datetime(2026, 1, 1, 12, 0, 0)
    dataset = sync_fit_to_video([
        {"timestamp": start, "lat": None, "lon": None, "developer_zero": 0.0},
    ], start)

    assert "developer_zero" in dataset.available_fit_fields
    assert dataset.catalog("developer_zero")["samples"] == [(start, 0.0)]
