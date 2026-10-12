"""Tests for compass migration policy (compass_motion_mode vs compass_rotation_mode).

Verifies the deterministic migration policy:
1. Legacy-only field ('compass_motion_mode') is respected.
2. Modern-only field ('compass_rotation_mode') is respected.
3. Both fields present with identical values agree.
4. Conflicting fields: modern field takes precedence over legacy field.
5. GUI value updates: updating modern field changes effective mode.
6. Project JSON round-trip preserves settings deterministically.
"""

from __future__ import annotations

import json
import pytest

from src.indicators.gauge import resolve_compass_mode


def test_1_only_legacy_field():
    """Historical layout containing only compass_motion_mode."""
    cfg_rose = {"compass_motion_mode": "rose"}
    cfg_needle = {"compass_motion_mode": "needle"}
    cfg_invalid = {"compass_motion_mode": "invalid_mode"}

    assert resolve_compass_mode(cfg_rose) == "rose"
    assert resolve_compass_mode(cfg_needle) == "needle"
    assert resolve_compass_mode(cfg_invalid) == "needle"


def test_2_only_modern_field():
    """Modern layout containing only compass_rotation_mode."""
    cfg_rose = {"compass_rotation_mode": "rose"}
    cfg_needle = {"compass_rotation_mode": "needle"}
    cfg_whitespace = {"compass_rotation_mode": "  ROSE  "}

    assert resolve_compass_mode(cfg_rose) == "rose"
    assert resolve_compass_mode(cfg_needle) == "needle"
    assert resolve_compass_mode(cfg_whitespace) == "rose"


def test_3_both_fields_identical():
    """Layout containing both fields with identical values."""
    cfg_rose = {"compass_motion_mode": "rose", "compass_rotation_mode": "rose"}
    cfg_needle = {"compass_motion_mode": "needle", "compass_rotation_mode": "needle"}

    assert resolve_compass_mode(cfg_rose) == "rose"
    assert resolve_compass_mode(cfg_needle) == "needle"


def test_4_conflicting_fields_modern_wins():
    """Layout containing conflicting fields: modern GUI field takes precedence."""
    cfg_modern_rose = {"compass_motion_mode": "needle", "compass_rotation_mode": "rose"}
    cfg_modern_needle = {"compass_motion_mode": "rose", "compass_rotation_mode": "needle"}

    assert resolve_compass_mode(cfg_modern_rose) == "rose"
    assert resolve_compass_mode(cfg_modern_needle) == "needle"


def test_5_gui_value_update():
    """Simulates GUI property editor updating the value."""
    cfg = {"compass_motion_mode": "needle", "compass_rotation_mode": "needle"}
    assert resolve_compass_mode(cfg) == "needle"

    # User changes choice in UI
    cfg["compass_rotation_mode"] = "rose"
    assert resolve_compass_mode(cfg) == "rose"


def test_6_project_json_serialization_round_trip(tmp_path):
    """Saving and loading from JSON preserves mode deterministically."""
    project_data = {
        "indicators": {
            "compass_legacy": {"compass_motion_mode": "rose"},
            "compass_modern": {"compass_rotation_mode": "rose"},
            "compass_default": {"label": "COMPASS"},
        }
    }

    target_file = tmp_path / "test_project.json"
    target_file.write_text(json.dumps(project_data), encoding="utf-8")

    loaded = json.loads(target_file.read_text(encoding="utf-8"))
    inds = loaded["indicators"]

    assert resolve_compass_mode(inds["compass_legacy"]) == "rose"
    assert resolve_compass_mode(inds["compass_modern"]) == "rose"
    assert resolve_compass_mode(inds["compass_default"]) == "needle"
