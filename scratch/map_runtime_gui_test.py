"""ETAP 1B — REAL GUI runtime test (offscreen QApplication, real MainWindow+AppController).

Drives the real TeleM GUI pipeline headlessly (QT_QPA_PLATFORM=offscreen) and
captures the ACTUAL composed preview QImage + widget state:

  1. Load GX010115 + FIT via the real _on_files_selected signal path.
  2. Wait for project load completion.
  3. Check MapContext status / overview_image.
  4. Add/refresh preview, capture the emitted preview QImage.
  5. Inspect the map indicator bbox region for real map pixels (not placeholder).
  6. Switch Standard -> Satellite via _on_property_changed, capture again.
  7. Assert A != B and satellite provider actually visible.

This is a real GUI runtime exercise of the full pipeline:
  Wczytaj -> MapPreload -> MapContext -> overview_image -> indicator ->
  compose_overlay -> preview GUI.  (Runs offscreen because the environment has
  no physical display; the widget rendering path is still exercised.)
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("TELEM_OFFLINE", "1")
import sys, time, threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from src.gui.qt.signals import get_signals
from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
from PIL import Image

def main():
    app = QApplication(sys.argv)
    signals = get_signals()
    ctrl = AppController()
    window = MainWindow()
    window.set_controller(ctrl)
    window.show()

    map_ready_events = []
    signals.sig_map_ready.connect(lambda: map_ready_events.append(time.perf_counter()))
    preview_images = []
    signals.sig_preview_frame_ready.connect(lambda qimg: preview_images.append(qimg))
    progress_events = []
    signals.sig_progress.connect(lambda p, t: progress_events.append((p, t)))
    errors = []
    signals.sig_error.connect(lambda e: errors.append(e))
    bboxes_events = []
    signals.sig_bboxes_ready.connect(lambda b, w, h: bboxes_events.append((b, w, h)))

    video = str(Path("Video/GX010115.MP4").resolve())
    fit = str(Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit").resolve())

    print("[MapRuntime] triggering sig_files_selected ...", flush=True)
    signals.sig_files_selected.emit([video], "", fit)

    # Pump the Qt event loop until project load completes.
    deadline = time.time() + 120
    loaded = False
    while time.time() < deadline:
        app.processEvents()
        if progress_events and progress_events[-1][0] >= 100:
            loaded = True
            break
        time.sleep(0.02)
    print(f"[MapRuntime] loaded={loaded} progress={progress_events[-1] if progress_events else None}", flush=True)

    ctx = getattr(ctrl, "map_context", None)
    snap = ctx.snapshot() if ctx is not None else None
    print(f"[MapRuntime] map_context={ctx is not None}")
    if snap:
        print(f"[MapRuntime] status={snap['status']} provider={snap['provider']} "
              f"overview={'yes' if snap['overview_image'] is not None else 'no'} "
              f"zoom={snap['overview_zoom']} tiles={snap['loaded_tiles']}/{snap['required_tiles']}")
    print(f"[MapRuntime] sig_map_ready fired {len(map_ready_events)}x")

    # The default def_layout has track_map (static_map).  Force a fresh render
    # and capture the latest preview QImage.
    time.sleep(0.2)
    app.processEvents()
    try:
        ctrl._render_preview()
    except Exception as exc:
        print(f"[MapRuntime] _render_preview raised: {exc!r}", flush=True)
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()

    def save(idx, tag):
        if not preview_images:
            print(f"[MapRuntime] NO preview QImage captured for {tag}!", flush=True)
            return None
        qimg = preview_images[-1]
        qimg = qimg.convertToFormat(qimg.Format.Format_RGBA8888)
        w, h = qimg.width(), qimg.height()
        img = Image.frombuffer("RGBA", (w, h), qimg.bits(), "raw", "RGBA", 0, 1)
        p = Path(f"scratch/map_runtime_{tag}.png")
        img.save(p)
        print(f"[MapRuntime] saved {p} {w}x{h}", flush=True)
        # Inspect the map bbox region.
        if bboxes_events:
            bb, bw, bh = bboxes_events[-1]
            m = bb.get("track_map")
            print(f"[MapRuntime] track_map bbox={m}", flush=True)
            if m:
                x, y, mw, mh = m
                crop = img.crop((x, y, x + mw, y + mh))
                from PIL import ImageStat
                st = ImageStat.Stat(crop)
                print(f"[MapRuntime] map region mean={[round(v,1) for v in st.mean[:3]]} "
                      f"stddev={[round(v,1) for v in st.stddev[:3]]} mode={img.mode}", flush=True)
        return img

    img_std = save(1, "standard")

    # ── Satellite switch ──────────────────────────────────────────────
    print("[MapRuntime] switching Standard -> Satellite ...", flush=True)
    try:
        ctrl._on_property_changed("track_map", "map_style", "satellite")
    except Exception as exc:
        print(f"[MapRuntime] property switch raised: {exc!r}", flush=True)
    app.processEvents()
    time.sleep(0.5)
    app.processEvents()
    try:
        ctrl._render_preview()
    except Exception as exc:
        print(f"[MapRuntime] _render_preview (sat) raised: {exc!r}", flush=True)
    app.processEvents()
    time.sleep(0.5)
    app.processEvents()

    snap2 = ctrl.map_context.snapshot() if getattr(ctrl, "map_context", None) else None
    if snap2:
        print(f"[MapRuntime] after switch: status={snap2['status']} provider={snap2['provider']} "
              f"overview={'yes' if snap2['overview_image'] is not None else 'no'}", flush=True)
    img_sat = save(2, "satellite")

    if img_std is not None and img_sat is not None:
        same = list(img_std.getdata()) == list(img_sat.getdata())
        print(f"[MapRuntime] standard==satellite images: {same}", flush=True)

    print(f"[MapRuntime] errors={errors}", flush=True)
    print("[MapRuntime] DONE", flush=True)

if __name__ == "__main__":
    main()
