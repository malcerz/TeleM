from __future__ import annotations

import importlib
import re
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TELEMETRY_EXPORTS = (
    "ensure_records_list",
    "extract_altitude_samples",
    "extract_exposure_samples",
    "extract_iso_samples",
    "extract_speed_samples",
    "extract_temperature_samples",
    "extract_track_samples",
    "find_gps_anchor",
    "flatten_record",
    "get_rotation_from_metadata",
    "haversine_m",
    "parse_exif_datetime",
)


def test_bikeridehud_reexports_existing_telemetry_functions() -> None:
    import SportCamHUD
    import TeleMGP
    from src import telemetry_extract

    for name in TELEMETRY_EXPORTS:
        implementation = getattr(telemetry_extract, name)
        assert getattr(SportCamHUD, name) is implementation
        assert getattr(TeleMGP, name) is implementation


def test_bikeridehud_direct_entry_calls_application_main(monkeypatch) -> None:
    application = importlib.import_module("src.gui.qt.application")
    calls: list[bool] = []
    monkeypatch.setattr(application, "main", lambda: calls.append(True))

    runpy.run_path(str(ROOT / "SportCamHUD.py"), run_name="__main__")

    assert calls == [True]
    assert sys.path[0] == str(ROOT)


def test_start_cmd_is_repo_relative_and_keeps_startup_errors_visible() -> None:
    launcher = (ROOT / "Start_SportCamHUD.cmd").read_text(encoding="utf-8")

    assert 'pushd "%~dp0"' in launcher
    assert '".venv\\Scripts\\python.exe" "SportCamHUD.py" %*' in launcher
    assert 'python "SportCamHUD.py" %*' in launcher
    assert "%ERRORLEVEL%" in launcher
    assert "pause >nul" in launcher
    assert re.search(r"\b[A-Za-z]:\\", launcher) is None
