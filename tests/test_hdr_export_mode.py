"""ETAP 5Z.2: HLG detection, HDR export-mode policy and queue snapshots."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ffmpeg.hdr_color import (
    DEFAULT_HDR_MODE, HDR_MODE_PRESERVE, HDR_MODE_TONEMAP, HDRExportConfigError,
    PIPELINE_HLG_PRESERVE, PIPELINE_HLG_TO_SDR, PIPELINE_SDR,
    classify_stream, normalize_hdr_mode, resolve_native_pipeline, summarize_sources,
)
from src.ffmpeg.render_errors import coerce_render_error
from src.gui.export_queue import ExportJob, ExportQueue

GOPRO_HLG = {"codec_name": "hevc", "profile": "Main 10", "pix_fmt": "yuv420p10le", "color_range": "pc",
             "color_space": "bt2020nc", "color_transfer": "arib-std-b67", "color_primaries": "bt2020",
             "width": 3840, "height": 2160, "avg_frame_rate": "30000/1001"}
SDR8 = {"codec_name": "hevc", "profile": "Main", "pix_fmt": "yuv420p", "color_range": "tv",
        "color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709",
        "width": 3840, "height": 2160, "avg_frame_rate": "30000/1001"}


def clip(stream, name="a.mp4", rotation=0, **override):
    return classify_stream({**stream, **override}, name, rotation)


def test_gopro_hlg_is_hlg_full_range():
    info = clip(GOPRO_HLG, rotation=-180)
    assert info.kind == "hlg" and info.full_range is True and info.bit_depth == 10 and info.rotation == 180


@pytest.mark.parametrize("override", [
    {"color_transfer": "bt709"},                                    # 10-bit BT.2020 without HLG transfer
    {"color_transfer": None},
])
def test_ten_bit_or_bt2020_alone_is_not_hdr(override):
    assert clip(GOPRO_HLG, **override).kind == "sdr10"


def test_sdr8():
    assert clip(SDR8).kind == "sdr8"


@pytest.mark.parametrize("override", [
    {"color_primaries": "bt709"}, {"pix_fmt": "yuv420p"}, {"color_range": None}, {"color_space": "bt709"},
])
def test_contradictory_hlg_metadata_is_ambiguous(override):
    assert clip(GOPRO_HLG, **override).kind == "ambiguous"


def test_pq_is_recognised_and_refused():
    s = summarize_sources([clip(GOPRO_HLG, color_transfer="smpte2084")])
    assert s.kind == "pq" and s.error
    with pytest.raises(HDRExportConfigError):
        resolve_native_pipeline(s, HDR_MODE_TONEMAP, "HEVC", 0x3, True)


def test_mixed_hlg_and_sdr_segments_refused():
    s = summarize_sources([clip(GOPRO_HLG, "a.mp4"), clip(SDR8, "b.mp4")])
    assert s.kind == "mixed" and "HLG" in s.error


def test_hlg_segments_with_different_range_refused():
    s = summarize_sources([clip(GOPRO_HLG, "a.mp4"), clip(GOPRO_HLG, "b.mp4", color_range="tv")])
    assert s.kind == "mixed"


def test_hlg_rotation_90_refused():
    s = summarize_sources([clip(GOPRO_HLG, rotation=90)])
    assert s.error and "Obrót" in s.error


def test_multi_segment_hlg_ok():
    s = summarize_sources([clip(GOPRO_HLG, "a.mp4", rotation=180), clip(GOPRO_HLG, "b.mp4", rotation=180)])
    assert s.is_hlg and s.full_range is True


def test_default_and_legacy_modes():
    assert DEFAULT_HDR_MODE == HDR_MODE_PRESERVE
    assert normalize_hdr_mode(None) == HDR_MODE_PRESERVE          # old settings / old queue jobs
    assert normalize_hdr_mode("garbage") == HDR_MODE_PRESERVE
    assert normalize_hdr_mode("tonemap_sdr") == HDR_MODE_TONEMAP


def test_sdr_source_always_uses_unchanged_pipeline():
    s = summarize_sources([clip(SDR8)])
    assert resolve_native_pipeline(s, HDR_MODE_PRESERVE, "HEVC", 0, None) == PIPELINE_SDR


def test_unreadable_colour_metadata_keeps_sdr_pipeline():
    from src.ffmpeg.hdr_color import VideoColorInfo
    s = summarize_sources([VideoColorInfo(path="x.mp4", kind="unknown", reason="ffprobe failed")])
    assert resolve_native_pipeline(s, HDR_MODE_PRESERVE, "HEVC", 0, None) == PIPELINE_SDR


def test_hlg_pipelines_selected():
    s = summarize_sources([clip(GOPRO_HLG)])
    assert resolve_native_pipeline(s, HDR_MODE_PRESERVE, "HEVC", 0x3, True) == PIPELINE_HLG_PRESERVE
    assert resolve_native_pipeline(s, HDR_MODE_TONEMAP, "HEVC", 0x3, None) == PIPELINE_HLG_TO_SDR
    assert resolve_native_pipeline(s, HDR_MODE_TONEMAP, "H264", 0x3, None) == PIPELINE_HLG_TO_SDR


def test_no_silent_fallback_without_main10():
    s = summarize_sources([clip(GOPRO_HLG)])
    with pytest.raises(HDRExportConfigError, match="Konwertuj do SDR"):
        resolve_native_pipeline(s, HDR_MODE_PRESERVE, "HEVC", 0x3, False)


def test_old_dll_without_hdr_support_is_refused():
    s = summarize_sources([clip(GOPRO_HLG)])
    for mode in (HDR_MODE_PRESERVE, HDR_MODE_TONEMAP):
        with pytest.raises(HDRExportConfigError, match="nie obsługuje"):
            resolve_native_pipeline(s, mode, "HEVC", 0, True)


def test_preserve_requires_hevc():
    s = summarize_sources([clip(GOPRO_HLG)])
    with pytest.raises(HDRExportConfigError, match="HEVC"):
        resolve_native_pipeline(s, HDR_MODE_PRESERVE, "AV1", 0x3, True)


def test_hdr_config_error_becomes_main_gui_message():
    from src.ffmpeg.amd_native_exporter import AMDHDRConfigError
    err = coerce_render_error(AMDHDRConfigError("Ten procesor graficzny nie zakodował strumienia HEVC Main10"))
    assert err.code == "HDR_MODE_UNAVAILABLE"
    assert err.display_message().startswith("Ten procesor graficzny")


def test_queue_jobs_keep_their_own_hdr_mode_across_persist_and_requeue(tmp_path: Path):
    q = ExportQueue(appdata_dir=tmp_path)
    try:
        a = ExportJob(video_paths=["a.mp4"], options={"encoder": "amd", "amd_hdr_mode": HDR_MODE_PRESERVE},
                      output_path=str(tmp_path / "a.mp4"))
        b = ExportJob(video_paths=["b.mp4"], options={"encoder": "amd", "amd_hdr_mode": HDR_MODE_TONEMAP},
                      output_path=str(tmp_path / "b.mp4"))
        q.add_job(a)
        q.add_job(b)
        q._persist()
        q.requeue_job(b.job_id)
        assert [j.options["amd_hdr_mode"] for j in q.get_jobs()] == [HDR_MODE_PRESERVE, HDR_MODE_TONEMAP]
    finally:
        q.stop()
    data = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    text = json.dumps(data)
    assert HDR_MODE_PRESERVE in text and HDR_MODE_TONEMAP in text
    q2 = ExportQueue(appdata_dir=tmp_path)
    try:
        assert sorted(j.options.get("amd_hdr_mode") for j in q2.get_jobs()) == sorted([HDR_MODE_PRESERVE, HDR_MODE_TONEMAP])
    finally:
        q2.stop()
