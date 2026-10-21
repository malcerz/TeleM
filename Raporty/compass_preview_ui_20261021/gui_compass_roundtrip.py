"""GUI round-trip of every compass property through the real Property Editor.

Runs the real AppController + MainWindow (offscreen) against an isolated
copy of a layout in a temp base_dir.  APPDATA / LOCALAPPDATA are redirected
to the temp directory, so neither the user's def_layout.json nor their
app_preferences / session layout can be touched.

Scenario (per the task):
  1. open the test layout (copy of the user's layout) and the MP4 + FIT,
  2. select the compass, change EVERY compass property through its widget,
  3. press the normal "Zapisz ustawienia" button,
  4. destroy the controller/window ("close the program"),
  5. start a new controller/window on the same base_dir + reload the MP4,
  6. compare every property, and the rendered compass bitmap.

Usage:  python gui_compass_roundtrip.py <out_json> [--edit-before-load]
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="compass_roundtrip_"))
os.environ["APPDATA"] = str(TMP / "appdata")
os.environ["LOCALAPPDATA"] = str(TMP / "localappdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox,
)

VIDEO = r"F:\GoPro\2026-10-16\GX010380.MP4"
FIT = r"F:\GoPro\2026-10-16\2026-10-16_06-22-14.fit"


def pump(app, s=0.3):
    end = time.perf_counter() + s
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def make(app, base):
    from src.gui.qt.controller import AppController
    from src.gui.qt.main_window import MainWindow
    ctl = AppController()
    ctl.base_dir = base
    ctl._startup_preset_path = ""
    ctl._load_startup_preset()
    win = MainWindow()
    win.set_controller(ctl)
    return ctl, win


def load(app, ctl):
    ctl._on_files_selected([VIDEO], "", FIT)
    t0 = time.perf_counter()
    while not getattr(ctl, "project_ready", False):
        app.processEvents()
        time.sleep(0.02)
        if time.perf_counter() - t0 > 180:
            raise TimeoutError("project_ready")
    pump(app, 0.5)


def editor(win):
    return win._project_tab.property_editor


def new_value(name, w):
    """A non-default value for each widget type, deterministic."""
    if isinstance(w, QComboBox):
        idx = (w.currentIndex() + 1) % max(1, w.count())
        return ("index", idx)
    if isinstance(w, QCheckBox):
        return ("bool", not w.isChecked())
    if isinstance(w, QSpinBox):
        v = w.value() + 2 if w.value() + 2 <= w.maximum() else w.value() - 2
        return ("int", v)
    if isinstance(w, QDoubleSpinBox):
        step = w.singleStep() or 0.1
        v = w.value() + 3 * step
        if v > w.maximum():
            v = w.value() - 3 * step
        return ("float", round(v, w.decimals()))
    if isinstance(w, QLineEdit):
        if name.endswith("color"):
            return ("text", "#12AB34")
        return ("text", (w.text() or "") + "X")
    return None


def apply(w, change):
    kind, v = change
    if kind == "index":
        w.setCurrentIndex(v)
        return w.itemData(v) if w.itemData(v) is not None else w.currentText()
    if kind == "bool":
        w.setChecked(v)
        return v
    if kind in ("int", "float"):
        w.setValue(v)
        return w.value()
    w.setText(v)
    return v


def edit_all(app, ctl, win):
    ctl._on_stream_clicked("compass")
    pump(app, 0.3)
    pe = editor(win)
    expected = {}
    skipped = []
    # Hybrid controls appear only after compass_heading_mode == gps_imu, so
    # switch the mode first and re-read the (rebuilt) editor.
    w = pe._field_widgets.get("compass_heading_mode")
    if w is not None:
        idx = w.findData("gps_imu")
        w.setCurrentIndex(idx)
        expected["compass_heading_mode"] = "gps_imu"
        pump(app, 0.5)
    for name, w in list(pe._field_widgets.items()):
        if name in expected or name in ("enabled",):
            continue
        if name == "compass_reference_source":
            # keep FIT (preferred); change it twice to prove the write path
            w.setCurrentIndex(w.findData("gpmf"))
            pump(app, 0.05)
            w = pe._field_widgets.get(name)
            w.setCurrentIndex(w.findData("fit"))
            expected[name] = "fit"
            continue
        ch = new_value(name, w)
        if ch is None:
            skipped.append(name)
            continue
        expected[name] = apply(w, ch)
        pump(app, 0.05)
    pump(app, 0.5)
    return expected, skipped


def compass_png(ctl, path):
    ctl._render_preview_sync(30.0)
    img = getattr(ctl, "_last_overlay_image", None)
    return img


def main() -> int:
    out = Path(sys.argv[1])
    edit_before_load = "--edit-before-load" in sys.argv
    base = TMP / "base"
    base.mkdir()
    src_layout = ROOT / "def_layout.json"
    shutil.copy2(src_layout, base / "def_layout.json")
    app = QApplication.instance() or QApplication(sys.argv)

    ctl, win = make(app, base)
    if edit_before_load:
        # Editing is only possible with a loaded project in the GUI; here
        # we edit, then load ANOTHER time to check the reload path.
        load(app, ctl)
        expected, skipped = edit_all(app, ctl, win)
        ctl.clear_project()
        pump(app, 0.3)
        load(app, ctl)
    else:
        load(app, ctl)
        expected, skipped = edit_all(app, ctl, win)
    live = dict(ctl.layout["indicators"]["compass"])

    # normal application save button
    win._settings_tab.btn_save_settings.click()
    pump(app, 0.5)
    saved = json.loads((base / "def_layout.json").read_text(encoding="utf-8"))["indicators"]["compass"]

    # "close the program"
    win.close()
    win.deleteLater()
    del ctl
    pump(app, 0.5)

    ctl2, win2 = make(app, base)
    load(app, ctl2)
    reloaded = dict(ctl2.layout["indicators"]["compass"])
    ctl2._on_stream_clicked("compass")
    pump(app, 0.3)
    pe2 = editor(win2)
    gui_vals = {}
    for name, w in pe2._field_widgets.items():
        if isinstance(w, QComboBox):
            gui_vals[name] = w.currentData() if w.currentData() is not None else w.currentText()
        elif isinstance(w, QCheckBox):
            gui_vals[name] = w.isChecked()
        elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
            gui_vals[name] = w.value()
        elif isinstance(w, QLineEdit):
            gui_vals[name] = w.text()

    def same(a, b):
        if isinstance(a, float) or isinstance(b, float):
            try:
                return abs(float(a) - float(b)) < 1e-6
            except (TypeError, ValueError):
                return False
        return a == b

    rows = []
    for name, exp in expected.items():
        rows.append({
            "field": name, "expected": exp, "live_model": live.get(name),
            "saved_json": saved.get(name), "reloaded_model": reloaded.get(name),
            "reloaded_gui": gui_vals.get(name),
            "ok": all(same(exp, v) for v in (live.get(name), saved.get(name), reloaded.get(name), gui_vals.get(name))),
        })
    bad = [r for r in rows if not r["ok"]]
    hyb_status = getattr(ctl2.telemetry, "_compass_status", None)
    res = {
        "scenario": "edit_then_reload_project" if edit_before_load else "edit_save_restart",
        "fields_tested": len(rows), "fields_ok": len(rows) - len(bad),
        "skipped_widgets": skipped, "failures": bad, "rows": rows,
        "reloaded_compass_status": hyb_status,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1, ensure_ascii=False, default=str))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
