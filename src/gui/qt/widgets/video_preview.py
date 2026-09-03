"""Widget podglądu wideo z osią czasu i interakcją myszką."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QEvent, QRect, QPoint
from PySide6.QtGui import QImage, QPixmap, QPainter

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton,
    QStackedWidget,
)

try:
    import shiboken6
    _HAS_SHIBOKEN = True
except ImportError:
    _HAS_SHIBOKEN = False

try:
    from PySide6.QtMultimediaWidgets import QVideoWidget
    _HAS_VIDEO_WIDGET = True
except ImportError:
    _HAS_VIDEO_WIDGET = False

from src.gui.qt.signals import get_signals
from src.gui.qt.widgets.seek_bar import SeekBar


def preview_aspect_size(available_h: int, available_w: int) -> tuple[int, int]:
    """Wspólny rozmiar podglądu 16:9 (ten sam w Projekt i Rendering).

    Rozmiar wyliczany z wysokości zakładki (0.8 × wysokość), ale ograniczany
    szerokością dostępną dla podglądu w Renderingu (~70% szerokości zakładki),
    aby ten sam rozmiar zmieścił się w obu zakładkach (Rendering ma 75% obszaru
    na podgląd, Projekt całą szerokość minus panel właściwości).
    """
    available_h = max(100, int(available_h))
    available_w = max(300, int(available_w))
    h = int(available_h * 0.8)
    w = int(h * 16.0 / 9.0)
    max_w = int(available_w * 0.70)
    if w > max_w:
        w = max_w
        h = int(w * 9.0 / 16.0)
    return (w, h)


class TopLevelHUDWindow(QWidget):
    """Okno nakładki HUD z przezroczystym tłem przypisane do okna głównego."""
    def __init__(self, parent_preview_widget):
        super().__init__(None)
        self.parent_preview_widget = parent_preview_widget
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.hud_pixmap = None

    def set_hud_pixmap(self, pixmap):
        self.hud_pixmap = pixmap
        self.update()

    def sync_geometry(self):
        if not self.parent_preview_widget:
            return
        main_win = self.parent_preview_widget.window()
        if main_win and main_win != self and self.parent() != main_win:
            self.setParent(main_win)
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowTransparentForInput)
            self.setAttribute(Qt.WA_TranslucentBackground, True)

        if main_win and (main_win.isMinimized() or not self.parent_preview_widget.isVisible()):
            self.hide()
            return

        if self.parent_preview_widget.stacked_widget:
            widget = self.parent_preview_widget.stacked_widget
            if not widget.isVisible():
                self.hide()
                return
            global_pos = widget.mapToGlobal(QPoint(0, 0))
            self.setGeometry(global_pos.x(), global_pos.y(), widget.width(), widget.height())
            if self.parent_preview_widget.is_using_mpv() and self.parent_preview_widget.isVisible():
                self.show()
                self.raise_()

    def paintEvent(self, event):
        if self.hud_pixmap and not self.hud_pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            vrect = self.parent_preview_widget.get_video_rect()
            # self.hud_pixmap has devicePixelRatio set to dpr.
            # Its underlying buffer is physical (phys_w x phys_h).
            # Drawing at logical (vrect.x(), vrect.y()) maps 1:1 to physical screen pixels with zero post-raster resize.
            painter.drawPixmap(vrect.x(), vrect.y(), self.hud_pixmap)
            painter.end()


class VideoPreview(QWidget):
    """Podgląd wideo + suwak osi czasu + klikalne/przeciągalne wskaźniki.

    Odbiera QPixmap z kontrolera przez sygnał sig_preview_frame_ready.
    Odbiera bounding boxy przez set_bboxes().
    Emituje sig_indicator_clicked / sig_indicator_moved.
    """

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self._controller: object = None  # ustawiane przez set_controller()
        self._duration_s = 100.0
        self._bboxes: dict[str, tuple[int, int, int, int]] = {}
        self._dragging_key: str | None = None
        self._drag_offset_norm: tuple[float, float] = (0.0, 0.0)
        self._pixmap_size: tuple[int, int] = (0, 0)
        self._pixmap_offset: tuple[int, int] = (0, 0)
        self._original_size: tuple[int, int] = (0, 0)
        self._is_playing = False
        self._build_ui()
        
        self.hud_overlay = TopLevelHUDWindow(self)
        
        # Event filter na image_label do przechwytywania zdarzeń myszy
        self.image_label.installEventFilter(self)

    def get_video_rect(self) -> QRect:
        """Zwraca rzeczywisty prostokąt obrazu wideo wewnątrz stacked_widget w pikselach logicznych.

        Uwzględnia aspect ratio wideo (lub 16:9 domyślnie) oraz letterbox / pillarbox.
        """
        w = self.stacked_widget.width()
        h = self.stacked_widget.height()
        if w <= 0 or h <= 0:
            return QRect(0, 0, 1, 1)

        vw = 16
        vh = 9
        ctrl = self._controller
        if ctrl is not None:
            info = getattr(ctrl, "video_info", None)
            vw = getattr(ctrl, "video_width", 0) or (info.get("width", 0) if isinstance(info, dict) else 0) or getattr(ctrl, "layout", {}).get("width", 0) or 16
            vh = getattr(ctrl, "video_height", 0) or (info.get("height", 0) if isinstance(info, dict) else 0) or getattr(ctrl, "layout", {}).get("height", 0) or 9
        aspect = float(vw) / float(vh) if vh > 0 else (16.0 / 9.0)

        if w / h >= aspect:
            target_h = h
            target_w = max(1, int(round(h * aspect)))
            ox = (w - target_w) // 2
            oy = 0
        else:
            target_w = w
            target_h = max(1, int(round(w / aspect)))
            ox = 0
            oy = (h - target_h) // 2

        return QRect(ox, oy, target_w, target_h)

    def get_dpr(self) -> float:
        """Zwraca devicePixelRatioF powierzchni podglądu."""
        try:
            return float(self.devicePixelRatioF())
        except Exception:
            return 1.0

    def get_physical_video_rect(self) -> QRect:
        """Zwraca prostokąt wideo w fizycznych pikselach bufora (DPI-aware)."""
        vrect = self.get_video_rect()
        dpr = self.get_dpr()
        return QRect(
            int(round(vrect.x() * dpr)),
            int(round(vrect.y() * dpr)),
            max(1, int(round(vrect.width() * dpr))),
            max(1, int(round(vrect.height() * dpr))),
        )

    def is_geometry_ready(self) -> bool:
        """Sprawdza, czy geometria podglądu jest gotowa i ma dodatnie wymiary."""
        vrect = self.get_video_rect()
        dpr = self.get_dpr()
        return (vrect.width() > 10 and vrect.height() > 10 and dpr > 0.0)

    def _notify_controller_preview_size(self) -> None:
        if self._controller and hasattr(self._controller, "set_preview_target_size"):
            phys_rect = self.get_physical_video_rect()
            dpr = self.get_dpr()
            if phys_rect.width() > 10 and phys_rect.height() > 10 and dpr > 0.0:
                self._controller.set_preview_target_size(phys_rect.width(), phys_rect.height(), dpr=dpr)
                self._print_preview_debug_info()


    def print_preview_raster_diag(self) -> None:
        """Wypisuje diagnostykę fizycznego mapowania rastra 1:1 dla fullscreen preview."""
        vrect = self.get_video_rect()
        dpr = self.get_dpr()
        phys_rect = self.get_physical_video_rect()
        ctrl = self._controller
        vw = getattr(ctrl, "video_width", 0) or 3840
        vh = getattr(ctrl, "video_height", 0) or 2160
        target_w = getattr(ctrl, "_preview_target_w", phys_rect.width())
        target_h = getattr(ctrl, "_preview_target_h", phys_rect.height())
        display_sx = 1.0
        display_sy = 1.0
        print(
            f"[PREVIEW RASTER]\n"
            f"video={vw}x{vh}\n"
            f"qt_logical={vrect.width()}x{vrect.height()}\n"
            f"dpr={dpr:.2f}\n"
            f"qt_physical={phys_rect.width()}x{phys_rect.height()}\n"
            f"hud_canvas={target_w}x{target_h}\n"
            f"composite={target_w}x{target_h}\n"
            f"display_scale_x={display_sx:.2f}\n"
            f"display_scale_y={display_sy:.2f}",
            flush=True,
        )

    def _print_preview_debug_info(self) -> None:
        if os.environ.get("TELEM_RENDER_DEBUG") or os.environ.get("TELEM_PREVIEW_DEBUG"):
            vrect = self.get_video_rect()
            dpr = self.get_dpr()
            phys_rect = self.get_physical_video_rect()
            cw = getattr(self._controller, "video_width", 3840) or 3840
            ch = getattr(self._controller, "video_height", 2160) or 2160
            sx = phys_rect.width() / float(cw) if cw > 0 else 1.0
            sy = phys_rect.height() / float(ch) if ch > 0 else 1.0
            print(
                f"[Preview HUD] "
                f"canonical={cw}x{ch} "
                f"widget_logical={self.stacked_widget.width()}x{self.stacked_widget.height()} "
                f"dpr={dpr:.2f} "
                f"video_rect_logical={vrect.x()},{vrect.y()},{vrect.width()}x{vrect.height()} "
                f"video_rect_physical={phys_rect.x()},{phys_rect.y()},{phys_rect.width()}x{phys_rect.height()} "
                f"overlay_surface={phys_rect.width()}x{phys_rect.height()} "
                f"scale_x={sx:.4f} "
                f"scale_y={sy:.4f} "
                f"offset_x={vrect.x()} "
                f"offset_y={vrect.y()} "
                f"post_raster_resize=False",
                flush=True,
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._notify_controller_preview_size()
        if self.is_using_mpv() and self._hud_alive():
            self.hud_overlay.sync_geometry()


    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Stack podglądu (HUD Label vs GPU QVideoWidget)
        self.stacked_widget = QStackedWidget()

        # Obraz podglądu HUD (Label)
        self.image_label = QLabel("Wybierz plik wideo\nw zakładce Wczytywanie")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet(
            "background-color: #1a1a1a; color: #666;"
            "font-size: 14px; border: 1px solid #333;"
        )
        self.image_label.setMinimumSize(400, 300)
        self.image_label.setScaledContents(False)
        self.image_label.setMouseTracking(True)
        self.stacked_widget.addWidget(self.image_label)

        # Specjalny QWidget tylko dla MPV (aby uniknąć konfliktów z QVideoWidget)
        self.mpv_widget = QWidget()
        self.mpv_widget.setAttribute(Qt.WA_NativeWindow, True)
        self.mpv_widget.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.mpv_widget.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.mpv_widget.setAttribute(Qt.WA_NoSystemBackground, True)
        self.stacked_widget.addWidget(self.mpv_widget)

        # Tradycyjne wyjście dla QMediaPlayer
        if _HAS_VIDEO_WIDGET:
            self.video_widget = QVideoWidget()
            self.video_widget.setStyleSheet("background-color: #000000;")
            self.stacked_widget.addWidget(self.video_widget)
        else:
            self.video_widget = QWidget()
            self.video_widget.setStyleSheet("background-color: #000000;")
            self.stacked_widget.addWidget(self.video_widget)

        layout.addWidget(self.stacked_widget, 1)

        # Oś czasu + Play/Stop + frame step + fullscreen
        time_row = QHBoxLayout()
        time_row.setContentsMargins(4, 2, 4, 2)
        time_row.setSpacing(4)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(28, 26)
        self.play_btn.setToolTip("Odtwarzaj / Pauza")
        self.play_btn.setStyleSheet(
            "QPushButton { background-color: #2a6a2a; color: #88ff88; "
            "border: 1px solid #4a8a4a; border-radius: 3px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background-color: #3a8a3a; }"
        )
        self.play_btn.clicked.connect(self._toggle_playback)
        time_row.addWidget(self.play_btn)

        # Obok Play: oba przyciski frame-step
        self.btn_prev_frame = QPushButton("|<")
        self.btn_prev_frame.setFixedSize(32, 26)
        self.btn_prev_frame.setToolTip("Poprzednia klatka")
        self.btn_prev_frame.setStyleSheet(
            "QPushButton { background-color: #333; color: #ccc; "
            "border: 1px solid #555; border-radius: 3px; font-weight: bold; font-size: 11px; }"
            "QPushButton:hover { background-color: #444; }"
        )
        self.btn_prev_frame.clicked.connect(lambda: self._step_frame(-1))
        time_row.addWidget(self.btn_prev_frame)

        self.btn_next_frame = QPushButton(">|")
        self.btn_next_frame.setFixedSize(32, 26)
        self.btn_next_frame.setToolTip("Następna klatka")
        self.btn_next_frame.setStyleSheet(
            "QPushButton { background-color: #333; color: #ccc; "
            "border: 1px solid #555; border-radius: 3px; font-weight: bold; font-size: 11px; }"
            "QPushButton:hover { background-color: #444; }"
        )
        self.btn_next_frame.clicked.connect(lambda: self._step_frame(+1))
        time_row.addWidget(self.btn_next_frame)

        self.time_label = QLabel("00:00")
        self.time_label.setFixedWidth(50)
        self.time_label.setStyleSheet("color: #aaa; font-size: 11px;")
        time_row.addWidget(self.time_label)

        self.seek_bar = SeekBar()
        self.seek_bar.sig_position_changed.connect(self._on_seek)
        time_row.addWidget(self.seek_bar, 1)

        self.duration_label = QLabel("00:00")
        self.duration_label.setFixedWidth(50)
        self.duration_label.setAlignment(Qt.AlignRight)
        self.duration_label.setStyleSheet("color: #aaa; font-size: 11px;")
        time_row.addWidget(self.duration_label)

        # Przycisk pełnoekranowy
        self.btn_fullscreen = QPushButton("\u26F6")
        self.btn_fullscreen.setFixedSize(28, 26)
        self.btn_fullscreen.setToolTip("Pełny ekran (ESC aby wyjść)")
        self.btn_fullscreen.setStyleSheet(
            "QPushButton { background-color: #333; color: #ddd; "
            "border: 1px solid #555; border-radius: 3px; font-size: 14px; }"
            "QPushButton:hover { background-color: #444; }"
        )
        self.btn_fullscreen.clicked.connect(self._toggle_fullscreen)
        time_row.addWidget(self.btn_fullscreen)

        layout.addLayout(time_row)

        # Referencja do okna pełnoekranowego (None gdy zamknięte)
        self._fullscreen_window: "FullscreenPreviewWindow | None" = None


    def _hud_alive(self) -> bool:
        """Czy obiekt C++ nakładki HUD nadal istnieje (bezpieczeństwo przy zamykaniu)."""
        hud = getattr(self, "hud_overlay", None)
        if hud is None:
            return False
        if _HAS_SHIBOKEN:
            try:
                return shiboken6.isValid(hud)
            except Exception:
                return False
        return True

    def is_using_mpv(self) -> bool:
        return self._controller is not None and getattr(self._controller, "mpv_player", None) is not None

    def _toggle_playback(self) -> None:
        """Przełącza odtwarzanie między Play (▶) a Pause (❚❚)."""
        if self._is_playing:
            self._is_playing = False
            self.play_btn.setText("▶")
            self.play_btn.setToolTip("Odtwarzaj")
            self.play_btn.setStyleSheet(
                "QPushButton { background-color: #2a6a2a; color: #88ff88; "
                "border: 1px solid #4a8a4a; border-radius: 3px; font-weight: bold; font-size: 13px; }"
                "QPushButton:hover { background-color: #3a8a3a; }"
            )
            self.signals.sig_playback_stop.emit()
        else:
            self._is_playing = True
            self.play_btn.setText("❚❚")
            self.play_btn.setToolTip("Zatrzymaj")
            self.play_btn.setStyleSheet(
                "QPushButton { background-color: #6a2a2a; color: #ff8888; "
                "border: 1px solid #8a4a4a; border-radius: 3px; font-weight: bold; font-size: 13px; }"
                "QPushButton:hover { background-color: #8a3a3a; }"
            )
            self.signals.sig_playback_start.emit()

    def showEvent(self, event):
        super().showEvent(event)
        win = self.window()
        if win:
            win.installEventFilter(self)
        self._notify_controller_preview_size()
        if self.is_using_mpv():
            self.hud_overlay.show()
            self.hud_overlay.sync_geometry()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._hud_alive():
            self.hud_overlay.hide()

    def closeEvent(self, event):
        if hasattr(self, "hud_overlay"):
            self.hud_overlay.close()
        super().closeEvent(event)

    def on_frame_ready(self, qimg: QImage | QPixmap) -> None:
        """Odbiera QImage/QPixmap z kontrolera i wyświetla 1:1 w natywnej rozdzielczości (DPI-aware)."""
        if qimg is None:
            return
        
        dpr = self.get_dpr()
        if isinstance(qimg, QImage) and not qimg.isNull():
            if abs(qimg.devicePixelRatio() - dpr) > 1e-4:
                qimg.setDevicePixelRatio(dpr)
            pixmap = QPixmap.fromImage(qimg)
        elif isinstance(qimg, QPixmap) and not qimg.isNull():
            pixmap = qimg
            if abs(pixmap.devicePixelRatio() - dpr) > 1e-4:
                pixmap.setDevicePixelRatio(dpr)
        else:
            return

        vrect = self.get_video_rect()

        if self.is_using_mpv():
            if hasattr(self, "hud_overlay"):
                self.hud_overlay.set_hud_pixmap(pixmap)
                self.hud_overlay.sync_geometry()
            return

        self.image_label.setPixmap(pixmap)
        self.image_label.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #333;"
        )
        self._pixmap_size = (pixmap.width(), pixmap.height())
        self._pixmap_offset = (vrect.x(), vrect.y())


    def set_bboxes(self, bboxes: dict[str, tuple[int, int, int, int]], orig_w: int, orig_h: int) -> None:
        """Odbiera bounding boxy wskaźników z kontrolera (w pikselach obrazu podglądu)."""
        self._bboxes = bboxes
        self._original_size = (orig_w, orig_h)

    def eventFilter(self, obj, event) -> bool:
        """Przechwytuje zdarzenia myszy i przemieszczania okna głównego."""
        if obj is self.window():
            if event.type() in (QEvent.Move, QEvent.Resize):
                if self.is_using_mpv() and self.isVisible() and self._hud_alive():
                    self.hud_overlay.sync_geometry()
            elif event.type() == QEvent.WindowStateChange:
                if self.window().isMinimized():
                    if self._hud_alive():
                        self.hud_overlay.hide()
                else:
                    if self.is_using_mpv() and self.isVisible() and self._hud_alive():
                        self.hud_overlay.show()
                        self.hud_overlay.sync_geometry()
            elif event.type() in (QEvent.Hide, QEvent.Close):
                if self._hud_alive():
                    self.hud_overlay.hide()
            elif event.type() == QEvent.Show:
                if self.is_using_mpv() and self.isVisible():
                    self.hud_overlay.show()
                    self.hud_overlay.sync_geometry()
            return super().eventFilter(obj, event)

        if obj in (self.image_label, self.video_widget, getattr(self, 'mpv_widget', None)) and event.type() in (
            QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease,
        ):
            if event.type() == QEvent.MouseMove and not self._dragging_key:
                return super().eventFilter(obj, event)

            me = event  # type: QMouseEvent
            lx, ly = me.position().x(), me.position().y()
            w, h = obj.width(), obj.height()
            nx, ny = self._norm_from_geometry(lx, ly, w, h)
            in_pixmap = 0.0 <= nx <= 100.0 and 0.0 <= ny <= 100.0

            if event.type() == QEvent.MouseButtonPress and me.button() == Qt.LeftButton:
                if in_pixmap:
                    key = self._hit_test(nx, ny)
                    if key:
                        self._dragging_key = key
                        ow, oh = self._original_size
                        bbox = self._bboxes.get(key)
                        if bbox and ow > 0 and oh > 0:
                            bx, by, bw, bh = bbox
                            # Semantyka pozycji (x, y) w layoucie zależy od formy:
                            #   - "text" oraz time_display → LEWY-GÓRNY róg
                            #   - bar/gauge/chart/segment_bar/map → ŚRODEK
                            # Kotwiczymy na właściwym punkcie (skala 0..100, zgodna
                            # z _norm_from_geometry), żeby wskaźnik nie przeskakiwał
                            # o połowę swojego rozmiaru przy chwyceniu.
                            if self._uses_topleft_anchor(key):
                                ax = bx / ow * 100.0
                                ay = by / oh * 100.0
                            else:
                                ax = (bx + bw / 2) / ow * 100.0
                                ay = (by + bh / 2) / oh * 100.0
                            self._drag_offset_norm = (nx - ax, ny - ay)
                        else:
                            self._drag_offset_norm = (0.0, 0.0)
                        self.signals.sig_indicator_clicked.emit(key)
                        return True
                return super().eventFilter(obj, event)

            if event.type() == QEvent.MouseMove and self._dragging_key:
                if in_pixmap:
                    nx = max(0.0, min(100.0, nx))
                    ny = max(0.0, min(100.0, ny))
                    ox, oy = self._drag_offset_norm
                    self.signals.sig_indicator_moved.emit(
                        self._dragging_key, nx - ox, ny - oy,
                    )
                    return True
                return super().eventFilter(obj, event)

            if event.type() == QEvent.MouseButtonRelease:
                self._dragging_key = None
                self._drag_offset_norm = (0.0, 0.0)
                return super().eventFilter(obj, event)

        return super().eventFilter(obj, event)

    def _norm_from_geometry(self, label_x: float, label_y: float, w: int, h: int) -> tuple[float, float]:
        """Przelicza współrzędne w widgetu na znormalizowane (0..100) wewnątrz rzeczywistego rect wideo."""
        vrect = self.get_video_rect()
        pw = vrect.width()
        ph = vrect.height()
        ox = vrect.x()
        oy = vrect.y()
        
        px = ((label_x - ox) / pw * 100.0) if pw > 0 else 0.0
        py = ((label_y - oy) / ph * 100.0) if ph > 0 else 0.0
        return (px, py)

    def _uses_topleft_anchor(self, key: str) -> bool:
        """True gdy pozycja (x, y) w layoucie oznacza LEWY-GÓRNY róg wskaźnika."""
        if key == "time_display":
            return True
        ctrl = self._controller
        if ctrl is None:
            return True
        cfg = getattr(ctrl, "layout", {}).get("indicators", {}).get(key, {})
        return str(cfg.get("form", "text") or "text") == "text"

    def _hit_test(self, nx: float, ny: float) -> str | None:
        """Sprawdza który wskaźnik został kliknięty."""
        ow, oh = self._original_size
        if ow <= 0 or oh <= 0:
            return None
        click_x = (nx / 100.0) * ow
        click_y = (ny / 100.0) * oh
        for key, (bx, by, bw, bh) in self._bboxes.items():
            if bx <= click_x <= bx + bw and by <= click_y <= by + bh:
                return key
        return None

    def on_duration_ready(self, duration_s: float) -> None:
        """Ustawia długość wideo na seekbarze."""
        self._duration_s = max(duration_s, 1.0)
        total_m = int(self._duration_s // 60)
        total_s = int(self._duration_s % 60)
        self.duration_label.setText(f"{total_m:02d}:{total_s:02d}")
        self.seek_bar.set_duration(duration_s)

    def set_controller(self, controller: object) -> None:
        """Ustaw referencję do kontrolera (wywoływane z project_tab)."""
        self._controller = controller
        if hasattr(controller, "set_preview_widget"):
            controller.set_preview_widget(self)
        if hasattr(controller, "set_video_widget") and self.video_widget:
            controller.set_video_widget(self.video_widget, getattr(self, 'mpv_widget', None))
        self._notify_controller_preview_size()

        if self.is_using_mpv():
            self.stacked_widget.setCurrentIndex(1)
            self.hud_overlay.show()
            self.hud_overlay.sync_geometry()
            if hasattr(self, 'mpv_widget') and self.mpv_widget:
                self.mpv_widget.installEventFilter(self)
            if self.video_widget:
                self.video_widget.installEventFilter(self)


    def _on_cut_region_changed(self, *args) -> None:
        return

    def _on_seek(self, seconds: float) -> None:
        """Użytkownik przeciągnął pasek (efektywny czas) → przelicz na oryginalny."""
        orig = self.seek_bar.eff_to_orig(seconds)
        self.signals.sig_seek_changed.emit(orig)

    def _on_seek_position(self, seconds: float) -> None:
        """Kontroler skorygował pozycję (oryginalny czas) → przelicz na efektywny."""
        eff = self.seek_bar.orig_to_eff(seconds)
        eff_capped = min(eff, self.seek_bar.get_effective_duration())
        self.seek_bar.set_position(eff)
        mins = int(eff_capped // 60)
        secs = int(eff_capped % 60)
        self.time_label.setText(f"{mins:02d}:{secs:02d}")

    # ── Krok klatkowy ─────────────────────────────────────────────────────

    def _step_frame(self, delta: int) -> None:
        """Przesuń pozycję o delta klatek (delegowane do kontrolera z obsługą MPV i multi-file)."""
        self.signals.sig_frame_step.emit(int(delta))

    # ── Pełnoekranowy podgląd ─────────────────────────────────────────────

    def _toggle_fullscreen(self) -> None:
        """Przełącz tryb pełnoekranowy (Fullscreen Preview)."""
        self.signals.sig_toggle_fullscreen.emit()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            self.signals.sig_toggle_fullscreen.emit()
            event.accept()
        elif key == Qt.Key_Space:
            self._toggle_playback()
            event.accept()
        elif key == Qt.Key_Left:
            self.signals.sig_frame_step.emit(-1)
            event.accept()
        elif key == Qt.Key_Right:
            self.signals.sig_frame_step.emit(1)
            event.accept()
        else:
            super().keyPressEvent(event)
