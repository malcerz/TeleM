"""Mixin for final video render requesting and execution pipelines.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from src.ffmpeg import detect_best_encoder, stream_overlay_to_ffmpeg
from src.ffmpeg.detection import _test_encoder
from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_speed_samples,
    extract_track_samples,
    get_container_rotation,
    get_rotation_from_metadata,
    load_json_with_fallback,
    smooth_speed_samples,
)
from src.video_helpers import (
    ffprobe_stream_info,
    find_executable,
    parse_fps,
    sanitize_output_path,
)


class RenderMixin:
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
                else:
                    self.signals.sig_render_stopped.emit()
            except Exception as e:
                if not self.render_cancel_event.is_set():
                    self.signals.sig_error.emit(f"Render error: {e}")
                else:
                    self.signals.sig_render_stopped.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _render_pipeline(self, options: dict) -> dict:
        """Wykonuje pipeline renderowania (istniejąca logika)."""
        encoder = options.get("encoder", detect_best_encoder())
        # Validate that the requested hardware encoder actually works on this GPU
        if encoder == "nv" and not _test_encoder("hevc_nvenc"):
            encoder = detect_best_encoder()
        elif encoder == "amd" and not (_test_encoder("hevc_amf") or _test_encoder("h264_amf")):
            encoder = detect_best_encoder()
        elif encoder == "intel" and not _test_encoder("hevc_qsv"):
            encoder = detect_best_encoder()

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
        src_w = int(streams[0].get("width", 1920)) if streams else 1920
        src_h = int(streams[0].get("height", 1080)) if streams else 1080

        from src.ffmpeg.command_builder import RESOLUTION_MAP
        target_res = RESOLUTION_MAP.get(resolution)
        if target_res is not None:
            render_w, render_h = target_res
        else:
            render_w, render_h = src_w, src_h

        layout = dict(self.layout, cut_regions=list(self._cut_regions))
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

        SMOOTHING_WINDOW = 5
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
            "iso_samples": self.telemetry.iso_samples,
            "exposure_samples": self.telemetry.exposure_samples,
            "temperature_samples": self.telemetry.temperature_samples,
            "accel_x_samples": self.telemetry.accel_x_samples,
            "accel_y_samples": self.telemetry.accel_y_samples,
            "accel_z_samples": self.telemetry.accel_z_samples,
            "accel_magnitude_samples": self.telemetry.accel_magnitude_samples,
            "gyro_x_samples": self.telemetry.gyro_x_samples,
            "gyro_y_samples": self.telemetry.gyro_y_samples,
            "gyro_z_samples": self.telemetry.gyro_z_samples,
            "gyro_magnitude_samples": self.telemetry.gyro_magnitude_samples,
        }

        # Smart Canvas Scaling: limit CPU overlay canvas to 1920 width if target is higher (e.g. 4K)
        # FFmpeg will automatically scale the overlay to render_w/render_h
        max_overlay_w = 1920
        if render_w > max_overlay_w:
            ov_w = max_overlay_w
            ov_h = int(max_overlay_w * render_h / render_w) if render_w > 0 else 1080
        else:
            ov_w = render_w
            ov_h = render_h

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
            # NVIDIA production is intentionally frozen at the validated
            # four-worker configuration.  GUI preset values must not
            # accidentally select a slower unbenchmarked worker count.
            workers=4 if encoder == "nv" else self.render_threads,
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
            on_render_progress=lambda c, t, e, f, h: self.signals.sig_render_progress.emit(c, t, e, f, h),
            cancel_event=self.render_cancel_event,
            encoder=encoder,
            gpu=0,
            resolution_name=resolution,
            video_bitrate=video_bitrate,
            rotation_degrees=effective_rotation,
            container_rotation=container_rotation_arg,
            overlay_w=ov_w,
            overlay_h=ov_h,
            render_w=render_w,
            render_h=render_h,
        )

        return {"total_overlay_frames": 0, "png_duration": 0}

    def _on_render_cancelled(self) -> None:
        self.render_cancel_event.set()
