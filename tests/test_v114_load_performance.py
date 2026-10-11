import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from src.gui.qt.mp4_inspector import GOPRO_FIRMWARE_MODELS, inspect_mp4, format_file_info_text
from src.gui.qt.tabs.load_tab import LoadTab, VideoFileCardWidget
from src.integrations.auto_telemetry_preflight import run_auto_telemetry_preflight
from src.multifile import resolve_clip_timestamp
from src.telemetry_cache_manager import (
    get_gpmf_light_json_path,
    get_gpmf_light_metadata_path,
)
from src.telemetry_native_gpmf import (
    GPMF_LIGHT_CACHE_VERSION,
    _IN_MEMORY_LIGHT_CACHE,
    get_gpmf_light_metadata,
)


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_firmware_mapping_accuracy():
    """Verify firmware prefix mapping to camera models."""
    assert GOPRO_FIRMWARE_MODELS["H26"] == "GoPro HERO13 Black"
    assert GOPRO_FIRMWARE_MODELS["H23"] == "GoPro HERO12 Black"
    assert GOPRO_FIRMWARE_MODELS["H22"] == "GoPro HERO11 Black"
    assert GOPRO_FIRMWARE_MODELS["H21"] == "GoPro HERO10 Black"
    assert GOPRO_FIRMWARE_MODELS["H19"] == "GoPro HERO9 Black"


def test_gpmf_light_metadata_flow(tmp_path, monkeypatch):
    """Verify get_gpmf_light_metadata cache hit, miss and fingerprinting."""
    monkeypatch.setenv("TELEM_CACHE_ROOT", str(tmp_path / "cache"))
    _IN_MEMORY_LIGHT_CACHE.clear()

    dummy_video = tmp_path / "test_clip.mp4"
    dummy_video.write_bytes(b"dummy_mp4_payload_123456789")

    mock_native = {
        "success": True,
        "camera_model": "GoPro",
        "duration_sec": 600.0,
        "payload_count": 600,
        "start_dt_utc": 1791520075.839021,
        "start_dt_str": "2026-10-09 04:27:55.839",
        "gps_track": [(1791520075.839021, 40.3359305, 27.1676837)],
    }

    with patch("src.telemetry_native_gpmf.extract_gpmf_native", return_value=mock_native) as mock_extract:
        # 1. First call: MISS -> extracts and saves to cache
        res1 = get_gpmf_light_metadata(dummy_video)
        assert res1 is not None
        assert res1["success"] is True
        assert res1["start_dt_utc"] == 1791520075.839021
        assert res1["first_gps"] == (40.3359305, 27.1676837)
        assert mock_extract.call_count == 1

        json_path = get_gpmf_light_json_path(dummy_video)
        meta_path = get_gpmf_light_metadata_path(dummy_video)
        assert json_path.exists()
        assert meta_path.exists()

        # 2. Second call: in-memory HIT -> 0 native extractions
        res2 = get_gpmf_light_metadata(dummy_video)
        assert res2 == res1
        assert mock_extract.call_count == 1

        # 3. Clear in-memory cache: disk HIT -> 0 native extractions
        _IN_MEMORY_LIGHT_CACHE.clear()
        res3 = get_gpmf_light_metadata(dummy_video)
        assert res3 == res1
        assert mock_extract.call_count == 1

        # 4. Fingerprint invalidation: modifying file causes re-extraction
        time.sleep(0.01)
        dummy_video.write_bytes(b"dummy_mp4_payload_modified_999")
        _IN_MEMORY_LIGHT_CACHE.clear()
        res4 = get_gpmf_light_metadata(dummy_video)
        assert res4 is not None
        assert mock_extract.call_count == 2


def test_inspect_mp4_date_local_and_firmware_resolution(tmp_path, monkeypatch):
    """Verify inspect_mp4 properly formats local date, timezone and camera model from firmware."""
    monkeypatch.setenv("TELEM_CACHE_ROOT", str(tmp_path / "cache"))
    dummy_video = tmp_path / "GX010361.MP4"
    dummy_video.write_bytes(b"video_bytes")

    fake_ffprobe_out = {
        "format": {
            "duration": "1574.339",
            "size": "9232543928",
            "bit_rate": "46468408",
            "tags": {
                "firmware": "H26.02.02.02.00",
            },
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "avg_frame_rate": "30000/1001",
            },
            {
                "codec_type": "data",
                "codec_name": "gpmd",
                "codec_tag_string": "gpmd",
                "tags": {"handler_name": "GoPro MET"},
            },
        ],
    }

    mock_light = {
        "success": True,
        "camera_model": "GoPro",
        "duration_sec": 1574.339,
        "payload_count": 1573,
        "start_dt_utc": 1791520075.839021,
        "start_dt_str": "2026-10-09 04:27:55.839",
        "first_gps": (40.3359305, 27.1676837),
    }

    with patch("subprocess.run") as mock_subproc, \
         patch("src.telemetry_native_gpmf.get_gpmf_light_metadata", return_value=mock_light):

        mock_subproc.return_value = MagicMock(returncode=0, stdout=json.dumps(fake_ffprobe_out), stderr="")

        info = inspect_mp4(dummy_video, ffprobe_exe="ffprobe")
        assert info["gpmf"] is True
        meta = info["gpmf_meta"]

        # Polish local time verification
        assert meta["date"] == "2026-10-09 06:27:55"
        assert meta["timezone"] == "UTC+2"
        assert meta["date_source"] == "GPMF (GPS)"

        # Camera model from firmware
        assert meta["camera"] == "GoPro HERO13 Black"
        assert meta["camera_source"] == "firmware H26.02.02.02.00"

        # Formatted info text
        formatted = format_file_info_text(info)
        assert "GoPro HERO13 Black (firmware H26.02.02.02.00)" in formatted
        assert "2026-10-09 06:27:55 (GPMF (GPS), UTC+2)" in formatted


def test_card_widget_ui_labels(qapp, tmp_path):
    """Verify VideoFileCardWidget displays local date, timezone and camera source."""
    card = VideoFileCardWidget(0, str(tmp_path / "clip.mp4"))
    info = {
        "gpmf": True,
        "gpmf_meta": {
            "camera": "GoPro HERO13 Black",
            "camera_source": "firmware H26.02.02.02.00",
            "date": "2026-10-09 06:27:55",
            "date_source": "GPMF (GPS)",
            "timezone": "UTC+2",
        },
        "video": {"resolution": "3840 x 2160", "fps_text": "29.97", "codec_label": "HEVC", "pix_fmt": "yuv420p10le"},
        "color": {"summary": "BT.2020 / HLG"},
        "audio": {"codec_label": "AAC", "sample_rate_text": "48 kHz", "channels_text": "Stereo"},
    }
    card.update_info(info, "ride.fit")
    assert "2026-10-09 06:27:55" in card.lbl_record_date.text()
    assert "GPMF (GPS), UTC+2" in card.lbl_record_date.text()
    assert "GoPro HERO13 Black" in card.lbl_camera.text()
    assert "firmware H26.02.02.02.00" in card.lbl_camera.text()


def test_non_blocking_load_click(qapp, tmp_path):
    """Verify _on_load starts project loading immediately without 4-second wait."""
    tab = LoadTab()
    dummy_video = tmp_path / "test.mp4"
    dummy_video.write_bytes(b"content")

    tab._video_paths = [str(dummy_video)]
    tab._autofit_in_progress = True

    sig_emitted = []
    tab.signals.sig_files_selected.connect(lambda paths, gpx, fit: sig_emitted.append(paths))

    t0 = time.perf_counter()
    tab._on_load()
    t1 = time.perf_counter()

    # Must execute in < 50 ms (NO 4-second blocking loop!)
    assert (t1 - t0) < 0.1
    assert tab._loading is True
    assert len(sig_emitted) == 1
    assert sig_emitted[0] == [str(dummy_video)]
    tab.close()


def test_late_attach_signal_emitted(qapp, tmp_path):
    """Verify _on_autofit_matched emits sig_late_telemetry_matched when already loading."""
    tab = LoadTab()
    tab._loading = True

    late_attached = []
    tab.signals.sig_late_telemetry_matched.connect(lambda p: late_attached.append(p))

    fit_path = str(tmp_path / "matched.fit")
    tab._on_autofit_matched(fit_path, gen=tab._autofit_gen)

    assert len(late_attached) == 1
    assert late_attached[0] == fit_path
    tab.close()


def test_multifile_resolver_uses_light_metadata(tmp_path):
    """Verify resolve_clip_timestamp resolves clip timestamp instantly via light metadata."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")

    mock_light = {
        "success": True,
        "start_dt_utc": 1791520075.839021,
        "start_dt_str": "2026-10-09 04:27:55.839",
    }

    with patch("src.telemetry_native_gpmf.get_gpmf_light_metadata", return_value=mock_light), \
         patch("src.telemetry_gpmf_new.extract_gpmf") as mock_extract_raw:

        res = resolve_clip_timestamp(video, use_cache=False)
        assert res.absolute_start_dt is not None
        assert res.absolute_start_dt == datetime(2026, 10, 9, 4, 27, 55, 839021)
        # Verify raw FFmpeg stream extraction was NOT called
        mock_extract_raw.assert_not_called()
