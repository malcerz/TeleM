import sys
import os
import math
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QHBoxLayout, QPushButton, QSlider, QLabel, QFileDialog
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import QTimer, Qt, QPointF
from PySide6.QtGui import QOpenGLContext, QPainter, QColor, QPen, QFont, QBrush

# Ustawienie ścieżki do libmpv
os.environ["PATH"] = os.path.dirname(os.path.abspath(__file__)) + os.pathsep + os.environ.get("PATH", "")
import mpv


class VideoOverlayGLWidget(QOpenGLWidget):
    """OpenGL Widget renderujący wideo przez akcelerowane libmpv w VRAM
    oraz rysujący nakładki graficzne HUD (prędkościomierz, dane FIT) w czasie rzeczywistym.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mpv_player = None
        self.mpv_gl = None

        # Akceleracja sprzętowa auto (NVDEC / QSV / AMF / D3D11VA)
        self.mpv_player = mpv.MPV(
            hwdec='auto',
            vo='libmpv',
            keep_open='yes'
        )

    def initializeGL(self):
        ctx = QOpenGLContext.currentContext()
        def get_proc_address(name):
            addr = ctx.getProcAddress(name.encode())
            return int(addr) if addr else 0

        try:
            self.mpv_gl = mpv.MpvRenderContext(
                self.mpv_player, 
                'opengl', 
                opengl_init_params={'get_proc_address': get_proc_address}
            )
            self.mpv_gl.update_cb = self._on_mpv_redraw
        except Exception as e:
            print(f"Błąd inicjalizacji MPV GL Context: {e}")

    def _on_mpv_redraw(self):
        # Aktualizacja klatki w wątku GUI
        QTimer.singleShot(0, self.update)

    def paintGL(self):
        # 1. Dekodowanie i renderowanie wideo GPU w VRAM (Zero-Copy)
        if self.mpv_gl:
            self.mpv_gl.render(
                fbo=self.defaultFramebufferObject(), 
                w=self.width(), 
                h=self.height(), 
                flip_y=True
            )

        # 2. Rysowanie nakładki HUD na żywo na buforze OpenGL
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        time_pos = self.mpv_player.time_pos or 0.0
        self._draw_speedometer(painter, time_pos)
        self._draw_telemetry_hud(painter, time_pos)

        painter.end()

    def _draw_speedometer(self, painter: QPainter, time_pos: float):
        """Dynamiczny testowy prędkościomierz graficzny."""
        speed = max(0.0, 32.0 + 18.0 * math.sin(time_pos * 0.8) + 6.0 * math.cos(time_pos * 2.1))
        max_speed = 70.0

        cx, cy = 130, self.height() - 130
        radius = 90

        # Tło zegara
        painter.setBrush(QBrush(QColor(10, 15, 25, 190)))
        painter.setPen(QPen(QColor(0, 200, 255), 2))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        # Łuk zakakresu prędkości
        start_angle = -210 * 16
        span_angle = -240 * (speed / max_speed) * 16
        painter.setPen(QPen(QColor(0, 255, 160), 7))
        painter.drawArc(cx - radius + 10, cy - radius + 10, (radius - 10) * 2, (radius - 10) * 2, start_angle, int(span_angle))

        # Wskazówka
        angle_rad = math.radians(210 - (speed / max_speed) * 240)
        pointer_len = radius - 18
        px = cx + pointer_len * math.cos(angle_rad)
        py = cy - pointer_len * math.sin(angle_rad)
        painter.setPen(QPen(QColor(255, 60, 60), 3))
        painter.drawLine(QPointF(cx, cy), QPointF(px, py))

        # Tekst cyfrowy
        painter.setFont(QFont("Segoe UI", 18, QFont.Bold))
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(cx - 45, cy + 20, 90, 30, Qt.AlignCenter, f"{speed:.1f}")
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QPen(QColor(170, 170, 170)))
        painter.drawText(cx - 45, cy + 45, 90, 20, Qt.AlignCenter, "km/h")

    def _draw_telemetry_hud(self, painter: QPainter, time_pos: float):
        """Testowe paski tętna i mocy (dane FIT/GPMF)."""
        hr = int(142 + 20 * math.sin(time_pos * 0.4))
        power = int(245 + 75 * math.cos(time_pos * 0.6))

        x, y = self.width() - 230, self.height() - 140
        w, h = 210, 120

        # Tło
        painter.setBrush(QBrush(QColor(15, 18, 28, 190)))
        painter.setPen(QPen(QColor(50, 60, 90), 1))
        painter.drawRoundedRect(x, y, w, h, 8, 8)

        # Puls (HR)
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.setPen(QPen(QColor(255, 80, 80)))
        painter.drawText(x + 12, y + 25, f"HR: {hr} bpm")
        painter.setBrush(QBrush(QColor(255, 80, 80, 220)))
        painter.drawRect(x + 12, y + 33, int((hr / 200.0) * 185), 8)

        # Moc (PWR)
        painter.setPen(QPen(QColor(60, 210, 255)))
        painter.drawText(x + 12, y + 68, f"PWR: {power} W")
        painter.setBrush(QBrush(QColor(60, 210, 255, 220)))
        painter.drawRect(x + 12, y + 76, int((power / 500.0) * 185), 8)


class MainWindow(QMainWindow):
    def __init__(self, video_path=None):
        super().__init__()
        self.setWindowTitle("TeleM HW Player - 4K/8K High Performance OpenGL Overlay Test")
        self.resize(1280, 720)

        self.video_widget = VideoOverlayGLWidget(self)

        self.btn_open = QPushButton("Otwórz Wideo")
        self.btn_play = QPushButton("Play / Pause")
        self.slider = QSlider(Qt.Horizontal)
        self.lbl_time = QLabel("00:00 / 00:00")

        self.btn_open.clicked.connect(self.open_file)
        self.btn_play.clicked.connect(self.toggle_play)
        self.slider.sliderMoved.connect(self.set_position)

        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(self.btn_open)
        ctrl_layout.addWidget(self.btn_play)
        ctrl_layout.addWidget(self.slider)
        ctrl_layout.addWidget(self.lbl_time)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.video_widget, stretch=1)
        main_layout.addLayout(ctrl_layout)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(100)
        self.ui_timer.timeout.connect(self.update_ui)
        self.ui_timer.start()

        if video_path and os.path.exists(video_path):
            QTimer.singleShot(500, lambda: self.video_widget.mpv_player.play(video_path))

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Wybierz plik wideo", "", "Video (*.mp4 *.mkv *.mov *.avi)")
        if path:
            self.video_widget.mpv_player.play(path)

    def toggle_play(self):
        self.video_widget.mpv_player.pause = not self.video_widget.mpv_player.pause

    def set_position(self, pos):
        dur = self.video_widget.mpv_player.duration or 0
        if dur > 0:
            target = (pos / 1000.0) * dur
            self.video_widget.mpv_player.time_pos = target

    def update_ui(self):
        player = self.video_widget.mpv_player
        if player and player.duration:
            pos = player.time_pos or 0
            dur = player.duration or 1
            self.slider.setValue(int((pos / dur) * 1000))
            self.lbl_time.setText(f"{int(pos//60):02d}:{int(pos%60):02d} / {int(dur//60):02d}:{int(dur%60):02d}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    test_video = os.path.join(os.path.dirname(__file__), "Video", "GX020079.MP4")
    win = MainWindow(video_path=test_video)
    win.show()
    sys.exit(app.exec())
