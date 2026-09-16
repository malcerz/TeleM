"""Visible production GUI startup trace for fit_gopro_battery_text.

Temporary audit harness for the startup-availability task.  It intentionally
uses the normal visible QApplication/AppController/MainWindow path and writes
only to D:.  Run with ``python tests/manual_gopro_battery_startup.py``.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
import src.gui.qt._mixins.preview_mixin as preview_module
import src.indicators.compositor as compositor

STAGE = sys.argv[1] if len(sys.argv) > 1 else "before"
OUT = Path("D:/TeleM_live_acceptance/gopro_battery_startup") / STAGE
OUT.mkdir(parents=True, exist_ok=True)
KEY = "fit_gopro_battery_text"
LIMIT = int(os.environ.get("GOPRO_TRACE_LIMIT", "150"))
VIDEO = "D:/GoPro/2026-09-02/GX010246.MP4"
FIT = "D:/GoPro/2026-09-02/Poranna_jazda_na_rowerze.fit"

app = QApplication([])
controller = AppController()
window = MainWindow()
window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
window.set_controller(controller)
window.showMaximized()

rows = []
latest = {}
accepted = 0
started = False
start_wall = 0.0
last_frame = -1

orig_prepare = preview_module.prepare_overlay_frame_data
def observe_prepare(**kwargs):
    result = orig_prepare(**kwargs)
    extra = (result or {}).get("extra_indicators", {})
    value = extra.get(KEY)
    latest.update(
        target_dt=kwargs.get("target_dt").isoformat() if kwargs.get("target_dt") else None,
        frame_data=value[0] if value is not None else None,
        extra=value,
        overlay_target_dt=(result or {}).get("target_dt"),
    )
    return result
preview_module.prepare_overlay_frame_data = observe_prepare

orig_render = compositor.render_value_indicator
def observe_render(*args, **kwargs):
    # dispatcher positional contract: ..., key, value, unit, label
    if len(args) >= 7 and args[4] == KEY:
        latest.update(compositor_value=args[5], formatted=kwargs.get("formatted_val"))
    return orig_render(*args, **kwargs)
compositor.render_value_indicator = observe_render

def on_frame(_qimg):
    global accepted, last_frame
    accepted += 1
    last_frame = accepted - 1
    if accepted <= LIMIT:
        capture(f"frame_{accepted - 1:04d}")

def capture(label):
    row = dict(latest, label=label, accepted=accepted, frame_index=last_frame,
               wall=time.monotonic(), global_time=controller.last_preview_ts,
               visible=window.isVisible(), qt_platform=app.platformName())
    try:
        row["video_time"] = controller.mpv_player.time_pos if controller.mpv_player else None
    except Exception:
        row["video_time"] = None
    try:
        window.grab().save(str(OUT / (label + "_window.png")))
        row["window_capture"] = "PASS"
    except Exception as exc:
        row["window_capture"] = str(exc)
    hud = getattr(getattr(window, "preview", None), "hud_overlay", None)
    if hud is not None and hud.isVisible():
        try:
            hud.grab().save(str(OUT / (label + "_hud.png")))
            row["hud_capture"] = "PASS"
        except Exception as exc:
            row["hud_capture"] = str(exc)
    else:
        row["hud_capture"] = "NOT_VISIBLE"
    rows.append(row)
    (OUT / "trace.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print("AUDIT", json.dumps(row, default=str), flush=True)

def begin():
    global started, start_wall
    if started or not controller.telemetry.fit_data or not controller.video_timeline:
        return
    samples = controller.telemetry.fit_data.get("gopro_battery", [])
    if not samples:
        print("AUDIT_NO_GOPRO_BATTERY", flush=True)
        return
    for cfg in controller.layout.get("indicators", {}).values():
        cfg["enabled"] = False
    controller._on_stream_clicked(KEY)
    cfg = controller.layout["indicators"][KEY]
    cfg.update(enabled=True, form="text", decimals=2, show_value=True,
               show_label=True, show_units=True, unit="%", x=50, y=50)
    controller._clear_caches()
    anchor = controller.video_timeline.clips[0].absolute_start_dt
    first = samples[0][0]
    latest.update(first_sample=first.isoformat(), video_start=anchor.isoformat(),
                  first_minus_video_s=(first.replace(tzinfo=None) - anchor.replace(tzinfo=None)).total_seconds(),
                  plan_ready=None, sample_count=len(samples))
    controller._on_seek_changed(0.0)
    QTimer.singleShot(1200, controller._on_playback_start)
    start_wall = time.monotonic()
    started = True
    print("AUDIT_START", json.dumps(latest, default=str), flush=True)

def finish():
    controller._on_playback_stop()
    capture("finished")
    try:
        if controller.mpv_player:
            controller.mpv_player.terminate()
            controller.mpv_player = None
        controller.media_player.stop()
    except Exception:
        pass
    app.quit()

timer = QTimer()
def tick():
    begin()
    if started and (accepted >= LIMIT or time.monotonic() - start_wall > 90):
        timer.stop()
        finish()
timer.timeout.connect(tick)
timer.start(250)
controller.signals.sig_preview_frame_ready.connect(on_frame)
QTimer.singleShot(500, lambda: controller.signals.sig_files_selected.emit([VIDEO], "", FIT))
QTimer.singleShot(180000, app.quit)
app.exec()
