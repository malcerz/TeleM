"""Mixin for preview generation, compositing queue, scaling, and PIL to QImage conversion.
"""

from __future__ import annotations

import time
import queue
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QImage
from PIL import Image, ImageDraw

from src.overlay_renderer import (
    prepare_overlay_frame_data,
    build_chart_data,
    render_preview,
    compose_overlay,
)
from src.video_helpers import extract_frame
from src.benchmark import BenchmarkTracker

try:
    from PySide6.QtMultimedia import QMediaPlayer
    _QT_MULTIMEDIA_AVAILABLE = True
except ImportError:
    _QT_MULTIMEDIA_AVAILABLE = False


class PreviewMixin:
    def _start_compositing_worker(self) -> None:
        """Worker: odbiera PIL Image z kolejki i kompozytuje w tle."""
        def worker() -> None:
            while self._comp_worker_running:
                try:
                    task = self._comp_queue.get(timeout=0.2)
                    if task is None:
                        break
                    pil_img, seek_seconds = task
                    # Compositing w tle — nie blokuje GUI
                    self._render_preview_from_pil(pil_img, seek_seconds)
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"[CompWorker] {e}", flush=True)

        self._comp_thread = threading.Thread(target=worker, daemon=True)
        self._comp_thread.start()

    def _on_video_frame(self, frame) -> None:
        """Szybki handler — tylko zapisz klatkę, compositing w workerze."""
        if self._preview_mode == "gpu_video":
            return

        # ── KLUCZOWA OPTYMALIZACJA: wczesny return gdy worker jest zajęty ──
        # Nie wywołujemy frame.toImage() ani nie kopiujemy 33MB VRAM->RAM gdy kolejka jest pełna!
        if self._comp_queue.full():
            return

        # Frame-dropping podczas playbacku
        if self._playing:
            self._frame_counter += 1
            if self._frame_counter % self._composite_every_n != 0:
                return

        bt = BenchmarkTracker.get_instance()
        bt.start_timer("video_decode")
        try:
            qimg = frame.toImage()
            if qimg is None or qimg.isNull():
                return
            self.last_src_qimg = qimg

            # Seek pending → pauzuj po pierwszej klatce
            if self._seek_pending:
                self._seek_pending = False
                if not self._playing:
                    self.media_player.pause()

            # Skaluj i konwertuj QImage → PIL szybko w GUI wątku (~1-2ms)
            # Resztę robi worker.
            preview_qimg = self._scale_qimg_to_preview(qimg)
            pil_img = self._qimage_to_pil(preview_qimg)
            self.last_src_pil = pil_img
            current_ts = self.media_player.position() / 1000.0
            self.last_preview_ts = current_ts

            # Push do kolejki workera — compositing w tle
            try:
                self._comp_queue.get_nowait()
            except queue.Empty:
                pass
            self._comp_queue.put((pil_img, current_ts))
        finally:
            bt.stop_timer("video_decode")

    def _render_preview_from_pil(self, pil_img: Image.Image, seek_seconds: float) -> None:
        """Renderuje nakładki na PIL Image (wołane z wątku workera).

        Emituje gotowy QImage z powrotem do GUI (QueuedConnection).
        """
        self.src_img = pil_img
        self.last_src_pil = pil_img
        self.last_preview_ts = seek_seconds
        self._render_preview(seek_seconds)

    def _scale_qimg_to_preview(self, qimg: QImage) -> QImage:
        """Skaluje QImage do `_preview_target_w` (zachowując proporcje)."""
        src_w, src_h = qimg.width(), qimg.height()
        if src_w <= self._preview_target_w:
            return qimg  # już wystarczająco małe
        ratio = self._preview_target_w / src_w
        preview_h = max(1, int(src_h * ratio))
        return qimg.scaled(
            self._preview_target_w, preview_h,
            Qt.KeepAspectRatio,
            Qt.FastTransformation,
        )

    @staticmethod
    def _qimage_to_pil(qimg: QImage) -> Image.Image:
        """Konwertuje QImage → PIL Image (RGB). Handluje stride padding."""
        if qimg.format() != QImage.Format_RGB888:
            qimg = qimg.convertToFormat(QImage.Format_RGB888)
        w, h = qimg.width(), qimg.height()
        stride = qimg.bytesPerLine()
        raw = bytes(qimg.bits())
        if stride == w * 3:
            data = raw[: w * h * 3]
        else:
            rows = [raw[y * stride : y * stride + w * 3] for y in range(h)]
            data = b"".join(rows)
        return Image.frombuffer("RGB", (w, h), data, "raw", "RGB", 0, 1)

    def _build_prepare_cache(self) -> None:
        """Oblicza raz wartości zakresów (const dla całego wideo)."""
        spd = self.telemetry.speed_samples or []
        trk = self.telemetry.track_samples or []
        alt = self.telemetry.alt_samples or []
        gpx_spd = self.telemetry.gpx_speed_samples or []
        gpx_trk = self.telemetry.gpx_track_samples or []
        gpx_alt = self.telemetry.gpx_alt_samples or []
        fit_data = self.telemetry.fit_data or {}

        # Odczytać źródła z layoutu (tak samo jak prepare_overlay_frame_data)
        indic = self.layout.get("indicators", {})

        # max_distance_m — per source
        max_dist = None
        dist_ind = indic.get("dist_visual") or indic.get("dist_text") or indic.get("fit_distance_text") or {}
        dist_src = dist_ind.get("source", "fit" if "fit_distance_text" in indic else "gpmf")
        if dist_src == "gpx":
            trk_for_range = gpx_trk or trk
        elif dist_src == "fit":
            trk_for_range = fit_data.get("track", []) or trk
        else:
            trk_for_range = trk
        if trk_for_range:
            max_dist = trk_for_range[-1][1]

        # max_speed_kmh — per source
        max_spd = None
        spd_src = indic.get("speed_visual", {}).get("source", "gpmf")
        if spd_src == "gpx":
            spd_for_range = gpx_spd or spd
        elif spd_src == "fit":
            spd_for_range = fit_data.get("speed", []) or spd
        else:
            spd_for_range = spd
        if spd_for_range:
            vals = [s for _, s in spd_for_range]
            if vals:
                max_spd = max(vals)

        # min_alt / max_alt — per source
        min_a = max_a = None
        alt_src = indic.get("alt_visual", {}).get("source", "gpmf")
        if alt_src == "gpx":
            alt_for_range = gpx_alt_s = gpx_alt or alt
        elif alt_src == "fit":
            alt_for_range = fit_alt_s = fit_data.get("alt", []) or alt
        else:
            alt_for_range = alt
        if alt_for_range:
            alts = [a for _, a in alt_for_range]
            if alts:
                min_a = min(alts)
                max_a = max(alts)

        self._prepare_cache = {
            "max_distance_m": max_dist,
            "max_speed_kmh": max_spd,
            "min_alt": min_a,
            "max_alt": max_a,
        }

    def _render_preview(self, seek_seconds: float | None = None) -> None:
        """Renderuje podgląd nakładki i wysyła QImage do GUI."""
        bt = BenchmarkTracker.get_instance()
        bt.start_timer("preview_cycle")
        bt.count("preview_frames")
        try:
            if not self.video_path:
                return

            w = self.layout.get("width", 1280)
            h = self.layout.get("height", 720)
            target_h = int(self._preview_target_w * h / w) if w > 0 else 720

            if self.is_using_mpv():
                self.src_img = Image.new("RGBA", (self._preview_target_w, target_h), (0, 0, 0, 0))
                self.last_src_pil = self.src_img
                if seek_seconds is not None:
                    self.last_preview_ts = seek_seconds
            elif self._preview_mode == "gpu_video":
                self.src_img = Image.new("RGBA", (self._preview_target_w, target_h), (0, 0, 0, 0))
                self.last_src_pil = self.src_img
                if seek_seconds is not None:
                    self.last_preview_ts = seek_seconds
            else:
                if seek_seconds is not None:
                    last_ts = getattr(self, "last_preview_ts", -1.0)
                    if self.last_src_pil is None or abs(seek_seconds - last_ts) > 0.05:
                        # Prefer QMediaPlayer path — hardware-accelerated decode
                        # (d3d11va on AMD, NVDEC on NVIDIA, QSV on Intel).
                        # QMediaPlayer delivers frames asynchronously via
                        # _on_video_frame → _render_preview_from_pil, which will
                        # call _render_preview again with the decoded frame already
                        # in self.last_src_pil / self.src_img.
                        if _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
                            self._seek_pending = True
                            pos_ms = max(0, int(seek_seconds * 1000))
                            self.media_player.setPosition(pos_ms)
                            if not self._playing:
                                self.media_player.play()
                            self.last_preview_ts = seek_seconds
                            # Use the last available frame while waiting for the
                            # new one to arrive from QMediaPlayer.
                            if self.last_src_pil is not None:
                                self.src_img = self.last_src_pil
                            else:
                                # No frame yet — create placeholder
                                self.src_img = Image.new(
                                    "RGBA",
                                    (self._preview_target_w, target_h),
                                    (0, 0, 0, 0),
                                )
                                self.last_src_pil = self.src_img
                        else:
                            # Fallback: synchronous CPU decode via OpenCV / FFmpeg
                            from src.video_helpers import extract_frame
                            frame = extract_frame(
                                self.video_path, seek_seconds,
                                ffmpeg_exe=self.ffmpeg_exe or "ffmpeg",
                                ffprobe_exe=self.ffprobe_exe or "ffprobe",
                                target_w=self._preview_target_w,
                                preferred_encoder=self.ui.render_tab.cmb_encoder.currentText() if getattr(self, "ui", None) and getattr(self.ui, "render_tab", None) else ""
                            )
                            if frame:
                                self.src_img = frame.convert("RGBA")
                                self.last_src_pil = self.src_img
                                self.last_preview_ts = seek_seconds
                elif self.last_src_pil is not None:
                    self.src_img = self.last_src_pil

            try:
                src_w, src_h = self.src_img.size
                if src_w < 10 or src_h < 10:
                    return

                date_txt, time_txt = "----.--.--", "--:--:--"
                overlay_data = None
                target_dt = None

                if self.telemetry.start_dt_utc:
                    current_ts = seek_seconds if seek_seconds is not None else 0
                    target_dt = self.telemetry.start_dt_utc + timedelta(seconds=current_ts)
                    if target_dt.tzinfo is None:
                        target_dt = target_dt.replace(tzinfo=timezone.utc)

                    if self._chart_data_cache is None:
                        duration_s = getattr(self.telemetry, "video_duration", None) or getattr(self, "total_duration_seconds", None)
                        end_dt_utc = (self.telemetry.start_dt_utc + timedelta(seconds=duration_s)) if (self.telemetry.start_dt_utc and duration_s) else None
                        source_ranges = {}
                        if self.telemetry.fit_data:
                            all_fit_pts = [s for s in self.telemetry.fit_data.values() if s]
                            if all_fit_pts:
                                source_ranges["fit"] = (
                                    min(s[0][0] for s in all_fit_pts),
                                    max(s[-1][0] for s in all_fit_pts),
                                )
                        self._chart_data_cache = build_chart_data(
                            self.layout,
                            self.telemetry.get_samples_for_source,
                            lambda field, src, key=None: self.telemetry.resolve_samples(
                                field, src, indicator_key=key
                            ),
                            start_dt_utc=self.telemetry.start_dt_utc,
                            end_dt_utc=end_dt_utc,
                            source_activity_ranges=source_ranges,
                        )
                    chart_data = self._chart_data_cache

                    # ── Oblicz raz wartości stałe (niezależne od klatki) ──
                    if not self._prepare_cache:
                        self._build_prepare_cache()

                    try:
                        bt.start_timer("telemetry_lookup")
                        try:
                            overlay_data = prepare_overlay_frame_data(
                                layout=self.layout,
                                target_dt=target_dt,
                                tz_offset_hours=2,
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
                                resolve_cache_value=lambda k, src, dt, indicator_key=None: self.telemetry.resolve_value(
                                    k, dt, source=src, indicator_key=indicator_key
                                ),
                                _range_cache=self._prepare_cache,
                            )
                        finally:
                            bt.stop_timer("telemetry_lookup")

                        if overlay_data:
                            date_txt = overlay_data["date_text"]
                            time_txt = overlay_data["time_text"]
                    except Exception as e:
                        import traceback
                        traceback.print_exc()

                # Pozycja dla kursora na wykresach
                current_position = (
                    seek_seconds / max(1.0, self.video_duration_s)
                    if seek_seconds is not None and self.video_duration_s > 0
                    else 0.0
                )

                # Sprawdź czy klatka jest w wyciętym fragmencie
                current_ts = seek_seconds if seek_seconds is not None else 0
                if self.is_in_cut_region(current_ts):
                    preview = self.src_img.convert("RGBA").copy()
                    from PIL import ImageDraw
                    draw = ImageDraw.Draw(preview)
                    bar_h = max(4, int(preview.height * 0.02))
                    draw.rectangle(
                        [(0, preview.height - bar_h), (preview.width, preview.height)],
                        fill=(200, 50, 50, 160),
                    )
                    draw.text(
                        (preview.width // 2 - 60, preview.height - bar_h - 16),
                        "-= WYCIĘTY FRAGMENT =-",
                        fill=(200, 50, 50, 220),
                    )
                    self.indicator_bboxes.clear()
                    overlay_data = None
                else:
                    self.indicator_bboxes.clear()

                bt.start_timer("overlay_rendering")
                try:
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
                            map_heading=overlay_data.get("map_heading"),
                            target_dt=overlay_data["target_dt"],
                            start_dt_utc=overlay_data["start_dt_utc"],
                            elapsed_seconds=overlay_data["elapsed_seconds"],
                            avg_speed_kmh=overlay_data["avg_speed_kmh"],
                            inplace=self._playing,
                        )
                    else:
                        # Check if preview already set (cut region or no telemetry)
                        try:
                            _ = preview
                        except NameError:
                            preview = None
                        if preview is None:
                            # No telemetry – show blank overlay
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
                finally:
                    bt.stop_timer("overlay_rendering")

                bt.start_timer("frame_conversion")
                try:
                    # Konwertuj PIL Image → QImage (thread-safe, GUI wątek zrobi QPixmap)
                    if self.is_using_mpv():
                        img_rgba = preview.convert("RGBA")
                        data = img_rgba.tobytes("raw", "RGBA")
                        qimg = QImage(
                            data, img_rgba.width, img_rgba.height,
                            img_rgba.width * 4, QImage.Format_RGBA8888,
                        )
                        qimg.nd = data
                    else:
                        data = preview.tobytes("raw", "RGBA")
                        qimg = QImage(
                            data, preview.width, preview.height,
                            preview.width * 4, QImage.Format_RGBA8888,
                        )
                        qimg.nd = data
                finally:
                    bt.stop_timer("frame_conversion")

                self.signals.sig_preview_frame_ready.emit(qimg)
                self.signals.sig_bboxes_ready.emit(
                    dict(self.indicator_bboxes),
                    self.src_img.width, self.src_img.height,
                )

            except Exception as e:
                import traceback
                traceback.print_exc()
        finally:
            bt.stop_timer("preview_cycle")
            # Periodically print summary during playback
            if self._playing and bt.counters["preview_frames"] % 150 == 0:
                bt.print_summary()
