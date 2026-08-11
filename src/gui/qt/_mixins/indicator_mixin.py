"""Mixin for indicator operations, layout setup, ranges, and data stream discovery.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from src.gui.indicator_schemas import BUILTIN_FIELDS
from src.gui.qt.models import DataStream, get_schema_for_form
from src.telemetry_extract import interpolate_value


class IndicatorMixin:
    def _on_stream_clicked(self, stream_key: str) -> None:
        """Użytkownik kliknął przycisk strumienia danych."""
        self._selected_stream_key = stream_key

        # Upewnij się, że wskaźnik istnieje w layoucie
        if "indicators" not in self.layout:
            self.layout["indicators"] = {}

        if stream_key not in self.layout["indicators"]:
            self._create_indicator(stream_key)
        else:
            # Jeśli istnieje ale jest wyłączony (np. z presetu) – włącz go
            cfg = self.layout["indicators"][stream_key]
            if not cfg.get("enabled", True):
                cfg["enabled"] = True
                print(f"[STREAM] Enabled existing indicator: {stream_key}", flush=True)

        cfg = self.layout["indicators"][stream_key]

        # Migracja: time_display zawsze używa form="time_display"
        if stream_key == "time_display" and cfg.get("form") != "time_display":
            cfg["form"] = "time_display"

        form = cfg.get("form", "text")
        schema = get_schema_for_form(form)

        self.signals.sig_properties_ready.emit(stream_key, schema, dict(cfg))

        try:
            self._render_preview()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.signals.sig_error.emit(
                f"Błąd renderowania podglądu: {e}"
            )

    def _create_indicator(self, key: str) -> None:
        """Tworzy domyślny wskaźnik w layoucie."""
        defaults: dict[str, Any] = {
            "enabled": True, "label": key, "x": 50.0, "y": 50.0,
            "rotation": 0, "form": "text", "font_size": 2.5,
            "size": 10.0, "thickness": 3, "min_val": 0, "max_val": 100,
            "ticks": 0, "show_value": True, "source": "gpmf", "decimals": 1,
            # Text
            "text_offset_x": 0.0, "text_offset_y": 0.0,
            # Gauge
            "start_angle": 180, "sweep_angle": 180,
            "needle_length": 1.1, "needle_width": 4, "needle_color": "#DC3232",
            "marker_size": 6, "marker_color": "#FFFFFF",
            # Chart
            "window_s": 30.0, "chart_color": "#00AAFF",
            "fill_color": "#00AAFF", "fill_alpha": 80,
            "grid_color": "#444444", "show_grid": True,
            "line_width": 2,
            # Segments
            "segments": 30, "segment_gap": 3, "segment_radius": 4,
            "inactive_alpha": 60, "inactive_color": "#333333",
            "direction": "horizontal", "grow_height": False,
            "show_min": True, "show_max": True, "show_label": True,
        }

        # Ustal źródło na podstawie klucza
        if key.startswith("fit_"):
            defaults["source"] = "fit"
        elif key in ("hr_text", "cad_text", "power_text", "atemp_text", "battery_text"):
            defaults["source"] = "gpx"

        # Ustal domyślną etykietę dla znanych kluczy
        _label_map = {
            "time_display": "Czas",
        }
        if key in _label_map:
            defaults["label"] = _label_map[key]

        # Specjalne domyślne wartości dla time_display
        if key == "time_display":
            defaults["show_date"] = True
            defaults["show_time"] = True
            defaults["show_elapsed"] = True
            defaults["show_avg_speed"] = True
            defaults["show_date_label"] = True
            defaults["date_label"] = "Data"
            defaults["show_time_label"] = True
            defaults["time_label"] = "Godzina"
            defaults["show_elapsed_label"] = True
            defaults["elapsed_label"] = "Czas"
            defaults["show_avg_speed_label"] = True
            defaults["avg_speed_label"] = "Średnia prędkość"
            defaults["font_size"] = 2.0
            defaults["date_font_size"] = 2.0
            defaults["time_font_size"] = 2.5
            defaults["elapsed_font_size"] = 2.5
            defaults["avg_speed_font_size"] = 2.0
            defaults["x"] = 2.0
            defaults["y"] = 3.0

        # Ustal domyślną formę na podstawie klucza (z rejestru indicators.py)
        from src.indicators import get_form_for_key
        _form, _form_overrides = get_form_for_key(key)
        defaults["form"] = _form
        defaults.update(_form_overrides)

        # time_display – własna forma, po get_form_for_key (jak track_map)
        if key == "time_display":
            defaults["form"] = "time_display"

        if key == "track_map":
            # Mapa – ma własne ustawienia niezależnie od rejestru
            defaults["form"] = "map"
            defaults["size"] = 18.0
            defaults["zoom"] = 16
            defaults["map_style"] = "light_all"
            defaults["marker_size"] = 7
            defaults["marker_color"] = "#FFFFFF"
            defaults["x"] = 2.0
            defaults["y"] = 15.0

        # Automatycznie ustaw min/max z danych telemetrycznych
        _min_v, _max_v = self._get_indicator_range(key)
        if _min_v is not None and _max_v is not None:
            defaults["min_val"] = _min_v
            defaults["max_val"] = _max_v

        self.layout["indicators"][key] = defaults

    def _get_indicator_range(self, key: str) -> tuple[float | None, float | None]:
        """Odczytaj min/max wartości z danych telemetrycznych dla wskaźnika.

        Zwraca (min_val, max_val) zaokrąglone do pełnych dziesiątek,
        lub (None, None) gdy brak danych.
        """
        samples: list[tuple] | None = None

        # FIT fields: fit_{field_name}_text
        if key.startswith("fit_") and key.endswith("_text"):
            field_name = key[4:-5]
            if self.telemetry.fit_data and field_name in self.telemetry.fit_data:
                samples = self.telemetry.fit_data[field_name]

        # GPX fields
        elif key in ("hr_text",):
            samples = self.telemetry.gpx_hr_samples
        elif key in ("cad_text",):
            samples = self.telemetry.gpx_cad_samples
        elif key in ("power_text",):
            samples = self.telemetry.gpx_power_samples
        elif key in ("atemp_text",):
            samples = self.telemetry.gpx_atemp_samples
        elif key == "speed_text_gpx":
            samples = self.telemetry.gpx_speed_samples

        # GPMF fields
        elif key in ("speed_text",):
            samples = self.telemetry.speed_samples
        elif key in ("dist_text",):
            samples = self.telemetry.track_samples
        elif key in ("alt_text",):
            samples = self.telemetry.alt_samples
        elif key in ("iso_text",):
            samples = self.telemetry.iso_samples
        elif key in ("exposure_text",):
            samples = self.telemetry.exposure_samples
        elif key in ("temp_text",):
            samples = self.telemetry.temperature_samples

        if not samples:
            return None, None

        vals = [v for _, v in samples if v is not None]
        if len(vals) < 2:
            return None, None

        raw_min = min(vals)
        raw_max = max(vals)

        is_temperature = key in ("temp_text", "atemp_text") or "temperature" in key or "atemp" in key

        # Temperature: min = 0 unless negative
        if is_temperature:
            if raw_min >= 0:
                min_val = 0.1
            else:
                min_val = math.floor(raw_min / 10.0) * 10.0
        else:
            min_val = math.floor(raw_min / 10.0) * 10.0

        max_val = math.ceil(raw_max / 10.0) * 10.0

        # Zabezpieczenie: max > min
        if max_val <= min_val:
            max_val = min_val + 10.0

        return min_val, max_val

    def _on_indicator_moved(self, key: str, x_norm: float, y_norm: float) -> None:
        """Przeciągnięto wskaźnik myszką — aktualizuj pozycję w layoucie (skala 0-100)."""
        if key not in self.layout.get("indicators", {}):
            return
        cfg = self.layout["indicators"][key]
        cfg["x"] = round(x_norm, 2)
        cfg["y"] = round(y_norm, 2)

        form = cfg.get("form", "text")
        schema = get_schema_for_form(form)
        self.signals.sig_properties_ready.emit(key, schema, dict(cfg))

        self._render_preview()

    def _on_delete_indicator(self, stream_key: str) -> None:
        """Usuwa wskaźnik z układu."""
        if (
            stream_key
            and stream_key in self.layout.get("indicators", {})
        ):
            del self.layout["indicators"][stream_key]
            if self.layout_mgr:
                self.layout_mgr.layout = self.layout
        self._selected_stream_key = ""
        self.signals.sig_properties_ready.emit("", [], {})
        self._render_preview()

    def _on_reset_layout(self) -> None:
        """Resetuje układ — usuwa wszystkie wskaźniki poza time_block."""
        # Zachowaj time_block jako bazowy wskaźnik daty/czasu, usuń resztę
        time_block_cfg = self.layout.get("indicators", {}).get(
            "time_block",
            {"enabled": True, "label": "Czas", "x": 1.8, "y": 3.0,
             "rotation": 0, "font_label": 1.25, "font_date": 2.0,
             "font_time": 2.0},
        )
        self.layout["indicators"] = {"time_block": time_block_cfg}
        self.layout["custom_texts"] = []
        if self.layout_mgr:
            self.layout_mgr.layout = self.layout
        self._selected_stream_key = ""
        self._render_preview()

    def _discover_data_streams(self) -> list[DataStream]:
        """Analizuje dane telemetryczne i zwraca listę dostępnych strumieni.

        To jest JEDYNE miejsce gdzie identyfikowane są dostępne dane.
        GUI NIGDY nie sprawdza bezpośrednio GPMF/GPX/FIT.
        """
        streams: list[DataStream] = []
        tm = self.telemetry

        # ── Czas (zawsze dostępny) ─────────────────────────────────────
        streams.append(DataStream(
            key="time_display", display_name="Czas", source="gpmf",
            category="other", unit="", suggested_form="text",
            sample_count=0,
            value_range=(0, 0),
        ))

        # ── GPMF (GoPro) ──────────────────────────────────────────────
        if tm.speed_samples:
            vals = [v for _, v in tm.speed_samples]
            streams.append(DataStream(
                key="speed_text", display_name="Prędkość", source="gpmf",
                category="gps", unit="km/h", suggested_form="gauge",
                sample_count=len(tm.speed_samples),
                value_range=(min(vals), max(vals)),
            ))
        if tm.track_samples:
            vals = [v for _, v in tm.track_samples]
            streams.append(DataStream(
                key="dist_text", display_name="Dystans", source="gpmf",
                category="gps", unit="km", suggested_form="text",
                sample_count=len(tm.track_samples),
                value_range=(0, max(vals)),
            ))

        if tm.track_samples or tm.fit_gps_track or tm.gpx_gps_track or tm.gps_track:
            streams.append(DataStream(
                key="track_map", display_name="Mapa", source="fit",
                category="gps", unit="", suggested_form="map",
                sample_count=max(
                    len(tm.track_samples),
                    len(tm.fit_gps_track),
                    len(tm.gpx_gps_track),
                    len(tm.gps_track),
                ),
                value_range=(0, 0),
            ))
        if tm.alt_samples:
            vals = [v for _, v in tm.alt_samples]
            streams.append(DataStream(
                key="alt_text", display_name="Wysokość", source="gpmf",
                category="gps", unit="m", suggested_form="bar",
                sample_count=len(tm.alt_samples),
                value_range=(min(vals), max(vals)),
            ))
        if tm.iso_samples:
            vals = [v for _, v in tm.iso_samples]
            streams.append(DataStream(
                key="iso_text", display_name="ISO", source="gpmf",
                category="camera", unit="ISO", suggested_form="text",
                sample_count=len(tm.iso_samples),
                value_range=(min(vals), max(vals)),
            ))
        if tm.exposure_samples:
            vals = [v for _, v in tm.exposure_samples]
            streams.append(DataStream(
                key="exposure_text", display_name="Czas naświetlania",
                source="gpmf", category="camera", unit="s",
                suggested_form="text",
                sample_count=len(tm.exposure_samples),
                value_range=(min(vals), max(vals)),
            ))
        if tm.temperature_samples:
            vals = [v for _, v in tm.temperature_samples]
            streams.append(DataStream(
                key="temp_text", display_name="Temperatura", source="gpmf",
                category="camera", unit="°C", suggested_form="text",
                sample_count=len(tm.temperature_samples),
                value_range=(min(vals), max(vals)),
            ))

        # ── GPX ───────────────────────────────────────────────────────
        if tm.gpx_speed_samples:
            vals = [v for _, v in tm.gpx_speed_samples]
            streams.append(DataStream(
                key="speed_text_gpx", display_name="Prędkość (GPX)",
                source="gpx", category="gps", unit="km/h",
                suggested_form="gauge",
                sample_count=len(tm.gpx_speed_samples),
                value_range=(min(vals), max(vals)),
            ))
        if tm.gpx_hr_samples:
            vals = [v for _, v in tm.gpx_hr_samples]
            streams.append(DataStream(
                key="hr_text", display_name="Tętno", source="gpx",
                category="sensor", unit="BPM", suggested_form="text",
                sample_count=len(tm.gpx_hr_samples),
                value_range=(min(vals), max(vals)),
            ))
        if tm.gpx_cad_samples:
            vals = [v for _, v in tm.gpx_cad_samples]
            streams.append(DataStream(
                key="cad_text", display_name="Kadencja", source="gpx",
                category="sensor", unit="rpm", suggested_form="text",
                sample_count=len(tm.gpx_cad_samples),
                value_range=(min(vals), max(vals)),
            ))
        if tm.gpx_power_samples:
            vals = [v for _, v in tm.gpx_power_samples]
            streams.append(DataStream(
                key="power_text", display_name="Moc", source="gpx",
                category="sensor", unit="W", suggested_form="bar",
                sample_count=len(tm.gpx_power_samples),
                value_range=(min(vals), max(vals)),
            ))
        if tm.gpx_atemp_samples:
            vals = [v for _, v in tm.gpx_atemp_samples]
            streams.append(DataStream(
                key="atemp_text", display_name="Temp. otoczenia", source="gpx",
                category="sensor", unit="°C", suggested_form="text",
                sample_count=len(tm.gpx_atemp_samples),
                value_range=(min(vals), max(vals)),
            ))

        # ── FIT (dynamicznie) ─────────────────────────────────────────
        for field_name in sorted(tm.fit_data.keys()):
            if field_name in ("speed", "alt", "track", "lat", "lon", "timestamp"):
                continue
            samples = tm.fit_data[field_name]
            vals = [v for _, v in samples if v is not None]
            if not vals:
                continue

            display = field_name.replace("_", " ").title()
            unit_map = {
                "heart_rate": "BPM", "cadence": "rpm", "power": "W",
                "temperature": "°C", "altitude": "m",
            }
            unit = unit_map.get(field_name, "")

            key = f"fit_{field_name}_text"
            streams.append(DataStream(
                key=key, display_name=f"{display} (FIT)", source="fit",
                category="sensor", unit=unit, suggested_form="text",
                sample_count=len(samples),
                value_range=(min(vals), max(vals)),
            ))

        return streams

    @staticmethod
    def _window_average(
        samples: list, target_dt: datetime, window: int,
    ) -> float:
        """Średnia `window` próbek wokół target_dt."""
        if not samples or window < 2:
            return interpolate_value(samples, target_dt) if samples else 0.0
        # Normalise timezone (samples may be naive, target_dt may be aware)
        ref_dt = target_dt
        if ref_dt.tzinfo is not None:
            ref_dt = ref_dt.replace(tzinfo=None)
        idx = 0
        for i, (dt, _) in enumerate(samples):
            cmp_dt = dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
            if cmp_dt >= ref_dt:
                idx = i
                break
        else:
            idx = len(samples) - 1
        half = window // 2
        start = max(0, idx - half)
        end = min(len(samples), start + window)
        start = max(0, end - window)
        nearby = [v for _, v in samples[start:end]]
        if not nearby:
            return interpolate_value(samples, target_dt)
        return sum(nearby) / len(nearby)

    def _resolve_smoothed_value(
        self, ind_key: str, ind_cfg: dict, target_dt: datetime, window: int,
    ) -> float | None:
        """Zwraca wartość wygładzoną per-wskaźnik, lub None gdy nie dotyczy."""
        source = ind_cfg.get("source", "gpmf")
        if "speed" in ind_key:
            spd_s, _, _ = self.telemetry.get_samples_for_source(source)
            return self._window_average(spd_s, target_dt, window)
        if "dist" in ind_key:
            _, trk_s, _ = self.telemetry.get_samples_for_source(source)
            return self._window_average(trk_s, target_dt, window)
        if "alt" in ind_key:
            _, _, alt_s = self.telemetry.get_samples_for_source(source)
            return self._window_average(alt_s, target_dt, window)
        if "power" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("power"), target_dt, window)
        if "hr" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("hr"), target_dt, window)
        if "cad" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("cad"), target_dt, window)
        if "atemp" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("atemp"), target_dt, window)
        if "battery" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("battery"), target_dt, window)
        if "iso" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("iso"), target_dt, window)
        if "exposure" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("exposure"), target_dt, window)
        if "temp" in ind_key and "atemp" not in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("temperature"), target_dt, window)
        if ind_key.startswith("fit_") and ind_key.endswith("_text"):
            field_name = ind_key[4:-5]
            return self._window_average(
                self.telemetry.resolve_samples(field_name), target_dt, window)
        return None
