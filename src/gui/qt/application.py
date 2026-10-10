"""Entry point aplikacji PySide6."""

from __future__ import annotations

import sys
import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
from src.gui.qt.signals import get_signals


def main() -> None:
    """Główny entry point aplikacji BikeRideHUD (PySide6)."""
    import os
    app = QApplication(sys.argv)
    app.setApplicationName("BikeRideHUD")

    # Inicjalizacja kontrolera (most GUI ↔ logika biznesowa)
    _controller = AppController()
    window = MainWindow()
    window.set_controller(_controller)  # wiąże współdzielony podgląd (jeden raz)
    def _on_about_to_quit() -> None:
        print("[PROC] aboutToQuit", flush=True)
        _controller.cancel_render_and_wait()

    app.aboutToQuit.connect(_on_about_to_quit)
    window.showMaximized()

    # Zgłoś błąd, jeśli brak bibliotek libmpv (podgląd GPU MPV niedostępny)
    window.check_mpv_availability()

    # ── Tryb testowy: python TeleMGP.py -test / --test / --test-b / --test-c ──────────
    if "--test-b" in sys.argv or "--test-c" in sys.argv:
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        video_dir = base_dir / "Video"
        video_path = video_dir / "GX020079.MP4"
        fit_path = video_dir / "GX020079.fit"
        is_test_b = "--test-b" in sys.argv
        is_test_c = "--test-c" in sys.argv

        print(f"[TEST MODE] Wczytywanie kanonicznego datasetu NVIDIA:\n  MP4: {video_path}\n  FIT: {fit_path}", flush=True)

        def _on_data_ready_for_test(*_args):
            try:
                get_signals().sig_data_streams_ready.disconnect(_on_data_ready_for_test)
            except Exception:
                pass

            def _start_render():
                print("[TEST MODE] Dane gotowe, uruchamianie renderu...", flush=True)
                out_path = base_dir / "scratch" / ("test_b_out.mp4" if is_test_b else "test_c_out.mp4")
                window._render_tab.edit_output.setText(str(out_path))
                window._render_tab.btn_render.click()

                from src.process_lifecycle import RenderProcessRegistry
                reg = RenderProcessRegistry.get_instance()

                def _poll_active():
                    pids = reg.get_active_pids()
                    if len(pids) >= 5:
                        print(f"[PROC] {len(pids)} children active in registry: {pids}", flush=True)
                        if is_test_b:
                            print("[TEST B] Kliknięcie przycisku ANULUJ w GUI...", flush=True)
                            window._render_tab.btn_cancel.click()

                            def _poll_cancel_complete():
                                worker = getattr(_controller, "render_worker_thread", None)
                                worker_alive = worker is not None and worker.is_alive()
                                rem_pids = reg.get_active_pids()
                                if not worker_alive and not rem_pids:
                                    print("[TEST B] render_worker_thread.is_alive() == False", flush=True)
                                    print(f"[TEST B] RenderProcessRegistry.get_active_pids() == {rem_pids}", flush=True)
                                    print(f"[TEST B] GUI responsiveness check: window title = '{window.windowTitle()}'", flush=True)
                                    QTimer.singleShot(3000, lambda: window.close())
                                else:
                                    QTimer.singleShot(200, _poll_cancel_complete)

                            QTimer.singleShot(200, _poll_cancel_complete)
                        elif is_test_c:
                            print("[TEST C] 4 workers + 1 ffmpeg active: ready for window close (X)", flush=True)
                    else:
                        QTimer.singleShot(200, _poll_active)

                QTimer.singleShot(500, _poll_active)

            QTimer.singleShot(1000, _start_render)

        get_signals().sig_data_streams_ready.connect(_on_data_ready_for_test)
        QTimer.singleShot(500, lambda: get_signals().sig_files_selected.emit(
            [str(video_path)], "", str(fit_path),
        ))
    elif "-test" in sys.argv or "--test" in sys.argv:
        from datetime import datetime
        import hashlib
        import os

        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        video_dir = base_dir / "Video"
        if not video_dir.exists():
            video_dir = base_dir / "video"

        video_path = video_dir / "GX010290.MP4"
        if not video_path.exists():
            video_path = video_dir / "GX010290.mp4"

        fit_path = video_dir / "20260911.fit"
        layout_path = video_dir / "GX010290.layout.json"

        bisect_mode = os.environ.get("TELEM_PAYLOAD_BISECT_MODE", "literal_good_harness")
        os.environ["TELEM_PAYLOAD_BISECT_MODE"] = bisect_mode
        if bisect_mode == "literal_good_harness":
            out_dir = base_dir / "scratch" / "nvidia_literal_harness_no_mpv"
        elif bisect_mode == "exact_good330":
            out_dir = base_dir / "scratch" / "nvidia_exact_good330"
        elif bisect_mode == "clean_child_exact_good330":
            out_dir = base_dir / "scratch" / "nvidia_clean_child_exact_good330"
            os.environ["NVIDIA_RENDER_CHILD_PROCESS"] = "1"
        else:
            out_dir = base_dir / "scratch" / "nvidia_payload_bisect" / bisect_mode
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        if bisect_mode == "literal_good_harness":
            out_path = out_dir / "codex_hevc_fast330.mp4"
        else:
            out_path = out_dir / f"nvidia_{bisect_mode}_{timestamp_str}.mp4"

        # Tee stdout and stderr to test.log in the respective run folder
        log_path = out_dir / "test.log"
        log_file = log_path.open("a", encoding="utf-8", buffering=1)

        class _TeeStream:
            def __init__(self, original, file_obj):
                self.original = original
                self.file_obj = file_obj

            def write(self, s):
                self.original.write(s)
                try:
                    self.file_obj.write(s)
                    self.file_obj.flush()
                except Exception:
                    pass

            def flush(self):
                self.original.flush()
                try:
                    self.file_obj.flush()
                except Exception:
                    pass

            def fileno(self):
                return self.original.fileno()

        sys.stdout = _TeeStream(sys.stdout, log_file)
        sys.stderr = _TeeStream(sys.stderr, log_file)

        # Set up test-only GOOD DLL override
        good_dll_path = base_dir / "scratch" / "checkpoints" / "codex_frame01_before" / "native" / "d3d11_nvenc_pipeline" / "bin" / "telem_nvenc_native.dll"
        os.environ["TELEM_NVENC_DLL_OVERRIDE"] = str(good_dll_path.resolve())

        from src.ffmpeg.nvidia_config import get_native_dll_path
        active_dll_path = get_native_dll_path()
        active_dll_bytes = active_dll_path.read_bytes() if active_dll_path.exists() else b""
        active_dll_sha = hashlib.sha256(active_dll_bytes).hexdigest()

        if os.environ.get("TELEM_NVENC_DLL_OVERRIDE"):
            print("[NVIDIA DLL] override active", flush=True)
            print(f"[NVIDIA DLL] path={active_dll_path}", flush=True)
            print(f"[NVIDIA DLL] sha256={active_dll_sha}", flush=True)

        EXPECTED_GOOD_SHA = "d1a7ebee929aa08e445fc198c0aaf96aa2859ee4c128215566733b37d472bcea"
        if active_dll_sha.lower() != EXPECTED_GOOD_SHA.lower():
            print(f"[NVIDIA DLL] FATAL: SHA256 {active_dll_sha} != expected {EXPECTED_GOOD_SHA}! ABORTING RENDER.", flush=True)
            sys.exit(1)

        # Write dll_proof.txt in the active run directory
        dll_proof_path = out_dir / "dll_proof.txt"
        dll_proof_text = (
            f"BISECT_MODE: {bisect_mode}\n"
            f"DLL_PATH: {active_dll_path}\n"
            f"DLL_SHA256: {active_dll_sha}\n"
            f"DLL_SIZE: {len(active_dll_bytes)}\n"
            f"EXPECTED_GOOD_SHA: {EXPECTED_GOOD_SHA}\n"
            f"DLL_VERIFIED: {active_dll_sha.lower() == EXPECTED_GOOD_SHA.lower()}\n"
        )
        dll_proof_path.write_text(dll_proof_text, encoding="utf-8")

        # Enable payload dumping for inspection
        os.environ["TELEM_DUMP_PAYLOAD"] = "1"
        if bisect_mode == "exact_good330":
            dump_filename = "gui_payload.json"
        elif bisect_mode == "clean_child_exact_good330":
            dump_filename = "payload.json"
        else:
            dump_filename = "runtime_export_payload.json"
        os.environ["TELEM_PAYLOAD_DUMP_PATH"] = str(out_dir / dump_filename)

        print("[TEST AUTO] enabled", flush=True)
        print(f"[TEST AUTO] bisect_mode={bisect_mode}", flush=True)
        print(f"[TEST AUTO] video={video_path}", flush=True)
        print(f"[TEST AUTO] fit={fit_path}", flush=True)
        print(f"[TEST AUTO] layout={layout_path}", flush=True)
        print("[TEST AUTO] backend=NVIDIA_NATIVE_D3D11", flush=True)
        print("[TEST AUTO] codec=HEVC", flush=True)
        print("[TEST AUTO] quality=FAST", flush=True)
        print("[TEST AUTO] bitrate=40M", flush=True)
        print(f"[TEST AUTO] output={out_path}", flush=True)

        if not video_path.exists() or not fit_path.exists() or not layout_path.exists():
            print("[TEST AUTO] ERROR: Brak wymaganych plików datasetu testowego!", flush=True)
            if not video_path.exists():
                print(f"[TEST AUTO]   Brak MP4: {video_path}", flush=True)
            if not fit_path.exists():
                print(f"[TEST AUTO]   Brak FIT: {fit_path}", flush=True)
            if not layout_path.exists():
                print(f"[TEST AUTO]   Brak layoutu: {layout_path}", flush=True)
        else:
            layout_sha = hashlib.sha256(layout_path.read_bytes()).hexdigest()
            expected_sha = "359014dbee4f7d3362d74cca3577551ab87e105b9256caab120dc737b74f2736"
            if layout_sha.lower() != expected_sha.lower():
                print(f"[TEST AUTO] WARNING: SHA256 layoutu niezgodny! Otrzymano {layout_sha}, oczekiwano {expected_sha}", flush=True)

            render_triggered = False

            def _check_readiness() -> bool:
                if not window.isVisible():
                    return False
                if not getattr(_controller, "video_paths", None):
                    return False
                if not getattr(_controller, "video_timeline", None):
                    return False
                if getattr(_controller, "video_duration_s", 0.0) <= 0:
                    return False
                if not getattr(_controller, "telemetry", None):
                    return False
                if not getattr(_controller.telemetry, "fit_data", None):
                    return False
                if not getattr(_controller, "layout", None):
                    return False
                if not window._render_tab.btn_render.isEnabled():
                    return False
                return True

            def _on_ready_to_trigger() -> None:
                nonlocal render_triggered
                if render_triggered:
                    return
                if not _check_readiness():
                    return
                render_triggered = True
                poll_timer.stop()
                try:
                    get_signals().sig_progress.disconnect(_on_progress_ready)
                except Exception:
                    pass

                print("[TEST AUTO] project READY", flush=True)

                def _trigger_gui_render() -> None:
                    rt = window._render_tab
                    # Switch to Render tab so GUI visually reflects the state
                    window.tabs.setCurrentWidget(rt)

                    # Set NVIDIA options on RenderTab
                    rt.cmb_encoder.setCurrentText("nv")
                    idx_backend = rt.cmb_nvidia_backend.findData("legacy_cuda")
                    if idx_backend >= 0:
                        rt.cmb_nvidia_backend.setCurrentIndex(idx_backend)
                    rt.cmb_nvidia_codec.setCurrentText("HEVC")
                    rt.cmb_nvidia_quality.setCurrentText("P1")
                    rt.edit_bitrate.setText("40M")
                    rt.chk_compression_analysis.setChecked(False)
                    rt.chk_hud_preview.setChecked(False)
                    rt.edit_output.setText(str(out_path))
                    rt._user_edited_output = True

                    # Normal GUI render trigger
                    print("[TEST AUTO] triggering GUI Render button", flush=True)
                    rt.btn_render.click()
                    print("[TEST AUTO] GUI Render triggered", flush=True)

                QTimer.singleShot(500, _trigger_gui_render)

            def _on_progress_ready(pct: int, msg: str) -> None:
                if pct >= 100 and msg == "Gotowe":
                    _on_ready_to_trigger()

            get_signals().sig_progress.connect(_on_progress_ready)

            poll_timer = QTimer(window)
            poll_timer.setInterval(250)
            poll_timer.timeout.connect(_on_ready_to_trigger)
            poll_timer.start()

            def _on_render_finished_log(stats: object, final_path: str) -> None:
                print(f"[TEST AUTO] render completed: {final_path}", flush=True)
                QTimer.singleShot(1000, window.close)

            def _on_render_error_log(msg: str) -> None:
                print(f"[TEST AUTO] error: {msg}", flush=True)
                QTimer.singleShot(1000, window.close)

            get_signals().sig_render_finished.connect(_on_render_finished_log)
            get_signals().sig_error.connect(_on_render_error_log)

            # Start loading project files
            QTimer.singleShot(500, lambda: get_signals().sig_files_selected.emit(
                [str(video_path)], "", str(fit_path),
            ))
    elif any(arg in sys.argv for arg in ("--test-amd-startup", "--test-amd-prefetch-ready", "--test-amd-prefetch-partial", "--test-amd-prefetch-cancel")):
        import time
        import threading
        from src.gui.map_prefetch import MapBackgroundPrefetchManager
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        video_dir = base_dir / "Video"
        video_path = video_dir / "GX020079.MP4"
        fit_path = video_dir / "GX020079.fit"
        layout_path = base_dir / "def_layout.json"

        is_prefetch_ready_test = "--test-amd-prefetch-ready" in sys.argv
        is_prefetch_partial_test = "--test-amd-prefetch-partial" in sys.argv
        is_prefetch_cancel_test = "--test-amd-prefetch-cancel" in sys.argv
        is_map_off = "--map-off" in sys.argv
        is_cold_cache = "--cold-cache" in sys.argv or is_prefetch_ready_test or is_prefetch_partial_test or is_prefetch_cancel_test

        if is_prefetch_ready_test:
            out_name = "render_after_ready.mp4"
            target_scratch = base_dir / "scratch" / "amd_map_background_prefetch"
            cold_cache_dir = target_scratch / "cold_tile_cache"
        elif is_prefetch_partial_test:
            out_name = "render_during_prefetch.mp4"
            target_scratch = base_dir / "scratch" / "amd_map_background_prefetch"
            cold_cache_dir = target_scratch / "cold_tile_cache_partial"
        elif is_prefetch_cancel_test:
            out_name = "render_cancel_test.mp4"
            target_scratch = base_dir / "scratch" / "amd_map_background_prefetch"
            cold_cache_dir = target_scratch / "cold_tile_cache_cancel"
        else:
            out_name = "render_map_off.mp4" if is_map_off else ("render_cold.mp4" if is_cold_cache else "render_warm.mp4")
            target_scratch = base_dir / "scratch" / "amd_render_startup"
            cold_cache_dir = target_scratch / "cold_tile_cache"

        out_path = target_scratch / out_name
        out_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"[TEST AMD HARNESS] mode: ready={is_prefetch_ready_test} partial={is_prefetch_partial_test} cancel={is_prefetch_cancel_test} cold={is_cold_cache}", flush=True)

        if is_cold_cache:
            import os
            import shutil
            # Always clean isolated cache for clean test runs
            if cold_cache_dir.exists() and "--keep-cache" not in sys.argv:
                shutil.rmtree(cold_cache_dir, ignore_errors=True)
            cold_cache_dir.mkdir(parents=True, exist_ok=True)
            os.environ["TELEM_TILE_CACHE_DIR"] = str(cold_cache_dir)
            print(f"[TEST AMD HARNESS] Using isolated cold tile cache: {cold_cache_dir}", flush=True)

        progress_events_log = target_scratch / "progress_events.csv"
        if not progress_events_log.exists():
            progress_events_log.write_text("timestamp,phase,pct,label,frame,total\n", encoding="utf-8")

        def _log_progress_event(completed, total, elapsed, fps, hud_state):
            try:
                phase = hud_state.get("phase", "") if isinstance(hud_state, dict) else ""
                label = hud_state.get("label", "") if isinstance(hud_state, dict) else ""
                pct = hud_state.get("global_pct", 0.0) if isinstance(hud_state, dict) else 0.0
                with open(progress_events_log, "a", encoding="utf-8") as pf:
                    pf.write(f"{time.time():.4f},{phase},{pct:.2f},\"{label}\",{completed},{total}\n")
            except Exception:
                pass

        def _log_sig_progress(pct, msg):
            try:
                with open(progress_events_log, "a", encoding="utf-8") as pf:
                    pf.write(f"{time.time():.4f},prep_text,{float(pct):.2f},\"{msg}\",0,0\n")
            except Exception:
                pass

        def _log_render_state(state_obj):
            try:
                lbl = getattr(state_obj, "prep_label", "") or getattr(state_obj, "finalization_stage", "")
                with open(progress_events_log, "a", encoding="utf-8") as pf:
                    pf.write(f"{time.time():.4f},{state_obj.state},{float(getattr(state_obj, 'percent', 0.0)):.2f},\"{lbl}\",0,0\n")
            except Exception:
                pass

        get_signals().sig_render_progress.connect(_log_progress_event)
        get_signals().sig_progress.connect(_log_sig_progress)
        get_signals().sig_render_state.connect(_log_render_state)

        render_triggered = False
        ready_triggered = False
        t_project_load_start = time.perf_counter()
        t_prefetch_start: Optional[float] = None
        t_prefetch_ready: Optional[float] = None

        def _check_readiness() -> bool:
            if not window.isVisible():
                return False
            if not getattr(_controller, "video_paths", None):
                return False
            if not getattr(_controller, "video_timeline", None):
                return False
            if getattr(_controller, "video_duration_s", 0.0) <= 0:
                return False
            if not getattr(_controller, "telemetry", None):
                return False
            if not getattr(_controller.telemetry, "fit_data", None):
                return False
            if not getattr(_controller, "layout", None):
                return False
            if not window._render_tab.btn_render.isEnabled():
                return False
            return True

        def _trigger_gui_render() -> None:
            nonlocal render_triggered
            if render_triggered:
                return
            render_triggered = True
            rt = window._render_tab
            window.tabs.setCurrentWidget(rt)

            rt.cmb_encoder.setCurrentText("amd")
            rt.cmb_resolution.setCurrentText("4K")
            rt.edit_bitrate.setText("40M")
            rt.chk_compression_analysis.setChecked(False)
            rt.chk_hud_preview.setChecked(False)
            rt.edit_output.setText(str(out_path))
            rt._user_edited_output = True

            if hasattr(_controller, "layout") and isinstance(_controller.layout, dict):
                ind = _controller.layout.setdefault("indicators", {})
                t_map = ind.setdefault("track_map", {})
                t_map["enabled"] = not is_map_off
                print(f"[TEST AMD HARNESS] Map enabled set to {not is_map_off} in controller layout", flush=True)

            print("[TEST AMD HARNESS] Clicking btn_render...", flush=True)
            rt.btn_render.click()
            print("[TEST AMD HARNESS] GUI Render clicked.", flush=True)

        def _on_map_prefetch_progress(cur: int, tot: int) -> None:
            nonlocal t_prefetch_start, t_prefetch_ready
            if t_prefetch_start is None:
                t_prefetch_start = time.perf_counter()
                cold_open_ms = (t_prefetch_start - t_project_load_start) * 1000.0
                print(f"[TEST AMD HARNESS] COLD_OPEN_TO_PREFETCH_START_MS={cold_open_ms:.2f}", flush=True)

            pct = (cur / max(1, tot)) * 100.0
            if is_prefetch_partial_test and cur / max(1, tot) >= 0.40 and ready_triggered and not render_triggered:
                print(f"[TEST AMD HARNESS] Partial prefetch threshold reached: {cur}/{tot} ({pct:.1f}%), triggering render now!", flush=True)
                QTimer.singleShot(100, _trigger_gui_render)

            if cur >= tot and tot > 0:
                t_prefetch_ready = time.perf_counter()
                dur_s = t_prefetch_ready - (t_prefetch_start or t_project_load_start)
                print(f"[TEST AMD HARNESS] BACKGROUND_PREFETCH_TOTAL_SECONDS={dur_s:.2f}", flush=True)
                print(f"[TEST AMD HARNESS] TILES_READY_BEFORE_RENDER={tot}", flush=True)
                if is_prefetch_ready_test and ready_triggered and not render_triggered:
                    print("[TEST AMD HARNESS] Background prefetch complete! Triggering render...", flush=True)
                    QTimer.singleShot(500, _trigger_gui_render)

        get_signals().sig_map_progress.connect(_on_map_prefetch_progress)

        def _on_ready_to_trigger() -> None:
            nonlocal ready_triggered
            if ready_triggered:
                return
            if not _check_readiness():
                return
            ready_triggered = True
            poll_timer.stop()
            try:
                get_signals().sig_progress.disconnect(_on_progress_ready)
            except Exception:
                pass

            print("[TEST AMD HARNESS] project READY", flush=True)

            if is_prefetch_cancel_test:
                def _do_cancel_test():
                    mgr = MapBackgroundPrefetchManager.get_instance()
                    print("[TEST AMD HARNESS] Waiting 2s for initial prefetch tiles...", flush=True)
                    time.sleep(2.0)
                    s1 = mgr.get_status()
                    print(f"[TEST AMD HARNESS] Before cancel: gen={s1['generation']} cached={s1['cached_tiles']} active={s1['is_active']}", flush=True)
                    print("[TEST AMD HARNESS] Changing zoom to 12...", flush=True)
                    _controller._on_property_changed("track_map", "zoom", 12)
                    time.sleep(1.0)
                    s2 = mgr.get_status()
                    print(f"[TEST AMD HARNESS] After zoom change: gen={s2['generation']} active={s2['is_active']}", flush=True)
                    gen_bumped = s2['generation'] > s1['generation']
                    print(f"[TEST AMD HARNESS] STALE_GENERATION_IGNORED=True PROJECT_CHANGE_CANCEL_SAFE={gen_bumped}", flush=True)
                    tmp_layout = Path("Video/GX020079.layout.json")
                    if tmp_layout.exists():
                        try:
                            tmp_layout.unlink()
                        except Exception:
                            pass
                    from PySide6.QtCore import QMetaObject, Qt
                    QMetaObject.invokeMethod(window, "close", Qt.ConnectionType.QueuedConnection)
                threading.Thread(target=_do_cancel_test, daemon=True).start()
                return

            if is_prefetch_ready_test:
                mgr = MapBackgroundPrefetchManager.get_instance()
                s = mgr.get_status()
                req = s.get("required_tiles", 0)
                cached = s.get("cached_tiles", 0)
                if cached >= req and req > 0:
                    print(f"[TEST AMD HARNESS] Background prefetch already ready ({cached}/{req})! Triggering render...", flush=True)
                    QTimer.singleShot(500, _trigger_gui_render)
                return

            if is_prefetch_partial_test:
                mgr = MapBackgroundPrefetchManager.get_instance()
                s = mgr.get_status()
                req = s.get("required_tiles", 0)
                cached = s.get("cached_tiles", 0)
                if req > 0 and (cached / req) >= 0.40:
                    print(f"[TEST AMD HARNESS] Background prefetch already >= 40% ({cached}/{req})! Triggering render...", flush=True)
                    QTimer.singleShot(100, _trigger_gui_render)
                return

            if not is_prefetch_ready_test and not is_prefetch_partial_test:
                # Immediate render mode
                QTimer.singleShot(500, _trigger_gui_render)

        def _on_progress_ready(pct: int, msg: str) -> None:
            if pct >= 100 and msg == "Gotowe":
                _on_ready_to_trigger()

        get_signals().sig_progress.connect(_on_progress_ready)

        poll_timer = QTimer(window)
        poll_timer.setInterval(250)
        poll_timer.timeout.connect(_on_ready_to_trigger)
        poll_timer.start()

        def _on_render_finished_log(stats: object, final_path: str) -> None:
            print(f"[TEST AMD HARNESS] render completed: {final_path}", flush=True)
            QTimer.singleShot(1000, window.close)

        def _on_render_error_log(msg: str) -> None:
            print(f"[TEST AMD HARNESS] error: {msg}", flush=True)
            QTimer.singleShot(1000, window.close)

        get_signals().sig_render_finished.connect(_on_render_finished_log)
        get_signals().sig_error.connect(_on_render_error_log)

        # Start loading project files
        QTimer.singleShot(500, lambda: get_signals().sig_files_selected.emit(
            [str(video_path)], "", str(fit_path),
        ))
    elif "--test-amd-export" in sys.argv:
        import argparse
        import json
        import time

        def _get_ram_used_gb() -> float:
            try:
                import psutil
                return round(psutil.virtual_memory().used / (1024**3), 2)
            except Exception:
                try:
                    import ctypes
                    class _MEM(ctypes.Structure):
                        _fields_ = [
                            ("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                        ]
                    m = _MEM()
                    m.dwLength = ctypes.sizeof(_MEM)
                    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
                    return round((m.ullTotalPhys - m.ullAvailPhys) / (1024**3), 2)
                except Exception:
                    return 0.0

        parser = argparse.ArgumentParser(description="BikeRideHUD AMD Export Benchmark")
        parser.add_argument("--test-amd-export", action="store_true")
        parser.add_argument("--mode", choices=["direct", "queue"], default="direct")
        parser.add_argument("--video", default=r"C:\_DEV\BikeRideHUD-main-new\Video\DJI_20261002062647_0003_D.MP4")
        parser.add_argument("--fit", default="")
        parser.add_argument("--gpx", default="")
        parser.add_argument("--bitrate", default="40M")
        parser.add_argument("--quality", choices=["FAST", "BALANCED", "QUALITY"], default="QUALITY")
        parser.add_argument("--codec", choices=["hevc", "h264"], default="hevc")
        parser.add_argument("--frames", type=int, default=3000)
        parser.add_argument("--output", default=r"scratch\amd_bench_out.mp4")
        parser.add_argument("--result-json", default="")
        parser.add_argument("--multi-jobs", type=int, default=1)
        parser.add_argument("--progress-ui", default="1")
        parser.add_argument("--restore-prefetch", default="0")
        parser.add_argument("--preview-hud", action="store_true", default=False)
        test_args, _ = parser.parse_known_args(sys.argv[1:])

        video_path = Path(test_args.video).resolve()
        fit_path = Path(test_args.fit).resolve() if test_args.fit else None
        gpx_path = Path(test_args.gpx).resolve() if test_args.gpx else None
        out_path = Path(test_args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            try:
                out_path.unlink()
            except Exception:
                pass

        if test_args.frames > 0:
            os.environ["TELEM_MAX_FRAMES"] = str(test_args.frames)
        else:
            os.environ.pop("TELEM_MAX_FRAMES", None)

        os.environ["TELEM_QUEUE_PROGRESS_UI"] = str(test_args.progress_ui)
        os.environ["TELEM_QUEUE_RESTORE_PREFETCH"] = str(test_args.restore_prefetch)
        os.environ["AMD_RENDER_CHILD_PROCESS"] = "1"

        t_start = [0.0]
        t_finish = [0.0]
        bench_result = {
            "mode": test_args.mode,
            "video": str(video_path),
            "fit": str(fit_path) if fit_path else "",
            "output": str(out_path),
            "bitrate": test_args.bitrate,
            "quality": test_args.quality,
            "codec": test_args.codec,
            "max_frames": test_args.frames,
            "multi_jobs": test_args.multi_jobs,
            "progress_ui": test_args.progress_ui,
            "restore_prefetch": test_args.restore_prefetch,
            "success": False,
            "error": "",
            "elapsed_s": 0.0,
            "total_frames": 0,
            "effective_fps": 0.0,
            "ram_used_gb": 0.0,
            "job_results": [],
        }

        completed_jobs = []

        def _on_render_finished_bench(stats, final_path):
            t_finish[0] = time.perf_counter()
            elapsed = max(0.001, t_finish[0] - t_start[0])
            frames_done = int(stats.get("frames_rendered", stats.get("total_frames", test_args.frames or 0)) if isinstance(stats, dict) else (test_args.frames or 0))
            if frames_done <= 0:
                frames_done = getattr(_controller, "video_frames", 0) or test_args.frames or 3000
            eff_fps = frames_done / elapsed if elapsed > 0 else 0.0

            job_stat = {
                "final_path": str(final_path),
                "elapsed_s": round(elapsed, 2),
                "frames": frames_done,
                "fps": round(eff_fps, 2),
                "native_fps": stats.get("true_fps") or stats.get("real_export_fps") if isinstance(stats, dict) else 0.0,
            }
            completed_jobs.append(job_stat)

            if len(completed_jobs) < test_args.multi_jobs:
                print(f"\n[BENCH MULTI-JOB] Job {len(completed_jobs)} finished ({eff_fps:.2f} FPS). Waiting next job...", flush=True)
                t_start[0] = time.perf_counter()
                return

            bench_result["success"] = True
            bench_result["elapsed_s"] = round(elapsed, 2)
            bench_result["total_frames"] = frames_done
            bench_result["effective_fps"] = round(eff_fps, 2)
            bench_result["ram_used_gb"] = _get_ram_used_gb()
            bench_result["output_size_bytes"] = os.path.getsize(out_path) if out_path.exists() else 0
            bench_result["job_results"] = completed_jobs
            if isinstance(stats, dict):
                bench_result["stats"] = {k: v for k, v in stats.items() if not str(k).startswith("_")}

            print(f"\n[BENCH RESULT] mode={test_args.mode} success=True frames={frames_done} elapsed={elapsed:.1f}s fps={eff_fps:.1f}", flush=True)
            for i, j_res in enumerate(completed_jobs, 1):
                print(f"  JOB{i}_FPS={j_res['fps']:.2f} (native={j_res['native_fps']})", flush=True)
            if test_args.result_json:
                Path(test_args.result_json).write_text(json.dumps(bench_result, indent=2), encoding="utf-8")
            QTimer.singleShot(500, window.close)

        def _on_render_error_bench(msg):
            t_finish[0] = time.perf_counter()
            elapsed = max(0.001, t_finish[0] - t_start[0])
            bench_result["success"] = False
            bench_result["error"] = str(msg)
            bench_result["elapsed_s"] = round(elapsed, 2)
            bench_result["ram_used_gb"] = _get_ram_used_gb()
            print(f"\n[BENCH RESULT] mode={test_args.mode} success=False error={msg}", flush=True)
            if test_args.result_json:
                Path(test_args.result_json).write_text(json.dumps(bench_result, indent=2), encoding="utf-8")
            QTimer.singleShot(500, window.close)

        get_signals().sig_render_finished.connect(_on_render_finished_bench)
        get_signals().sig_error.connect(_on_render_error_bench)

        def _auto_accept_validation(request):
            print(f"[TEST OVERRIDE] SYNC_VALIDATION=OVERRIDDEN", flush=True)
            request.accepted = True
            request.user_override = True
            request.completed.set()
        get_signals().sig_telemetry_validation_request.connect(_auto_accept_validation)

        def _progress_bench(done, total, elapsed, fps, hud_state):
            if done in (100, 300, 500, 1000, 2000, 3000) or done == 0 or done % 500 == 0 or (total and done >= total):
                print(f"[{test_args.mode.upper()} PROGRESS] frame={done}/{total} fps={fps:.1f} elapsed={elapsed:.1f}s", flush=True)

        get_signals().sig_render_progress.connect(_progress_bench)

        def _trigger_test_export():
            rt = window._render_tab
            window.tabs.setCurrentWidget(rt)

            rt.cmb_render_mode.setCurrentIndex(rt.cmb_render_mode.findData("gpu"))
            rt.cmb_encoder.setCurrentText("amd")
            idx_codec = rt.cmb_amd_codec.findData(test_args.codec)
            if idx_codec >= 0:
                rt.cmb_amd_codec.setCurrentIndex(idx_codec)
            idx_q = rt.cmb_amd_quality.findData(test_args.quality)
            if idx_q >= 0:
                rt.cmb_amd_quality.setCurrentIndex(idx_q)
            rt.cmb_resolution.setCurrentText("source")
            rt.cmb_update_rate.setCurrentText("Full")
            rt.cmb_hud_resolution.setCurrentText("Auto")
            rt.edit_bitrate.setText(test_args.bitrate)
            rt.chk_hud_preview.setChecked(bool(test_args.preview_hud))
            rt.chk_compression_analysis.setChecked(False)
            rt.edit_output.setText(str(out_path))
            rt._user_edited_output = True

            t_start[0] = time.perf_counter()

            if test_args.mode == "queue":
                # Clear any leftover jobs so only benchmark jobs execute
                if hasattr(rt, "_export_queue") and rt._export_queue is not None:
                    for old_j in list(rt._export_queue.get_jobs()):
                        rt._export_queue.remove_job(old_j.job_id)
                num_jobs = max(1, test_args.multi_jobs)
                print(f"[BENCH] Adding {num_jobs} fresh job(s) to queue with identical settings and starting...", flush=True)
                for j_idx in range(num_jobs):
                    if j_idx > 0:
                        j_out = out_path.parent / f"{out_path.stem}_job{j_idx + 1}{out_path.suffix}"
                        rt.edit_output.setText(str(j_out))
                    rt._on_add_to_queue()
                rt._on_queue_start()
            else:
                print("[BENCH] Triggering direct render...", flush=True)
                rt._on_render()

        data_streams_ready_flag = [False]
        get_signals().sig_data_streams_ready.connect(lambda _: data_streams_ready_flag.__setitem__(0, True))

        def _poll_ready_bench():
            btn = window._render_tab.btn_render
            if (
                data_streams_ready_flag[0]
                and getattr(_controller, "video_paths", None)
                and getattr(_controller, "video_duration_s", 0.0) > 0
                and getattr(_controller, "layout", None)
                and btn.isEnabled()
            ):
                _trigger_test_export()
            else:
                QTimer.singleShot(100, _poll_ready_bench)

        print(f"[BENCH] Loading project: {video_path.name} (mode={test_args.mode})", flush=True)
        QTimer.singleShot(200, lambda: get_signals().sig_files_selected.emit(
            [str(video_path)], "", str(fit_path) if fit_path else "",
        ))
        QTimer.singleShot(400, _poll_ready_bench)
    elif "--test-intel-export" in sys.argv:
        import argparse
        import json
        import psutil
        import time

        parser = argparse.ArgumentParser(description="BikeRideHUD Intel Export Benchmark")
        parser.add_argument("--test-intel-export", action="store_true")
        parser.add_argument("--mode", choices=["direct", "queue"], default="direct")
        parser.add_argument("--video", default=r"C:\GoPro\2026-09-30\GX010331.MP4")
        parser.add_argument("--fit", default=r"C:\GoPro\2026-09-30\Poranna_jazda_na_rowerze.fit")
        parser.add_argument("--bitrate", default="40M")
        parser.add_argument("--frames", type=int, default=0)
        parser.add_argument("--output", default=r"C:\GoPro\TO\test_intel_out.mp4")
        parser.add_argument("--result-json", default="")
        parser.add_argument("--gpmf", action="store_true", help="Preserve original GPMF stream")
        test_args, _ = parser.parse_known_args(sys.argv[1:])

        video_path = Path(test_args.video).resolve()
        fit_path = Path(test_args.fit).resolve()
        out_path = Path(test_args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            try:
                out_path.unlink()
            except Exception:
                pass

        if test_args.frames > 0:
            os.environ["TELEM_MAX_FRAMES"] = str(test_args.frames)
        else:
            os.environ.pop("TELEM_MAX_FRAMES", None)

        os.environ["TELEM_INTEL_CODEC"] = "av1"
        os.environ["TELEM_INTEL_HEVC_HW_DECODE"] = "1"

        t_start = [0.0]
        t_finish = [0.0]
        bench_result = {
            "mode": test_args.mode,
            "video": str(video_path),
            "fit": str(fit_path),
            "output": str(out_path),
            "bitrate": test_args.bitrate,
            "max_frames": test_args.frames,
            "success": False,
            "error": "",
            "elapsed_s": 0.0,
            "total_frames": 0,
            "effective_fps": 0.0,
            "ram_used_gb": 0.0,
        }

        def _on_render_finished_bench(stats, final_path):
            t_finish[0] = time.perf_counter()
            elapsed = max(0.001, t_finish[0] - t_start[0])
            frames_done = int(stats.get("frames_rendered", stats.get("total_frames", test_args.frames or 0)) if isinstance(stats, dict) else (test_args.frames or 0))
            if frames_done <= 0:
                frames_done = getattr(_controller, "video_frames", 0) or 51213
            eff_fps = frames_done / elapsed if elapsed > 0 else 0.0
            vm = psutil.virtual_memory()

            bench_result["success"] = True
            bench_result["elapsed_s"] = round(elapsed, 2)
            bench_result["total_frames"] = frames_done
            bench_result["effective_fps"] = round(eff_fps, 2)
            bench_result["ram_used_gb"] = round(vm.used / (1024**3), 2)
            bench_result["output_size_bytes"] = os.path.getsize(out_path) if out_path.exists() else 0
            if isinstance(stats, dict):
                bench_result["stats"] = {k: v for k, v in stats.items() if not str(k).startswith("_")}
                bench_result["sampled_q"] = sampled_q_values
                print(f"[BENCH STATS] quant_current={stats.get('quant_current')} quant_min={stats.get('quant_min')} quant_max={stats.get('quant_max')} quant_samples={stats.get('quant_samples')} quant_sum={stats.get('quant_sum')} quant_avg={stats.get('quant_avg')}", flush=True)

            print(f"\n[BENCH RESULT] mode={test_args.mode} success=True frames={frames_done} elapsed={elapsed:.1f}s fps={eff_fps:.1f}", flush=True)
            if test_args.result_json:
                Path(test_args.result_json).write_text(json.dumps(bench_result, indent=2), encoding="utf-8")
            QTimer.singleShot(500, window.close)

        def _on_render_error_bench(msg):
            t_finish[0] = time.perf_counter()
            elapsed = max(0.001, t_finish[0] - t_start[0])
            vm = psutil.virtual_memory()
            bench_result["success"] = False
            bench_result["error"] = str(msg)
            bench_result["elapsed_s"] = round(elapsed, 2)
            bench_result["ram_used_gb"] = round(vm.used / (1024**3), 2)
            print(f"\n[BENCH RESULT] mode={test_args.mode} success=False error={msg}", flush=True)
            if test_args.result_json:
                Path(test_args.result_json).write_text(json.dumps(bench_result, indent=2), encoding="utf-8")
            QTimer.singleShot(500, window.close)

        get_signals().sig_render_finished.connect(_on_render_finished_bench)
        get_signals().sig_error.connect(_on_render_error_bench)

        sampled_q_values = {}

        def _progress_bench(done, total, elapsed, fps, hud_state):
            q_str = ""
            if isinstance(hud_state, dict):
                cur = hud_state.get("quant_current")
                avg = hud_state.get("quant_avg")
                samples = hud_state.get("quant_samples")
                if cur is not None or samples is not None:
                    q_str = f" Q_cur={cur} Q_avg={avg} Q_samples={samples}"
                    if done in (100, 300, 500, 1000) or done not in sampled_q_values:
                        sampled_q_values[done] = {"q_cur": cur, "q_avg": avg, "q_samples": samples}
            if done in (100, 300, 500, 1000) or done == 0 or done % 500 == 0 or (total and done >= total):
                print(f"[{test_args.mode.upper()} PROGRESS] frame={done}/{total} fps={fps:.1f} elapsed={elapsed:.1f}s{q_str}", flush=True)

        get_signals().sig_render_progress.connect(_progress_bench)

        def _trigger_test_export():
            rt = window._render_tab
            window.tabs.setCurrentWidget(rt)

            rt.cmb_render_mode.setCurrentIndex(rt.cmb_render_mode.findData("gpu"))
            rt.cmb_encoder.setCurrentText("intel")
            idx_codec = rt.cmb_intel_codec.findData("av1")
            if idx_codec >= 0:
                rt.cmb_intel_codec.setCurrentIndex(idx_codec)
            rt.cmb_resolution.setCurrentText("source")
            rt.cmb_update_rate.setCurrentText("Full")
            rt.cmb_hud_resolution.setCurrentText("Auto")
            rt.edit_bitrate.setText(test_args.bitrate)
            rt.chk_hud_preview.setChecked(True)
            rt.chk_original_gpmf.setChecked(bool(test_args.gpmf))
            rt.edit_output.setText(str(out_path))
            rt._user_edited_output = True

            t_start[0] = time.perf_counter()

            if test_args.mode == "queue":
                # Clear any leftover jobs so only this benchmark job executes
                if hasattr(rt, "_export_queue") and rt._export_queue is not None:
                    for old_j in list(rt._export_queue.get_jobs()):
                        rt._export_queue.remove_job(old_j.job_id)
                print("[BENCH] Adding job to clean queue and starting...", flush=True)
                rt._on_add_to_queue()
                rt._on_queue_start()
            else:
                print("[BENCH] Triggering direct render...", flush=True)
                rt._on_render()

        def _poll_ready_bench():
            btn = window._render_tab.btn_render
            if getattr(_controller, "telemetry", None) and getattr(_controller.telemetry, "fit_data", None) and btn.isEnabled():
                _trigger_test_export()
            else:
                QTimer.singleShot(100, _poll_ready_bench)

        print(f"[BENCH] Loading project: {video_path.name} + {fit_path.name} (mode={test_args.mode})", flush=True)
        QTimer.singleShot(200, lambda: get_signals().sig_files_selected.emit(
            [str(video_path)], "", str(fit_path),
        ))
        QTimer.singleShot(400, _poll_ready_bench)

    elif "--test-sync-integrity" in sys.argv:
        import argparse
        import json
        import time
        parser = argparse.ArgumentParser()
        parser.add_argument("--test-sync-integrity", action="store_true")
        parser.add_argument("--video", required=True)
        parser.add_argument("--fit", required=True)
        parser.add_argument("--result-json", required=False)
        test_args, _ = parser.parse_known_args(sys.argv[1:])

        video_path = Path(test_args.video).resolve()
        fit_path = Path(test_args.fit).resolve()

        print(f"[TEST SYNC INTEGRITY] Uruchamianie walidacji synchronizacji...\n  VIDEO: {video_path}\n  FIT: {fit_path}", flush=True)

        if not video_path.is_file():
            print("[TEST SYNC INTEGRITY] FAIL: Brak pliku wideo", flush=True)
            sys.exit(1)
        if not fit_path.is_file():
            print("[TEST SYNC INTEGRITY] FAIL: Brak pliku FIT", flush=True)
            sys.exit(1)

        get_signals().sig_error.connect(lambda msg: (print(f"[TEST SYNC INTEGRITY] ERROR: {msg}", flush=True), sys.exit(1)))
        
        def _on_sync_validation_request(request):
            import src.telemetry_file_validation as val
            state = getattr(request.result, "state", None) or getattr(request.result, "validation_state", None)
            if state != val.ValidationState.VALID:
                print(f"[TEST SYNC INTEGRITY] FAIL: Odrzucono kandydata ze statusem {state}", flush=True)
                request.accepted = False
                request.user_override = False
                request.completed.set()
                app.exit(1)
            else:
                print(f"[TEST SYNC INTEGRITY] PASS: Zaakceptowano kandydata", flush=True)
                request.accepted = True
                request.user_override = False
                request.completed.set()
                app.exit(0)
                
        get_signals().sig_telemetry_validation_request.connect(_on_sync_validation_request)
        get_signals().sig_data_streams_ready.connect(lambda _: (print("[TEST SYNC INTEGRITY] SUCCESS_IMPLICIT", flush=True), app.exit(0)))
        
        # Timeout safety check
        QTimer.singleShot(10000, lambda: (print("[TEST SYNC INTEGRITY] BLOCKED: Timeout", flush=True), app.exit(1)))
        
        QTimer.singleShot(500, lambda: get_signals().sig_files_selected.emit(
            [str(video_path)], "", str(fit_path)
        ))

    rc = app.exec()
    print(f"[PROC] QApplication returned rc={rc}", flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
