"""FFmpeg command line arguments builder.
"""

from __future__ import annotations

import os
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

# NVIDIA rotation=180 CUDA fast-path (production default).
#
# For encoder == "nv" and effective rotation == 180 the CUDA fast-path
# (scale_cuda / overlay_cuda / -pix_fmt cuda, HUD canvas rotated 180 deg in
# Python, displaymatrix rotate=180 injected into the container) is the DEFAULT
# production path. It is NOT gated by an enable flag.
#
# Legacy opt-out (forces the old CPU path: vflip,hflip + software scale/overlay
# + hevc_nvenc yuv420p): TELEM_NV_ROT180_CPU_FALLBACK=1 (truthy, case/whitespace-
# insensitive). Unset/""/"0"/"false"/"no" → CUDA fast-path stays active.
# rotation 0 / 90 / 270 and non-NVIDIA encoders are unaffected.
NV_ROT180_CPU_FALLBACK_ENV = "TELEM_NV_ROT180_CPU_FALLBACK"
_NV_ROT180_ON_VALUES = {"1", "true", "yes", "on"}


def _env_flag_on(name: str) -> bool:
    """True only when the env var is explicitly in the ON set (default OFF)."""
    return os.environ.get(name, "").strip().lower() in _NV_ROT180_ON_VALUES


def is_nv_rot180_cuda(
    encoder: str,
    rotation_degrees: int,
    container_rotation: int = 0,
) -> bool:
    """Return True when NVIDIA rotation=180 uses the CUDA fast-path.

    Default ON for encoder == "nv" and effective rotation == 180.
    Opt-out: TELEM_NV_ROT180_CPU_FALLBACK truthy forces the legacy CPU path.
    rotation 0 / 90 / 270 and non-NVIDIA encoders are unaffected.
    """
    if encoder != "nv":
        return False
    effective = container_rotation if container_rotation != 0 else rotation_degrees
    if effective != 180:
        return False
    return not _env_flag_on(NV_ROT180_CPU_FALLBACK_ENV)



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

def get_layout_hud_regions(
    layout: dict[str, Any], canvas_w: int, canvas_h: int, max_regions: int = 3
) -> tuple[int, int, list[tuple[int, int, int, int, int, int]]]:
    """Compute compact multi-region atlas bounds for layout.

    Returns:
        atlas_w, atlas_h, regions
        where regions is a list of (dest_x, dest_y, src_x, src_y, region_w, region_h)
    """
    indicators = layout.get("indicators", {})
    custom_texts = layout.get("custom_texts", [])
    enabled_indicators = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}

    if not enabled_indicators and not custom_texts:
        return 2, 2, [(0, 0, 0, 0, 2, 2)]

    boxes = []
    for key, cfg in enabled_indicators.items():
        lx = cfg.get("x", 0.0)
        ly = cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        sz = cfg.get("size", cfg.get("font_size", 10.0))
        sw = int(round((sz / 100.0) * canvas_w)) if sz <= 100.0 else int(round(sz))
        sh = int(round((sz / 100.0) * canvas_h)) if sz <= 100.0 else int(round(sz))

        form = cfg.get("form", "text")
        if form in ("chart", "moving_map", "static_map", "map") or "map" in key or "chart" in key:
            sw = max(sw, int(canvas_w * 0.45))
            sh = max(sh, int(canvas_h * 0.45))
        elif form == "gauge" or "gauge" in key:
            sw = max(sw, int(canvas_w * 0.35))
            sh = max(sh, int(canvas_h * 0.50))
        elif "time" in key or "date" in key or form in ("time", "date"):
            sw = max(sw, int(canvas_w * 0.25))
            sh = max(sh, int(canvas_h * 0.15))
        else:
            sw = max(sw, int(canvas_w * 0.20))
            sh = max(sh, int(canvas_h * 0.15))

        is_text = (form == "text") or (key in ("time_block", "time_display"))

        if not is_text:
            x1 = max(0, px - sw // 2 - 60)
            y1 = max(0, py - sh // 2 - 60)
            x2 = min(canvas_w, px + sw // 2 + 60)
            y2 = min(canvas_h, py + sh // 2 + 60)
        else:
            x1 = max(0, px - 40)
            y1 = max(0, py - 40)
            x2 = min(canvas_w, px + sw + 60)
            y2 = min(canvas_h, py + sh + 60)

        boxes.append([x1, y1, x2, y2])

    for ct_cfg in custom_texts:
        lx = ct_cfg.get("x", 0.0)
        ly = ct_cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        sw = int(canvas_w * 0.25)
        sh = int(canvas_h * 0.15)
        boxes.append([max(0, px - sw // 2 - 40), max(0, py - sh // 2 - 40), min(canvas_w, px + sw // 2 + 40), min(canvas_h, py + sh // 2 + 40)])

    clusters = [[b[0], b[1], b[2], b[3]] for b in boxes]

    while len(clusters) > max_regions:
        best_pair = None
        best_waste = float("inf")
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                b1, b2 = clusters[i], clusters[j]
                mb = [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]
                ma = (mb[2] - mb[0]) * (mb[3] - mb[1])
                a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
                a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
                waste = ma - (a1 + a2)
                if waste < best_waste:
                    best_waste = waste
                    best_pair = (i, j)

        if best_pair is None:
            break
        i, j = best_pair
        b1, b2 = clusters[i], clusters[j]
        mb = [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]
        clusters.pop(j)
        clusters.pop(i)
        clusters.append(mb)

    sorted_clusters = sorted(clusters, key=lambda c: (c[3] - c[1]), reverse=True)
    regions = []
    shelf_x = 0
    shelf_y = 0
    current_shelf_h = 0
    atlas_max_x = 0
    atlas_max_y = 0
    max_shelf_w = canvas_w

    for c in sorted_clusters:
        x1, y1, x2, y2 = c
        w = max(2, x2 - x1)
        h = max(2, y2 - y1)
        if x1 % 2 != 0: x1 -= 1
        if y1 % 2 != 0: y1 -= 1
        if w % 2 != 0: w += 1
        if h % 2 != 0: h += 1
        w = min(canvas_w - x1, w)
        h = min(canvas_h - y1, h)

        if shelf_x + w > max_shelf_w and shelf_x > 0:
            shelf_x = 0
            shelf_y += current_shelf_h
            current_shelf_h = 0

        regions.append((x1, y1, shelf_x, shelf_y, w, h))
        shelf_x += w
        current_shelf_h = max(current_shelf_h, h)

        atlas_max_x = max(atlas_max_x, shelf_x)
        atlas_max_y = max(atlas_max_y, shelf_y + current_shelf_h)

    atlas_w = max(2, atlas_max_x)
    atlas_h = max(2, atlas_max_y)
    if atlas_w % 2 != 0: atlas_w += 1
    if atlas_h % 2 != 0: atlas_h += 1

    return atlas_w, atlas_h, regions


def _build_stream_ffmpeg_cmd(
    ffmpeg_exe: str,
    input_args: list[str],
    output_file: str,
    canvas_w: int = 1920,
    canvas_h: int = 1080,
    stream_w: int = 1920,
    stream_h: int = 1080,
    generation_fps: float = 30.0,
    encoder: str = "cpu",
    gpu: int = 0,
    video_bitrate: str = "25M",
    render_w: int = 3840,
    render_h: int = 2160,
    resolution_name: str = "4k",
    container_rotation: int = 0,
    rotation_degrees: int = 0,
    hwaccel: str | None = None,
    cut_regions: list[tuple[float, float]] | None = None,
    audio_input_args: list[str] | None = None,
    hud_x: int = 0,
    hud_y: int = 0,
    is_no_hud: bool = False,
    hud_regions: list[tuple[int, int, int, int, int, int]] | None = None,
    overlay_w: int | None = None,
    overlay_h: int | None = None,
    use_gpu_compositor: bool = False,
) -> tuple[list[str], str]:
    if overlay_w is not None:
        canvas_w = overlay_w
        if stream_w == 1920 and overlay_w != 1920:
            stream_w = overlay_w
    if overlay_h is not None:
        canvas_h = overlay_h
        if stream_h == 1080 and overlay_h != 1080:
            stream_h = overlay_h
    """Build the ffmpeg command for the streaming pipeline.

    When *hwaccel* is ``"cuda"`` and no rotation is needed, the GPU
    ``overlay_cuda`` filter is used so that compositing runs on the GPU.
    When manual rotation (90/180/270) is required, the whole chain falls
    back to the CPU (CPU scaling, ``overlay``, CPU rotation filters) so
    that CUDA hardware frames never reach CPU-only filters like
    ``vflip``/``transpose``, which cannot convert them.
    """
    target_res = RESOLUTION_MAP.get(resolution_name)
    nv_rot180_cuda = is_nv_rot180_cuda(encoder, rotation_degrees, container_rotation)
    needs_cpu_rotation = rotation_degrees in (90, 180, 270)
    if nv_rot180_cuda:
        # NVIDIA rotation=180: handled on the CUDA path (HUD canvas rotated in
        # Python), so it is NOT treated as a CPU-rotation case for the NVIDIA branch.
        needs_cpu_rotation = False
    has_cuts = bool(cut_regions and len(cut_regions) > 0)
    effective_rotation = container_rotation if container_rotation != 0 else rotation_degrees

    no_res_change = not target_res or (render_w == canvas_w and render_h == canvas_h)
    if is_no_hud and encoder == "amd" and not needs_cpu_rotation and no_res_change and not has_cuts:
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
    elif encoder == "amd" and not needs_cpu_rotation:
        if effective_rotation == 180:
            base_filter = "[0:v]format=nv12,vflip,hflip[base]"
        elif effective_rotation == 90:
            base_filter = "[0:v]format=nv12,transpose=1[base]"
        elif effective_rotation == 270:
            base_filter = "[0:v]format=nv12,transpose=2[base]"
        else:
            base_filter = "[0:v]format=nv12[base]"
    elif target_res:
        if effective_rotation == 180:
            base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos,vflip,hflip[base]"
        elif effective_rotation == 90:
            base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos,transpose=1[base]"
        elif effective_rotation == 270:
            base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos,transpose=2[base]"
        else:
            base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos[base]"
    else:
        if effective_rotation == 180:
            base_filter = "[0:v]vflip,hflip[base]"
        elif effective_rotation == 90:
            base_filter = "[0:v]transpose=1[base]"
        elif effective_rotation == 270:
            base_filter = "[0:v]transpose=2[base]"
        else:
            base_filter = "[0:v]null[base]"

    scale_x = render_w / canvas_w if canvas_w > 0 else 1.0
    scale_y = render_h / canvas_h if canvas_h > 0 else 1.0

    # ── Overlay stream & operator ───────────────────────────────────────
    if encoder == "nv" and not needs_cpu_rotation:
        if stream_w != render_w or stream_h != render_h:
            ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,scale={render_w}:{render_h}:flags=bilinear,hwupload_cuda[ov]"
        else:
            ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba,hwupload_cuda[ov]"
        ov_op = f"overlay_cuda=x={hud_x}:y={hud_y}"
        filter_complex = f"{base_filter};{ov_input};[base][ov]{ov_op}[vtemp]"
    elif encoder == "amd" and use_gpu_compositor and not needs_cpu_rotation:
        if "-init_hw_device" not in input_args:
            input_args = ["-init_hw_device", "opencl=ocl", "-filter_hw_device", "ocl", *input_args]

        if effective_rotation == 180:
            base_filter = "[0:v]format=nv12,vflip,hflip,hwupload[base]"
        elif effective_rotation == 90:
            base_filter = "[0:v]format=nv12,transpose=1,hwupload[base]"
        elif effective_rotation == 270:
            base_filter = "[0:v]format=nv12,transpose=2,hwupload[base]"
        else:
            base_filter = "[0:v]format=nv12,hwupload[base]"

        if stream_w != render_w or stream_h != render_h:
            ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,scale={render_w}:{render_h}:flags=bilinear,hwupload[ov]"
        else:
            ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba,hwupload[ov]"

        filter_complex = f"{base_filter};{ov_input};[base][ov]overlay_opencl[v_ocl];[v_ocl]hwdownload,format=nv12[vtemp]"
    elif hud_regions and len(hud_regions) > 1:
        n_reg = len(hud_regions)
        split_labels = "".join([f"[ov_raw_{i}]" for i in range(n_reg)])
        ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,split={n_reg}{split_labels}"

        crop_ops = []
        overlay_ops = []
        curr_base = "[base]"
        for i, r in enumerate(hud_regions):
            dest_x, dest_y, src_x, src_y, rw, rh = r
            s_dest_x = int(round(dest_x * scale_x))
            s_dest_y = int(round(dest_y * scale_y))
            s_src_x = src_x
            s_src_y = src_y
            s_rw = int(round(rw * scale_x))
            s_rh = int(round(rh * scale_y))
            if s_rw % 2 != 0: s_rw += 1
            if s_rh % 2 != 0: s_rh += 1

            if scale_x != 1.0 or scale_y != 1.0:
                crop_ops.append(f"[ov_raw_{i}]crop={rw}:{rh}:{src_x}:{src_y},scale={s_rw}:{s_rh}:flags=bilinear[ov_{i}]")
            else:
                crop_ops.append(f"[ov_raw_{i}]crop={rw}:{rh}:{src_x}:{src_y}[ov_{i}]")

            next_base = f"[v_step_{i}]" if i < n_reg - 1 else "[vtemp]"
            overlay_ops.append(
                f"{curr_base}[ov_{i}]overlay={s_dest_x}:{s_dest_y}{':shortest=1' if i == n_reg - 1 else ''}{next_base}"
            )
            curr_base = next_base

        filter_complex = (
            f"{base_filter};{ov_input};" + ";".join(crop_ops) + ";" + ";".join(overlay_ops)
        )
    else:
        s_hud_x = int(round(hud_x * scale_x))
        s_hud_y = int(round(hud_y * scale_y))
        if scale_x != 1.0 or scale_y != 1.0:
            s_stream_w = int(round(stream_w * scale_x))
            s_stream_h = int(round(stream_h * scale_y))
            if s_stream_w % 2 != 0: s_stream_w += 1
            if s_stream_h % 2 != 0: s_stream_h += 1
            ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,scale={s_stream_w}:{s_stream_h}:flags=bilinear[ov]"
        else:
            ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba[ov]"
        ov_op = f"overlay={s_hud_x}:{s_hud_y}:shortest=1"
        filter_complex = f"{base_filter};{ov_input};[base][ov]{ov_op}[vtemp]"

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

    filter_complex += f";{v_last}null[vout]"

    cmd: list[str] = [
        ffmpeg_exe, "-y",
        *input_args,
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{stream_w}x{stream_h}",
        "-r", str(generation_fps),
        "-i", "pipe:0",
    ]
    if audio_input_args:
        cmd.extend(audio_input_args)
    # NV1: NVIDIA-only filter_complex_threads override.
    # Set TELEM_NV_FILTER_COMPLEX_THREADS=2 or =4 to A/B test.
    # Has NO effect for encoder != "nv".
    _nv_fct_raw = os.environ.get("TELEM_NV_FILTER_COMPLEX_THREADS", "").strip()
    _nv_fct: int | None = None
    if encoder == "nv" and _nv_fct_raw:
        try:
            _nv_fct = int(_nv_fct_raw)
            if _nv_fct < 1:
                _nv_fct = None
        except ValueError:
            _nv_fct = None

    if _nv_fct is not None:
        cmd.extend(["-filter_complex_threads", str(_nv_fct)])
        print(f"[NV1] filter_complex_threads={_nv_fct}", flush=True)

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

    # Metadane obrotu: normalnie obrót jest fizycznie zaaplikowany w base_filter,
    # więc w metadanych piszemy rotate=0. W CUDA ROT180 (NVIDIA rotation=180)
    # obraz pozostaje fizycznie nieobrócony (base video + HUD obrócony 180 w
    # Pythonie), a poprawny displaymatrix rotate=180 jest wstrzykiwany do
    # kontenera po zakończeniu (src.ffmpeg.displaymatrix) — tag rotate=180 pełni
    # rolę zapasową.
    out_rotation = 180 if nv_rot180_cuda else 0
    cmd.extend([
        "-map_metadata", "-1", "-metadata:s:v:0", f"rotate={out_rotation}",
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
