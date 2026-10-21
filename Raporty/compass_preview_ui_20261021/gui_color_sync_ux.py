"""Real-GUI checks for the color swatch and the empty-Preview click (ETAP D).

Isolated APPDATA/LOCALAPPDATA + temp base_dir; the user's files are only read.
QColorDialog.getColor is replaced by a scripted answer (OK with a colour or
Cancel) because a modal dialog cannot be driven offscreen; one real, non-modal
QColorDialog is opened only for the screenshot.

Usage: python gui_color_sync_ux.py <out_dir>
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="color_sync_ux_"))
os.environ["APPDATA"] = str(TMP / "appdata")
os.environ["LOCALAPPDATA"] = str(TMP / "localappdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QColorDialog  # noqa: E402

VIDEO = r"F:\GoPro\2026-10-16\GX010380.MP4"
FIT = r"F:\GoPro\2026-10-16\2026-10-16_06-22-14.fit"


def pump(app, s):
    end = time.perf_counter() + s
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    base = TMP / "base"
    base.mkdir()
    shutil.copy2(ROOT / "def_layout.json", base / "def_layout.json")
    app = QApplication.instance() or QApplication(sys.argv)

    from src.gui.qt.controller import AppController
    from src.gui.qt.main_window import MainWindow
    from src.gui.qt.signals import get_signals
    import src.gui.qt.widgets.property_editor as pe_mod

    def make():
        ctl = AppController()
        ctl.base_dir = base
        ctl._startup_preset_path = ""
        ctl._load_startup_preset()
        win = MainWindow()
        win.resize(1700, 1000)
        win.set_controller(ctl)
        win.show()
        ctl._on_files_selected([VIDEO], "", FIT)
        t0 = time.perf_counter()
        while not getattr(ctl, "project_ready", False):
            app.processEvents()
            time.sleep(0.01)
            if time.perf_counter() - t0 > 180:
                raise TimeoutError
        pump(app, 1.5)
        return ctl, win

    sig = get_signals()
    frames: list = []
    sig.sig_preview_frame_ready.connect(lambda img: frames.append(img))
    offset_sets: list = []
    sig.sig_sync_offset_set.connect(lambda v: offset_sets.append(v))

    ctl, win = make()
    res: dict = {"color": {}, "sync": {}}
    cmp = lambda: ctl.layout["indicators"]["compass"]  # noqa: E731

    # ── Colour swatch ──────────────────────────────────────────────────
    ctl._on_stream_clicked("compass")
    pump(app, 0.5)
    pe = win._project_tab.property_editor
    edit = pe._field_widgets["compass_needle_color"]
    swatch = pe._field_rows["compass_needle_color"].findChild(pe_mod.ColorSwatch)
    res["color"]["dots_button_present"] = any(
        b.text() == "..." for b in pe._field_rows["compass_needle_color"].findChildren(pe_mod.QPushButton))
    res["color"]["initial_model"] = cmp().get("compass_needle_color")

    answers = []
    orig_get = QColorDialog.getColor
    QColorDialog.getColor = staticmethod(lambda *a, **k: answers.pop(0))
    try:
        # OK with a colour
        answers.append(QColor("#33CC99"))
        n = len(frames)
        QTest.mouseClick(swatch, Qt.LeftButton, Qt.NoModifier, swatch.rect().center())
        pump(app, 1.0)
        res["color"]["pick_ok"] = {"hex": edit.text(), "swatch": swatch.color_name,
                                   "model": cmp().get("compass_needle_color"),
                                   "preview_rerendered": len(frames) > n}
        # Cancel
        answers.append(QColor())
        QTest.mouseClick(swatch, Qt.LeftButton, Qt.NoModifier, swatch.rect().center())
        pump(app, 0.5)
        res["color"]["cancel"] = {"hex": edit.text(), "model": cmp().get("compass_needle_color")}
    finally:
        QColorDialog.getColor = orig_get
    # Manual HEX
    edit.setText("#FF8800")
    pump(app, 0.5)
    res["color"]["manual_hex"] = {"swatch": swatch.color_name, "model": cmp().get("compass_needle_color")}
    # Invalid HEX
    edit.setText("#12XY9")
    pump(app, 0.3)
    invalid_model = cmp().get("compass_needle_color")
    edit.editingFinished.emit()
    pump(app, 0.3)
    res["color"]["invalid_hex"] = {"model_while_invalid": invalid_model, "hex_after_finish": edit.text(),
                                   "swatch": swatch.color_name}
    pe.grab().save(str(out / "ux_property_editor_color_swatch.png"))
    dlg = QColorDialog(QColor(swatch.color_name))
    dlg.setOption(QColorDialog.DontUseNativeDialog, True)
    dlg.show()
    pump(app, 0.3)
    dlg.grab().save(str(out / "ux_color_dialog.png"))
    dlg.close()

    # ── Empty-Preview click → Synchronizacja telemetrii ─────────────────
    vp = win.preview
    target = vp.stacked_widget.currentWidget()
    res["sync"]["preview_widget"] = type(target).__name__
    pump(app, 0.5)
    bboxes = dict(vp._bboxes)
    ow, oh = vp._original_size
    vrect = vp.get_video_rect()

    def to_widget(nx, ny):
        return QPoint(int(vrect.x() + nx / 100.0 * vrect.width()), int(vrect.y() + ny / 100.0 * vrect.height()))

    def empty_point():
        for ny in range(5, 96, 5):
            for nx in range(5, 96, 5):
                if vp._hit_test(nx, ny) is None:
                    return nx, ny
        return None

    win.activateWindow()
    win.raise_()
    pump(app, 0.3)
    sync_value_before = pe.sync_panel.spin.value()
    nx, ny = empty_point()
    offset_sets.clear()
    QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, to_widget(nx, ny))
    pump(app, 0.5)
    res["sync"]["empty_click"] = {
        "point_norm": [nx, ny], "selected_key": ctl._selected_stream_key,
        "sync_panel_visible": pe.sync_panel.isVisible(),
        "offset_has_focus": pe.sync_panel.spin.hasFocus() or pe.sync_panel.spin.lineEdit().hasFocus(),
        "window_focus_widget": type(win.focusWidget()).__name__ if win.focusWidget() else None,
        "window_focus_is_offset": win.focusWidget() in (pe.sync_panel.spin, pe.sync_panel.spin.lineEdit()),
        "offset_text_selected": pe.sync_panel.spin.lineEdit().selectedText(),
        "offset_before": sync_value_before, "offset_after": pe.sync_panel.spin.value(),
        "offset_set_signals": list(offset_sets),
    }
    win.grab().save(str(out / "ux_sync_after_empty_click.png"))

    # click on the compass → compass selected (indicator selection intact)
    key = "compass"
    bx, by, bw, bh = bboxes[key]
    cxn, cyn = (bx + bw / 2) / ow * 100.0, (by + bh / 2) / oh * 100.0
    QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, to_widget(cxn, cyn))
    pump(app, 0.5)
    res["sync"]["indicator_click"] = {"selected_key": ctl._selected_stream_key,
                                      "property_editor_key": pe._current_key,
                                      "sync_panel_visible": pe.sync_panel.isVisible()}
    # drag the compass by +3 % x
    x0 = cmp()["x"]
    QTest.mousePress(target, Qt.LeftButton, Qt.NoModifier, to_widget(cxn, cyn))
    for k in range(1, 7):
        QTest.mouseMove(target, to_widget(cxn - 0.5 * k, cyn))
        pump(app, 0.05)
    QTest.mouseRelease(target, Qt.LeftButton, Qt.NoModifier, to_widget(cxn - 3.0, cyn))
    pump(app, 0.5)
    res["sync"]["drag"] = {"x_before": x0, "x_after": cmp()["x"], "selected_key": ctl._selected_stream_key}
    # click inside the black margin of the scaled preview
    margin = None
    if vrect.x() > 2:
        margin = QPoint(max(1, vrect.x() // 2), target.height() // 2)
    elif vrect.y() > 2:
        margin = QPoint(target.width() // 2, max(1, vrect.y() // 2))
    if margin is not None:
        QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, margin)
        pump(app, 0.5)
        res["sync"]["margin_click"] = {"selected_key": ctl._selected_stream_key,
                                       "sync_panel_visible": pe.sync_panel.isVisible(),
                                       "offset_after": pe.sync_panel.spin.value()}
    else:
        res["sync"]["margin_click"] = "NOT TESTED (no margin at this window size)"

    # ── Persist + restart ───────────────────────────────────────────────
    win._settings_tab.btn_save_settings.click()
    pump(app, 0.5)
    win.close()
    pump(app, 0.3)
    ctl2, win2 = make()
    res["color"]["after_restart_model"] = ctl2.layout["indicators"]["compass"].get("compass_needle_color")
    res["color"]["saved_json"] = json.loads((base / "def_layout.json").read_text(encoding="utf-8"))["indicators"]["compass"].get("compass_needle_color")
    win2.close()

    c, s_ = res["color"], res["sync"]
    checks = {
        "no_dots_button": not c["dots_button_present"],
        "pick_ok": c["pick_ok"]["model"] == "#33CC99" and c["pick_ok"]["swatch"] == "#33CC99" and c["pick_ok"]["preview_rerendered"],
        "cancel_no_change": c["cancel"]["model"] == "#33CC99",
        "manual_hex": c["manual_hex"]["model"] == "#FF8800" and c["manual_hex"]["swatch"] == "#FF8800",
        "invalid_hex_rejected": c["invalid_hex"]["model_while_invalid"] == "#FF8800" and c["invalid_hex"]["hex_after_finish"] == "#FF8800",
        "persisted": c["after_restart_model"] == "#FF8800" and c["saved_json"] == "#FF8800",
        "empty_click_sync": s_["empty_click"]["sync_panel_visible"] and (s_["empty_click"]["offset_has_focus"] or s_["empty_click"]["window_focus_is_offset"]) and s_["empty_click"]["selected_key"] == "",
        "offset_unchanged": s_["empty_click"]["offset_before"] == s_["empty_click"]["offset_after"] and not s_["empty_click"]["offset_set_signals"],
        "indicator_click": s_["indicator_click"]["selected_key"] == "compass" and s_["indicator_click"]["property_editor_key"] == "compass",
        "drag": s_["drag"]["x_after"] < s_["drag"]["x_before"],
    }
    if isinstance(s_["margin_click"], dict):
        checks["margin_click_sync"] = s_["margin_click"]["sync_panel_visible"] and s_["margin_click"]["selected_key"] == ""
    res["checks"] = checks
    (out / "ux_checks.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(json.dumps(res, indent=1, default=str))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
