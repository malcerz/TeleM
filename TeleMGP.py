#!/usr/bin/env python3
"""TeleMGP – Compatibility launcher shim for BikeRideHUD.

Ta nakładka startowa zachowuje pełną wsteczną kompatybilność
z istniejącymi skryptami, testami i narzędziami wywołującymi TeleMGP.py.
Głównym kanonicznym launcherem jest BikeRideHUD.py.
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from BikeRideHUD import (  # noqa: E402, F401
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
