"""Tests for FIT field registration into the Extension listbox.

Tests the ``_register_fit_fields`` and ``_rebuild_ext_list`` methods of
``HudTunerApp`` without requiring a full Tkinter GUI — uses a minimal
test double / partial mock.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

# Module-level symbols that _register_fit_fields depends on
from src.gui.hud_tuner_app import BUILTIN_FIELDS, get_value_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EPOCH = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)


def _sample(
    dt: datetime | None = None,
    val: float = 50.0,
) -> tuple[datetime, float]:
    return (dt or _EPOCH, val)


def _samples(*vals: float) -> list[tuple[datetime, float]]:
    """Create a list of (timestamp, value) pairs."""
    return [(_EPOCH, v) for v in vals]


# ---------------------------------------------------------------------------
# Test double for HudTunerApp (only the parts _register_fit_fields touches)
# ---------------------------------------------------------------------------


class FitRegistrationStub:
    """Minimal stand-in for HudTunerApp exercising ``_register_fit_fields``.

    Only implements the attributes and methods that
    ``_register_fit_fields`` and ``_rebuild_ext_list`` access.
    """

    def __init__(self) -> None:
        self.fit_data: dict[str, list[tuple[datetime, float]]] = {}
        self.fit_ext_fields: list[str] = []
        self.layout: dict[str, Any] = {
            "indicators": {},
        }
        # Mock Tkinter Listbox – record calls for assertions
        self.ext_list = MagicMock()

    # --- Methods under test (bound to the stub) ---

    # We import the real functions and bind them to the stub
    _register_fit_fields = None  # set in fixture
    _rebuild_ext_list = None  # set in fixture


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stub():
    """Provide a clean ``FitRegistrationStub`` per test."""
    # Import here so we can bind the real methods
    from src.gui.hud_tuner_app import HudTunerApp

    s = FitRegistrationStub()
    # Bind the real methods to our stub
    s._register_fit_fields = HudTunerApp._register_fit_fields.__get__(s, FitRegistrationStub)  # type: ignore[attr-defined]
    s._rebuild_ext_list = HudTunerApp._rebuild_ext_list.__get__(s, FitRegistrationStub)  # type: ignore[attr-defined]
    return s


# ---------------------------------------------------------------------------
# Tests for _register_fit_fields
# ---------------------------------------------------------------------------


class TestRegisterFitFields:
    """Tests for the ``_register_fit_fields`` method."""

    def test_empty_fit_data_does_nothing(self, stub: FitRegistrationStub) -> None:
        """With empty fit_data, no indicators should be added."""
        stub.fit_data = {}
        stub._register_fit_fields()
        assert stub.layout["indicators"] == {}
        assert stub.fit_ext_fields == []
        stub.ext_list.delete.assert_not_called()

    def test_only_gps_fields_skipped(self, stub: FitRegistrationStub) -> None:
        """GPS fields (speed/alt/track/lat/lon/timestamp) should be skipped."""
        stub.fit_data = {
            "speed": _samples(30.0),
            "alt": _samples(100.0),
            "track": _samples(5000.0),
            "lat": _samples(52.0),
            "lon": _samples(21.0),
            "timestamp": _samples(1.0),
        }
        stub._register_fit_fields()
        # All GPS → nothing registered
        assert stub.layout["indicators"] == {}
        assert stub.fit_ext_fields == []

    def test_single_fit_field_registered(self, stub: FitRegistrationStub) -> None:
        """A single non-GPS field should produce one fit_*_text indicator."""
        stub.fit_data = {"heart_rate": _samples(72, 85, 90)}
        stub._register_fit_fields()

        key = "fit_heart_rate_text"
        assert key in stub.layout["indicators"]
        assert key in BUILTIN_FIELDS
        assert stub.fit_ext_fields == [key]

        cfg = stub.layout["indicators"][key]
        assert cfg["enabled"] is True
        assert cfg["source"] == "fit"
        assert cfg["form"] == "text"
        assert cfg["min_val"] == 72
        assert cfg["max_val"] >= 90
        # label auto-generated from field name
        assert "Heart Rate" in cfg["label"] or "Heart Rate" == cfg["label"]

    def test_multiple_fields(self, stub: FitRegistrationStub) -> None:
        """Multiple non-GPS fields each get their own indicator."""
        stub.fit_data = {
            "heart_rate": _samples(72),
            "cadence": _samples(85),
            "temperature": _samples(30),
        }
        stub._register_fit_fields()

        expected_keys = {
            "fit_heart_rate_text",
            "fit_cadence_text",
            "fit_temperature_text",
        }
        assert expected_keys.issubset(stub.layout["indicators"].keys())
        assert set(stub.fit_ext_fields) == expected_keys

        for key in expected_keys:
            assert key in BUILTIN_FIELDS

    def test_gps_fields_excluded_from_extension(self, stub: FitRegistrationStub) -> None:
        """GPS fields should not produce extension indicators even when mixed."""
        stub.fit_data = {
            "speed": _samples(30.0),
            "heart_rate": _samples(72),
            "alt": _samples(100.0),
            "temperature": _samples(30),
        }
        stub._register_fit_fields()

        registered = set(stub.fit_ext_fields)
        assert "fit_heart_rate_text" in registered
        assert "fit_temperature_text" in registered
        assert "fit_speed_text" not in registered
        assert "fit_alt_text" not in registered

    def test_duplicate_keys_skipped(self, stub: FitRegistrationStub) -> None:
        """If an indicator already exists in layout, it should be added to fit_ext_fields
        but the existing config should not be overwritten."""
        stub.fit_data = {"heart_rate": _samples(72)}
        # Manually pre-add the key and clear any stale entry
        stub.layout["indicators"]["fit_heart_rate_text"] = {"existing": True}
        stub._register_fit_fields()

        # The existing config should not have been overwritten
        assert stub.layout["indicators"]["fit_heart_rate_text"] == {"existing": True}
        # Key is still added to fit_ext_fields so the Extension list shows it
        assert stub.fit_ext_fields == ["fit_heart_rate_text"]

    def test_realistic_fit_fields(self, stub: FitRegistrationStub) -> None:
        """Test with fields matching a real FIT file (Morning_Ride.fit)."""
        stub.fit_data = {
            "K1": _samples(0.0),
            "K2": _samples(0.0),
            "cadence": _samples(85),
            "curVpower": _samples(150),
            "distance": _samples(1000),
            "enhanced_altitude": _samples(120),
            "enhanced_speed": _samples(30),
            "fractional_cadence": _samples(85.5),
            "gopro_battery": _samples(90),
            "heart_rate": _samples(140),
            "passing_speed": _samples(25),
            "passing_speedabs": _samples(25),
            "radar_current": _samples(1),
            "temperature": _samples(28),
        }
        stub._register_fit_fields()

        # GPS fields are NOT in fit_data above, so all fields should register
        expected = {
            "fit_K1_text",
            "fit_K2_text",
            "fit_cadence_text",
            "fit_curVpower_text",
            "fit_distance_text",
            "fit_enhanced_altitude_text",
            "fit_enhanced_speed_text",
            "fit_fractional_cadence_text",
            "fit_gopro_battery_text",
            "fit_heart_rate_text",
            "fit_passing_speed_text",
            "fit_passing_speedabs_text",
            "fit_radar_current_text",
            "fit_temperature_text",
        }
        assert expected.issubset(stub.layout["indicators"].keys())
        assert set(stub.fit_ext_fields) == expected
        # All should be in BUILTIN_FIELDS
        for key in expected:
            assert key in BUILTIN_FIELDS

    def test_none_values_filtered(self, stub: FitRegistrationStub) -> None:
        """Samples where value is None should be filtered out before min/max."""
        stub.fit_data = {
            "heart_rate": [
                (_EPOCH, 72.0),
                (_EPOCH, None),  # should be ignored
                (_EPOCH, 90.0),
            ],
        }
        stub._register_fit_fields()
        cfg = stub.layout["indicators"]["fit_heart_rate_text"]
        assert cfg["min_val"] == 72.0
        assert cfg["max_val"] >= 90.0

    def test_all_none_values_use_defaults(self, stub: FitRegistrationStub) -> None:
        """If all values are None, min=0 and max=100 should be used."""
        stub.fit_data = {
            "heart_rate": [
                (_EPOCH, None),
                (_EPOCH, None),
            ],
        }
        stub._register_fit_fields()
        cfg = stub.layout["indicators"]["fit_heart_rate_text"]
        assert cfg["min_val"] == 0
        assert cfg["max_val"] == 100

    def test_stale_fit_ext_fields_cleared(self, stub: FitRegistrationStub) -> None:
        """On re-registration, old fit_ext_fields should be cleared."""
        stub.fit_ext_fields = ["fit_old_field_text"]
        stub.fit_data = {"heart_rate": _samples(72)}
        stub._register_fit_fields()
        assert stub.fit_ext_fields == ["fit_heart_rate_text"]
        assert "fit_old_field_text" not in stub.fit_ext_fields

    def test_rebuild_ext_list_called(self, stub: FitRegistrationStub) -> None:
        """_rebuild_ext_list should be called after registration."""
        stub.fit_data = {"heart_rate": _samples(72)}
        stub._register_fit_fields()
        # ext_list.delete and insert should have been called
        stub.ext_list.delete.assert_called()
        stub.ext_list.insert.assert_called()
        # Check that insert was called with the right label
        insert_calls = stub.ext_list.insert.call_args_list
        labels = [call[0][1] for call in insert_calls]
        assert any("Heart Rate" in lbl for lbl in labels)


# ---------------------------------------------------------------------------
# Tests for _rebuild_ext_list
# ---------------------------------------------------------------------------


class TestRebuildExtList:
    """Tests for the ``_rebuild_ext_list`` method."""

    def test_empty_fields(self, stub: FitRegistrationStub) -> None:
        """With no FIT fields, only GPX extension fields are inserted."""
        stub.fit_ext_fields = []
        stub._rebuild_ext_list()
        stub.ext_list.delete.assert_called_once_with(0, tk.END)
        # GPX_EXT_FIELDS (power_text, atemp_text, hr_text, cad_text, battery_text)
        # are now always inserted first
        from src.gui.widgets import GPX_EXT_FIELDS
        assert stub.ext_list.insert.call_count == len(GPX_EXT_FIELDS)

    def test_populated_fields(self, stub: FitRegistrationStub) -> None:
        """Each field in fit_ext_fields + GPX_EXT_FIELDS should be inserted."""
        stub.layout["indicators"]["fit_hr_text"] = {"label": "Heart Rate"}
        stub.layout["indicators"]["fit_cad_text"] = {"label": "Cadence"}
        stub.fit_ext_fields = ["fit_hr_text", "fit_cad_text"]
        stub._rebuild_ext_list()
        # delete should have been called
        stub.ext_list.delete.assert_called_once()
        # GPX_EXT_FIELDS are inserted first, then FIT fields
        from src.gui.widgets import GPX_EXT_FIELDS
        assert stub.ext_list.insert.call_count == len(GPX_EXT_FIELDS) + 2

    def test_missing_indicator_config(self, stub: FitRegistrationStub) -> None:
        """If an indicator config is missing, the key itself is used as label."""
        # No config in layout for this key
        stub.fit_ext_fields = ["fit_missing_text"]
        stub._rebuild_ext_list()
        stub.ext_list.insert.assert_called_with(tk.END, "fit_missing_text")

    def test_no_ext_list_does_not_crash(self) -> None:
        """If ext_list does not exist, _rebuild_ext_list should do nothing."""
        from src.gui.hud_tuner_app import HudTunerApp

        obj = MagicMock()
        obj.fit_ext_fields = ["some_key"]
        obj.layout = {"indicators": {}}
        # Remove ext_list
        del obj.ext_list
        # This should not raise
        HudTunerApp._rebuild_ext_list(obj)


# ---------------------------------------------------------------------------
# Integration-style test: _register_fit_fields → _rebuild_ext_list
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_builtin_fields():
    """Remove any FIT fields added to BUILTIN_FIELDS after each test.

    Since BUILTIN_FIELDS is a module-level dict shared across tests, we
    need to clean up the keys that ``_register_fit_fields`` adds.
    """
    before = set(BUILTIN_FIELDS.keys())
    yield
    after = set(BUILTIN_FIELDS.keys())
    added = after - before
    for key in added:
        BUILTIN_FIELDS.pop(key, None)
