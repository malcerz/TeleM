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
            "x": 0.5,
            "y": 0.5,
            "font_size": 0.025,
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
        "version": 5,
        "global": {"text_outline": 3},
        "custom_texts": [],
        "indicators": {
            "time_block": {
                "enabled": True, "label": "Czas", "x": 0.018, "y": 0.030, "rotation": 0,
                "font_label": 0.0125, "font_date": 0.020, "font_time": 0.020
            },
            "speed_visual": {
                "enabled": True, "label": "", "x": 0.50, "y": 0.78, "rotation": 0, "form": "gauge",
                "font_size": 0.0125, "size": 0.108, "thickness": 0.007, "min_val": 0, "max_val": 60, "ticks": 6,
                "source": "gpmf"
            },
            "speed_text": {
                "enabled": True, "label": "", "x": 0.50, "y": 0.855, "rotation": 0, "form": "text",
                "font_size": 0.042, "size": 0.1, "thickness": 0.001, "min_val": 0, "max_val": 100, "ticks": 0,
                "source": "gpmf"
            },
            "dist_visual": {
                "enabled": True, "label": "", "x": 0.50, "y": 0.925, "rotation": 0, "form": "bar",
                "font_size": 0.0125, "size": 0.20, "thickness": 0.004, "min_val": 0, "max_val": 10, "ticks": 5,
                "show_range_labels": True,
                "range_label_offset_x": 0.0,
                "range_label_offset_y": 0.0,
                "range_label_spread_x": 0.0,
                "value_offset_x": 0.0,
                "value_offset_y": 0.0,
                "source": "gpmf"
            },
            "dist_text": {
                "enabled": True, "label": "", "x": 0.50, "y": 0.955, "rotation": 0, "form": "text",
                "font_size": 0.017, "size": 0.1, "thickness": 0.001, "min_val": 0, "max_val": 100, "ticks": 0,
                "source": "gpmf"
            },
            "alt_visual": {
                "enabled": True, "label": "Alt", "x": 0.04, "y": 0.80, "rotation": 90, "form": "bar",
                "font_size": 0.0125, "size": 0.20, "thickness": 0.006, "min_val": 0, "max_val": 100, "ticks": 5,
                "show_range_labels": True,
                "range_label_offset_x": 0.0,
                "range_label_offset_y": 0.0,
                "range_label_spread_x": 0.0,
                "value_offset_x": 0.0,
                "value_offset_y": 0.0,
                "source": "gpmf"
            },
            "alt_text": {
                "enabled": True, "label": "", "x": 0.025, "y": 0.8, "rotation": 0, "form": "text",
                "font_size": 0.017, "size": 0.1, "thickness": 0.001, "min_val": 0, "max_val": 1000, "ticks": 0,
                "source": "gpmf"
            },
            "iso_text": {
                "enabled": True, "label": "ISO", "x": 0.90, "y": 0.08, "rotation": 0, "form": "text",
                "font_size": 0.018, "size": 0.1, "thickness": 0.001, "min_val": 0, "max_val": 12800, "ticks": 0
            },
            "exposure_text": {
                "enabled": True, "label": "Exp", "x": 0.82, "y": 0.08, "rotation": 0, "form": "text",
                "font_size": 0.018, "size": 0.1, "thickness": 0.001, "min_val": 0, "max_val": 10000, "ticks": 0
            },
            "temp_text": {
                "enabled": True, "label": "Temp", "x": 0.74, "y": 0.08, "rotation": 0, "form": "text",
                "font_size": 0.018, "size": 0.1, "thickness": 0.001, "min_val": 0, "max_val": 100, "ticks": 0
            },
            "power_text": {
                "enabled": True, "label": "Moc", "x": 0.185, "y": 0.08, "rotation": 0, "form": "text",
                "font_size": 0.018, "size": 0.1, "thickness": 0.001, "min_val": 0, "max_val": 1000, "ticks": 0
            },
            "atemp_text": {
                "enabled": True, "label": "ATemp", "x": 0.265, "y": 0.08, "rotation": 0, "form": "text",
                "font_size": 0.018, "size": 0.1, "thickness": 0.001, "min_val": -20, "max_val": 60, "ticks": 0
            },
            "hr_text": {
                "enabled": True, "label": "HR", "x": 0.345, "y": 0.08, "rotation": 0, "form": "text",
                "font_size": 0.018, "size": 0.1, "thickness": 0.001, "min_val": 0, "max_val": 250, "ticks": 0
            },
            "cad_text": {
                "enabled": True, "label": "Cad", "x": 0.41, "y": 0.08, "rotation": 0, "form": "text",
                "font_size": 0.018, "size": 0.1, "thickness": 0.001, "min_val": 0, "max_val": 200, "ticks": 0
            },
            "battery_text": {
                "enabled": True, "label": "Bat", "x": 0.49, "y": 0.08, "rotation": 0, "form": "text",
                "font_size": 0.018, "size": 0.1, "thickness": 0.001, "min_val": 0, "max_val": 100, "ticks": 0
            },
            "track_map": {
                "enabled": False, "label": "Mapa", "x": 0.02, "y": 0.15, "rotation": 0, "form": "map",
                "font_size": 0.012, "size": 0.18, "thickness": 1, "zoom": 16,
                "source": "gpmf", "map_style": "light_all", "min_val": 0, "max_val": 1, "ticks": 0,
                "marker_size": 7, "marker_color": "#FFFFFF",
            },
        },
        "smoothing": {"method": "moving_average", "strength": 3}
    }


def normalize_layout(layout_path: Path | str | None, video_width: int, video_height: int) -> dict[str, Any]:
    layout = default_layout(video_width, video_height)
    if layout_path and Path(layout_path).exists():
        user = json.loads(Path(layout_path).read_text(encoding='utf-8'))
        if not isinstance(user, dict):
            return layout
        layout["global"].update(user.get("global", {}))
        layout["smoothing"].update(user.get("smoothing", {}))
        if "indicators" in user and isinstance(user["indicators"], dict):
            for k, v in user["indicators"].items():
                if isinstance(v, dict):
                    if k in layout["indicators"]:
                        layout["indicators"][k].update(v)
                    else:
                        layout["indicators"][k] = v
        if "custom_texts" in user:
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
            layout["version"] = 5

    return layout


def resolve_font_path(family_name: str) -> str:
    """Znajduje ścieżkę pliku czcionki dla podanej nazwy rodziny (Windows)."""
    import os
    if os.name != 'nt':
        return family_name
    if Path(family_name).exists():
        return family_name
    try:
        import winreg
        fonts_dir = Path(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts') as key:
            count = winreg.QueryInfoKey(key)[1]
            for i in range(count):
                name, value, _ = winreg.EnumValue(key, i)
                if name.lower().startswith(family_name.lower()) and '(TrueType)' in name:
                    candidate = fonts_dir / value
                    if candidate.exists():
                        return str(candidate)
    except Exception:
        pass
    for ext in ('.ttf', '.otf'):
        candidate = Path(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts') / f'{family_name}{ext}'
        if candidate.exists():
            return str(candidate)
    return family_name


