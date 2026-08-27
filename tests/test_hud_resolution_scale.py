"""Contract tests for export HUD raster resolution."""

from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd


def test_480p_hud_scale_75_is_upscaled_to_export_canvas():
    _, filt = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg",
        input_args=["-i", "input.mp4"],
        output_file="out.mp4",
        overlay_w=640,
        overlay_h=360,
        generation_fps=30.0,
        encoder="cpu",
        render_w=854,
        render_h=480,
        resolution_name="480p",
    )
    assert "scale=854:480" in filt


def test_hud_100_percent_is_noop_for_matching_canvas():
    _, filt = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg",
        input_args=["-i", "input.mp4"],
        output_file="out.mp4",
        overlay_w=1920,
        overlay_h=1080,
        generation_fps=30.0,
        encoder="cpu",
        render_w=1920,
        render_h=1080,
        resolution_name="1080p",
    )
    assert "format=rgba,scale=" not in filt
