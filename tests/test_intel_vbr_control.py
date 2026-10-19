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


def test_ffmpeg_telemetry_uses_real_distinct_samples_and_rejects_unknown_hevc():
    tracker=IntelQsvTracker("h264")
    for line in ["frame=0","stream_0_0_q=0", "frame=10", "stream_0_0_q=23", "stream_0_0_q=23",
                 "frame=20", "stream_0_0_q=31", "TargetUsage: 4; RateControlMethod: VBR"]:
        tracker.feed_progress_line(line)
    data=tracker.get_hud_state_dict()
    assert data["quant_avg"] == 27 and data["quant_samples"] == 2
    assert data["quant_min"] == 23 and data["quant_max"] == 31
    assert data["rate_control"] == "VBR" and not data["is_cqp"]
    hevc=IntelQsvTracker("hevc")
    hevc.feed_progress_line("frame=10"); hevc.feed_progress_line("stream_0_0_q=0")
    assert hevc.get_hud_state_dict()["quant_samples"] == 0
    assert "QP: --" in hevc.get_hud_state_dict()["compression_text"]


def test_unverified_native_hevc_feedback_is_not_published_as_real_qp():
    from src.ffmpeg.intel_native_exporter import _withhold_unverified_hevc_qp
    data = _withhold_unverified_hevc_qp(dict(quant_current=1, quant_avg=5.5,
        quant_min=1, quant_max=31, quant_samples=500, quant_sum=2750, avg_qp=5.5))
    assert data["quant_current"] is None and data["avg_qp"] is None
    assert data["quant_samples"] == 0 and not data["compression_active"]
    assert data["qp_unverified_feedback"]["quant_samples"] == 500
    assert "QP: --" in data["compression_text"] and data["quant_reason"]


def _fake_slice_qp_lib(**values):
    import ctypes
    from src.ffmpeg.intel_native_exporter import IntelHevcSliceQpStats

    class Lib:
        def intel_native_get_hevc_slice_qp(self, ptr):
            stats = ctypes.cast(ptr, ctypes.POINTER(IntelHevcSliceQpStats)).contents
            for key, value in values.items():
                setattr(stats, key, value)
            return 0
    return Lib()


def test_hevc_slice_qp_is_published_under_slice_keys_only():
    from src.ffmpeg.intel_native_exporter import _withhold_unverified_hevc_qp
    lib = _fake_slice_qp_lib(valid=1, frames=300, slices=300, max_slices_per_frame=1, cu_qp_delta_enabled=1,
                             cur_frame_weighted=26.0, cur_frame_min=26, cur_frame_max=26,
                             run_avg=26.0, run_min=26, run_max=26,
                             vpl_reported=300, vpl_zero=93, vpl_mismatch=207, parse_us_total=3000.0)
    data = _withhold_unverified_hevc_qp(dict(quant_current=1, quant_avg=2.0), lib)
    assert data["avg_qp"] is None and data["quant_avg"] is None and data["quant_current"] is None
    assert not data["compression_active"]
    assert data["slice_qp_available"] and data["slice_qp_avg"] == 26.0 and data["slice_qp_min"] == 26
    assert data["slice_qp_cu_qp_delta_enabled"] and "cu_qp_delta" in data["slice_qp_note"]
    assert data["compression_text"].startswith("Slice QP: 26 |") and "próbki: 300" in data["compression_text"]
    assert data["slice_qp_valid_samples"] == 300 and data["slice_qp_rejected_samples"] == 0
    assert data["vpl_hevc_frame_qp_crosscheck"]["zero"] == 93
    assert data["slice_qp_parse_us_per_frame"] == 10.0


def test_hevc_slice_qp_absent_shows_reason():
    from src.ffmpeg.intel_native_exporter import _withhold_unverified_hevc_qp
    data = _withhold_unverified_hevc_qp({}, _fake_slice_qp_lib(valid=0, disabled=1))
    assert not data["slice_qp_available"] and data["slice_qp_reason"] == "telemetry disabled"
    assert "Slice QP: --" in data["compression_text"] and "QP: --" in data["compression_text"]
