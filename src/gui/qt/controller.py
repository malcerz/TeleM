"""AppController — most między GUI (PySide6) a logiką biznesową.

Kontroler:
- Przyjmuje sygnały z GUI
- Wywołuje istniejące menedżery (TelemetryDataManager, LayoutManager, itd.)
- Emituje sygnały zwrotne do GUI
- NIE zawiera kodu GUI (żadnych widgetów)
- NIE modyfikuje istniejącej logiki biznesowej
"""

from __future__ import annotations

import json
import math
import queue
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog

# ── Istniejąca logika biznesowa (NIETKNIĘTA) ──────────────────────────────
from src.gui.layout_manager import LayoutManager, default_layout, normalize_layout, resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.gui.indicator_schemas import BUILTIN_FIELDS

from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    extract_gps_track,
    interpolate_speed, interpolate_distance, interpolate_altitude,
    interpolate_value, smooth_speed_samples, smooth_speed_values,
    find_metadata_json, ensure_records_list,
    get_rotation_from_metadata, get_container_rotation,
    load_json_with_fallback,
)
from src.overlay_renderer import FONT_CACHE, build_chart_data, render_preview
from src.map_renderer import clear_map_cache
from src.video_helpers import (
    extract_frame, ffprobe_stream_info, find_executable, find_local_tool,
    get_cached_capture, clear_capture_cache, parse_fps, sanitize_output_path,
    get_proxy_path,
)
from src.ffmpeg_pipeline import (
    detect_best_encoder, stream_overlay_to_ffmpeg,
)

from src.gui.qt.models import DataStream, FieldSchema, get_schema_for_form
from src.gui.qt.signals import get_signals

try:
    from src.telemetry_gpmf_new import gpmf_to_exiftool_json
    _GPMF_AVAILABLE = True
except ImportError:
    _GPMF_AVAILABLE = False

try:
    from telemetry_gpx import find_gpx_for_video, process_gpx
    _GPX_AVAILABLE = True
except ImportError:
    _GPX_AVAILABLE = False

try:
    from telemetry_fit import find_fit_for_video, process_fit
    _FIT_AVAILABLE = True
except ImportError:
    _FIT_AVAILABLE = False


SMOOTHING_WINDOW = 5


class AppController:
    """Kontroler aplikacji — most między GUI a logiką biznesową."""

    def __init__(self) -> None:
        self.signals = get_signals()
        self.base_dir = Path(__file__).resolve().parent.parent.parent.parent

        # ── Stan ────────────────────────────────────────────────────────
        self.video_paths: list[Path] = []
        self.video_path: Optional[Path] = None
        self.meta_path: Optional[Path] = None
        self.gpx_path: Optional[Path] = None
        self.fit_path: Optional[Path] = None
        self.font_path = resolve_font_path("Arial")
        self.src_img = Image.new("RGB", (1280, 720), (0, 0, 0))
        self.layout: dict[str, Any] = default_layout(1280, 720)
        self.video_duration_s = 0.0
        self.fps = 30.0
        self.last_preview_ts = -1.0
        self.indicator_bboxes: dict = {}
        self._selected_stream_key: str = ""

        # Wczytaj startowy preset z def_layout.json jeśli istnieje
        self._startup_preset_path: str = ""
        self._load_startup_preset()

        # ── Narzędzia ──────────────────────────────────────────────────
        self.ffprobe_path = find_local_tool(self.base_dir, ["ffprobe.exe", "ffprobe"]) or "ffprobe"
        self.exiftool_path = find_local_tool(self.base_dir, ["exiftool.exe", "exiftool"]) or "exiftool"
        self.ffmpeg_exe: Optional[str] = None
        self.ffprobe_exe: Optional[str] = None

        # ── Inicjalizacja menedżerów (istniejąca logika) ───────────────
        self.telemetry = TelemetryDataManager(
            extract_speed_fn=extract_speed_samples,
            extract_altitude_fn=extract_altitude_samples,
            extract_track_fn=extract_track_samples,
            extract_iso_fn=extract_iso_samples,
            extract_exposure_fn=extract_exposure_samples,
            extract_temperature_fn=extract_temperature_samples,
            smooth_fn=smooth_speed_samples,
            interpolate_fn=interpolate_value,
            get_rotation_meta_fn=get_rotation_from_metadata,
            get_container_rotation_fn=get_container_rotation,
            find_meta_json_fn=find_metadata_json,
            find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
            load_telemetry_fn=lambda *a: None,
            ensure_records_fn=ensure_records_list,
            load_json_fallback_fn=load_json_with_fallback,
            write_records_fn=lambda p, r: None,
            extract_samples_exiftool_fn=lambda f: [],
            extract_altitude_exiftool_fn=lambda f: [],
            extract_gps_track_fn=extract_gps_track,
            find_gps_anchor_fn=lambda r: None,
            smooth_values_fn=smooth_speed_values,
        )

        self.layout_mgr = LayoutManager(
            default_layout_fn=default_layout,
            normalize_layout_fn=normalize_layout,
        )

        # ── Preview worker ─────────────────────────────────────────────
        self._preview_queue: queue.Queue = queue.Queue(maxsize=1)
        self._preview_worker: Optional[threading.Thread] = None
        self._start_preview_worker()

        # ── Render state ───────────────────────────────────────────────
        self.render_cancel_event = threading.Event()

        # ── Playback state ────────────────────────────────────────────
        self._playback_timer: Optional[QTimer] = None
        self._playback_pos: float = 0.0
        self._playing = False

        # ── Podłącz sygnały ────────────────────────────────────────────
        self._connect_signals()

    def _connect_signals(self) -> None:
        s = self.signals
        s.sig_files_selected.connect(self._on_files_selected)
        s.sig_stream_clicked.connect(self._on_stream_clicked)
        s.sig_indicator_clicked.connect(self._on_stream_clicked)
        s.sig_indicator_moved.connect(self._on_indicator_moved)
        s.sig_reset_layout.connect(self._on_reset_layout)
        s.sig_save_preset.connect(self._on_save_preset)
        s.sig_load_preset.connect(self._on_load_preset)
        s.sig_property_changed.connect(self._on_property_changed)
        s.sig_delete_indicator.connect(self._on_delete_indicator)
        s.sig_render_requested.connect(self._on_render_requested)
        s.sig_render_cancelled.connect(self._on_render_cancelled)
        s.sig_seek_changed.connect(self._on_seek_changed)
        s.sig_settings_changed.connect(self._on_settings_changed)
        s.sig_playback_start.connect(self._on_playback_start)
        s.sig_playback_stop.connect(self._on_playback_stop)
        s.sig_data_streams_ready.connect(lambda _: self._render_preview(0))

    def _load_startup_preset(self) -> None:
        """Wczytaj _startup_preset z def_layout.json jeśli istnieje."""
        def_layout = self.base_dir / "def_layout.json"
        if def_layout.exists():
            try:
                data = json.loads(def_layout.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._startup_preset_path = data.get("_startup_preset", "")
            except Exception:
                self._startup_preset_path = ""

    # ═════════════════════════════════════════════════════════════════════
    # WORKER PODGLĄDU
    # ═════════════════════════════════════════════════════════════════════

    def _start_preview_worker(self) -> None:
        def worker() -> None:
            while True:
                try:
                    task = self._preview_queue.get()
                    if task is None:
                        break
                    video_paths, ts = task
                    if not self.ffmpeg_exe or not self.ffprobe_exe:
                        continue
                    img = extract_frame(
                        video_paths, ts,
                        self.ffmpeg_exe, self.ffprobe_exe, target_w=960,
                    )
                    if img:
                        self.src_img = img
                        self.last_preview_ts = ts
                        self._render_preview(ts)
                except Exception as e:
                    print(f"[Preview worker] {e}", flush=True)
                finally:
                    self._preview_queue.task_done()

        self._preview_worker = threading.Thread(target=worker, daemon=True)
        self._preview_worker.start()

    # ═════════════════════════════════════════════════════════════════════
    # OBSŁUGA ZDARZEŃ GUI — WYBÓR PLIKÓW
    # ═════════════════════════════════════════════════════════════════════

    def _on_files_selected(
        self,
        video_paths: list[str],
        gpx_path: str,
        fit_path: str,
    ) -> None:
        """Użytkownik wybrał pliki w zakładce Wczytywanie."""
        self.signals.sig_progress.emit(0, "Wczytywanie wideo...")

        def bg_load() -> None:
            try:
                self.video_paths = [Path(p) for p in video_paths]
                self.video_path = self.video_paths[0]

                # Wykryj narzędzia
                ffprobe_exe = find_executable(
                    str(self.ffprobe_path),
                    [str(self.base_dir / "ffprobe.exe"), "ffprobe.exe"],
                )
                ffmpeg_exe = find_executable(
                    "ffmpeg",
                    [str(self.base_dir / "ffmpeg.exe"), "ffmpeg.exe"],
                )
                if not ffprobe_exe or not ffmpeg_exe:
                    self.signals.sig_error.emit(
                        "Nie znaleziono ffprobe.exe / ffmpeg.exe"
                    )
                    return
                self.ffprobe_exe = ffprobe_exe
                self.ffmpeg_exe = ffmpeg_exe

                # Analiza wideo
                self.signals.sig_progress.emit(15, "Analiza strumienia...")
                info = ffprobe_stream_info(ffprobe_exe, self.video_paths[0])
                streams = info.get("streams", [])
                w = int(streams[0].get("width", 1920)) if streams else 1920
                h = int(streams[0].get("height", 1080)) if streams else 1080
                self.fps = parse_fps(
                    streams[0].get("avg_frame_rate")
                    or streams[0].get("r_frame_rate")
                ) if streams else 30.0
                total_dur = sum(
                    float(
                        ffprobe_stream_info(ffprobe_exe, p)
                        .get("format", {})
                        .get("duration", 0)
                        or 0
                    )
                    for p in self.video_paths
                )
                self.video_duration_s = total_dur

                self.signals.sig_video_info_ready.emit(
                    f"{w}x{h} @ {self.fps:.1f} fps, {total_dur:.1f}s"
                )
                self.signals.sig_video_duration_ready.emit(total_dur)

                # Layout — użyj startowego preseta jeśli ustawiony
                preset_path = self._startup_preset_path or self.layout.get("_startup_preset", "")
                if preset_path and Path(preset_path).exists():
                    # Wczytaj preset bezpośrednio (bez scalania z domyślnym)
                    self.layout = json.loads(
                        Path(preset_path).read_text(encoding="utf-8")
                    )
                else:
                    def_layout = self.base_dir / "def_layout.json"
                    self.layout = normalize_layout(def_layout, w, h)
                self._selected_stream_key = ""
                self.src_img = Image.new("RGB", (w, h), (0, 0, 0))

                # Wczytaj/wygeneruj metadane
                self.signals.sig_progress.emit(30, "Sprawdzanie metadanych...")
                self._load_or_generate_telemetry()

                # Wczytaj GPX (jeśli podano)
                if gpx_path and _GPX_AVAILABLE:
                    self.gpx_path = Path(gpx_path)
                    self.telemetry.load_gpx(
                        self.video_path, self.telemetry.start_dt_utc,
                        manual_path=self.gpx_path,
                    )

                # Wczytaj FIT (jeśli podano)
                if fit_path and _FIT_AVAILABLE:
                    self.fit_path = Path(fit_path)
                    self.telemetry.load_fit(
                        self.video_path, self.telemetry.start_dt_utc,
                        manual_path=self.fit_path,
                    )

                # Zarejestruj pola FIT
                if self.telemetry.fit_data:
                    fit_keys = self.telemetry.register_fit_fields(
                        self.layout, BUILTIN_FIELDS,
                    )
                    self.fit_ext_fields = list(fit_keys)

                # Odkryj strumienie danych
                self.signals.sig_progress.emit(80, "Budowa interfejsu...")
                streams = self._discover_data_streams()
                self.signals.sig_data_streams_ready.emit(streams)

                # Pobierz pierwszą klatkę i wyrenderuj podgląd
                clear_capture_cache()
                first_frame = extract_frame(
                    self.video_paths, 0, ffmpeg_exe, ffprobe_exe,
                )
                if first_frame:
                    self.src_img = first_frame
                self._render_preview(0)

                self.signals.sig_progress.emit(100, "Gotowe")

            except Exception as e:
                import traceback
                traceback.print_exc()
                self.signals.sig_error.emit(str(e))

        threading.Thread(target=bg_load, daemon=True).start()

    def _load_or_generate_telemetry(self) -> None:
        """Wczytaj istniejący JSON lub wygeneruj synchronicznie (blokada).

        Blokuje do czasu sparsowania danych, emitując postęp przez sig_progress.
        """
        if not self.video_path:
            return

        meta = self.video_path.with_suffix(".json")
        if meta.exists():
            records = ensure_records_list(load_json_with_fallback(meta))
            if records:
                self.signals.sig_progress.emit(45, "Wczytywanie JSON...")
                self.telemetry.records = records
                self.telemetry.load_gpmf_from_exiftool(self.video_path)
                self.telemetry.load_gpmf_records(records)
                self.telemetry.load_gps_track(records)
                self.meta_path = meta
                return

        # ── JSON nie istnieje → generuj synchronicznie (blokada) ──────
        self.signals.sig_progress.emit(45, "Generowanie metadanych...")

        data = None
        method = ""
        # Próbuj GPMF (bezpośrednio z ffmpeg — dużo szybszy niż ExifTool)
        if _GPMF_AVAILABLE and self.ffmpeg_exe and self.ffprobe_exe:
            try:
                self.signals.sig_progress.emit(50, "GPMF: czytanie strumienia...")
                data = gpmf_to_exiftool_json(
                    str(self.video_paths[0]),
                    self.ffmpeg_exe, self.ffprobe_exe,
                )
                if data:
                    method = "GPMF"
                    print(f"[GPMF] Succeeded — extracted {len(data[0]) if isinstance(data, list) and data else 0} keys", flush=True)
                else:
                    print("[GPMF] Returned empty data", flush=True)
            except Exception as exc:
                print(f"[GPMF] Failed: {exc} — falling back to ExifTool", flush=True)

        # Fallback: ExifTool
        if not data:
            self.signals.sig_progress.emit(55, "ExifTool: odczyt metadanych...")
            exe = find_executable(
                str(self.exiftool_path),
                [str(self.base_dir / "exiftool.exe"), "exiftool.exe"],
            )
            if not exe:
                raise RuntimeError("Nie znaleziono exiftool")
            proc = subprocess.run(
                [exe, "-ee", "-j", "-G3", str(self.video_paths[0])],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr or "ExifTool error")
            data = json.loads(proc.stdout)
            method = "ExifTool"

        if data:
            flat = data[0] if isinstance(data, list) else data
            json_path = self.video_path.with_suffix(".json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(flat, f, indent=2, ensure_ascii=False)
            self.meta_path = json_path

            self.signals.sig_progress.emit(65, f"Parsowanie danych ({method})...")
            records = ensure_records_list([flat])
            self.telemetry.records = records
            # Przekazujemy flat zamiast uruchamiać ExifTool ponownie
            self.telemetry.load_gpmf_from_exiftool(self.video_path, flat=flat)
            self.telemetry.load_gpmf_records(records)
            self.telemetry.load_gps_track(records)

            # Jeśli start_dt_utc wciąż None (brak GPSDateTime w GPMF),
            # użyj daty z metadanych wideo
            if self.telemetry.start_dt_utc is None and self.ffprobe_exe:
                try:
                    import subprocess, json as _json
                    p = subprocess.run(
                        [self.ffprobe_exe, "-v", "error", "-show_format", "-of", "json",
                         str(self.video_path)],
                        capture_output=True, text=True, timeout=5,
                    )
                    if p.returncode == 0:
                        info = _json.loads(p.stdout)
                        ct = info.get("format", {}).get("tags", {}).get("creation_time")
                        if ct:
                            from datetime import timezone as _tz
                            dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                            self.telemetry.start_dt_utc = dt.astimezone(_tz.utc).replace(tzinfo=None)
                            print(f"[start_dt_utc] Fallback from video creation_time: {self.telemetry.start_dt_utc}", flush=True)
                except Exception as exc:
                    print(f"[start_dt_utc] Fallback failed: {exc}", flush=True)

        self.signals.sig_progress.emit(70, "Metadane gotowe")

        # Nie wołaj _generate_meta_json() — wszystko jest już zrobione

    def _generate_meta_json(self) -> None:
        """Generuje metadata JSON dla wideo (GPMF → ExifTool fallback)."""
        if not self.video_path:
            return

        self.signals.sig_progress.emit(45, "Generowanie metadanych...")

        def worker() -> None:
            try:
                data = None
                # Próbuj GPMF
                if _GPMF_AVAILABLE and self.ffmpeg_exe and self.ffprobe_exe:
                    try:
                        data = gpmf_to_exiftool_json(
                            str(self.video_paths[0]),
                            self.ffmpeg_exe, self.ffprobe_exe,
                        )
                    except Exception:
                        pass

                # Fallback: ExifTool
                if not data:
                    exe = find_executable(
                        str(self.exiftool_path),
                        [str(self.base_dir / "exiftool.exe"), "exiftool.exe"],
                    )
                    if not exe:
                        raise RuntimeError("Nie znaleziono exiftool")
                    proc = subprocess.run(
                        [exe, "-ee", "-j", "-G3", str(self.video_paths[0])],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True,
                    )
                    if proc.returncode != 0:
                        raise RuntimeError(proc.stderr or "ExifTool error")
                    data = json.loads(proc.stdout)

                if data:
                    flat = data[0] if isinstance(data, list) else data
                    json_path = self.video_path.with_suffix(".json")
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(flat, f, indent=2, ensure_ascii=False)
                    self.meta_path = json_path

                    records = ensure_records_list([flat])
                    self.telemetry.records = records
                    self.telemetry.load_gpmf_from_exiftool(self.video_path)
                    self.telemetry.load_gpmf_records(records)
                    self.telemetry.load_gps_track(records)

                    # Ponownie odkryj strumienie danych i odśwież UI
                    streams = self._discover_data_streams()
                    self.signals.sig_data_streams_ready.emit(streams)

                self.signals.sig_progress.emit(70, "Metadane gotowe")

            except Exception as e:
                self.signals.sig_error.emit(f"Błąd generowania metadanych: {e}")

        threading.Thread(target=worker, daemon=True).start()

    # ═════════════════════════════════════════════════════════════════════
    # ODKRYWANIE STRUMIENI DANYCH
    # ═════════════════════════════════════════════════════════════════════

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

    # ═════════════════════════════════════════════════════════════════════
    # KLIKNIĘCIE STRUMIENIA → PANEL WŁAŚCIWOŚCI
    # ═════════════════════════════════════════════════════════════════════

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
            "enabled": True, "label": key, "x": 0.5, "y": 0.5,
            "rotation": 0, "form": "text", "font_size": 0.025,
            "size": 0.1, "thickness": 3, "min_val": 0, "max_val": 100,
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

        # Ustal domyślną formę na podstawie klucza (z rejestru indicators.py)
        from src.indicators import get_form_for_key
        _form, _form_overrides = get_form_for_key(key)
        defaults["form"] = _form
        defaults.update(_form_overrides)

        if key == "track_map":
            # Mapa – ma własne ustawienia niezależnie od rejestru
            defaults["form"] = "map"
            defaults["size"] = 0.18
            defaults["zoom"] = 16
            defaults["map_style"] = "light_all"
            defaults["marker_size"] = 7
            defaults["marker_color"] = "#FFFFFF"
            defaults["x"] = 0.02
            defaults["y"] = 0.15

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
                min_val = 0.0
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
        """Przeciągnięto wskaźnik myszką — aktualizuj pozycję w layoucie."""
        if key not in self.layout.get("indicators", {}):
            return
        self.layout["indicators"][key]["x"] = x_norm
        self.layout["indicators"][key]["y"] = y_norm
        self._render_preview()

    # ═════════════════════════════════════════════════════════════════════
    # USUŃ WSKAŹNIK
    # ═════════════════════════════════════════════════════════════════════

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

    # ═════════════════════════════════════════════════════════════════════
    # RESET WSKAŹNIKÓW
    # ═════════════════════════════════════════════════════════════════════

    def _on_reset_layout(self) -> None:
        """Resetuje układ — usuwa wszystkie wskaźniki poza time_block."""
        # Zachowaj time_block jako bazowy wskaźnik daty/czasu, usuń resztę
        time_block_cfg = self.layout.get("indicators", {}).get(
            "time_block",
            {"enabled": True, "label": "Czas", "x": 0.018, "y": 0.030,
             "rotation": 0, "font_label": 0.0125, "font_date": 0.020,
             "font_time": 0.020},
        )
        self.layout["indicators"] = {"time_block": time_block_cfg}
        self.layout["custom_texts"] = []
        if self.layout_mgr:
            self.layout_mgr.layout = self.layout
        self._selected_stream_key = ""
        self._render_preview()

    # ═════════════════════════════════════════════════════════════════════
    # ZAPISZ / WCZYTAJ PRESET
    # ═════════════════════════════════════════════════════════════════════

    def _on_save_preset(self) -> None:
        """Zapisuje obecny układ do pliku JSON."""
        path, _ = QFileDialog.getSaveFileName(
            None, "Zapisz preset układu", "",
            "JSON (*.json);;Wszystkie (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.layout, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.signals.sig_error.emit(f"Błąd zapisu presetu: {e}")

    def _on_load_preset(self) -> None:
        """Wczytuje układ z pliku JSON i odświeża podgląd."""
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
                from src.gui.qt.models import get_schema_for_form
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

    # ═════════════════════════════════════════════════════════════════════
    # ZMIANA WŁAŚCIWOŚCI
    # ═════════════════════════════════════════════════════════════════════

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

        # Jeśli zmieniono formę — wyślij nowy schemat
        if field_name == "form" and value != old_form:
            schema = get_schema_for_form(value)
            self.signals.sig_properties_ready.emit(stream_key, schema, dict(cfg))

        # Synchronizuj layout_mgr
        if self.layout_mgr:
            self.layout_mgr.layout = self.layout

        # Inwalidacja cache mapy
        if stream_key == "track_map" and field_name in ("zoom", "map_style"):
            clear_map_cache()

        # Odśwież podgląd
        self._render_preview()

    # ═════════════════════════════════════════════════════════════════════
    # RENDEROWANIE PODGLĄDU
    # ═════════════════════════════════════════════════════════════════════

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

    def _render_preview(self, seek_seconds: float | None = None) -> None:
        """Renderuje podgląd nakładki i wysyła QPixmap do GUI."""
        try:
            if not self.video_path:
                return

            src_w, src_h = self.src_img.size
            if src_w < 10 or src_h < 10:
                return

            # Wartości domyślne (demo)
            date_txt, time_txt = "----.--.--", "--:--:--"
            indicator_overrides: dict[str, float] = {}
            overlay_data: dict | None = None
            target_dt = None

            if self.telemetry.start_dt_utc:
                current_ts = seek_seconds if seek_seconds is not None else 0
                target_dt = self.telemetry.start_dt_utc + timedelta(seconds=current_ts)
                if target_dt.tzinfo is None:
                    target_dt = target_dt.replace(tzinfo=timezone.utc)

                from src.overlay_renderer import (
                    prepare_overlay_frame_data, build_chart_data,
                )

                chart_data = build_chart_data(
                    self.layout,
                    self.telemetry.get_samples_for_source,
                    self.telemetry.resolve_samples,
                )

                overlay_data = None
                try:
                    overlay_data = prepare_overlay_frame_data(
                        layout=self.layout,
                        target_dt=target_dt,
                        tz_offset_hours=2,  # hardcoded – same as render pipeline default
                        start_dt_utc=self.telemetry.start_dt_utc,
                        speed_samples=self.telemetry.speed_samples or [],
                        track_samples=self.telemetry.track_samples or [],
                        alt_samples=self.telemetry.alt_samples or [],
                        iso_samples=self.telemetry.iso_samples,
                        exposure_samples=self.telemetry.exposure_samples,
                        temperature_samples=self.telemetry.temperature_samples,
                        gpx_speed_samples=self.telemetry.gpx_speed_samples,
                        gpx_track_samples=self.telemetry.gpx_track_samples,
                        gpx_alt_samples=self.telemetry.gpx_alt_samples,
                        gpx_power_samples=self.telemetry.gpx_power_samples,
                        gpx_atemp_samples=self.telemetry.gpx_atemp_samples,
                        gpx_hr_samples=self.telemetry.gpx_hr_samples,
                        gpx_cad_samples=self.telemetry.gpx_cad_samples,
                        fit_data=self.telemetry.fit_data,
                        gps_track=self.telemetry.get_gps_track_for_source(
                            self.layout.get("indicators", {})
                            .get("track_map", {}).get("source", "fit")
                        ),
                        total_frames=max(1, int(self.video_duration_s)),
                        current_index=int(current_ts) if current_ts else 0,
                        chart_data=chart_data,
                        extra_field_keys=getattr(self, "fit_ext_fields", None),
                        resolve_cache_value=lambda k, dt: self.telemetry.resolve_value(k, dt),
                    )
                    if overlay_data:
                        date_txt = overlay_data["date_text"]
                        time_txt = overlay_data["time_text"]
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"[PREVIEW] prepare_overlay_frame_data failed: {e}", flush=True)

                date_txt = overlay_data["date_text"]
                time_txt = overlay_data["time_text"]

            # Pozycja dla kursora na wykresach
            current_position = (
                seek_seconds / max(1.0, self.video_duration_s)
                if seek_seconds is not None and self.video_duration_s > 0
                else 0.0
            )

            # Renderuj overlay (istniejąca funkcja)
            self.indicator_bboxes.clear()

            if overlay_data is not None:
                preview = render_preview(
                    self.src_img, self.layout, self.font_path,
                    overlay_data["date_text"], overlay_data["time_text"],
                    overlay_data["speed_value"],
                    overlay_data["distance_m"],
                    overlay_data["max_distance_m"],
                    overlay_data["alt_value"],
                    overlay_data["min_alt"],
                    overlay_data["max_alt"],
                    overlay_data["iso_value"],
                    overlay_data["exposure_value"],
                    overlay_data["temp_value"],
                    indicator_values=overlay_data["indicator_values"],
                    max_speed_kmh=overlay_data["max_speed_kmh"],
                    power_value=overlay_data["power_value"],
                    atemp_value=overlay_data["atemp_value"],
                    hr_value=overlay_data["hr_value"],
                    cad_value=overlay_data["cad_value"],
                    battery_value=overlay_data["battery_value"],
                    _bboxes=self.indicator_bboxes,
                    extra_indicators=overlay_data["extra_indicators"],
                    chart_data=overlay_data["chart_data"],
                    current_position=current_position,
                    gps_track=overlay_data["gps_track"],
                    target_dt=overlay_data["target_dt"],
                    start_dt_utc=overlay_data["start_dt_utc"],
                )
            else:
                # No telemetry – show blank overlay
                from src.overlay_renderer import compose_overlay
                overlay = compose_overlay(
                    src_w, src_h, self.layout, self.font_path,
                    date_txt, time_txt,
                    0.0, 0.0, 1.0, 0.0, None, None,
                    0.0, 0.0, 0.0,
                    indicator_values={}, max_speed_kmh=None,
                    power_value=0.0, atemp_value=0.0,
                    hr_value=0.0, cad_value=0.0, battery_value=0.0,
                    chart_data={}, current_position=current_position,
                    extra_indicators={}, gps_track=[],
                    target_dt=None, start_dt_utc=None,
                )
                preview = self.src_img.convert("RGBA").copy()
                preview.alpha_composite(overlay)
                self.indicator_bboxes.clear()

            # Konwertuj PIL Image → QPixmap
            from PySide6.QtGui import QImage, QPixmap
            img_rgb = preview.convert("RGB")
            data = img_rgb.tobytes("raw", "RGB")
            qimg = QImage(
                data, img_rgb.width, img_rgb.height,
                img_rgb.width * 3, QImage.Format_RGB888,
            )
            pixmap = QPixmap.fromImage(qimg)
            self.signals.sig_preview_frame_ready.emit(pixmap)
            self.signals.sig_bboxes_ready.emit(
                dict(self.indicator_bboxes),
                self.src_img.width, self.src_img.height,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()

    # ═════════════════════════════════════════════════════════════════════
    # SEEK
    # ═════════════════════════════════════════════════════════════════════

    def _on_seek_changed(self, seconds: float) -> None:
        """Użytkownik przesunął oś czasu."""
        self._playback_pos = seconds  # sync playback position
        if (
            self.video_paths
            and abs(seconds - self.last_preview_ts) > 0.1
        ):
            try:
                self._preview_queue.get_nowait()
            except queue.Empty:
                pass
            self._preview_queue.put((self.video_paths, seconds))

        self._render_preview(seconds)

    # ═════════════════════════════════════════════════════════════════════
    # PLAYBACK
    # ═════════════════════════════════════════════════════════════════════

    def _on_playback_start(self) -> None:
        """Użytkownik kliknął Play — uruchom automatyczny seek."""
        if not self.video_path or self.video_duration_s <= 0:
            return
        self._playing = True
        self._playback_step()

    def _on_playback_stop(self) -> None:
        """Użytkownik kliknął Stop — zatrzymaj playback."""
        self._playing = False
        if self._playback_timer is not None:
            try:
                self._playback_timer.stop()
            except Exception:
                pass
            self._playback_timer = None

    def _playback_step(self) -> None:
        """Przesuń seek o 1 klatkę i zaplanuj następny krok."""
        if not self._playing:
            return
        # Oblicz aktualny seek z ostatniego wejścia wideo
        step = 1.0 / max(self.fps, 1.0)
        # Odczytaj obecną pozycję seeka przez ostatnio wyrenderowany podgląd
        # Używamy sig_seek_changed -> _on_seek_changed, więc musimy sami
        # zarządzać bieżącą pozycją. Symulujemy przesunięcie suwaka.
        # Pobieramy ostatnią pozycję z ostatniego wysłanego seeka.
        # Najprościej: przechowujemy ostatnią pozycję.
        if not hasattr(self, '_playback_pos'):
            self._playback_pos = 0.0
        nxt = self._playback_pos + step
        if nxt >= self.video_duration_s:
            self._on_playback_stop()
            self._playback_pos = 0.0
            self.signals.sig_seek_changed.emit(0.0)
            return
        self._playback_pos = nxt
        self.signals.sig_seek_changed.emit(nxt)
        interval = max(16, int(step * 1000))
        self._playback_timer = QTimer.singleShot(interval, self._playback_step)

    # ═════════════════════════════════════════════════════════════════════
    # RENDEROWANIE KOŃCOWE
    # ═════════════════════════════════════════════════════════════════════

    def _on_render_requested(self, options: dict) -> None:
        """Użytkownik kliknął 'Renderuj'."""
        if not self.video_path:
            self.signals.sig_error.emit("Najpierw wybierz plik wideo.")
            return

        # Zapisz layout
        def_layout = self.base_dir / "def_layout.json"
        with open(def_layout, "w", encoding="utf-8") as f:
            json.dump(self.layout, f, indent=2, ensure_ascii=False)

        self.render_cancel_event.clear()

        def worker() -> None:
            try:
                stats = self._render_pipeline(options)
                if not self.render_cancel_event.is_set():
                    output = options.get("output", "output.mp4")
                    self.signals.sig_render_finished.emit(stats, output)
            except Exception as e:
                self.signals.sig_error.emit(f"Render error: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _render_pipeline(self, options: dict) -> dict:
        """Wykonuje pipeline renderowania (istniejąca logika)."""
        encoder = options.get("encoder", detect_best_encoder())
        resolution = options.get("resolution", "source")
        output = options.get("output", "output.mp4")
        video_bitrate = options.get("bitrate", "40M")

        meta = self.video_path.with_suffix(".json")
        if not meta.exists():
            raise RuntimeError("Brak pliku metadanych JSON.")

        ffmpeg_exe = self.ffmpeg_exe or find_executable("ffmpeg")
        ffprobe_exe = self.ffprobe_exe or find_executable("ffprobe")
        if not ffmpeg_exe or not ffprobe_exe:
            raise RuntimeError("ffmpeg/ffprobe nie znalezione")

        info = ffprobe_stream_info(ffprobe_exe, self.video_path)
        streams = info.get("streams", [])
        fps_stream = parse_fps(
            streams[0].get("avg_frame_rate")
            or streams[0].get("r_frame_rate")
        ) if streams else 30.0
        w = int(streams[0].get("width", 1920)) if streams else 1920
        h = int(streams[0].get("height", 1080)) if streams else 1080

        layout = self.layout
        records = ensure_records_list(load_json_with_fallback(meta))

        # Odczytaj rotację z metadanych (tak samo jak w export_controller)
        rotation_degrees = get_rotation_from_metadata(records)
        container_rotation = get_container_rotation(ffprobe_exe, self.video_path)
        if container_rotation != 0:
            effective_rotation = container_rotation
            container_rotation_arg = container_rotation
        else:
            effective_rotation = rotation_degrees
            container_rotation_arg = 0

        speed = extract_speed_samples(records)
        speed = smooth_speed_samples(speed, "moving_average", SMOOTHING_WINDOW)
        track = extract_track_samples(records)
        alt = extract_altitude_samples(records)
        if alt:
            alt = smooth_speed_samples(alt, "moving_average", SMOOTHING_WINDOW)

        output_path = sanitize_output_path(Path(output))
        if not output_path.is_absolute():
            output_path = self.video_path.parent / output_path

        self.signals.sig_progress.emit(5, "Renderowanie HUD...")

        field_samples = {
            "speed_samples": speed,
            "track_samples": track,
            "alt_samples": alt,
        }

        stream_overlay_to_ffmpeg(
            ffmpeg_exe=ffmpeg_exe,
            input_files=self.video_paths,
            output_file=output_path,
            duration_s=self.video_duration_s,
            start_dt_utc=self.telemetry.start_dt_utc,
            tz_offset_hours=2,
            speed_samples=speed,
            track_samples=track,
            alt_samples=alt,
            font_path=self.font_path,
            layout=layout,
            field_samples=field_samples,
            target_fps=fps_stream,
            update_rate_step=1,
            max_distance_m=track[-1][1] if track else 0,
            workers=None,
            iso_samples=self.telemetry.iso_samples,
            exposure_samples=self.telemetry.exposure_samples,
            temperature_samples=self.telemetry.temperature_samples,
            gpx_speed_samples=self.telemetry.gpx_speed_samples,
            gpx_track_samples=self.telemetry.gpx_track_samples,
            gpx_alt_samples=self.telemetry.gpx_alt_samples,
            gpx_power_samples=self.telemetry.gpx_power_samples,
            gpx_atemp_samples=self.telemetry.gpx_atemp_samples,
            gpx_hr_samples=self.telemetry.gpx_hr_samples,
            gpx_cad_samples=self.telemetry.gpx_cad_samples,
            fit_data=self.telemetry.fit_data,
            gps_track=self.telemetry.get_gps_track_for_source(
                self.layout.get("indicators", {})
                .get("track_map", {}).get("source", "fit")
            ),
            progress_cb=lambda val, txt: self.signals.sig_progress.emit(val, txt),
            cancel_event=self.render_cancel_event,
            encoder=encoder,
            gpu=0,
            resolution_name=resolution,
            video_bitrate=video_bitrate,
            rotation_degrees=effective_rotation,
            container_rotation=container_rotation_arg,
            overlay_w=w,
            overlay_h=h,
            render_w=w,
            render_h=h,
        )

        return {"total_overlay_frames": 0, "png_duration": 0}

    def _on_render_cancelled(self) -> None:
        self.render_cancel_event.set()

    # ═════════════════════════════════════════════════════════════════════
    # USTAWIENIA
    # ═════════════════════════════════════════════════════════════════════

    def _on_settings_changed(self, name: str, value: Any) -> None:
        if name == "font":
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
