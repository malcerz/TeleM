"""Export controller for HUD Tuner GUI application.

Manages video rendering pipeline execution, ExifTool/GPMF metadata generation, and progress UI updates.
"""

import json
import math
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

from src.ffmpeg_pipeline import (
    RESOLUTION_MAP,
    stream_overlay_to_ffmpeg,
)
from src.video_helpers import find_executable
from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    find_gps_anchor,
    get_container_rotation,
    get_rotation_from_metadata,
    load_json_with_fallback,
    smooth_speed_samples,
)
from src.gui.dialogs.statistics_dialog import show_statistics_dialog

# GPMF binary parser – native Python extraction
try:
    from src.telemetry_gpmf_new import gpmf_to_exiftool_json
    _GPMF_AVAILABLE = True
except ImportError:
    _GPMF_AVAILABLE = False

try:
    from telemetry_gpx import process_gpx
except ImportError:
    def process_gpx(video_path, video_start_dt=None):
        return None

try:
    from telemetry_fit import find_fit_for_video, process_fit
except ImportError:
    def find_fit_for_video(video_path): return None
    def process_fit(manual_fit, start_dt_utc): return None

SMOOTHING_WINDOW = 5


class ExportController:
    """Manages video export, telemetry metadata generation, and progress tracking."""

    def __init__(self, app):
        self.app = app

    def render_now(self, layout_path=None):
        if not self.app.video_path:
            messagebox.showerror('Błąd', 'Nie wybrano pliku MP4.')
            return
        if layout_path is None:
            layout_path = self.app.base_dir / 'def_layout.json'
        meta_candidate = self.app.video_path.with_suffix(".json")
        if not meta_candidate.exists():
            if messagebox.askyesno('Brak JSON', f'Nie znaleziono:\n{meta_candidate}\n\nWygenerować przez exiftool?'):
                self.generate_meta_json(callback=lambda: self.render_now(layout_path=layout_path))
                return
            else:
                return
        encoder       = self.app.encoder_var.get()
        prefer_3d     = True
        resolution    = self.app.resolution_var.get()
        video_bitrate = self.app.video_bitrate_var.get().strip()
        output_file   = sanitize_output_path(self.app.output_var.get().strip() or 'output_h265.mp4')
        try:
            tz_offset = int(self.app.tz_offset_var.get())
        except ValueError:
            tz_offset = 2
        if not output_file.is_absolute():
            output_file = self.app.video_path.parent / output_file

        # Zapisz lokalną konfigurację obok pliku wyjściowego
        local_config_path = output_file.parent / f"{output_file.stem}.layout.json"
        try:
            local_config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_config_path, 'w', encoding='utf-8') as f:
                json.dump(self.app.layout, f, indent=2, ensure_ascii=False)
            print(f"[CONFIG] Lokalna konfiguracja zapisana: {local_config_path}", flush=True)
        except Exception as exc:
            print(f"[CONFIG] Nie udało się zapisać lokalnej konfiguracji: {exc}", flush=True)

        # Aktualizuj def_layout.json
        try:
            with open(self.app.base_dir / 'def_layout.json', 'w', encoding='utf-8') as f:
                json.dump(self.app.layout, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[CONFIG] Nie udało się zapisać def_layout.json: {exc}", flush=True)

        workers = None
        if self.app.worker_mode_var.get() == 'manual':
            try:
                workers = max(1, int(self.app.worker_count_var.get()))
            except Exception:
                pass

        self.app.render_stats.config(text="Rozpoczynanie renderowania...")
        self.app.render_progress.config(mode='determinate', value=0)
        self.app.render_cancel_event.clear()
        self.app.render_button.config(text='Anuluj', command=self.cancel_render)

        def run_render():
            try:
                t_export_start = time.time()
                print(f"Render start: input={self.app.video_paths_to_process}, output={output_file}")
                self.app.root.after(0, lambda: (
                    self.app._render_frame.pack(fill=tk.X, padx=8, pady=(0, 4)),
                    self.app.render_stats.config(text="Render w tle...")
                ))
                stats = self.render_pipeline(
                    input_file=self.app.video_paths_to_process,
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
                if not self.app.render_cancel_event.is_set() and stats:
                    self.app.root.after(0, lambda: show_statistics_dialog(self.app.root, stats, export_duration, output_file))
            except Exception as e:
                err_msg = str(e)
                print('Render thread exception:', err_msg)
                self.app.root.after(0, lambda msg=err_msg: messagebox.showerror('Błąd renderowania', msg))
            finally:
                self.app.root.after(0, self.on_render_finished)

        threading.Thread(target=run_render, daemon=True).start()

    def cancel_render(self):
        self.app.render_cancel_event.set()
        if isinstance(self.app._active_process, dict):
            process = self.app._active_process.get('process')
            if process is not None:
                try:
                    process.terminate()
                except Exception:
                    pass
        elif self.app._active_process is not None:
            try:
                self.app._active_process.terminate()
            except Exception:
                pass
        self.app.render_stats.config(text='Przerywanie renderowania...')
        self.app.render_button.config(state='disabled')

    def on_render_finished(self):
        self.app.render_button.config(text='Render teraz', command=self.render_now, state='normal')
        if self.app.render_cancel_event.is_set():
            self.app.render_stats.config(text='Anulowano')
        else:
            self.app.render_stats.config(text='Gotowy')
        self.app.render_progress.stop()
        self.app.render_progress.config(value=0, mode='determinate')
        self.app._render_frame.pack_forget()

    def generate_meta_json(self, video_paths=None, silent=False, callback=None):
        paths = video_paths or self.app.video_paths_to_process or ([self.app.video_path] if self.app.video_path else [])
        if not paths:
            return

        self.app.render_stats.config(text="Generowanie telemetrii...")
        self.app.render_progress.config(mode='indeterminate')
        self.app.render_progress.start()

        def worker():
            method_used = "ExifTool"
            try:
                if _GPMF_AVAILABLE:
                    try:
                        ffmpeg_exe = self.app.ffmpeg_exe or find_executable(
                            'ffmpeg', [str(self.app.base_dir / 'ffmpeg.exe'), 'ffmpeg.exe'])
                        ffprobe_exe = self.app.ffprobe_exe or find_executable(
                            str(self.app.ffprobe_path), [str(self.app.base_dir / 'ffprobe.exe'), 'ffprobe.exe'])

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
                        print(f"⚠ GPMF failed: {gpmf_err} — falling back to ExifTool", flush=True)

                if method_used == "ExifTool":
                    print("➡ USING EXIFTOOL", flush=True)
                    exiftool_exe = find_executable(
                        str(self.app.exiftool_path),
                        [str(self.app.base_dir / 'exiftool.exe'), 'exiftool.exe']
                    )
                    if not exiftool_exe:
                        raise RuntimeError("❌ Nie znaleziono exiftool")

                    self.app.exiftool_path = exiftool_exe
                    cmd = [exiftool_exe, "-ee", "-j", "-G3", str(paths[0])]
                    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                    if proc.returncode != 0:
                        raise RuntimeError(proc.stderr or "ExifTool error")

                    data = json.loads(proc.stdout)
                    if not data:
                        raise RuntimeError("❌ ExifTool zwrócił puste dane")

                flat = data[0]
                json_path = self.app.video_path.with_suffix(".json")

                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(flat, f, indent=2, ensure_ascii=False)

                print(f"✅ JSON zapisany: {json_path}  (method: {method_used})")
                self.app.records = [flat]

                def _meta_progress(stage: int, text: str) -> None:
                    self.app.root.after(0, lambda t=text: self.app.render_stats.config(text=t))

                self.app.update_telemetry_data(progress_callback=_meta_progress)

                def success():
                    self.app.render_progress.stop()
                    self.app.render_progress.config(mode='determinate', value=0)
                    self.app.render_stats.config(text="Gotowy")

                    self.app.meta_path = json_path
                    self.app.meta_info_var.set(f'Meta: {json_path.name}  ({method_used})')

                    self.app.build_property_editor_builtin()
                    try:
                        self.app._register_fit_fields()
                    except Exception as exc:
                        print(f"[FIT] Error registering FIT fields: {exc}", flush=True)
                    self.app.refresh()

                    if not silent:
                        messagebox.showinfo('OK', f'JSON wygenerowany ({method_used}):\n{json_path}')

                    if callback:
                        callback()

                self.app.root.after(0, success)

            except Exception as e:
                err_text = str(e)
                def error(err=err_text):
                    self.app.render_progress.stop()
                    self.app.render_progress.config(mode='determinate', value=0)
                    self.app.render_stats.config(text="Błąd")
                    messagebox.showerror('Błąd telemetrii', err)

                self.app.root.after(0, error)

        threading.Thread(target=worker, daemon=True).start()

    def render_pipeline(self, input_file, meta_path, layout_path, output_file,
                        encoder, prefer_3d, resolution, video_bitrate,
                        workers=None, tz_offset=2):
        from src.gui.hud_tuner_app import normalize_layout, ffprobe_stream_info, parse_fps

        ffmpeg_exe  = self.app.ffmpeg_exe or find_executable('ffmpeg',  [str(self.app.base_dir / 'ffmpeg.exe'), 'ffmpeg.exe'])
        ffprobe_exe = self.app.ffprobe_exe or find_executable(str(self.app.ffprobe_path), [str(self.app.base_dir / 'ffprobe.exe'), 'ffprobe.exe'])
        self.app.ffmpeg_exe = ffmpeg_exe
        self.app.ffprobe_exe = ffprobe_exe
        if not ffmpeg_exe:
            raise RuntimeError('Nie znaleziono ffmpeg.exe.')
        if not ffprobe_exe:
            raise RuntimeError('Nie znaleziono ffprobe.exe.')

        primary_input = input_file[0] if isinstance(input_file, list) else input_file
        info    = ffprobe_stream_info(ffprobe_exe, primary_input)
        streams = info.get('streams', [])
        fps          = parse_fps(streams[0].get('avg_frame_rate') or streams[0].get('r_frame_rate')) if streams else 30.0
        video_width  = int(streams[0].get('width',  1920)) if streams else 1920
        video_height = int(streams[0].get('height', 1080)) if streams else 1080

        duration_s = self.app.video_duration_s if isinstance(input_file, list) and input_file == self.app.video_paths_to_process and self.app.video_duration_s > 0 else 0.0
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

        rotation_degrees = get_rotation_from_metadata(records)
        container_rotation = get_container_rotation(ffprobe_exe, input_file)

        rotation_override = self.app.rotation_var.get() if hasattr(self.app, 'rotation_var') else 'auto'
        if rotation_override != 'auto':
            effective_rotation = int(rotation_override)
            container_rotation_arg = 0
        else:
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

        start_dt_utc = getattr(self.app, 'start_dt_utc', None)
        if start_dt_utc is None:
            anchor = find_gps_anchor(records)
            if anchor:
                start_dt_utc = anchor
            elif gpmf_speed:
                start_dt_utc = gpmf_speed[0][0]
            else:
                start_dt_utc = None

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
            if gpx_track:
                gpx_track_samples = gpx_track
            if gpx_alt:
                gpx_alt_samples = smooth_speed_samples(gpx_alt, "moving_average", SMOOTHING_WINDOW)
            if gpx_power:
                gpx_power_samples = gpx_power
            if gpx_atemp:
                gpx_atemp_samples = gpx_atemp
            if gpx_hr:
                gpx_hr_samples = gpx_hr
            if gpx_cad:
                gpx_cad_samples = gpx_cad
            if start_dt_utc is None and gpx_speed:
                start_dt_utc = gpx_speed[0][0]

        fit_data = dict(getattr(self.app, 'fit_data', {}) or {})
        tm = self.app.telemetry
        if tm and tm.fit_data:
            fit_data = dict(tm.fit_data)

        manual_fit = getattr(self.app, 'fit_path', None)
        if not fit_data:
            if not (manual_fit and Path(manual_fit).suffix.lower() == '.fit' and Path(manual_fit).is_file()):
                auto_fit = find_fit_for_video(primary_input)
                if auto_fit:
                    manual_fit = auto_fit
            if manual_fit and Path(manual_fit).suffix.lower() == '.fit' and Path(manual_fit).is_file():
                try:
                    fit_result = process_fit(manual_fit, start_dt_utc)
                except Exception as _e:
                    fit_result = None
                if fit_result:
                    fit_data = {}
                    for key, samples in fit_result.items():
                        if key in ('speed', 'alt'):
                            fit_data[key] = smooth_speed_samples(samples, "moving_average", SMOOTHING_WINDOW)
                        else:
                            fit_data[key] = samples
                    if start_dt_utc is None and fit_data.get('speed'):
                        start_dt_utc = fit_data['speed'][0][0]

        if fit_data:
            orig_fit_data = self.app.fit_data
            self.app.fit_data = fit_data
            self.app._register_fit_fields(layout)
            self.app.fit_data = orig_fit_data

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
        max_distance_m = gpmf_track[-1][1] if gpmf_track else 0

        update_rate_str = self.app.update_rate_var.get() if hasattr(self.app, 'update_rate_var') else 'Full'
        if update_rate_str == 'Half':
            update_rate_step = 2
        elif update_rate_str == 'Quarter':
            update_rate_step = 4
        else:
            update_rate_step = 1

        generation_fps = fps / update_rate_step
        total_overlay_frames = max(1, math.ceil(duration_s * generation_fps))

        def update_ui(val, stats):
            self.app.root.after(0, lambda: (
                self.app.render_progress.config(mode='determinate'),
                self.app.render_progress.config(value=val),
                self.app.render_stats.config(text=stats)
            ))

        self.app.render_progress['maximum'] = total_overlay_frames
        update_ui(0, "Renderowanie HUD (stream)...")
        self.app._active_process = {'process': None}
        t_render_start = time.time()

        # GPS track z per-source selection (zgodnie z preview w hud_tuner_app.refresh)
        if tm:
            map_src = layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
            gps_trk = tm.get_gps_track_for_source(map_src)
        else:
            gps_trk = getattr(self.app, 'gps_track', None) or []

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
            font_path=self.app.font_path,
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
            gps_track=gps_trk,
            progress_cb=update_ui,
            cancel_event=self.app.render_cancel_event,
            active_process_holder=self.app._active_process,
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

        if self.app.render_cancel_event.is_set():
            return

        return {
            'total_overlay_frames': total_overlay_frames,
            'final_frames': int(duration_s * fps),
            'png_duration': render_duration,
            'mov_duration': 0,
            'final_duration': 0,
        }


def sanitize_output_path(path_text):
    txt = str(path_text).strip()
    while txt.endswith('.'):
        txt = txt[:-1]
    return Path(txt)
