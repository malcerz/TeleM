from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.indicators.frame_data import (
    build_active_fit_field_plan,
    prepare_overlay_frame_data,
)


ROOT = Path(__file__).resolve().parents[1]
DISCOVERED = {
    "speed", "track", "alt", "K1", "K2", "cadence", "curVpower",
    "distance", "enhanced_altitude", "enhanced_speed",
    "fractional_cadence", "gopro_battery", "heart_rate", "temperature",
}


def _frame(plan: dict[str, list[str]], layout: dict, resolver, stats=None):
    now = datetime(2026, 8, 5, 4, 28, 11, tzinfo=timezone.utc)
    return prepare_overlay_frame_data(
        layout=layout,
        target_dt=now,
        tz_offset_hours=2,
        start_dt_utc=now,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        resolve_cache_value=resolver,
        fit_field_plan=plan,
        resolve_stats=stats,
    )


def test_current_layout_uses_only_four_dynamic_fit_fields() -> None:
    layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
    plan = build_active_fit_field_plan(layout, DISCOVERED)

    assert plan["active_fit_fields"] == [
        "cadence", "enhanced_speed", "heart_rate", "temperature"
    ]
    assert plan["active_standard_resolve_fields"] == []
    assert set(plan["inactive_fit_fields"]) == DISCOVERED - set(
        plan["active_fit_fields"]
    )


def test_alternative_layout_automatically_activates_new_fit_field() -> None:
    field_name = "fractional_cadence"
    layout = {
        "indicators": {
            f"fit_{field_name}_text": {
                "enabled": True,
                "form": "text",
                "source": "fit",
            }
        }
    }
    plan = build_active_fit_field_plan(layout, DISCOVERED)
    calls: list[str] = []

    data = _frame(
        plan,
        layout,
        lambda field, _dt: calls.append(field) or 12.5,
    )

    assert plan["active_fit_fields"] == [field_name]
    assert calls == [field_name]
    assert data["extra_indicators"][f"fit_{field_name}_text"][0] == 12.5


def test_duplicate_consumers_resolve_exact_field_once_per_frame() -> None:
    layout = {
        "indicators": {
            "power_text": {"enabled": True, "form": "text"},
            "fit_power_text": {"enabled": True, "form": "chart", "source": "fit"},
        }
    }
    plan = build_active_fit_field_plan(layout, {"power"})
    calls: list[str] = []
    stats: dict = {"calls": 0, "per_field": {}}

    data = _frame(
        plan,
        layout,
        lambda field, _dt: calls.append(field) or 321.0,
        stats,
    )

    assert plan["unique_resolve_fields"] == ["power"]
    # The two indicators explicitly select different sources (default GPX
    # for power_text and FIT for fit_power_text), so they are distinct
    # resolver requests even though the logical field name is the same.
    assert calls == ["power", "power"]
    assert stats == {"calls": 2, "per_field": {"power": 2}}
    assert data["power_value"] == 321.0
    assert data["extra_indicators"]["fit_power_text"][0] == 321.0


def test_disabled_fit_indicator_is_not_resolved() -> None:
    layout = {
        "indicators": {
            "fit_K1_text": {"enabled": False, "form": "text", "source": "fit"},
        }
    }
    plan = build_active_fit_field_plan(layout, {"K1"})
    calls: list[str] = []

    data = _frame(plan, layout, lambda field, _dt: calls.append(field) or 1.0)

    assert plan["active_fit_fields"] == []
    assert plan["inactive_fit_fields"] == ["K1"]
    assert calls == []
    # Disabled/missing dynamic fields do not become synthetic zeroes.
    assert data["extra_indicators"]["fit_K1_text"][0] is None
