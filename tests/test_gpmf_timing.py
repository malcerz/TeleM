"""Regression tests for real GPS9 absolute timing."""

from __future__ import annotations

import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.telemetry_gpmf_new import gpmf_to_exiftool_json, to_exiftool_json
from src.telemetry_extract import (
    extract_exposure_samples,
    extract_iso_samples,
    extract_temperature_samples,
)


GPS9_TYPE = "lllllllSS"
GPS9_SCAL = (10000000, 10000000, 1000, 1000, 100, 1, 1000, 100, 1)


def _gps9_payload(rows: list[tuple[int, ...]]) -> bytes:
    return b"".join(struct.pack(">7l2H", *row) for row in rows)


def test_gps9_days_secs_decode_to_real_utc() -> None:
    payload = _gps9_payload([
        (543655031, 186238153, 38812, 4290, 456, 9713, 17750800, 145, 3),
        (543655030, 186238150, 38820, 4290, 456, 9713, 17750900, 145, 3),
    ])

    data = to_exiftool_json(
        [("TYPE", GPS9_TYPE), ("SCAL", GPS9_SCAL), ("GPS9", payload)],
        "synthetic.mp4",
        start_dt=datetime(2026, 8, 5, 4, 28, 4, tzinfo=timezone.utc),
    )[0]

    assert data["Doc1:GPSDateTime"] == "2026:08:05 04:55:50.800"
    assert data["Doc1-1:GPSDateTime"] == "2026:08:05 04:55:50.900"
    assert data["Doc1:GPSDays"] == pytest.approx(9713.0)
    assert data["Doc1:GPSSecs"] == pytest.approx(17750.8)
    assert data["Doc1:GPSDOP"] == pytest.approx(1.45)
    assert data["Doc1:GPSFix"] == pytest.approx(3.0)


def test_gps9_invalid_time_keeps_creation_time_fallback() -> None:
    payload = _gps9_payload([
        (543655031, 186238153, 38812, 4290, 456, 9713, 86400000, 145, 3),
    ])
    fallback = datetime(2026, 8, 5, 4, 28, 4, tzinfo=timezone.utc)

    data = to_exiftool_json(
        [("TYPE", GPS9_TYPE), ("SCAL", GPS9_SCAL), ("GPS9", payload)],
        "synthetic.mp4",
        start_dt=fallback,
    )[0]

    assert data["Doc1:GPSDateTime"] == "2026:08:05 04:28:04.000"


def test_iso_and_shut_use_stream_timing_without_deduplication() -> None:
    record = {
        "Doc1:GPSDateTime": "2026:08:05 04:55:50.800",
        "Doc1:ISO": [100, 101],
        "Doc1:ISO_STMP": 1_000_000,
        "Doc1:ISO_TSMP": 0,
        "Doc1:ExposureTimes": "1/100 1/101",
        "Doc1:SHUT_STMP": 1_000_000,
        "Doc1:SHUT_TSMP": 0,
        "Doc2:GPSDateTime": "2026:08:05 04:55:51.800",
        "Doc2:ISO": [102, 103],
        "Doc2:ISO_STMP": 2_001_000,
        "Doc2:ISO_TSMP": 30,
        "Doc2:ExposureTimes": "1/102 1/103",
        "Doc2:SHUT_STMP": 2_001_000,
        "Doc2:SHUT_TSMP": 30,
    }

    iso = extract_iso_samples([record])
    shut = extract_exposure_samples([record])
    assert len(iso) == 4
    assert len(shut) == 4
    assert iso[0][0].microsecond == 800000
    assert iso[2][0].microsecond == 801000
    assert all(b[0] > a[0] for a, b in zip(iso, iso[1:]))
    assert all(b[0] > a[0] for a, b in zip(shut, shut[1:]))


def test_tmpc_uses_one_canonical_stream_sample_and_keeps_equal_values() -> None:
    record = {
        "Doc1:GPSDateTime": "2026:08:05 04:55:50.800",
        "Doc1:CameraTemperature": "30.376953125 C",
        "Doc1:TMPC_STMP": 1_000_000,
        "Doc1:TMPC_TSMP": 200101,
        "Doc1:TMPC_SourceStream": "ACCL",
        "Doc1:TMPC_ACCL_Value": 30.376953125,
        "Doc1:TMPC_GYRO_Value": 30.376953125,
        "Doc2:GPSDateTime": "2026:08:05 04:55:51.800",
        "Doc2:CameraTemperature": "30.376953125 C",
        "Doc2:TMPC_STMP": 2_001_000,
        "Doc2:TMPC_TSMP": 200300,
        "Doc2:TMPC_SourceStream": "ACCL",
        "Doc2:TMPC_ACCL_Value": 30.376953125,
        "Doc2:TMPC_GYRO_Value": 30.376953125,
    }

    samples = extract_temperature_samples([record])
    assert len(samples) == 2
    assert samples[0][1] == pytest.approx(30.376953125)
    assert samples[1][1] == pytest.approx(30.376953125)
    assert samples[1][0] > samples[0][0]


def test_tmpc_cache_fields_distinguish_accl_and_gyro() -> None:
    data = to_exiftool_json(
        [
            ("STMP", 1_000_000), ("TSMP", 200101),
            ("STNM", "Accelerometer"), ("TMPC", 30.0),
            ("STMP", 1_001_800), ("TSMP", 200102),
            ("STNM", "Gyroscope"), ("TMPC", 30.0),
        ],
        "synthetic.mp4",
    )[0]

    assert data["Doc1:TMPC_ACCL_Value"] == pytest.approx(30.0)
    assert data["Doc1:TMPC_GYRO_Value"] == pytest.approx(30.0)
    assert data["Doc1:TMPC_SourceStream"] == "ACCL"


@pytest.mark.skipif(
    not Path("Video/GX020079.mp4").exists(),
    reason="real GPMF fixture not present",
)
def test_real_gx020079_gps9_timing_and_camera_stream_counts() -> None:
    data = gpmf_to_exiftool_json("Video/GX020079.mp4")[0]
    gps_keys = [k for k in data if k.endswith(":GPSDateTime")]

    assert len(gps_keys) == 378
    assert data[gps_keys[0]] == "2026:08:05 04:55:50.800"
    assert data[gps_keys[-1]] == "2026:08:05 04:56:28.500"
    assert data["Doc1:GPSLatitude"] == pytest.approx(54.3655031)
    assert data["Doc1:GPSLongitude"] == pytest.approx(18.6238153)
    assert data["Doc38-7:GPSLatitude"] == pytest.approx(54.3642093)
    assert data["Doc38-7:GPSLongitude"] == pytest.approx(18.6235643)

    iso_count = sum(
        len(data[k])
        for k in data
        if k.endswith(":ISO") and isinstance(data[k], (list, tuple))
    )
    exposure_count = sum(
        len(str(data[k]).split())
        for k in data
        if k.endswith(":ExposureTimes")
    )
    assert iso_count == 1131
    assert exposure_count == 1131

    times = [
        datetime.strptime(data[key], "%Y:%m:%d %H:%M:%S.%f")
        for key in gps_keys
    ]
    intervals = [
        (times[i] - times[i - 1]).total_seconds()
        for i in range(1, len(times))
    ]
    assert min(intervals) == pytest.approx(0.1)
    assert max(intervals) == pytest.approx(0.1)
    assert (times[-1] - times[0]).total_seconds() == pytest.approx(37.7)
