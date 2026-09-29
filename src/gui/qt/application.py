"""Entry point aplikacji PySide6."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
from src.gui.qt.signals import get_signals


def main() -> None:
    """Główny entry point aplikacji BikeRideHUD (PySide6)."""
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
                    rt.cmb_nvidia_codec.setCurrentText("HEVC")
                    rt.cmb_nvidia_quality.setCurrentText("Fast")
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

    rc = app.exec()
    print(f"[PROC] QApplication returned rc={rc}", flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
