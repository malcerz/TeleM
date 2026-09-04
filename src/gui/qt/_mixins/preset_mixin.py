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
try:
    from src.indicators.helpers import _STATIC_CACHE
except Exception:
    _STATIC_CACHE = None  # type: ignore[assignment]


class PresetMixin:
    def _on_save_preset(self) -> None:
        """Zapisuje obecny układ do pliku JSON wybranego przez użytkownika (Save File Dialog)."""
        path, _ = QFileDialog.getSaveFileName(
            None, "Zapisz preset układu", "",
            "JSON (*.json);;Wszystkie (*.*)",
        )
        if not path:
            return
        try:
            from src.indicators.compositor import normalize_layout_for_save
            layout_copy = normalize_layout_for_save(self.layout)
            if hasattr(self, "_cut_regions") and self._cut_regions:
                layout_copy["cut_regions"] = self._cut_regions
            else:
                layout_copy.pop("cut_regions", None)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(layout_copy, f, indent=2, ensure_ascii=False)
            self._layout_dirty = False
            print(f"[Preset] Zapisano preset użytkownika do {path}", flush=True)
        except Exception as e:
            self.signals.sig_error.emit(f"Błąd zapisu presetu: {e}")

    def _on_load_preset(self) -> None:
        """Wczytuje układ z pliku JSON (User Preset z Open File Dialog) i odświeża podgląd."""
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
            self._user_preset_path = str(path)
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
            if hasattr(self, "_map_preload_provider_switch"):
                from src.gui.qt._mixins.project_mixin import _map_provider_from_layout
                self._map_preload_provider_switch(_map_provider_from_layout(self.layout))
            self._render_preview()
            print(f"[Preset] Wczytano preset użytkownika z {path} (plik chroniony przed autosave)", flush=True)
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

        # Inwalidacja cache przygotowania — gdy zmienią się dane wpływające na geometrię/wygląd
        if field_name in (
            "source", "form", "bar_style", "min_val", "max_val", "chart_time_scope", "chart_window_s",
            "ticks", "thickness", "major_ticks", "minor_ticks", "segments",
            "major_tick_length", "minor_tick_length", "major_tick_thickness", "minor_tick_thickness",
            "needle_width", "needle_length", "needle_color",
            "font", "value_font", "label_font", "range_font",
        ):
            self._clear_caches()
            if field_name in ("font", "value_font", "label_font", "range_font"):
                try:
                    from src.indicators.helpers import FONT_CACHE
                    FONT_CACHE.clear()
                except Exception:
                    pass
                # Wyczyść statyczny cache tarcz gauge (zawiera font w kluczu)
                if _STATIC_CACHE is not None:
                    _STATIC_CACHE.clear()

        # Map provider/style switch (ETAP MAP PRELOAD): reuse the same
        # MapContext geometry, restart the overview preload for the new
        # provider (Standard → Satellite).  FIT/GPS is NOT re-parsed; the
        # generation bump guarantees a stale job cannot overwrite the new one.
        if field_name == "map_style" and stream_key == "track_map":
            try:
                if hasattr(self, "_map_preload_provider_switch"):
                    self._map_preload_provider_switch(str(value))
            except Exception:
                pass

        # Oznacz układ w RAM jako zmodyfikowany
        self._layout_dirty = True

        # Jeśli aktualnie załadowany jest film, aktualizuj stan roboczy projektu (.layout.json).
        # NIGDY nie modyfikuj wczytanego presetu użytkownika (_user_preset_path) ani def_layout.json!
        if getattr(self, "video_path", None):
            self._save_project_layout()

        # Odśwież podgląd
        self._render_preview()

    def get_project_layout_path(self) -> Optional[Path]:
        """Zwraca ścieżkę do roboczego layoutu projektu powiązanego z aktualnym filmem (np. Video/GX010115.layout.json)."""
        video = getattr(self, "video_path", None)
        if not video:
            return None
        return Path(video).with_suffix(".layout.json")

    def _save_project_layout(self) -> Optional[Path]:
        """Zapisuje bieżący stan roboczy layoutu dla konkretnego filmu (sidecar .layout.json).

        Przechowuje aktualny stan pracy nad filmem. NIGDY nie modyfikuje wczytanego
        presetu użytkownika (self._user_preset_path) ani pliku szablonu def_layout.json.
        """
        proj_path = self.get_project_layout_path()
        if not proj_path:
            return None
        try:
            from src.indicators.compositor import normalize_layout_for_save
            saved = normalize_layout_for_save(self.layout)
            if hasattr(self, "_cut_regions") and self._cut_regions:
                saved["cut_regions"] = self._cut_regions
            else:
                saved.pop("cut_regions", None)
            with open(proj_path, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2, ensure_ascii=False)
            print(f"[ProjectLayout] Zapisano roboczy layout filmu do {proj_path}", flush=True)
            return proj_path
        except Exception as e:
            print(f"[ProjectLayout] Błąd zapisu layoutu projektu: {e}", flush=True)
            return None

    def _save_current_layout_to_default(self) -> None:
        """Trwały zapis całego stanu układu (wszystkie wskaźniki, per-indicator font, icon, pozycje) do def_layout.json."""
        try:
            base = getattr(self, "base_dir", None)
            if not base:
                return
            from src.indicators.compositor import normalize_layout_for_save
            def_layout = Path(base) / "def_layout.json"
            self._startup_preset_path = ""
            self.layout["_startup_preset"] = ""
            saved = normalize_layout_for_save(self.layout)
            saved["_startup_preset"] = ""
            if hasattr(self, "_cut_regions") and self._cut_regions:
                saved["cut_regions"] = self._cut_regions
            else:
                saved.pop("cut_regions", None)

            # Persystuj globalny font oraz outline
            font_family = getattr(self, "_global_font_family", "") or ""
            if font_family:
                saved.setdefault("global", {})["font"] = font_family
            elif def_layout.exists():
                try:
                    existing = json.loads(def_layout.read_text(encoding="utf-8"))
                    if "font" in existing.get("global", {}):
                        saved.setdefault("global", {})["font"] = existing["global"]["font"]
                except Exception:
                    pass

            text_outline = self.layout.get("global", {}).get("text_outline")
            if text_outline is not None:
                saved.setdefault("global", {})["text_outline"] = text_outline

            amd_mode = getattr(self, "amd_decode_mode", "gpu") or "gpu"
            saved.setdefault("global", {})["amd_decode_mode"] = amd_mode

            with open(def_layout, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2, ensure_ascii=False)
            self._layout_dirty = False
            print(f"[Layout] Zapisano aktualny layout do {def_layout} (wskaźników: {len(saved.get('indicators', {}))})", flush=True)
        except Exception as e:
            print(f"[Layout] Błąd zapisu do def_layout.json: {e}", flush=True)

    def _save_global_settings_to_default(self) -> None:
        """Persystuje aktualny layout i globalne ustawienia do def_layout.json."""
        self._save_current_layout_to_default()

    def _on_save_global_settings(self) -> None:
        """Jawny zapis aktualnego całego layoutu (wszystkie wskaźniki, właściwości, fonty) do def_layout.json."""
        self._save_current_layout_to_default()
        print("[Settings] Zapisano cały układ użytkownika do def_layout.json", flush=True)

    def _on_settings_changed(self, name: str, value: Any) -> None:
        if name == "threads":
            self.render_threads = int(value)
        elif name == "amd_decode_mode":
            self.amd_decode_mode = str(value).lower()
        elif name == "font":
            family = str(value)
            self._global_font_family = family
            self.font_path = resolve_font_path(family)
            FONT_CACHE.clear()
            # Wyczyść statyczny cache tarcz gauge (klucz zawiera font_path)
            if _STATIC_CACHE is not None:
                _STATIC_CACHE.clear()
            self._clear_caches()
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
