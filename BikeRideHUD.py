"""Canonical BikeRideHUD launcher and TeleMGP compatibility exports."""

from __future__ import annotations

import sys
from pathlib import Path

_REPOSITORY_ROOT = str(Path(__file__).resolve().parent)
while _REPOSITORY_ROOT in sys.path:
    sys.path.remove(_REPOSITORY_ROOT)
sys.path.insert(0, _REPOSITORY_ROOT)

from src.telemetry_extract import (  # noqa: E402
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    find_gps_anchor,
    flatten_record,
    get_rotation_from_metadata,
    haversine_m,
    parse_exif_datetime,
)


if __name__ == "__main__":
    from src.gui.qt.application import main

    main()
