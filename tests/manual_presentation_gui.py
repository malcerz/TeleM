"""Visible production GUI audit. Artifacts go to D:, never user presets.

Run: python tests/manual_presentation_gui.py before|after
Wrappers observe real calls and pixels without replacing calculated values.
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop('QT_QPA_PLATFORM', None)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt
from PIL import ImageGrab
from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
import src.indicators.compositor as compositor
import src.gui.qt._mixins.preview_mixin as preview_module

STAGE = sys.argv[1] if len(sys.argv) > 1 else 'before'
OUT = Path('D:/TeleM_live_acceptance/presentation_architecture') / STAGE
OUT.mkdir(parents=True, exist_ok=True)
KEY = 'fit_garmin_battery_percent_text'
app = QApplication([])
controller = AppController()
window = MainWindow()
window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
window.set_controller(controller)
window.showMaximized()
controller.get_project_layout_path = lambda: OUT / 'audit.layout.json'
rows = []
latest = {}
accepted = 0
started = False
step = 0
start_wall = 0

original_value = compositor.render_value_indicator
def observe_value(*args, **kwargs):
    if len(args) > 5 and args[4] == KEY:
        latest.update(value=args[5], formatted=kwargs.get('formatted_val'))
    return original_value(*args, **kwargs)
compositor.render_value_indicator = observe_value
original_prepare = preview_module.prepare_overlay_frame_data
def observe_prepare(**kwargs):
    result = original_prepare(**kwargs)
    val = result['extra_indicators'].get(KEY)
    if val is not None:
        latest.update(target_dt=kwargs['target_dt'].isoformat(), frame_data=val[0],
                      controller_cfg=dict(controller.layout['indicators'][KEY]),
                      manager_has_layout=hasattr(controller.telemetry, 'layout'))
    return result
preview_module.prepare_overlay_frame_data = observe_prepare

def on_frame(qimg):
    global accepted
    accepted += 1
controller.signals.sig_preview_frame_ready.connect(on_frame)

def capture(label):
    row = dict(latest, label=label, wall=time.monotonic(), accepted=accepted,
               global_time=controller.last_preview_ts,
               video_time=controller.mpv_player.time_pos if controller.mpv_player else None,
               visible=window.isVisible(), qt_platform=app.platformName())
    rows.append(row)
    # Always save the actual visible Qt widget paint, including its HUD. A
    # minimized RDP desktop can make desktop BitBlt unavailable independently
    # of the normal windows-platform application rendering.
    window.grab().save(str(OUT / (label + '_window.png')))
    hud = getattr(getattr(window, 'preview', None), 'hud_overlay', None)
    if hud is not None and hud.isVisible():
        hud.grab().save(str(OUT / (label + '_hud.png')))
        row['hud_capture'] = 'PASS'
    else:
        row['hud_capture'] = 'NOT_VISIBLE'
    try:
        ImageGrab.grab().save(OUT / (label + '.png'))
        row['desktop_capture'] = 'PASS'
    except OSError as exc:
        row['desktop_capture'] = str(exc)
    (OUT / 'trace.json').write_text(json.dumps(rows, indent=2, default=str), encoding='utf-8')
    print('AUDIT', json.dumps(row, default=str), flush=True)

def finish():
    controller._on_playback_stop()
    capture('finished')
    controller._comp_worker_running = False
    if controller.mpv_player:
        controller.mpv_player.terminate()
        controller.mpv_player = None
    controller.media_player.stop()
    # The production MPV object uses native teardown; avoid running duplicate
    # widget cleanup against a terminated player after the audited window ends.
    app.quit()

def tick():
    global started, step, start_wall
    if not started:
        if not controller.telemetry.fit_data or not controller.video_timeline:
            return
        samples = controller.telemetry.fit_data.get('garmin_battery_percent', [])
        if not samples:
            return
        for cfg in controller.layout.get('indicators', {}).values():
            cfg['enabled'] = False
        cfg = controller.layout['indicators'][KEY]
        cfg.update(enabled=True, form='bar', bar_style='segments', decimals=2,
                   x=50, y=50, size=55, font_size=4, show_value=True,
                   show_label=True, show_units=True, unit='%', min_val=0, max_val=100)
        controller._cut_regions = []
        controller._clear_caches()
        controller._on_stream_clicked(KEY)
        # Use the first real run and its next change event; never assume
        # Battery levels or anchor from the last duplicate sample.
        base = samples[0][0]
        next_change = next((i for i in range(1, len(samples))
                            if samples[i][1] != samples[i - 1][1]), None)
        if next_change is None:
            print('AUDIT_NO_CHANGE_EVENT', flush=True)
            return
        transition_duration = (samples[next_change][0] - base).total_seconds()
        anchor = controller.video_timeline.clips[0].absolute_start_dt
        offset = (base.replace(tzinfo=None) - anchor.replace(tzinfo=None)).total_seconds()
        controller._audit_transition_start = offset
        controller._audit_transition_duration = transition_duration
        controller._on_seek_changed(max(0.0, offset + transition_duration * 0.1))
        QTimer.singleShot(1200, controller._on_playback_start)
        start_wall = time.monotonic()
        started = True
        print('AUDIT_START', offset, 'manager layout', hasattr(controller.telemetry, 'layout'), flush=True)
        return
    elapsed = time.monotonic() - start_wall
    if step < (7 if STAGE == 'before' else 12) and elapsed >= 2 * (step + 1):
        capture(f'play_{step:02d}')
        step += 1
    if STAGE == 'before' and elapsed > 15:
        timer.stop()
        finish()
    elif STAGE != 'before' and elapsed > 25:
        timer.stop()
        controller._on_playback_stop()
        run_checkpoints(0)

def run_checkpoints(index):
    fractions = [0, .1, .25, .5, .75, .9, 1]
    if index == len(fractions):
        controller._on_seek_changed(controller._audit_transition_start + controller._audit_transition_duration * .5)
        QTimer.singleShot(1200, lambda: property_check(0))
        return
    controller._on_seek_changed(controller._audit_transition_start + fractions[index] * controller._audit_transition_duration)
    QTimer.singleShot(1200, lambda: (capture(f'seek_{index}'), run_checkpoints(index + 1)))

def property_check(dp):
    if dp > 3:
        controller._on_playback_start()
        property_playback(0)
        return
    controller.signals.sig_property_changed.emit(KEY, 'decimals', dp)
    QTimer.singleShot(1200, lambda: (capture(f'property_{dp}'), property_check(dp + 1)))

def property_playback(dp):
    if dp > 3:
        finish()
        return
    controller.signals.sig_property_changed.emit(KEY, 'decimals', dp)
    QTimer.singleShot(2000, lambda: (capture(f'playing_property_{dp}'), property_playback(dp + 1)))

timer = QTimer()
timer.timeout.connect(tick)
timer.start(250)
QTimer.singleShot(500, lambda: controller.signals.sig_files_selected.emit(
    ['D:/GoPro/2026-09-02/GX010246.MP4'], '',
    'D:/GoPro/2026-09-02/Poranna_jazda_na_rowerze.fit'))
QTimer.singleShot(180000, app.quit)
app.exec()
