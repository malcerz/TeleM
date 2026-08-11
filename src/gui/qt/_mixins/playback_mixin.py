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

        current_file = self.video_path
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
            # Emit a preview refresh to repaint HUD overlay
            self._render_preview(current_pos)

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
            self._render_preview(self.mpv_player.time_pos or 0.0)
            return

        if not _QT_MULTIMEDIA_AVAILABLE or not hasattr(self, "media_player"):
            return
        if mode == "gpu_video" and self.video_widget:
            self.media_player.setVideoOutput(self.video_widget)
        else:
            self.media_player.setVideoOutput(self.video_sink)
            self._render_preview(self.media_player.position() / 1000.0)

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

    def _on_seek_changed(self, seconds: float) -> None:
        """Użytkownik przesunął oś czasu."""
        seconds = self._skip_cut_regions(seconds)
        self._playback_pos = seconds
        self.signals.sig_seek_position.emit(seconds)

        if self.is_using_mpv():
            try:
                self.mpv_player.time_pos = seconds
                self._render_preview(seconds)
            except Exception as e:
                print(f"[MPV Seek Error] {e}")
            return

        # _render_preview handles QMediaPlayer seeking internally
        # (hardware-accelerated frame decode via _on_video_frame callback)
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
            pos = self.mpv_player.time_pos or 0.0

            # Przeskakuj regiony wycięte
            nxt = self._skip_cut_regions(pos)
            if abs(nxt - pos) > 0.1:
                self.mpv_player.time_pos = nxt
                pos = nxt

            # Wykrycie końca wideo
            if pos >= self.video_duration_s:
                self._on_playback_stop()
                self.signals.sig_seek_position.emit(0.0)
                try:
                    self.mpv_player.time_pos = 0.0
                except Exception:
                    pass
                return

            self.signals.sig_seek_position.emit(pos)
            self._render_preview(pos)
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
        Ten timer służy tylko do wyznaczania końca playbacku.
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
