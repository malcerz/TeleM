"""CPU P0.3: profile -> x265 preset mapping and exclusive rate control."""
import pytest

from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd
from src.ffmpeg.cpu_x265 import build_cpu_x265_args, parse_bitrate_kbps, resolve_cpu_preset


def _cpu_cmd(profile="balanced", mode="abr", bitrate="40M"):
    cmd, _fc = _build_stream_ffmpeg_cmd(
        "ffmpeg", ["-i", "in.mp4"], "out.mp4", encoder="cpu", video_bitrate=bitrate,
        is_10bit=True, intel_encoder_profile=profile, cpu_rate_mode=mode,
        container_rotation=180, cpu_color_range="pc",
    )
    return cmd


@pytest.mark.parametrize("profile,preset", [("fast", "ultrafast"), ("balanced", "faster"),
                                            ("quality", "medium"), ("Szybki", "ultrafast"),
                                            ("Jakość", "medium")])
def test_profile_preset_mapping(profile, preset, monkeypatch):
    monkeypatch.delenv("TELEM_CPU_X265_PRESET", raising=False)
    assert resolve_cpu_preset(profile) == preset


@pytest.mark.parametrize("text,kbps", [("40M", 40000), ("16384k", 16384), ("16.5M", 16500),
                                       ("8m", 8000), ("", None), ("abc", None), ("0M", None)])
def test_parse_bitrate(text, kbps):
    assert parse_bitrate_kbps(text) == kbps


@pytest.mark.parametrize("bitrate,kbps", [("8M", "8000k"), ("16M", "16000k"), ("40M", "40000k"), ("80M", "80000k")])
def test_abr_has_bitrate_and_no_crf(bitrate, kbps):
    cmd = _cpu_cmd(mode="abr", bitrate=bitrate)
    assert cmd.count("-b:v") == 1 and cmd[cmd.index("-b:v") + 1] == kbps
    assert "-crf" not in cmd
    assert "-maxrate" not in cmd and "-bufsize" not in cmd  # no pretend CBR / hard cap


def test_crf_has_crf_and_no_bitrate():
    cmd = _cpu_cmd(mode="crf", bitrate="40M")
    assert cmd.count("-crf") == 1 and "-b:v" not in cmd


def test_abr_invalid_bitrate_falls_back_to_crf_explicitly():
    args, desc = build_cpu_x265_args("balanced", "abr", "garbage")
    assert "-crf" in args and "-b:v" not in args and "FALLBACK" in desc


def test_main10_hlg_flags_preserved():
    cmd = _cpu_cmd()
    for pair in (("-profile:v", "main10"), ("-pix_fmt", "yuv420p10le"), ("-color_trc", "arib-std-b67"),
                 ("-color_primaries", "bt2020"), ("-colorspace", "bt2020nc")):
        assert cmd[len(cmd) - 1 - cmd[::-1].index(pair[0]) + 1] == pair[1]  # last = output option
    assert cmd[cmd.index("-c:a") + 1] == "copy"


def test_legacy_settings_keep_previous_encoding():
    from src.ffmpeg.cpu_x265 import settings_to_cpu_choice
    assert settings_to_cpu_choice({}) == ("quality", "crf", True)
    assert settings_to_cpu_choice({"encoder_profile": "fast", "bitrate": "40M"}) == ("quality", "crf", True)
    assert settings_to_cpu_choice({"cpu_profile": "fast"}) == ("fast", "crf", False)
    assert settings_to_cpu_choice({"cpu_rate_mode": "abr"}) == ("quality", "abr", False)
    assert settings_to_cpu_choice({"cpu_profile": "balanced", "cpu_rate_mode": "abr"}) == ("balanced", "abr", False)
