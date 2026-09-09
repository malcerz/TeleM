"""Mixin for final video render requesting and execution pipelines.
"""

from __future__ import annotations

import json
import inspect
import os
import threading
import time
import traceback
from dataclasses import replace
from pathlib import Path

from src.ffmpeg import detect_best_encoder, stream_overlay_to_ffmpeg
from src.ffmpeg.detection import _test_encoder
from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_speed_samples,
    extract_track_samples,
    get_container_rotation,
    get_rotation_from_metadata,
    load_json_with_fallback,
    smooth_speed_samples,
)
from src.video_helpers import (
    ffprobe_stream_info,
    find_executable,
    parse_fps,
    sanitize_output_path,
)
from src.render_progress import (
    RenderCancelReason,
    RenderCancelRequest,
    RenderProgressState,
    next_render_generation_id,
)
from src.ffmpeg.hybrid_render import GpuTopology, RenderMode, choose_hybrid_mode, normalize_render_mode


class RenderMixin:
    def _begin_render_cancel_session(self, generation_id: int) -> None:
        """Install isolated cancellation state for a new export session."""
        self.render_cancel_event = threading.Event()
        self._render_cancel_lock = threading.Lock()
        self._render_cancel_reason = RenderCancelReason.NONE
        self._render_cancel_source = ""
        self._render_cancel_generation_id = generation_id

    def _set_render_cancel(
        self,
        *,
        generation_id: int,
        reason: RenderCancelReason,
        source: str,
    ) -> bool:
        """Set only the active session's render event, with an audit record."""
        active_generation = int(getattr(self, "_active_render_generation_id", 0) or 0)
        if generation_id != active_generation or active_generation <= 0:
            print(
                "[RenderCancel] IGNORE "
                f"generation={generation_id} active_generation={active_generation} "
                f"source={source} reason={reason.value}",
                flush=True,
            )
            return False

        event = getattr(self, "render_cancel_event", None)
        if event is None:
            return False
        lock = getattr(self, "_render_cancel_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._render_cancel_lock = lock
        with lock:
            if event.is_set():
                return False
            self._render_cancel_reason = reason
            self._render_cancel_source = source
            self._render_cancel_generation_id = generation_id
            event.set()

        latest = getattr(self, "_render_latest_state", None)
        frame = getattr(latest, "frame", 0)
        start = float(getattr(self, "_render_session_start", 0.0) or 0.0)
        elapsed = max(0.0, time.monotonic() - start) if start else 0.0
        chain = " -> ".join(
            frame_info.function
            for frame_info in inspect.stack(context=0)[1:5]
        )
        print(
            "[RenderCancel] SET "
            f"generation={generation_id} source={source} reason={reason.value} "
            f"thread={threading.current_thread().name} frame={frame} "
            f"elapsed={elapsed:.3f}s stack={chain}",
            flush=True,
        )
        return True

    def _on_render_requested(self, options: dict) -> None:
        """Użytkownik kliknął 'Renderuj'."""
        if not self.video_path:
            self.signals.sig_error.emit("Najpierw wybierz plik wideo.")
            return

        # Zapisz stan roboczy layoutu dla konkretnego filmu (sidecar .layout.json).
        # NIGDY nie nadpisuj wczytanego presetu użytkownika ani def_layout.json!
        if hasattr(self, "_save_project_layout"):
            self._save_project_layout()

        generation_id = int(options.get("_render_generation_id", 0) or 0)
        if generation_id <= 0:
            generation_id = next_render_generation_id()
        # Every export owns a new event.  A previous worker may still be
        # draining while its terminal Qt signal is queued, so clearing a
        # process-wide event is not sufficient isolation.
        self._begin_render_cancel_session(generation_id)
        self.render_process_holder = {}
        self._render_generation_counter = max(
            int(getattr(self, "_render_generation_counter", 0)), generation_id
        )
        self._active_render_generation_id = generation_id
        self._render_session_start = time.monotonic()
        self._render_primary_error = ""
        self._render_cleanup_errors = []
        self._render_latest_state = RenderProgressState(
            generation_id=generation_id, state="running",
        )

        def emit_initial_state() -> None:
            signal = getattr(self.signals, "sig_render_state", None)
            if signal is not None:
                signal.emit(self._render_latest_state)

        emit_initial_state()

        def emit_render_progress(completed, total, elapsed, fps, hud_state) -> None:
            hud_state = dict(hud_state or {})
            if completed and total:
                hud_state.setdefault("phase", "render")
            requested_mode = normalize_render_mode(options.get("render_mode", "gpu"))
            hud_state.setdefault("role", "cpu" if requested_mode is RenderMode.CPU else "gpu")
            hud_state.setdefault("backend", str(options.get("encoder", "auto")))
            hud_state.setdefault("frame_done", int(completed or 0))
            hud_state.setdefault("frame_total", int(total or 0))
            hud_state.setdefault("fps_instant", float(fps or 0.0))
            self.signals.sig_render_progress.emit(
                completed, total, elapsed, fps, hud_state,
            )
            phase = hud_state.get("phase") if isinstance(hud_state, dict) else "render"
            now_elapsed = max(
                float(elapsed or 0.0),
                time.monotonic() - self._render_session_start,
            )
            latest = self._render_latest_state
            if phase == "render":
                frame = max(latest.frame, int(completed or 0))
                total_frames = max(latest.total_frames, int(total or 0))
                percent = (100.0 * frame / total_frames) if total_frames else 0.0
                effective_fps = float(
                    (hud_state.get("fps") if isinstance(hud_state, dict) else None)
                    or fps or latest.fps or 0.0
                )
                eta_s = (
                    max(0.0, (total_frames - frame) / effective_fps)
                    if effective_fps > 0 and total_frames > frame else None
                )
                snapshot = RenderProgressState(
                    generation_id=generation_id,
                    state="cancelling" if self.render_cancel_event.is_set() else "rendering",
                    frame=frame,
                    total_frames=total_frames,
                    percent=percent,
                global_percent=float(hud_state.get("global_pct", percent)) if isinstance(hud_state, dict) else percent,
                elapsed_s=now_elapsed,
                fps=effective_fps,
                eta_s=eta_s,
                cancel_requested=self.render_cancel_event.is_set(),
                cancel_reason=getattr(self, "_render_cancel_reason", RenderCancelReason.NONE),
                cancel_source=getattr(self, "_render_cancel_source", ""),
                backend=str(hud_state.get("backend", "")) if isinstance(hud_state, dict) else "",
                role=str(hud_state.get("role", "")) if isinstance(hud_state, dict) else "",
                phase="render",
                frame_done=frame,
                frame_total=total_frames,
                fps_instant=effective_fps,
                fps_average=effective_fps,
                )
            elif phase == "finalize":
                snapshot = replace(
                    latest,
                    state="cancelling" if self.render_cancel_event.is_set() else "finalizing",
                    elapsed_s=now_elapsed,
                    global_percent=float(hud_state.get("global_pct", latest.global_percent)) if isinstance(hud_state, dict) else latest.global_percent,
                    finalization_stage=str(hud_state.get("finalize_stage", hud_state.get("label", "Finalizacja..."))) if isinstance(hud_state, dict) else "Finalizacja...",
                    cancel_requested=self.render_cancel_event.is_set(),
                    cancel_reason=getattr(self, "_render_cancel_reason", RenderCancelReason.NONE),
                    cancel_source=getattr(self, "_render_cancel_source", ""),
                    backend=str(hud_state.get("backend", latest.backend)) if isinstance(hud_state, dict) else latest.backend,
                    role=str(hud_state.get("role", latest.role)) if isinstance(hud_state, dict) else latest.role,
                    phase="finalize",
                )
            else:
                snapshot = replace(
                    latest,
                    state="preparing",
                    elapsed_s=now_elapsed,
                    cancel_requested=self.render_cancel_event.is_set(),
                    cancel_reason=getattr(self, "_render_cancel_reason", RenderCancelReason.NONE),
                    cancel_source=getattr(self, "_render_cancel_source", ""),
                    backend=str(hud_state.get("backend", latest.backend)) if isinstance(hud_state, dict) else latest.backend,
                    role=str(hud_state.get("role", latest.role)) if isinstance(hud_state, dict) else latest.role,
                    phase="prepare",
                )
            self._render_latest_state = snapshot
            signal = getattr(self.signals, "sig_render_state", None)
            if signal is not None:
                signal.emit(snapshot)

        def emit_terminal_state(kind: str, *, error: bool = False) -> None:
            latest = getattr(self, "_render_latest_state", RenderProgressState(generation_id=generation_id, state=kind))
            now_elapsed = max(latest.elapsed_s, time.monotonic() - self._render_session_start)
            snapshot = replace(
                latest,
                generation_id=generation_id,
                state=kind,
                elapsed_s=now_elapsed,
                eta_s=0.0 if kind == "completed" else latest.eta_s,
                cancel_requested=bool(self.render_cancel_event.is_set()),
                cancelled=kind == "cancelled",
                failed=error,
                completed=kind == "completed",
                percent=100.0 if kind == "completed" else latest.percent,
                global_percent=100.0 if kind == "completed" else latest.global_percent,
                cancel_reason=(
                    getattr(self, "_render_cancel_reason", RenderCancelReason.NONE)
                    if kind == "cancelled" else RenderCancelReason.NONE
                ),
                cancel_source=(
                    getattr(self, "_render_cancel_source", "")
                    if kind == "cancelled" else ""
                ),
            )
            self._render_latest_state = snapshot
            signal = getattr(self.signals, "sig_render_state", None)
            if signal is not None:
                signal.emit(snapshot)

        self._emit_render_progress_callback = emit_render_progress
        self._emit_render_terminal_state = emit_terminal_state

        def worker() -> None:
            try:
                stats = self._render_pipeline(options)
                if not self.render_cancel_event.is_set():
                    emit_terminal_state("completed")
                    output = options.get("output", "output.mp4")
                    self.signals.sig_render_finished.emit(stats, output)
                else:
                    emit_terminal_state("cancelled")
                    self.signals.sig_render_stopped.emit()
            except Exception as e:
                primary_error = f"{type(e).__name__}: {e}".strip()
                if primary_error.endswith(":"):
                    primary_error = f"{type(e).__name__}: <empty message>"
                self._render_primary_error = primary_error
                trace = traceback.format_exc()
                print(f"[RENDER PRIMARY ERROR] {primary_error}", flush=True)
                print(f"[RENDER PRIMARY TRACEBACK]\n{trace}", flush=True)
                if not self.render_cancel_event.is_set():
                    emit_terminal_state("failed", error=True)
                    self.signals.sig_error.emit(f"Render error: {primary_error}")
                else:
                    emit_terminal_state("cancelled")
                    self.signals.sig_render_stopped.emit()

        self.render_worker_thread = threading.Thread(
            target=worker, daemon=True, name="TeleM-RenderWorker",
        )
        self.render_worker_thread.start()

    def _render_pipeline(self, options: dict) -> dict:
        """Wykonuje pipeline renderowania (istniejąca logika)."""
        encoder = options.get("encoder", detect_best_encoder())
        if encoder == "auto":
            encoder = detect_best_encoder()
        requested_render_mode = normalize_render_mode(options.get("render_mode", "gpu"))
        if requested_render_mode is RenderMode.CPU:
            # Existing software renderer remains the canonical CPU-only path.
            encoder = "cpu"
        elif requested_render_mode is RenderMode.HYBRID:
            # A CPU producer must never create independently encoded chunks.
            # Until a backend advertises its verified handoff to the one final
            # native encoder, Hybrid safely continues as GPU-only.
            decision = choose_hybrid_mode(
                requested=requested_render_mode,
                backend=str(encoder),
                topology=GpuTopology.APU if encoder in {"amd", "intel"} else GpuTopology.UNKNOWN,
            )
            options["_hybrid_decision"] = decision
            print(
                f"[HYBRID] requested=GPU+CPU effective={decision.effective.value} "
                f"cpu_workers={decision.cpu_workers} reason={decision.reason}",
                flush=True,
            )
        # Validate that the requested hardware encoder actually works on this GPU
        if encoder == "nv" and not _test_encoder("hevc_nvenc"):
            encoder = detect_best_encoder()
        elif encoder == "amd" and not (_test_encoder("hevc_amf") or _test_encoder("h264_amf")):
            encoder = detect_best_encoder()
        elif encoder == "intel":
            # INTEL_FORCE: no silent cross-GPU fallback.  If the user explicitly
            # requested Intel, the full controlled resolution (adapter + QSV) is
            # performed by stream_overlay_to_ffmpeg, which raises a controlled
            # error (IntelBackendError) when no usable Intel GPU/QSV exists.
            pass

        resolution = options.get("resolution", "source")
        output = options.get("output", "output.mp4")
        video_bitrate = options.get("bitrate", "40M")
        hud_option = options.get("hud_resolution_scale", "Auto")

        meta = self.video_path.with_suffix(".json") if self.video_path else None

        ffmpeg_exe = self.ffmpeg_exe or find_executable("ffmpeg")
        ffprobe_exe = self.ffprobe_exe or find_executable("ffprobe")
        if not ffmpeg_exe or not ffprobe_exe:
            raise RuntimeError("ffmpeg/ffprobe nie znalezione")

        info = ffprobe_stream_info(ffprobe_exe, self.video_path)
        streams = info.get("streams", [])
        fps_stream = parse_fps(
            streams[0].get("avg_frame_rate")
            or streams[0].get("r_frame_rate")
        ) if streams else 30.0
        src_w = int(streams[0].get("width", 1920)) if streams else 1920
        src_h = int(streams[0].get("height", 1080)) if streams else 1080

        from src.ffmpeg.command_builder import RESOLUTION_MAP
        target_res = RESOLUTION_MAP.get(resolution)
        if target_res is not None:
            render_w, render_h = target_res
        else:
            render_w, render_h = src_w, src_h

        layout = dict(self.layout, cut_regions=list(self._cut_regions))
        records = []
        if meta and meta.exists():
            try:
                records = ensure_records_list(load_json_with_fallback(meta))
            except Exception:
                records = []

        # Odczytaj rotację z metadanych lub kontenera
        if records:
            rotation_degrees = get_rotation_from_metadata(records)
        else:
            rotation_degrees = getattr(self.telemetry, "rotation_degrees", 0) or 0
        container_rotation = get_container_rotation(ffprobe_exe, self.video_path)
        if container_rotation != 0:
            effective_rotation = container_rotation
            container_rotation_arg = container_rotation
        else:
            effective_rotation = rotation_degrees
            container_rotation_arg = 0

        SMOOTHING_WINDOW = 5
        speed = getattr(self.telemetry, "speed_samples", None)
        if not speed and records:
            speed = extract_speed_samples(records)
            speed = smooth_speed_samples(speed, "moving_average", SMOOTHING_WINDOW)
        track = getattr(self.telemetry, "track_samples", None)
        if not track and records:
            track = extract_track_samples(records)
        alt = getattr(self.telemetry, "alt_samples", None)
        if not alt and records:
            alt = extract_altitude_samples(records)
            if alt:
                alt = smooth_speed_samples(alt, "moving_average", SMOOTHING_WINDOW)

        output_path = sanitize_output_path(Path(output))
        if not output_path.is_absolute():
            output_path = self.video_path.parent / output_path

        self.signals.sig_progress.emit(5, "Renderowanie HUD...")
        # Faza "Przygotowywanie HUD" na wspólnym pasku postępu eksportu
        # (render_mixin przygotowuje dane przed stream_overlay_to_ffmpeg).
        self.signals.sig_render_progress.emit(
            0, 0, 0.0, 0.0,
            {"phase": "prep", "pct": 0.0, "label": "Przygotowywanie HUD..."},
        )

        field_samples = {
            "speed_samples": speed,
            "track_samples": track,
            "alt_samples": alt,
            "heading_samples": getattr(self.telemetry, "heading_samples", None),
            "gpx_heading_samples": getattr(self.telemetry, "gpx_heading_samples", None),
            "slope_samples": getattr(self.telemetry, "slope_samples", None),
            "gpx_slope_samples": getattr(self.telemetry, "gpx_slope_samples", None),
            "iso_samples": getattr(self.telemetry, "iso_samples", None),
            "exposure_samples": getattr(self.telemetry, "exposure_samples", None),
            "temperature_samples": getattr(self.telemetry, "temperature_samples", None),
            "accel_x_samples": getattr(self.telemetry, "accel_x_samples", None),
            "accel_y_samples": getattr(self.telemetry, "accel_y_samples", None),
            "accel_z_samples": getattr(self.telemetry, "accel_z_samples", None),
            "accel_magnitude_samples": getattr(self.telemetry, "accel_magnitude_samples", None),
            "gyro_x_samples": getattr(self.telemetry, "gyro_x_samples", None),
            "gyro_y_samples": getattr(self.telemetry, "gyro_y_samples", None),
            "gyro_z_samples": getattr(self.telemetry, "gyro_z_samples", None),
            "gyro_magnitude_samples": getattr(self.telemetry, "gyro_magnitude_samples", None),
        }

        # Resolve HUD resolution scale policy (Auto -> 75% for Intel 4K, 100% for other)
        from src.ffmpeg.streaming import resolve_hud_resolution_policy
        hud_resolution_scale, policy_msg = resolve_hud_resolution_policy(
            encoder=encoder,
            render_w=render_w,
            render_h=render_h,
            user_option=hud_option,
        )
        if policy_msg:
            print(policy_msg, flush=True)

        # HUD is rasterized at an explicit fraction of the export canvas.
        # Keep dimensions even because the downstream YUV/GPU filters require it.
        if render_w == 3840 and render_h == 2160 and abs(hud_resolution_scale - 0.75) < 1e-4:
            ov_w = 2560
            ov_h = 1440
        else:
            ov_w = max(2, int(round(render_w * hud_resolution_scale)))
            ov_h = max(2, int(round(render_h * hud_resolution_scale)))
        if ov_w % 2:
            ov_w += 1
        if ov_h % 2:
            ov_h += 1

        stream_kwargs = dict(
            ffmpeg_exe=ffmpeg_exe,
            input_files=self.video_paths,
            output_file=output_path,
            duration_s=self.video_duration_s,
            start_dt_utc=self.telemetry.start_dt_utc,
            video_timeline=getattr(self, "video_timeline", None),
            tz_offset_hours=2,
            speed_samples=speed,
            track_samples=track,
            alt_samples=alt,
            font_path=self.font_path,
            layout=layout,
            field_samples=field_samples,
            target_fps=fps_stream,
            update_rate_step=1,
            max_distance_m=track[-1][1] if track else 0,
            # NVIDIA production is intentionally frozen at the validated
            # four-worker configuration.  GUI preset values must not
            # accidentally select a slower unbenchmarked worker count.
            workers=4 if encoder == "nv" else self.render_threads,
            iso_samples=getattr(self.telemetry, "iso_samples", None),
            exposure_samples=getattr(self.telemetry, "exposure_samples", None),
            temperature_samples=getattr(self.telemetry, "temperature_samples", None),
            gpx_speed_samples=getattr(self.telemetry, "gpx_speed_samples", None),
            gpx_track_samples=getattr(self.telemetry, "gpx_track_samples", None),
            gpx_alt_samples=getattr(self.telemetry, "gpx_alt_samples", None),
            gpx_power_samples=getattr(self.telemetry, "gpx_power_samples", None),
            gpx_atemp_samples=getattr(self.telemetry, "gpx_atemp_samples", None),
            gpx_hr_samples=getattr(self.telemetry, "gpx_hr_samples", None),
            gpx_cad_samples=getattr(self.telemetry, "gpx_cad_samples", None),
            fit_data=getattr(self.telemetry, "fit_data", {}),
            gps_track=(
                self.telemetry.get_gps_track_for_source(
                    self.layout.get("indicators", {})
                    .get("track_map", {}).get("source", "fit")
                )
                if hasattr(self.telemetry, "get_gps_track_for_source")
                else getattr(self.telemetry, "gps_track", None)
            ),
            progress_cb=lambda val, txt: self.signals.sig_progress.emit(val, txt),
            on_render_progress=getattr(
                self, "_emit_render_progress_callback", None
            ),
            cancel_event=self.render_cancel_event,
            cancel_reason_provider=lambda: getattr(
                self, "_render_cancel_reason", RenderCancelReason.NONE
            ),
            encoder=encoder,
            gpu=0,
            resolution_name=resolution,
            video_bitrate=video_bitrate,
            rotation_degrees=effective_rotation,
            container_rotation=container_rotation_arg,
            overlay_w=ov_w,
            overlay_h=ov_h,
            render_w=render_w,
            render_h=render_h,
            hud_resolution_scale=hud_resolution_scale,
            active_process_holder=self.render_process_holder,
            amd_decode_mode=options.get("amd_decode_mode", getattr(self, "amd_decode_mode", "gpu")),
            preview_session=options.get("_amd_export_preview_session"),
            preview_state_provider=getattr(self, "preview_diagnostics_provider", None),
            generation_id=int(options.get("_render_generation_id", 0) or 0),
        )

        # AMD's native D3D11/MF/AMF stack must not remain loaded in the long-
        # lived Qt process.  A real input file uses a Windows ``spawn`` child;
        # nonexistent synthetic paths keep the direct call seam used by unit
        # tests and diagnostics.
        amd_child_enabled = (
            encoder in ("amd", "amd_native")
            and str(os.environ.get("AMD_RENDER_CHILD_PROCESS", "1")).strip().lower()
            not in {"0", "false", "off", "no"}
            and bool(self.video_paths)
            # ``is_file`` intentionally avoids test doubles that patch
            # ``Path.exists`` and, more importantly, prevents attempting a
            # spawned job for a directory/synthetic path.  Production video
            # clips are regular files and therefore enter containment.
            and all(Path(path).is_file() for path in self.video_paths)
        )
        if amd_child_enabled:
            from src.ffmpeg.amd_child_process import run_amd_render_child

            child_kwargs = dict(stream_kwargs)
            for key in (
                "progress_cb",
                "on_render_progress",
                "cancel_event",
                "cancel_reason_provider",
                "preview_state_provider",
                "preview_session",
                "active_process_holder",
            ):
                child_kwargs.pop(key, None)
            preview_session = options.get("_amd_export_preview_session")
            run_amd_render_child(
                render_kwargs=child_kwargs,
                preview_config=options.get("_amd_export_preview_config"),
                progress_cb=lambda val, txt: self.signals.sig_progress.emit(val, txt),
                on_render_progress=getattr(self, "_emit_render_progress_callback", None),
                on_preview_frame=(
                    preview_session.accept_external_frame
                    if preview_session is not None
                    and hasattr(preview_session, "accept_external_frame")
                    else None
                ),
                cancel_event=self.render_cancel_event,
                cancel_reason_provider=lambda: getattr(
                    self, "_render_cancel_reason", RenderCancelReason.NONE
                ),
                active_process_holder=self.render_process_holder,
                generation_id=int(options.get("_render_generation_id", 0) or 0),
            )
        else:
            stream_overlay_to_ffmpeg(**stream_kwargs)

        return {"total_overlay_frames": 0, "png_duration": 0}

    def _on_render_cancel_requested(self, request: RenderCancelRequest) -> None:
        """Handle a generation-tagged GUI cancellation request."""
        if not isinstance(request, RenderCancelRequest):
            return
        self._set_render_cancel(
            generation_id=request.generation_id,
            reason=request.reason,
            source=request.source,
        )

    def _on_render_cancelled(self) -> None:
        """Legacy compatibility entry point for an explicit GUI cancel."""
        self._set_render_cancel(
            generation_id=int(getattr(self, "_active_render_generation_id", 0) or 0),
            reason=RenderCancelReason.USER_CANCEL,
            source="GUI_BUTTON_LEGACY",
        )
        # The render worker owns writer -> stdin ordering. Do not close stdin
        # from the GUI thread while the writer may still be inside write().

    def cancel_render_and_wait(self, timeout: float = 7.0) -> bool:
        """Request cancellation for app shutdown and wait only bounded time."""
        worker = getattr(self, "render_worker_thread", None)
        if worker is None or not worker.is_alive():
            return True
        self._set_render_cancel(
            generation_id=int(getattr(self, "_active_render_generation_id", 0) or 0),
            reason=RenderCancelReason.APP_SHUTDOWN,
            source="APPLICATION_EXIT",
        )
        worker.join(timeout=max(0.1, timeout))
        if worker.is_alive():
            process = getattr(self, "render_process_holder", {}).get("process")
            if process is not None:
                try:
                    from src.ffmpeg.streaming import _stop_ffmpeg_process
                    _stop_ffmpeg_process(process, graceful_timeout=0.1)
                except Exception:
                    pass
            worker.join(timeout=2.0)
        return not worker.is_alive()
