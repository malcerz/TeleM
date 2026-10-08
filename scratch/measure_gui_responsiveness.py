import sys
import time
import os
import shutil
from pathlib import Path
import numpy as np

sys.path.insert(0, r"C:\_DEV\BikeRideHUD-main-new")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from src.gui.qt.main_window import MainWindow
from src.gui.qt.controller import AppController
from src.gui.qt.signals import get_signals

def clear_caches():
    print("Clearing specific media caches for GX010349, GX010350, GX010354...")
    cache_dir = Path(r"C:\Users\Malcerz\AppData\Local\BikeRideHUD\cache\media")
    if cache_dir.exists():
        for name in ["GX010349", "GX010350", "GX010354"]:
            for d in cache_dir.glob(f"{name}*"):
                if d.is_dir():
                    shutil.rmtree(d, ignore_errors=True)
                    
    render_prep_dir = Path(r"C:\_DEV\BikeRideHUD-main-new\cache\render_telemetry")
    if render_prep_dir.exists():
        shutil.rmtree(render_prep_dir, ignore_errors=True)

def run_measurement(mode="cold"):
    print(f"\n==========================================")
    print(f"  RUNNING REAL GUI MEASUREMENT: MODE={mode.upper()}")
    print(f"==========================================")
    
    if mode == "cold":
        clear_caches()

    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
        
    win = MainWindow()
    ctrl = AppController()
    win.set_controller(ctrl)
    
    t0 = time.perf_counter()
    
    # Event loop stall measurement
    heartbeat_interval_ms = 16.0  # ~60 Hz heartbeat
    last_tick = time.perf_counter()
    stalls_ms = []
    
    def tick():
        nonlocal last_tick
        now = time.perf_counter()
        elapsed_ms = (now - last_tick) * 1000.0
        stall_ms = max(0.0, elapsed_ms - heartbeat_interval_ms)
        stalls_ms.append(stall_ms)
        if stall_ms > 100.0:
            print(f"  [HEARTBEAT STALL >100ms] stall={stall_ms:.1f}ms at t={(now - t0)*1000.0:.1f}ms")
        last_tick = now

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(int(heartbeat_interval_ms))

    # Trackers
    first_frame_ms = None
    gpmf_ready_ms = None
    fit_ready_ms = None
    full_hud_ready_ms = None
    
    def on_video_info(info):
        nonlocal first_frame_ms
        if first_frame_ms is None:
            first_frame_ms = (time.perf_counter() - t0) * 1000.0
            print(f"  [SIGNAL] First frame ready: {first_frame_ms:.1f} ms")
            
    def on_data_streams(streams):
        nonlocal full_hud_ready_ms
        if full_hud_ready_ms is None:
            full_hud_ready_ms = (time.perf_counter() - t0) * 1000.0
            print(f"  [SIGNAL] Data streams (FULL HUD) ready: {full_hud_ready_ms:.1f} ms")
            QTimer.singleShot(2500, quit_app)

    def on_telemetry_status(payload):
        nonlocal fit_ready_ms
        st = payload.get("status", "")
        if "Gotowy" in st or "Sukces" in st or "Zakończono" in st:
            if fit_ready_ms is None:
                fit_ready_ms = (time.perf_counter() - t0) * 1000.0
                print(f"  [SIGNAL] FIT ready: {fit_ready_ms:.1f} ms")
                
    def on_progress(pct, msg):
        nonlocal gpmf_ready_ms
        if "Gotowe" in msg or pct == 100:
            if gpmf_ready_ms is None:
                gpmf_ready_ms = (time.perf_counter() - t0) * 1000.0
                print(f"  [SIGNAL] GPMF ready (100%): {gpmf_ready_ms:.1f} ms")

    sigs = get_signals()
    sigs.sig_video_info_ready.connect(on_video_info)
    sigs.sig_data_streams_ready.connect(on_data_streams)
    sigs.sig_remote_telemetry_status.connect(on_telemetry_status)
    sigs.sig_progress.connect(on_progress)
    
    def quit_app():
        print(f"  [INFO] Auto-quitting after measurement.")
        app.quit()

    paths = [
        r"F:\GoPro\2026-10-07\GX010349.MP4",
        r"F:\GoPro\2026-10-07\GX010350.MP4",
        r"F:\GoPro\2026-10-07\GX010354.MP4"
    ]
    
    print("  Emitting sig_files_selected...")
    sigs.sig_files_selected.emit(paths, "", "")
    
    # Fallback timeout
    quit_timer = QTimer()
    quit_timer.timeout.connect(quit_app)
    quit_timer.setSingleShot(True)
    quit_timer.start(25000 if mode == "cold" else 15000)
    
    app.exec()
    timer.stop()

    # Calculate statistics
    stalls_arr = np.array(stalls_ms, dtype=np.float64) if stalls_ms else np.zeros(1)
    max_stall = float(np.max(stalls_arr))
    p95_stall = float(np.percentile(stalls_arr, 95))
    p99_stall = float(np.percentile(stalls_arr, 99))
    stalls_over_100 = int(np.sum(stalls_arr > 100.0))

    print("\n---------------- RESULTS ----------------")
    print(f"MODE:                        {mode.upper()}")
    print(f"CLICK_TO_FIRST_FRAME_MS:     {first_frame_ms}")
    print(f"CLICK_TO_GPMF_READY_MS:      {gpmf_ready_ms}")
    print(f"CLICK_TO_FIT_READY_MS:       {fit_ready_ms}")
    print(f"CLICK_TO_FULL_HUD_READY_MS:  {full_hud_ready_ms}")
    print(f"MAX_EVENT_LOOP_STALL_MS:     {max_stall:.1f}")
    print(f"P95_EVENT_LOOP_STALL_MS:     {p95_stall:.1f}")
    print(f"P99_EVENT_LOOP_STALL_MS:     {p99_stall:.1f}")
    print(f"STALL_COUNT_OVER_100MS:      {stalls_over_100}")
    print("-----------------------------------------\n")
    
    return {
        "mode": mode,
        "first_frame_ms": first_frame_ms,
        "gpmf_ready_ms": gpmf_ready_ms,
        "fit_ready_ms": fit_ready_ms,
        "full_hud_ready_ms": full_hud_ready_ms,
        "max_stall": max_stall,
        "p95_stall": p95_stall,
        "p99_stall": p99_stall,
        "stalls_over_100": stalls_over_100,
    }

if __name__ == "__main__":
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else "cold"
    run_measurement(mode_arg)
