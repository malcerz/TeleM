"""Layout manager – loading, saving and normalising HUD layout configurations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional


class LayoutManager:
    """Manages HUD layout configurations (JSON-based indicator definitions).

    Handles loading from def_layout.json, saving, migration between versions,
    and normalisation to the current default layout.
    """

    def __init__(
        self,
        default_layout_fn: Optional[Callable[[int, int], dict[str, Any]]] = None,
        normalize_layout_fn: Optional[
            Callable[[Path | str | None, int, int], dict[str, Any]]
        ] = None,
    ) -> None:
        self.layout: dict[str, Any] = {}
        self._default_layout_fn = default_layout_fn
        self._normalize_layout_fn = normalize_layout_fn

    # ------------------------------------------------------------------
    # Layout operations
    # ------------------------------------------------------------------

    def reset(self, video_width: int, video_height: int) -> dict[str, Any]:
        """Reset layout to defaults for the given video dimensions."""
        if self._default_layout_fn:
            self.layout = self._default_layout_fn(video_width, video_height)
        else:
            self.layout = {}
        return self.layout

    def load(
        self,
        layout_path: Path | str | None,
        video_width: int,
        video_height: int,
    ) -> dict[str, Any]:
        """Load a layout from a JSON file, merging with defaults.

        Args:
            layout_path: Path to the JSON layout file (may not exist).
            video_width: Video width in pixels (for relative positioning).
            video_height: Video height in pixels.

        Returns:
            The merged layout dict.
        """
        if self._normalize_layout_fn:
            self.layout = self._normalize_layout_fn(
                layout_path, video_width, video_height
            )
        else:
            self.layout = {}
        return self.layout

    def save(self, layout_path: Path | str) -> Path:
        """Save the current layout to a JSON file.

        Args:
            layout_path: Destination path.

        Returns:
            The path the layout was saved to.
        """
        path = Path(layout_path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.layout, f, indent=2, ensure_ascii=False)
        return path

    # ------------------------------------------------------------------
    # Indicator helpers
    # ------------------------------------------------------------------

    def get_indicator(self, key: str) -> dict[str, Any]:
        """Get a single indicator config by key."""
        return self.layout.get("indicators", {}).get(key, {})

    def set_indicator_source(self, key: str, source: str) -> None:
        """Set the telemetry source for a given indicator."""
        ind = self.layout.get("indicators", {}).get(key)
        if ind is not None:
            ind["source"] = source

    def set_indicators_source(
        self, keys: list[str], source: str
    ) -> None:
        """Set the telemetry source for multiple indicators at once."""
        for key in keys:
            self.set_indicator_source(key, source)

    def get_outline(self) -> int:
        """Get the global text outline width."""
        return self.layout.get("global", {}).get("text_outline", 3)

    def set_outline(self, value: int) -> None:
        """Set the global text outline width."""
        self.layout.setdefault("global", {})["text_outline"] = value

    def get_enabled_keys(self) -> list[str]:
        """Return list of enabled indicator keys."""
        inds = self.layout.get("indicators", {})
        return [k for k, v in inds.items() if v.get("enabled", True)]

    def get_smoothing(self) -> dict[str, Any]:
        """Get the smoothing configuration dict."""
        return self.layout.get("smoothing", {})

    # ------------------------------------------------------------------
    # Custom texts
    # ------------------------------------------------------------------

    def get_custom_texts(self) -> list[dict[str, Any]]:
        """Get the list of custom text overlays."""
        return self.layout.get("custom_texts", [])

    def add_custom_text(self) -> int:
        """Add a new default custom text entry. Returns its index."""
        texts = self.layout.setdefault("custom_texts", [])
        idx = len(texts) + 1
        texts.append({
            "enabled": True,
            "text": f"Custom {idx}",
            "x": 50.0,
            "y": 50.0,
            "font_size": 2.5,
            "color": "#FFFFFF",
            "rotation": 0,
        })
        return len(texts) - 1

    def remove_custom_text(self, index: int) -> None:
        """Remove a custom text by index."""
        texts = self.layout.get("custom_texts", [])
        if 0 <= index < len(texts):
            del texts[index]

    def update_indicator(self, key: str, updates: dict[str, Any]) -> None:
        """Update a single indicator's config."""
        ind = self.layout.setdefault("indicators", {}).get(key)
        if ind is not None:
            ind.update(updates)

    def disable_indicators_except(self, keep_keys: list[str]) -> None:
        """Disable all indicators except those in *keep_keys*."""
        inds = self.layout.get("indicators", {})
        for key in inds:
            if key not in keep_keys:
                inds[key]["enabled"] = False

    def get_builtin_keys(self, ext_fields: list[str]) -> list[str]:
        """Return indicator keys that are NOT in ext_fields and NOT fit_*."""
        inds = self.layout.get("indicators", {})
        return [k for k in inds if k not in ext_fields and not k.startswith("fit_")]

    def get_ext_keys(self, gpx_ext_fields: list[str], fit_ext_fields: list[str]) -> list[str]:
        """Return GPX + FIT extension keys."""
        return list(gpx_ext_fields) + list(fit_ext_fields)

    def update_custom_text(self, index: int, **kwargs: Any) -> None:
        """Update properties of a custom text entry."""
        texts = self.layout.get("custom_texts", [])
        if 0 <= index < len(texts):
            texts[index].update(kwargs)


def default_layout(video_width: int, video_height: int) -> dict[str, Any]:
    return {
        "version": 6,
        "global": {"text_outline": 3},
        "custom_texts": [],
        "indicators": {
            "time_block": {
                "enabled": True, "label": "Czas", "x": 1.8, "y": 3.0, "rotation": 0,
                "font_label": 1.25, "font_date": 2.0, "font_time": 2.0
            },
            "speed_visual": {
                "enabled": True, "label": "", "x": 50.0, "y": 78.0, "rotation": 0, "form": "gauge",
                "font_size": 1.25, "size": 10.8, "thickness": 0.7, "min_val": 0, "max_val": 60, "ticks": 6,
                "source": "gpmf"
            },
            "speed_text": {
                "enabled": True, "label": "", "x": 50.0, "y": 85.5, "rotation": 0, "form": "text",
                "font_size": 4.2, "size": 10.0, "thickness": 0.1, "min_val": 0, "max_val": 100, "ticks": 0,
                "source": "gpmf"
            },
            "dist_visual": {
                "enabled": True, "label": "", "x": 50.0, "y": 92.5, "rotation": 0, "form": "bar",
                "font_size": 1.25, "size": 20.0, "thickness": 0.4, "min_val": 0, "max_val": 10, "ticks": 5,
                "show_range_labels": True,
                "range_label_offset_x": 0.0,
                "range_label_offset_y": 0.0,
                "range_label_spread_x": 0.0,
                "value_offset_x": 0.0,
                "value_offset_y": 0.0,
                "source": "gpmf"
            },
            "dist_text": {
                "enabled": True, "label": "", "x": 50.0, "y": 95.5, "rotation": 0, "form": "text",
                "font_size": 1.7, "size": 10.0, "thickness": 0.1, "min_val": 0, "max_val": 100, "ticks": 0,
                "source": "gpmf"
            },
            "alt_visual": {
                "enabled": True, "label": "Alt", "x": 4.0, "y": 80.0, "rotation": 90, "form": "bar",
                "font_size": 1.25, "size": 20.0, "thickness": 0.6, "min_val": 0, "max_val": 100, "ticks": 5,
                "show_range_labels": True,
                "range_label_offset_x": 0.0,
                "range_label_offset_y": 0.0,
                "range_label_spread_x": 0.0,
                "value_offset_x": 0.0,
                "value_offset_y": 0.0,
                "source": "gpmf"
            },
            "alt_text": {
                "enabled": True, "label": "", "x": 2.5, "y": 80.0, "rotation": 0, "form": "text",
                "font_size": 1.7, "size": 10.0, "thickness": 0.1, "min_val": 0, "max_val": 1000, "ticks": 0,
                "source": "gpmf"
            },
            "iso_text": {
                "enabled": True, "label": "ISO", "x": 90.0, "y": 8.0, "rotation": 0, "form": "text",
                "font_size": 1.8, "size": 10.0, "thickness": 0.1, "min_val": 0, "max_val": 12800, "ticks": 0
            },
            "exposure_text": {
                "enabled": True, "label": "Exp", "x": 82.0, "y": 8.0, "rotation": 0, "form": "text",
                "font_size": 1.8, "size": 10.0, "thickness": 0.1, "min_val": 0, "max_val": 10000, "ticks": 0
            },
            "temp_text": {
                "enabled": True, "label": "Temp", "x": 74.0, "y": 8.0, "rotation": 0, "form": "text",
                "font_size": 1.8, "size": 10.0, "thickness": 0.1, "min_val": 0, "max_val": 100, "ticks": 0
            },
            "power_text": {
                "enabled": True, "label": "Moc", "x": 18.5, "y": 8.0, "rotation": 0, "form": "text",
                "font_size": 1.8, "size": 10.0, "thickness": 0.1, "min_val": 0, "max_val": 1000, "ticks": 0
            },
            "atemp_text": {
                "enabled": True, "label": "ATemp", "x": 26.5, "y": 8.0, "rotation": 0, "form": "text",
                "font_size": 1.8, "size": 10.0, "thickness": 0.1, "min_val": -20, "max_val": 60, "ticks": 0
            },
            "hr_text": {
                "enabled": True, "label": "HR", "x": 34.5, "y": 8.0, "rotation": 0, "form": "text",
                "font_size": 1.8, "size": 10.0, "thickness": 0.1, "min_val": 0, "max_val": 250, "ticks": 0
            },
            "cad_text": {
                "enabled": True, "label": "Cad", "x": 41.0, "y": 8.0, "rotation": 0, "form": "text",
                "font_size": 1.8, "size": 10.0, "thickness": 0.1, "min_val": 0, "max_val": 200, "ticks": 0
            },
            "battery_text": {
                "enabled": True, "label": "Bat", "x": 49.0, "y": 8.0, "rotation": 0, "form": "text",
                "font_size": 1.8, "size": 10.0, "thickness": 0.1, "min_val": 0, "max_val": 100, "ticks": 0
            },
            "track_map": {
                "enabled": False, "label": "Mapa", "x": 2.0, "y": 15.0, "rotation": 0, "form": "map",
                "font_size": 1.2, "size": 18.0, "thickness": 1, "zoom": 16,
                "source": "gpmf", "map_style": "light_all", "map_shape": "square",
                "min_val": 0, "max_val": 1, "ticks": 0,
                "marker_size": 7, "marker_color": "#FFFFFF",
            },
        },
        "smoothing": {"method": "moving_average", "strength": 3}
    }


def normalize_layout(layout_path: Path | str | None, video_width: int, video_height: int) -> dict[str, Any]:
    layout = default_layout(video_width, video_height)
    if layout_path and Path(layout_path).exists():
        try:
            user = json.loads(Path(layout_path).read_text(encoding='utf-8'))
        except Exception:
            return layout
        if not isinstance(user, dict):
            return layout

        if "global" in user and isinstance(user["global"], dict):
            layout["global"].update(user["global"])
        if "smoothing" in user and isinstance(user["smoothing"], dict):
            layout["smoothing"].update(user["smoothing"])
        if "_startup_preset" in user:
            layout["_startup_preset"] = user["_startup_preset"]
        if "cut_regions" in user:
            layout["cut_regions"] = user["cut_regions"]

        if "indicators" in user and isinstance(user["indicators"], dict):
            layout["indicators"] = user["indicators"]
        if "custom_texts" in user and isinstance(user["custom_texts"], list):
            layout["custom_texts"] = user["custom_texts"]

        if user.get("version", 0) < 5:
            old_inds = layout.get("indicators", {})
            if "gauge" in old_inds:
                layout["indicators"]["speed_visual"] = old_inds["gauge"]
                layout["indicators"]["speed_visual"]["form"] = "gauge"
                layout["indicators"]["speed_visual"]["size"] = old_inds["gauge"].get("radius", 0.1)
                layout["indicators"]["speed_visual"]["thickness"] = old_inds["gauge"].get("arc_width", 0.007)
                layout["indicators"]["speed_visual"]["max_val"] = old_inds["gauge"].get("gauge_max", 60)
                layout["indicators"]["speed_visual"]["ticks"] = 6
            if "speed_text" in old_inds:
                layout["indicators"]["speed_text"]["form"] = "text"
                layout["indicators"]["speed_text"]["font_size"] = old_inds["speed_text"].get("font_speed", 0.04)
            if "distance_block" in old_inds:
                db = old_inds["distance_block"]
                layout["indicators"]["dist_visual"] = db.copy()
                layout["indicators"]["dist_visual"]["form"] = "bar"
                layout["indicators"]["dist_visual"]["size"] = db.get("bar_width", 0.2)
                layout["indicators"]["dist_visual"]["thickness"] = db.get("bar_height", 0.004)
                layout["indicators"]["dist_text"] = db.copy()
                layout["indicators"]["dist_text"]["form"] = "text"
                layout["indicators"]["dist_text"]["font_size"] = db.get("font_value", 0.017)

        if user.get("version", 0) < 6:
            relative_fields = [
                "x", "y", "size", "font_size", "font_label", "font_date", "font_time",
                "date_font_size", "time_font_size", "elapsed_font_size", "avg_speed_font_size",
                "value_offset_x", "value_offset_y", "range_label_offset_x",
                "range_label_offset_y", "range_label_spread_x", "text_offset_x", "text_offset_y"
            ]
            for ind in layout.get("indicators", {}).values():
                if isinstance(ind, dict):
                    for field in relative_fields:
                        if field in ind and isinstance(ind[field], (int, float)):
                            if -1.0 <= ind[field] <= 1.0:
                                ind[field] = round(float(ind[field]) * 100.0, 4)
            for ct in layout.get("custom_texts", []):
                if isinstance(ct, dict):
                    for field in ("x", "y", "font_size"):
                        if field in ct and isinstance(ct[field], (int, float)):
                            if -1.0 <= ct[field] <= 1.0:
                                ct[field] = round(float(ct[field]) * 100.0, 4)
            layout["version"] = 6

    return layout


def resolve_font_path(family_name: str) -> str:
    """Znajduje ścieżkę pliku czcionki dla podanej nazwy rodziny (Windows)."""
    from src.indicators.helpers import resolve_indicator_font_path
    return resolve_indicator_font_path(family_name, default_font_path="")


