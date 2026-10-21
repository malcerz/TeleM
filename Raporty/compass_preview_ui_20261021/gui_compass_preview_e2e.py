"""End-to-end reproduction of "compass frozen until ~2:44" in the real GUI.

User flow (no test override of the layout):
  1. start with a copy of the user's def_layout.json (standard mode saved),
  2. open GX010380.MP4 + FIT,
  3. select the compass and choose "GPS/FIT + IMU" in the Property Editor,
  4. open the same MP4 again (what the user does when re-checking material),
  5. seek with the real seek signal (no Play) and record what the compass
     renderer actually drew + the HUD frame that reached the Qt preview.

``--simulate-old`` reproduces the pre-fix project load (layout re-read from
disk) by disabling the session working layout, to show the reported state.

Usage: python gui_compass_preview_e2e.py <out_dir> [--simulate-old]
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="compass_e2e_"))
os.environ["APPDATA"] = str(TMP / "appdata")
os.environ["LOCALAPPDATA"] = str(TMP / "localappdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

VIDEO = r"F:\GoPro\2026-10-16\GX010380.MP4"
FIT = r"F:\GoPro\2026-10-16\2026-10-16_06-22-14.fit"
TIMES = [0, 10, 30, 60, 79, 120, 150, 163, 164, 165, 180]


def pump(app, s):
    end = time.perf_counter() + s
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    simulate_old = "--simulate-old" in sys.argv
    base = TMP / "base"
    base.mkdir()
    shutil.copy2(ROOT / "def_layout.json", base / "def_layout.json")

    app = QApplication.instance() or QApplication(sys.argv)
    import src.indicators.gauge as gauge
    import src.gui.qt._mixins.project_mixin as pm
    if simulate_old:
        pm._working_layout_copy = lambda layout: None
    drawn: list = []
    orig = gauge._render_compass_indicator

    def spy(canvas_w, canvas_h, layout, font_path, key, value, unit, label, cfg, *a, **kw):
        drawn.append(None if (value is None or cfg.get("_compass_missing")) else float(value))
        return orig(canvas_w, canvas_h, layout, font_path, key, value, unit, label, cfg, *a, **kw)

    gauge._render_compass_indicator = spy

    from src.gui.qt.controller import AppController
    from src.gui.qt.main_window import MainWindow
    from src.gui.qt.signals import get_signals
    ctl = AppController()
    ctl.base_dir = base
    ctl._startup_preset_path = ""
    ctl._load_startup_preset()
    win = MainWindow()
    win.resize(1600, 1000)
    win.set_controller(ctl)
    win.show()
    sig = get_signals()
    frames: list = []
    sig.sig_preview_frame_ready.connect(lambda img: frames.append(img))

    def load():
        ctl._on_files_selected([VIDEO], "", FIT)
        t0 = time.perf_counter()
        while not getattr(ctl, "project_ready", False):
            app.processEvents()
            time.sleep(0.01)
            if time.perf_counter() - t0 > 180:
                raise TimeoutError
        pump(app, 1.0)
        return time.perf_counter() - t0

    load()
    saved_mode = ctl.layout["indicators"]["compass"].get("compass_heading_mode", "<missing>")
    ctl._on_stream_clicked("compass")
    pump(app, 0.3)
    pe = win._project_tab.property_editor
    w = pe._field_widgets["compass_heading_mode"]
    w.setCurrentIndex(w.findData("gps_imu"))
    pump(app, 2.5)
    mode_after_edit = ctl.layout["indicators"]["compass"].get("compass_heading_mode")

    ctl.clear_project()
    pump(app, 0.3)
    load_s = load()
    mode_after_reopen = ctl.layout["indicators"]["compass"].get("compass_heading_mode", "<missing → standard>")
    assert not getattr(ctl, "_playing", False)

    rows = []
    for t in TIMES:
        drawn.clear()
        n = len(frames)
        sig.sig_seek_changed.emit(float(t))
        t0 = time.perf_counter()
        while (len(frames) == n or not drawn) and time.perf_counter() - t0 < 10:
            app.processEvents()
            time.sleep(0.005)
        pump(app, 0.15)
        img = frames[-1] if frames else None
        png = None
        if img is not None and hasattr(img, "save"):
            png = out / f"preview_{'old' if simulate_old else 'new'}_t{t:03d}.png"
            img.save(str(png))
        rows.append({"t": t, "drawn_heading": drawn[-1] if drawn else "NOT_RENDERED",
                     "frame_png": str(png.name) if png else None})
        print(rows[-1], flush=True)
    res = {
        "simulate_old_project_load": simulate_old,
        "mode_in_saved_layout": saved_mode,
        "mode_after_gui_edit": mode_after_edit,
        "mode_after_reopen": mode_after_reopen,
        "reopen_load_seconds": round(load_s, 2),
        "compass_status": getattr(ctl.telemetry, "_compass_status", None),
        "playing": bool(getattr(ctl, "_playing", False)),
        "rows": rows,
    }
    (out / f"e2e_{'old' if simulate_old else 'new'}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}), flush=True)
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
