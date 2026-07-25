"""Tests for the LayoutManager class."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.gui.layout_manager import LayoutManager

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def default_layout_fn() -> Any:
    """Return a simple default layout function."""

    def _default(w: int, h: int) -> dict[str, Any]:
        return {
            "version": 5,
            "global": {"text_outline": 3},
            "custom_texts": [],
            "indicators": {
                "speed_text": {
                    "enabled": True,
                    "label": "",
                    "x": 0.5,
                    "y": 0.5,
                    "form": "text",
                    "font_size": 0.04,
                    "source": "gpmf",
                },
                "alt_text": {
                    "enabled": True,
                    "label": "Alt",
                    "x": 0.1,
                    "y": 0.8,
                    "form": "text",
                    "font_size": 0.017,
                    "source": "gpmf",
                },
            },
        }

    return _default


@pytest.fixture
def normalize_layout_fn() -> Any:
    """Return a simple normalise function that merges user layout with defaults."""

    def _normalize(
        layout_path: Path | str | None, w: int, h: int
    ) -> dict[str, Any]:
        base = {
            "version": 5,
            "global": {"text_outline": 3},
            "custom_texts": [],
            "indicators": {
                "speed_text": {
                    "enabled": True,
                    "label": "",
                    "x": 0.5,
                    "y": 0.5,
                    "form": "text",
                    "font_size": 0.04,
                    "source": "gpmf",
                },
            },
        }
        if layout_path and Path(layout_path).exists():
            user = json.loads(Path(layout_path).read_text(encoding="utf-8"))
            if "indicators" in user:
                base["global"].update(user.get("global", {}))
                for k, v in user.get("indicators", {}).items():
                    if k in base["indicators"] and isinstance(v, dict):
                        base["indicators"][k].update(v)
            if "custom_texts" in user:
                base["custom_texts"] = user["custom_texts"]
        return base

    return _normalize


@pytest.fixture
def manager(
    default_layout_fn: Any, normalize_layout_fn: Any
) -> LayoutManager:
    return LayoutManager(default_layout_fn, normalize_layout_fn)


# ── Tests ───────────────────────────────────────────────────────────────────


class TestLayoutManager:
    """Suite of tests for LayoutManager."""

    def test_init(self, manager: LayoutManager) -> None:
        """Manager should initialise with empty layout."""
        assert manager.layout == {}

    def test_reset(self, manager: LayoutManager) -> None:
        """reset() should return a layout with default indicators."""
        layout = manager.reset(1920, 1080)
        assert "indicators" in layout
        assert "speed_text" in layout["indicators"]
        assert layout["indicators"]["speed_text"]["enabled"] is True
        assert layout["indicators"]["speed_text"]["x"] == 0.5

    def test_load_no_file(self, manager: LayoutManager) -> None:
        """load() without a file should return defaults."""
        layout = manager.load(None, 1920, 1080)
        assert "speed_text" in layout["indicators"]

    def test_load_with_file(
        self, manager: LayoutManager, tmp_path: Path
    ) -> None:
        """load() with a JSON file should merge user settings."""
        user_layout = {
            "indicators": {
                "speed_text": {"x": 0.75, "font_size": 0.06},
            },
            "global": {"text_outline": 5},
        }
        layout_file = tmp_path / "test_layout.json"
        layout_file.write_text(
            json.dumps(user_layout), encoding="utf-8"
        )

        layout = manager.load(layout_file, 1920, 1080)
        assert layout["indicators"]["speed_text"]["x"] == 0.75
        assert layout["indicators"]["speed_text"]["font_size"] == 0.06
        assert layout["global"]["text_outline"] == 5

    def test_save(self, manager: LayoutManager, tmp_path: Path) -> None:
        """save() should write layout to JSON."""
        manager.reset(1920, 1080)
        out = tmp_path / "saved_layout.json"
        result = manager.save(out)
        assert result == out
        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert "indicators" in loaded

    def test_get_indicator(self, manager: LayoutManager) -> None:
        """get_indicator() should return the config for a given key."""
        manager.reset(1920, 1080)
        ind = manager.get_indicator("speed_text")
        assert ind.get("enabled") is True
        assert ind.get("form") == "text"

    def test_get_indicator_missing(self, manager: LayoutManager) -> None:
        """get_indicator() should return empty dict for unknown keys."""
        manager.reset(1920, 1080)
        assert manager.get_indicator("nonexistent") == {}

    def test_set_indicator_source(self, manager: LayoutManager) -> None:
        """set_indicator_source() should update the source field."""
        manager.reset(1920, 1080)
        manager.set_indicator_source("speed_text", "gpx")
        assert (
            manager.get_indicator("speed_text").get("source") == "gpx"
        )

    def test_set_indicators_source(self, manager: LayoutManager) -> None:
        """set_indicators_source() should update multiple indicators."""
        manager.reset(1920, 1080)
        manager.set_indicators_source(["speed_text", "alt_text"], "fit")
        assert manager.get_indicator("speed_text").get("source") == "fit"
        assert manager.get_indicator("alt_text").get("source") == "fit"

    def test_get_outline_default(self, manager: LayoutManager) -> None:
        """Default outline should be 3."""
        assert manager.get_outline() == 3

    def test_set_outline(self, manager: LayoutManager) -> None:
        """set_outline() should persist the outline value."""
        manager.set_outline(7)
        assert manager.get_outline() == 7

    def test_get_enabled_keys(self, manager: LayoutManager) -> None:
        """get_enabled_keys() should return only enabled indicators."""
        manager.reset(1920, 1080)
        keys = manager.get_enabled_keys()
        assert "speed_text" in keys

    def test_custom_texts(self, manager: LayoutManager) -> None:
        """Custom text CRUD operations."""
        manager.reset(1920, 1080)
        assert manager.get_custom_texts() == []

        idx = manager.add_custom_text()
        assert idx == 0
        texts = manager.get_custom_texts()
        assert len(texts) == 1
        assert texts[0]["text"] == "Custom 1"

        manager.add_custom_text()
        assert len(manager.get_custom_texts()) == 2

        manager.remove_custom_text(0)
        assert len(manager.get_custom_texts()) == 1

        manager.update_custom_text(0, text="Updated", x=0.3)
        assert manager.get_custom_texts()[0]["text"] == "Updated"
        assert manager.get_custom_texts()[0]["x"] == 0.3

    def test_remove_custom_text_out_of_range(
        self, manager: LayoutManager
    ) -> None:
        """Removing an out-of-range index should not raise."""
        manager.reset(1920, 1080)
        manager.remove_custom_text(5)  # should not raise
        manager.remove_custom_text(-1)  # should not raise
