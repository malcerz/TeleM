"""Visible GUI smoke for GoPro Battery decimal property and ISO formatting."""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("QT_QPA_PLATFORM", None)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt
from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
import src.indicators.compositor as compositor

OUT = Path("D:/TeleM_live_acceptance/gopro_battery_iso_decimal")
OUT.mkdir(parents=True, exist_ok=True)
BAT = "fit_gopro_battery_text"
app = QApplication([])
controller = AppController()
window = MainWindow()
window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
window.set_controller(controller)
window.showMaximized()
controller.get_project_layout_path = lambda: OUT / "project.layout.json"
rows, latest, schema_seen = [], {}, {}
orig = compositor.render_value_indicator
def observe(*args, **kwargs):
    if len(args) > 5 and args[4] in (BAT, "iso_text"):
        latest[args[4]] = {"value": args[5], "formatted": kwargs.get("formatted_val")}
    return orig(*args, **kwargs)
compositor.render_value_indicator = observe
def on_ready(key, schema, values):
    if key in (BAT, "iso_text"):
        schema_seen[key] = {"fields": [f.name for f in schema],
                            "decimals_default": next((f.default for f in schema if f.name == "decimals"), None),
                            "decimals_label": next((f.label for f in schema if f.name == "decimals"), None)}
controller.signals.sig_properties_ready.connect(on_ready)
def capture(label):
    project_tab = getattr(window, "_project_tab", None)
    editor = getattr(project_tab, "property_editor", None)
    widget = getattr(editor, "_field_widgets", {}).get("decimals") if editor else None
    row = {"label": label, "schema": dict(schema_seen), "render": dict(latest),
           "editor_decimals": widget.value() if widget is not None else None,
           "visible": window.isVisible()}
    rows.append(row)
    window.grab().save(str(OUT / f"{label}.png"))
    (OUT / "trace.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print("GUI_AUDIT", json.dumps(row, default=str), flush=True)
def finish():
    capture("finished")
    if controller.mpv_player:
        controller.mpv_player.terminate(); controller.mpv_player = None
    controller.media_player.stop(); app.quit()
def run():
    if not controller.telemetry or not controller.video_timeline:
        QTimer.singleShot(500, run); return
    for cfg in controller.layout.get("indicators", {}).values(): cfg["enabled"] = False
    controller._on_stream_clicked(BAT)
    capture("battery_default")
    def battery_dp(dp):
        if dp > 3:
            # Emulate a newly added ISO indicator: no legacy precision key.
            controller.layout["indicators"].get("iso_text", {}).pop("decimals", None)
            controller.layout["indicators"].get("iso_text", {}).pop("decimal_places", None)
            controller._on_stream_clicked("iso_text")
            capture("iso_default")
            controller._on_seek_changed(30.0)
            QTimer.singleShot(1000, lambda: (capture("iso_seek"), finish()))
            return
        controller.signals.sig_property_changed.emit(BAT, "decimals", dp)
        QTimer.singleShot(700, lambda: (capture(f"battery_dp{dp}"), battery_dp(dp + 1)))
    battery_dp(0)
QTimer.singleShot(1000, lambda: controller.signals.sig_files_selected.emit(
    ["D:/GoPro/2026-09-02/GX010246.MP4"], "", "D:/GoPro/2026-09-02/Poranna_jazda_na_rowerze.fit"))
QTimer.singleShot(2500, run)
QTimer.singleShot(120000, app.quit)
app.exec()
