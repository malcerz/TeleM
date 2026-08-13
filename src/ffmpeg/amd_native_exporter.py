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
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from PIL import Image
except ImportError:
    Image = None

from src.indicators.compositor import compose_overlay

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

    native_dll.telem_amd_process_frame.restype = c_int
    native_dll.telem_amd_process_frame.argtypes = [c_void_p, c_uint]

    native_dll.telem_amd_dump_checkpoint.restype = c_int
    native_dll.telem_amd_dump_checkpoint.argtypes = [c_void_p, c_uint, ctypes.c_char_p, ctypes.c_wchar_p]

    native_dll.telem_amd_flush.restype = c_int
    native_dll.telem_amd_flush.argtypes = [c_void_p]

    native_dll.telem_amd_close.restype = c_int
    native_dll.telem_amd_close.argtypes = [c_void_p]

    native_dll.telem_amd_get_stats.restype = None
    native_dll.telem_amd_get_stats.argtypes = [c_void_p, POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64)]

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

    # Main Frame Processing Loop
    for frame_idx in range(total_frames):
        if cancel_event is not None and cancel_event.is_set():
            print("[AMD NATIVE D3D11] Export cancelled by user.", flush=True)
            native_dll.telem_amd_close(h_context)
            return False

        curr_dt = base_dt + timedelta(seconds=frame_idx / target_fps)

        frame_kwargs = prepare_overlay_frame_data(
            layout=layout,
            target_dt=curr_dt,
            tz_offset_hours=tz_offset_hours,
            start_dt_utc=base_dt,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
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
            total_frames=total_frames,
            current_index=frame_idx,
        )

        _bboxes = {}
        composed_img = compose_overlay(
            canvas_w=video_width,
            canvas_h=video_height,
            layout=layout,
            font_path=font_path,
            _bboxes=_bboxes,
            **frame_kwargs
        )

        # Handle frame 30 diagnostic dumps & magenta marker
        if frame_idx == 30:
            print("\n=== REAL GUI EXPORT TRACE (Frame 30) ===", flush=True)
            if composed_img:
                composed_img.save("01_python_hud.png")

            # Force Magenta Diagnostic Marker (x=50, y=50, w=500, h=250)
            from PIL import ImageDraw
            draw = ImageDraw.Draw(composed_img)
            draw.rectangle([50, 50, 550, 300], fill=(255, 0, 255, 255))
            composed_img.save("02_buffer_sent_to_dll.png")

        # Convert PIL Image to RGBA bytes and send to DLL
        rgba_bytes = composed_img.tobytes("raw", "RGBA")
        native_dll.telem_amd_update_hud(
            h_context,
            rgba_bytes,
            video_width,
            video_height,
            video_width * 4
        )

        # Process frame inside native DLL (D3D11VA decode -> VideoProcessor blend -> AMF encode)
        ret = native_dll.telem_amd_process_frame(h_context, frame_idx)
        if not ret:
            print(f"[AMD NATIVE D3D11] ERROR: telem_amd_process_frame failed on frame {frame_idx}", flush=True)

        if frame_idx == 30:
            native_dll.telem_amd_dump_checkpoint(h_context, 30, b"03_d3d11_hud_texture", os.path.abspath("03_d3d11_hud_texture.png"))
            native_dll.telem_amd_dump_checkpoint(h_context, 30, b"04_videoprocessor_output", os.path.abspath("04_videoprocessor_output.png"))

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

    # Dump Checkpoint 05 (Frame 30 from final encoded MP4)
    if os.path.exists(output_file_str):
        cmd_thumb = [
            ffmpeg_exe, "-y",
            "-ss", "1.0",
            "-i", output_file_str,
            "-vframes", "1",
            "05_final_encoded_frame.png"
        ]
        subprocess.run(cmd_thumb, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    return True
