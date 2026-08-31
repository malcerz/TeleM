"""Mixin for preview generation, compositing queue, scaling, and PIL to QImage conversion.
"""

from __future__ import annotations

import os
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
    # ── Multi-file preview time resolution (ETAP 4A) ─────────────────────
    # Three distinct times exist at any moment and must never be conflated:
    #   GLOBAL  — position on the compressed project axis (seek bar),
    #   LOCAL   — position inside the currently loaded MP4 (decoder),
    #   ABSOLUTE— real telemetry timestamp (FIT/GPMF/GPX).
    #   global_time -> active clip -> local_time (decoder) -> absolute (telemetry)

    def _resolve_preview_time(self, global_time: float) -> dict:
        """Resolve a GLOBAL preview time to clip / local / absolute.

        Returns a dict with keys:
            global_time (float), clip_index (int|None), clip (VideoClip|None),
            local_time (float), absolute_dt (datetime|None).
        When no timeline exists (legacy single-file) it reduces to
        ``local == global`` and ``absolute == start_dt_utc + global``.
        """
        g = float(global_time if global_time is not None else 0.0)
        timeline = getattr(self, "video_timeline", None)
        if timeline is not None and timeline.clip_count:
            idx, local = timeline.global_to_clip(g)
            clip = timeline.clips[idx] if idx is not None else None
            abs_dt = timeline.global_to_absolute(
                g, base_dt=self.telemetry.start_dt_utc
            )
            return {
                "global_time": g,
                "clip_index": idx,
                "clip": clip,
                "local_time": local,
                "absolute_dt": abs_dt,
            }
        # Legacy single-file fallback.
        abs_dt = None
        if getattr(self.telemetry, "start_dt_utc", None):
            abs_dt = self.telemetry.start_dt_utc + timedelta(seconds=g)
            if abs_dt.tzinfo is None:
                abs_dt = abs_dt.replace(tzinfo=timezone.utc)
        return {
            "global_time": g,
            "clip_index": 0,
            "clip": None,
            "local_time": g,
            "absolute_dt": abs_dt,
        }

    def _local_to_global(self, local_time: float) -> float:
        """Convert the player's LOCAL position to GLOBAL project time.

        Uses the active preview clip's ``global_start_s``.  Falls back to the
        identity mapping (single file) when no timeline / clip is known.
        """
        idx = getattr(self, "_active_preview_clip_index", None)
        timeline = getattr(self, "video_timeline", None)
        if timeline is not None and timeline.clip_count and idx is not None:
            if 0 <= idx < timeline.clip_count:
                return timeline.clips[idx].global_start_s + float(local_time)
        return float(local_time)

    def _log_preview_clip_switch(
        self, idx: int, global_time: float, local_time: float,
        absolute_dt, clip,
    ) -> None:
        """Diagnostic logged once per clip switch (not per frame)."""
        total = getattr(self.video_timeline, "clip_count", 0)
        abs_txt = (
            absolute_dt.isoformat(timespec="milliseconds")
            if absolute_dt is not None else "N/A"
        )
        source = getattr(clip, "timestamp_source", "?")
        quality = getattr(clip, "timestamp_quality", "?")
        print(
            f"[MultiFile Preview] Switch clip {idx + 1}/{total} "
            f"global={global_time:.3f} local={local_time:.3f} "
            f"absolute={abs_txt} source={source} quality={quality}",
            flush=True,
        )

    def _preview_ensure_active_clip(
        self, clip_index, clip, local_time: float, global_time: float = 0.0
    ) -> bool:
        """Switch the preview decoder source only when the clip changed.

        Returns True when a source switch happened (and, for QMediaPlayer, a
        seek is deferred to ``_on_media_status_changed``).
        """
        active = getattr(self, "_active_preview_clip_index", None)
        if clip_index is None or clip is None:
            return False
        if active == clip_index:
            return False
        self._log_preview_clip_switch(
            clip_index,
            global_time,
            local_time,
            getattr(clip, "absolute_start_dt", None),
            clip,
        )
        # Unify generation tracking & transition state for both MPV and QMedia
        self._source_generation = getattr(self, "_source_generation", 0) + 1
        self._source_transition_in_progress = True
        self._expected_source_path = str(clip.path)

        if self.is_using_mpv():
            try:
                self._mpv_pending_seek_s = float(local_time)
                self.mpv_player.play(str(clip.path))
                # Set pause state matching current playback mode
                if not self._playing:
                    self.mpv_player.pause = True
                else:
                    self.mpv_player.pause = False
            except Exception as exc:
                print(f"[MultiFile Preview] MPV source switch failed: {exc}", flush=True)
                self._source_transition_in_progress = False
        elif _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
            try:
                # QMediaPlayer loads asynchronously — record the target seek
                # and apply it in _on_media_status_changed after loading.
                self._pending_seek_ms = int(max(0.0, float(local_time) * 1000.0))
                self.media_player.setSource(
                    QUrl.fromLocalFile(str(clip.path))
                )
            except Exception as exc:
                print(f"[MultiFile Preview] QMedia source switch failed: {exc}", flush=True)
                self._source_transition_in_progress = False
        self._active_preview_clip_index = clip_index
        return True


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

        # FIX D (early): discard all frames while a source switch is in flight.
        # The old HEVC demuxer can keep delivering decoded frames after
        # setSource() is called; accepting them would feed stale position()
        # values into _local_to_global and produce garbage global timestamps
        # (root cause of the 84:59 display regression).
        if getattr(self, "_source_transition_in_progress", False):
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
            # QMediaPlayer reports the LOCAL position of the active clip;
            # map it back to the GLOBAL project axis (ETAP 4A).
            local_ts = self.media_player.position() / 1000.0

            # FIX D: secondary guards against stale position() values that
            # slip through after the transition flag is cleared:
            # (a) Bilateral clip-duration check: local_ts must not exceed the
            #     canonical clip duration by more than 1 s.  The old decoder
            #     can briefly report its last-known position which may equal
            #     the GLOBAL start of the new clip (e.g. 2549 s for clip 2),
            #     yielding a bogus global_ts = 2*global_start ≈ 5098 s = 84:58.
            # (b) Source path identity: the player source must match the clip
            #     we expect to be decoding.
            _idx_d = getattr(self, "_active_preview_clip_index", None)
            _tl_d = getattr(self, "video_timeline", None)
            if _tl_d is not None and _idx_d is not None and 0 <= _idx_d < _tl_d.clip_count:
                _clip_d = _tl_d.clips[_idx_d]
                if local_ts > _clip_d.duration_s + 1.0:
                    import os as _os_d
                    if _os_d.environ.get("TELEM_MULTIFILE_DEBUG", "0") == "1":
                        print(
                            f"[MFPreview] frame DISCARD stale pos "
                            f"local_ts={local_ts:.3f}s "
                            f"clip_dur={_clip_d.duration_s:.3f}s idx={_idx_d}",
                            flush=True,
                        )
                    return
                _exp_path = getattr(self, "_expected_source_path", None)
                if _exp_path is not None:
                    try:
                        import os as _os_d2
                        _act = self.media_player.source().toLocalFile()
                        if _act and (
                            _os_d2.path.normcase(_os_d2.path.abspath(_act))
                            != _os_d2.path.normcase(_os_d2.path.abspath(_exp_path))
                        ):
                            return  # frame from wrong source
                    except Exception:
                        pass

            global_ts = self._local_to_global(local_ts)
            self.last_preview_ts = global_ts

            # Push do kolejki workera — compositing w tle
            try:
                self._comp_queue.get_nowait()
            except queue.Empty:
                pass
            self._comp_queue.put((pil_img, global_ts))
        finally:
            bt.stop_timer("video_decode")

    def _on_media_status_changed(self, status: Any) -> None:  # noqa: C901
        """Handle QMediaPlayer status changes for multi-file source switching.

        On ``LoadedMedia``/``BufferedMedia``: apply the pending seek that was
        recorded before ``setSource()`` was called and clear the transition
        flag (FIX B).

        On ``EndOfMedia``: apply a five-condition compound guard (FIX C) before
        advancing to the next clip:

        1. No source transition is in progress (``_source_transition_in_progress``
           is False) — setSource() was called very recently; the event is stale.
        2. EOF has not already been consumed for the current
           ``_source_generation`` (idempotency guard).
        3. ``_active_preview_clip_index`` is the expected clip index (sanity).
        4. ``media_player.source()`` matches ``_expected_source_path`` (identity
           guard — frame from wrong source cannot trigger clip advance).
        5. ``media_player.position()`` lies within ±1000 ms of the canonical
           clip duration from VideoTimeline (bilateral window guard — rejects
           both too-early spurious EOFs and stale old-decoder positions that
           happen to be >= clip_dur because the old clip was longer).

        Only when ALL five conditions are met is the EOF consumed and
        ``_on_media_end()`` deferred via ``QTimer.singleShot``.
        """
        try:
            import os as _os_c
            from PySide6.QtMultimedia import QMediaPlayer as _QMP
            _dbg = _os_c.environ.get("TELEM_MULTIFILE_DEBUG", "0") == "1"

            if status in (_QMP.MediaStatus.LoadedMedia, _QMP.MediaStatus.BufferedMedia):
                # FIX B: new source confirmed loaded — clear transition flag so
                # frames and subsequent EndOfMedia events are processed normally.
                self._source_transition_in_progress = False
                pending = getattr(self, "_pending_seek_ms", None)
                if pending is not None:
                    self.media_player.setPosition(int(pending))
                    self._pending_seek_ms = None
                    # After setSource(), QMediaPlayer is in Stopped state.
                    # Resume play() if the project is in playback mode.
                    if self._playing:
                        self.media_player.play()

            elif status == _QMP.MediaStatus.EndOfMedia:
                # ── FIX C: Compound guard — all five conditions required ───
                cur_gen = getattr(self, "_source_generation", 0)
                cur_idx = getattr(self, "_active_preview_clip_index", None)
                timeline = getattr(self, "video_timeline", None)

                def _reject(reason: str) -> None:
                    if _dbg:
                        print(
                            f"[MFPreview] EOF REJECTED ({reason}) "
                            f"gen={cur_gen} idx={cur_idx}",
                            flush=True,
                        )

                # Guard 1: transition in progress
                if getattr(self, "_source_transition_in_progress", False):
                    _reject("transition_in_progress")
                    return

                # Guard 2: already consumed for this generation (idempotency)
                if getattr(self, "_eof_consumed_for_generation", -1) == cur_gen:
                    _reject("already_consumed")
                    return

                # Guards 3–5 require a known clip from the timeline
                if timeline is not None and cur_idx is not None and 0 <= cur_idx < timeline.clip_count:
                    clip = timeline.clips[cur_idx]

                    # Guard 4: source path identity
                    exp_path = getattr(self, "_expected_source_path", None)
                    if exp_path is not None:
                        try:
                            act_path = self.media_player.source().toLocalFile()
                            if act_path and (
                                _os_c.path.normcase(_os_c.path.abspath(act_path))
                                != _os_c.path.normcase(_os_c.path.abspath(exp_path))
                            ):
                                _reject(f"source_mismatch act={act_path}")
                                return
                        except Exception:
                            pass

                    # Guard 5: bilateral ±1000 ms window around canonical duration
                    # Uses VideoTimeline duration (frame-count based), NOT
                    # player.duration() (container-based, may differ by >1 s).
                    canonical_dur_ms = int(clip.duration_s * 1000)
                    player_pos_ms = self.media_player.position()
                    epsilon_ms = 1000
                    if abs(player_pos_ms - canonical_dur_ms) > epsilon_ms:
                        _reject(
                            f"position_outside_window "
                            f"pos={player_pos_ms}ms "
                            f"canonical={canonical_dur_ms}ms "
                            f"window=±{epsilon_ms}ms"
                        )
                        return

                # All guards passed — consume this generation's EOF
                self._eof_consumed_for_generation = cur_gen
                if _dbg:
                    print(
                        f"[MFPreview] EOF ACCEPTED gen={cur_gen} idx={cur_idx}",
                        flush=True,
                    )
                QTimer.singleShot(0, self._on_media_end)

        except Exception as exc:
            print(f"[MultiFile Preview] mediaStatusChanged: {exc}", flush=True)

    def _render_preview_from_pil(self, pil_img: Image.Image, seek_seconds: float) -> None:
        """Renderuje nakładki na PIL Image (wołane z wątku workera).

        Emituje gotowy QImage z powrotem do GUI (QueuedConnection).
        """
        self.src_img = pil_img
        self.last_src_pil = pil_img
        self.last_preview_ts = seek_seconds
        self._render_preview(seek_seconds)

    def set_preview_widget(self, widget: object) -> None:
        """Zapamiętuje instancję widgetu VideoPreview."""
        self.video_preview_widget = widget

    def refresh_preview_geometry_and_hud(self, force: bool = False) -> None:
        """Synchronizuje fizyczny rozmiar podglądu z VideoPreview i wykonuje natychmiastowy render."""
        preview_widget = getattr(self, "video_preview_widget", None)
        if preview_widget is not None and hasattr(preview_widget, "get_physical_video_rect"):
            if (hasattr(preview_widget, "is_geometry_ready") and preview_widget.is_geometry_ready()) or force:
                prect = preview_widget.get_physical_video_rect()
                dpr = preview_widget.get_dpr()
                if prect.width() > 10 and prect.height() > 10:
                    self.set_preview_target_size(prect.width(), prect.height(), dpr=dpr)
                    return
        if getattr(self, "video_path", None) and getattr(self, "_preview_target_w", None) and getattr(self, "_preview_target_h", None):
            self._render_preview()

    def set_preview_target_size(self, w: int, h: int, dpr: float = 1.0) -> None:
        """Ustawia docelowy fizyczny rozmiar podglądu 1:1 z geometrią obszaru wideo (DPI-aware)."""
        w = max(10, int(w))
        h = max(10, int(h))
        cur_w = getattr(self, "_preview_target_w", None)
        cur_h = getattr(self, "_preview_target_h", None)
        cur_dpr = getattr(self, "_preview_dpr", 1.0)
        size_changed = (cur_w != w or cur_h != h or abs(cur_dpr - dpr) > 1e-4)
        if size_changed:
            old_target = f"{cur_w}x{cur_h}@{cur_dpr:.2f}" if cur_w else "None"
            self._preview_target_w = w
            self._preview_target_h = h
            self._preview_dpr = dpr
            new_target = f"{w}x{h}@{dpr:.2f}"
            # Invalidate cached render buffers/charts when preview size changes
            self._chart_data_cache = None
            if os.environ.get("TELEM_PREVIEW_DEBUG") or os.environ.get("TELEM_RENDER_DEBUG"):
                print(f"[PreviewInit] event=geometry_changed old_target={old_target} new_target={new_target} rerender={not getattr(self, '_playing', False) and bool(getattr(self, 'video_path', None))}", flush=True)
            if not getattr(self, "_playing", False) and getattr(self, "video_path", None):
                self._render_preview()



    def _scale_qimg_to_preview(self, qimg: QImage) -> QImage:
        """Skaluje QImage do `_preview_target_w` (zachowując proporcje)."""
        src_w, src_h = qimg.width(), qimg.height()
        target_w = getattr(self, "_preview_target_w", 960)
        target_h = getattr(self, "_preview_target_h", None)
        if target_h is None or target_h <= 0:
            target_h = max(1, int(src_h * target_w / src_w))
        if src_w == target_w and src_h == target_h:
            return qimg  # już wystarczająco małe
        return qimg.scaled(
            target_w, target_h,
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
        spd_ind = indic.get("speed_visual") or indic.get("speed_text") or indic.get("fit_speed_text") or indic.get("fit_enhanced_speed_text") or {}
        spd_src = spd_ind.get("source", "fit" if ("fit_speed_text" in indic or "fit_enhanced_speed_text" in indic) else "gpmf")
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
        alt_ind = indic.get("alt_visual") or indic.get("alt_text") or indic.get("fit_altitude_text") or indic.get("fit_enhanced_altitude_text") or {}
        alt_src = alt_ind.get("source", "fit" if ("fit_altitude_text" in indic or "fit_enhanced_altitude_text" in indic) else "gpmf")
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
        # Async map: expose the prepared MapContext to the map renderers so
        # they show the overview/placeholder instead of blocking on tiles.
        try:
            from src.indicators.map_prepare import set_current_map_context
            set_current_map_context(getattr(self, "map_context", None))
        except Exception:
            pass
        bt = BenchmarkTracker.get_instance()
        bt.start_timer("preview_cycle")
        bt.count("preview_frames")
        try:
            if not self.video_path:
                return

            # ── ETAP 4A: resolve GLOBAL preview time → clip/local/absolute ──
            # GLOBAL -> active clip -> LOCAL time (decoder) -> ABSOLUTE (telemetry).
            res = self._resolve_preview_time(
                seek_seconds if seek_seconds is not None
                else getattr(self, "last_preview_ts", 0.0)
            )
            global_time = res["global_time"]
            local_time = res["local_time"]
            clip_index = res["clip_index"]
            clip = res["clip"]
            target_dt = res["absolute_dt"]

            target_w = getattr(self, "_preview_target_w", 960)
            target_h = getattr(self, "_preview_target_h", None)
            if target_h is None or target_h <= 0:
                vw = getattr(self, "video_width", 0) or (self.video_info.get("width", 0) if isinstance(getattr(self, "video_info", None), dict) else 0) or self.layout.get("width", 16) or 16
                vh = getattr(self, "video_height", 0) or (self.video_info.get("height", 0) if isinstance(getattr(self, "video_info", None), dict) else 0) or self.layout.get("height", 9) or 9
                target_h = max(1, int(round(target_w * vh / vw))) if vw > 0 else 540

            if self.is_using_mpv():
                self.src_img = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                self.last_src_pil = self.src_img
                if seek_seconds is not None:
                    self.last_preview_ts = global_time
            elif self._preview_mode == "gpu_video":
                self.src_img = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                self.last_src_pil = self.src_img
                if seek_seconds is not None:
                    self.last_preview_ts = global_time
            else:
                if seek_seconds is not None:
                    last_ts = getattr(self, "last_preview_ts", -1.0)
                    if self.last_src_pil is None or abs(global_time - last_ts) > 0.05:
                        # Prefer QMediaPlayer path — hardware-accelerated decode
                        # (d3d11va on AMD, NVDEC on NVIDIA, QSV on Intel).
                        # QMediaPlayer delivers frames asynchronously via
                        # _on_video_frame → _render_preview_from_pil, which will
                        # call _render_preview again with the decoded frame already
                        # in self.last_src_pil / self.src_img.
                        if _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
                            # Switch source only when the clip changed; seek the
                            # decoder to the clip's LOCAL time.
                            switched = self._preview_ensure_active_clip(
                                clip_index, clip, local_time, global_time
                            )
                            self._seek_pending = True
                            if not switched:
                                self.media_player.setPosition(
                                    max(0, int(local_time * 1000))
                                )
                            if not self._playing:
                                self.media_player.play()
                            self.last_preview_ts = global_time
                            # Use the last available frame while waiting for the
                            # new one to arrive from QMediaPlayer.
                            if self.last_src_pil is not None:
                                self.src_img = self.last_src_pil
                            else:
                                # No frame yet — create placeholder
                                self.src_img = Image.new(
                                    "RGBA",
                                    (target_w, target_h),
                                    (0, 0, 0, 0),
                                )
                                self.last_src_pil = self.src_img
                        else:
                            # Fallback: synchronous CPU decode via OpenCV / FFmpeg.
                            # extract_frame is multi-clip aware — it maps GLOBAL
                            # time internally to the right clip / local offset.
                            from src.video_helpers import extract_frame
                            frame = extract_frame(
                                self.video_paths or [self.video_path], global_time,
                                ffmpeg_exe=self.ffmpeg_exe or "ffmpeg",
                                ffprobe_exe=self.ffprobe_exe or "ffprobe",
                                target_w=target_w,
                                preferred_encoder=self.ui.render_tab.cmb_encoder.currentText() if getattr(self, "ui", None) and getattr(self.ui, "render_tab", None) else ""
                            )
                            if frame:
                                if frame.size != (target_w, target_h):
                                    frame = frame.resize((target_w, target_h), Image.LANCZOS)
                                self.src_img = frame.convert("RGBA")
                                self.last_src_pil = self.src_img
                                self.last_preview_ts = global_time
                elif self.last_src_pil is not None:
                    self.src_img = self.last_src_pil


            try:
                src_w, src_h = self.src_img.size
                if src_w < 10 or src_h < 10:
                    return

                date_txt, time_txt = "----.--.--", "--:--:--"
                overlay_data = None

                if target_dt is None and self.telemetry.start_dt_utc:
                    # Legacy fallback (no timeline / no clip absolute start):
                    # start_dt_utc + global time.
                    target_dt = self.telemetry.start_dt_utc + timedelta(seconds=global_time)
                    if target_dt.tzinfo is None:
                        target_dt = target_dt.replace(tzinfo=timezone.utc)

                if target_dt is not None:
                    if self._chart_data_cache is None:
                        # ETAP 4B: with a multi-file timeline use the real
                        # absolute end (max clip absolute_end) for the chart
                        # range instead of start_dt_utc + project_duration.
                        end_dt_utc = None
                        _tl = getattr(self, "video_timeline", None)
                        if _tl is not None and _tl.clip_count:
                            from src.multifile import timeline_absolute_end
                            end_dt_utc = timeline_absolute_end(_tl)
                        if end_dt_utc is None:
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
                                current_index=int(global_time) if global_time else 0,
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

                # Pozycja dla kursora na wykresach (GLOBAL axis)
                current_position = (
                    global_time / max(1.0, self.video_duration_s)
                    if self.video_duration_s > 0
                    else 0.0
                )

                # Sprawdź czy klatka jest w wyciętym fragmencie (GLOBAL axis)
                if self.is_in_cut_region(global_time):
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
                            async_map=True,
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
                                async_map=True,
                            )
                            preview = self.src_img.convert("RGBA").copy()
                            preview.alpha_composite(overlay)
                        self.indicator_bboxes.clear()
                finally:
                    bt.stop_timer("overlay_rendering")

                bt.start_timer("frame_conversion")
                try:
                    dpr = getattr(self, "_preview_dpr", 1.0)
                    # Konwertuj PIL Image → QImage (thread-safe, GUI wątek zrobi QPixmap)
                    if self.is_using_mpv():
                        img_rgba = preview.convert("RGBA")
                        data = img_rgba.tobytes("raw", "RGBA")
                        qimg = QImage(
                            data, img_rgba.width, img_rgba.height,
                            img_rgba.width * 4, QImage.Format_RGBA8888,
                        )
                        if dpr > 0:
                            qimg.setDevicePixelRatio(dpr)
                        qimg.nd = data
                    else:
                        data = preview.tobytes("raw", "RGBA")
                        qimg = QImage(
                            data, preview.width, preview.height,
                            preview.width * 4, QImage.Format_RGBA8888,
                        )
                        if dpr > 0:
                            qimg.setDevicePixelRatio(dpr)
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
