"""Timeline of a real MP4 open in the GUI: progress, ready, HUD frames, overlay.

Records (t since file selection): sig_progress, project load state, every
preview frame (with the share of non-transparent HUD pixels), map/compass
signals and, when present, sig_hud_preparation events + overlay visibility.

Usage: python gui_load_timeline.py <out_json> [--layout PATH] [--no-fit]
       [--screens DIR] [--switch-to PATH]   (second MP4 opened mid-load)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="load_timeline_"))
os.environ["APPDATA"] = str(TMP / "appdata")
os.environ["LOCALAPPDATA"] = str(TMP / "localappdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

VIDEO = r"F:\GoPro\2026-10-16\GX010380.MP4"
FIT = r"F:\GoPro\2026-10-16\2026-10-16_06-22-14.fit"


def hud_coverage(img) -> float:
    try:
        from PySide6.QtGui import QImage
        if not isinstance(img, QImage):
            img = img.toImage()
        img = img.convertToFormat(QImage.Format_RGBA8888)
        import numpy as np
        arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=img.sizeInBytes()).reshape(img.height(), img.bytesPerLine())
        a = arr[:, 3: img.width() * 4: 4]
        return float((a > 0).mean())
    except Exception:
        return -1.0


def grab_window(win):
    """Window grab + the mpv-mode top-level HUD window painted at its place."""
    from PySide6.QtGui import QPainter
    from PySide6.QtCore import QPoint
    img = win.grab()
    vp = win.preview
    if vp.is_using_mpv() and vp._hud_alive() and vp.isVisible() and vp.hud_overlay.isVisible():
        hud = vp.hud_overlay
        hud.resize(vp.stacked_widget.size())
        layer = hud.grab()
        pos = vp.stacked_widget.mapTo(win, QPoint(0, 0))
        painter = QPainter(img)
        painter.drawPixmap(pos, layer)
        painter.end()
    return img


def main() -> int:
    out = Path(sys.argv[1])
    layout_src = Path(sys.argv[sys.argv.index("--layout") + 1]) if "--layout" in sys.argv else ROOT / "def_layout.json"
    fit = "" if "--no-fit" in sys.argv else FIT
    screens = Path(sys.argv[sys.argv.index("--screens") + 1]) if "--screens" in sys.argv else None
    switch_to = sys.argv[sys.argv.index("--switch-to") + 1] if "--switch-to" in sys.argv else None
    base = TMP / "base"
    base.mkdir()
    shutil.copy2(layout_src, base / "def_layout.json")
    app = QApplication.instance() or QApplication(sys.argv)
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
    t0 = [time.perf_counter()]
    ev: list = []
    now = lambda: round(time.perf_counter() - t0[0], 3)  # noqa: E731
    sig.sig_progress.connect(lambda p, m: ev.append({"t": now(), "ev": "progress", "pct": p, "msg": m}))
    sig.sig_project_load_state.connect(lambda d: ev.append({"t": now(), "ev": "load_state", "state": d.get("state"), "gen": d.get("generation")}))
    sig.sig_preview_frame_ready.connect(lambda img: ev.append({"t": now(), "ev": "frame", "hud_cov": round(hud_coverage(img), 4)}))
    sig.sig_map_ready.connect(lambda: ev.append({"t": now(), "ev": "map_ready"}))
    sig.sig_compass_prepared.connect(lambda tok: ev.append({"t": now(), "ev": "compass_prepared"}))
    if hasattr(sig, "sig_hud_preparation"):
        sig.sig_hud_preparation.connect(lambda d: ev.append({"t": now(), "ev": "hud_prep", **{k: v for k, v in d.items() if k != "stages"},
                                                              "stages": [(s["key"], s["state"]) for s in d.get("stages", [])]}))
    shots = []
    shots_tags: set = set()

    def overlay_visible():
        vp = win.preview
        st = getattr(vp, "_preparing_state", None)
        return bool(st and st.get("active"))

    fake_map = sys.argv[sys.argv.index("--fake-map") + 1] if "--fake-map" in sys.argv else None
    if fake_map:
        # Scripted route prefetch (network outcome is not reproducible):
        # real manager callbacks/signals, scripted tile counts and result.
        import threading as _th
        from src.gui.map_prefetch import MapBackgroundPrefetchManager
        mgr = MapBackgroundPrefetchManager.get_instance()
        state = {"active": False}
        mgr.is_active = lambda: state["active"]

        def fake_schedule(**kw):
            state["active"] = True

            def run():
                for cur in (0, 10, 20, 30):
                    mgr._on_progress_change(cur, 50)
                    mgr._update_status(f"Mapa: przygotowywanie {cur}/50")
                    time.sleep(0.4)
                if fake_map == "error":
                    state["active"] = False
                    mgr._update_status("Mapa: błąd pobierania kafelków (HTTP 503)")
                elif fake_map == "ok":
                    mgr._on_progress_change(50, 50)
                    state["active"] = False
                    mgr._update_status("Mapa: gotowa")
                # "slow": stays active -> 20 s HUD wait limit
            _th.Thread(target=run, daemon=True).start()
            return True
        mgr.schedule_prefetch = fake_schedule
    t0[0] = time.perf_counter()
    ctl._on_files_selected([VIDEO], "", fit)
    if "--clear-mid" in sys.argv:
        end = time.perf_counter() + 1.0
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.005)
        ev.append({"t": now(), "ev": "clear_project"})
        ctl.clear_project()
        end = time.perf_counter() + 8.0
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.005)
        res = {"scenario": "clear_mid_load", "overlay_visible_end": overlay_visible(), "project_ready": ctl.project_ready,
               "events": ev}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
        print(json.dumps({k: v for k, v in res.items() if k != "events"}), flush=True)
        return 0
    if switch_to:
        end = time.perf_counter() + 0.4
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.005)
        ev.append({"t": now(), "ev": "switch_project", "to": switch_to})
        ctl._on_files_selected([switch_to], "", "")
    deadline = time.perf_counter() + 240
    last_vis = None
    shot_ready = False
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)
        vis = overlay_visible()
        if vis != last_vis:
            ev.append({"t": now(), "ev": "overlay_visible", "value": vis})
            if screens is not None:
                screens.mkdir(parents=True, exist_ok=True)
                p = screens / f"overlay_{'on' if vis else 'off'}_{len(shots)}.png"
                grab_window(win).save(str(p))
                shots.append(p.name)
            last_vis = vis
        if screens is not None and vis and getattr(ctl, "project_ready", False) and "ready_preparing" not in shots_tags:
            shots_tags.add("ready_preparing")
            end = time.perf_counter() + 0.25
            while time.perf_counter() < end:
                app.processEvents()
                time.sleep(0.005)
            if overlay_visible():
                p = screens / "hud_preparing_project_tab.png"
                grab_window(win).save(str(p))
                shots.append(p.name)
                ev.append({"t": now(), "ev": "screenshot", "file": p.name})
        if getattr(ctl, "project_ready", False) and not vis and any(e["ev"] == "frame" for e in ev):
            if not shot_ready:
                end = time.perf_counter() + 3.0
                while time.perf_counter() < end:
                    app.processEvents()
                    time.sleep(0.005)
                    if overlay_visible():
                        break
                if not overlay_visible():
                    shot_ready = True
                    if screens is not None:
                        p = screens / "hud_ready_project_tab.png"
                        grab_window(win).save(str(p))
                        shots.append(p.name)
                    break
    if "--late-fit" in sys.argv:
        ev.append({"t": now(), "ev": "late_fit_attach"})
        late_t = now()
        ctl.late_attach_telemetry(FIT)
        if screens is not None:
            end = time.perf_counter() + 0.1
            while time.perf_counter() < end:
                app.processEvents()
                time.sleep(0.005)
            p = screens / "late_fit_preparing.png"
            grab_window(win).save(str(p))
            shots.append(p.name)
        deadline = time.perf_counter() + 60
        seen_on = False
        while time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)
            vis = overlay_visible()
            if vis != last_vis:
                ev.append({"t": now(), "ev": "overlay_visible", "value": vis})
                last_vis = vis
            seen_on = seen_on or vis
            if seen_on and not vis:
                break
    ready_t = next((e["t"] for e in ev if e["ev"] == "load_state" and e["state"] == "ready"), None)
    first_hud = next((e["t"] for e in ev if e["ev"] == "frame" and e["hud_cov"] > 0.001), None)
    hidden_t = next((e["t"] for e in reversed(ev) if e["ev"] == "overlay_visible" and e["value"] is False), None)
    warm = None
    if "--twice" in sys.argv:
        # Same session, same cache dirs: the second open is the warm path.
        ctl.clear_project()
        end = time.perf_counter() + 0.5
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.005)
        mark = len(ev)
        ev.append({"t": now(), "ev": "second_open"})
        t_open = time.perf_counter()
        ctl._on_files_selected([VIDEO], "", fit)
        seen_on, t_ready, t_hidden = False, None, None
        while time.perf_counter() - t_open < 120:
            app.processEvents()
            time.sleep(0.005)
            if t_ready is None and getattr(ctl, "project_ready", False):
                t_ready = time.perf_counter() - t_open
            vis = overlay_visible()
            seen_on = seen_on or vis
            if seen_on and not vis and t_ready is not None:
                t_hidden = time.perf_counter() - t_open
                break
        warm = {"ready_s": round(t_ready, 3) if t_ready else None,
                "overlay_hidden_s": round(t_hidden, 3) if t_hidden else None}
    final_prep = next((e for e in reversed(ev) if e["ev"] == "hud_prep"), None)
    res = {"layout": str(layout_src), "fit": fit, "ready_s": ready_t, "first_hud_frame_s": first_hud,
           "final_state": final_prep and {k: final_prep.get(k) for k in ("state", "generation", "errors", "stages", "cancelled")},
           "status_bar": win.status_label.text(), "warm_second_open": warm,
           "gap_ready_to_hud_s": (round(first_hud - ready_t, 3) if (ready_t is not None and first_hud is not None) else None),
           "overlay_hidden_s": hidden_t, "screens": shots, "events": ev}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "events"}, default=str), flush=True)
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
