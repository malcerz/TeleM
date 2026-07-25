"""HUD Tuner GUI application – main HudTunerApp class.

This module contains the main GUI application class and all remaining
helper functions that have not been extracted to separate modules.
"""

import io
import json
import math
import os
import queue
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk
except ImportError:
    print("Błąd: brakuje Pillow. Zainstaluj: python -m pip install pillow", file=sys.stderr)
    sys.exit(1)

try:
    from telemetry_gpx import find_gpx_for_video, parse_gpx, process_gpx, sync_gpx_to_video
    _GPX_AVAILABLE = True
except ImportError:
    _GPX_AVAILABLE = False
    def process_gpx(video_path, video_start_dt=None):  # noqa: E302gp.py

        return None
    def find_gpx_for_video(video_path):  # noqa: E302
        return None
    def parse_gpx(path):  # noqa: E302
        return None
    def sync_gpx_to_video(points, video_start_dt):  # noqa: E302
        return None, None, None, None, None, None, None

try:
    from telemetry_fit import find_fit_for_video, parse_fit, process_fit, sync_fit_to_video
    _FIT_AVAILABLE = True
except ImportError:
    _FIT_AVAILABLE = False
    def process_fit(video_path, video_start_dt=None):  # noqa: E302
        return None
    def find_fit_for_video(video_path):  # noqa: E302
        return None
    def parse_fit(path):  # noqa: E302
        return None
    def sync_fit_to_video(points, video_start_dt):  # noqa: E302
        return {}

# Import GUI components from the refactored src.gui package
try:
    from src.gui.widgets import (
        FIELD_LABELS,
        GPX_EXT_FIELDS,
        GPX_EXT_LABELS,
        BoolRow,
        ChoiceRow,
        ColorRow,
        NumericRow,
        ScrollableFrame,
        TextRow,
    )
except ImportError:
    # Fallback: define stub classes (should not happen in normal use)
    class ScrollableFrame: pass
    class NumericRow: pass
    class BoolRow: pass
    class ChoiceRow: pass
    class TextRow: pass
    class ColorRow: pass
    FIELD_LABELS = {}
    GPX_EXT_FIELDS = []
    GPX_EXT_LABELS = {}

# Import manager classes (refactored logic)
try:
    from src.gui.layout_manager import LayoutManager
    from src.gui.telemetry_manager import TelemetryDataManager
    _MANAGERS_AVAILABLE = True
except ImportError:
    TelemetryDataManager = object  # fallback
    LayoutManager = object
    _MANAGERS_AVAILABLE = False

# All telemetry extraction, interpolation and smoothing functions
# have been moved to src/telemetry_extract.py
from src.telemetry_extract import (  # noqa: E402
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_gps_track,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    extract_samples_exiftool, extract_altitude_samples_exiftool,
    load_telemetry_exiftool,
    interpolate_speed, interpolate_distance, interpolate_altitude,
    interpolate_iso, interpolate_exposure, interpolate_temperature,
    interpolate_value,
    smooth_speed_samples, smooth_speed_values,
    moving_average, exponential_moving_average,
    speed_at_time,
    flatten_record, ensure_records_list,
    parse_exif_datetime, parse_float_maybe, parse_gps_coord,
    haversine_m, find_gps_anchor,
    get_all_values_by_suffix, get_value_by_suffix_for_prefix,
    find_metadata_json, find_metadata_json_for_write,
    write_records_to_json,
    get_rotation_from_metadata, get_container_rotation,
    format_time, format_raw_value,
    json_loads,
    load_json_with_fallback,
)

# GPMF binary parser – native Python extraction (no external ExifTool needed)
try:
    from src.telemetry_gpmf_new import gpmf_to_exiftool_json
    _GPMF_AVAILABLE = True
except ImportError:
    _GPMF_AVAILABLE = False

    def gpmf_to_exiftool_json(video_path, ffmpeg_exe='ffmpeg', ffprobe_exe='ffprobe'):  # noqa: E302
        raise RuntimeError("GPMF module not available")


APP_VERSION = "0.9.0"
RESOLUTION_OPTIONS = ['source', '8k', '5.3k', '4k', '1080p', '720p', '480p']
ENCODER_OPTIONS = ['nv', 'intel', 'cpu']
GPS_OPTIONS = ['3d', '2d']
ROTATION_OPTIONS = ['auto', '0', '90', '180', '270']
SMOOTHING_WINDOW = 5
# Indicator schemas have been moved to src/gui/indicator_schemas.py
from src.gui.indicator_schemas import (
    TELEMETRY_SOURCES, get_common_schema, get_value_schema,
    get_segment_bar_schema,
    _FORM_FIELDS, _ALL_FORM_FIELDS, BUILTIN_FIELDS, TELEMETRY_TAGS,
)


# FONT_CACHE, font helpers and all overlay rendering functions
# have been moved to src/overlay_renderer.py
from src.overlay_renderer import (
    FONT_CACHE,
    s,
    build_chart_data,
    load_font,
    load_font_cache_small,
    parse_hex_color,
    generate_history_chart,
    render_custom_text,
    rotated_paste,
    render_time_block,
    render_value_indicator,
    compose_overlay,
    render_preview,
)
from src.map_renderer import clear_map_cache

# generate_history_chart, load_font_cache_small and parse_hex_color
# have been moved to src/overlay_renderer.py (imported above).
# Indicator schemas imported from src.gui.indicator_schemas.py above.


from src.video_helpers import (
    clear_capture_cache,
    extract_frame,
    ffprobe_resolution,
    ffprobe_stream_info,
    find_executable,
    find_local_tool,
    get_cached_capture,
    get_proxy_path,
    parse_fps,
    run,
    run_live,
    sanitize_output_path,
)
from src.gui.layout_manager import (
    LayoutManager,
    default_layout,
    normalize_layout,
    resolve_font_path,
)
try:
    from src.gui.telemetry_manager import TelemetryDataManager
    _MANAGERS_AVAILABLE = True
except ImportError:
    TelemetryDataManager = object  # fallback
    _MANAGERS_AVAILABLE = False


# FONT_CACHE, font helpers and all overlay rendering functions
# have been moved to src/overlay_renderer.py
from src.overlay_renderer import (
    FONT_CACHE,
    s,
    build_chart_data,
    load_font,
    load_font_cache_small,
    parse_hex_color,
    generate_history_chart,
    render_custom_text,
    rotated_paste,
    render_time_block,
    render_value_indicator,
    compose_overlay,
    render_preview,
)
from src.map_renderer import clear_map_cache

from src.ffmpeg_pipeline import (
    WORKER_CACHE,
    RESOLUTION_MAP,
    detect_gpu_decoder,
    detect_best_encoder,
    init_worker,
    _get_source_samples,
    _resolve_cache_value,
    _resolve_cache_samples,
    render_overlay_job,
    generate_overlay_sequence,
    build_overlay_video,
    _build_stream_ffmpeg_cmd,
    render_overlay_frame,
    render_frame_bytes_job,
    stream_overlay_to_ffmpeg,
    _report_stream_progress,
    run_ffmpeg_with_progress,
    scale_filter_for_resolution,
    append_bitrate_args,
    apply_overlay_video,
)


class HudTunerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f'HUD Tuner v{APP_VERSION}')
        self.root.geometry('1600x1050')
        self.base_dir      = Path(__file__).resolve().parent.parent.parent  # główny folder programu (TeleMGP)
        self.video_paths_to_process = []
        self.font_path     = resolve_font_path('Arial')
        self.video_path    = None
        self.meta_path     = None
        self.gpx_path      = None   # manually selected or auto-discovered GPX
        self.fit_path      = None   # manually selected or auto-discovered FIT

        self.src_img       = Image.new('RGB', (1280, 720), (0, 0, 0))
        self.last_preview_timestamp = -1
        self.layout        = default_layout(*self.src_img.size)
        self.photo         = None
        self.ffprobe_path  = find_local_tool(self.base_dir, ['ffprobe.exe', 'ffprobe']) or 'ffprobe'
        self.exiftool_path = find_local_tool(self.base_dir, ['exiftool.exe', 'exiftool']) or 'exiftool'
        self.ffmpeg_exe = None
        self.ffprobe_exe = None

        # ── Manager classes (refactored logic) ──
        if _MANAGERS_AVAILABLE:
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
                find_meta_json_write_fn=find_metadata_json_for_write,
                load_telemetry_fn=load_telemetry_exiftool,
                ensure_records_fn=ensure_records_list,
                load_json_fallback_fn=load_json_with_fallback,
                write_records_fn=write_records_to_json,
                load_exiftool_fn=load_telemetry_exiftool,
                extract_samples_exiftool_fn=extract_samples_exiftool,
                extract_altitude_exiftool_fn=extract_altitude_samples_exiftool,
                extract_gps_track_fn=extract_gps_track,
                find_gps_anchor_fn=find_gps_anchor,
                smooth_values_fn=smooth_speed_values,
            )
            self.layout_mgr = LayoutManager(
                default_layout_fn=default_layout,
                normalize_layout_fn=normalize_layout,
            )
        else:
            self.telemetry = None
            self.layout_mgr = None

        # ── Controllers ──
        from src.gui.preview_controller import PreviewController
        from src.gui.export_controller import ExportController
        self.preview_ctrl = PreviewController(self)
        self.export_ctrl = ExportController(self)

        self.video_duration_s = 0.0
        self._refresh_after_id = None
        self._playback_after_id = None
        self._playing = False
        self.render_cancel_event = threading.Event()
        self._active_process = None
        self._render_executor = None
        self.render_button = None

        self.encoder_var         = tk.StringVar(value=detect_best_encoder())
        self.rotation_var        = tk.StringVar(value='auto')
        self.resolution_var      = tk.StringVar(value='source')
        self.update_rate_var     = tk.StringVar(value='Full')
        self.fps                 = 30.0
        self.worker_mode_var     = tk.StringVar(value='auto')
        self.worker_count_var    = tk.StringVar(value='8')
        self.tz_offset_var       = tk.StringVar(value='2')
        self.font_style_var      = tk.StringVar(value='Arial')
        self.outline_var         = tk.IntVar(value=3)
        self.seek_var            = tk.DoubleVar(value=0.0)
        self.output_var          = tk.StringVar(value='output_h265.mp4')
        self.video_bitrate_var   = tk.StringVar(value='40M')
        self.video_info_var      = tk.StringVar(value='Brak pliku MP4')
        self.meta_info_var       = tk.StringVar(value='Telemetry JSON: nie wygenerowano (ExifTool)')
        self.loading_status      = tk.StringVar(value='')
        # Smoothing is always active with SMOOTHING_WINDOW = 5

        # Asynchronous preview frame loader setup
        self._preview_queue = queue.Queue(maxsize=1)
        self._preview_worker_thread = None
        self._start_preview_worker()

        # ── Setup Views ──
        from src.gui.views.left_panel import LeftPanelView
        from src.gui.views.center_panel import CenterPanelView
        from src.gui.views.right_panel import RightPanelView

        self.main_pw = tk.PanedWindow(root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        self.main_pw.pack(fill='both', expand=True)

        self.left_panel_view = LeftPanelView(self.main_pw, self)
        self.center_panel_view = CenterPanelView(self.main_pw, self)
        self.right_panel_view = RightPanelView(self.main_pw, self)

        self.main_pw.add(self.left_panel_view.frame, minsize=10, width=400)
        self.main_pw.add(self.center_panel_view.frame, minsize=1000)
        self.main_pw.add(self.right_panel_view.frame, minsize=60, width=80)

        self.build_property_editor_builtin()
        self.root.after_idle(self.refresh)

    @property
    def fit_ext_fields(self):
        return self.telemetry.fit_ext_fields if self.telemetry else []

    @fit_ext_fields.setter
    def fit_ext_fields(self, val):
        if self.telemetry:
            self.telemetry.fit_ext_fields = val

    @property
    def records(self):
        return self.telemetry.records if self.telemetry else []

    @records.setter
    def records(self, val):
        if self.telemetry:
            self.telemetry.records = val

    @property
    def fit_data(self):
        return self.telemetry.fit_data if self.telemetry else {}

    @fit_data.setter
    def fit_data(self, val):
        if self.telemetry:
            self.telemetry.fit_data = val

    @property
    def start_dt_utc(self):
        return self.telemetry.start_dt_utc if self.telemetry else None

    @start_dt_utc.setter
    def start_dt_utc(self, val):
        if self.telemetry:
            self.telemetry.start_dt_utc = val

    @property
    def indicator_bboxes(self):
        """Delegate indicator bounding boxes dictionary to the preview controller.
        Returns an empty dict if preview controller is not yet created.
        """
        return getattr(self, 'preview_ctrl', None).indicator_bboxes if getattr(self, 'preview_ctrl', None) else {}

    @indicator_bboxes.setter
    def indicator_bboxes(self, val):
        if getattr(self, 'preview_ctrl', None):
            self.preview_ctrl.indicator_bboxes = val

    def _start_preview_worker(self):
        def worker():
            while True:
                try:
                    task = self._preview_queue.get()
                    if task is None:
                        break
                    video_paths, ts, ffmpeg_exe, ffprobe_exe = task
                    img = extract_frame(video_paths, ts, ffmpeg_exe, ffprobe_exe, target_w=960)
                    if img:
                        self.root.after(0, self._on_frame_loaded, img, ts)
                except Exception as e:
                    print(f"Error in preview worker thread: {e}")
                finally:
                    self._preview_queue.task_done()
        self._preview_worker_thread = threading.Thread(target=worker, daemon=True)
        self._preview_worker_thread.start()

    def _on_frame_loaded(self, img, ts):
        self.src_img = img
        # last_preview_timestamp is set before refresh() to prevent
        # refresh() from re-submitting the same timestamp to the queue
        self.last_preview_timestamp = ts
        # schedule_refresh triggers overlay re-render with the new frame
        self.schedule_refresh(delay=0)

    def schedule_refresh(self, delay=60):
        if self._refresh_after_id is not None:
            try:
                self.root.after_cancel(self._refresh_after_id)
            except Exception:
                pass
        self._refresh_after_id = self.root.after(delay, self.refresh)

    # ── Playback controls ──────────────────────────────────────────────

    def playback_start(self):
        """Start preview playback (auto-advance seek)."""
        if self.video_path is None or self.video_duration_s <= 0:
            return
        self._playing = True
        self.playback_step()

    def playback_stop(self):
        """Stop preview playback."""
        self._playing = False
        if self._playback_after_id is not None:
            try:
                self.root.after_cancel(self._playback_after_id)
            except Exception:
                pass
            self._playback_after_id = None

    def playback_step(self):
        """Advance one frame during playback."""
        if not self._playing:
            return
        current = self.seek_var.get()
        step = 1.0 / max(self.fps, 1.0)
        nxt = current + step
        if nxt >= self.video_duration_s:
            self.playback_stop()
            return
        self.seek_var.set(nxt)
        self.schedule_refresh(0)
        interval = max(16, int(step * 1000))
        self._playback_after_id = self.root.after(interval, self.playback_step)

    def on_preview_resize(self, event=None):
        self.schedule_refresh(60)

    def format_time(self, total_sec):
        total_sec = int(total_sec)
        if total_sec >= 3600:
            return f"{total_sec // 3600}:{(total_sec % 3600) // 60:02d}:{total_sec % 60:02d}"
        else:
            return f"{total_sec // 60:02d}:{total_sec % 60:02d}"

    def update_seek_time_label(self):
        self.draw_tick_labels()

    def draw_tick_labels(self, event=None):
        """Rysuje podziałkę czasu na tick_canvas z etykietami w formacie MM:SS / HH:MM:SS."""
        c = self.tick_canvas
        c.delete('all')
        cw = c.winfo_width()
        if cw < 10:
            return
        total = int(self.seek_slider.cget('to'))
        if total <= 0:
            return
        # Wyznacz odstęp między tickami
        if total <= 60:
            step = 10
        elif total <= 600:
            step = 60
        elif total <= 3600:
            step = 300
        elif total <= 7200:
            step = 600
        else:
            step = 1800
        # Rysuj ticki i etykiety
        for t in range(0, total + 1, step):
            x = int(cw * t / total)
            c.create_line(x, 0, x, 8, fill='#aaaaaa', width=1)
            c.create_text(x, 10, text=self.format_time(t), anchor='n',
                          font=('Consolas', 8), fill='#ffffff')
        # ostatni tick (jeśli total nie jest wielokrotnością step)
        if total % step != 0:
            x = cw - 1
            c.create_line(x, 0, x, 8, fill='#aaaaaa', width=1)
            c.create_text(x, 10, text=self.format_time(total), anchor='n',
                          font=('Consolas', 8), fill='#ffffff')

    def on_seek_arrow(self, event=None):
        current = self.seek_var.get()
        if event.keysym in ('Left', 'Down'):
            new_value = max(0, current - 1)
        else:
            new_value = current + 1
        self.seek_var.set(new_value)
        self.schedule_refresh(100)
        return 'break'

    def build_property_editor_builtin(self):
        self.edit_mode = 'builtin'
        for child in self.props_container.winfo_children():
            child.destroy()
        self.property_widgets = {}
        # Sprawdź, która lista ma zaznaczenie
        ct_sel = self.custom_texts_list.curselection()
        if ct_sel:
            idx = ct_sel[0]
            custom_texts = self.layout.get("custom_texts", [])
            if 0 <= idx < len(custom_texts):
                cfg = custom_texts[idx]
                schema = [
                    ("enabled", "bool", None, None, None),
                    ("text", "text", None, None, None),
                    ("x", "float", 0.0, 1.0, 0.001),
                    ("y", "float", 0.0, 1.0, 0.001),
                    ("rotation", "choice", [0, 90, 180, 270], None, None),
                    ("font_size", "float", 0.005, 0.2, 0.001),
                    ("color", "color", None, None, None),
                ]
                for field_name, field_type, a, b, c in schema:
                    if field_type == 'bool':
                        row = BoolRow(self.props_container, field_name, cfg.get(field_name, True), self.on_builtin_change)
                    elif field_type == 'choice':
                        row = ChoiceRow(self.props_container, field_name, cfg.get(field_name, a[0]), a, self.on_builtin_change)
                    elif field_type == 'int':
                        row = NumericRow(self.props_container, field_name, cfg.get(field_name, a), a, b, c, self.on_builtin_change, is_int=True)
                    elif field_type == 'text':
                        row = TextRow(self.props_container, field_name, cfg.get(field_name, ''), self.on_builtin_change)
                    elif field_type == 'color':
                        row = ColorRow(self.props_container, field_name, cfg.get(field_name, '#FFFFFF'), self.on_builtin_change)
                    else:
                        row = NumericRow(self.props_container, field_name, cfg.get(field_name, a), a, b, c, self.on_builtin_change)
                    row.pack(fill=tk.X, padx=4, pady=2)
                    self.property_widgets[field_name] = row
            return
        sel = self.indicator_list.curselection()
        if sel:
            name = self.indicator_list.get(sel[0])
        else:
            sel = self.ext_list.curselection()
            if sel:
                ext_keys = list(GPX_EXT_FIELDS) + self.fit_ext_fields
                if 0 <= sel[0] < len(ext_keys):
                    name = ext_keys[sel[0]]
                else:
                    name = list(self.layout['indicators'].keys())[0]
            else:
                name = list(self.layout['indicators'].keys())[0]
        cfg = self.layout['indicators'].get(name)
        if cfg is None:
            return
        form = cfg.get("form", "text")
        # Use form-specific schema for segment_bar, otherwise fall back to builtin or default
        if form == "segment_bar":
            schema = get_segment_bar_schema()
        else:
            schema = BUILTIN_FIELDS.get(name, get_value_schema())
        # Filter by form: keep common fields + current-form fields + indicator-specific extras
        allowed = _FORM_FIELDS.get(form, _FORM_FIELDS["text"])
        schema = [
            f for f in schema
            if f[0] in ("enabled", "label", "x", "y", "rotation", "form")
            or f[0] in allowed
            or f[0] not in _ALL_FORM_FIELDS
        ]
        for field_name, field_type, a, b, c in schema:
            if field_type == 'bool':
                row = BoolRow(self.props_container, field_name, cfg.get(field_name, False), self.on_builtin_change)
            elif field_type == 'choice':
                row = ChoiceRow(self.props_container, field_name, cfg.get(field_name, a[0]), a, self.on_builtin_change)
            elif field_type == 'int':
                row = NumericRow(self.props_container, field_name, cfg.get(field_name, a), a, b, c, self.on_builtin_change, is_int=True)
            elif field_type == 'text':
                row = TextRow(self.props_container, field_name, cfg.get(field_name, ''), self.on_builtin_change)
            elif field_type == 'color':
                row = ColorRow(self.props_container, field_name, cfg.get(field_name, ''), self.on_builtin_change)
            else:
                row = NumericRow(self.props_container, field_name, cfg.get(field_name, a), a, b, c, self.on_builtin_change)
            row.pack(fill=tk.X, padx=4, pady=2)
            self.property_widgets[field_name] = row

    def on_builtin_select(self, event=None):
        self.ext_list.selection_clear(0, tk.END)
        self.custom_texts_list.selection_clear(0, tk.END)
        self.build_property_editor_builtin()
        self.refresh()

    def on_ext_select(self, event=None):
        self.indicator_list.selection_clear(0, tk.END)
        self.custom_texts_list.selection_clear(0, tk.END)
        self.build_property_editor_builtin()
        self.refresh()

    def _rebuild_custom_texts_list(self):
        """Odświeża listbox custom textów."""
        self.custom_texts_list.delete(0, tk.END)
        for idx, ct in enumerate(self.layout.get("custom_texts", [])):
            text_preview = str(ct.get("text", ""))[:30]
            self.custom_texts_list.insert(tk.END, f"{idx}: {text_preview}")

    def on_custom_text_select(self, event=None):
        self.indicator_list.selection_clear(0, tk.END)
        self.ext_list.selection_clear(0, tk.END)
        self.build_property_editor_builtin()

    def add_custom_text(self):
        """Dodaje nowy custom text do layoutu."""
        self.layout.setdefault("custom_texts", []).append({
            "enabled": True,
            "text": "Nowy tekst",
            "x": 0.5,
            "y": 0.5,
            "rotation": 0,
            "font_size": 0.03,
            "color": "#FFFFFF",
        })
        self._rebuild_custom_texts_list()
        # Zaznacz ostatni
        last_idx = len(self.layout["custom_texts"]) - 1
        self.custom_texts_list.selection_set(last_idx)
        self.build_property_editor_builtin()
        self.refresh()

    def remove_custom_text(self):
        sel = self.custom_texts_list.curselection()
        if not sel:
            return
        idx = sel[0]
        custom_texts = self.layout.get("custom_texts", [])
        if 0 <= idx < len(custom_texts):
            del custom_texts[idx]
            self._rebuild_custom_texts_list()
            self.build_property_editor_builtin()
            self.refresh()

    def reset_indicators(self):
        """Resetuje wszystkie wskaźniki oprócz time_block – wyłącza je i czyści custom texty."""
        from tkinter import messagebox
        if not messagebox.askyesno('Reset', 'Wyłączyć wszystkie wskaźniki oprócz daty/czasu?'):
            return
        indicators = self.layout.get('indicators', {})
        for key in list(indicators.keys()):
            if key == 'time_block':
                continue
            # Wyłącz wskaźnik i zachowaj resztę configu
            indicators[key]['enabled'] = False
        # Wyczyść custom texty
        self.layout['custom_texts'] = []
        # Odśwież UI
        self._rebuild_custom_texts_list()
        self._rebuild_ext_list()
        # Przebuduj listę głównych wskaźników
        self.indicator_list.delete(0, tk.END)
        for key in self.layout['indicators'].keys():
            if key not in GPX_EXT_FIELDS and not key.startswith("fit_"):
                self.indicator_list.insert(tk.END, key)
        self.build_property_editor_builtin()
        self.refresh()

    def on_builtin_change(self):
        if getattr(self, '_suppress_builtin_change', False):
            return
        # Sprawdź, która lista ma zaznaczenie - priorytet: custom_texts > indicator > gpx_ext
        ct_sel = self.custom_texts_list.curselection()
        if ct_sel:
            idx = ct_sel[0]
            custom_texts = self.layout.get("custom_texts", [])
            if 0 <= idx < len(custom_texts):
                for field_name, widget in self.property_widgets.items():
                    custom_texts[idx][field_name] = widget.get()
                self._rebuild_custom_texts_list()
                # Przywróć zaznaczenie po odświeżeniu listy
                if idx < self.custom_texts_list.size():
                    self.custom_texts_list.selection_set(idx)
                self.refresh()
            return
        sel = self.indicator_list.curselection()
        if sel:
            key = self.indicator_list.get(sel[0])
        else:
            sel = self.ext_list.curselection()
            if sel:
                ext_keys = list(GPX_EXT_FIELDS) + self.fit_ext_fields
                if 0 <= sel[0] < len(ext_keys):
                    key = ext_keys[sel[0]]
                else:
                    return
            else:
                return
        cfg = self.layout['indicators'].get(key)
        if cfg is None:
            return
        # Clear map cache when zoom or map_style changes
        old_zoom = cfg.get("zoom")
        old_style = cfg.get("map_style")
        old_form = cfg.get("form", "text")
        for field_name, widget in self.property_widgets.items():
            cfg[field_name] = widget.get()
        # Synchronizuj layout_mgr po zmianie
        if self.layout_mgr is not None:
            self.layout_mgr.layout = self.layout
        if key == "track_map" and (cfg.get("zoom") != old_zoom or cfg.get("map_style") != old_style):
            clear_map_cache()
        # If form changed, rebuild the property panel to show/hide relevant fields
        if cfg.get("form", "text") != old_form:
            self._suppress_builtin_change = True
            self.build_property_editor_builtin()
            self._suppress_builtin_change = False
        self.schedule_refresh(60)

    # ── Telemetry delegation ────────────────────────────────────────────────

    def _sync_from_telemetry(self):
        """Copy telemetry data from the manager into local attributes."""
        if not self.telemetry:
            return
        tm = self.telemetry
        self.speed_samples = tm.speed_samples
        self.alt_samples = tm.alt_samples
        self.track_samples = tm.track_samples
        self.iso_samples = tm.iso_samples
        self.exposure_samples = tm.exposure_samples
        self.temperature_samples = tm.temperature_samples
        self.start_dt_utc = tm.start_dt_utc
        self.records = tm.records
        # GPX
        self.gpx_speed_samples = tm.gpx_speed_samples
        self.gpx_alt_samples = tm.gpx_alt_samples
        self.gpx_track_samples = tm.gpx_track_samples
        self.gpx_power_samples = tm.gpx_power_samples
        self.gpx_atemp_samples = tm.gpx_atemp_samples
        self.gpx_hr_samples = tm.gpx_hr_samples
        self.gpx_cad_samples = tm.gpx_cad_samples
        # FIT
        self.fit_data = dict(tm.fit_data) if tm.fit_data else {}
        self.fit_ext_fields = list(tm.fit_ext_fields)
        # GPS track for map
        self.gps_track = list(tm.gps_track)
        self.gpx_gps_track = list(tm.gpx_gps_track)
        self.fit_gps_track = list(tm.fit_gps_track)

    def update_telemetry_data(self, progress_callback=None):
        """Load all telemetry data via TelemetryDataManager.

        Args:
            progress_callback: Optional callable(stage_percent, status_text)
                for fine-grained progress reporting during loading.
        """
        if not self.telemetry or not self.records:
            return

        tm = self.telemetry
        tm.video_path = self.video_path

        def _report(stage: int, text: str) -> None:
            if progress_callback:
                progress_callback(stage, text)

        # ── GPMF from ExifTool flat dict ──
        _report(56, "Odczyt GPMF (ExifTool)...")
        tm.load_gpmf_from_exiftool(self.video_path)
        tm.load_gpmf_records(self.records)
        tm.load_gps_track(self.records)
        gpmf_speed_n = len(tm.speed_samples)
        gpmf_gps_n = len(tm.gps_track)
        gpmf_info = f"GPMF: {gpmf_speed_n} spd, {gpmf_gps_n} GPS"

        # ── GPX ──
        _report(62, "Wczytywanie GPX...")
        manual_gpx = self.gpx_path
        if manual_gpx and Path(manual_gpx).suffix.lower() == '.gpx' and Path(manual_gpx).is_file():
            tm.load_gpx(self.video_path, tm.start_dt_utc, manual_path=Path(manual_gpx))
        else:
            tm.load_gpx(self.video_path, tm.start_dt_utc)

        if tm.gpx_speed_samples:
            if not self.gpx_path:
                tm.auto_switch_source(self.layout, "gpx")
                # Update UI labels
                auto_path = find_gpx_for_video(self.video_path)
                if auto_path:
                    self.gpx_info_var.set(f'GPX: {auto_path.name}  (auto)  {len(tm.gpx_speed_samples)} pkt')
                cur = self.meta_info_var.get()
                if "GPX" not in cur:
                    self.meta_info_var.set(cur.rstrip() + "  |  GPX: OK")

        gpx_info = f"GPX: {len(tm.gpx_speed_samples)} pkt" if tm.gpx_speed_samples else "GPX: brak"

        # ── FIT ──
        _report(66, "Wczytywanie FIT...")
        manual_fit = self.fit_path
        if manual_fit and Path(manual_fit).suffix.lower() == '.fit' and Path(manual_fit).is_file():
            tm.load_fit(self.video_path, tm.start_dt_utc, manual_path=Path(manual_fit))
        else:
            tm.load_fit(self.video_path, tm.start_dt_utc)

        if tm.fit_data:
            if not self.fit_path:
                tm.auto_switch_source(self.layout, "fit")
            total_pts = sum(len(v) for v in tm.fit_data.values())
            fields = ', '.join(sorted(tm.fit_data.keys()))
            fit_name = Path(manual_fit).name if manual_fit else "auto"
            self.fit_info_var.set(f'FIT: {fit_name}  {total_pts} pkt\n  [{fields}]')
            if not self.fit_path and manual_fit:
                self.fit_path = manual_fit
            cur = self.meta_info_var.get()
            if "FIT" not in cur:
                self.meta_info_var.set(cur.rstrip() + "  |  FIT: OK")

        fit_info = f"FIT: {len(tm.fit_data)} pól" if tm.fit_data else "FIT: brak"

        self._sync_from_telemetry()

        # ── Podsumowanie ──
        _report(70, f"Telemetria: {gpmf_info} | {gpx_info} | {fit_info}")

        print(f"speed_samples (GPMF): {len(self.speed_samples)}")
        print(f"gpx_speed_samples: {len(self.gpx_speed_samples)}")
        print(f"fit_data keys: {list(self.fit_data.keys())}")
        print(f"alt_samples (GPMF): {len(self.alt_samples)}")
        print(f"gpx_alt_samples: {len(self.gpx_alt_samples)}")


    def open_image(self):
        path = filedialog.askopenfilename(filetypes=[('Obrazy', '*.jpg *.jpeg *.png *.bmp')])
        if not path:
            return
        self.src_img = Image.open(path).convert('RGB')
        layout_path = Path(path).with_suffix('.layout.json')
        self.layout  = normalize_layout(layout_path, *self.src_img.size)
        self.build_property_editor_builtin()
        self.refresh()

    def open_video(self):
        paths = filedialog.askopenfilenames(filetypes=[('Wideo', '*.mp4 *.MP4 *.mov *.MOV')])
        if not paths:
            return

        video_paths = sorted([Path(p) for p in paths])
        self.video_paths_to_process = video_paths

        # Podstawowa ścieżka dla UI i nazw plików wyjściowych
        self.video_path = video_paths[0]

        self.loading_progress['value'] = 0
        self.loading_progress['maximum'] = 100
        self._loading_frame.pack(fill=tk.X, padx=8, pady=(4, 0))
        if len(video_paths) > 1:
            self.video_info_var.set(f"Łączenie {len(video_paths)} plików...")
        else:
            self.video_info_var.set("Wczytywanie wideo...")

        def _progress(stage: int, text: str) -> None:
            self.root.after(0, lambda: (
                self.loading_progress.configure(value=stage),
                self.loading_status.set(text),
            ))

        def bg_load():
            try:
                ffprobe_exe = find_executable(str(self.ffprobe_path), [str(self.base_dir / 'ffprobe.exe'), 'ffprobe.exe'])
                ffmpeg_exe  = find_executable('ffmpeg', [str(self.base_dir / 'ffmpeg.exe'), 'ffmpeg.exe'])
                self.ffprobe_exe = ffprobe_exe
                self.ffmpeg_exe = ffmpeg_exe
                if not ffprobe_exe:
                    raise RuntimeError('Nie znaleziono ffprobe')
                _progress(10, "Analiza strumienia wideo...")

                # Odczytujemy meta z pierwszego pliku dla rozdzielczości/fps, ale sumujemy dur
                first_info = ffprobe_stream_info(ffprobe_exe, video_paths[0])
                streams = first_info.get('streams', [])
                w = int(streams[0].get('width',  1920)) if streams else 1920
                h = int(streams[0].get('height', 1080)) if streams else 1080
                fps = parse_fps(streams[0].get('avg_frame_rate') or streams[0].get('r_frame_rate')) if streams else 30.0
                self.fps = fps

                total_dur = 0.0
                for p in video_paths:
                    p_info = ffprobe_stream_info(ffprobe_exe, p)
                    total_dur += float(p_info.get('format', {}).get('duration', 0) or 0)
                self.video_duration_s = total_dur
                _progress(25, "Pobieranie pierwszej klatki...")

                # Wyczyść cache uchwytów OpenCV (nowy plik wideo)
                clear_capture_cache()
                # Wstępne zbudowanie cache OpenCV (unikamy opóźnienia przy pierwszym seek)
                for vp in video_paths:
                    proxy = get_proxy_path(vp)
                    get_cached_capture(proxy if proxy else vp)

                # Pobranie pierwszej klatki w tle, by uniknąć zacięcia przy pierwszym odświeżeniu
                first_frame = extract_frame(video_paths, 0, ffmpeg_exe, ffprobe_exe) if ffmpeg_exe else None
                _progress(40, "Sprawdzanie metadanych telemetrii...")

                # Wstępne sprawdzenie i wczytanie telemetrii
                meta_candidate = find_metadata_json(video_paths[0])
                records = []
                if meta_candidate.exists():
                    records = ensure_records_list(load_json_with_fallback(meta_candidate))
                    _progress(55, "Przetwarzanie danych telemetrii...")
                    # Przygotuj dane telemetryczne już w wątku tła
                    self.records = records
                    self.update_telemetry_data(progress_callback=_progress)
                _progress(75, "Aktualizacja interfejsu...")

                def sync_ui():
                    self.src_img = first_frame if first_frame else Image.new('RGB', (w, h), (30, 30, 30))
                    def_layout = self.base_dir / 'def_layout.json'
                    self.layout  = normalize_layout(def_layout, w, h)
                    self.seek_slider.config(to=total_dur, tickinterval=0)
                    self.seek_var.set(0)
                    self.root.after_idle(self.draw_tick_labels)
                    # Ustawiamy na 0, jeśli klatka została pobrana, aby refresh() jej nie pobierał ponownie
                    self.last_preview_timestamp = 0 if first_frame else -1
                    self.video_duration_s = total_dur

                    self.video_info_var.set(f'Video: {w}x{h} @ {fps:.2f}fps, {total_dur:.1f}s ({len(video_paths)} plik(i))')

                    # Automatyczna nazwa pliku wyjściowego data-czas
                    try:
                        ts = getattr(self, 'start_dt_utc', None)
                        if ts is None:
                            ts = datetime.fromtimestamp(video_paths[0].stat().st_mtime)
                        if ts.tzinfo is not None:
                            ts = ts.astimezone(None)
                        self.output_var.set(ts.strftime('%Y%m%d-%H%M.mp4'))
                    except Exception:
                        pass

                    if meta_candidate.exists():
                        self.meta_path = meta_candidate
                        self.meta_info_var.set(f'Meta: {meta_candidate.name}  (z pliku)')
                        if not self.speed_samples and not self.track_samples:
                            self.render_stats.config(text='Meta JSON obecne, ale brak próbek. Odczyt...')
                            self.generate_meta_json(video_paths=video_paths, silent=True)
                    else:
                        self.meta_info_var.set('Meta JSON: brak — generuję ExifTool...')
                        self.generate_meta_json(video_paths=video_paths, silent=True)

                    # Automatyczny zapis ustawień (layoutu) – tylko gdy def_layout.json nie istnieje
                    # lub jest pusty (np. {} utworzone przez przypadkowe zapisanie)
                    try:
                        if not def_layout.exists():
                            with open(def_layout, 'w', encoding='utf-8') as f:
                                json.dump(self.layout, f, indent=2, ensure_ascii=False)
                        else:
                            existing = json.loads(def_layout.read_text(encoding='utf-8'))
                            if not isinstance(existing, dict) or not existing.get("indicators"):
                                with open(def_layout, 'w', encoding='utf-8') as f:
                                    json.dump(self.layout, f, indent=2, ensure_ascii=False)
                    except Exception: pass

                    self.build_property_editor_builtin()
                    # Register FIT fields before refresh so they render immediately
                    try:
                        self._register_fit_fields()
                    except Exception as exc:
                        print(f"[FIT] Error registering FIT fields: {exc}", flush=True)
                        import traceback
                        traceback.print_exc()
                    self.refresh()
                    self.loading_progress['value'] = 100
                    self.loading_status.set("Gotowe")
                    self.root.after(500, lambda: (
                        self.loading_progress.stop(),
                        self._loading_frame.pack_forget(),
                        self.loading_status.set("")
                    ))

                self.root.after(0, sync_ui)

            except Exception as e:
                self.root.after(0, lambda e=e: (
                    self.loading_progress.stop(),
                    self.loading_progress.configure(value=0),
                    self._loading_frame.pack_forget(),
                    self.loading_status.set(f"Błąd: {e}"),
                    messagebox.showerror('Błąd', str(e))
                ))
        threading.Thread(target=bg_load, daemon=True).start()

    def open_telemetry(self):
        """Manually select a .gpx or .fit file and store data separately."""
        path = filedialog.askopenfilename(
            filetypes=[('GPX/FIT', '*.gpx *.GPX *.fit *.FIT'), ('GPX', '*.gpx *.GPX'), ('FIT', '*.fit *.FIT'), ('Wszystkie', '*.*')],
            title='Wybierz plik GPX lub FIT'
        )
        if not path:
            return

        fpath = Path(path)
        suffix = fpath.suffix.lower()

        if suffix == '.fit':
            self.fit_path = fpath
            if not _FIT_AVAILABLE:
                messagebox.showerror('Blad FIT', 'Modul telemetry_fit nie jest dostepny.\nSprawdz czy plik telemetry_fit.py znajduje sie w tym samym katalogu.')
                self.fit_info_var.set('FIT: brak modulu telemetry_fit')
                return
            try:
                if self.telemetry:
                    self.telemetry.fit_path = self.fit_path
                    ok = self.telemetry.load_fit(self.video_path, self.start_dt_utc, manual_path=self.fit_path)
                    if not ok:
                        messagebox.showwarning('FIT', 'Plik FIT nie zawiera rekordow z czasem.')
                        return
                    self.telemetry.auto_switch_source(self.layout, "fit")
                    self._sync_from_telemetry()
                    total_pts = sum(len(v) for v in self.fit_data.values())
                    fields = ', '.join(sorted(self.fit_data.keys()))
                    self.fit_info_var.set(f'FIT: {self.fit_path.name}  ({total_pts} pkt  [{fields}])')
                    self._register_fit_fields()
                    self.build_property_editor_builtin()
                    self.refresh()
            except Exception as exc:
                messagebox.showerror('Blad FIT', str(exc))
                self.fit_info_var.set('FIT: blad wczytywania')

        else:  # .gpx
            self.gpx_path = fpath
            if not _GPX_AVAILABLE:
                messagebox.showerror('Blad GPX', 'Modul telemetry_gpx nie jest dostepny.\nSprawdz czy plik telemetry_gpx.py znajduje sie w tym samym katalogu.')
                self.gpx_info_var.set('GPX: brak modulu telemetry_gpx')
                return
            try:
                if self.telemetry:
                    self.telemetry.gpx_path = self.gpx_path
                    ok = self.telemetry.load_gpx(self.video_path, self.start_dt_utc, manual_path=self.gpx_path)
                    if not ok:
                        messagebox.showwarning('GPX', 'Plik GPX nie zawiera punktow z czasem.')
                        return
                    self.telemetry.auto_switch_source(self.layout, "gpx")
                    self._sync_from_telemetry()
                    self.gpx_info_var.set(f'GPX: {self.gpx_path.name}  ({len(self.gpx_speed_samples)} pkt)')
                    self.build_property_editor_builtin()
                    self.refresh()
            except Exception as exc:
                messagebox.showerror('Blad GPX', str(exc))
                self.gpx_info_var.set('GPX: blad wczytywania')

    def _get_samples_for_source(self, source_type):
        """Return (speed_samples, track_samples, alt_samples) for the given source."""
        if self.telemetry:
            return self.telemetry.get_samples_for_source(source_type)
        return (self.speed_samples, self.track_samples, self.alt_samples)

    def resolve_source_value(self, field_name, target_dt, prefer="fit"):
        if self.telemetry:
            return self.telemetry.resolve_value(field_name, target_dt, prefer)
        return None

    def resolve_source_samples(self, field_name, prefer="fit"):
        if self.telemetry:
            return self.telemetry.resolve_samples(field_name, prefer)
        return []

    def _register_fit_fields(self, layout: Optional[dict] = None) -> None:
        """Create ``fit_*_text`` indicators for every FIT field.

        Only GPS-positional fields (speed/alt/track/lat/lon/timestamp) are
        skipped – they are handled by built-in indicators via the source
        selector.  Every other field (heart_rate, cadence, power, …) becomes
        a separate fit_*_text entry in the Extension list.
        """
        if layout is None:
            layout = self.layout
        if not self.fit_data:
            print("[FIT] No FIT data to register (fit_data is empty)", flush=True)
            return
        _GPS_HANDLED = {"speed", "alt", "track", "lat", "lon", "timestamp"}
        if "indicators" not in layout:
            layout["indicators"] = {}
        # Clear stale extension fields when (re-)registering on the main layout
        if layout is self.layout:
            self.fit_ext_fields.clear()
        for field_name in sorted(self.fit_data.keys()):
            try:
                if field_name in _GPS_HANDLED:
                    continue
                key = f"fit_{field_name}_text"
                already_exists = key in layout["indicators"]
                if not already_exists:
                    samples = self.fit_data[field_name]
                    vals = [v for _, v in samples if v is not None]
                    max_val = max(vals) if vals else 100
                    min_val = min(vals) if vals else 0
                    layout["indicators"][key] = {
                        "enabled": True,
                        "label": field_name.replace("_", " ").title(),
                        "x": 0.5, "y": 0.08, "rotation": 0,
                        "form": "text",
                        "font_size": 0.018, "size": 0.1, "thickness": 0.001,
                        "min_val": min_val, "max_val": max(max_val, min_val + 1),
                        "ticks": 0, "source": "fit",
                        "unit": "",
                    }
                    BUILTIN_FIELDS[key] = get_value_schema()
                    print(
                        f"[FIT] Registered: {key}"
                        f" ({len(samples)} samples, range {min_val}–{max_val})",
                        flush=True,
                    )
                if layout is self.layout:
                    self.fit_ext_fields.append(key)
            except Exception as exc:
                print(
                    f"[FIT] Skipping field '{field_name}': {exc}",
                    flush=True,
                )
                import traceback
                traceback.print_exc()
                continue
        if layout is self.layout:
            self._rebuild_ext_list()

    def _rebuild_ext_list(self) -> None:
        """Rebuild the Extension listbox – GPX extension + FIT dynamic indicators."""
        if not hasattr(self, 'ext_list'):
            return
        self.ext_list.delete(0, tk.END)
        # GPX extension fields (power, atemp, hr, cad, battery)
        for key in GPX_EXT_FIELDS:
            cfg = self.layout["indicators"].get(key, {})
            label = cfg.get("label", GPX_EXT_LABELS.get(key, key))
            self.ext_list.insert(tk.END, label)
        # FIT dynamic fields
        for key in self.fit_ext_fields:
            cfg = self.layout["indicators"].get(key, {})
            label = cfg.get("label", key)
            self.ext_list.insert(tk.END, label)

    def _rebuild_indicator_list(self) -> None:
        """Rebuild the main indicator listbox from the current layout."""
        if not hasattr(self, 'indicator_list'):
            return
        self.indicator_list.delete(0, tk.END)
        for key in self.layout.get('indicators', {}):
            if key not in GPX_EXT_FIELDS and not key.startswith("fit_"):
                self.indicator_list.insert(tk.END, key)

    def refresh(self):
        self._refresh_after_id = None
        try:
            # Bez wgranego pliku – tylko czarny obraz
            if self.video_path is None:
                pw = self.preview_label.winfo_width()
                ph = self.preview_label.winfo_height()
                if pw > 10 and ph > 10:
                    blank = Image.new('RGB', (pw, ph), (0, 0, 0))
                    self.photo = ImageTk.PhotoImage(blank)
                    self.preview_label.configure(image=self.photo)
                return

            pw = self.preview_label.winfo_width()
            ph = self.preview_label.winfo_height()
            if pw < 10 or ph < 10:
                return

            current_ts = self.seek_var.get()
            if self.video_paths_to_process:
                if abs(current_ts - self.last_preview_timestamp) > 0.1:
                    ffmpeg_exe = self.ffmpeg_exe or find_executable('ffmpeg', [str(self.base_dir / 'ffmpeg.exe'), 'ffmpeg.exe'])
                    ffprobe_exe = self.ffprobe_exe or find_executable('ffprobe', [str(self.base_dir / 'ffprobe.exe'), 'ffprobe.exe'])
                    if ffmpeg_exe and ffprobe_exe:
                        try:
                            self._preview_queue.get_nowait()
                        except queue.Empty:
                            pass
                        self._preview_queue.put((self.video_paths_to_process, current_ts, ffmpeg_exe, ffprobe_exe))

            # Dane do podglądu (Demo jeśli brak telemetrii)
            speed_val, dist_m, max_dist, alt_val, iso_val, exp_val, temp_val = 45.0, 1500.0, 10000.0, 70.0, 100, 500, 25
            power_val, atemp_val, hr_val, cad_val, battery_val = 0, 20, 0, 0, 85
            date_txt, time_txt = "2026-06-17", "12:00:00.0"
            indicator_values = {}
            max_speed_kmh = None
            target_dt = None

            if self.start_dt_utc:
                update_rate = self.update_rate_var.get()
                if update_rate == 'Half':
                    N = 2
                elif update_rate == 'Quarter':
                    N = 4
                else:
                    N = 1
                fps = getattr(self, 'fps', 30.0)
                frame_idx = int(round(current_ts * fps))
                calc_frame_idx = max(0, frame_idx - (frame_idx % N))
                calc_ts = calc_frame_idx / fps

                target_dt = self.start_dt_utc + timedelta(seconds=calc_ts)
                if target_dt.tzinfo is None:
                    target_dt = target_dt.replace(tzinfo=timezone.utc)

                # ── Oblicz wartości per-wskaźnik uwzględniając źródło danych ──
                # Dla każdego wskaźnika sprawdzamy źródło w layout i interpolujemy z odpowiednich próbek
                indicator_values = {}
                for ind_key in ('speed_visual', 'speed_text', 'dist_visual', 'dist_text', 'alt_visual', 'alt_text'):
                    ind_cfg = self.layout['indicators'].get(ind_key, {})
                    src = ind_cfg.get('source', 'gpmf')
                    spd_s, trk_s, alt_s = self._get_samples_for_source(src)
                    if ind_key in ('speed_visual', 'speed_text'):
                        indicator_values[ind_key] = interpolate_speed(spd_s, target_dt)
                    elif ind_key in ('dist_visual', 'dist_text'):
                        indicator_values[ind_key] = interpolate_distance(trk_s, target_dt)
                    elif ind_key in ('alt_visual', 'alt_text'):
                        indicator_values[ind_key] = interpolate_altitude(alt_s, target_dt)

                speed_val = indicator_values.get('speed_visual', interpolate_speed(self.speed_samples, target_dt))
                dist_m    = indicator_values.get('dist_visual', interpolate_distance(self.track_samples, target_dt))
                # Debug source switching
                if self.track_samples:
                    max_dist = self.track_samples[-1][1]
                    # Dla dist_visual użyj dystansu z tego samego źródła co wskaźnik
                    dist_src = self.layout['indicators'].get('dist_visual', {}).get('source', 'gpmf')
                    _, trk_s, _ = self._get_samples_for_source(dist_src)
                    if trk_s:
                        max_dist = trk_s[-1][1]

                # max_speed_kmh z odpowiedniego źródła
                max_speed_kmh = None
                spd_src = self.layout['indicators'].get('speed_visual', {}).get('source', 'gpmf')
                spd_s, _, _ = self._get_samples_for_source(spd_src)
                if spd_s:
                    spd_vals = [s for _, s in spd_s]
                    if spd_vals:
                        max_speed_kmh = max(spd_vals)

                if self.alt_samples:
                    alt_val = indicator_values.get('alt_visual', interpolate_altitude(self.alt_samples, target_dt))

                # ── Wartości GPMF-native przez helper ──
                iso_val     = self.resolve_source_value("iso", target_dt)
                exp_val     = self.resolve_source_value("exposure", target_dt)
                temp_val    = self.resolve_source_value("temperature", target_dt)

                # ── Wartości z GPX/FIT extensions (przez helper) ──
                power_val   = self.resolve_source_value("power", target_dt)
                atemp_val   = self.resolve_source_value("atemp", target_dt)
                hr_val      = self.resolve_source_value("hr", target_dt)
                cad_val     = self.resolve_source_value("cad", target_dt)
                battery_val = self.resolve_source_value("battery", target_dt)

                try: tz_off = int(self.tz_offset_var.get())
                except: tz_off = 2

                local_dt = target_dt + timedelta(hours=tz_off)
                date_txt = local_dt.strftime('%Y-%m-%d')
                time_txt = local_dt.strftime('%H:%M:%S')

            try:
                # Cache min/max alt (przelicz tylko gdy dane się zmienią)
                alt_src = self.layout['indicators'].get('alt_visual', {}).get('source', 'gpmf')
                if self.telemetry:
                    min_alt, max_alt = self.telemetry.get_alt_range(alt_src)
                else:
                    min_alt = max_alt = None

                # ── Przygotuj dane wykresów (chart) dla podglądu ──
                total_duration = getattr(self, 'video_duration_s', 1.0)
                try: fps_val = self.fps
                except: fps_val = 30.0
                total_frames = max(1, int(total_duration * fps_val))
                current_position = current_ts / max(1.0, total_duration) if total_duration > 0 else 0.0
                chart_data = build_chart_data(
                    self.layout,
                    self._get_samples_for_source,
                    self.resolve_source_samples,
                )

                # Build extra indicators from FIT fields
                extra_indicators = {}
                for key in self.fit_ext_fields:
                    field_name = key[4:-5]  # strip "fit_" and "_text"
                    if field_name in self.fit_data:
                        val = self.resolve_source_value(field_name, target_dt) or 0.0
                    else:
                        val = 0.0
                    cfg = self.layout["indicators"].get(key, {})
                    unit = cfg.get("unit", "")
                    label = cfg.get("label", field_name)
                    extra_indicators[key] = (val, unit, label)

                self.indicator_bboxes.clear()
                # Resolve GPS track for map indicator
                map_src = "gpmf"
                if self.telemetry:
                    map_src = self.layout["indicators"].get("track_map", {}).get("source", "gpmf")
                map_gps_track = None
                if map_src == "gpx":
                    map_gps_track = self.gpx_gps_track or self.gps_track
                elif map_src == "fit":
                    map_gps_track = self.fit_gps_track or self.gps_track
                else:
                    map_gps_track = self.gps_track

                preview = render_preview(self.src_img, self.layout, self.font_path,
                                         date_txt, time_txt, speed_val, dist_m, max_dist, alt_val, min_alt, max_alt, iso_val, exp_val, temp_val,
                                         indicator_values=indicator_values, max_speed_kmh=max_speed_kmh,
                                         power_value=power_val, atemp_value=atemp_val,
                                         hr_value=hr_val, cad_value=cad_val,
                                         battery_value=battery_val,
                                         _bboxes=self.indicator_bboxes,
                                         chart_data=chart_data, current_position=current_position,
                                         extra_indicators=extra_indicators,
                                         gps_track=map_gps_track,
                                         target_dt=target_dt,
                                         start_dt_utc=self.start_dt_utc)
                preview.thumbnail((pw, ph), Image.BILINEAR)
                self.photo = ImageTk.PhotoImage(preview)
                self.preview_label.configure(image=self.photo)
            except Exception as e:
                self.preview_label.configure(image='', text=f'Błąd podglądu:\n{e}')
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self.preview_label.configure(image='', text=f'Błąd (callback):\n{e}')
            except Exception:
                pass

    def save_configuration(self):
        if not self.video_path:
            messagebox.showerror('Błąd', 'Najpierw wybierz plik MP4.')
            return
        def_layout = self.base_dir / 'def_layout.json'
        with open(def_layout, 'w', encoding='utf-8') as f:
            json.dump(self.layout, f, indent=2, ensure_ascii=False)
        # Synchronizuj layout_mgr, aby był spójny ze stanem UI
        if self.layout_mgr is not None:
            self.layout_mgr.layout = self.layout
        messagebox.showinfo('Zapisano', f'Konfiguracja zapisana:\n{def_layout}')

    def on_font_change(self, event=None):
        self.font_path = resolve_font_path(self.font_style_var.get())
        FONT_CACHE.clear()
        self.refresh()

    def on_outline_change(self):
        if self.layout_mgr is not None:
            self.layout_mgr.set_outline(self.outline_var.get())
        else:
            self.layout.setdefault("global", {})["text_outline"] = self.outline_var.get()
        self.refresh()

    def load_json(self):
        path = filedialog.askopenfilename(filetypes=[('JSON', '*.json')])
        if not path:
            return
        try:
            w, h = self.src_img.size
            if self.layout_mgr is not None:
                self.layout = self.layout_mgr.load(path, w, h)
            else:
                self.layout = normalize_layout(path, w, h)
            # Rejestruj pola FIT przed budową edytora, aby nowe wskaźniki trafiły do UI
            self._register_fit_fields()
            self._rebuild_indicator_list()
            self.build_property_editor_builtin()
            self.refresh()
        except Exception as e:
            messagebox.showerror('Błąd', str(e))

    def render_now(self, layout_path=None):
        if not self.video_path:
            messagebox.showerror('Błąd', 'Nie wybrano pliku MP4.')
            return
        if layout_path is None:
            layout_path = self.base_dir / 'def_layout.json'
        meta_candidate = self.video_path.with_suffix(".json")
        if not meta_candidate.exists():
            if messagebox.askyesno('Brak JSON', f'Nie znaleziono:\n{meta_candidate}\n\nWygenerować przez exiftool?'):
                self.generate_meta_json(callback=lambda: self.render_now(layout_path=layout_path))
                return
            else:
                return
        encoder       = self.encoder_var.get()
        prefer_3d     = True
        resolution    = self.resolution_var.get()
        video_bitrate = self.video_bitrate_var.get().strip()
        output_file   = sanitize_output_path(self.output_var.get().strip() or 'output_h265.mp4')
        try:
            tz_offset = int(self.tz_offset_var.get())
        except ValueError:
            tz_offset = 2
        if not output_file.is_absolute():
            output_file = self.video_path.parent / output_file

        # Zapisz lokalną konfigurację obok pliku wyjściowego (do użytku tylko dla tego pliku MP4)
        local_config_path = output_file.parent / f"{output_file.stem}.layout.json"
        try:
            local_config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_config_path, 'w', encoding='utf-8') as f:
                json.dump(self.layout, f, indent=2, ensure_ascii=False)
            print(f"[CONFIG] Lokalna konfiguracja zapisana: {local_config_path}", flush=True)
        except Exception as exc:
            print(f"[CONFIG] Nie udało się zapisać lokalnej konfiguracji: {exc}", flush=True)

        # Aktualizuj def_layout.json – render_pipeline wczytuje layout z tego pliku
        try:
            with open(self.base_dir / 'def_layout.json', 'w', encoding='utf-8') as f:
                json.dump(self.layout, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[CONFIG] Nie udało się zapisać def_layout.json: {exc}", flush=True)

        workers = None
        if self.worker_mode_var.get() == 'manual':
            try:
                workers = max(1, int(self.worker_count_var.get()))
            except Exception:
                pass

        self.render_stats.config(text="Rozpoczynanie renderowania...")
        self.render_progress.config(mode='determinate', value=0)
        self.render_cancel_event.clear()
        self.render_button.config(text='Anuluj', command=self.cancel_render)

        def run_render():
            try:
                t_export_start = time.time()
                print(f"Render start: input={self.video_paths_to_process}, output={output_file}")
                self.root.after(0, lambda: (
                    self._render_frame.pack(fill=tk.X, padx=8, pady=(0, 4)),
                    self.render_stats.config(text="Render w tle...")
                ))
                stats = self.render_pipeline(
                    input_file=self.video_paths_to_process,
                    meta_path=meta_candidate,
                    layout_path=layout_path,
                    output_file=output_file,
                    encoder=encoder,
                    prefer_3d=prefer_3d,
                    resolution=resolution,
                    video_bitrate=video_bitrate,
                    workers=workers,
                    tz_offset=tz_offset
                )
                t_export_end = time.time()
                export_duration = t_export_end - t_export_start
                if not self.render_cancel_event.is_set() and stats:
                    self.root.after(0, lambda: self.show_statistics_dialog(stats, export_duration, output_file))
            except Exception as e:
                err_msg = str(e)
                print('Render thread exception:', err_msg)
                self.root.after(0, lambda msg=err_msg: messagebox.showerror('Błąd renderowania', msg))
            finally:
                self.root.after(0, self._on_render_finished)

        threading.Thread(target=run_render, daemon=True).start()

    def cancel_render(self):
        self.render_cancel_event.set()
        if isinstance(self._active_process, dict):
            process = self._active_process.get('process')
            if process is not None:
                try:
                    process.terminate()
                except Exception:
                    pass
        elif self._active_process is not None:
            try:
                self._active_process.terminate()
            except Exception:
                pass
        self.render_stats.config(text='Przerywanie renderowania...')
        self.render_button.config(state='disabled')

    def _on_render_finished(self):
        self.render_button.config(text='Render teraz', command=self.render_now, state='normal')
        if self.render_cancel_event.is_set():
            self.render_stats.config(text='Anulowano')
        else:
            self.render_stats.config(text='Gotowy')
        self.render_progress.stop()
        self.render_progress.config(value=0, mode='determinate')
        self._render_frame.pack_forget()

    def show_statistics_dialog(self, stats, export_duration, output_file):
        dialog = tk.Toplevel(self.root)
        dialog.title("Statystyki eksportu")
        dialog.geometry("500x320")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        try:
            x = self.root.winfo_x() + (self.root.winfo_width() - 500) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - 320) // 2
            dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass

        title_label = ttk.Label(dialog, text="Eksport zakończony pomyślnie!", font=("Segoe UI", 12, "bold"))
        title_label.pack(pady=(15, 5))

        desc_label = ttk.Label(dialog, text=f"Plik: {Path(output_file).name}", font=("Segoe UI", 9, "italic"))
        desc_label.pack(pady=(0, 15))

        table_frame = ttk.Frame(dialog, padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        ttk.Label(table_frame, text="Etap", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=5)
        ttk.Label(table_frame, text="Czas trwania", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(table_frame, text="Średnia wydajność", font=("Segoe UI", 10, "bold")).grid(row=0, column=2, sticky="w", padx=10, pady=5)

        ttk.Separator(table_frame, orient='horizontal').grid(row=1, column=0, columnspan=3, sticky='ew', pady=5)

        def fmt_time(seconds):
            if seconds >= 60:
                mins = int(seconds // 60)
                secs = seconds % 60
                return f"{mins} min {secs:.1f} s"
            return f"{seconds:.2f} s"

        def fmt_fps(frames, duration):
            if duration <= 0:
                return "0.0 fps"
            return f"{frames / duration:.1f} fps"

        # 1. Total Export
        total_time_str = fmt_time(export_duration)
        total_fps_str = fmt_fps(stats['final_frames'], export_duration)

        ttk.Label(table_frame, text="Od naciśnięcia Export", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w", padx=10, pady=5)
        ttk.Label(table_frame, text=total_time_str, font=("Segoe UI", 10, "bold")).grid(row=2, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(table_frame, text=total_fps_str, font=("Segoe UI", 10, "bold")).grid(row=2, column=2, sticky="w", padx=10, pady=5)

        # 2. Streaming render (jednoetapowy)
        png_time_str = fmt_time(stats['png_duration'])
        png_fps_str = fmt_fps(stats['total_overlay_frames'], stats['png_duration'])

        ttk.Label(table_frame, text="Render HUD + kompresja").grid(row=3, column=0, sticky="w", padx=10, pady=5)
        ttk.Label(table_frame, text=png_time_str).grid(row=3, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(table_frame, text=png_fps_str).grid(row=3, column=2, sticky="w", padx=10, pady=5)

        btn = ttk.Button(dialog, text="OK", command=dialog.destroy)
        btn.pack(pady=15)

    def generate_meta_json(self, video_paths=None, silent=False, callback=None):
        paths = video_paths or self.video_paths_to_process or ([self.video_path] if self.video_path else [])
        if not paths:
            return

        self.render_stats.config(text="Generowanie telemetrii...")
        self.render_progress.config(mode='indeterminate')
        self.render_progress.start()

        def worker():
            method_used = "ExifTool"  # default fallback
            try:
                # ── Step 1: try GPMF binary parser (native Python, no external deps) ──
                if _GPMF_AVAILABLE:
                    try:
                        ffmpeg_exe = self.ffmpeg_exe or find_executable(
                            'ffmpeg', [str(self.base_dir / 'ffmpeg.exe'), 'ffmpeg.exe'])
                        ffprobe_exe = self.ffprobe_exe or find_executable(
                            str(self.ffprobe_path), [str(self.base_dir / 'ffprobe.exe'), 'ffprobe.exe'])

                        if ffmpeg_exe and ffprobe_exe:
                            print("➡ GPMF: extracting binary stream via ffmpeg...", flush=True)
                            data = gpmf_to_exiftool_json(paths[0], ffmpeg_exe, ffprobe_exe)
                            if data:
                                method_used = "GPMF"
                                print("✅ GPMF extraction succeeded", flush=True)
                            else:
                                raise RuntimeError("GPMF returned empty data")
                        else:
                            raise RuntimeError("ffmpeg/ffprobe not found for GPMF")
                    except Exception as gpmf_err:
                        # GPMF failed — fall through to ExifTool
                        print(f"⚠ GPMF failed: {gpmf_err} — falling back to ExifTool", flush=True)

                # ── Step 2: ExifTool fallback ──
                if method_used == "ExifTool":
                    print("➡ USING EXIFTOOL", flush=True)

                    exiftool_exe = find_executable(
                        str(self.exiftool_path),
                        [str(self.base_dir / 'exiftool.exe'), 'exiftool.exe']
                    )

                    if not exiftool_exe:
                        raise RuntimeError("❌ Nie znaleziono exiftool")

                    self.exiftool_path = exiftool_exe

                    cmd = [
                        exiftool_exe,
                        "-ee",
                        "-j",
                        "-G3",
                        str(paths[0])
                    ]

                    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                    if proc.returncode != 0:
                        raise RuntimeError(proc.stderr or "ExifTool error")

                    data = json.loads(proc.stdout)
                    if not data:
                        raise RuntimeError("❌ ExifTool zwrócił puste dane")

                flat = data[0]

                # ✅ ZAPIS DO TEGO SAMEGO KATALOGU CO VIDEO
                json_path = self.video_path.with_suffix(".json")

                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(flat, f, indent=2, ensure_ascii=False)

                print(f"✅ JSON zapisany: {json_path}  (method: {method_used})")

                # ✅ WAŻNE – dalsza część programu
                self.records = [flat]

                def _meta_progress(stage: int, text: str) -> None:
                    self.root.after(0, lambda t=text: self.render_stats.config(text=t))

                self.update_telemetry_data(progress_callback=_meta_progress)

                def success():
                    self.render_progress.stop()
                    self.render_progress.config(mode='determinate', value=0)
                    self.render_stats.config(text="Gotowy")

                    self.meta_path = json_path
                    self.meta_info_var.set(f'Meta: {json_path.name}  ({method_used})')

                    self.build_property_editor_builtin()
                    # Register FIT fields before refresh so they render immediately
                    try:
                        self._register_fit_fields()
                    except Exception as exc:
                        print(f"[FIT] Error registering FIT fields: {exc}", flush=True)
                        import traceback
                        traceback.print_exc()
                    self.refresh()

                    if not silent:
                        messagebox.showinfo('OK', f'JSON wygenerowany ({method_used}):\n{json_path}')

                    if callback:
                        callback()

                self.root.after(0, success)

            except Exception as e:
                err_text = str(e)

                def error(err=err_text):
                    self.render_progress.stop()
                    self.render_progress.config(mode='determinate', value=0)
                    self.render_stats.config(text="Błąd")
                    messagebox.showerror('Błąd telemetrii', err)

                self.root.after(0, error)

        threading.Thread(target=worker, daemon=True).start()

    def render_pipeline(self, input_file, meta_path, layout_path, output_file,
                        encoder, prefer_3d, resolution, video_bitrate,
                        workers=None, tz_offset=2):
        ffmpeg_exe  = self.ffmpeg_exe or find_executable('ffmpeg',  [str(self.base_dir / 'ffmpeg.exe'), 'ffmpeg.exe'])
        ffprobe_exe = self.ffprobe_exe or find_executable(str(self.ffprobe_path), [str(self.base_dir / 'ffprobe.exe'), 'ffprobe.exe'])
        self.ffmpeg_exe = ffmpeg_exe
        self.ffprobe_exe = ffprobe_exe
        if not ffmpeg_exe:
            raise RuntimeError('Nie znaleziono ffmpeg.exe.')
        if not ffprobe_exe:
            raise RuntimeError('Nie znaleziono ffprobe.exe.')
        if not Path(self.font_path).exists() and not any(p in str(self.font_path) for p in ('/', '\\')):
            # Font is a family name, not a path – try loading it, fallback to default
            pass
        elif not Path(self.font_path).exists():
            raise RuntimeError(f'Nie znaleziono czcionki: {self.font_path}')

        # Obsługa listy plików wejściowych
        primary_input = input_file[0] if isinstance(input_file, list) else input_file
        info    = ffprobe_stream_info(ffprobe_exe, primary_input)
        streams = info.get('streams', [])
        fps          = parse_fps(streams[0].get('avg_frame_rate') or streams[0].get('r_frame_rate')) if streams else 30.0
        video_width  = int(streams[0].get('width',  1920)) if streams else 1920
        video_height = int(streams[0].get('height', 1080)) if streams else 1080

        duration_s = self.video_duration_s if isinstance(input_file, list) and input_file == self.video_paths_to_process and self.video_duration_s > 0 else 0.0
        if duration_s <= 0.0:
            if isinstance(input_file, list):
                for p in input_file:
                    duration_s += float(ffprobe_stream_info(ffprobe_exe, p).get('format', {}).get('duration', 0))
            else:
                duration_s = float(info.get('format', {}).get('duration', 0))

        if duration_s <= 0:
            raise RuntimeError('Nie udało się odczytać długości filmu.')

        target_res = RESOLUTION_MAP.get(resolution)
        render_width, render_height = (video_width, video_height) if target_res is None else target_res

        records = ensure_records_list(load_json_with_fallback(meta_path))

        # --- v4.1.3: odczytaj rotację PRZED generowaniem klatek ---
        rotation_degrees = get_rotation_from_metadata(records)
        container_rotation = get_container_rotation(ffprobe_exe, input_file)

        # Manual override from UI: 'auto' or one of 0/90/180/270
        rotation_override = self.rotation_var.get() if hasattr(self, 'rotation_var') else 'auto'
        if rotation_override != 'auto':
            effective_rotation = int(rotation_override)
            # when user forces rotation, disable container auto-rotate handling
            container_rotation_arg = 0
        else:
            # container rotation tag is the primary indicator of actual pixel orientation.
            # When container has no rotation tag (0), fall back to GoPro metadata:
            # some files have pixels NOT pre-rotated by the camera but DO have AutoRotation
            # metadata indicating the correct orientation.
            effective_rotation = container_rotation if container_rotation != 0 else rotation_degrees
            container_rotation_arg = container_rotation

        print(f"[ROTATION] container={container_rotation}  metadata={rotation_degrees}  "
              f"override={rotation_override}  effective={effective_rotation}", flush=True)

        overlay_width, overlay_height = render_width, render_height
        if effective_rotation in (90, 270):
            overlay_width, overlay_height = render_height, render_width

        layout   = normalize_layout(layout_path, overlay_width, overlay_height)

        gpmf_speed = extract_speed_samples(records, prefer_3d=prefer_3d)
        gpmf_speed = smooth_speed_samples(gpmf_speed, "moving_average", SMOOTHING_WINDOW)
        gpmf_track = extract_track_samples(records)
        gpmf_alt   = extract_altitude_samples(records)
        iso_samples          = extract_iso_samples(records)
        exposure_samples     = extract_exposure_samples(records)
        temperature_samples  = extract_temperature_samples(records)
        if gpmf_alt:
            gpmf_alt = smooth_speed_samples(gpmf_alt, "moving_average", SMOOTHING_WINDOW)

        # Użyj start_dt_utc z GUI – FIT/GPX były do niego zsynchronizowane
        start_dt_utc = getattr(self, 'start_dt_utc', None)
        if start_dt_utc is None:
            anchor = find_gps_anchor(records)
            if anchor:
                start_dt_utc = anchor
            elif gpmf_speed:
                start_dt_utc = gpmf_speed[0][0]
            else:
                start_dt_utc = None

        # GPX: osobne próbki – źródło wybierane per-wskaźnik
        gpx_speed_samples = []
        gpx_track_samples = []
        gpx_alt_samples = []
        gpx_power_samples = []
        gpx_atemp_samples = []
        gpx_hr_samples = []
        gpx_cad_samples = []
        gpx_result = process_gpx(primary_input, start_dt_utc)
        if gpx_result is not None:
            gpx_speed, gpx_track, gpx_alt, gpx_power, gpx_atemp, gpx_hr, gpx_cad = gpx_result
            if gpx_speed:
                gpx_speed_samples = smooth_speed_samples(gpx_speed, "moving_average", SMOOTHING_WINDOW)
                print("[GPX] render: gpx_speed_samples: " + str(len(gpx_speed_samples)), flush=True)
            if gpx_track:
                gpx_track_samples = gpx_track
                print("[GPX] render: gpx_track_samples: " + str(len(gpx_track_samples)), flush=True)
            if gpx_alt:
                gpx_alt_samples = smooth_speed_samples(gpx_alt, "moving_average", SMOOTHING_WINDOW)
                print("[GPX] render: gpx_alt_samples: " + str(len(gpx_alt_samples)), flush=True)
            if gpx_power:
                gpx_power_samples = gpx_power
                print("[GPX] render: gpx_power_samples: " + str(len(gpx_power_samples)), flush=True)
            if gpx_atemp:
                gpx_atemp_samples = gpx_atemp
                print("[GPX] render: gpx_atemp_samples: " + str(len(gpx_atemp_samples)), flush=True)
            if gpx_hr:
                gpx_hr_samples = gpx_hr
                print("[GPX] render: gpx_hr_samples: " + str(len(gpx_hr_samples)), flush=True)
            if gpx_cad:
                gpx_cad_samples = gpx_cad
                print("[GPX] render: gpx_cad_samples: " + str(len(gpx_cad_samples)), flush=True)
            if start_dt_utc is None and gpx_speed:
                start_dt_utc = gpx_speed[0][0]

        # FIT: dynamiczne pola z self.fit_data
        fit_data = dict(getattr(self, 'fit_data', {}) or {})

        # Fallback: parsuj z pliku tylko jeśli GUI nie ma danych
        manual_fit = getattr(self, 'fit_path', None)
        if not fit_data:
            # Auto-discover FIT if no manual path
            if not (manual_fit and Path(manual_fit).suffix.lower() == '.fit' and Path(manual_fit).is_file()):
                auto_fit = find_fit_for_video(primary_input)
                if auto_fit:
                    manual_fit = auto_fit
                    print(f"[FIT] render: auto-discovered {manual_fit}", flush=True)
            if manual_fit and Path(manual_fit).suffix.lower() == '.fit' and Path(manual_fit).is_file():
                try:
                    fit_result = process_fit(manual_fit, start_dt_utc)
                except Exception as _e:
                    print('[FIT] render: blad wczytywania FIT: ' + str(_e), flush=True)
                    fit_result = None
                if fit_result:
                    fit_data = {}
                    for key, samples in fit_result.items():
                        if key in ('speed', 'alt'):
                            fit_data[key] = smooth_speed_samples(samples, "moving_average", SMOOTHING_WINDOW)
                        else:
                            fit_data[key] = samples
                        print(f"[FIT] render: {key}_samples: {len(fit_data[key])}", flush=True)
                    if start_dt_utc is None and fit_data.get('speed'):
                        start_dt_utc = fit_data['speed'][0][0]

        # Register FIT fields in the render layout
        if fit_data:
            orig_fit_data = self.fit_data
            self.fit_data = fit_data
            self._register_fit_fields(layout)
            self.fit_data = orig_fit_data

        # Fallback: jeśli GPX puste, używamy GPMF jako źródła
        speed_samples = gpmf_speed
        track_samples = gpmf_track
        alt_samples   = gpmf_alt

        if not speed_samples:
            raise RuntimeError(f'Nie znaleziono próbek prędkości w pliku: {meta_path}')
        if not track_samples:
            raise RuntimeError(f'Nie znaleziono próbek GPS do dystansu w pliku: {meta_path}')

        field_samples = {
            'speed_samples': gpmf_speed,
            'track_samples': gpmf_track,
            'alt_samples': gpmf_alt,
        }
        # max_distance_m z domyślnego źródła (gpmf), render_overlay_job dobierze per-wskaźnik
        max_distance_m = gpmf_track[-1][1] if gpmf_track else 0

        update_rate_str = self.update_rate_var.get() if hasattr(self, 'update_rate_var') else 'Full'
        if update_rate_str == 'Half':
            update_rate_step = 2
        elif update_rate_str == 'Quarter':
            update_rate_step = 4
        else:
            update_rate_step = 1

        generation_fps = fps / update_rate_step
        total_overlay_frames = max(1, math.ceil(duration_s * generation_fps))

        def update_ui(val, stats):
            self.root.after(0, lambda: (
                self.render_progress.config(mode='determinate'),
                self.render_progress.config(value=val),
                self.render_stats.config(text=stats)
            ))

        # ── NOWY PIPELINE: Producent-Konsument → pipe do FFmpeg ──
        self.render_progress['maximum'] = total_overlay_frames
        update_ui(0, "Renderowanie HUD (stream)...")
        self._active_process = {'process': None}
        t_render_start = time.time()

        stream_overlay_to_ffmpeg(
            ffmpeg_exe=ffmpeg_exe,
            input_files=input_file,
            output_file=sanitize_output_path(output_file),
            duration_s=duration_s,
            start_dt_utc=start_dt_utc,
            tz_offset_hours=tz_offset,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            font_path=self.font_path,
            layout=layout,
            field_samples=field_samples,
            target_fps=fps,
            update_rate_step=update_rate_step,
            max_distance_m=max_distance_m,
            workers=workers,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temperature_samples,
            gpx_speed_samples=gpx_speed_samples,
            gpx_track_samples=gpx_track_samples,
            gpx_alt_samples=gpx_alt_samples,
            gpx_power_samples=gpx_power_samples,
            gpx_atemp_samples=gpx_atemp_samples,
            gpx_hr_samples=gpx_hr_samples,
            gpx_cad_samples=gpx_cad_samples,
            fit_data=fit_data,
            gps_track=getattr(self, 'gps_track', None) or [],
            progress_cb=update_ui,
            cancel_event=self.render_cancel_event,
            active_process_holder=self._active_process,
            encoder=encoder,
            gpu=0,
            resolution_name=resolution,
            video_bitrate=video_bitrate,
            rotation_degrees=effective_rotation,
            container_rotation=container_rotation_arg,
            overlay_w=overlay_width,
            overlay_h=overlay_height,
            render_w=render_width,
            render_h=render_height,
        )
        t_render_end = time.time()
        render_duration = t_render_end - t_render_start

        if self.render_cancel_event.is_set():
            return

        return {
            'total_overlay_frames': total_overlay_frames,
            'final_frames': int(duration_s * fps),
            'png_duration': render_duration,
            'mov_duration': 0,
            'final_duration': 0,
        }


def main():
    """Entry point for the HUD Tuner GUI application."""
    root = tk.Tk()
    app = HudTunerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
