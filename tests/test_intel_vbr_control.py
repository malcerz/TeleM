import os
import pytest
from src.ffmpeg.intel_config import resolve_intel_vbr, intel_ffmpeg_preset, resolve_intel_target_usage
from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd
from src.ffmpeg.intel_telemetry import IntelQsvTracker


def test_vbr_preserves_40m_native_buffer_and_scales_high_bitrates():
    rc = resolve_intel_vbr("40M")
    assert tuple(rc) == (40000, 50000, 10000, 5000, 1)
    rc = resolve_intel_vbr("100M")
    assert rc.target_kbps == 100000 and rc.max_kbps == 125000
    assert rc.multiplier == 2
    assert resolve_intel_vbr("5M").buffer_kb == 1250


@pytest.mark.parametrize("value", ["bad", "0M", "-5M", "nan"])
def test_invalid_bitrate_is_not_silently_replaced(value):
    with pytest.raises(ValueError): resolve_intel_vbr(value)


@pytest.mark.parametrize("profile,tu,preset", [("fast",7,"veryfast"),("balanced",4,"medium"),("quality",1,"veryslow")])
def test_profiles_change_only_preset_not_vbr_limits(monkeypatch, profile, tu, preset):
    monkeypatch.delenv("TELEM_INTEL_TARGET_USAGE", raising=False)
    assert resolve_intel_target_usage("hevc", profile) == tu
    assert intel_ffmpeg_preset(profile) == preset
    cmd, _ = _build_stream_ffmpeg_cmd("ffmpeg",["-i","source.mp4"],"out.mp4",encoder="intel",
           intel_codec="hevc",intel_encoder_profile=profile,intel_cpu_software_decode=True,
           intel_cpu_download_format="p010le",video_bitrate="40M")
    assert cmd[cmd.index("-preset")+1] == preset
    assert cmd[cmd.index("-maxrate")+1] == "50000000"
    assert cmd[cmd.index("-bufsize")+1] == "80000000"
    assert cmd[cmd.index("-b:v")+1] == "40000000"
    assert "-global_quality" not in cmd and "-qp" not in cmd


def test_ffmpeg_telemetry_keeps_vbr_but_ignores_all_qp_samples():
    for codec in ("hevc", "h264", "av1"):
        tracker = IntelQsvTracker(codec)
        for line in ["frame=10", "stream_0_0_q=23", "frame=20", "stream_0_0_q=31",
                     "TargetUsage: 7; RateControlMethod: VBR", "TargetKbps: 40000; MaxKbps: 50000"]:
            tracker.feed_progress_line(line)
        state = tracker.get_hud_state_dict()
        assert state["rate_control"] == "VBR" and not state["is_cqp"]
        assert state["encoder_accepted"]["TargetUsage"] == 7
        assert state["encoder_accepted"]["MaxKbps"] == 50000
        assert not any("qp" in key or "quant" in key for key in state if key != "is_cqp")


def test_native_qp_parser_and_per_frame_feedback_are_absent():
    from pathlib import Path
    import ctypes
    from src.ffmpeg.intel_native_exporter import _load_native_intel_dll, IntelNativePipelineStats
    source = (Path(__file__).resolve().parents[1] / "src/native/intel/d3d11_intel_pipeline/telem_intel_native.c").read_text()
    for removed in ("record_slot_qp", "hevc_slice_qp_record", "av1_extract_base_q_idx",
                    "MFX_EXTBUFF_ENCODED_FRAME_INFO", "TELEM_INTEL_QUANT_TELEMETRY"):
        assert removed not in source
    lib = _load_native_intel_dll()
    assert not hasattr(lib, "intel_native_get_hevc_slice_qp")
    assert not hasattr(lib, "intel_native_hevc_slice_qp_selftest")
    assert hasattr(lib, "intel_native_configure_vbr")
    # Reserved old statistics slots remain for binary-layout compatibility only.
    assert ctypes.sizeof(IntelNativePipelineStats) > 0


def test_progress_does_not_display_legacy_saved_quantizer_data():
    from src.render_progress import RenderProgressState, format_render_progress_status
    state = RenderProgressState(generation_id=1, state="rendering", frame=10, total_frames=100,
                                fps=55, qp=22, avg_qp=24, compression_text="QP: 22")
    text = format_render_progress_status(state)
    assert "55.0" in text and "QP" not in text and "Quantizer" not in text
