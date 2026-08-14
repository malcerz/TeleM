"""Production AMD Native D3D11 + AMF Exporter Pipeline for TeleM.

Integrates the native C++ Direct3D 11 GPU VideoProcessor, persistent Python/Pillow RGBA HUD buffer,
and direct AMD AMF hardware encoding inside telem_amd_native.dll.
"""

from __future__ import annotations

import os
import sys
import time
import math
import subprocess
import ctypes
from ctypes import wintypes, byref, c_void_p, c_uint, c_uint64, c_int, POINTER, Structure
from datetime import datetime, timedelta
import numpy as np
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from PIL import Image
except ImportError:
    Image = None

from src.indicators.compositor import compose_overlay
from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value, WORKER_CACHE

def export_amd_native_d3d11(
    ffmpeg_exe: str,
    input_files: list,
    output_file: str,
    duration_s: float,
    video_width: int,
    video_height: int,
    start_dt_utc: Optional[datetime],
    tz_offset_hours: float,
    speed_samples: list,
    track_samples: list,
    alt_samples: list,
    font_path: str,
    layout: dict[str, Any],
    field_samples: dict[str, Any],
    target_fps: float = 29.97,
    video_bitrate: str = "",
    codec: str = "hevc_amf",
    quality: str = "speed",
    rc: str = "cqp",
    qp_p: int = 28,
    qp_i: int = 28,
    max_distance_m: Optional[float] = None,
    iso_samples: Optional[list] = None,
    exposure_samples: Optional[list] = None,
    temperature_samples: Optional[list] = None,
    gpx_speed_samples: Optional[list] = None,
    gpx_track_samples: Optional[list] = None,
    gpx_alt_samples: Optional[list] = None,
    gpx_power_samples: Optional[list] = None,
    gpx_atemp_samples: Optional[list] = None,
    gpx_hr_samples: Optional[list] = None,
    gpx_cad_samples: Optional[list] = None,
    fit_data: Optional[dict[str, list]] = None,
    gps_track: Optional[list] = None,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[dict] = None,
) -> bool:
    """Execute production native AMD D3D11 + AMF video export pipeline via telem_amd_native.dll."""
    total_frames = max(1, math.ceil(duration_s * target_fps))
    input_file = input_files[0] if isinstance(input_files, list) else input_files
    input_file_str = str(Path(input_file).resolve())
    output_file_str = str(Path(output_file).resolve())

    # 1. Locate and Load telem_amd_native.dll
    dll_path = os.path.abspath("native/d3d11_amf_pipeline/bin/telem_amd_native.dll")
    if not os.path.exists(dll_path):
        print(f"[AMD NATIVE D3D11] ERROR: DLL not found at {dll_path}", flush=True)
        print("AMD_NATIVE_D3D11 = FAIL", flush=True)
        return False

    if hasattr(os, "add_dll_directory"):
        mingw_bin = r"c:\tools\mingw64\bin"
        if os.path.exists(mingw_bin):
            os.add_dll_directory(mingw_bin)

    try:
        native_dll = ctypes.CDLL(dll_path)
    except Exception as e:
        print(f"[AMD NATIVE D3D11] Failed to load DLL {dll_path}: {e}", flush=True)
        print("AMD_NATIVE_D3D11 = FAIL", flush=True)
        return False

    build_time = datetime.fromtimestamp(os.path.getmtime(dll_path)).strftime("%Y-%m-%d %H:%M:%S")
    print("TELEM AMD NATIVE DLL:", flush=True)
    print(f"  absolute path:    {dll_path}", flush=True)
    print(f"  build timestamp:  {build_time}", flush=True)
    print(f"  version/build id: v1.0-ETAP3C-GCC16", flush=True)

    # Function Signatures
    native_dll.telem_amd_create.restype = c_void_p
    native_dll.telem_amd_create.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, c_uint, c_uint, c_uint, c_uint]

    native_dll.telem_amd_update_hud.restype = c_int
    native_dll.telem_amd_update_hud.argtypes = [c_void_p, ctypes.c_char_p, c_uint, c_uint, c_uint]

    native_dll.telem_amd_update_video_frame.restype = c_int
    native_dll.telem_amd_update_video_frame.argtypes = [c_void_p, ctypes.c_char_p, c_uint, c_uint, c_uint]

    native_dll.telem_amd_process_frame.restype = c_int
    native_dll.telem_amd_process_frame.argtypes = [c_void_p, c_uint, c_int]

    native_dll.telem_amd_dump_checkpoint.restype = c_int
    native_dll.telem_amd_dump_checkpoint.argtypes = [c_void_p, c_uint, ctypes.c_char_p, ctypes.c_wchar_p]

    native_dll.telem_amd_flush.restype = c_int
    native_dll.telem_amd_flush.argtypes = [c_void_p]

    native_dll.telem_amd_close.restype = c_int
    native_dll.telem_amd_close.argtypes = [c_void_p]

    native_dll.telem_amd_get_stats.restype = None
    native_dll.telem_amd_get_stats.argtypes = [c_void_p, POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64)]

    # 2. Log Telemetry Channel Availability
    gpmf_count = len(speed_samples) if speed_samples else 0
    fit_speed_samples = (fit_data or {}).get("speed", [])
    fit_count = len(fit_speed_samples) if fit_speed_samples else 0
    gpx_count = len(gpx_speed_samples) if gpx_speed_samples else 0

    print(f"\n[TELEMETRY CHANNELS LOG]", flush=True)
    print(f"  GPMF records count: {gpmf_count}", flush=True)
    print(f"  FIT records count:  {fit_count}", flush=True)
    print(f"  GPX records count:  {gpx_count}", flush=True)

    base_dt = start_dt_utc or datetime.now()

    # 3. Initialize Worker Cache for FIT / GPMF / GPX Resolution
    init_worker(
        video_width=video_width,
        video_height=video_height,
        font_path=font_path,
        layout=layout,
        field_samples=field_samples,
        max_distance_m=max_distance_m,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temperature_samples,
        gpx_speed_samples=gpx_speed_samples,
        gpx_track_samples=gpx_track_samples,
        gpx_alt_samples=gpx_alt_samples,
        gpx_power_samples=gpx_power_samples,
        gpx_atemp_samples=gpx_atemp_samples,
        gpx_hr_samples=gpx_hr_samples,
        gpx_cad_samples=gpx_cad_samples,
        fit_data=fit_data,
        gps_track=gps_track,
        start_dt_utc=base_dt,
        tz_offset_hours=tz_offset_hours,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        target_fps=target_fps,
        update_rate_step=1,
        total_overlay_frames=total_frames,
    )

    fps_num = int(round(target_fps * 1000))
    fps_den = 1000

    print("[AMD NATIVE D3D11] Initializing telem_amd_native context...", flush=True)
    h_context = native_dll.telem_amd_create(
        input_file_str,
        output_file_str,
        video_width,
        video_height,
        fps_num,
        fps_den
    )

    if not h_context:
        print("[AMD NATIVE D3D11] ERROR: telem_amd_create returned NULL!", flush=True)
        print("AMD_NATIVE_D3D11 = FAIL", flush=True)
        return False

    base_dt = start_dt_utc or datetime.now()
    start_time = time.time()
    progress_interval = max(1, min(10, total_frames // 100))

    from src.indicators.frame_data import prepare_overlay_frame_data

    # Launch FFmpeg Video Frame Decoder Pipe
    cmd_decode = [
        ffmpeg_exe, "-y",
        "-i", input_file_str,
        "-vf", f"scale={video_width}:{video_height},format=nv12",
        "-f", "rawvideo",
        "-pix_fmt", "nv12",
        "pipe:1"
    ]
    frame_size = video_width * video_height * 3 // 2
    try:
        proc_dec = subprocess.Popen(
            cmd_decode,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"[AMD NATIVE D3D11] ERROR: Failed to launch decoder pipe: {e}", flush=True)
        native_dll.telem_amd_close(h_context)
        return False
    # Main Frame Processing Loop
    for frame_idx in range(total_frames):
        if cancel_event is not None and cancel_event.is_set():
            print("[AMD NATIVE D3D11] Export cancelled by user.", flush=True)
            proc_dec.kill()
            native_dll.telem_amd_close(h_context)
            return False

        curr_dt = base_dt + timedelta(seconds=frame_idx / target_fps)

        # Read base video NV12 frame from decoder
        raw_nv12 = proc_dec.stdout.read(frame_size)
        if len(raw_nv12) != frame_size:
            break

        if frame_idx == 0 or frame_idx == 30:
            y_arr = np.frombuffer(raw_nv12[:video_width * video_height], dtype=np.uint8)
            print(f"[DECODER PIPE] Frame {frame_idx} NV12 Y-channel: min={y_arr.min()}, max={y_arr.max()}, mean={y_arr.mean():.1f}", flush=True)

        if frame_idx == 30:
            # Checkpoint A: raw NV12 from FFmpeg before D3D11 upload
            y_size = video_width * video_height
            y_p = np.frombuffer(raw_nv12[:y_size], dtype=np.uint8).reshape((video_height, video_width))
            uv_p = np.frombuffer(raw_nv12[y_size:], dtype=np.uint8).reshape((video_height // 2, video_width // 2, 2))
            u = np.repeat(np.repeat(uv_p[:, :, 0], 2, axis=0), 2, axis=1).astype(np.float32) - 128.0
            v = np.repeat(np.repeat(uv_p[:, :, 1], 2, axis=0), 2, axis=1).astype(np.float32) - 128.0
            y = y_p.astype(np.float32)
            r = np.clip(y + 1.402 * v, 0, 255).astype(np.uint8)
            g = np.clip(y - 0.344136 * u - 0.714136 * v, 0, 255).astype(np.uint8)
            b = np.clip(y + 1.772 * u, 0, 255).astype(np.uint8)
            rgb = np.dstack([r, g, b])
            if Image:
                Image.fromarray(rgb, "RGB").save("A_base_cpu_nv12.png")
                print("[CHECKPOINT] Saved A_base_cpu_nv12.png", flush=True)

        # Fetch precomputed chart data (it is built by init_worker)
        chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})

        frame_kwargs = prepare_overlay_frame_data(
            layout=layout,
            target_dt=curr_dt,
            start_dt_utc=base_dt,
            tz_offset_hours=tz_offset_hours,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temperature_samples,
            total_frames=total_frames,
            current_index=frame_idx,
            chart_data=chart_data,
            resolve_cache_value=_resolve_cache_value,
            gpx_speed_samples=gpx_speed_samples,
            gpx_track_samples=gpx_track_samples,
            gpx_alt_samples=gpx_alt_samples,
            gpx_power_samples=gpx_power_samples,
            gpx_atemp_samples=gpx_atemp_samples,
            gpx_hr_samples=gpx_hr_samples,
            gpx_cad_samples=gpx_cad_samples,
            fit_data=fit_data,
            gps_track=gps_track,
            _range_cache=WORKER_CACHE.get("_prep_cache"),
        )

        if frame_idx % 30 == 0:
            print(f"Frame {frame_idx}: HR={frame_kwargs.get('hr_value')}, CAD={frame_kwargs.get('cad_value')}", flush=True)

        _bboxes = {}
        composed_img = compose_overlay(
            canvas_w=video_width,
            canvas_h=video_height,
            layout=layout,
            font_path=font_path,
            _bboxes=_bboxes,
            **frame_kwargs
        )

        # Handle frame 30 diagnostic dumps
        if frame_idx == 30:
            print("\n=== REAL GUI EXPORT TRACE (Frame 30) ===", flush=True)
            if composed_img:
                composed_img.save("01_python_hud.png")
                composed_img.save("02_buffer_sent_to_dll.png")

        # Update HUD in DLL
        if composed_img:
            rgba_bytes = composed_img.tobytes("raw", "RGBA")
            native_dll.telem_amd_update_hud(
                h_context,
                rgba_bytes,
                video_width,
                video_height,
                video_width * 4
            )

        # Upload Video Frame (with HUD blend onto staging NV12)
        native_dll.telem_amd_update_video_frame(
            h_context,
            raw_nv12,
            video_width,
            video_height,
            video_width
        )
        if frame_idx == 30:
            # Checkpoint B: readback of D3D11 texture after upload, before VP
            native_dll.telem_amd_dump_checkpoint(h_context, 30, b"B_base_d3d11", os.path.abspath("B_base_d3d11.png"))

        # Process frame inside native DLL (VideoProcessor blit -> AMF encode)
        has_hud = 1 if (layout.get("indicators") or layout.get("custom_texts")) else 0
        ret = native_dll.telem_amd_process_frame(h_context, frame_idx, has_hud)
        if not ret:
            print(f"[AMD NATIVE D3D11] ERROR: telem_amd_process_frame failed on frame {frame_idx}", flush=True)

        if frame_idx == 30:
            native_dll.telem_amd_dump_checkpoint(h_context, 30, b"E_amf_input", os.path.abspath("E_amf_input.png"))

        # Progress reporting
        if (frame_idx + 1) % progress_interval == 0 or (frame_idx + 1) == total_frames:
            elapsed = time.time() - start_time
            fps = (frame_idx + 1) / elapsed if elapsed > 0 else 0
            eta = (total_frames - (frame_idx + 1)) / fps if fps > 0 else 0
            pct = int(((frame_idx + 1) / total_frames) * 100)
            m, s = divmod(int(elapsed), 60)
            em, es = divmod(int(eta), 60)
            stats_str = f"Render: {pct}% ({frame_idx+1}/{total_frames}) | {fps:.1f} FPS | {m:02d}:{s:02d} elapsed, ETA {em:02d}:{es:02d}"
            if progress_cb:
                progress_cb(frame_idx + 1, stats_str)

    if proc_dec:
        if proc_dec.stdout and hasattr(proc_dec.stdout, "close"):
            try:
                proc_dec.stdout.close()
            except Exception:
                pass
        try:
            proc_dec.wait()
        except Exception:
            pass

    # 4. Flush and Retrieve Stats
    native_dll.telem_amd_flush(h_context)

    c_decoded = c_uint64(0)
    c_vp = c_uint64(0)
    c_sub = c_uint64(0)
    c_rec = c_uint64(0)
    native_dll.telem_amd_get_stats(h_context, byref(c_decoded), byref(c_vp), byref(c_sub), byref(c_rec))

    print("\n[AMD NATIVE D3D11 PIPELINE STATS]", flush=True)
    print(f"  Source requested: {total_frames}", flush=True)
    print(f"  Decoded frames:   {c_decoded.value}", flush=True)
    print(f"  VP processed:     {c_vp.value}", flush=True)
    print(f"  AMF submitted:    {c_sub.value}", flush=True)
    print(f"  AMF output:       {c_rec.value}", flush=True)

    native_dll.telem_amd_close(h_context)

    # 5. Final Fast Remux (Copy Video Stream + Copy Audio Stream - ZERO VIDEO RE-ENCODE)
    temp_h265 = output_file_str + ".h265"
    if not os.path.exists(temp_h265) or os.path.getsize(temp_h265) == 0:
        print(f"[AMD NATIVE D3D11] ERROR: Raw bitstream {temp_h265} is missing or empty!", flush=True)
        return False

    cmd_mux = [
        ffmpeg_exe, "-y",
        "-i", temp_h265,
        "-i", input_file_str,
        "-map", "0:v",
        "-map", "1:a?",
        "-c:v", "copy",
        "-c:a", "copy",
        output_file_str
    ]

    print("[AMD NATIVE D3D11] Muxing encoded video stream + audio (-c:v copy -c:a copy)...", flush=True)
    proc = subprocess.run(cmd_mux, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        print(f"[AMD NATIVE D3D11] WARNING: FFmpeg remux failed, renaming raw bitstream.", flush=True)
        if os.path.exists(output_file_str): os.remove(output_file_str)
        os.rename(temp_h265, output_file_str)
    else:
        print(f"[AMD NATIVE D3D11] Remux complete. Final output: {output_file_str}", flush=True)
        if os.path.exists(temp_h265):
            os.remove(temp_h265)

    # Dump Checkpoint F (Frame 30 from final encoded MP4)
    if os.path.exists(output_file_str):
        cmd_thumb = [
            ffmpeg_exe, "-y",
            "-i", output_file_str,
            "-vf", "select=eq(n\\,30)",
            "-vframes", "1",
            "F_final_mp4.png"
        ]
        subprocess.run(cmd_thumb, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("[CHECKPOINT] Saved F_final_mp4.png", flush=True)

    return True

    return True
