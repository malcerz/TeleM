"""Short real NVIDIA Native export through the GUI controller (same path as the Export button).

Usage:
    python tools/nvidia_short_real_export.py OUT_DIR [--start S] [--frames N]

Loads D:\\GoPro\\2026-08-31\\GX010239.MP4 + 2026-10-20_15-04-03.fit (the golden-frame
fixture pairing), exports N frames from frame S with encoder "nv", writes the render
stats (FPS) to OUT_DIR/export_stats.json and leaves the MP4 in OUT_DIR.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(r"C:\_DEV\SportCamHUD")
sys.path.insert(0, str(PROJECT_ROOT))

VIDEO = r"C:\_DEV\SportCamHUD\Raporty\CPU_4K_DIAGNOSTICS_20261029\source_0deg.mp4"
FIT = r"D:\GoPro\2026-10-13_15-02-49.fit"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--start", type=int, default=3536)
    ap.add_argument("--frames", type=int, default=150)
    ap.add_argument("--encoder", default="nv", help="nv (default) or intel: control run of the Intel backend")
    ap.add_argument("--nvidia-quality", default=None, help="Fast (P1) / Balanced (P3) / Quality (P5, default)")
    ap.add_argument("--legacy-desc-abi", action="store_true",
                    help="A/B only: feed a pre-2026-10-29 DLL (800-byte TelemIndicatorDesc). New fields are "
                         "appended at struct ends, so the first 800 bytes keep the old layout.")
    args = ap.parse_args()
    if args.legacy_desc_abi:
        import ctypes
        import src.ffmpeg.nvidia_config as nc
        orig_load = nc.load_native_pipeline

        def load_legacy(*a, **kw):
            dll = orig_load(*a, **kw)
            orig_set = dll.telem_nvenc_set_indicators

            def set_indicators(handle, arr, count):
                stride = ctypes.sizeof(nc.TelemIndicatorDesc)
                raw = ctypes.string_at(ctypes.addressof(arr), stride * count)
                packed = b"".join(raw[i * stride:i * stride + 800] for i in range(count))
                buf = ctypes.create_string_buffer(packed, len(packed))
                return orig_set(handle, ctypes.cast(buf, ctypes.POINTER(nc.TelemIndicatorDesc)), count)

            dll.telem_nvenc_set_indicators = set_indicators
            return dll

        nc.load_native_pipeline = load_legacy
        import src.ffmpeg.nvidia_native_exporter as nexp
        nexp.load_native_pipeline = load_legacy
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = (args.out_dir / "nvidia_short_export.mp4").resolve()

    from PySide6.QtWidgets import QApplication
    from src.gui.qt.controller import AppController
    from src.gui.qt.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    ctrl = AppController()
    import os
    ctrl.render_threads = int(os.environ.get("CPU_HUD_BENCH_WORKERS", "15"))
    win = MainWindow()
    win.set_controller(ctrl)
    ctrl._on_files_selected([VIDEO], "", FIT)
    t0 = time.time()
    while time.time() - t0 < 120:
        app.processEvents()
        time.sleep(0.05)
        if ctrl.export_readiness_state()[0] == "ready":
            break
    print(f"[SHORT EXPORT] readiness={ctrl.export_readiness_state()}", flush=True)

    result: dict = {}

    def on_finished(stats, output):
        result["stats"] = stats
        result["output"] = str(output)

    def on_error(msg):
        result["error"] = str(msg)

    ctrl.signals.sig_render_finished.connect(on_finished)
    ctrl.signals.sig_error.connect(on_error)
    options = {
        "encoder": args.encoder,
        "resolution": "source",
        "rotation": "auto",
        "update_rate": "Full",
        "bitrate": "40M",
        "output": str(out_mp4),
        "start_frame": args.start,
        "max_frames": args.frames,
    }
    if args.encoder == "nv":
        options["nvidia_backend"] = "native_d3d11"
        if args.nvidia_quality:
            options["nvidia_quality"] = args.nvidia_quality
    t_start = time.time()
    ctrl.signals.sig_render_requested.emit(options)
    while time.time() - t_start < 900 and not result:
        app.processEvents()
        time.sleep(0.05)
    result["wall_s"] = round(time.time() - t_start, 2)
    result["options"] = options

    def _jsonable(v):
        try:
            json.dumps(v)
            return v
        except TypeError:
            return str(v)

    stats = result.get("stats")
    if isinstance(stats, dict):
        result["stats"] = {k: _jsonable(v) for k, v in stats.items()}
    (args.out_dir / "export_stats.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[SHORT EXPORT] done: {json.dumps(result)[:2000]}", flush=True)
    return 0 if "error" not in result and out_mp4.exists() else 1


if __name__ == "__main__":
    sys.exit(main())




