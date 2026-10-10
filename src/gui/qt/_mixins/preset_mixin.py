"""Mixin for presets, layouts, properties and general settings.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog

from src.gui.indicator_schemas import BUILTIN_FIELDS
from src.gui.qt.models import (
    _sync_size_font_fields,
    get_schema_for_indicator,
    normalize_indicator_decimal_defaults,
)
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
            from src.indicators.compositor import normalize_layout_for_save, sanitize_layout_for_json
            layout_copy = normalize_layout_for_save(self.layout)
            if hasattr(self, "_cut_regions") and self._cut_regions:
                layout_copy["cut_regions"] = self._cut_regions
            else:
                layout_copy.pop("cut_regions", None)
            layout_copy = sanitize_layout_for_json(layout_copy)
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
            normalize_indicator_decimal_defaults(loaded)
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
                from src.indicators.availability import compute_indicator_availability, log_indicator_availability
                avail = compute_indicator_availability(self.layout, telemetry=self.telemetry)
                self.layout["_indicator_availability"] = {k: v[0] for k, v in avail.items()}
                log_indicator_availability(avail)
                streams = self._discover_data_streams()
                self.signals.sig_data_streams_ready.emit(streams)
            if hasattr(self, "_map_preload_provider_switch"):
                from src.gui.qt._mixins.project_mixin import _map_provider_from_layout
                self._map_preload_provider_switch(_map_provider_from_layout(self.layout))
            render_tab = getattr(getattr(self, "ui", None), "render_tab", None) or getattr(getattr(self, "ui", None), "_render_tab", None) or getattr(self, "render_tab", None) or getattr(self, "_render_tab", None)
            if render_tab is not None and hasattr(render_tab, "apply_export_settings"):
                render_tab.apply_export_settings(self.layout.get("export_settings", {}))
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

        # Jeśli zmieniono formę, pole semantyczne lub styl bara — wyślij nowy schemat
        if (
            (field_name == "form" and value != old_form)
            or (field_name == "field")
            or (field_name == "bar_style" and cfg.get("form") in ("bar", "segment_bar"))
            or (field_name == "chart_time_scope" and cfg.get("form") == "chart")
        ):
            from src.telemetry_resolver import is_integer_only_field
            if is_integer_only_field(stream_key, cfg):
                cfg.pop("decimals", None)
                cfg.pop("decimal_places", None)
            schema = get_schema_for_indicator(
                stream_key,
                cfg.get("form", "text"),
                bar_style=cfg.get("bar_style", "ruler"),
                chart_time_scope=cfg.get("chart_time_scope", "activity"),
                cfg=cfg,
            )
            self.signals.sig_properties_ready.emit(stream_key, schema, dict(cfg))

        # Synchronizuj layout_mgr
        if self.layout_mgr:
            self.layout_mgr.layout = self.layout

        # Inwalidacja cache przygotowania i renderowania wskaźników
        # Każda zmiana właściwości (kolor, geometria, skala, styl) musi natychmiast
        # unieważnić cache, aby aktualna klatka Preview odświeżyła się od razu bez seek.
        self._clear_caches()

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

        if stream_key == "track_map" and field_name in ("map_style", "zoom", "source", "gps_source", "map_orientation", "enabled"):
            try:
                if hasattr(self, "_trigger_map_background_prefetch"):
                    self._trigger_map_background_prefetch(reason=f"prop_{field_name}")
            except Exception:
                pass

        # Oznacz układ w RAM jako zmodyfikowany
        self._layout_dirty = True

        # Zapisz bieżący stan sesji do AppData (nigdy obok materiału wideo)
        self._save_session_layout()

        # Odśwież podgląd
        self._render_preview()

    def get_session_layout_path(self) -> Path:
        """Zwraca ścieżkę do roboczego layoutu sesji w AppData."""
        import os
        base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or (Path.home() / ".bikeridehud"))
        d = base / "SportCamHUD" / "session"
        d.mkdir(parents=True, exist_ok=True)
        return d / "active_layout.json"

    def get_project_layout_path(self) -> Optional[Path]:
        """Zwraca ścieżkę do roboczego layoutu sesji w AppData (zastąpiło zaśmiecające sidecary)."""
        return self.get_session_layout_path()

    def _save_session_layout(self) -> Optional[Path]:
        """Zapisuje stan roboczy layoutu w katalogu aplikacji (%LOCALAPPDATA%\\SportCamHUD\\session\\).

        NIGDY nie tworzy ani nie modyfikuje plików w katalogu z materiałami wideo!
        """
        try:
            from src.indicators.compositor import normalize_layout_for_save, sanitize_layout_for_json
            saved = normalize_layout_for_save(self.layout)
            # P0-FIX: cut_regions are runtime IN/OUT state managed by RenderTab
            # per-session and must NOT be persisted to the sidecar layout.
            # Serializing them poisons subsequent sessions: scrubbing is locked
            # to the previously-set range and render is capped at that duration.
            saved.pop("cut_regions", None)

            render_tab = getattr(getattr(self, "ui", None), "render_tab", None) or getattr(getattr(self, "ui", None), "_render_tab", None) or getattr(self, "render_tab", None) or getattr(self, "_render_tab", None)
            if render_tab is not None:
                exp = saved.setdefault("export_settings", {})
                if hasattr(render_tab, "cmb_nvidia_backend"):
                    exp["nvidia_backend"] = render_tab.cmb_nvidia_backend.currentData()
                if hasattr(render_tab, "cmb_nvidia_codec"):
                    exp["codec"] = render_tab.cmb_nvidia_codec.currentText()
                if hasattr(render_tab, "cmb_intel_codec"):
                    exp["intel_codec"] = render_tab.cmb_intel_codec.currentData()
                if hasattr(render_tab, "cmb_encoder_profile"):
                    exp["encoder_profile"] = render_tab.cmb_encoder_profile.currentData()
                if hasattr(render_tab, "cmb_nvidia_quality"):
                    exp["quality_profile"] = render_tab.cmb_nvidia_quality.currentData() or render_tab.cmb_nvidia_quality.currentText()
                if hasattr(render_tab, "edit_bitrate"):
                    exp["bitrate"] = render_tab.edit_bitrate.text().strip()
                if hasattr(render_tab, "chk_compression_analysis"):
                    exp["compression_analysis"] = render_tab.chk_compression_analysis.isChecked()
                if hasattr(render_tab, "chk_original_gpmf"):
                    exp["preserve_original_gpmf"] = render_tab.chk_original_gpmf.isChecked()

            saved = sanitize_layout_for_json(saved)
            sess_path = self.get_session_layout_path()
            tmp = sess_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, sess_path)
            return sess_path
        except Exception as e:
            print(f"[SessionLayout] Błąd zapisu layoutu sesji: {e}", flush=True)
            return None

    def _save_project_layout(self) -> Optional[Path]:
        """Kompatybilność wsteczna: przekierowuje do bezpiecznego zapisu sesji w AppData."""
        return self._save_session_layout()

    def _save_current_layout_to_default(self) -> None:
        """Trwały zapis całego stanu układu (wszystkie wskaźniki, per-indicator font, icon, pozycje) do def_layout.json."""
        try:
            base = getattr(self, "base_dir", None)
            if not base:
                return
            from src.indicators.compositor import normalize_layout_for_save, sanitize_layout_for_json
            def_layout = Path(base) / "def_layout.json"
            self._startup_preset_path = ""
            self.layout["_startup_preset"] = ""
            saved = normalize_layout_for_save(self.layout)
            saved["_startup_preset"] = ""
            # P0-FIX: same as _save_project_layout — do not persist runtime
            # IN/OUT cut_regions to the global default layout.
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
            amd_codec_val = getattr(self, "amd_codec", "hevc") or "hevc"
            saved.setdefault("global", {})["amd_codec"] = amd_codec_val
            amd_quality = getattr(self, "amd_encoder_quality", "FAST") or "FAST"
            saved.setdefault("global", {})["amd_encoder_quality"] = amd_quality
            saved.setdefault("global", {})["render_mode"] = getattr(self, "render_mode", "gpu") or "gpu"
            integrations_cfg = self.layout.get("integrations")
            if integrations_cfg:
                saved["integrations"] = dict(integrations_cfg)

            saved = sanitize_layout_for_json(saved)
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
        elif name == "amd_codec":
            self.amd_codec = str(value).lower()
        elif name == "amd_encoder_quality":
            self.amd_encoder_quality = str(value).upper()
        elif name == "render_mode":
            self.render_mode = str(value).lower()
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
        elif name == "charts_skip_pauses":
            self.layout["charts_skip_pauses"] = bool(value)
            self._chart_data_cache = None
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
        elif name in ("auto_activity_source", "garmin_username", "strava_client_id"):
            self.layout.setdefault("integrations", {})[name] = str(value)
            self._layout_dirty = True
            try:
                def_layout = self.base_dir / "def_layout.json"
                if def_layout.exists():
                    data = json.loads(def_layout.read_text(encoding="utf-8"))
                else:
                    data = {}
                data.setdefault("integrations", {})[name] = str(value)
                with open(def_layout, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
