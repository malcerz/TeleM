"""Visible Garmin Battery frame-0/startup and range-label audit."""
import os, sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("QT_QPA_PLATFORM", None)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt
from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
import src.gui.qt._mixins.preview_mixin as preview
import src.indicators.compositor as compositor
import src.indicators.bar as bar

OUT = Path("D:/TeleM_live_acceptance/garmin_battery_startup_range")
OUT.mkdir(parents=True, exist_ok=True)
KEY = "fit_garmin_battery_percent_text"
app = QApplication([]); controller = AppController(); window = MainWindow()
window.setWindowFlag(Qt.WindowStaysOnTopHint, True); window.set_controller(controller); window.showMaximized()
controller.get_project_layout_path = lambda: OUT / "project.layout.json"
rows=[]; latest={}; range_calls=[]
orig=preview.prepare_overlay_frame_data; orig_r=compositor.render_value_indicator
orig_fmt=bar._fmt_number
def obs_fmt(value, decimals):
    if float(value) in (0.0, 100.0, 95.95092365714285):
        range_calls.append((float(value), int(decimals)))
    return orig_fmt(value, decimals)
bar._fmt_number=obs_fmt
def obs_prepare(**kw):
    d=orig(**kw); val=d.get("extra_indicators",{}).get(KEY)
    latest.update(target_dt=str(kw.get("target_dt")), frame_data=None if val is None else val[0], extra=val)
    return d
def obs_render(*a,**kw):
    if len(a)>5 and a[4]==KEY: latest.update(compositor_value=a[5], formatted=kw.get("formatted_val"))
    return orig_r(*a,**kw)
preview.prepare_overlay_frame_data=obs_prepare; compositor.render_value_indicator=obs_render
def capture(label):
    row=dict(label=label, latest=latest, range_calls=range_calls[-40:], global_time=controller.last_preview_ts, visible=window.isVisible())
    rows.append(row); window.grab().save(str(OUT/f"{label}.png"));
    (OUT/"trace.json").write_text(json.dumps(rows,indent=2,default=str),encoding="utf-8"); print("AUDIT",json.dumps(row,default=str),flush=True)
def finish():
    controller._on_playback_stop(); capture("finished")
    if controller.mpv_player: controller.mpv_player.terminate(); controller.mpv_player=None
    controller.media_player.stop(); app.quit()
def poll():
    if not controller.video_timeline or not controller.telemetry.fit_data:
        QTimer.singleShot(500,poll); return
    controller._on_stream_clicked(KEY)
    controller.layout["indicators"][KEY].update(
        form="bar", bar_style="segments", decimals=2,
        show_min=True, show_max=True, show_range_labels=True,
        min_val=0.0, max_val=100.0, unit="%",
    )
    controller._clear_caches()
    # Explicitly seek to exact project start and capture immediately after the
    # normal preview refresh, without play/pause or another FIT load.
    controller._on_seek_changed(0.0)
    QTimer.singleShot(1200, lambda: (capture("frame0"), capture("frame1"), finish()))
QTimer.singleShot(500,lambda: controller.signals.sig_files_selected.emit(
    ["D:/GoPro/2026-09-02/GX010246.MP4"],"","D:/GoPro/2026-09-02/Poranna_jazda_na_rowerze.fit"))
QTimer.singleShot(2500,poll); QTimer.singleShot(120000,app.quit); app.exec()
