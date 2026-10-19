"""Real Qt load-button/worker lifecycle with a tiny MP4 and no telemetry.

Decoder presentation, GPU work and map prefetch are excluded: this checks
project readiness and controls, not preview pixels or export performance.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "Raporty/gui_recovery_20261018/project_probe"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(ROOT / "scratch/project-probe-profile")
os.environ["LOCALAPPDATA"] = str(ROOT / "scratch/project-probe-local")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PySide6.QtTest import QTest, QSignalSpy
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication, QMessageBox
    from src.gui.qt.controller import AppController
    from src.gui.qt.main_window import MainWindow
    import src.gui.qt._mixins.project_mixin as loading
    ffmpeg = ROOT.parent / "SportCamHUD/runtime/common/ffmpeg/ffmpeg.exe"
    ffprobe = ffmpeg.with_name("ffprobe.exe")
    video = OUT / "tiny.mp4"
    subprocess.run([str(ffmpeg), "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x36:rate=10",
                    "-t", "0.3", "-c:v", "mpeg4", "-y", str(video)], check=True)
    loading.find_executable = lambda preferred, *_args: str(ffprobe if "ffprobe" in preferred else ffmpeg)
    loading._QT_MULTIMEDIA_AVAILABLE = False
    class ProbeController(AppController):
        def _setup_media_player(self): pass
        def _load_startup_preset(self): self.layout = {"global":{"font":"Arial"},"indicators":{}}
        def _load_or_generate_telemetry(self): pass
        def refresh_preview_geometry_and_hud(self): pass
        def _trigger_map_background_prefetch(self, **kwargs): pass
    app = QApplication.instance() or QApplication([])
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
    if font_path.is_file():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont("Segoe UI", 10))
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)
    ctrl = ProbeController(); ctrl.base_dir = OUT
    (OUT / "def_layout.json").write_text(json.dumps(ctrl.layout))
    win = MainWindow(); win.set_controller(ctrl); win.show()
    events = []
    ctrl.signals.sig_project_load_state.connect(lambda state: events.append(dict(state)))
    errors = QSignalSpy(ctrl.signals.sig_error)
    def wait(predicate):
        for _ in range(2000):
            QTest.qWait(10)
            if predicate(): return
        raise RuntimeError("Project lifecycle did not settle")
    assert not win.tabs.isTabEnabled(1)
    win.grab().save(str(OUT / "startup.png"))
    win._load_tab.set_video_paths([str(video)], start_search=False)
    QTest.mouseClick(win._load_tab.btn_load, Qt.LeftButton)
    assert not win.tabs.isTabEnabled(1)
    wait(lambda: win.tabs.isTabEnabled(1) and win.tabs.currentWidget() is win._project_tab)
    assert win.tabs.isTabEnabled(1) and win.tabs.currentWidget() is win._project_tab
    assert errors.count() == 0
    win.grab().save(str(OUT / "ready.png"))
    win._load_tab._on_clear()
    assert not ctrl.video_paths and not ctrl.project_ready and not win.tabs.isTabEnabled(1)
    win.grab().save(str(OUT / "cleared.png"))
    invalid = OUT / "invalid.mp4"; invalid.write_text("not a video")
    win._load_tab.set_video_paths([str(invalid)], start_search=False)
    win._load_tab._on_load()
    wait(lambda: bool(events) and events[-1]["state"] == "failed")
    assert not ctrl.project_ready and not win.tabs.isTabEnabled(1)
    assert win._load_tab.btn_load.isEnabled()
    assert all(win.tabs.isTabEnabled(i) for i in (0,2,3))
    result = dict(passed=True, events=events, invalid_errors=errors.count(),
                  final_tabs=[win.tabs.isTabEnabled(i) for i in range(4)],
                  exclusions=["GPU/decoder presentation", "telemetry extraction", "map prefetch", "export"])
    (OUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    ctrl._comp_worker_running = False
    win.close(); app.processEvents()
    print("PASS real Qt load button + real ffprobe: startup/ready/clear/invalid-video")


if __name__ == "__main__": main()
