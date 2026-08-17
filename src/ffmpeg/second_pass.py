"""Second-pass and file-based FFmpeg overlay rendering.

Generates overlay frame sequences to disk, encodes video clips from frames,
and merges overlay streams onto source videos.
"""

from __future__ import annotations

import math
import os
import subprocess
import time
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from concurrent.futures import ProcessPoolExecutor

from src.ffmpeg.detection import detect_gpu_decoder, _test_encoder
from src.ffmpeg.worker_cache import init_worker
from src.ffmpeg.frame_renderer import render_overlay_job
from src.ffmpeg.command_builder import scale_filter_for_resolution, append_bitrate_args, RESOLUTION_MAP
from src.ffmpeg.streaming import run_ffmpeg_with_progress


def generate_overlay_sequence(
    overlay_dir: Path,
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
    target_fps: float = 30.0,
    workers: Optional[int] = None,
    max_distance_m: Optional[float] = None,
    progress_cb: Optional[Callable] = None,
    cancel_event: Optional[Any] = None,
    update_rate_step: int = 1,
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
) -> int:
    """Generate overlay frames as BMP files using multiprocessing."""
    overlay_dir.mkdir(parents=True, exist_ok=True)
    generation_fps = target_fps / update_rate_step
    total_overlay_frames = max(1, math.ceil(duration_s * generation_fps))
    if cancel_event is not None and cancel_event.is_set():
        return 0
    workers = workers or max(1, (os.cpu_count() or 1) - 1)
    jobs = [
        (i, str(overlay_dir), start_dt_utc, tz_offset_hours,
         speed_samples, track_samples, alt_samples, target_fps, update_rate_step)
        for i in range(total_overlay_frames)
    ]
    start_time = time.time()

    from src.ffmpeg.worker_cache import WORKER_CACHE
    WORKER_CACHE["total_overlay_frames"] = total_overlay_frames

    progress_interval = max(1, min(3, total_overlay_frames // 1000))
    if workers <= 1:
        init_worker(
            video_width, video_height, font_path, layout, field_samples, max_distance_m,
            iso_samples, exposure_samples, temperature_samples,
            gpx_speed_samples, gpx_track_samples, gpx_alt_samples,
            gpx_power_samples, gpx_atemp_samples, gpx_hr_samples, gpx_cad_samples,
            fit_data=fit_data,
            gps_track=gps_track,
            start_dt_utc=start_dt_utc, tz_offset_hours=tz_offset_hours,
            speed_samples=speed_samples, track_samples=track_samples,
            alt_samples=alt_samples, target_fps=target_fps,
            update_rate_step=update_rate_step,
        )
        for i, job in enumerate(jobs, start=1):
            if cancel_event is not None and cancel_event.is_set():
                return i - 1
            render_overlay_job(job)
            if i % progress_interval == 0 or i == total_overlay_frames:
                elapsed = time.time() - start_time
                m, s = divmod(int(elapsed), 60)
                h, m = divmod(m, 60)
                fps = i / elapsed if elapsed > 0 else 0
                stats = f"PNG: {i}/{total_overlay_frames} | fps: {fps:.1f} | elapse: {h:02d}:{m:02d}:{s:02d}"
                if progress_cb:
                    progress_cb(i, stats)
        return total_overlay_frames

    done = 0
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=init_worker,
        initargs=(
            video_width, video_height, font_path, layout, field_samples, max_distance_m,
            iso_samples, exposure_samples, temperature_samples,
            gpx_speed_samples, gpx_track_samples, gpx_alt_samples,
            gpx_power_samples, gpx_atemp_samples, gpx_hr_samples, gpx_cad_samples,
            fit_data,
            gps_track,
            start_dt_utc, tz_offset_hours,
            speed_samples, track_samples, alt_samples,
            target_fps, update_rate_step,
        ),
    ) as ex:
        chunk = max(1, total_overlay_frames // max(1, workers * 4))
        for _ in ex.map(render_overlay_job, jobs, chunksize=chunk):
            if cancel_event is not None and cancel_event.is_set():
                try:
                    ex.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
                break
            done += 1
            if done % progress_interval == 0 or done == total_overlay_frames:
                elapsed = time.time() - start_time
                m, s = divmod(int(elapsed), 60)
                h, m = divmod(m, 60)
                fps = done / elapsed if elapsed > 0 else 0
                stats = f"PNG: {done}/{total_overlay_frames} | fps: {fps:.1f} | elapse: {h:02d}:{m:02d}:{s:02d}"
                if progress_cb:
                    progress_cb(done, stats)
        try:
            if cancel_event is not None and cancel_event.is_set():
                ex.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        return done


def build_overlay_video(
    ffmpeg_exe: str,
    overlay_dir: Path,
    overlay_video_path: str,
    fps: float = 30.0,
    total_frames: Optional[int] = None,
    progress_cb: Optional[Callable] = None,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[dict] = None,
) -> None:
    """Build a ProRes overlay video from rendered BMP frames."""
    cmd = [
        ffmpeg_exe, "-y", "-framerate", str(fps),
        "-i", str(overlay_dir / "overlay_%06d.bmp"),
        "-c:v", "qtrle", "-pix_fmt", "argb", str(overlay_video_path),
    ]
    if progress_cb and total_frames:
        run_ffmpeg_with_progress(
            cmd, total_frames, progress_cb, "MOV",
            cancel_event=cancel_event, active_process_holder=active_process_holder,
        )
    else:
        if cancel_event is not None and cancel_event.is_set():
            return
        p = subprocess.run(cmd)
        if p.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {p.returncode}")


def apply_overlay_video(
    ffmpeg_exe: str,
    input_files: list,
    overlay_video: str,
    output_file: str,
    encoder: str,
    gpu: int,
    target_fps: float,
    resolution_name: str = "source",
    video_bitrate: str = "",
    rotation_degrees: int = 0,
    container_rotation: int = 0,
    total_frames: Optional[int] = None,
    progress_cb: Optional[Callable] = None,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[dict] = None,
) -> None:
    """Apply a pre-rendered overlay video onto the source video."""
    hwaccel = detect_gpu_decoder(encoder, ffmpeg_exe=ffmpeg_exe)
    # Manual rotation uses CPU filters (vflip/transpose) which cannot take
    # CUDA frames, so fall back to the CPU chain when rotation is required.
    needs_cpu_rotation = rotation_degrees in (90, 180, 270)

    # Hardware acceleration works natively with rotation metadata in container
    if hwaccel == "cuda" and encoder == "nv" and not needs_cpu_rotation:
        ov_op = "overlay_cuda=x=0:y=0"
        ov_fps = f"[1:v]fps={target_fps},format=rgba,hwupload_cuda"
        target = RESOLUTION_MAP.get(resolution_name)
        if target:
            w_tgt, h_tgt = target
            base_chain = f"[0:v]scale_cuda={w_tgt}:{h_tgt}:format=yuv420p[base]"
        else:
            base_chain = "[0:v]scale_cuda=format=yuv420p[base]"
    else:
        ov_op = "overlay"
        ov_fps = f"[1:v]fps={target_fps}"
        base_chain = scale_filter_for_resolution(resolution_name)

    ov_chain = f"{ov_fps}[ov]"

    input_args: list[str] = []
    if hwaccel:
        input_args.extend(["-hwaccel", hwaccel])
        if hwaccel == "cuda" and encoder == "nv" and not needs_cpu_rotation:
            input_args.extend(["-hwaccel_output_format", "cuda"])
        elif hwaccel == "qsv":
            input_args.extend(["-hwaccel_output_format", "nv12"])
    if isinstance(input_files, list) and len(input_files) > 1:
        concat_txt = Path(output_file).parent / "render_concat_list.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in input_files:
                escaped_p = str(p.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped_p}'\n")
        input_args.extend(["-f", "concat", "-safe", "0", "-i", str(concat_txt)])
    else:
        input_file = input_files[0] if isinstance(input_files, list) else input_files
        if container_rotation != 0:
            input_args.extend(["-noautorotate", "-i", str(input_file)])
        else:
            input_args.extend(["-i", str(input_file)])

    if rotation_degrees == 180:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]vflip,hflip[vout]"
        )
    elif rotation_degrees == 90:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]transpose=1[vout]"
        )
    elif rotation_degrees == 270:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]transpose=2[vout]"
        )
    else:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vout]"
        )

    effective_rotation = container_rotation if container_rotation != 0 else (rotation_degrees if rotation_degrees != 0 else 0)
    cmd: list[str] = [
        ffmpeg_exe, "-y",
        *input_args,
        "-i", str(overlay_video),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-map_metadata", "-1", "-metadata:s:v:0", f"rotate={effective_rotation}",
    ]

    try:
        print("FFmpeg final command:", shlex.join(cmd), flush=True)
    except Exception:
        print("FFmpeg final command:", " ".join(map(str, cmd)), flush=True)

    if encoder == "nv":
        cmd.extend([
            "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
            "-cq", "24", "-pix_fmt", "yuv420p", "-gpu", str(gpu), "-c:a", "copy",
        ])
    elif encoder == "amd":
        amf_encoder = "hevc_amf" if _test_encoder("hevc_amf") else "h264_amf"
        cmd.extend([
            "-c:v", amf_encoder, "-usage", "transcoding", "-quality", "speed",
            "-rc", "cbr", "-pix_fmt", "nv12", "-c:a", "copy",
        ])
    elif encoder == "intel":
        cmd.extend([
            "-c:v", "hevc_qsv", "-preset", "veryfast",
            "-global_quality", "24", "-look_ahead", "0",
            "-async_depth", "4", "-pix_fmt", "nv12", "-c:a", "copy",
        ])
    else:
        cmd.extend([
            "-c:v", "libx265", "-preset", "medium", "-crf", "24",
            "-pix_fmt", "yuv420p", "-c:a", "copy",
        ])

    cmd = append_bitrate_args(cmd, encoder, video_bitrate)
    cmd.append(str(output_file))

    if progress_cb and total_frames:
        run_ffmpeg_with_progress(
            cmd, total_frames, progress_cb, "Render",
            cancel_event=cancel_event, active_process_holder=active_process_holder,
        )
    else:
        if cancel_event is not None and cancel_event.is_set():
            return
        p = subprocess.run(cmd)
        if p.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {p.returncode}")

    if isinstance(input_files, list) and len(input_files) > 1:
        concat_txt = Path(output_file).parent / "render_concat_list.txt"
        if concat_txt.exists():
            concat_txt.unlink()
