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
import os
import queue
import threading
from pathlib import Path
from typing import Any, Optional

from PIL import Image
from PySide6.QtCore import QObject, QTimer, QUrl, Qt

# ── Istniejąca logika biznesowa (NIETKNIĘTA) ──────────────────────────────
from src.gui.layout_manager import LayoutManager, default_layout, normalize_layout, resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_gps_track,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    get_container_rotation,
    get_rotation_from_metadata,
    interpolate_value,
    load_json_with_fallback,
    smooth_speed_samples,
    smooth_speed_values,
    find_metadata_json,
)
from src.video_helpers import find_local_tool
from src.gui.qt.signals import get_signals

# Flagi dostępności modułów dla kompatybilności wstecznej (np. z testami)
try:
    from PySide6.QtMultimedia import QMediaPlayer
    _QT_MULTIMEDIA_AVAILABLE = True
except ImportError:
    _QT_MULTIMEDIA_AVAILABLE = False

try:
    import mpv
    _MPV_AVAILABLE = True
except Exception:
    _MPV_AVAILABLE = False

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

try:
    from src.telemetry_gpmf_new import gpmf_to_exiftool_json
    _GPMF_AVAILABLE = True
except ImportError:
    _GPMF_AVAILABLE = False

# ── Mixiny ──────────────────────────────────────────────────────────────
from src.gui.qt._mixins import (
    CutMixin,
    IndicatorMixin,
    PlaybackMixin,
    PresetMixin,
    PreviewMixin,
    ProjectMixin,
    RenderMixin,
)


class AppController(
    QObject,
    CutMixin,
    IndicatorMixin,
    PlaybackMixin,
    PresetMixin,
    PreviewMixin,
    ProjectMixin,
    RenderMixin,
):
    """Kontroler aplikacji — most między GUI a logiką biznesową.

    Odpowiedzialności podzielone na mixiny:
    - CutMixin: cięcia i trimowanie wideo
    - IndicatorMixin: wskaźniki HUD i strumienie telemetryczne
    - PlaybackMixin: odtwarzanie (MPV/QMediaPlayer)
    - PresetMixin: wczytywanie i zapis presetów / opcje wskaźników
    - PreviewMixin: renderowanie i składanie podglądu (PIL/QImage)
    - ProjectMixin: wczytywanie plików i ekstrakcja telemetrii
    - RenderMixin: renderowanie końcowe filmu (FFmpeg pipeline)
    """

    def __init__(self) -> None:
        super().__init__()
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
        self._cut_regions: list[tuple[float, float]] = []

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

        # ── Przygotowanie danych podglądu — cache wartości stałych ──────
        self._prepare_cache: dict = {}
        self._chart_data_cache: Optional[dict] = None

        # ── QMediaPlayer (GPU-accelerated preview) ─────────────────────
        self._setup_media_player()
        self.last_src_qimg: Any = None
        self.last_src_pil: Image.Image | None = None
        self._seek_pending = False
        self._frame_counter = 0
        self._composite_every_n = 1
        # Docelowa szerokość podglądu — kompozytowanie w niższej rozdzielczości
        self._preview_target_w = 960

        # ── Worker compositingu (tło — nie blokuje GUI) ────────────────
        self._comp_queue: queue.Queue = queue.Queue(maxsize=2)
        self._comp_worker_running = True
        self._comp_thread: Optional[threading.Thread] = None
        self._start_compositing_worker()

        # ── Render state ───────────────────────────────────────────────
        self.render_cancel_event = threading.Event()
        self.render_threads: Optional[int] = None

        # ── Playback state ────────────────────────────────────────────
        self._playback_timer: Optional[QTimer] = None
        self._playback_pos: float = 0.0
        self._playing = False
        self.video_widget: Optional[object] = None
        self._preview_mode: str = "hud"
        self.mpv_player = None
        self._mpv_timer = None
        self.mpv_preview_vendor: str = "auto"  # auto / nv / amd / intel / cpu
        self.mpv_hwdec_active: str | None = None

        # ── Inicjalizacja GPU ───────────────────────────────────────────
        try:
            from src.indicators.gpu_compositor import GpuCompositor
            gpu = GpuCompositor.get_instance()
            if gpu:
                print(f"[Controller] Akceleracja GPU aktywna: {gpu.device_name}", flush=True)
            else:
                print("[Controller] Akceleracja GPU niedostępna, używam trybu CPU/Pillow", flush=True)
        except Exception as e:
            print(f"[Controller] Błąd inicjalizacji GPU: {e}", flush=True)

        # ── Podłącz sygnały ────────────────────────────────────────────
        self._connect_signals()

        # ── Inicjalizacja benchmarka ───────────────────────────────────
        from src.benchmark import BenchmarkTracker
        BenchmarkTracker.get_instance().enable(True)

    def _clear_caches(self) -> None:
        """Czyszczenie pamięci podręcznej wyliczeń podglądu."""
        self._prepare_cache.clear()
        self._chart_data_cache = None

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
        s.sig_preview_mode_changed.connect(self._on_preview_mode_changed)
        s.sig_preview_accel_changed.connect(self._on_preview_accel_changed)
        s.sig_data_streams_ready.connect(lambda _: self._render_preview(0))

    def _load_startup_preset(self) -> None:
        """Wczytuje def_layout.json oraz _startup_preset jeśli istnieje."""
        def_layout = self.base_dir / "def_layout.json"
        if def_layout.exists():
            try:
                self.layout = normalize_layout(def_layout, 1280, 720)
                self._startup_preset_path = self.layout.get("_startup_preset", "")
            except Exception as e:
                print(f"[Controller] Błąd wczytywania def_layout.json: {e}", flush=True)
