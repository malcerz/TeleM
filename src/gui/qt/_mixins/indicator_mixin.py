"""Mixin for indicator operations, layout setup, ranges, and data stream discovery.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from src.gui.indicator_schemas import BUILTIN_FIELDS
from src.gui.qt.models import (
    DataStream,
    canonical_defaults,
    compass_indicator_fields,
    get_schema_for_form,
)
from src.telemetry_extract import interpolate_value


class IndicatorMixin:
    def _on_stream_clicked(self, stream_key: str) -> None:
        """Użytkownik kliknął przycisk strumienia danych."""
        self._selected_stream_key = stream_key

        # Invalidate chart and prepare caches so newly added indicators compute freshly
        self._chart_data_cache = None
        if hasattr(self, "_prepare_cache") and isinstance(self._prepare_cache, dict):
            self._prepare_cache.clear()

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
        bar_style = cfg.get("bar_style", "ruler")
        schema = (
            compass_indicator_fields()
            if stream_key == "compass"
            else get_schema_for_form(
                form, bar_style=bar_style,
                chart_time_scope=cfg.get("chart_time_scope", "activity"),
            )
        )

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
            "size": 2.5, "thickness": 3, "min_val": 0, "max_val": 100,
            "ticks": 0, "show_value": True, "source": "gpmf", "decimals": 1,
            # Text
            "text_offset_x": 0.0, "text_offset_y": 0.0,
            # Gauge
            "start_angle": 180, "sweep_angle": 180,
            "needle_length": 1.1, "needle_width": 4, "needle_color": "#DC3232",
            "marker_size": 6, "marker_color": "#FFFFFF",
            # Chart
            "chart_window_s": 60.0, "chart_color": "#00AAFF",
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
            if key.endswith("_text"):
                field_name = key[4:-5]
                defaults["field"] = field_name
                catalog = getattr(getattr(self, "telemetry", None), "fit_data", {})
                cat_dict = getattr(catalog, "field_catalog", {}) if catalog else {}
                meta = cat_dict.get(field_name, {})
                if field_name in ("enhanced_speed", "speed"):
                    defaults["label"] = "Speed"
                elif field_name in ("enhanced_altitude", "altitude"):
                    defaults["label"] = "Altitude"
                else:
                    defaults["label"] = meta.get("display_name") or field_name.replace("_", " ").title()
                defaults["unit"] = meta.get("unit") or ""
                if not defaults["unit"]:
                    unit_map = {
                        "heart_rate": "BPM", "cadence": "rpm", "power": "W",
                        "temperature": "°C", "altitude": "m", "curVpower": "W",
                        "solar": "%", "solar_pct": "%", "battery": "%", "battery_pct": "%",
                        "discharge": "%/h", "speed": "km/h", "enhanced_speed": "km/h",
                        "enhanced_altitude": "m", "distance": "km",
                    }
                    defaults["unit"] = unit_map.get(field_name, "")
                if defaults["unit"] in ("°C", "C", "degC") or "temp" in field_name.lower():
                    defaults["major_step"] = 1.0
                elif defaults["unit"] == "km" or "dist" in field_name.lower():
                    defaults["major_step"] = 1.0
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
        if defaults.get("form") == "text":
            defaults["size"] = defaults["font_size"]

        # time_display – własna forma, po get_form_for_key (jak track_map)
        if key == "time_display":
            defaults["form"] = "time_display"

        if key == "track_map":
            # Mapa – ma własne ustawienia niezależnie od rejestru
            defaults["form"] = "map"
            defaults["size"] = 18.0
            defaults["zoom"] = 16
            defaults["map_orientation"] = "north_up"
            defaults["map_style"] = "light_all"
            defaults["marker_size"] = 7
            defaults["marker_color"] = "#FFFFFF"
            defaults["x"] = 2.0
            defaults["y"] = 15.0

        if key == "compass":
            defaults["label"] = "COMPASS"
            defaults["form"] = "gauge"
            defaults["gauge_style"] = "compass"
            defaults["field"] = "heading"
            defaults["source"] = "gpmf"
            defaults["x"] = 70.65
            defaults["y"] = 20.0
            defaults["size"] = 7.8
            defaults["font_size"] = 1.2
            defaults["show_value"] = True
            defaults["unit"] = "°"
            defaults["opacity"] = 1.0
            defaults["compass_show_cardinals"] = True
            defaults["compass_show_heading"] = True
            defaults["compass_heading_format"] = "03d"
            defaults["compass_tick_degrees"] = 15
            defaults["compass_major_tick_degrees"] = 45
            defaults["compass_tick_color"] = "#DDE7F2"
            defaults["compass_cardinal_color"] = "#FFFFFF"
            defaults["compass_needle_color"] = "#FFD42A"
            defaults["compass_ring_color"] = "#B8C7D9"
            defaults["compass_heading_color"] = "#FFFFFF"

        if key == "slope_text":
            defaults["label"] = "SLOPE"
            defaults["field"] = "slope"
            defaults["form"] = "bar"
            defaults["bar_style"] = "slope"
            defaults["source"] = "gpmf"
            defaults["x"] = 73.0
            defaults["y"] = 52.0
            defaults["size"] = 20.0
            defaults["font_size"] = 1.35
            defaults["unit"] = "%"
            defaults["min_val"] = -20.0
            defaults["max_val"] = 20.0
            defaults["major_tick"] = 5.0
            defaults["minor_tick"] = 1.0
            defaults["show_value"] = True
            defaults["show_label"] = True
            defaults["show_range_labels"] = True
            defaults["show_units"] = True
            defaults["decimals"] = 1
            defaults["opacity"] = 1.0
            defaults["track_color"] = "#8D9AA7"
            defaults["tick_color"] = "#DDE7F2"
            defaults["zero_tick_color"] = "#FFFFFF"
            defaults["marker_color"] = "#FFD42A"
            defaults["marker_border_color"] = "#FFFFFF"

        # Automatycznie ustaw min/max z danych telemetrycznych
        _min_v, _max_v = self._get_indicator_range(key)
        if _min_v is not None and _max_v is not None:
            defaults["min_val"] = _min_v
            defaults["max_val"] = _max_v

        # ── Kompletny config: uzupełnij brakujące pola kanonicznymi
        # defaultami ze schematu (JEDNO źródło prawdy).
        # Dzięki temu model == Property Editor == Preview/Renderer od pierwszej
        # chwili, bez „przeskoku" przy pierwszej edycji właściwości.
        if key == "compass":
            _schema = compass_indicator_fields()
        else:
            _schema = get_schema_for_form(
                defaults.get("form", "text"),
                bar_style=defaults.get("bar_style", "ruler"),
                chart_time_scope=defaults.get("chart_time_scope", "activity"),
            )
        for _field_name, _field_default in canonical_defaults(_schema).items():
            if _field_name not in defaults:
                defaults[_field_name] = _field_default

        self.layout["indicators"][key] = defaults

    def _get_indicator_range(self, key: str) -> tuple[float | None, float | None]:
        """Odczytaj min/max wartości z danych telemetrycznych dla wskaźnika.

        Zwraca (min_val, max_val) zaokrąglone do pełnych dziesiątek,
        lub (None, None) gdy brak danych.
        """
        if key == "slope_text":
            return -20.0, 20.0

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
        elif key in {
            "accel_x_text", "accel_y_text", "accel_z_text", "accel_magnitude_text",
            "gyro_x_text", "gyro_y_text", "gyro_z_text", "gyro_magnitude_text",
        }:
            samples = getattr(self.telemetry, key[:-5] + "_samples", [])

        if not samples:
            return None, None

        vals = [v for _, v in samples if v is not None]
        if len(vals) < 2:
            return None, None

        is_distance = key in ("dist_text", "dist_visual", "fit_distance_text") or "distance" in key or "dist_" in key
        if is_distance:
            vals = [v / 1000.0 for v in vals]
            raw_min = min(vals)
            raw_max = max(vals)
            min_val = 0.0
            max_val = math.ceil(raw_max)
            if max_val <= min_val:
                max_val = min_val + 5.0
            return min_val, max_val

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
        bar_style = cfg.get("bar_style", "ruler")
        schema = get_schema_for_form(
            form, bar_style=bar_style,
            chart_time_scope=cfg.get("chart_time_scope", "activity"),
        )
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
        heading_source = None
        heading_count = 0
        if tm.heading_samples:
            heading_source, heading_count = "gpmf", len(tm.heading_samples)
        elif tm.fit_data.get("heading"):
            heading_source, heading_count = "fit", len(tm.fit_data["heading"])
        elif tm.gpx_heading_samples:
            heading_source, heading_count = "gpx", len(tm.gpx_heading_samples)
        if heading_source is not None:
            streams.append(DataStream(
                key="compass", display_name="Compass / GPS course",
                source=heading_source, category="gps", unit="°",
                suggested_form="gauge", sample_count=heading_count,
                value_range=(0.0, 360.0),
            ))
        slope_source = None
        slope_samples = []
        if tm.slope_samples:
            slope_source, slope_samples = "gpmf", tm.slope_samples
        elif tm.fit_data.get("slope"):
            slope_source, slope_samples = "fit", tm.fit_data["slope"]
        elif tm.gpx_slope_samples:
            slope_source, slope_samples = "gpx", tm.gpx_slope_samples
        if slope_source is not None:
            vals = [v for _, v in slope_samples if v is not None]
            if vals:
                streams.append(DataStream(
                    key="slope_text", display_name="Slope / Grade",
                    source=slope_source, category="gps", unit="%",
                    suggested_form="bar", sample_count=len(slope_samples),
                    value_range=(min(vals), max(vals)),
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
        imu_streams = (
            ("accel_x", "Accelerometer X", "m/s"),
            ("accel_y", "Accelerometer Y", "m/s"),
            ("accel_z", "Accelerometer Z", "m/s"),
            ("accel_magnitude", "Accelerometer Magnitude", "m/s"),
            ("gyro_x", "Gyroscope X", "rad/s"),
            ("gyro_y", "Gyroscope Y", "rad/s"),
            ("gyro_z", "Gyroscope Z", "rad/s"),
            ("gyro_magnitude", "Gyroscope Magnitude", "rad/s"),
        )
        for field_name, display_name, unit in imu_streams:
            samples = getattr(tm, f"{field_name}_samples", [])
            if samples:
                vals = [v for _, v in samples]
                streams.append(DataStream(
                    key=f"{field_name}_text", display_name=display_name,
                    source="gpmf", category="sensor", unit=unit,
                    suggested_form="chart", sample_count=len(samples),
                    value_range=(min(vals), max(vals)),
                ))

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
        from src.indicators import get_form_for_key
        for field_name in sorted(tm.fit_data.keys()):
            if field_name in ("track", "lat", "lon", "timestamp", "heading"):
                continue
            if field_name == "speed" and "enhanced_speed" in tm.fit_data:
                continue
            if field_name == "alt" and "enhanced_altitude" in tm.fit_data:
                continue
            samples = tm.fit_data[field_name]
            vals = [v for _, v in samples if v is not None]
            if not vals and not samples:
                continue

            catalog = getattr(tm.fit_data, "field_catalog", {}) or {}
            meta = catalog.get(field_name, {})
            raw_display = meta.get("display_name") or field_name.replace("_", " ").title()
            unit = meta.get("unit", "")
            if not unit:
                unit_map = {
                    "heart_rate": "BPM", "cadence": "rpm", "power": "W",
                    "temperature": "°C", "altitude": "m", "curVpower": "W",
                    "solar": "%", "solar_pct": "%", "battery": "%", "battery_pct": "%",
                    "discharge": "%/h", "speed": "km/h", "enhanced_speed": "km/h",
                    "enhanced_altitude": "m",
                }
                unit = unit_map.get(field_name, "")

            key = f"fit_{field_name}_text"
            form, _ = get_form_for_key(key)
            val_min = min(vals) if vals else 0.0
            val_max = max(vals) if vals else 100.0

            display_suffix = "" if "(FIT)" in raw_display else " (FIT)"
            display_name = f"{raw_display}{display_suffix}"

            category = "sensor"
            if field_name in ("speed", "enhanced_speed", "alt", "enhanced_altitude", "distance"):
                category = "gps"

            streams.append(DataStream(
                key=key, display_name=display_name, source="fit",
                category=category, unit=unit, suggested_form=form,
                sample_count=len(samples),
                value_range=(val_min, val_max),
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
                self.telemetry.resolve_samples("power", source, indicator_key=ind_key), target_dt, window)
        if "hr" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("hr", source, indicator_key=ind_key), target_dt, window)
        if "cad" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("cad", source, indicator_key=ind_key), target_dt, window)
        if "atemp" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("atemp", source, indicator_key=ind_key), target_dt, window)
        if "battery" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("battery", source, indicator_key=ind_key), target_dt, window)
        if "iso" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("iso", source, indicator_key=ind_key), target_dt, window)
        if "exposure" in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("exposure", source, indicator_key=ind_key), target_dt, window)
        if "temp" in ind_key and "atemp" not in ind_key:
            return self._window_average(
                self.telemetry.resolve_samples("temperature", source, indicator_key=ind_key), target_dt, window)
        if ind_key.startswith("fit_") and ind_key.endswith("_text"):
            field_name = ind_key[4:-5]
            return self._window_average(
                self.telemetry.resolve_samples(field_name, "fit", indicator_key=ind_key), target_dt, window)
        imu_field = {
            "accel_x_text": "accel_x", "accel_y_text": "accel_y",
            "accel_z_text": "accel_z", "accel_magnitude_text": "accel_magnitude",
            "gyro_x_text": "gyro_x", "gyro_y_text": "gyro_y",
            "gyro_z_text": "gyro_z", "gyro_magnitude_text": "gyro_magnitude",
        }.get(ind_key)
        if imu_field:
            return self._window_average(
                self.telemetry.resolve_samples(imu_field, source, indicator_key=ind_key),
                target_dt, window)
        return None
