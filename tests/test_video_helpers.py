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
        resolution_name="4k",
        container_rotation=0,
        rotation_degrees=0,
    )
    assert "scale=3840:2160" in filter_complex


def test_nv_cuda_rotation_uses_cpu_chain(monkeypatch):
    """NVIDIA + CUDA + manual rotation (180 forced to CPU fallback) must NOT use
    GPU filters: vflip/hflip are CPU-only and cannot consume CUDA frames (see
    'Impossible to convert between the formats supported by the filter
    Parsed_vflip...'). This is the legacy CPU fallback path, forced via
    TELEM_NV_ROT180_CPU_FALLBACK."""
    monkeypatch.setenv("TELEM_NV_ROT180_CPU_FALLBACK", "1")
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
    # GPU compositing must be bypassed for the CPU fallback
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
        encoder="intel", rotation_degrees=180,
        **{**base_kwargs, "container_rotation": 180},
    )
    assert "hevc_qsv" in intel_cmd
    assert intel_cmd[intel_cmd.index("-pix_fmt", intel_cmd.index("-c:v")) + 1] == "nv12"
    assert _encoder_args(intel_cmd) == _encoder_args(intel_cmd_r)
    assert "overlay_cuda" not in intel_fc_r
    # ETAP 5D: autorotate contract -- no baked manual flips for Intel.
    assert "vflip,hflip" not in intel_fc_r
    assert "hwdownload,format=nv12" in intel_fc
    assert "overlay_qsv" not in intel_fc

    intel_10_cmd, intel_10_fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, intel_cpu_download_format="p010le", **base_kwargs,
    )
    assert "hwdownload,format=p010le" in intel_10_fc
    assert "-pix_fmt" in intel_10_cmd
    assert intel_10_cmd[intel_10_cmd.index("-pix_fmt", intel_10_cmd.index("-c:v")) + 1] == "p010le"

    intel_hdr_cmd, intel_hdr_fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, intel_cpu_download_format="p010le",
        intel_cpu_software_decode=True, **base_kwargs,
    )
    assert "[0:v]format=p010le" in intel_hdr_fc
    assert "hwdownload" not in intel_hdr_fc
    assert intel_hdr_cmd[intel_hdr_cmd.index("-pix_fmt", intel_hdr_cmd.index("-c:v")) + 1] == "p010le"

    intel_native_cmd, intel_native_fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, intel_gpu_resident=True, **base_kwargs,
    )
    assert "overlay_qsv" in intel_native_fc
    assert "hwupload=derive_device=qsv" in intel_native_fc
    assert "scale_qsv" not in intel_native_fc
    assert "overlay_cuda" not in intel_native_fc
    assert "hwdownload" not in intel_native_fc
    assert all(token not in intel_native_cmd for token in ("cuda", "nvenc", "amf"))

    region_cmd, region_fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, intel_gpu_resident=True,
        stream_w=704, stream_h=410, hud_x=102, hud_y=50, **base_kwargs,
    )
    assert "-s" in region_cmd
    assert region_cmd[region_cmd.index("-s") + 1] == "704x410"
    assert "overlay_qsv=x=102:y=50" in region_fc
    assert "hwdownload" not in region_fc

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


def _cpu_ref_kwargs(**overrides):
    base = dict(
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
    )
    base.update(overrides)
    return base


# ── INTEL ETAP 4A: CPU_REFERENCE bounded-HUD transport ───────────────────────

def test_intel_cpu_ref_region_graph():
    """CPU_REFERENCE + REGION: rawvideo input shrinks to the bbox and the SW
    overlay is positioned at the bbox origin; QSV decode/download stays nv12."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd

    cmd, fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, container_rotation=0,
        stream_w=704, stream_h=410, hud_x=102, hud_y=50,
        intel_gpu_resident=False, **_cpu_ref_kwargs(),
    )
    assert "-s" in cmd
    assert cmd[cmd.index("-s") + 1] == "704x410"
    assert "overlay=102:50" in fc
    assert "hwdownload,format=nv12" in fc
    assert "overlay_qsv" not in fc
    assert "hevc_qsv" in cmd
    assert cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "nv12"


def test_intel_cpu_ref_region_rotation_graphs():
    """ETAP 5D contract: Intel relies on import autorotate -- the REGION graph
    must NOT bake manual rotation transforms anymore, and the HUD overlay x/y
    stays in the shared upright coordinate space."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd

    for rotation, token in ((90, "transpose=1"), (180, "vflip,hflip"), (270, "transpose=2")):
        cmd, fc = _build_stream_ffmpeg_cmd(
            encoder="intel", rotation_degrees=rotation, container_rotation=rotation,
            stream_w=704, stream_h=410, hud_x=102, hud_y=50,
            intel_gpu_resident=False, **_cpu_ref_kwargs(),
        )
        assert token not in fc, rotation
        assert "overlay=102:50" in fc, rotation
        assert cmd[cmd.index("-s") + 1] == "704x410", rotation


def test_intel_cpu_ref_region_hdr_p010_graph():
    """HDR/P010 CPU_REFERENCE with REGION: software decode stays hwdownload-free."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd

    cmd, fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, container_rotation=0,
        stream_w=704, stream_h=410, hud_x=102, hud_y=50,
        intel_gpu_resident=False,
        intel_cpu_software_decode=True,
        intel_cpu_download_format="p010le",
        **_cpu_ref_kwargs(),
    )
    assert "hwdownload" not in fc
    assert "format=p010le[base]" in fc
    assert "overlay=102:50" in fc
    assert cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "p010le"


def test_intel_hud_region_gate_switches(monkeypatch):
    """ETAP 3C/4A gate: native keeps its switch; CPU_REFERENCE has its own
    switch and is limited to unrotated projects."""
    from src.ffmpeg.streaming import _intel_hud_region_gate as gate

    monkeypatch.delenv("TELEM_INTEL_HUD_REGION", raising=False)
    monkeypatch.delenv("TELEM_INTEL_CPU_REF_HUD_REGION", raising=False)
    # Native: ETAP 3C switch decides; rotation is irrelevant for native.
    assert gate(True, 180, 180) is True
    monkeypatch.setenv("TELEM_INTEL_HUD_REGION", "0")
    assert gate(True, 0, 0) is False
    monkeypatch.delenv("TELEM_INTEL_HUD_REGION", raising=False)

    # CPU_REFERENCE: default ON.  ETAP 5D: with the Intel autorotate import
    # contract, source rotation no longer forces FULL_CANVAS; other encoders
    # (legacy call shape without encoder=) keep the unrotated-only rule.
    assert gate(False, 0, 0) is True
    assert gate(False, 180, 180, "intel") is True
    assert gate(False, 180, 0) is False
    assert gate(False, 90, 0) is False
    assert gate(False, 0, 270) is False
    # Kill switch applies to both shapes.
    monkeypatch.setenv("TELEM_INTEL_CPU_REF_HUD_REGION", "0")
    assert gate(False, 0, 0) is False
    assert gate(False, 180, 180, "intel") is False


# ── INTEL ETAP 4B: measured REGION eligibility + scale!=1 graphs ─────────────

def _ratio_layout():
    """Two corner text indicators -> wide union bbox (>0.85 of 1080p canvas)."""
    return {"indicators": {
        "speed_text": {"type": "speed_text", "x": 140, "y": 140,
                       "width": 220, "height": 80, "enabled": True},
        "dist_text": {"type": "dist_text", "x": 1560, "y": 1040,
                      "width": 220, "height": 70, "enabled": True},
    }}


def _small_layout():
    return {"indicators": {
        "speed_text": {"type": "speed_text", "x": 200, "y": 200,
                       "width": 220, "height": 80, "enabled": True},
    }}


def test_intel_hud_region_decision_threshold(monkeypatch):
    """ETAP 4B policy: default 0.85 gate, env-overridable, even-aligned crop."""
    from src.ffmpeg.streaming import _intel_hud_region_decision as decide

    monkeypatch.delenv("TELEM_INTEL_CPU_REF_HUD_REGION_MAX_RATIO",
                       raising=False)
    # Small cluster -> REGION with an even-aligned rectangle.
    hx, hy, sw, sh, ratio, mode = decide(_small_layout(), 1920, 1080)
    assert mode == "region"
    assert 0.0 < ratio < 0.5
    assert hx % 2 == 0 and hy % 2 == 0 and sw % 2 == 0 and sh % 2 == 0
    assert sw <= 1920 and sh <= 1080

    # Corner-spread layout crosses the default threshold -> FULL fallback.
    _, _, _, _, ratio_big, mode_big = decide(_ratio_layout(), 1920, 1080)
    assert mode_big == "full_threshold"
    assert ratio_big >= 0.85

    # Threshold override: raising it re-enables REGION for the same layout;
    # lowering it forces FULL even for the small cluster.
    monkeypatch.setenv("TELEM_INTEL_CPU_REF_HUD_REGION_MAX_RATIO", "0.9")
    assert decide(_ratio_layout(), 1920, 1080)[5] == "region"
    monkeypatch.setenv("TELEM_INTEL_CPU_REF_HUD_REGION_MAX_RATIO", "0.03")
    assert decide(_small_layout(), 1920, 1080)[5] == "full_threshold"


def test_intel_cpu_ref_region_scale_target_res_graph():
    """CPU_REFERENCE + REGION + target_res != source: base scales via lanczos
    after hwdownload while HUD keeps its bbox geometry (canvas == render)."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd

    cmd, fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, container_rotation=0,
        stream_w=476, stream_h=216, hud_x=530, hud_y=280,
        intel_gpu_resident=False,
        render_w=1280, render_h=720,
        resolution_name="720p",
        overlay_w=1280, overlay_h=720,
        ffmpeg_exe="ffmpeg", input_args=["-i", "test.mp4"],
        output_file="out.mp4", generation_fps=30.0, gpu=0,
        video_bitrate="40M",
    )
    assert "hwdownload,format=nv12,scale=1280:720:flags=lanczos" in fc
    assert "overlay=530:280" in fc
    assert cmd[cmd.index("-s") + 1] == "476x216"
    assert cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "nv12"


def test_intel_cpu_ref_region_canvas_scale_graph():
    """HUD canvas smaller than render: the bbox is bilinear-scaled by
    scale_x/scale_y and positioned at the rounded scaled origin."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd

    cmd, fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, container_rotation=0,
        stream_w=176, stream_h=108, hud_x=265, hud_y=140,
        intel_gpu_resident=False,
        render_w=1280, render_h=720,
        resolution_name="source",
        overlay_w=640, overlay_h=360,
        ffmpeg_exe="ffmpeg", input_args=["-i", "test.mp4"],
        output_file="out.mp4", generation_fps=30.0, gpu=0,
        video_bitrate="40M",
    )
    # scale_x = render/canvas = 2.0 -> 176*2 x 108*2 and 265*2/140*2
    assert "format=rgba,scale=352:216:flags=bilinear" in fc
    assert "overlay=530:280" in fc
    assert cmd[cmd.index("-s") + 1] == "176x108"


# ── NVIDIA ROT180 CUDA fast-path (production default) ────────────────────────

def _nv_cmd(rotation_degrees=180, container_rotation=0, hwaccel="cuda",
            render_w=3840, render_h=2160, resolution_name="4k"):
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd
    input_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", "test.mp4"]
    if container_rotation != 0:
        input_args.insert(0, "-noautorotate")
    return _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg",
        input_args=input_args,
        output_file="out.mp4",
        overlay_w=1920,
        overlay_h=1080,
        generation_fps=30.0,
        encoder="nv",
        gpu=0,
        video_bitrate="40M",
        render_w=render_w,
        render_h=render_h,
        resolution_name=resolution_name,
        container_rotation=container_rotation,
        rotation_degrees=rotation_degrees,
        hwaccel=hwaccel,
    )


def test_nv_rotation0_cuda_normal(monkeypatch):
    """rotation=0 keeps the plain NVIDIA CUDA path (unchanged)."""
    monkeypatch.delenv("TELEM_NV_ROT180_CPU_FALLBACK", raising=False)
    cmd, filter_complex = _nv_cmd(rotation_degrees=0, container_rotation=0,
                                  render_w=1920, render_h=1080, resolution_name="source")
    assert "scale_cuda" in filter_complex
    assert "overlay_cuda" in filter_complex
    assert "vflip,hflip" not in filter_complex
    assert "transpose" not in filter_complex
    assert cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "cuda"
    assert cmd[cmd.index("-metadata:s:v:0") + 1] == "rotate=0"


def test_nv_rotation180_cuda_default(monkeypatch):
    """rotation=180 uses the CUDA ROT180 fast-path by DEFAULT (no env needed)."""
    monkeypatch.delenv("TELEM_NV_ROT180_CPU_FALLBACK", raising=False)
    cmd, filter_complex = _nv_cmd(rotation_degrees=180, container_rotation=180)
    assert "vflip,hflip" not in filter_complex
    assert "scale_cuda" in filter_complex
    assert "overlay_cuda" in filter_complex
    assert "hwupload_cuda" in filter_complex
    assert cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "cuda"
    assert cmd[cmd.index("-metadata:s:v:0") + 1] == "rotate=180"


@pytest.mark.parametrize("env_value", ["1", "true", "yes", "on", "TRUE", " On "])
def test_nv_rotation180_cpu_fallback(monkeypatch, env_value):
    """TELEM_NV_ROT180_CPU_FALLBACK truthy forces the old CPU path for 180."""
    monkeypatch.setenv("TELEM_NV_ROT180_CPU_FALLBACK", env_value)
    cmd, filter_complex = _nv_cmd(rotation_degrees=180, container_rotation=180)
    assert "overlay_cuda" not in filter_complex
    assert "hwupload_cuda" not in filter_complex
    assert "scale_cuda" not in filter_complex
    assert "vflip,hflip" in filter_complex
    assert cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "yuv420p"
    assert cmd[cmd.index("-metadata:s:v:0") + 1] == "rotate=0"


@pytest.mark.parametrize("env_value", [None, "", "0", "false", "no"])
def test_nv_rotation180_fallback_off_stays_cuda(monkeypatch, env_value):
    """Fallback env unset/empty/0/false/no keeps CUDA ROT180 (default ON)."""
    from src.ffmpeg.command_builder import is_nv_rot180_cuda
    if env_value is None:
        monkeypatch.delenv("TELEM_NV_ROT180_CPU_FALLBACK", raising=False)
    else:
        monkeypatch.setenv("TELEM_NV_ROT180_CPU_FALLBACK", env_value)
    assert is_nv_rot180_cuda("nv", 180, 180) is True
    cmd, filter_complex = _nv_cmd(rotation_degrees=180, container_rotation=180)
    assert "scale_cuda" in filter_complex
    assert "overlay_cuda" in filter_complex
    assert cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "cuda"


@pytest.mark.parametrize("rot", [90, 270])
def test_nv_rotation90_270_cpu_fallback(monkeypatch, rot):
    """90/270 remain on the CPU fallback regardless of the ROT180 switch."""
    monkeypatch.delenv("TELEM_NV_ROT180_CPU_FALLBACK", raising=False)
    cmd, filter_complex = _nv_cmd(rotation_degrees=rot, container_rotation=0,
                                  render_w=1920, render_h=1080, resolution_name="source")
    assert "overlay_cuda" not in filter_complex
    assert "transpose" in filter_complex
    assert cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "yuv420p"


def test_amd_rotation180_no_nv2(monkeypatch):
    """AMD rotation=180 keeps its CPU chain (no CUDA fast-path)."""
    monkeypatch.delenv("TELEM_NV_ROT180_CPU_FALLBACK", raising=False)
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd
    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg",
        input_args=["-i", "test.mp4"],
        output_file="out.mp4",
        overlay_w=1920, overlay_h=1080, generation_fps=30.0,
        encoder="amd", gpu=0, video_bitrate="40M",
        render_w=1920, render_h=1080, resolution_name="source",
        container_rotation=0, rotation_degrees=180,
    )
    assert "overlay_cuda" not in filter_complex
    assert "vflip,hflip" in filter_complex


def test_intel_rotation180_no_nv2(monkeypatch):
    """Intel rotation=180 keeps its CPU chain (no CUDA fast-path)."""
    monkeypatch.delenv("TELEM_NV_ROT180_CPU_FALLBACK", raising=False)
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd
    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe="ffmpeg",
        input_args=["-i", "test.mp4"],
        output_file="out.mp4",
        overlay_w=1920, overlay_h=1080, generation_fps=30.0,
        encoder="intel", gpu=0, video_bitrate="40M",
        render_w=1920, render_h=1080, resolution_name="source",
        container_rotation=0, rotation_degrees=180,
    )
    assert "overlay_cuda" not in filter_complex
    # ETAP 5D: autorotate contract -- no baked manual flips for Intel.
    assert "vflip,hflip" not in filter_complex
    assert "hevc_qsv" in cmd


# ── displaymatrix writer hardening ───────────────────────────────────────────

def _make_mini_mp4() -> bytes:
    """Minimal moov/trak/tkhd/hdlr(vide) MP4 shell for the displaymatrix writer."""
    import struct

    def box(typ: str, payload: bytes) -> bytes:
        return struct.pack(">I", 8 + len(payload)) + typ.encode() + payload

    # tkhd v0: version(1)+flags(3) + 8 header fields (32B) + matrix(36B)
    tkhd_payload = bytes([0, 0, 0, 0]) + b"\x00" * 32 + b"\x00" * 36
    hdlr_payload = bytes(4) + b"\x00\x00\x00\x00" + b"vide" + b"\x00" * 12
    mdia = box("mdia", box("hdlr", hdlr_payload))
    trak = box("trak", box("tkhd", tkhd_payload) + mdia)
    moov = box("moov", trak)
    ftyp = box("ftyp", b"isom" + b"\x00\x00\x00\x00" + b"isom")
    return ftyp + moov


def _make_mini_mp4_no_video_track() -> bytes:
    """MP4 shell with only an audio (soun) track — no video track at all."""
    import struct

    def box(typ: str, payload: bytes) -> bytes:
        return struct.pack(">I", 8 + len(payload)) + typ.encode() + payload

    tkhd_payload = bytes([0, 0, 0, 0]) + b"\x00" * 32 + b"\x00" * 36
    hdlr_payload = bytes(4) + b"\x00\x00\x00\x00" + b"soun" + b"\x00" * 12
    mdia = box("mdia", box("hdlr", hdlr_payload))
    trak = box("trak", box("tkhd", tkhd_payload) + mdia)
    moov = box("moov", trak)
    ftyp = box("ftyp", b"isom" + b"\x00\x00\x00\x00" + b"isom")
    return ftyp + moov


def test_displaymatrix_valid_mp4_pass(tmp_path):
    """Valid MP4: writes + verifies the exact rotation-180 matrix, no temp left."""
    from src.ffmpeg.displaymatrix import (
        find_video_tkhd_matrix,
        verify_rotation_180_displaymatrix,
        write_rotation_180_displaymatrix,
    )
    p = tmp_path / "valid.mp4"
    p.write_bytes(_make_mini_mp4())
    assert write_rotation_180_displaymatrix(p, 3840, 2160) is True
    assert verify_rotation_180_displaymatrix(p, 3840, 2160) is True
    data = p.read_bytes()
    mo, me = find_video_tkhd_matrix(data)
    matrix = data[mo:me]
    expected = (
        b"\x00\x00\x00\x00" + b"\xff\xff\x00\x00" + b"\x00\x00\x00\x00" +
        b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00" + b"\xff\xff\x00\x00" +
        b"\x00\x00\x00\x00" +
        (3840 << 16).to_bytes(4, "big") + (2160 << 16).to_bytes(4, "big")
    )
    assert matrix == expected
    assert not list(tmp_path.glob("*.tmp"))


def test_displaymatrix_truncated_mp4_controlled_failure(tmp_path):
    """Truncated/invalid MP4 must fail cleanly without modifying the file."""
    from src.ffmpeg.displaymatrix import write_rotation_180_displaymatrix
    p = tmp_path / "trunc.mp4"
    good = _make_mini_mp4()
    p.write_bytes(good[: len(good) // 2])  # cut inside moov
    before = p.read_bytes()
    assert write_rotation_180_displaymatrix(p, 3840, 2160) is False
    assert p.read_bytes() == before  # untouched
    assert not list(tmp_path.glob("*.tmp"))


def test_displaymatrix_no_video_track_controlled_failure(tmp_path):
    """A file with no video track must fail cleanly without modifying the file."""
    from src.ffmpeg.displaymatrix import write_rotation_180_displaymatrix
    p = tmp_path / "novideo.mp4"
    p.write_bytes(_make_mini_mp4_no_video_track())
    before = p.read_bytes()
    assert write_rotation_180_displaymatrix(p, 3840, 2160) is False
    assert p.read_bytes() == before


def test_rot180_injection_failure_is_controlled_error():
    """When the displaymatrix writer cannot write/verify, the export path must
    raise a controlled error (never report success)."""
    from unittest.mock import patch
    import src.ffmpeg.displaymatrix as dm
    from src.ffmpeg.streaming import _inject_rot180_displaymatrix

    with patch.object(dm, "write_rotation_180_displaymatrix") as m:
        m.return_value = True
        assert _inject_rot180_displaymatrix("out.mp4", 3840, 2160) is True
        m.assert_called_once_with("out.mp4", 3840, 2160)
        # writer returns False (structural problem) -> controlled RuntimeError
        m.return_value = False
        with pytest.raises(RuntimeError):
            _inject_rot180_displaymatrix("out.mp4", 3840, 2160)


# ── INTEL ETAP 4K: RC contract cleanup (dead global_quality removed,
#    exactly one bitrate target, env override) ──────────────────────────────

def test_intel_hevc_vbr_contract_cleanup():
    """Intel HDR command must have NO dead -global_quality and EXACTLY one
    -b:v equal to the application video_bitrate."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd

    kwargs = _cpu_ref_kwargs()
    kwargs["video_bitrate"] = "40M"
    kwargs["intel_cpu_download_format"] = "p010le"
    cmd, fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, container_rotation=0,
        stream_w=808, stream_h=1700, hud_x=3032, hud_y=240,
        intel_gpu_resident=False, **kwargs)
    assert "-global_quality" not in cmd
    assert "-global_quality" not in fc
    assert cmd.count("-b:v") == 1
    assert cmd[cmd.index("-b:v") + 1] == "40M"
    # production HDR pixel format preserved
    assert cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "p010le"
    assert "hwdownload,format=nv12" not in fc


def test_intel_qsv_bitrate_env_override(monkeypatch):
    """TELEM_INTEL_QSV_BITRATE_MBPS overrides the application bitrate for
    Intel at resolution time; invalid values fall back."""
    from src.ffmpeg.streaming import resolve_intel_qsv_bitrate as res

    monkeypatch.delenv("TELEM_INTEL_QSV_BITRATE_MBPS", raising=False)
    assert res("40M") == ("40M", "application")

    monkeypatch.setenv("TELEM_INTEL_QSV_BITRATE_MBPS", "24")
    assert res("40M") == ("24M", "env_override")
    monkeypatch.setenv("TELEM_INTEL_QSV_BITRATE_MBPS", "40")
    assert res("40M") == ("40M", "env_override")

    monkeypatch.setenv("TELEM_INTEL_QSV_BITRATE_MBPS", "garbage")
    assert res("40M") == ("40M", "application")


def test_intel_hevc_env_override_reaches_final_command(monkeypatch):
    """Full chain: resolve_intel_qsv_bitrate override feeds the builder, so
    the final Intel command carries EXACTLY ONE -b:v 24M (no 40M remnant)."""
    from src.ffmpeg.streaming import resolve_intel_qsv_bitrate as res
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd

    monkeypatch.setenv("TELEM_INTEL_QSV_BITRATE_MBPS", "24")
    bv, source = res("40M")
    assert source == "env_override" and bv == "24M"
    cmd, fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, container_rotation=0,
        stream_w=808, stream_h=1700, hud_x=3032, hud_y=240,
        intel_gpu_resident=False,
        render_w=3840, render_h=2160,
        resolution_name="source",
        overlay_w=3840, overlay_h=2160,
        ffmpeg_exe="ffmpeg", input_args=["-i", "gx.mp4"],
        output_file="out.mp4", generation_fps=30.0, gpu=0,
        video_bitrate=bv,
        intel_cpu_download_format="p010le",
    )
    assert cmd.count("-b:v") == 1
    assert cmd[cmd.index("-b:v") + 1] == "24M"
    assert "40M" not in cmd
    assert "-global_quality" not in cmd


def test_intel_sdr_nv12_unchanged_by_rc_cleanup():
    """Intel SDR keeps nv12 pix_fmt after the RC cleanup (no p010 drift)."""
    from src.ffmpeg_pipeline import _build_stream_ffmpeg_cmd

    cmd, fc = _build_stream_ffmpeg_cmd(
        encoder="intel", rotation_degrees=0, container_rotation=0,
        stream_w=1920, stream_h=1080, hud_x=100, hud_y=50,
        intel_gpu_resident=False,
        render_w=1280, render_h=720,
        resolution_name="720p",
        overlay_w=1280, overlay_h=720,
        ffmpeg_exe="ffmpeg", input_args=["-i", "sdr.mp4"],
        output_file="out.mp4", generation_fps=30.0, gpu=0,
        video_bitrate="40M",
        intel_cpu_download_format="nv12",
    )
    assert cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "nv12"
    assert "-global_quality" not in cmd
    assert cmd.count("-b:v") == 1

