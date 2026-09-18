"""Run one production RenderTab export for the NVIDIA performance truth run.

This is benchmark orchestration only.  It instantiates the same QApplication,
AppController, MainWindow and RenderTab used by ``BikeRideHUD.py`` and presses
the real GUI export button after loading the canonical dataset.  It does not
implement or bypass a renderer.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

# The helper lives under scratch; make the repository root importable exactly
# as the canonical ``BikeRideHUD.py`` launcher does.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
from src.gui.qt.signals import get_signals


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("legacy_cuda", "native_d3d11"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--frames", type=int, default=1131)
    parser.add_argument("--layout", default="def_layout.json")
    parser.add_argument("--video", default="Video/GX020079.MP4")
    parser.add_argument("--fit", default="Video/GX020079.fit")
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--rotation", default="auto", choices=("auto", "0", "90", "180", "270"))
    parser.add_argument("--timeseries", default="", help="optional CSV path for GUI progress FPS samples")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[2]
    video_path = (base_dir / args.video).resolve() if not Path(args.video).is_absolute() else Path(args.video).resolve()
    fit_path = (base_dir / args.fit).resolve() if not Path(args.fit).is_absolute() else Path(args.fit).resolve()
    layout_path = Path(args.layout).resolve()
    output_path = Path(args.output).resolve()
    result_path = Path(args.result).resolve()
    timeseries_path = Path(args.timeseries).resolve() if args.timeseries else None
    result_path.parent.mkdir(parents=True, exist_ok=True)

    # Both backends receive the same explicit frame range.  The two variables
    # are consumed by existing stream/native dispatch code and are not a
    # renderer change.
    os.environ["TELEM_MAX_FRAMES"] = str(max(1, int(args.frames)))
    os.environ["TELEM_AUTONOMOUS_NATIVE_GUI_MAX_FRAMES"] = str(max(1, int(args.frames)))

    result: dict[str, object] = {
        "backend": args.backend,
        "video": str(video_path),
        "fit": str(fit_path),
        "layout": str(layout_path),
        "output": str(output_path),
        "requested_frames": int(args.frames),
        "process_start_epoch": time.time(),
        "process_start_perf": time.perf_counter(),
        "render_click_perf": None,
        "render_finished_perf": None,
        "app_exit_perf": None,
        "finished_signal_path": None,
        "error": None,
        "status": "starting",
    }
    progress_rows: list[dict[str, object]] = []

    app = QApplication(sys.argv)
    app.setApplicationName("BikeRideHUD")
    controller = AppController()
    window = MainWindow()
    window.set_controller(controller)
    window.showMaximized()
    try:
        window.check_mpv_availability()
    except Exception as exc:
        print(f"[GUI PERF] mpv availability check warning: {exc!r}", flush=True)

    signals = get_signals()
    started = False
    finished = False

    def write_result() -> None:
        result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    def close_later() -> None:
        try:
            window.close()
        except Exception:
            app.quit()

    def on_error(message: str) -> None:
        nonlocal finished
        if finished:
            return
        result["status"] = "error"
        result["error"] = str(message)
        print(f"[GUI PERF] render error: {message}", flush=True)
        finished = True
        QTimer.singleShot(500, close_later)

    def on_finished(_stats: object, final_path: str) -> None:
        nonlocal finished
        if finished:
            return
        result["status"] = "finished"
        result["render_finished_perf"] = time.perf_counter()
        result["finished_signal_path"] = str(final_path)
        print(f"[GUI PERF] render finished: {final_path}", flush=True)
        finished = True
        # Let the final mux/rename and GUI state settle before recording the
        # process wall-time endpoint.
        QTimer.singleShot(1000, close_later)

    def on_render_progress(completed: int, total: int, elapsed: float, fps: float, hud_state: object) -> None:
        state = hud_state if isinstance(hud_state, dict) else {}
        progress_rows.append({
            "sample_perf": time.perf_counter(),
            "since_click_s": (time.perf_counter() - float(result["render_click_perf"])) if result.get("render_click_perf") else 0.0,
            "completed": int(completed or 0),
            "total": int(total or 0),
            "elapsed_s": float(elapsed or 0.0),
            "fps": float(fps or 0.0),
            "phase": state.get("phase", ""),
            "backend": state.get("backend", ""),
            "role": state.get("role", ""),
        })

    def configure_and_click() -> None:
        nonlocal started
        if started or finished:
            return
        rt = window._render_tab
        # The button is enabled while the Load tab is still initializing.
        # Require the same project readiness state used by the canonical GUI
        # autonomous path so the click cannot race file/telemetry loading.
        if (
            not window.isVisible()
            or not rt.btn_render.isEnabled()
            or not getattr(controller, "video_paths", None)
            or not getattr(controller, "video_timeline", None)
            or float(getattr(controller, "video_duration_s", 0.0) or 0.0) <= 0.0
            or not getattr(getattr(controller, "telemetry", None), "fit_data", None)
        ):
            return
        started = True
        try:
            if layout_path.is_file():
                controller.layout = json.loads(layout_path.read_text(encoding="utf-8"))
                controller._user_preset_path = str(layout_path)
                if getattr(controller, "layout_mgr", None) is not None:
                    controller.layout_mgr.layout = controller.layout
            rt.cmb_encoder.setCurrentText("nv")
            idx = rt.cmb_nvidia_backend.findData(args.backend)
            if idx >= 0:
                rt.cmb_nvidia_backend.setCurrentIndex(idx)
            rt.cmb_nvidia_codec.setCurrentText("HEVC")
            rt.cmb_nvidia_quality.setCurrentText("Fast")
            rt.cmb_resolution.setCurrentText("4k")
            rt.cmb_rotation.setCurrentText(args.rotation)
            rt.cmb_update_rate.setCurrentText("Full")
            rt.cmb_hud_resolution.setCurrentText("Auto")
            rt.edit_bitrate.setText("40M")
            rt.chk_compression_analysis.setChecked(False)
            rt.chk_hud_preview.setChecked(False)
            rt.edit_output.setText(str(output_path))
            rt._user_edited_output = True
            result["render_click_perf"] = time.perf_counter()
            result["status"] = "rendering"
            print(
                f"[GUI PERF] pressing RenderTab EKSPORTUJ backend={args.backend} "
                f"frames={args.frames} output={output_path}",
                flush=True,
            )
            rt.btn_render.click()
        except Exception as exc:
            on_error(f"configure/click failed: {type(exc).__name__}: {exc}")

    def on_data_ready(*_args: object) -> None:
        print("[GUI PERF] telemetry/data ready", flush=True)
        QTimer.singleShot(250, configure_and_click)

    signals.sig_data_streams_ready.connect(on_data_ready)
    signals.sig_render_finished.connect(on_finished)
    signals.sig_error.connect(on_error)
    signals.sig_render_progress.connect(on_render_progress)

    # Load exactly as the normal GUI Load tab does.
    QTimer.singleShot(500, lambda: signals.sig_files_selected.emit(
        [str(video_path)], "", str(fit_path)
    ))

    readiness_timer = QTimer(window)
    readiness_timer.setInterval(250)
    readiness_timer.timeout.connect(configure_and_click)
    readiness_timer.start()

    # A failed load must not leave an unattended GUI process running.
    QTimer.singleShot(max(1, int(args.timeout_sec)) * 1000, lambda: on_error(f"GUI benchmark timeout ({int(args.timeout_sec)} s)"))
    app.exec()
    result["app_exit_perf"] = time.perf_counter()
    result["process_end_epoch"] = time.time()
    if result.get("status") == "starting":
        result["status"] = "closed_before_render"
    write_result()
    if timeseries_path:
        timeseries_path.parent.mkdir(parents=True, exist_ok=True)
        with timeseries_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=[
                "sample_perf", "since_click_s", "completed", "total", "elapsed_s",
                "fps", "phase", "backend", "role",
            ])
            writer.writeheader()
            writer.writerows(progress_rows)
    print(f"[GUI PERF] result={result_path}", flush=True)
    return 0 if result.get("status") == "finished" else 2


if __name__ == "__main__":
    raise SystemExit(main())
