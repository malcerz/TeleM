"""Real MainWindow/controller/decoder test with the user's cached video/FIT pair.

Run explicitly from the runtime root. Uses an isolated tile cache, never clears
the user's map cache, and does not save modified layout settings.
"""
from pathlib import Path
import hashlib
import inspect
import json
import os
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import numpy as np
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from src import moving_map, map_renderer
    from src.indicators import dispatcher
    from src.integrations.remote_cache import find_cached_video_telemetry
    from src.gui.qt.controller import AppController
    from src.gui.qt.main_window import MainWindow
    from src.indicators.availability import compute_indicator_availability
    moving_indicator_file = Path(inspect.getsourcefile(dispatcher._render_moving_map_indicator)).resolve()

    video = Path("D:/GoPro/GX010338.MP4")
    cached = find_cached_video_telemetry([video])
    if not video.exists() or cached is None:
        print("REAL_GUI=BLOCKED (video or its verified cached FIT unavailable)", flush=True)
        return 2
    fit = cached[2]
    out = ROOT / "scratch/preview_map_real_gui"
    out.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(tempfile.mkdtemp(prefix="telem-preview-map-"))
    init_cache = moving_map.TileCache.__init__
    moving_map.TileCache.__init__ = lambda self, cache_dir_arg=None: init_cache(self, cache_dir)
    moving_map.TileCache._mem.clear()
    moving_map.TileCache._mem_order.clear()
    moving_map._shared_cache = moving_map.TileCache(cache_dir)
    map_renderer.CACHE_DIR = cache_dir
    raw_download = moving_map._download_tile_raw
    static_download = map_renderer.download_tile
    phase = ["cold"]
    moving_map._download_tile_raw = lambda *args: None if phase[0] == "cold" else raw_download(*args)
    map_renderer.download_tile = lambda *args, **kwargs: static_download(*args, **dict(kwargs, download=False)) if phase[0] == "cold" else static_download(*args, **kwargs)
    rows = []
    tag = ["loading"]
    latest = {}
    original_coverage = moving_map.MovingMapRenderer.viewport_tile_coverage
    def coverage(self, *args):
        value = original_coverage(self, *args)
        latest["coverage"] = value
        return value
    moving_map.MovingMapRenderer.viewport_tile_coverage = coverage

    def wrap(original, form):
        def observed(*args, **kwargs):
            result = original(*args, **kwargs)
            image, x, y, _ = result
            if tag[0] != "loading":
                record = dict(tag=tag[0], form=form, coverage=latest.get("coverage"),
                              map_present=image is not None, track_present=False, marker_present=False,
                              x=x, y=y, size=image.size if image is not None else None)
                if image is not None:
                    rgb = np.asarray(image)[:,:,:3]
                    record["track_present"] = bool(((rgb[:,:,0] > 180) & (rgb[:,:,1] < 110) & (rgb[:,:,2] < 100)).any())
                    record["marker_present"] = bool((rgb.min(axis=2) > 240).any())
                    image.save(out / (tag[0] + "_map.png"))
                latest["map"] = record
            return result
        return observed
    dispatcher._render_moving_map_indicator = wrap(dispatcher._render_moving_map_indicator, "map")
    dispatcher._render_static_map_indicator = wrap(dispatcher._render_static_map_indicator, "static_map")
    app = QApplication(sys.argv)
    ctrl = AppController()
    window = MainWindow()
    window.set_controller(ctrl)
    window.showMaximized()
    emitted = [0]
    ctrl.signals.sig_preview_frame_ready.connect(lambda image: emitted.__setitem__(0, emitted[0]+1))
    evidence = dict(runtime_root=str(ctrl.base_dir), moving_map_file=str(moving_indicator_file),
                    moving_map_sha=hashlib.sha256(moving_indicator_file.read_bytes()).hexdigest(),
                    pid=os.getpid(), video=str(video), fit=str(fit), isolated_cache=str(cache_dir), rows=rows)
    points = [("frame_"+str(i), i/29.97) for i in (0,100,500,1000,2000)]
    state = dict(started=False, point=0, timeout=time.monotonic()+180, preview_before=0)
    code = [1]

    def save():
        (out / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    def finish(ok):
        from src.gui.map_viewport_prefetch import preview_viewport_prefetch
        evidence["prefetch_threads_started"] = preview_viewport_prefetch.threads_started
        evidence["result"] = "PASS" if ok else "FAIL"
        save()
        code[0] = 0 if ok else 1
        print("REAL_GUI="+evidence["result"], flush=True)
        if "--hold" not in sys.argv:
            window.close()

    def select_point():
        name, seconds = points[state["point"]]
        tag[0] = name
        latest.pop("map", None)
        state["preview_before"] = emitted[0]
        ctrl.signals.sig_seek_changed.emit(seconds)
        QTimer.singleShot(800, capture)

    def capture():
        record = dict(latest.get("map", {}))
        record["preview_emitted"] = emitted[0] > state["preview_before"]
        record["project_available"] = ctrl.layout.get("_indicator_availability",{}).get("track_map")
        rows.append(record)
        window.grab().save(str(out / (tag[0]+"_window.png")))
        window.preview.hud_overlay.grab().save(str(out / (tag[0]+"_hud_widget.png")))
        pixmap = window.preview.hud_overlay.hud_pixmap
        if pixmap is not None:
            pixmap.save(str(out / (tag[0]+"_hud_pixmap.png")))
        record["hud_widget_visible"] = window.preview.hud_overlay.isVisible()
        record["hud_pixmap_present"] = pixmap is not None and not pixmap.isNull()
        save()
        state["point"] += 1
        if state["point"] < len(points):
            select_point()
        elif phase[0] == "cold":
            def begin_warm():
                if "--hold" in sys.argv and not (out / "continue_warm").exists():
                    QTimer.singleShot(500, begin_warm)
                    return
                phase[0] = "warm"
                tag[0] = "warm"
                QTimer.singleShot(11000, warm)
            print("REAL_GUI=COLD_SEEK_COMPLETE", flush=True)
            QTimer.singleShot(500, begin_warm)
        else:
            finish(all(r.get("map_present") and r.get("track_present") and r.get("marker_present") and r.get("project_available") and r.get("preview_emitted") and r.get("hud_widget_visible") and r.get("hud_pixmap_present") for r in rows))

    def warm():
        ctrl._render_preview(ctrl.last_preview_ts)
        if latest.get("coverage", 0) < 1.0 and time.monotonic() < state["timeout"]:
            QTimer.singleShot(1000, warm)
            return
        points.append(("after_preload", ctrl.last_preview_ts))
        select_point()

    def poll():
        if time.monotonic() > state["timeout"]:
            finish(False)
            return
        if not state["started"] and ctrl.video_path and not ctrl._preview_telemetry_loading and ctrl.telemetry.fit_gps_track:
            state["started"] = True
            cfg = ctrl.layout["indicators"]["track_map"]
            evidence["original_map_config"] = dict(cfg)
            cfg.update(enabled=True, gps_source="auto")
            avail = compute_indicator_availability(ctrl.layout, telemetry=ctrl.telemetry)
            ctrl.layout["_indicator_availability"] = {k:v[0] for k,v in avail.items()}
            evidence["fps"] = ctrl.fps
            points[:] = [("frame_"+str(i), i/ctrl.fps) for i in (0,100,500,1000,2000)] + [("seek_"+str(p), ctrl.video_duration_s*p/100) for p in (0,25,50,75,10)]
            window.tabs.setCurrentWidget(window._project_tab)
            QTimer.singleShot(1000, select_point)
        elif not state["started"]:
            QTimer.singleShot(500, poll)

    ctrl._on_files_selected([str(video)], "", str(fit))
    QTimer.singleShot(500, poll)
    app.exec()
    return code[0]


if __name__ == "__main__":
    raise SystemExit(main())
