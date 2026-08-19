"""
Verification test for Export Preview lifecycle, FPS display, and performance smoke.
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path("c:/_DEV/TeleM")))

from src.gui.qt.tabs.render_tab import RenderTab
from src.gui.qt.signals import get_signals
from PySide6.QtWidgets import QApplication, QMessageBox
from PIL import Image
from datetime import datetime, timezone

QMessageBox.information = lambda *args, **kwargs: None

# Initialize Qt App for test
app = QApplication.instance()
if app is None:
    app = QApplication([])

signals = get_signals()
tab = RenderTab()

class DummyController:
    video_paths = ["tests/test_media/sample.mp4"]
    video_path = "tests/test_media/sample.mp4"
    video_duration_s = 10.0
    font_path = "assets/Roboto-Bold.ttf"
    ffmpeg_exe = "ffmpeg"
    ffprobe_exe = "ffprobe"
    layout = {
        "width": 1920, "height": 1080,
        "indicators": {
            "speed_visual": {"enabled": True, "type": "speed", "x": 10, "y": 10, "size": 0.2},
            "fit_cadence_text": {"enabled": True, "type": "chart", "x": 50, "y": 80, "size": 0.3},
        }
    }
    class Telemetry:
        start_dt_utc = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)
        speed_samples = [(datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc), 25.0), (datetime(2026, 8, 19, 12, 0, 5, tzinfo=timezone.utc), 30.0)]
        track_samples = [(datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc), 0.0), (datetime(2026, 8, 19, 12, 0, 5, tzinfo=timezone.utc), 50.0)]
        alt_samples = [(datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc), 100.0), (datetime(2026, 8, 19, 12, 0, 5, tzinfo=timezone.utc), 150.0)]
        iso_samples = exposure_samples = temperature_samples = None
        gpx_speed_samples = gpx_track_samples = gpx_alt_samples = None
        gpx_power_samples = gpx_atemp_samples = gpx_hr_samples = gpx_cad_samples = None
        fit_data = None
        def get_samples_for_source(self, *args, **kwargs): return []
        def resolve_samples(self, *args, **kwargs): return []
        def get_gps_track_for_source(self, *args, **kwargs): return []
        def resolve_value(self, *args, **kwargs): return 0.0
    telemetry = Telemetry()

from datetime import datetime, timezone
tab._controller = DummyController()
tab._controller.telemetry.start_dt_utc = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)

print("===============================================================================")
print("1. VERIFYING STATS AND FPS PROGRESS CONTRACT")
print("===============================================================================")

# Simulate on_render_progress: completed=100, total=300, elapsed=2.5s, fps=40.0
tab._rendering = True
tab._render_start = time.monotonic() - 2.5
tab._render_total = 300
tab._on_render_progress(completed=100, total=300, elapsed=2.5, fps=40.0, hud_state={"ts": 3.33, "frame_idx": 99})

stats_text = tab.lbl_stats.text()
print(f"Stats label output: {stats_text}")
assert "FPS: 40.0" in stats_text, f"FPS incorrect: {stats_text}"
assert "Frame: 100 / 300" in stats_text, f"Frame count incorrect: {stats_text}"
assert "33.3%" in stats_text, f"Percentage incorrect: {stats_text}"
print("FPS & Stats formatting: PASS")

print("\n===============================================================================")
print("2. VERIFYING PREVIEW FRAME GENERATION & THROTTLING")
print("===============================================================================")

qimg = tab._build_preview_qimage(ts=3.33, tw=640, th=360)
assert qimg is not None and not qimg.isNull(), "Built preview QImage is null!"
tab._on_export_preview_ready(qimg)
pixmap = tab.hud_preview_label.pixmap()
assert pixmap is not None and not pixmap.isNull(), "Preview pixmap is null!"
print(f"Generated preview pixmap: {pixmap.width()}x{pixmap.height()} -> PASS")

print("\n===============================================================================")
print("3. VERIFYING EXPORT FINISH & SECOND EXPORT LIFECYCLE")
print("===============================================================================")

tab._on_finished({}, "out.mp4")
assert not tab._rendering, "Should not be rendering after finish"
assert tab._hud_ts is None, "HUD timestamp should be reset after finish"
assert not tab.preview_slot.isHidden(), "preview_slot should be restored after finish"
assert tab.hud_preview_label.isHidden(), "hud_preview_label should be hidden after finish"

# Second export
tab._rendering = True
tab._render_start = time.monotonic()
tab._render_total = 500
tab._on_render_progress(completed=50, total=500, elapsed=1.2, fps=41.6, hud_state={"ts": 1.66, "frame_idx": 49})
stats_text2 = tab.lbl_stats.text()
print(f"Second export stats: {stats_text2}")
assert "FPS: 41.6" in stats_text2
assert "Frame: 50 / 500" in stats_text2

tab._on_cancel()
assert not tab._rendering, "Should not be rendering after cancel"
print("Second export & Cancel lifecycle: PASS")

print("\n===============================================================================")
print("ALL PREVIEW & PROGRESS LIFECYCLE CHECKS: PASS!")
print("===============================================================================")
