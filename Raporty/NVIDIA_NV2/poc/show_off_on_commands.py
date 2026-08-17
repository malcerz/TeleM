"""Print DEFAULT (CUDA ROT180) vs FALLBACK (CPU) NV command fragments.

Mirrors streaming.py's input-arg decision so the fragments are faithful to the
real `stream_overlay_to_ffmpeg` command.
"""
import os
import sys

BASE = r"F:\_DEV\TeleM"
sys.path.insert(0, BASE)

from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd, is_nv_rot180_cuda  # noqa: E402

RENDER = dict(
    overlay_w=1920, overlay_h=1080, generation_fps=30000 / 1001,
    encoder="nv", gpu=0, video_bitrate="40M",
    render_w=3840, render_h=2160, resolution_name="source",
    container_rotation=180, rotation_degrees=180, hwaccel="cuda",
)


def build(fallback_env):
    if fallback_env is None:
        os.environ.pop("TELEM_NV_ROT180_CPU_FALLBACK", None)
    else:
        os.environ["TELEM_NV_ROT180_CPU_FALLBACK"] = fallback_env
    nv2 = is_nv_rot180_cuda("nv", 180, 180)
    # streaming.py input-arg logic
    needs_cpu_rotation = 180 in (90, 180, 270)
    if nv2:
        needs_cpu_rotation = False
    input_args = ["-hwaccel", "cuda"]
    if not needs_cpu_rotation:
        input_args += ["-hwaccel_output_format", "cuda"]
    input_args += ["-noautorotate", "-i", "GX020079.MP4"]
    cmd, fc = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg", input_args=input_args, output_file="out.mp4", **RENDER
    )
    return nv2, input_args, fc, cmd


def show(label, nv2, input_args, fc, cmd):
    print(f"===== {label}  (cuda_rot180={nv2}) =====")
    print("INPUT_ARGS:", " ".join(input_args))
    print("FILTER:", fc)
    print("PIX_FMT:", cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1])
    print("ROTATE_META:", cmd[cmd.index("-metadata:s:v:0") + 1])


show("DEFAULT (no env) - CUDA ROT180", *build(None))
show("FALLBACK (CPU_FALLBACK=1) - CPU", *build("1"))

