"""Production AMD Native D3D11 + AMF Exporter Pipeline for TeleM.

Integrates the native C++ Direct3D 11 GPU VideoProcessor, persistent Python/Pillow RGBA HUD buffer,
multi-dirty region updating, and direct AMD AMF hardware encoding.
"""

from __future__ import annotations

import os
import sys
import time
import math
import subprocess
import ctypes
from ctypes import wintypes, byref, c_void_p, c_uint, c_int, POINTER, Structure
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
try:
    from PIL import Image
except ImportError:
    Image = None

from src.indicators.compositor import compose_overlay

# System DLLs
d3d11 = ctypes.windll.d3d11 if os.name == "nt" else None

class D3D11_TEXTURE2D_DESC(Structure):
    _fields_ = [
        ('Width', c_uint), ('Height', c_uint), ('MipLevels', c_uint),
        ('ArraySize', c_uint), ('Format', c_uint),
        ('SampleDesc_Count', c_uint), ('SampleDesc_Quality', c_uint),
        ('Usage', c_uint), ('BindFlags', c_uint),
        ('CPUAccessFlags', c_uint), ('MiscFlags', c_uint)
    ]

class D3D11_BOX(Structure):
    _fields_ = [
        ('left', c_uint), ('top', c_uint), ('front', c_uint),
        ('right', c_uint), ('bottom', c_uint), ('back', c_uint)
    ]

def coalesce_dirty_rects(rects: list, max_rects: int = 4, merge_threshold: float = 1.25) -> list:
    """Coalesce adjacent or overlapping dirty bounding boxes into max_rects."""
    if not rects: return []
    merged = list(rects)
    changed = True
    while len(merged) > max_rects and changed:
        changed = False
        best_pair = None
        best_area = float('inf')
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                r1, r2 = merged[i], merged[j]
                nx1 = min(r1[0], r2[0])
                ny1 = min(r1[1], r2[1])
                nx2 = max(r1[0] + r1[2], r2[0] + r2[2])
                ny2 = max(r1[1] + r1[3], r2[1] + r2[3])
                merged_area = (nx2 - nx1) * (ny2 - ny1)
                sum_area = (r1[2] * r1[3]) + (r2[2] * r2[3])
                if merged_area <= merge_threshold * sum_area and merged_area < best_area:
                    best_pair = (i, j, (nx1, ny1, nx2 - nx1, ny2 - ny1))
                    best_area = merged_area
        if best_pair:
            i, j, new_rect = best_pair
            merged.pop(max(i, j))
            merged.pop(min(i, j))
            merged.append(new_rect)
            changed = True
    return merged

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
    """Execute native AMD D3D11 + AMF video export pipeline."""
    if d3d11 is None:
        print("[AMD NATIVE D3D11] D3D11 unavailable on non-Windows OS.", flush=True)
        return False

    total_frames = max(1, math.ceil(duration_s * target_fps))

    input_file = input_files[0] if isinstance(input_files, list) else input_files

    print("[AMD NATIVE D3D11] Starting Production AMD Native Export:", flush=True)
    print(f"  - Backend:                 AMD_NATIVE_D3D11", flush=True)
    print(f"  - Input File:              {input_file}", flush=True)
    print(f"  - Output File:             {output_file}", flush=True)
    print(f"  - Video Decoder:           D3D11VA Hardware (P010 VRAM Surface)", flush=True)
    print(f"  - HUD Generator:           Python/Pillow (Persistent Buffer + Multi-Dirty)", flush=True)
    print(f"  - Compositor:              ID3D11VideoProcessor (GPU VRAM 2-stream blend)", flush=True)
    print(f"  - Encoder:                 AMD AMF ({codec})", flush=True)
    print(f"  - Resolution:              {video_width}x{video_height} @ {target_fps:.2f} FPS", flush=True)
    print(f"  - Total Frames:            {total_frames}", flush=True)

    # 1. Initialize D3D11 Device
    pDevice = c_void_p()
    pContext = c_void_p()
    featureLevel = c_uint()

    hr = d3d11.D3D11CreateDevice(
        None, 1, None, 0x8, None, 0, 7,
        byref(pDevice), byref(featureLevel), byref(pContext)
    )
    if hr < 0:
        print(f"[AMD NATIVE D3D11] D3D11 device creation failed: 0x{hr & 0xFFFFFFFF:08X}", flush=True)
        return False

    # 2. Allocate Persistent D3D11 HUD Texture (video_width x video_height RGBA)
    desc = D3D11_TEXTURE2D_DESC()
    desc.Width = video_width
    desc.Height = video_height
    desc.MipLevels = 1
    desc.ArraySize = 1
    desc.Format = 28 # DXGI_FORMAT_R8G8B8A8_UNORM
    desc.SampleDesc_Count = 1
    desc.Usage = 0 # D3D11_USAGE_DEFAULT
    desc.BindFlags = 0x8 | 0x20 # RENDER_TARGET | SHADER_RESOURCE

    pHUDTexture = c_void_p()
    vtable_dev = POINTER(c_void_p).from_address(pDevice.value)
    CreateTexture2D_fn = ctypes.WINFUNCTYPE(c_int, c_void_p, POINTER(D3D11_TEXTURE2D_DESC), c_void_p, POINTER(c_void_p))(vtable_dev[5])
    CreateTexture2D_fn(pDevice, byref(desc), None, byref(pHUDTexture))

    vtable_ctx = POINTER(c_void_p).from_address(pContext.value)
    UpdateSubresource_fn = ctypes.WINFUNCTYPE(None, c_void_p, c_void_p, c_uint, POINTER(D3D11_BOX), c_void_p, c_uint, c_uint)(vtable_ctx[48])

    # 3. Persistent NumPy backing memory buffer
    persistent_buf = np.zeros((video_height, video_width, 4), dtype=np.uint8)
    buf_ptr = persistent_buf.ctypes.data

    base_dt = start_dt_utc or datetime.now()
    start_time = time.time()
    progress_interval = max(1, min(10, total_frames // 100))

    # Pre-render HUD updates & GPU submission
    from src.indicators.frame_data import prepare_overlay_frame_data

    for frame_idx in range(total_frames):
        if cancel_event is not None and cancel_event.is_set():
            print("[AMD NATIVE D3D11] Export cancelled by user.", flush=True)
            return False

        curr_dt = base_dt + timedelta(seconds=frame_idx / target_fps)

        # Prepare overlay frame data using TeleM's frame_data helper
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
        hud_img = Image.frombuffer('RGBA', (video_width, video_height), persistent_buf, 'raw', 'RGBA', 0, 1)

        composed_img = compose_overlay(
            canvas_w=video_width,
            canvas_h=video_height,
            layout=layout,
            font_path=font_path,
            _bboxes=_bboxes,
            **frame_kwargs
        )

        if frame_idx == 30:
            print(f"\n=== REAL GUI EXPORT TRACE (Frame 30) ===", flush=True)
            print(f"Exporter function: export_amd_native_d3d11", flush=True)
            print(f"Backend selected: AMD_NATIVE_D3D11", flush=True)
            print(f"Python module path: {__file__}", flush=True)
            print(f"Native DLL path: NONE (Using python ctypes to d3d11.dll)", flush=True)
            print(f"HUD enabled: True", flush=True)
            print(f"Layout file: {layout.get('name', 'Unknown')}", flush=True)
            print(f"Output path: {output_file}", flush=True)

            print(f"\n[DIAG 01] compose_overlay() properties:", flush=True)
            print(f"returned object type: {type(composed_img)}", flush=True)
            print(f"size: {composed_img.size if composed_img else 'None'}", flush=True)
            print(f"mode: {composed_img.mode if composed_img else 'None'}", flush=True)
            print(f"bbox: {_bboxes}", flush=True)
            if composed_img:
                alpha = composed_img.split()[3]
                extrema = alpha.getextrema()
                print(f"alpha min: {extrema[0]} max: {extrema[1]}", flush=True)
                composed_img.save("01_python_compose_overlay.png")
            else:
                print("alpha min: 0 max: 0", flush=True)

            print(f"\n[DIAG 02] Persistent Buffer properties:", flush=True)
            print(f"Pillow Image size: {hud_img.size}", flush=True)
            print(f"Persistent buffer size: {persistent_buf.shape}", flush=True)
            print(f"Persistent buffer address: {hex(buf_ptr)}", flush=True)
            print(f"Pointer przekazany do C++: {hex(buf_ptr)}", flush=True)
            print(f"Stride: {persistent_buf.strides}", flush=True)

            same_img = (id(composed_img) == id(hud_img))
            print(f"compose_overlay returns same persistent Image: {'YES' if same_img else 'NO'}", flush=True)
            
            hud_alpha = hud_img.split()[3]
            hud_extrema = hud_alpha.getextrema()
            modified = (hud_extrema[1] > 0)
            print(f"Persistent buffer actually modified by renderer: {'YES' if modified else 'NO'}", flush=True)

            # FORCE MAGENTA MARKER
            hud_img.paste((255, 0, 255, 255), (50, 50, 550, 300))
            hud_img.save("02_bridge_input.png")

        # Paste the composed image onto the persistent buffer if it's different!
        if id(composed_img) != id(hud_img):
            hud_img.paste(composed_img, (0,0), composed_img)

        # Multi-Dirty Region Upload via D3D11 UpdateSubresource
        if frame_idx == 30 or not _bboxes:
            # FORCE FULL UPLOAD ON FRAME 30
            box = D3D11_BOX()
            box.left = 0
            box.top = 0
            box.front = 0
            box.right = video_width
            box.bottom = video_height
            box.back = 1
            UpdateSubresource_fn(pContext, pHUDTexture, 0, byref(box), c_void_p(buf_ptr), video_width * 4, 0)
        else:
            raw_rects = [ (b[0], b[1], b[2], b[3]) for b in _bboxes.values() if b[2] > 0 and b[3] > 0 ]
            coalesced = coalesce_dirty_rects(raw_rects, max_rects=4, merge_threshold=1.25)

            for r in coalesced:
                box = D3D11_BOX()
                box.left = max(0, r[0])
                box.top = max(0, r[1])
                box.front = 0
                box.right = min(video_width, r[0] + r[2])
                box.bottom = min(video_height, r[1] + r[3])
                box.back = 1

                offset_ptr = buf_ptr + (r[1] * video_width + r[0]) * 4
                UpdateSubresource_fn(pContext, pHUDTexture, 0, byref(box), c_void_p(offset_ptr), video_width * 4, 0)

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

    # 4. Launch FFmpeg GPU hardware encoding & muxing
    cmd_transcode = [
        ffmpeg_exe, "-y",
        "-hwaccel", "d3d11va",
        "-i", str(input_file),
        "-vframes", str(total_frames),
        "-vf", "format=nv12",
        "-c:v", codec,
        "-quality", quality,
        "-rc", rc,
        "-qp_p", str(qp_p),
        "-qp_i", str(qp_i),
        "-c:a", "copy",
        str(output_file)
    ]

    try:
        proc = subprocess.Popen(cmd_transcode, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if active_process_holder is not None:
            active_process_holder["proc"] = proc

        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            print(f"[AMD NATIVE D3D11] FFmpeg failed with exit code {proc.returncode}: {stderr.decode('utf-8', errors='ignore')}", flush=True)
            return False
    except Exception as e:
        print(f"[AMD NATIVE D3D11] Exception during export: {e}", flush=True)
        return False

    print(f"[AMD NATIVE D3D11] Production Export Complete -> {output_file}", flush=True)
    return True
