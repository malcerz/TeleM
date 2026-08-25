"""Widget podglądu wideo z osią czasu i interakcją myszką."""

from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QImage, QPixmap, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton,
    QStackedWidget, QComboBox,
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
            global_pos = widget.mapToGlobal(widget.rect().topLeft())
            self.setGeometry(global_pos.x(), global_pos.y(), widget.width(), widget.height())
            if self.parent_preview_widget.is_using_mpv() and self.parent_preview_widget.isVisible():
                self.show()
                self.raise_()

    def paintEvent(self, event):
        if self.hud_pixmap and not self.hud_pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            scaled = self.hud_pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            ox = (self.width() - scaled.width()) // 2
            oy = (self.height() - scaled.height()) // 2
            painter.drawPixmap(ox, oy, scaled)
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
        self._connect_trim()
        
        self.hud_overlay = TopLevelHUDWindow(self)
        
        # Event filter na image_label do przechwytywania zdarzeń myszy
        self.image_label.installEventFilter(self)

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

        # Oś czasu + Play/Stop
        time_row = QHBoxLayout()
        time_row.setContentsMargins(4, 2, 4, 2)
        time_row.setSpacing(4)

        self.play_btn = QPushButton("\u25B6")
        self.play_btn.setFixedSize(28, 26)
        self.play_btn.setToolTip("Odtwarzaj / Pauza")
        self.play_btn.setStyleSheet(
            "QPushButton { background-color: #2a6a2a; color: #88ff88; "
            "border: 1px solid #4a8a4a; border-radius: 3px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background-color: #3a8a3a; }"
        )
        self.play_btn.clicked.connect(self._toggle_playback)
        time_row.addWidget(self.play_btn)

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

        # ¦¦ Przyciski wycinania ¦¦

        self.cut_btn = QPushButton("\u2702")  # ?
        self.cut_btn.setFixedSize(26, 26)
        self.cut_btn.setToolTip("Wytnij zaznaczony fragment")
        self.cut_btn.setStyleSheet(
            "QPushButton { background-color: #5a3a2a; color: #ffaa66; "
            "border: 1px solid #7a5a4a; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #7a4a3a; }"
        )
        time_row.addWidget(self.cut_btn)

        self.undo_cut_btn = QPushButton("\u21B6")  # ?
        self.undo_cut_btn.setFixedSize(26, 26)
        self.undo_cut_btn.setToolTip("Cofnij ostatnie wycięcie")
        self.undo_cut_btn.setStyleSheet(
            "QPushButton { background-color: #3a3a5a; color: #8888ff; "
            "border: 1px solid #5a5a7a; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #4a4a7a; }"
        )
        time_row.addWidget(self.undo_cut_btn)

        self.restore_cut_btn = QPushButton("\u21A9")  # ?
        self.restore_cut_btn.setFixedSize(26, 26)
        self.restore_cut_btn.setToolTip("Przywróć wszystkie wycięte fragmenty")
        self.restore_cut_btn.setStyleSheet(
            "QPushButton { background-color: #3a5a3a; color: #88ff88; "
            "border: 1px solid #5a7a5a; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #4a7a4a; }"
        )
        time_row.addWidget(self.restore_cut_btn)

        layout.addLayout(time_row)

    # ── Widoczność narzędzi wycinania (✂/↩/↩) ──────────────────────────

    def set_cut_tools_visible(self, visible: bool) -> None:
        """Pokaż/ukryj przyciski wycinania.

        Podgląd jest współdzielony między zakładkami Projekt i Rendering;
        narzędzia wycinania są ukrywane w Projekcie, a pozostają w Rendering.
        """
        for btn in (self.cut_btn, self.undo_cut_btn, self.restore_cut_btn):
            btn.setVisible(visible)

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

    # ¦¦ Slot: nowa klatka podglądu ¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦

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
        """Odbiera QImage/QPixmap z kontrolera i wyświetla.

        QImage jest thread-safe i przychodzi z workera przez QueuedConnection.
        Konwersja na QPixmap (wymaga GUI wątku) odbywa się tutaj.
        """
        if qimg is None:
            return
        
        if self.is_using_mpv():
            if isinstance(qimg, QImage) and not qimg.isNull():
                pixmap = QPixmap.fromImage(qimg)
            elif isinstance(qimg, QPixmap) and not qimg.isNull():
                pixmap = qimg
            else:
                return
            if hasattr(self, "hud_overlay"):
                self.hud_overlay.set_hud_pixmap(pixmap)
                self.hud_overlay.sync_geometry()
            return

        if isinstance(qimg, QImage) and not qimg.isNull():
            pixmap = QPixmap.fromImage(qimg)
        elif isinstance(qimg, QPixmap) and not qimg.isNull():
            pixmap = qimg
        else:
            return
        scaled = pixmap.scaled(
            self.image_label.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.image_label.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #333;"
        )

        # Zapisz rozmiar i offset wyświetlonej pixmapy (do przeliczania współrzędnych)
        pix_size = scaled.size()
        self._pixmap_size = (pix_size.width(), pix_size.height())
        label_size = self.image_label.size()
        ox = (label_size.width() - pix_size.width()) // 2
        oy = (label_size.height() - pix_size.height()) // 2
        self._pixmap_offset = (ox, oy)

    def set_bboxes(self, bboxes: dict[str, tuple[int, int, int, int]], orig_w: int, orig_h: int) -> None:
        """Odbiera bounding boxy wskaźników z kontrolera (w pikselach oryginalnego obrazu)."""
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
                            #   - "text" oraz time_block/time_display → LEWY-GÓRNY róg
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
        """Przelicza współrzędne w widgetu na znormalizowane (0..100) w oryginalnym obrazie."""
        ow, oh = self._original_size
        if ow <= 0 or oh <= 0:
            return 0.0, 0.0
        
        scale = min(w / ow, h / oh)
        pw = ow * scale
        ph = oh * scale
        ox = (w - pw) / 2
        oy = (h - ph) / 2
        
        px = ((label_x - ox) / pw * 100.0) if pw > 0 else 0.0
        py = ((label_y - oy) / ph * 100.0) if ph > 0 else 0.0
        return (px, py)

    def _uses_topleft_anchor(self, key: str) -> bool:
        """True gdy pozycja (x, y) w layoucie oznacza LEWY-GÓRNY róg wskaźnika.

        W kompozytorze wskaźniki z formą "text" (oraz specjalne
        time_block/time_display) są pozycjonowane lewym-górnym rogiem;
        pozostałe formy (bar, gauge, chart, segment_bar, map, static_map)
        są pozycjonowane środkiem.
        """
        if key in ("time_block", "time_display"):
            return True
        ctrl = self._controller
        if ctrl is None:
            return True
        cfg = getattr(ctrl, "layout", {}).get("indicators", {}).get(key, {})
        return str(cfg.get("form", "text") or "text") == "text"

    def _hit_test(self, nx: float, ny: float) -> str | None:
        """Sprawdza który wskaźnik został kliknięty.

        nx, ny to współrzędne znormalizowane (0..100) względem oryginalnego obrazu.
        Bboxy w self._bboxes są w pikselach oryginalnego obrazu.
        """
        ow, oh = self._original_size
        if ow <= 0 or oh <= 0:
            return None
        # Przelicz znormalizowane współrzędne (0..100) na piksele oryginału
        click_x = (nx / 100.0) * ow
        click_y = (ny / 100.0) * oh
        for key, (bx, by, bw, bh) in self._bboxes.items():
            if bx <= click_x <= bx + bw and by <= click_y <= by + bh:
                return key
        return None

    # ¦¦ Slot: długość wideo ¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦

    def on_duration_ready(self, duration_s: float) -> None:
        """Ustawia długość wideo na seekbarze i znacznikach A/B."""
        self._duration_s = max(duration_s, 1.0)
        total_m = int(self._duration_s // 60)
        total_s = int(self._duration_s % 60)
        self.duration_label.setText(f"{total_m:02d}:{total_s:02d}")
        self.seek_bar.set_duration(duration_s)

    def set_controller(self, controller: object) -> None:
        """Ustaw referencję do kontrolera (wywoływane z project_tab)."""
        self._controller = controller
        if hasattr(controller, "set_video_widget") and self.video_widget:
            controller.set_video_widget(self.video_widget, getattr(self, 'mpv_widget', None))
        if self.is_using_mpv():
            self.stacked_widget.setCurrentIndex(1)
            self.hud_overlay.show()
            self.hud_overlay.sync_geometry()
            if hasattr(self, 'mpv_widget') and self.mpv_widget:
                self.mpv_widget.installEventFilter(self)
            if self.video_widget:
                self.video_widget.installEventFilter(self)

    def _connect_trim(self) -> None:
        self.cut_btn.clicked.connect(self._on_cut)
        self.undo_cut_btn.clicked.connect(self._on_undo_cut)
        self.restore_cut_btn.clicked.connect(self._on_restore_cut)

    def _on_cut(self) -> None:
        """Kliknięto ✂ — wytnij aktualny zakres A-B."""
        eff_a, eff_b = self.seek_bar.get_range()
        if not self.seek_bar.has_selection() or eff_b - eff_a < 0.1 or not self._controller:
            return
        if not hasattr(self._controller, 'add_cut_region'):
            return
        # Przelicz z efektywnego na oryginalny czas
        orig_a = self.seek_bar.eff_to_orig(eff_a)
        orig_b = self.seek_bar.eff_to_orig(eff_b)
        self._controller.add_cut_region(orig_a, orig_b)
        self.seek_bar.clear_selection()

    def _on_undo_cut(self) -> None:
        """Kliknięto ↩ — cofnij ostatnie wycięcie."""
        if self._controller and hasattr(self._controller, 'undo_cut_region'):
            self._controller.undo_cut_region()

    def _on_restore_cut(self) -> None:
        """Kliknięto ↩ — przywróć wszystkie wycięte fragmenty."""
        if self._controller and hasattr(self._controller, 'clear_cut_regions'):
            self._controller.clear_cut_regions()

    def _on_cut_region_changed(self, *args) -> None:
        """Aktualizuj seek bar po zmianie listy wyciętych fragmentów."""
        if self._controller and hasattr(self._controller, '_cut_regions'):
            self.seek_bar.set_cut_regions(self._controller._cut_regions)
            # Po aktualizacji cięć odśwież podgląd – przeskocz za wycięty zakres
            self._on_seek(self.seek_bar.get_position())
            # Zaktualizuj etykietę duration (efektywny czas)
            eff_dur = self.seek_bar._effective_duration_s
            total_m = int(eff_dur // 60)
            total_s = int(eff_dur % 60)
            self.duration_label.setText(f"{total_m:02d}:{total_s:02d}")

    # ¦¦ Slot: przesunięcie seekbara ¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦

    def _on_seek(self, seconds: float) -> None:
        """Użytkownik przeciągnął pasek (efektywny czas) → przelicz na oryginalny."""
        orig = self.seek_bar.eff_to_orig(seconds)
        self.signals.sig_seek_changed.emit(orig)

    def _on_seek_position(self, seconds: float) -> None:
        """Kontroler skorygował pozycję (oryginalny czas) → przelicz na efektywny."""
        eff = self.seek_bar.orig_to_eff(seconds)
        self.seek_bar.set_position(eff)
        mins = int(eff // 60)
        secs = int(eff % 60)
        self.time_label.setText(f"{mins:02d}:{secs:02d}")
