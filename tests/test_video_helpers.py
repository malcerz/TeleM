"""Tests for video_helpers module — extract_frame and get_cached_capture."""

import pytest
from unittest.mock import patch, MagicMock
from src.video_helpers import extract_frame, get_cached_capture


@patch("src.video_helpers.detect_gpu_decoder")
@patch("src.video_helpers.subprocess.run")
@patch("src.video_helpers.ffprobe_stream_info")
def test_extract_frame_passes_preferred_encoder(mock_ffprobe, mock_run, mock_detect):
    """extract_frame should forward preferred_encoder to detect_gpu_decoder."""
    mock_ffprobe.return_value = {"format": {"duration": 100.0}}
    mock_detect.return_value = "d3d11va"

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = b"fake_image_data"
    mock_run.return_value = mock_proc

    with patch("src.video_helpers.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_open.return_value = mock_img
        mock_img.convert.return_value = "fake_rgba"

        result = extract_frame(
            video_paths=["fake.mp4"],
            timestamp_s=10.0,
            preferred_encoder="amd"
        )

        mock_detect.assert_called_once_with("amd")
        assert result == "fake_rgba"


@patch("src.video_helpers.detect_gpu_decoder")
@patch("src.video_helpers.subprocess.run")
@patch("src.video_helpers.ffprobe_stream_info")
def test_extract_frame_hwaccel_in_ffmpeg_cmd(mock_ffprobe, mock_run, mock_detect):
    """When detect_gpu_decoder returns a value, extract_frame should include -hwaccel in the ffmpeg command."""
    mock_ffprobe.return_value = {"format": {"duration": 100.0}}
    mock_detect.return_value = "d3d11va"

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = b"fake_image_data"
    mock_run.return_value = mock_proc

    with patch("src.video_helpers.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_open.return_value = mock_img
        mock_img.convert.return_value = "fake_rgba"

        extract_frame(
            video_paths=["fake.mp4"],
            timestamp_s=10.0,
            preferred_encoder="amd"
        )

        # Check first call args include -hwaccel d3d11va
        first_call_args = mock_run.call_args_list[0]
        cmd = first_call_args[0][0]
        assert "-hwaccel" in cmd
        assert "d3d11va" in cmd


@patch("src.video_helpers.detect_gpu_decoder")
@patch("src.video_helpers.subprocess.run")
@patch("src.video_helpers.ffprobe_stream_info")
def test_extract_frame_no_hwaccel_when_none(mock_ffprobe, mock_run, mock_detect):
    """When detect_gpu_decoder returns None, -hwaccel should not be in the command."""
    mock_ffprobe.return_value = {"format": {"duration": 100.0}}
    mock_detect.return_value = None

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = b"fake_image_data"
    mock_run.return_value = mock_proc

    with patch("src.video_helpers.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_open.return_value = mock_img
        mock_img.convert.return_value = "fake_rgba"

        extract_frame(
            video_paths=["fake.mp4"],
            timestamp_s=5.0,
        )

        first_call_args = mock_run.call_args_list[0]
        cmd = first_call_args[0][0]
        assert "-hwaccel" not in cmd


def test_get_cached_capture_graceful_without_cv2():
    """get_cached_capture should return None when cv2 is not available."""
    from src.video_helpers import _CV2_CAP_CACHE
    _CV2_CAP_CACHE.clear()

    with patch.dict("sys.modules", {"cv2": None}):
        result = get_cached_capture("nonexistent.mp4")
        assert result is None


def test_encoder_fallback_on_unsupported_gpu():
    """When nvenc is not supported (e.g. on AMD system), validation should fallback to best encoder."""
    from src.ffmpeg_pipeline import detect_best_encoder, _test_encoder
    with patch("src.ffmpeg_pipeline._test_encoder") as mock_test:
        def _mock_test_impl(name):
            return name in ("hevc_amf", "h264_amf")
        mock_test.side_effect = _mock_test_impl

        # detect_best_encoder should detect amd
        with patch("subprocess.run") as mock_run:
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = " V....D hevc_amf\n V....D h264_amf\n"
            mock_run.return_value = mock_res
            best = detect_best_encoder()
            assert best == "amd"


def test_smart_canvas_scaling_filter_cmd():
    """When overlay_w != render_w, _build_stream_ffmpeg_cmd should include scale filter for overlay stream."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd
    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg",
        input_args=["-i", "test.mp4"],
        output_file="out.mp4",
        overlay_w=1920,
        overlay_h=1080,
        generation_fps=30.0,
        encoder="amd",
        gpu=0,
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        container_rotation=0,
        rotation_degrees=0,
    )
    assert "scale=3840:2160" in filter_complex


def test_nv_cuda_rotation_uses_cpu_chain():
    """NVIDIA + CUDA + manual rotation must NOT use GPU filters: vflip/hflip are
    CPU-only and cannot consume CUDA frames (see 'Impossible to convert between
    the formats supported by the filter Parsed_vflip...')."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd
    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg",
        input_args=["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", "test.mp4"],
        output_file="out.mp4",
        overlay_w=1920,
        overlay_h=1080,
        generation_fps=30.0,
        encoder="nv",
        gpu=0,
        video_bitrate="40M",
        render_w=1920,
        render_h=1080,
        resolution_name="source",
        container_rotation=0,
        rotation_degrees=180,
        hwaccel="cuda",
    )
    # GPU compositing must be bypassed for rotation
    assert "overlay_cuda" not in filter_complex
    assert "hwupload_cuda" not in filter_complex
    # CPU rotation must still be applied
    assert "vflip,hflip" in filter_complex
    # Encoder must receive system-memory frames, not CUDA frames
    c_idx = cmd.index("-c:v")
    pix_idx = cmd.index("-pix_fmt", c_idx)
    assert cmd[pix_idx + 1] == "yuv420p"


def test_nv_cuda_no_rotation_keeps_gpu_chain():
    """Regression: NVIDIA + CUDA without rotation keeps the GPU overlay_cuda
    chain and CUDA-frame output so nvenc stays fully GPU-accelerated."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd
    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg",
        input_args=["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", "test.mp4"],
        output_file="out.mp4",
        overlay_w=1920,
        overlay_h=1080,
        generation_fps=30.0,
        encoder="nv",
        gpu=0,
        video_bitrate="40M",
        render_w=1920,
        render_h=1080,
        resolution_name="source",
        container_rotation=0,
        rotation_degrees=0,
        hwaccel="cuda",
    )
    assert "overlay_cuda" in filter_complex
    assert "hwupload_cuda" in filter_complex
    c_idx = cmd.index("-c:v")
    pix_idx = cmd.index("-pix_fmt", c_idx)
    assert cmd[pix_idx + 1] == "cuda"


def test_intel_and_cpu_pipeline_unchanged():
    """Intel and CPU (libx265) must keep their exact compression settings
    regardless of rotation - they already use the CPU chain."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd

    def _encoder_args(cmd: list) -> list:
        # Encoder block is appended from '-c:v' onwards; compare only that part
        return cmd[cmd.index("-c:v"):]

    base_kwargs = dict(
        ffmpeg_exe="ffmpeg",
        input_args=["-i", "test.mp4"],
        output_file="out.mp4",
        overlay_w=1920,
        overlay_h=1080,
        generation_fps=30.0,
        gpu=0,
        video_bitrate="40M",
        render_w=1920,
        render_h=1080,
        resolution_name="source",
        container_rotation=0,
    )
    # Intel (QSV) - rotation must not alter the encoder settings
    intel_cmd, intel_fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, **base_kwargs,
    )
    intel_cmd_r, intel_fc_r = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=180, **base_kwargs,
    )
    assert "hevc_qsv" in intel_cmd
    assert intel_cmd[intel_cmd.index("-pix_fmt", intel_cmd.index("-c:v")) + 1] == "nv12"
    assert _encoder_args(intel_cmd) == _encoder_args(intel_cmd_r)
    assert "overlay_cuda" not in intel_fc_r
    assert "vflip,hflip" in intel_fc_r

    # CPU (libx265) - rotation must not alter the encoder settings
    cpu_cmd, cpu_fc = _build_stream_ffmpeg_cmd(
        encoder="cpu", rotation_degrees=0, **base_kwargs,
    )
    cpu_cmd_r, cpu_fc_r = _build_stream_ffmpeg_cmd(
        encoder="cpu", rotation_degrees=180, **base_kwargs,
    )
    assert "libx265" in cpu_cmd
    assert cpu_cmd[cpu_cmd.index("-pix_fmt", cpu_cmd.index("-c:v")) + 1] == "yuv420p"
    assert _encoder_args(cpu_cmd) == _encoder_args(cpu_cmd_r)
    assert "overlay_cuda" not in cpu_fc_r
    assert "vflip,hflip" in cpu_fc_r


