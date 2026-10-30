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
    """Główny entry point aplikacji SportCamHUD (PySide6)."""
    import os
    from src.config_paths import isolate_harness_config
    isolate_harness_config(sys.argv, Path(__file__).resolve().parents[3])
    app = QApplication(sys.argv)
    app.setApplicationName("SportCamHUD")

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
    if "--test-first-preview" in sys.argv:
        from tools.first_preview_harness import install
        install(app, window, _controller)
    elif "--test-b" in sys.argv or "--test-c" in sys.argv:
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

        # Set up test-only GOOD DLL override if present in runtime
        from src.runtime_paths import get_nvidia_native_dll
        good_dll_path = get_nvidia_native_dll()
        if good_dll_path.exists():
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
                    idx_codec = rt.cmb_nvidia_codec.findData("hevc_main10")
                    if idx_codec >= 0:
                        rt.cmb_nvidia_codec.setCurrentIndex(idx_codec)
                    else:
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

        parser = argparse.ArgumentParser(description="SportCamHUD AMD Export Benchmark")
        parser.add_argument("--test-amd-export", action="store_true")
        parser.add_argument("--mode", choices=["direct", "queue"], default="direct")
        parser.add_argument("--video", default=r"C:\_DEV\SportCamHUD-main-new\Video\DJI_20261002062647_0003_D.MP4")
        parser.add_argument("--fit", default="")
        parser.add_argument("--gpx", default="")
        parser.add_argument("--bitrate", default="40M")
        parser.add_argument("--quality", choices=["FAST", "BALANCED", "QUALITY"], default="QUALITY")
        parser.add_argument("--codec", choices=["hevc", "h264"], default="hevc")
        parser.add_argument("--frames", type=int, default=3000)
        parser.add_argument("--start-seconds", type=float, default=0.0)
        parser.add_argument("--output", default=r"scratch\amd_bench_out.mp4")
        parser.add_argument("--result-json", default="")
        parser.add_argument("--multi-jobs", type=int, default=1)
        parser.add_argument("--progress-ui", default="1")
        parser.add_argument("--restore-prefetch", default="0")
        parser.add_argument("--preview-hud", action="store_true", default=False)
        parser.add_argument("--layout", default="")
        # ETAP 5Z.2: HDR mode set through the GUI combo (preserve_hlg | tonemap_sdr);
        # --queue-hdr-modes gives one mode per queued job (comma separated).
        parser.add_argument("--hdr-mode", default="")
        parser.add_argument("--queue-hdr-modes", default="")
        # ETAP 5Z.3 test-only lifecycle hooks.  They call the normal GUI cancel
        # (_on_cancel) and the queue's requeue path; nothing touches the render loop.
        parser.add_argument("--videos", default="", help="comma separated multi-file project (overrides --video)")
        parser.add_argument("--cancel-after-frames", type=int, default=0)
        parser.add_argument("--retry-after-cancel", action="store_true")
        parser.add_argument("--retry-after-error", action="store_true")
        parser.add_argument("--retry-dll", default="", help="TELEM_AMD_NATIVE_DLL used for the retry")
        parser.add_argument("--retry-gui-hdr-mode", default="", help="GUI HDR mode set before the retry (job must keep its own)")
        test_args, _ = parser.parse_known_args(sys.argv[1:])

        video_list = [Path(v.strip()).resolve() for v in test_args.videos.split(",") if v.strip()]
        video_path = video_list[0] if video_list else Path(test_args.video).resolve()
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
        live_qp_samples = []

        def _on_render_finished_bench(stats, final_path):
            if "events" in bench_result:
                _event("render_finished", path=str(final_path), queue=_queue_statuses())
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

            bench_result["finish_epoch"] = time.time()
            bench_result["success"] = True
            bench_result["elapsed_s"] = round(elapsed, 2)
            bench_result["total_frames"] = frames_done
            bench_result["effective_fps"] = round(eff_fps, 2)
            bench_result["ram_used_gb"] = _get_ram_used_gb()
            bench_result["output_size_bytes"] = os.path.getsize(out_path) if out_path.exists() else 0
            bench_result["job_results"] = completed_jobs
            if isinstance(stats, dict):
                bench_result["stats"] = {k: v for k, v in stats.items() if not str(k).startswith("_")}
            bench_result["live_qp_samples"] = live_qp_samples
            from src.project_preparation import contract as _contract, ProjectMapPreparation
            bench_result["prepare_contract"] = _contract.summary()
            bench_result["map_preparation"] = ProjectMapPreparation.instance().snapshot()
            bench_result["map_gps_diagnostics"] = getattr(getattr(_controller, "telemetry", None), "map_gps_diagnostics", None)

            print(f"\n[BENCH RESULT] mode={test_args.mode} success=True frames={frames_done} elapsed={elapsed:.1f}s fps={eff_fps:.1f}", flush=True)
            for i, j_res in enumerate(completed_jobs, 1):
                print(f"  JOB{i}_FPS={j_res['fps']:.2f} (native={j_res['native_fps']})", flush=True)
            if test_args.result_json:
                Path(test_args.result_json).write_text(json.dumps(bench_result, indent=2, default=str), encoding="utf-8")
            QTimer.singleShot(500, window.close)

        lifecycle = {"cancel_sent": False, "retried": False}
        bench_result["events"] = []

        def _event(kind, **detail):
            rec = {"t": round(time.perf_counter() - t_start[0], 3), "event": kind, **detail}
            bench_result["events"].append(rec)
            print(f"[BENCH LIFECYCLE] {json.dumps(rec, default=str)}", flush=True)

        def _queue_statuses():
            q = getattr(window._render_tab, "_export_queue", None)
            if q is None:
                return []
            return [{"job_id": j.job_id[:8], "status": j.render_status, "hdr_mode": j.options.get("amd_hdr_mode"),
                     "bitrate": j.options.get("bitrate"), "quality": j.options.get("amd_encoder_quality"),
                     "error": (j.render_error or "")[:160]} for j in q.get_jobs()]

        def _resource_snapshot(label):
            snap = {"label": label}
            try:
                import psutil
                snap["child_processes"] = [
                    {"pid": c.pid, "name": c.name(), "status": c.status()}
                    for c in psutil.Process().children(recursive=True)]
            except Exception as exc:
                snap["child_processes_error"] = str(exc)
            try:
                snap["telem_pipes"] = [p for p in os.listdir("\\\\.\\pipe\\") if p.startswith("telem_amf_")]
            except Exception as exc:
                snap["telem_pipes_error"] = str(exc)
            snap["output_dir_files"] = sorted(
                f"{p.name}:{p.stat().st_size}" for p in out_path.parent.glob(out_path.stem + "*") if p.is_file())
            snap["queue"] = _queue_statuses()
            return snap

        def _do_retry(reason):
            lifecycle["retried"] = True
            rt = window._render_tab
            if test_args.retry_dll:
                os.environ["TELEM_AMD_NATIVE_DLL"] = test_args.retry_dll
            if test_args.retry_gui_hdr_mode:
                rt.set_amd_hdr_mode(test_args.retry_gui_hdr_mode)
            q = getattr(rt, "_export_queue", None)
            if test_args.mode == "queue" and q is not None:
                ids = [j.job_id for j in q.get_jobs() if j.render_status not in ("queued", "done") and not j.is_active()]
                _event("retry", reason=reason, requeue_ids=[i[:8] for i in ids], gui_hdr_mode=rt.cmb_hdr_mode.currentData(),
                       dll=os.environ.get("TELEM_AMD_NATIVE_DLL", ""))
                q.requeue_jobs(ids)
                rt._refresh_queue_ui()
                rt._on_queue_start()
            else:
                _event("retry", reason=reason, mode="direct", gui_hdr_mode=rt.cmb_hdr_mode.currentData())
                t_start[0] = time.perf_counter()
                rt._on_render()

        def _on_render_stopped_bench():
            _event("render_stopped", queue=_queue_statuses())

            def _after_stop():
                bench_result.setdefault("snapshots", []).append(_resource_snapshot("3s_after_stop"))
                if test_args.retry_after_cancel and not lifecycle["retried"]:
                    _do_retry("cancelled")
                    return
                bench_result["success"] = False
                bench_result["cancelled"] = True
                if test_args.result_json:
                    Path(test_args.result_json).write_text(json.dumps(bench_result, indent=2, default=str), encoding="utf-8")
                QTimer.singleShot(500, window.close)
            QTimer.singleShot(3000, _after_stop)

        if test_args.cancel_after_frames > 0:
            get_signals().sig_render_stopped.connect(_on_render_stopped_bench)

        def _on_render_error_bench(msg):
            if test_args.retry_after_error and not lifecycle["retried"]:
                _event("render_error", message=str(msg)[:300], queue=_queue_statuses())
                bench_result.setdefault("snapshots", []).append(_resource_snapshot("at_error"))
                QTimer.singleShot(3000, lambda: _do_retry("error"))
                return
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
            state = getattr(getattr(request, "result", None), "state", None)
            state_value = getattr(state, "value", str(state))
            request.accepted = state_value == "VALID"
            request.user_override = False
            request.completed.set()
            print(f"[BENCH] SYNC_VALIDATION={state_value} USER_OVERRIDE=NO", flush=True)
            if state_value != "VALID":
                _on_render_error_bench(f"FIT validation rejected: {state_value}")

        try:
            get_signals().sig_telemetry_validation_request.disconnect(window._on_telemetry_validation_request)
        except Exception:
            pass
        try:
            get_signals().sig_error.disconnect(window._on_error)
        except Exception:
            pass
        get_signals().sig_telemetry_validation_request.connect(_auto_accept_validation)

        def _progress_bench(done, total, elapsed, fps, hud_state):
            if (
                done > 0 and total >= test_args.frames
                and isinstance(hud_state, dict)
                and any(hud_state.get(key) is not None for key in ("avg_qp", "qp_avg", "mean_qp", "current_qp"))
                and "click_to_first_progress_ms" not in bench_result
            ):
                bench_result["click_to_first_progress_ms"] = (time.perf_counter() - t_start[0]) * 1000.0
            if isinstance(hud_state, dict):
                qp_value = next((hud_state.get(key) for key in ("avg_qp", "qp_avg", "mean_qp", "current_qp") if hud_state.get(key) is not None), None)
                compression_text = hud_state.get("compression_text")
                if qp_value is not None or compression_text:
                    live_qp_samples.append({"frame": done, "qp": qp_value, "text": compression_text})
            if done in (100, 300, 500, 1000, 2000, 3000) or done == 0 or done % 500 == 0 or (total and done >= total):
                print(f"[{test_args.mode.upper()} PROGRESS] frame={done}/{total} fps={fps:.1f} elapsed={elapsed:.1f}s", flush=True)
            if (test_args.cancel_after_frames > 0 and not lifecycle["cancel_sent"] and not lifecycle["retried"]
                    and done >= test_args.cancel_after_frames):
                lifecycle["cancel_sent"] = True
                _event("cancel_requested", frame=done, total=total)
                bench_result.setdefault("snapshots", []).append(_resource_snapshot("before_cancel"))
                QTimer.singleShot(0, window._render_tab._on_cancel)

        get_signals().sig_render_progress.connect(_progress_bench)

        def _configure_test_export():
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
            if test_args.hdr_mode:
                rt.set_amd_hdr_mode(test_args.hdr_mode)
            bench_result["hdr_mode_gui"] = rt.cmb_hdr_mode.currentData()
            bench_result["hdr_selector_visible"] = bool(rt.widget_hdr_mode.isVisibleTo(rt))
            bench_result["source_color"] = getattr(_controller, "source_color_summary", None)
            rt.chk_hud_preview.setChecked(bool(test_args.preview_hud))
            # The QP diagnostics checkbox was removed from RenderTab (98848d7).
            if hasattr(rt, "chk_compression_analysis"):
                rt.chk_compression_analysis.setChecked(False)
            rt.edit_output.setText(str(out_path))
            rt._user_edited_output = True

            if test_args.start_seconds > 0:
                rt._in_orig = test_args.start_seconds
                rt._out_orig = test_args.start_seconds + test_args.frames / max(0.001, float(_controller.fps))
                rt._ensure_range_applied()
                rt._update_inout_labels()
            bench_result["range_start_seconds"] = test_args.start_seconds
            bench_result["preview_hud"] = bool(test_args.preview_hud)

        def _trigger_test_export():
            rt = window._render_tab
            t_start[0] = time.perf_counter()
            bench_result["click_perf_counter"] = t_start[0]
            bench_result["click_epoch"] = time.time()

            if test_args.mode == "queue":
                # Clear any leftover jobs so only benchmark jobs execute
                if hasattr(rt, "_export_queue") and rt._export_queue is not None:
                    for old_j in list(rt._export_queue.get_jobs()):
                        rt._export_queue.remove_job(old_j.job_id)
                num_jobs = max(1, test_args.multi_jobs)
                print(f"[BENCH] Adding {num_jobs} fresh job(s) to queue with identical settings and starting...", flush=True)
                queue_modes = [m.strip() for m in test_args.queue_hdr_modes.split(",") if m.strip()]
                bench_result["queue_hdr_modes"] = []
                for j_idx in range(num_jobs):
                    if j_idx > 0:
                        j_out = out_path.parent / f"{out_path.stem}_job{j_idx + 1}{out_path.suffix}"
                        rt.edit_output.setText(str(j_out))
                    if queue_modes:
                        rt.set_amd_hdr_mode(queue_modes[j_idx % len(queue_modes)])
                    rt._on_add_to_queue()
                    bench_result["queue_hdr_modes"].append(rt.cmb_hdr_mode.currentData())
                if queue_modes and rt._export_queue is not None:
                    # Change the GUI after queueing: frozen jobs must keep their own modes.
                    rt.set_amd_hdr_mode("tonemap_sdr" if queue_modes[-1] == "preserve_hlg" else "preserve_hlg")
                    bench_result["queue_job_modes_frozen"] = [
                        j.options.get("amd_hdr_mode") for j in rt._export_queue.get_jobs()]
                rt._on_queue_start()
            else:
                print("[BENCH] Triggering direct render...", flush=True)
                rt._on_render()

        data_streams_ready_flag = [False]
        get_signals().sig_data_streams_ready.connect(lambda _: data_streams_ready_flag.__setitem__(0, True))

        amd_configured_flag = [False]

        def _poll_ready_bench():
            btn = window._render_tab.btn_render
            ready, _ = _controller.export_readiness()
            if (
                data_streams_ready_flag[0]
                and not getattr(_controller, "_preview_telemetry_loading", False)
                and getattr(_controller, "source_color_summary", None) is not None
                and getattr(_controller, "video_paths", None)
                and getattr(_controller, "video_duration_s", 0.0) > 0
                and getattr(_controller, "layout", None)
                and btn.isEnabled()
                and ready
            ):
                if not amd_configured_flag[0]:
                    amd_configured_flag[0] = True
                    if test_args.layout and Path(test_args.layout).is_file() and not os.environ.get("TELEM_CONFIG_DIR"):
                        from src.gui.layout_manager import normalize_layout
                        _controller.layout = normalize_layout(Path(test_args.layout).resolve(), 1280, 720)
                        print(f"[BENCH] Loaded custom benchmark layout: {test_args.layout}", flush=True)
                    _configure_test_export()
                    QTimer.singleShot(150, _poll_ready_bench)
                    return
                try:
                    from src.integrations.esri import esri_client
                    provider = getattr(_controller, "_prepared_hud_provider", None)
                    actual = getattr(_controller, "_last_preview_hud_data", None)
                    prev_idx = getattr(_controller, "_last_preview_hud_frame", 0) or 0
                    prepared = provider.frame(prev_idx) if provider is not None else None
                    value_keys = ("target_dt", "speed_value", "alt_value", "indicator_values", "extra_indicators",
                                  "map_heading", "heading_compass", "elapsed_seconds", "avg_speed_kmh")
                    vals = lambda d: {k: d.get(k) for k in value_keys} if isinstance(d, dict) else None
                    f0 = int(round(test_args.start_seconds * float(_controller.fps or 29.97)))
                    f_mid = f0 + max(0, test_args.frames // 2)
                    f_end = f0 + max(0, test_args.frames - 1)
                    sample_frames = {}
                    if provider is not None:
                        for lbl, fi in (("start", f0), ("mid", f_mid), ("end", f_end)):
                            fd = provider.frame(fi)
                            sample_frames[lbl] = {
                                "frame_index": fi,
                                "target_dt": str(fd.get("target_dt")),
                                "map_heading": fd.get("map_heading"),
                                "speed_value": fd.get("speed_value"),
                                "gps_source": getattr(fd.get("gps_track"), "source", None),
                                "gps_points": len(fd.get("gps_track") or ()),
                            }
                    pix = window.preview.hud_overlay.hud_pixmap
                    if pix is not None and not pix.isNull():
                        pix.save(str(out_path.with_name(out_path.stem + "_preview_hud.png")))
                    window.grab().save(str(out_path.with_name(out_path.stem + "_preview_window.png")))
                    bench_result["parity_audit"] = {
                        "preview_frame_index": prev_idx,
                        "numeric_parity": vals(actual) == vals(prepared) and actual is not None,
                        "preview_map_heading": actual.get("map_heading") if isinstance(actual, dict) else None,
                        "export_map_heading": prepared.get("map_heading") if isinstance(prepared, dict) else None,
                        "selected_gps_source": getattr(_controller._project_map_gps_track(), "source", None),
                        "selected_gps_points": len(_controller._project_map_gps_track() or ()),
                        "esri_attribution": esri_client.attribution,
                        "sample_frames": sample_frames,
                    }
                except Exception as exc:
                    bench_result["parity_audit_error"] = str(exc)
                _trigger_test_export()
            else:
                QTimer.singleShot(100, _poll_ready_bench)

        print(f"[BENCH] Loading project: {video_path.name} (mode={test_args.mode})", flush=True)
        QTimer.singleShot(200, lambda: get_signals().sig_files_selected.emit(
            [str(v) for v in (video_list or [video_path])], "", str(fit_path) if fit_path else "",
        ))
        QTimer.singleShot(400, _poll_ready_bench)
    elif "--test-intel-export" in sys.argv or "--test-cpu-export" in sys.argv:
        import argparse
        import json
        import psutil
        import time

        parser = argparse.ArgumentParser(description="SportCamHUD Intel Export Benchmark")
        parser.add_argument("--test-intel-export", action="store_true")
        parser.add_argument("--test-cpu-export", action="store_true")
        parser.add_argument("--start-frame", type=int, default=0)
        parser.add_argument("--codec", choices=["av1", "h264", "hevc", "hevc_sdr"], default="hevc")
        parser.add_argument("--intel-path", choices=["native", "ffmpeg"], default="native")
        parser.add_argument("--profile", choices=["fast", "balanced", "quality"], default="balanced")
        parser.add_argument("--golden-dir", default="", help="CPU harness: capture the editor HUD here")
        parser.add_argument("--golden-frame", type=int, default=0, help="export-relative frame index to capture")
        parser.add_argument("--cpu-rate-mode", choices=["abr", "crf"], default="abr",
                            help="CPU harness: GUI 'Kontrola bitrate' selection")
        parser.add_argument("--layout", default="")
        parser.add_argument("--fail-executor-init", action="store_true", help="Harness-only failure injection for FFmpeg cleanup")
        parser.add_argument("--fail-native-init", action="store_true", help="Harness-only -11 injection before the native pipe writer connects")
        parser.add_argument("--watchdog-seconds", type=int, default=120)
        parser.add_argument("--preview-hud", action="store_true")
        parser.add_argument("--export-preview-evidence", default="",
                            help="Harness-only: record export preview pixels, GUI heartbeat and cleanup")
        parser.add_argument("--preview-toggle", action="store_true",
                            help="Harness-only: switch Intel preview off and back on during export")
        parser.add_argument("--mode", choices=["direct", "queue"], default="direct")
        parser.add_argument("--video", default=r"C:\GoPro\2026-09-30\GX010331.MP4")
        parser.add_argument("--fit", default=r"C:\GoPro\2026-09-30\Poranna_jazda_na_rowerze.fit")
        parser.add_argument("--bitrate", default="40M")
        parser.add_argument("--frames", type=int, default=0)
        parser.add_argument("--output", default=r"C:\GoPro\TO\test_intel_out.mp4")
        parser.add_argument("--result-json", default="")
        parser.add_argument("--gpmf", action="store_true", help="Preserve original GPMF stream")
        parser.add_argument("--cancel-after-frames", type=int, default=0,
                            help="Harness-only: press the GUI Cancel action after N rendered frames")
        parser.add_argument("--wait-prepared", action="store_true",
                            help="Harness-only: click Start after the project's background preparation finished")
        parser.add_argument("--preview-checks", default="",
                            help="Harness-only: directory; seek the Preview to start/middle/end before Start and record map tile misses + screenshots")
        parser.add_argument("--offline-after-ready", action="store_true",
                            help="Harness-only: refuse every outbound socket of this process and its export workers once the project is READY")
        parser.add_argument("--reexport", action="store_true",
                            help="Harness-only: export the same prepared project a second time")
        parser.add_argument("--lean-check", default="",
                            help="Harness-only: directory; after READY record the Lean value seen at the Preview time and in the export table for the same frame")
        parser.add_argument("--visual-edit-check", default="",
                            help="Harness-only: directory; edit every visual-only indicator key after READY and compare the reused HUD data with a fresh build")
        test_args, _ = parser.parse_known_args(sys.argv[1:])
        cpu_harness = test_args.test_cpu_export
        if cpu_harness and (test_args.frames <= 0 or test_args.start_frame < 0 or test_args.mode != "direct"):
            parser.error("CPU harness requires --frames > 0, --start-frame >= 0 and --mode direct")
        if cpu_harness:
            os.environ["TELEM_CPU_HARNESS_TRACE"] = "1"

        if test_args.export_preview_evidence:
            from tools.intel_export_preview_probe import install
            install(window, test_args.export_preview_evidence, toggle=test_args.preview_toggle)

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

        os.environ["TELEM_INTEL_CODEC"] = test_args.codec
        os.environ["TELEM_INTEL_NATIVE_D3D11"] = "1" if test_args.intel_path == "native" else "0"
        os.environ["TELEM_INTEL_HEVC_HW_DECODE"] = "1"

        t_start = [0.0]
        t_finish = [0.0]
        cpu_project_load_started = time.perf_counter() if cpu_harness else None
        bench_result = {
            "backend": "cpu" if cpu_harness else "intel",
            "start_frame": test_args.start_frame if cpu_harness else 0,
            "codec": test_args.codec,
            "profile": test_args.profile,
            "cpu_rate_mode": getattr(test_args, "cpu_rate_mode", None) if cpu_harness else None,
            "intel_path": test_args.intel_path,
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
        # Diagnose deadlocks and fail the harness instead of waiting forever
        # on a hidden modal dialog or an unavailable device.
        import faulthandler
        faulthandler.dump_traceback_later(test_args.watchdog_seconds, exit=True)
        if test_args.fail_executor_init:
            from src.ffmpeg.streaming import _RenderExecutor
            def _fail_executor_init(*args, **kwargs):
                raise TypeError("HARNESS_EXECUTOR_INIT_FAILURE: 'lazy_import' object is not callable")
            _RenderExecutor.__init__ = _fail_executor_init
        if test_args.fail_native_init:
            from src.ffmpeg.intel_native_exporter import _load_native_intel_dll
            _load_native_intel_dll().intel_native_pipeline_init_multi_ex = lambda *args: -11

        # Inspect the actual error dialog, then dismiss only this expected
        # unsupported-codec error so the normal sig_error handler can finish.
        from PySide6.QtWidgets import QMessageBox
        dialog_timer = QTimer(window)
        def _inspect_intel_error_dialog():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, QMessageBox):
                txt = dialog.text()
                if "Plik już istnieje" in txt or "nadpisać" in txt or "zastąpić" in txt:
                    print(f"[BENCH DIALOG AUTO-YES] {txt}", flush=True)
                    dialog.accept()
                elif "Intel: wybrany kodek" in txt or "HARNESS_EXECUTOR_INIT_FAILURE" in txt:
                    bench_result["codec_error_dialog"] = txt
                    print(f"[BENCH DIALOG] {txt}", flush=True)
                    dialog.reject()
                elif os.environ.get("TELEM_INTEL_NULL_BENCHMARK") == "1" and "MP4 po eksporcie" in txt:
                    dialog.reject()
        dialog_timer.timeout.connect(_inspect_intel_error_dialog)
        dialog_timer.start(100)

        def _on_render_finished_bench(stats, final_path):
            t_finish[0] = time.perf_counter()
            elapsed = max(0.001, t_finish[0] - t_start[0])
            frames_done = int(stats.get("frames_rendered", stats.get("total_frames", test_args.frames or 0)) if isinstance(stats, dict) else (test_args.frames or 0))
            if frames_done <= 0:
                frames_done = getattr(_controller, "video_frames", 0) or 51213
            eff_fps = frames_done / elapsed if elapsed > 0 else 0.0
            vm = psutil.virtual_memory()
            holder_stats = getattr(_controller, "render_process_holder", {}).get("intel_encoder_stats")
            if holder_stats:
                stats = dict(stats or {}, **holder_stats)

            from src.ffmpeg.intel_native_exporter import _probe_video_summary
            from src.runtime_paths import get_ffmpeg_exe
            summary = _probe_video_summary(str(get_ffmpeg_exe()), str(final_path))
            source_summary = _probe_video_summary(str(get_ffmpeg_exe()), str(video_path))
            videos = [s for s in summary.get("streams", []) if s.get("codec_type") == "video"]
            audio = [s for s in summary.get("streams", []) if s.get("codec_type") == "audio"]
            source_audio = any(s.get("codec_type") == "audio" for s in source_summary.get("streams", []))
            actual_frames = int(videos[0].get("nb_frames", 0)) if videos else 0
            frames_done = actual_frames
            eff_fps = actual_frames / elapsed if elapsed > 0 else 0.0
            import threading
            forwarders = [t.name for t in threading.enumerate() if t.name == "IntelPipeForwarder"]
            bench_result["pipe_forwarders_after_export"] = forwarders
            valid = bool(videos) and (not source_audio or bool(audio))
            valid = valid and not forwarders
            if test_args.frames:
                valid = valid and actual_frames == test_args.frames
            if videos and audio:
                valid = valid and abs(float(videos[0].get("duration", 0)) - float(audio[0].get("duration", 0))) < 0.1
            if cpu_harness:
                from src.ffmpeg.render_errors import validate_partial_output
                from src.ffmpeg.hdr_color import probe_video_color
                from src.runtime_paths import get_ffprobe_exe
                av_valid, _, av_details = validate_partial_output(get_ffprobe_exe(), final_path,
                                                                   min_duration_s=0, check_av_timing=True)
                source_color = probe_video_color(video_path, str(get_ffmpeg_exe()))
                output_color = probe_video_color(final_path, str(get_ffmpeg_exe()))
                color_valid = (not source_color.is_hlg or
                               (output_color.is_hlg and output_color.bit_depth == 10 and
                                output_color.pix_fmt == "yuv420p10le" and
                                output_color.color_primaries == source_color.color_primaries and
                                output_color.color_space == source_color.color_space and
                                output_color.color_range == source_color.color_range))
                valid = valid and av_valid and color_valid
                bench_result["cpu_validation"] = {"av": av_details, "source_color": source_color.to_dict(),
                                                  "output_color": output_color.to_dict(), "color_valid": color_valid}
            bench_result["validation"] = {"valid": valid, "probe": summary, "actual_video_frames": actual_frames}
            bench_result["success"] = valid
            if not valid:
                bench_result["error"] = "MP4 validation failed: missing streams, frame count or A/V duration mismatch"
            faulthandler.cancel_dump_traceback_later()
            bench_result["elapsed_s"] = round(elapsed, 2)
            bench_result["total_frames"] = frames_done
            bench_result["effective_fps"] = round(eff_fps, 2)
            bench_result["ram_used_gb"] = round(vm.used / (1024**3), 2)
            bench_result["output_size_bytes"] = os.path.getsize(out_path) if out_path.exists() else 0
            if isinstance(stats, dict):
                bench_result["stats"] = {k: v for k, v in stats.items() if not str(k).startswith("_")}
            if cpu_harness:
                bench_result["cpu_stream_metrics"] = getattr(_controller, "render_process_holder", {}).get("cpu_stream_metrics")

            print(f"\n[BENCH RESULT] mode={test_args.mode} success={valid} frames={actual_frames} elapsed={elapsed:.1f}s fps={eff_fps:.1f}", flush=True)
            from src.project_preparation import contract as _contract
            bench_result["prepare_contract"] = _contract.summary()
            if test_args.reexport and "first_run" not in bench_result:
                import copy as _copy
                bench_result["first_run"] = _copy.deepcopy(bench_result)
                print("[BENCH] Re-exporting the same prepared project", flush=True)
                faulthandler.dump_traceback_later(test_args.watchdog_seconds, exit=True)
                QTimer.singleShot(1500, lambda: _click_start(reexport=True))
                return
            if test_args.result_json:
                Path(test_args.result_json).write_text(json.dumps(bench_result, indent=2, default=str), encoding="utf-8")
            QTimer.singleShot(500, window.close)

        def _on_render_error_bench(msg):
            faulthandler.cancel_dump_traceback_later()
            if os.environ.get("TELEM_INTEL_NULL_BENCHMARK") == "1":
                from src.ffmpeg.intel_native_exporter import get_last_intel_export_stats
                native = get_last_intel_export_stats()
                if native.get("diagnostic_null_sink"):
                    bench_result.update(diagnostic_null_sink=True, stats=native,
                        success=(native.get("finish_rc") == 0 and native.get("encoded_frames") == native.get("frames_rendered")
                                 and native.get("encoded_frames") == native.get("requested_frames", test_args.frames)),
                        total_frames=native.get("encoded_frames"),
                        elapsed_s=native.get("total_wall_seconds"),
                        effective_fps=native.get("encoded_frames", 0) / max(.001, native.get("total_wall_seconds", 0)),
                        expected_no_mp4_message=str(msg))
                    from src.project_preparation import contract as _null_contract
                    bench_result["prepare_contract"] = _null_contract.summary()
                    if test_args.result_json:
                        Path(test_args.result_json).write_text(json.dumps(bench_result, indent=2, default=str), encoding="utf-8")
                    QTimer.singleShot(500, window.close)
                    return
            t_finish[0] = time.perf_counter()
            elapsed = max(0.001, t_finish[0] - t_start[0])
            vm = psutil.virtual_memory()
            bench_result["success"] = False
            bench_result["error"] = str(msg)
            bench_result["elapsed_s"] = round(elapsed, 2)
            bench_result["ram_used_gb"] = round(vm.used / (1024**3), 2)
            bench_result["ffmpeg_children_after_error"] = [p.pid for p in psutil.Process().children(recursive=True)
                                                         if p.is_running() and p.name().lower() == "ffmpeg.exe"]
            print(f"\n[BENCH RESULT] mode={test_args.mode} success=False error={msg}", flush=True)
            if test_args.result_json:
                Path(test_args.result_json).write_text(json.dumps(bench_result, indent=2), encoding="utf-8")
            QTimer.singleShot(500, window.close)

        get_signals().sig_render_finished.connect(_on_render_finished_bench)
        get_signals().sig_error.connect(_on_render_error_bench)

        cancel_state = {"requested": False}

        def _progress_bench(done, total, elapsed, fps, hud_state):
            if done in (100, 300, 500, 1000) or done == 0 or done % 500 == 0 or (total and done >= total):
                print(f"[{test_args.mode.upper()} PROGRESS] frame={done}/{total} fps={fps:.1f} elapsed={elapsed:.1f}s", flush=True)
            if test_args.cancel_after_frames and done >= test_args.cancel_after_frames and not cancel_state["requested"]:
                cancel_state["requested"] = True
                print(f"[BENCH CANCEL] requesting GUI cancel at frame={done}", flush=True)
                QTimer.singleShot(0, window._render_tab._on_cancel)

        get_signals().sig_render_progress.connect(_progress_bench)

        # Opt-in acceptance evidence from the real GUI event loop. No production
        # control is bypassed and no system-wide input is synthesized.
        acceptance_dir = os.environ.get("TELEM_INTEL_ACCEPTANCE_DIR")
        if acceptance_dir:
            evidence_dir = Path(acceptance_dir)
            evidence_dir.mkdir(parents=True, exist_ok=True)
            latest_progress = {"done": 0, "total": test_args.frames}
            sample_previous = [time.perf_counter(), 0]
            tab_actions = set()
            def _acceptance_progress(done, total, elapsed, fps, hud_state):
                if total > 1:
                    latest_progress.update(done=int(done), total=int(total))
            get_signals().sig_render_progress.connect(_acceptance_progress)
            def _acceptance_sample():
                if not t_start[0]:
                    return
                now = time.perf_counter()
                done = latest_progress["done"]
                dt = now-sample_previous[0]
                row = dict(qpc_s=now, since_gui_start_s=now-t_start[0], frame=done,
                           fps=(done-sample_previous[1])/dt, window_s=dt)
                with (evidence_dir/"fps_10s.jsonl").open("a",encoding="utf-8") as f:
                    f.write(json.dumps(row)+"\n")
                sample_previous[:] = [now, done]
            acceptance_timer = QTimer(window)
            acceptance_timer.timeout.connect(_acceptance_sample)
            acceptance_timer.start(10000)
            def _acceptance_tabs():
                rt = window._render_tab
                if latest_progress["done"] > 0 and rt._rendering and "initialRendering" not in tab_actions:
                    tab_actions.add("initialRendering")
                    window.tabs.setCurrentWidget(rt)
                if latest_progress["done"] < 2000 or not rt._rendering:
                    return
                steps = [(2000,"Ustawienia"),(2200,"Wczytywanie"),(2400,"Projekt"),(2600,"Rendering")]
                for threshold, title in steps:
                    if latest_progress["done"] >= threshold and title not in tab_actions:
                        tab_actions.add(title)
                        for i in range(window.tabs.count()):
                            if window.tabs.tabText(i) == title:
                                window.tabs.setCurrentIndex(i)
                                def capture(title=title):
                                    overlay = window.preview.hud_overlay
                                    pix = rt.hud_preview_label.pixmap()
                                    row=dict(tab=title,frame=latest_progress["done"],rendering=rt._rendering,
                                             can_show_hud=overlay.can_show_hud(),overlay_visible=overlay.isVisible(),
                                             tap_active=rt._export_preview_gpu_tap,preview_pixmap=bool(pix and not pix.isNull()))
                                    window.grab().save(str(evidence_dir/f"tab_{title}.png"))
                                    with (evidence_dir/"tabs.jsonl").open("a",encoding="utf-8") as f:
                                        f.write(json.dumps(row)+"\n")
                                QTimer.singleShot(150,capture)
                                break
                        break
                if latest_progress["done"] >= 2800 and "dialog" not in tab_actions:
                    tab_actions.add("dialog")
                    dialog=QMessageBox(window)
                    dialog.setWindowTitle("Acceptance: dialog during export")
                    dialog.setText("Test izolacji HUD podczas aktywnego eksportu")
                    dialog.setModal(True)
                    dialog.open()
                    def capture_dialog():
                        overlay=window.preview.hud_overlay
                        row=dict(tab="dialog",frame=latest_progress["done"],modal_active=QApplication.activeModalWidget() is dialog,
                                 can_show_hud=overlay.can_show_hud(),overlay_visible=overlay.isVisible())
                        dialog.grab().save(str(evidence_dir/"dialog.png"))
                        with (evidence_dir/"tabs.jsonl").open("a",encoding="utf-8") as f:
                            f.write(json.dumps(row)+"\n")
                        dialog.accept()
                    QTimer.singleShot(250,capture_dialog)
            acceptance_tabs_timer = QTimer(window)
            acceptance_tabs_timer.timeout.connect(_acceptance_tabs)
            acceptance_tabs_timer.start(500)

        def _on_render_stopped_cancel_bench():
            if not cancel_state["requested"]:
                return
            faulthandler.cancel_dump_traceback_later()
            elapsed = max(0.001, time.perf_counter() - t_start[0])
            bench_result.update(success=True, cancelled=True, elapsed_s=round(elapsed, 2),
                                output_exists=out_path.exists())
            print(f"[BENCH RESULT] mode={test_args.mode} cancelled=True elapsed={elapsed:.1f}s", flush=True)
            if test_args.result_json:
                Path(test_args.result_json).write_text(json.dumps(bench_result, indent=2), encoding="utf-8")
            QTimer.singleShot(500, window.close)

        get_signals().sig_render_stopped.connect(_on_render_stopped_cancel_bench)

        def _configure_export():
            rt = window._render_tab
            rt.cmb_render_mode.setCurrentIndex(rt.cmb_render_mode.findData("gpu"))
            rt.cmb_encoder.setCurrentText("cpu" if cpu_harness else "intel")
            rt.cmb_encoder_profile.setCurrentIndex(rt.cmb_encoder_profile.findData(test_args.profile))
            if cpu_harness:
                rt.cmb_cpu_profile.setCurrentIndex(rt.cmb_cpu_profile.findData(test_args.profile))
                rt.cmb_cpu_rate_mode.setCurrentIndex(rt.cmb_cpu_rate_mode.findData(test_args.cpu_rate_mode))
            if test_args.layout:
                from src.gui.layout_manager import normalize_layout
                _controller.layout = normalize_layout(Path(test_args.layout).resolve(), 1280, 720)
            idx_codec = rt.cmb_intel_codec.findData(test_args.codec)
            if idx_codec >= 0:
                rt.cmb_intel_codec.setCurrentIndex(idx_codec)
            rt.cmb_resolution.setCurrentText("source")
            rt.cmb_update_rate.setCurrentText("Full")
            rt.cmb_hud_resolution.setCurrentText("Auto")
            rt.edit_bitrate.setText(test_args.bitrate)
            if cpu_harness and test_args.golden_dir:
                from src.gui.qt.harness_golden import capture_editor_hud
                vw = int(getattr(_controller, "video_width", 0) or 3840)
                vh = int(getattr(_controller, "video_height", 0) or 2160)
                bench_result["golden_editor_capture"] = capture_editor_hud(
                    _controller, test_args.start_frame + test_args.golden_frame, test_args.golden_dir, vw, vh)
            rt.chk_hud_preview.setChecked(test_args.preview_hud)
            rt.chk_original_gpmf.setChecked(bool(test_args.gpmf))
            rt.edit_output.setText(str(out_path))
            rt._user_edited_output = True
            if cpu_harness and not getattr(rt, "_cpu_harness_wrapped", False):
                original_start_render = rt._start_render
                def _cpu_start_render(options, *args, **kwargs):
                    options = dict(options, encoder="cpu", start_frame=test_args.start_frame,
                                   max_frames=test_args.frames)
                    return original_start_render(options, *args, **kwargs)
                rt._start_render = _cpu_start_render
                rt._cpu_harness_wrapped = True

        export_state = {"configured": False, "checks_done": not test_args.preview_checks, "offline": False}
        heartbeat = QTimer(window)
        heartbeat_gaps = []
        heartbeat_last = [time.perf_counter()]
        def _prepare_heartbeat():
            now = time.perf_counter()
            heartbeat_gaps.append((now - heartbeat_last[0]) * 1000)
            heartbeat_last[0] = now
        heartbeat.timeout.connect(_prepare_heartbeat)
        heartbeat.start(20)
        import threading as _hb_threads
        import traceback as _hb_traceback
        heartbeat_stalls = []
        def _watch_prepare_gui():
            main_id = _hb_threads.main_thread().ident
            while t_start[0] == 0 and len(heartbeat_stalls) < 40:
                lag = time.perf_counter() - heartbeat_last[0]
                if lag > .25:
                    frame = sys._current_frames().get(main_id)
                    if frame is not None:
                        heartbeat_stalls.append({"gap_ms": lag * 1000,
                              "stack": "".join(_hb_traceback.format_stack(frame)),
                              "hud_building": bool((getattr(_controller, "_hud_data_state", None) or {}).get("building")),
                              "project_loading": bool(getattr(_controller, "_project_loading", False)),
                              "workers": {thread.name: "".join(_hb_traceback.format_stack(sys._current_frames()[thread.ident]))
                                  for thread in _hb_threads.enumerate()
                                  if thread.ident in sys._current_frames() and
                                  any(word in thread.name.lower() for word in ("prepare", "project", "load"))}})
                time.sleep(.1)
        _hb_threads.Thread(target=_watch_prepare_gui, name="HarnessGuiHeartbeat", daemon=True).start()

        def _click_start(reexport=False):
            if cpu_harness and not reexport:
                bench_result["project_load_until_click_s"] = time.perf_counter() - cpu_project_load_started
            if not reexport:
                heartbeat.stop()
                gaps = sorted(heartbeat_gaps)
                bench_result["prepare_gui_heartbeat"] = {
                    "interval_ms": 20, "samples": len(gaps),
                    "max_gap_ms": max(gaps, default=0),
                    "p95_gap_ms": gaps[int((len(gaps)-1)*.95)] if gaps else None,
                    "gaps_over_100ms": sum(g > 100 for g in gaps),
                    "stall_samples": heartbeat_stalls,
                }
                Path(str(out_path) + ".prepare_gui.json").write_text(
                    json.dumps(bench_result["prepare_gui_heartbeat"], indent=2), encoding="utf-8")
            rt = window._render_tab
            window.tabs.setCurrentWidget(rt)
            if reexport:
                second = out_path.with_name(out_path.stem + "_reexport" + out_path.suffix)
                if second.exists():
                    second.unlink()
                rt.edit_output.setText(str(second))
                rt._user_edited_output = True
            if acceptance_dir:
                import numpy as np
                hybrid_result = getattr(_controller.telemetry, "_compass_result", None)
                if hybrid_result is not None:
                    np.save(evidence_dir/"compass_hybrid_axis.npy", hybrid_result.axis)
                from src.telemetry_compass_hybrid import snapshot_manager
                compass_inputs = snapshot_manager(_controller.telemetry)
                np.savez(evidence_dir/"compass_inputs.npz", gyro=compass_inputs.gyroscope_samples,
                         accel=compass_inputs.accelerometer_samples,fit_track=compass_inputs.fit_gps_track,
                         fit_speed=compass_inputs.fit_data["speed"])
            t_start[0] = time.perf_counter()
            if acceptance_dir:
                sample_previous[:] = [t_start[0], 0]
                (evidence_dir/"gui_start.json").write_text(json.dumps(dict(qpc_s=t_start[0],epoch=time.time())),encoding="utf-8")

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
                rt.btn_render.click()

        def _install_offline_guard():
            from src.project_preparation import install_offline_guard
            install_offline_guard("harness-gui")
            os.environ["TELEM_HARNESS_OFFLINE"] = "1"
            export_state["offline"] = True
            bench_result["offline_after_ready"] = True
            print("[BENCH] Offline after READY: outbound sockets refused in GUI and export workers", flush=True)

        def _run_preview_checks(then):
            from src.integrations import esri as _esri
            from src.moving_map import TileCache
            evidence = Path(test_args.preview_checks)
            evidence.mkdir(parents=True, exist_ok=True)
            duration = float(getattr(_controller, "video_duration_s", 0.0) or 0.0)
            points = [("start", 0.5), ("middle", duration / 2.0), ("end", max(0.0, duration - 1.0))]
            provider = getattr(_controller, "_prepared_hud_provider", None)
            if provider is not None:
                import numpy as _point_np
                columns = provider.columnar_cache().columns
                candidates = [("alt_min", "alt", False), ("alt_max", "alt", True)]
                lean_key = next(iter(provider.cache.static.lean_keys), None)
                if lean_key:
                    candidates.append(("turn_peak", f"lean_{lean_key}", True))
                for name, key, maximum in candidates:
                    channel = columns.get(key)
                    if channel is not None and _point_np.isfinite(channel).any():
                        values = _point_np.abs(channel) if name == "turn_peak" else channel
                        index = int(_point_np.nanargmax(values) if maximum else _point_np.nanargmin(values))
                        points.append((name, index / provider.fps))
            misses = {"current": None, "rows": []}
            real_cached = _esri.esri_client.cached_image
            real_get = TileCache.get

            def counted_cached(z, x, y):
                img = real_cached(z, x, y)
                if img is None and misses["current"] is not None:
                    misses["current"].add((z, x, y))
                return img

            def counted_get(self, z, x, y, style):
                img = real_get(self, z, x, y, style)
                if img is None and misses["current"] is not None:
                    misses["current"].add((z, x, y))
                return img

            _esri.esri_client.cached_image = counted_cached
            TileCache.get = counted_get
            last_frame = {"img": None, "index": None}

            def keep_frame(qimg):
                last_frame["img"] = qimg.copy()
                last_frame["index"] = getattr(_controller, "_last_preview_hud_frame", None)

            get_signals().sig_preview_frame_ready.connect(keep_frame)
            window.tabs.setCurrentWidget(window._project_tab)

            def step(i):
                if i > 0:
                    name, sec = points[i - 1]
                    provider = getattr(_controller, "_prepared_hud_provider", None)
                    expected = provider.frame_index(sec) if provider is not None else None
                    if last_frame["index"] != expected or last_frame["img"] is None:
                        # A screenshot of the preceding seek is not parity evidence.
                        attempts[0] += 1
                        if attempts[0] < 150:
                            QTimer.singleShot(100, lambda: step(i))
                            return
                    actual = getattr(_controller, "_last_preview_hud_data", None)
                    prepared = provider.frame(expected) if provider is not None and expected is not None else None
                    value_keys = ("target_dt", "speed_value", "alt_value", "indicator_values", "extra_indicators",
                                  "map_heading", "heading_compass", "elapsed_seconds", "avg_speed_kmh")
                    values = lambda data: {k: data.get(k) for k in value_keys} if data is not None else None
                    shot = evidence / f"preview_{name}.png"
                    window.grab().save(str(shot))
                    if last_frame["img"] is not None:
                        # The composed Preview frame (HUD layer; MPV draws the video natively).
                        last_frame["img"].save(str(evidence / f"preview_{name}_hud.png"))
                    row = dict(point=name, seconds=round(sec, 3), map_tile_misses=len(misses["current"]),
                               missing=sorted(misses["current"])[:10], screenshot=str(shot),
                               readiness=_controller.export_readiness(), expected_frame=expected,
                               actual_frame=last_frame["index"], fresh=last_frame["index"] == expected,
                               preview_values=values(actual), export_values=values(prepared),
                               numeric_parity=values(actual) == values(prepared) and actual is not None)
                    misses["rows"].append(row)
                    print(f"[BENCH PREVIEW CHECK] {json.dumps(row, default=str)}", flush=True)
                if i >= len(points):
                    misses["current"] = None
                    _esri.esri_client.cached_image = real_cached
                    TileCache.get = real_get
                    (evidence / "preview_checks.json").write_text(json.dumps(misses["rows"], indent=2, default=str), encoding="utf-8")
                    bench_result["preview_checks"] = misses["rows"]
                    get_signals().sig_preview_frame_ready.disconnect(keep_frame)
                    then()
                    return
                misses["current"] = set()
                last_frame.update(img=None, index=None)
                attempts[0] = 0
                get_signals().sig_seek_changed.emit(float(points[i][1]))
                QTimer.singleShot(3000, lambda: step(i + 1))

            attempts = [0]
            step(0)

        def _run_visual_edit_check():
            from src.ffmpeg.intel_native_exporter import (
                prepared_intel_hud_data, build_intel_hud_data, intel_hud_data_ready, _is_visual_only_key)
            from src.telemetry_precompute import compare_telemetry_caches, _same_value
            evidence = Path(test_args.visual_edit_check)
            evidence.mkdir(parents=True, exist_ok=True)
            ctx0 = _controller._intel_hud_ctx()
            prepared = prepared_intel_hud_data(ctx0)
            edits = []
            for name, cfg in _controller.layout.get("indicators", {}).items():
                if not isinstance(cfg, dict):
                    continue
                for key in list(cfg):
                    if not _is_visual_only_key(key):
                        continue
                    value = cfg[key]
                    if isinstance(value, bool):
                        cfg[key] = not value
                    elif isinstance(value, (int, float)):
                        cfg[key] = value + (0.37 if key in ("x", "y") else 1)
                    elif isinstance(value, str) and (value.startswith("#") or key.endswith("color")):
                        cfg[key] = "#123456"
                    elif key == "font":
                        cfg[key] = "Arial"
                    else:
                        continue
                    edits.append(f"{name}.{key}")
            ctx1 = _controller._intel_hud_ctx()
            reused = intel_hud_data_ready(ctx1)
            fresh = build_intel_hud_data(ctx1, complete=True)
            result = {"edited_keys": len(edits), "edited_sample": edits[:40], "prepared_before_edit": prepared is not None,
                      "reused_after_edit": reused}
            if prepared is not None:
                result["telemetry_parity"] = compare_telemetry_caches(fresh["telemetry_cache"], prepared["telemetry_cache"])
                result["chart_data_equal"] = _same_value(fresh["chart_data"], prepared["chart_data"])
                result["range_cache_equal"] = _same_value(fresh["range_cache"], prepared["range_cache"])
            (evidence / "visual_edit_check.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            bench_result["visual_edit_check"] = {k: v for k, v in result.items() if k != "edited_sample"}
            print(f"[BENCH VISUAL EDIT CHECK] {json.dumps(bench_result['visual_edit_check'], default=str)}", flush=True)

        def _run_lean_check():
            from datetime import timedelta as _td
            from src.ffmpeg.intel_native_exporter import prepared_intel_hud_data, prepare_intel_hud_data
            from src.telemetry_imu import interpolate_roll
            evidence = Path(test_args.lean_check)
            evidence.mkdir(parents=True, exist_ok=True)
            ctx = _controller._intel_hud_ctx()
            data = prepared_intel_hud_data(ctx) or prepare_intel_hud_data(ctx)
            table = data["telemetry_cache"]
            cfg = _controller.layout["indicators"].get("lean_indicator", {})
            smooth = float(cfg.get("lean_smoothing_s", 0.0) or 0.0)
            timeline = _controller.telemetry._get_lean_roll_samples(str(cfg.get("axis", "y")), smooth)
            rows = []
            for t in (0.5, 49.5, 620.587, 1240.173):
                frame = int(round(t * float(ctx["target_fps"])))
                resolved = _controller._resolve_preview_time(t)
                preview_dt = resolved.get("absolute_dt") or (ctx["start_dt_utc"] + _td(seconds=t))
                record = table.lookup(frame)
                export_dt = record.get("target_dt")
                rows.append(dict(
                    t=t, frame=frame, preview_dt=str(preview_dt), export_target_dt=str(export_dt),
                    preview_timeline_value=interpolate_roll(timeline, preview_dt),
                    export_table_value=record["extra_indicators"].get("lean_indicator", [None])[0],
                    timeline_at_export_dt=interpolate_roll(timeline, export_dt) if hasattr(export_dt, "tzinfo") else None,
                    lean_axis=cfg.get("axis"), lean_smoothing_s=smooth, lean_sync_ms=cfg.get("lean_sync_ms"),
                    timeline_samples=len(timeline)))
            (evidence / "lean_check.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
            bench_result["lean_check"] = rows
            print(f"[BENCH LEAN CHECK] {json.dumps(rows, default=str)}", flush=True)

        def _after_ready():
            if test_args.lean_check and "lean_check" not in bench_result:
                _run_lean_check()
            if test_args.visual_edit_check and "visual_edit_check" not in bench_result:
                _run_visual_edit_check()
            if test_args.offline_after_ready and not export_state["offline"]:
                _install_offline_guard()
            _click_start()

        def _background_preparation_done() -> bool:
            ready, reason = _controller.export_readiness()
            if not ready:
                if bench_result.get("_last_not_ready") != reason:
                    bench_result["_last_not_ready"] = reason
                    print(f"[BENCH] waiting for READY: {reason}", flush=True)
                return False
            telem = _controller.telemetry
            layout = getattr(_controller, "layout", None) or {}
            for key, cfg in layout.get("indicators", {}).items():
                if (isinstance(cfg, dict) and cfg.get("enabled", True)
                        and (cfg.get("form") == "lean" or key == "lean_indicator")
                        and str(cfg.get("source", "gyro")).strip().lower() != "grade"):
                    axis = str(cfg.get("axis", "x")).strip().lower()
                    axis = axis if axis in ("x", "y", "z") else "x"
                    smooth = float(cfg.get("lean_smoothing_s", 0.0) or 0.0)
                    if f"{axis}_{smooth:.2f}" not in getattr(telem, "_lean_roll_cache", {}):
                        return False
            worker = getattr(telem, "_compass_worker", None)
            return worker is None or not worker.is_alive()

        def _poll_ready_bench():
            btn = window._render_tab.btn_render
            if (getattr(_controller, "telemetry", None)
                    and getattr(_controller.telemetry, "fit_data", None)
                    and not getattr(_controller, "_preview_telemetry_loading", False)
                    and btn.isEnabled()
                    and (not test_args.wait_prepared or _background_preparation_done())):
                if not export_state["configured"]:
                    export_state["configured"] = True
                    _configure_export()  # may re-prepare for the selected backend
                    QTimer.singleShot(100, _poll_ready_bench)
                    return
                if test_args.wait_prepared:
                    from src.project_preparation import ProjectMapPreparation
                    bench_result["map_preparation"] = ProjectMapPreparation.instance().snapshot()
                    print(f"[BENCH] Project READY {json.dumps(bench_result['map_preparation'], default=str)}; clicking Start", flush=True)
                if not export_state["checks_done"]:
                    export_state["checks_done"] = True
                    _run_preview_checks(_after_ready)
                    return
                _after_ready()
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
        from dataclasses import asdict, is_dataclass
        from datetime import datetime
        from enum import Enum

        parser = argparse.ArgumentParser()
        parser.add_argument("--test-sync-integrity", action="store_true")
        parser.add_argument("--video", required=True)
        parser.add_argument("--fit", required=True)
        parser.add_argument("--result-json", required=False)
        test_args, _ = parser.parse_known_args(sys.argv[1:])
        video_path = Path(test_args.video).resolve()
        fit_path = Path(test_args.fit).resolve()
        result_path = Path(test_args.result_json).resolve() if test_args.result_json else None
        print(
            f"[TEST SYNC INTEGRITY] Starting real validation\n  VIDEO: {video_path}\n  FIT: {fit_path}",
            flush=True,
        )

        def _json_value(value):
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, (Path, datetime)):
                return str(value)
            if is_dataclass(value):
                return asdict(value)
            raise TypeError(f"Unsupported JSON value: {type(value).__name__}")

        def _finish_sync_test(status, validation=None, error=None, exit_code=1):
            import src.gui.telemetry_manager as telemetry_manager
            result = {
                "status": status,
                "video": str(video_path),
                "fit": str(fit_path),
                "validation": validation,
                "smart_sync": dict(telemetry_manager.LAST_SMARTSYNC_DIAGNOSTICS),
                "user_override": bool(getattr(_controller, "_last_telemetry_user_override", False)),
                "error": str(error) if error is not None else None,
            }
            if result_path is not None:
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_text(json.dumps(result, indent=2, default=_json_value), encoding="utf-8")
            print(f"[TEST SYNC INTEGRITY] RESULT={status}", flush=True)
            if error is not None:
                print(f"[TEST SYNC INTEGRITY] ERROR={error}", flush=True)
            app.exit(exit_code)

        if not video_path.is_file():
            QTimer.singleShot(0, lambda: _finish_sync_test("MISSING_FILE", error=f"Missing video: {video_path}"))
        elif not fit_path.is_file():
            QTimer.singleShot(0, lambda: _finish_sync_test("MISSING_FILE", error=f"Missing FIT: {fit_path}"))
        else:
            def _on_sync_validation_request(request):
                result = request.result
                state = getattr(result, "state", None)
                state_value = getattr(state, "value", str(state))
                if state_value == "VALID":
                    # Valid candidates are normally accepted synchronously without a prompt.
                    request.accepted = True
                    request.user_override = False
                    request.completed.set()
                    return
                request.accepted = False
                request.user_override = False
                request.completed.set()
                _finish_sync_test(
                    "INVALID", validation=result, error=getattr(result, "reason_code", "INVALID"),
                )

            def _on_sync_ready(*_args):
                result = getattr(_controller, "_last_external_telemetry_validation_result", None)
                telemetry = getattr(_controller, "telemetry", None)
                loaded_path = getattr(telemetry, "fit_path", None)
                fit_data = getattr(telemetry, "fit_data", None)
                import src.gui.telemetry_manager as telemetry_manager
                smart_sync = dict(telemetry_manager.LAST_SMARTSYNC_DIAGNOSTICS)
                if result is None or getattr(getattr(result, "state", None), "value", None) != "VALID":
                    _finish_sync_test("INVALID", validation=result, error="No explicit VALID file validation")
                    return
                if not loaded_path or Path(loaded_path).resolve() != fit_path or not fit_data:
                    _finish_sync_test("INVALID", validation=result, error="FIT did not load from the requested source")
                    return
                if smart_sync.get("status") != "VALID" or not smart_sync.get("matched_points"):
                    _finish_sync_test("INVALID", validation=result, error="No accepted spatial SmartSync result")
                    return
                if getattr(_controller, "_last_telemetry_user_override", False):
                    _finish_sync_test("INVALID", validation=result, error="Unexpected user override")
                    return
                _finish_sync_test("VALID", validation=result, exit_code=0)

            def _on_sync_error(message):
                _finish_sync_test("INTERNAL_ERROR", error=message)

            try:
                get_signals().sig_telemetry_validation_request.disconnect(window._on_telemetry_validation_request)
            except Exception:
                pass
            try:
                get_signals().sig_error.disconnect(window._on_error)
            except Exception:
                pass
            get_signals().sig_telemetry_validation_request.connect(_on_sync_validation_request)
            get_signals().sig_data_streams_ready.connect(_on_sync_ready)
            get_signals().sig_error.connect(_on_sync_error)
            QTimer.singleShot(
                120000,
                lambda: _finish_sync_test("TIMEOUT", error="Validation timed out"),
            )
            QTimer.singleShot(500, lambda: get_signals().sig_files_selected.emit(
                [str(video_path)], "", str(fit_path)
            ))

    rc = app.exec()
    print(f"[PROC] QApplication returned rc={rc}", flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
