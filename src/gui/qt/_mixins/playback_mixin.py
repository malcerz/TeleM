"""Mixin for MPV & QMediaPlayer playback setup, play/pause controls, seek, and tickers.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, QUrl, Qt

from src.gui.qt.mpv_hwdec import (
    build_mpv_options,
    detect_preview_vendor,
    get_hwdec_diagnostics,
)
from src.gui.qt.mpv_hwdec import vendor_label as _vendor_label

_MPV_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
if _MPV_BASE_DIR.exists():
    os.environ["PATH"] = str(_MPV_BASE_DIR) + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(_MPV_BASE_DIR))
        except Exception:
            pass

try:
    import mpv
    _MPV_AVAILABLE = True
except Exception:
    _MPV_AVAILABLE = False

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
    _QT_MULTIMEDIA_AVAILABLE = True
except ImportError:
    _QT_MULTIMEDIA_AVAILABLE = False


class PlaybackMixin:
    def is_using_mpv(self) -> bool:
        return self.mpv_player is not None

    def set_video_widget(self, widget: object, mpv_widget: object = None) -> None:
        """Ustawia widget QVideoWidget do natywnego odtwarzania sprzętowego."""
        self.video_widget = widget
        self.mpv_widget = mpv_widget or widget
        if _MPV_AVAILABLE and self.mpv_widget is not None:
            try:
                if getattr(self, "mpv_player", None):
                    try:
                        self.mpv_player.terminate()
                    except Exception:
                        pass

                # Resolve 'auto' to actual vendor for initialisation
                vendor = self.mpv_preview_vendor
                if vendor == "auto":
                    vendor = detect_preview_vendor()
                    self.mpv_preview_vendor = vendor  # remember resolved

                opts = build_mpv_options(vendor)
                self.mpv_player = mpv.MPV(
                    wid=str(int(self.mpv_widget.winId())),
                    **opts,
                )
                label = _vendor_label(vendor)
                print(f"[Controller] MPV zinicjalizowany pomyślnie (GPU: {label}, "
                      f"hwdec={opts.get('hwdec','auto')})")
            except Exception as e:
                print(f"[Controller] Nie udało się zainicjalizować MPV: {e}. Używam QMediaPlayer.")
                self.mpv_player = None

        if not self.is_using_mpv():
            if self._preview_mode == "gpu_video" and _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
                self.media_player.setVideoOutput(self.video_widget)

    def reinit_mpv(self, vendor: str) -> None:
        """Re-create the mpv player with a new GPU vendor selection.

        Preserves the current playback position and file so the preview
        continues seamlessly after the switch.
        """
        if not _MPV_AVAILABLE or not self.mpv_widget:
            return

        # Preserve the ACTIVE clip (multi-file) rather than always clip 0.
        current_file = self.video_path
        active = getattr(self, "_active_preview_clip_index", None)
        timeline = getattr(self, "video_timeline", None)
        if (
            timeline is not None and timeline.clip_count and active is not None
            and 0 <= active < timeline.clip_count
        ):
            current_file = timeline.clips[active].path
        current_pos = 0.0

        if self.mpv_player and current_file:
            try:
                current_pos = self.mpv_player.time_pos or 0.0
            except Exception:
                current_pos = 0.0
            try:
                self.mpv_player.terminate()
            except Exception:
                pass
            self.mpv_player = None
        self._mpv_timer = None

        self.mpv_preview_vendor = vendor
        self.set_video_widget(self.video_widget, self.mpv_widget)

        if self.mpv_player and current_file:
            self.mpv_player.play(str(current_file))
            self.mpv_player.pause = True
            try:
                self.mpv_player.time_pos = current_pos
            except Exception:
                pass
            # Emit a preview refresh to repaint HUD overlay (GLOBAL position).
            self._render_preview(self._local_to_global(current_pos))

    def _on_preview_accel_changed(self, vendor: str) -> None:
        """Handle the preview accelerator combo change from the UI."""
        if vendor == self.mpv_preview_vendor:
            return
        print(f"[Controller] Podgląd GPU zmieniony na: {_vendor_label(vendor)}")
        self.reinit_mpv(vendor)

    def _on_preview_mode_changed(self, mode: str) -> None:
        """Przełącza tryb podglądu (HUD Overlay vs Czyste Wideo GPU)."""
        self._preview_mode = mode
        if self.is_using_mpv():
            # mpv reports LOCAL position -> map back to GLOBAL for the HUD.
            self._render_preview(
                self._local_to_global(self.mpv_player.time_pos or 0.0)
            )
            return

        if not _QT_MULTIMEDIA_AVAILABLE or not hasattr(self, "media_player"):
            return
        if mode == "gpu_video" and self.video_widget:
            self.media_player.setVideoOutput(self.video_widget)
        else:
            self.media_player.setVideoOutput(self.video_sink)
            self._render_preview(
                self._local_to_global(self.media_player.position() / 1000.0)
            )

    def _setup_media_player(self) -> None:
        """Inicjalizuje QMediaPlayer + QVideoSink do podglądu wideo."""
        if not _QT_MULTIMEDIA_AVAILABLE:
            return
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0)  # wyciszone

        # Jawnie utwórz QVideoSink i ustaw jako output — FFmpeg backend
        # nie tworzy domyślnego sinka (videoSink() zwraca None).
        self.video_sink = QVideoSink()
        self.video_sink.videoFrameChanged.connect(self._on_video_frame)
        self.media_player.setVideoOutput(self.video_sink)
        # ETAP 4A: multi-file source switch — apply the pending seek once the
        # new clip is loaded, and handle end-of-media (next clip / stop).
        self.media_player.mediaStatusChanged.connect(self._on_media_status_changed)

    def _on_seek_changed(self, seconds: float) -> None:
        """Użytkownik przesunął oś czasu (GLOBAL position of the project)."""
        seconds = self._skip_cut_regions(seconds)
        self._playback_pos = seconds
        self.signals.sig_seek_position.emit(seconds)

        # global -> clip -> local (decoder) / absolute (telemetry)
        res = self._resolve_preview_time(seconds)

        if self.is_using_mpv():
            # Switch source only when the active clip changed; seek MPV to the
            # LOCAL time of that clip (never the global project time).
            self._preview_ensure_active_clip(
                res["clip_index"], res["clip"], res["local_time"], seconds
            )
            try:
                self.mpv_player.time_pos = res["local_time"]
                self._render_preview(seconds)
            except Exception as e:
                print(f"[MPV Seek Error] {e}")
            return

        # QMediaPlayer seeking (source switch + local seek) is handled inside
        # _render_preview (hardware-accelerated via _on_video_frame callback).
        self._render_preview(seconds)

    def _on_playback_start(self) -> None:
        """Użytkownik kliknął Play — GPU-accelerated playback."""
        if not self.video_path or self.video_duration_s <= 0:
            return
        self._playing = True
        self._frame_counter = 0
        self._composite_every_n = 3  # ograniczenie do ~10 FPS, aby zapobiec zamrożeniu CPU przy programowym QMediaPlayer

        if self.is_using_mpv():
            try:
                self.mpv_player.pause = False
                if self._mpv_timer is None:
                    self._mpv_timer = QTimer()
                    self._mpv_timer.timeout.connect(self._on_mpv_playback_tick)
                self._mpv_timer.start(33)  # ~30 FPS HUD update
            except Exception as e:
                print(f"[MPV Play Error] {e}")
            return

        if _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
            self.media_player.play()

    def _on_playback_stop(self) -> None:
        """Użytkownik kliknął Stop."""
        self._playing = False
        if self.is_using_mpv():
            try:
                self.mpv_player.pause = True
            except Exception:
                pass
            if self._mpv_timer is not None:
                self._mpv_timer.stop()
            return

        if _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
            self.media_player.pause()
        if self._playback_timer is not None:
            try:
                self._playback_timer.stop()
            except Exception:
                pass
            self._playback_timer = None

    def _on_mpv_playback_tick(self) -> None:
        if not self._playing or not self.is_using_mpv():
            return
        try:
            # MPV reports the LOCAL position of the active clip.
            local_pos = self.mpv_player.time_pos or 0.0
            global_pos = self._local_to_global(local_pos)

            # Przeskakuj regiony wycięte (on the GLOBAL axis)
            nxt = self._skip_cut_regions(global_pos)
            if abs(nxt - global_pos) > 0.1:
                res = self._resolve_preview_time(nxt)
                self._preview_ensure_active_clip(
                    res["clip_index"], res["clip"], res["local_time"], nxt
                )
                self.mpv_player.time_pos = res["local_time"]
                global_pos = nxt

            # Rozwiąż aktywny clip + local time.
            res = self._resolve_preview_time(global_pos)
            clip = res["clip"]
            clip_idx = res["clip_index"]
            local = res["local_time"]

            if clip is not None and local >= clip.duration_s - 1e-3:
                # Koniec bieżącego clipu.
                timeline = getattr(self, "video_timeline", None)
                if (
                    timeline is not None and clip_idx is not None
                    and clip_idx + 1 < timeline.clip_count
                ):
                    # Automatyczne przejście do następnego clipu (local=0),
                    # globalna oś pozostaje ciągła.
                    next_idx = clip_idx + 1
                    next_clip = timeline.clips[next_idx]
                    self._preview_ensure_active_clip(
                        next_idx, next_clip, 0.0, next_clip.global_start_s
                    )
                    try:
                        self.mpv_player.time_pos = 0.0
                    except Exception:
                        pass
                    self.signals.sig_seek_position.emit(next_clip.global_start_s)
                    self._render_preview(next_clip.global_start_s)
                else:
                    # Koniec ostatniego clipu = koniec całego projektu.
                    self._on_playback_stop()
                    self.signals.sig_seek_position.emit(0.0)
                    try:
                        self.mpv_player.time_pos = 0.0
                    except Exception:
                        pass
                return

            self.signals.sig_seek_position.emit(global_pos)
            self._render_preview(global_pos)
        except Exception as e:
            print(f"[MPV Tick Error] {e}")

    def _check_mpv_hwdec(self) -> None:
        """Verify that mpv is actually using hardware decoding.

        Called ~1.5s after file load to give mpv time to initialise the
        decoder.  Logs the active hwdec, interop, GPU context, and VO.
        If software-only decoding is detected, prints a warning.
        """
        if not self.is_using_mpv():
            return
        try:
            diag = get_hwdec_diagnostics(self.mpv_player)
            # Store for potential UI use
            self.mpv_hwdec_active = diag.get("hwdec_current")
            hw = diag.get("hwdec_current")
            if hw and hw != "no":
                print(f"[MPV HW] Dekodowanie sprzętowe aktywne: {hw}")
                print(f"          interop={diag.get('hwdec_interop')}, "
                      f"vo={diag.get('current_vo')}, "
                      f"gpu_ctx={diag.get('current_gpu_context')}, "
                      f"fmt={diag.get('pixelformat')}")
            else:
                print("[MPV HW] OSTRZEŻENIE: Dekodowanie PROGRAMOWE "
                      "(brak akceleracji sprzętowej). Sprawdź GPU/sterowniki.")
                print(f"          hwdec-current={hw}, "
                      f"codec={diag.get('video_codec')}")
        except Exception as e:
            print(f"[MPV HW] Nie udało się odczytać diagnostyki: {e}")

    def _playback_step(self) -> None:
        """Przesuń pozycję i zaplanuj następny krok.

        QMediaPlayer gra w tle — klatki płyną z _on_video_frame.
        Ten timer służy tylko do wyznaczania końca playbacku (GLOBAL axis).
        Przełączenie na następny clip realizuje _on_media_end.
        """
        if not self._playing:
            return
        step = 1.0 / max(self.fps, 1.0)
        if not hasattr(self, "_playback_pos"):
            self._playback_pos = 0.0
        raw_next = self._playback_pos + step
        nxt = self._skip_cut_regions(raw_next)
        if nxt != raw_next and _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
            self._seek_pending = True
            timeline = getattr(self, "video_timeline", None)
            if timeline is not None:
                # Multi-file: seek within/into the active clip uses LOCAL time.
                res = self._resolve_preview_time(nxt)
                switched = self._preview_ensure_active_clip(
                    res["clip_index"], res["clip"], res["local_time"], nxt
                )
                if not switched:
                    self.media_player.setPosition(
                        max(0, int(res["local_time"] * 1000))
                    )
            else:
                # Legacy single-file: global == local.
                self.media_player.setPosition(max(0, int(nxt * 1000)))
        if nxt >= self.video_duration_s:
            self._on_playback_stop()
            self._playback_pos = 0.0
            self.signals.sig_seek_position.emit(0.0)
            return
        self._playback_pos = nxt
        self.signals.sig_seek_position.emit(nxt)
        interval = max(16, int(step * 1000))
        self._playback_timer = QTimer.singleShot(interval, self._playback_step)

    def _on_media_end(self) -> None:
        """QMediaPlayer reached the end of the active clip's media.

        If there is a next clip, switch to it (local=0) and continue; only the
        end of the LAST clip stops the whole project.  The GLOBAL axis remains
        continuous (no gap inserted).
        """
        if not self._playing:
            return
        idx = getattr(self, "_active_preview_clip_index", 0)
        timeline = getattr(self, "video_timeline", None)
        if (
            timeline is not None and idx is not None
            and idx + 1 < timeline.clip_count
        ):
            next_idx = idx + 1
            next_clip = timeline.clips[next_idx]
            self._preview_ensure_active_clip(
                next_idx, next_clip, 0.0, next_clip.global_start_s
            )
            self._pending_seek_ms = 0
            self._seek_pending = True
            if not self._playing:
                self.media_player.play()
            self._playback_pos = next_clip.global_start_s
            self.signals.sig_seek_position.emit(next_clip.global_start_s)
            self._render_preview(next_clip.global_start_s)
        else:
            self._on_playback_stop()
            self._playback_pos = 0.0
            self.signals.sig_seek_position.emit(0.0)
