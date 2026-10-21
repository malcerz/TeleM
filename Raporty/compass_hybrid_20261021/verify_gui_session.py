"""Verification of GUI session for Hybrid Compass (Section 15 of user specification).

Tests:
1. Open GX010380.MP4 + FIT.
2. Wait for project_ready.
3. Without pressing Play, verify heading at 0s.
4. Seek to 10s, 30s, 60s, 79s, 120s, and back to 0s, measuring seek and HUD render times.
5. Re-open to verify warm cache performance.
6. Test switching source to gpmf.
"""
from __future__ import annotations

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime, timezone

# Ensure offscreen Qt platform
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow

VIDEO_PATH = r"F:\GoPro\2026-10-16\GX010380.MP4"
FIT_PATH = r"F:\GoPro\2026-10-16\2026-10-16_06-22-14.fit"
OUT_JSON = ROOT / "Raporty" / "compass_hybrid_20261021" / "gui_session_results.json"


def process_qt_events(app: QApplication, duration_s: float = 0.1) -> None:
    start = time.perf_counter()
    while time.perf_counter() - start < duration_s:
        app.processEvents()
        time.sleep(0.01)


def wait_for_project_ready(controller: AppController, app: QApplication, timeout_s: float = 60.0) -> float:
    start = time.perf_counter()
    while not getattr(controller, "project_ready", False):
        if time.perf_counter() - start > timeout_s:
            raise TimeoutError(f"Project failed to become ready within {timeout_s}s")
        app.processEvents()
        time.sleep(0.05)
    return time.perf_counter() - start


def run_gui_verification():
    app = QApplication.instance() or QApplication(sys.argv)

    results: dict = {
        "video": VIDEO_PATH,
        "fit": FIT_PATH,
        "cold_load": {},
        "warm_load": {},
        "seek_measurements": [],
        "source_switch": {},
    }

    print("[GUI Test] Initializing AppController & MainWindow...", flush=True)
    controller = AppController()
    window = MainWindow()
    window.set_controller(controller)

    preset_path = str(ROOT / "Raporty" / "compass_hybrid_20261021" / "layout_fit.json")
    controller._startup_preset_path = preset_path
    cfg = json.loads(Path(preset_path).read_text(encoding="utf-8"))["indicators"]["compass"]

    # 1. COLD LOAD (or using existing orientation cache)
    print(f"[GUI Test] Step 1: Loading video {VIDEO_PATH} and FIT...", flush=True)
    t0 = time.perf_counter()
    controller._on_files_selected([VIDEO_PATH], "", FIT_PATH)
    load_time_1 = wait_for_project_ready(controller, app, timeout_s=90.0)
    process_qt_events(app, 0.5)

    print(f"[GUI Test] Project ready in {load_time_1:.2f}s", flush=True)
    results["cold_load"]["load_seconds"] = round(load_time_1, 2)
    results["cold_load"]["compass_status"] = controller.telemetry._compass_status
    results["cold_load"]["has_result"] = controller.telemetry._compass_result is not None
    if controller.telemetry._compass_result:
        diag = controller.telemetry._compass_result.diagnostics
        results["cold_load"]["reference_source"] = diag.get("reference_source")
        results["cold_load"]["method"] = diag.get("clips", [{}])[0].get("method")
        results["cold_load"]["cache_hit"] = diag.get("clips", [{}])[0].get("cache_hit")
        results["cold_load"]["prepare_seconds"] = diag.get("prepare_seconds")

    # 2. CHECK HEADING IN FRAME 0 WITHOUT PLAY
    is_playing = getattr(controller, "is_playing", False)
    assert not is_playing, "Playback should NOT be running!"
    print(f"[GUI Test] Verified is_playing == {is_playing} (no Play clicked)", flush=True)

    # 3. SEEK MEASUREMENTS: 0s, 10s, 30s, 60s, 79s, 120s, 0s
    seek_targets = [0.0, 10.0, 30.0, 60.0, 79.0, 120.0, 0.0]
    for target in seek_targets:
        t_seek_start = time.perf_counter()
        info = controller._resolve_preview_time(target)
        target_dt = info.get("absolute_dt")
        heading_val = controller.telemetry.resolve_value(
            "heading", target_dt, indicator_key="compass", indicator_config=cfg
        )
        seek_elapsed_ms = (time.perf_counter() - t_seek_start) * 1000.0

        t_render_start = time.perf_counter()
        controller._render_preview_sync(target)
        render_elapsed_ms = (time.perf_counter() - t_render_start) * 1000.0

        meas = {
            "target_s": target,
            "heading_deg": round(float(heading_val), 2) if heading_val is not None else None,
            "resolve_ms": round(seek_elapsed_ms, 2),
            "hud_render_ms": round(render_elapsed_ms, 2),
            "target_dt": target_dt.isoformat() if target_dt else None,
        }
        results["seek_measurements"].append(meas)
        print(f"  Seek {target:>5.1f}s -> Heading: {meas['heading_deg']}°, resolve: {seek_elapsed_ms:.2f}ms, HUD render: {render_elapsed_ms:.2f}ms", flush=True)

    # 4. SECOND START (WARM CACHE)
    print("[GUI Test] Step 4: Testing second load (warm cache)...", flush=True)
    controller.clear_project()
    process_qt_events(app, 0.2)
    controller._on_files_selected([VIDEO_PATH], "", FIT_PATH)
    load_time_2 = wait_for_project_ready(controller, app, timeout_s=90.0)
    process_qt_events(app, 0.5)

    print(f"[GUI Test] Second load ready in {load_time_2:.2f}s", flush=True)
    results["warm_load"]["load_seconds"] = round(load_time_2, 2)
    if controller.telemetry._compass_result:
        diag = controller.telemetry._compass_result.diagnostics
        results["warm_load"]["cache_hit"] = diag.get("clips", [{}])[0].get("cache_hit")
        results["warm_load"]["prepare_seconds"] = diag.get("prepare_seconds")

    # 5. SWITCH TO GPMF SOURCE
    print("[GUI Test] Step 5: Testing reference source switch to gpmf...", flush=True)
    cfg["compass_reference_source"] = "gpmf"
    controller.telemetry.invalidate_compass()
    t_switch_start = time.perf_counter()
    controller.telemetry.prepare_compass(cfg)
    switch_elapsed = time.perf_counter() - t_switch_start

    info0 = controller._resolve_preview_time(0.0)
    h0_gpmf = controller.telemetry.resolve_value(
        "heading", info0.get("absolute_dt"), indicator_key="compass", indicator_config=cfg
    )
    results["source_switch"]["switch_seconds"] = round(switch_elapsed, 3)
    results["source_switch"]["reference_source"] = controller.telemetry._compass_result.diagnostics.get("reference_source")
    results["source_switch"]["heading_frame_0"] = round(float(h0_gpmf), 2) if h0_gpmf is not None else None
    print(f"  Switched to GPMF in {switch_elapsed:.3f}s -> Heading at 0s: {results['source_switch']['heading_frame_0']}°", flush=True)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[GUI Test] Results saved to {OUT_JSON}", flush=True)


if __name__ == "__main__":
    run_gui_verification()
