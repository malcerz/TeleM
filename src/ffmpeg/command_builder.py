"""FFmpeg command line arguments builder.
"""

from __future__ import annotations

from typing import Any
from src.ffmpeg.detection import _test_encoder

RESOLUTION_MAP: dict[str, tuple[int, int] | None] = {
    "source": None,
    "8k": (7680, 4320),
    "5.3k": (5312, 2988),
    "4k": (3840, 2160),
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "480p": (854, 480),
}


def scale_filter_for_resolution(resolution_name: str) -> str:
    """Return an ffmpeg scale filter string for the given resolution name."""
    target = RESOLUTION_MAP.get(resolution_name)
    if not target:
        return "[0:v]null[base]"
    w, h = target
    return f"[0:v]scale={w}:{h}:flags=lanczos[base]"


def append_bitrate_args(cmd: list[str], encoder: str, video_bitrate: str) -> list[str]:
    """Append bitrate arguments to an ffmpeg command."""
    if not video_bitrate:
        return cmd
    if encoder in ("nv", "amd"):
        cmd.extend(["-b:v", video_bitrate, "-maxrate", video_bitrate])
        bufsize = video_bitrate
        try:
            if video_bitrate.lower().endswith("m"):
                bufsize = f"{float(video_bitrate[:-1]) * 2:g}M"
            elif video_bitrate.lower().endswith("k"):
                bufsize = f"{float(video_bitrate[:-1]) * 2:g}k"
        except Exception:
            pass
        cmd.extend(["-bufsize", bufsize])
    else:
        cmd.extend(["-b:v", video_bitrate])
    return cmd


def get_layout_hud_bbox(layout: dict[str, Any], canvas_w: int, canvas_h: int) -> tuple[int, int, int, int]:
    """Compute combined bounding box (x, y, w, h) of enabled indicators in layout."""
    indicators = layout.get("indicators", {})
    custom_texts = layout.get("custom_texts", [])

    enabled_indicators = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}
    if not enabled_indicators and not custom_texts:
        return 0, 0, 2, 2

    min_x, min_y = canvas_w, canvas_h
    max_x, max_y = 0, 0
    has_any = False

    for key, cfg in enabled_indicators.items():
        lx = cfg.get("x", 0.0)
        ly = cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))

        sz = cfg.get("size", cfg.get("font_size", 10.0))
        sw = int(round((sz / 100.0) * canvas_w)) if sz <= 100.0 else int(round(sz))
        sh = int(round((sz / 100.0) * canvas_h)) if sz <= 100.0 else int(round(sz))

        form = cfg.get("form", "")
        if form in ("chart", "moving_map", "static_map"):
            sw = max(sw, int(canvas_w * 0.45))
            sh = max(sh, int(canvas_h * 0.35))

        min_x = min(min_x, max(0, px - 40))
        min_y = min(min_y, max(0, py - 40))
        max_x = max(max_x, min(canvas_w, px + sw + 60))
        max_y = max(max_y, min(canvas_h, py + sh + 60))
        has_any = True

    for ct_cfg in custom_texts:
        lx = ct_cfg.get("x", 0.0)
        ly = ct_cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        min_x = min(min_x, max(0, px - 40))
        min_y = min(min_y, max(0, py - 40))
        max_x = max(max_x, min(canvas_w, px + 500))
        max_y = max(max_y, min(canvas_h, py + 150))
        has_any = True

    if not has_any:
        return 0, 0, 2, 2

    w = max(2, max_x - min_x)
    h = max(2, max_y - min_y)
    if min_x % 2 != 0: min_x -= 1
    if min_y % 2 != 0: min_y -= 1
    if w % 2 != 0: w += 1
    if h % 2 != 0: h += 1

    return min_x, min_y, min(canvas_w - min_x, w), min(canvas_h - min_y, h)


def _build_stream_ffmpeg_cmd(
    ffmpeg_exe: str,
    input_args: list[str],
    output_file: str,
    overlay_w: int,
    overlay_h: int,
    generation_fps: float,
    encoder: str,
    gpu: int,
    video_bitrate: str,
    render_w: int,
    render_h: int,
    resolution_name: str,
    container_rotation: int,
    rotation_degrees: int,
    hwaccel: str | None = None,
    cut_regions: list[tuple[float, float]] | None = None,
    audio_input_args: list[str] | None = None,
    hud_x: int = 0,
    hud_y: int = 0,
    is_no_hud: bool = False,
) -> tuple[list[str], str]:
    """Build the ffmpeg command for the streaming pipeline.

    When *hwaccel* is ``"cuda"`` and no rotation is needed, the GPU
    ``overlay_cuda`` filter is used so that compositing runs on the GPU.
    When manual rotation (90/180/270) is required, the whole chain falls
    back to the CPU (CPU scaling, ``overlay``, CPU rotation filters) so
    that CUDA hardware frames never reach CPU-only filters like
    ``vflip``/``transpose``, which cannot convert them.
    """
    target_res = RESOLUTION_MAP.get(resolution_name)
    needs_cpu_rotation = rotation_degrees in (90, 180, 270)
    has_cuts = bool(cut_regions and len(cut_regions) > 0)
    effective_rotation = container_rotation if container_rotation != 0 else rotation_degrees

    if is_no_hud and encoder == "amd" and not needs_cpu_rotation and not target_res and not has_cuts:
        amf_encoder = "hevc_amf" if _test_encoder("hevc_amf") else "h264_amf"
        cmd = [ffmpeg_exe, "-y", *input_args]
        if audio_input_args:
            cmd.extend(audio_input_args)
        audio_idx = "2" if audio_input_args else "0"
        cmd.extend([
            "-map", "0:v",
            "-map", f"{audio_idx}:a?",
            "-map_metadata", "-1",
            "-metadata:s:v:0", f"rotate={effective_rotation}",
            "-c:v", amf_encoder,
            "-usage", "transcoding",
            "-quality", "speed",
            "-rc", "cbr",
            "-pix_fmt", "nv12",
        ])
        cmd = append_bitrate_args(cmd, encoder, video_bitrate)
        cmd.extend(["-c:a", "copy", output_file])
        return cmd, "direct_gpu_passthrough (zero hwdownload)"

    # ── Base filter (video scaling & format conversion) ───────────────────
    if encoder == "nv" and not needs_cpu_rotation:
        if hwaccel == "cuda":
            if target_res:
                base_filter = f"[0:v]scale_cuda={render_w}:{render_h}:format=yuv420p[base]"
            else:
                base_filter = "[0:v]scale_cuda=format=yuv420p[base]"
        else:
            if target_res:
                base_filter = f"[0:v]hwupload_cuda,scale_cuda={render_w}:{render_h}:format=yuv420p[base]"
            else:
                base_filter = "[0:v]hwupload_cuda,scale_cuda=format=yuv420p[base]"
    elif target_res:
        base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos[base]"
    else:
        base_filter = "[0:v]null[base]"

    # ── Overlay stream & operator ───────────────────────────────────────
    if encoder == "nv" and not needs_cpu_rotation:
        if overlay_w != render_w or overlay_h != render_h:
            ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,scale={overlay_w}:{overlay_h}:flags=bilinear,hwupload_cuda[ov]"
        else:
            ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba,hwupload_cuda[ov]"
        ov_op = f"overlay_cuda=x={hud_x}:y={hud_y}"
    else:
        ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba[ov]"
        ov_op = f"overlay={hud_x}:{hud_y}:shortest=1"

    filter_complex = (
        f"{base_filter};{ov_input};"
        f"[base][ov]{ov_op}[vtemp]"
    )

    # ── Cut region drop (select filter) ────────────────────────────────
    has_cuts = bool(cut_regions and len(cut_regions) > 0)
    if has_cuts:
        # Build select/aselect expression: drop frames in cut regions
        parts = []
        for cs, ce in cut_regions:
            parts.append(f"between(t,{cs},{ce})")
        select_expr = "not(" + "+".join(parts) + ")"
        filter_complex += (
            f";[vtemp]select='{select_expr}',setpts=N/FRAME_RATE/TB[vtemp2]"
        )
        # Audio: aselect – tnie ścieżkę audio tak samo jak wideo
        audio_idx = "2" if audio_input_args else "0"
        filter_complex += (
            f";[{audio_idx}:a]aselect='{select_expr}',asetpts=N/SR/TB[aout]"
        )
        print(f"[CUT] select filter: {select_expr}", flush=True)
        v_last = "[vtemp2]"
    else:
        filter_complex += ";[vtemp]null[vtemp2]"
        v_last = "[vtemp2]"

    # ── Manual rotation (rotation_degrees) ─────────────────────────────
    if rotation_degrees == 180:
        filter_complex += f";{v_last}vflip,hflip[vout]"
    elif rotation_degrees == 90:
        filter_complex += f";{v_last}transpose=1[vout]"
    elif rotation_degrees == 270:
        filter_complex += f";{v_last}transpose=2[vout]"
    else:
        filter_complex += f";{v_last}null[vout]"

    cmd: list[str] = [
        ffmpeg_exe, "-y",
        *input_args,
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{overlay_w}x{overlay_h}",
        "-r", str(generation_fps),
        "-i", "pipe:0",
    ]
    if audio_input_args:
        cmd.extend(audio_input_args)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]",
    ])

    if has_cuts:
        # Gdy są cięcia – audio przechodzi przez aselect, potrzebuje re-encoda
        cmd.extend(["-map", "[aout]?"])
    else:
        # Bez cięć – audio kopiowane wprost z pliku
        audio_idx = "2" if audio_input_args else "0"
        cmd.extend(["-map", f"{audio_idx}:a?"])

    effective_rotation = container_rotation if container_rotation != 0 else rotation_degrees
    cmd.extend([
        "-map_metadata", "-1", "-metadata:s:v:0", f"rotate={effective_rotation}",
    ])

    if encoder == "nv":
        cmd.extend([
            "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
            "-cq", "24",
            "-pix_fmt", "cuda" if (hwaccel == "cuda" and not needs_cpu_rotation) else "yuv420p",
            "-gpu", str(gpu),
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])
    elif encoder == "amd":
        amf_encoder = "hevc_amf" if _test_encoder("hevc_amf") else "h264_amf"
        cmd.extend([
            "-c:v", amf_encoder, "-usage", "transcoding", "-quality", "speed",
            "-rc", "cbr", "-pix_fmt", "nv12",
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])
    elif encoder == "intel":
        cmd.extend([
            "-c:v", "hevc_qsv", "-preset", "veryfast",
            "-global_quality", "24", "-look_ahead", "0",
            "-async_depth", "4", "-pix_fmt", "nv12",
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])
    else:
        cmd.extend([
            "-c:v", "libx265", "-preset", "medium", "-crf", "24",
            "-pix_fmt", "yuv420p",
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])

    cmd = append_bitrate_args(cmd, encoder, video_bitrate)
    cmd.append(str(output_file))
    cmd.extend(["-progress", "pipe:1", "-nostats", "-loglevel", "error"])
    return cmd, filter_complex
