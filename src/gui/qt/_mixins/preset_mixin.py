"""Mixin for presets, layouts, properties and general settings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog

from src.gui.indicator_schemas import BUILTIN_FIELDS
from src.gui.qt.models import _sync_size_font_fields, get_schema_for_form
from src.overlay_renderer import FONT_CACHE
from src.gui.layout_manager import resolve_font_path


class PresetMixin:
    def _on_save_preset(self) -> None:
        """Zapisuje obecny układ do pliku JSON."""
        path, _ = QFileDialog.getSaveFileName(
            None, "Zapisz preset układu", "",
            "JSON (*.json);;Wszystkie (*.*)",
        )
        if not path:
            return
        try:
            # Dołącz cut_regions do zapisywanego layoutu
            layout_copy = dict(self.layout)
            if self._cut_regions:
                layout_copy["cut_regions"] = self._cut_regions
            else:
                layout_copy.pop("cut_regions", None)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(layout_copy, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.signals.sig_error.emit(f"Błąd zapisu presetu: {e}")

    def _on_load_preset(self) -> None:
        """Wczytuje układ z pliku JSON i odświeża podgląd."""
        self._clear_caches()
        path, _ = QFileDialog.getOpenFileName(
            None, "Wczytaj preset układu", "",
            "JSON (*.json);;Wszystkie (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("Nieprawidłowy format pliku")
            self.layout = loaded
            if self.layout_mgr:
                self.layout_mgr.layout = self.layout
            self._selected_stream_key = ""
            self.indicator_bboxes.clear()
            # Odśwież strumienie danych – DataStreamBar musi się zaktualizować
            if self.telemetry:
                self.fit_ext_fields = []
                if self.telemetry.fit_data:
                    fit_keys = self.telemetry.register_fit_fields(
                        self.layout, BUILTIN_FIELDS,
                    )
                    self.fit_ext_fields = list(fit_keys)
                streams = self._discover_data_streams()
                self.signals.sig_data_streams_ready.emit(streams)
            self._render_preview()
        except Exception as e:
            self.signals.sig_error.emit(f"Błąd wczytania presetu: {e}")

    def _on_property_changed(
        self, stream_key: str, field_name: str, value: Any,
    ) -> None:
        """Użytkownik zmienił wartość pola właściwości."""
        cfg = self.layout.get("indicators", {}).get(stream_key)
        if cfg is None:
            return

        # Konwertuj typy dla bool
        if isinstance(value, bool):
            pass
        elif field_name in ("enabled", "show_value", "show_range_labels"):
            value = bool(value)

        old_form = cfg.get("form", "text")
        cfg[field_name] = value

        # "Rozmiar" (size) i "Size" (font_size) są zsynchronizowane tylko dla
        # forma "text". Dla gauge/chart/bar itd. size = wymiary, font_size =
        # czcionka — muszą być niezależne (patrz _sync_size_font_fields).
        _sync_size_font_fields(cfg, field_name)

        # Jeśli zmieniono formę lub styl bara — wyślij nowy schemat
        if (
            (field_name == "form" and value != old_form)
            or (field_name == "bar_style" and cfg.get("form") in ("bar", "segment_bar"))
            or (field_name == "chart_time_scope" and cfg.get("form") == "chart")
        ):
            schema = get_schema_for_form(
                cfg.get("form", "text"),
                bar_style=cfg.get("bar_style", "ruler"),
                chart_time_scope=cfg.get("chart_time_scope", "activity"),
            )
            self.signals.sig_properties_ready.emit(stream_key, schema, dict(cfg))

        # Synchronizuj layout_mgr
        if self.layout_mgr:
            self.layout_mgr.layout = self.layout

        # Inwalidacja cache przygotowania — gdy zmieni się form/bar_style/source/scope/ticks/thickness zmieniają dane statyczne
        if field_name in ("source", "form", "bar_style", "min_val", "max_val", "chart_time_scope", "chart_window_s", "ticks", "thickness", "major_ticks", "minor_ticks", "segments"):
            self._clear_caches()

        # Odśwież podgląd
        self._render_preview()

    def _on_settings_changed(self, name: str, value: Any) -> None:
        if name == "threads":
            self.render_threads = int(value)
        elif name == "font":
            self.font_path = resolve_font_path(str(value))
            FONT_CACHE.clear()
            self._render_preview()
        elif name == "outline":
            self.layout.setdefault("global", {})["text_outline"] = int(value)
            self._render_preview()
        elif name == "startup_preset":
            self._startup_preset_path = str(value) if value else ""
            self.layout["_startup_preset"] = self._startup_preset_path
            # Zapisz tylko _startup_preset w def_layout.json (nie nadpisuj całości)
            try:
                def_layout = self.base_dir / "def_layout.json"
                if def_layout.exists():
                    data = json.loads(def_layout.read_text(encoding="utf-8"))
                else:
                    data = {}
                data["_startup_preset"] = self._startup_preset_path
                with open(def_layout, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
