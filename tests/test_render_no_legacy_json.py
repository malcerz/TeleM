"""Tests verifying that video render preparation does not require legacy <video>.json sidecars."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.gui.qt._mixins.render_mixin import RenderMixin
from src.gui.telemetry_manager import TelemetryDataManager


class DummySignals:
    class DummySig:
        def emit(self, *args, **kwargs):
            pass
    def __init__(self):
        self.sig_error = self.DummySig()
        self.sig_progress = self.DummySig()
        self.sig_render_progress = self.DummySig()
        self.sig_render_finished = self.DummySig()
        self.sig_render_stopped = self.DummySig()


class DummyRenderController(RenderMixin):
    def __init__(self, video_path: Path, video_paths: list[Path] | None = None):
        self.video_path = video_path
        self.video_paths = video_paths or [video_path]
        self.video_duration_s = 10.0
        self.telemetry = TelemetryDataManager()
        self.layout = {"indicators": {}}
        self._cut_regions = []
        self.signals = DummySignals()
        self.render_cancel_event = MagicMock()
        self.render_cancel_event.is_set.return_value = False
        self.render_process_holder = {}
        self.ffmpeg_exe = "ffmpeg"
        self.ffprobe_exe = "ffprobe"
        self.font_path = "font.ttf"
        self.render_threads = 2
        self.amd_decode_mode = "gpu"


@patch("src.gui.qt._mixins.render_mixin.stream_overlay_to_ffmpeg")
@patch("src.gui.qt._mixins.render_mixin.ffprobe_stream_info")
@patch("src.gui.qt._mixins.render_mixin.get_container_rotation")
@patch("src.gui.qt._mixins.render_mixin.detect_best_encoder")
def test_render_preparation_without_legacy_json(
    mock_detect_encoder,
    mock_container_rotation,
    mock_ffprobe_info,
    mock_stream_overlay,
    tmp_path,
):
    mock_detect_encoder.return_value = "cpu"
    mock_container_rotation.return_value = 0
    mock_ffprobe_info.return_value = {
        "streams": [{"width": 1920, "height": 1080, "r_frame_rate": "30/1"}]
    }

    dummy_video = tmp_path / "clip_without_json.MP4"
    dummy_video.write_bytes(b"dummy mp4")

    # Ensure no .json sidecar exists
    meta_json = dummy_video.with_suffix(".json")
    assert not meta_json.exists()

    ctrl = DummyRenderController(dummy_video)
    dt0 = datetime(2026, 8, 14, 11, 18, 3, tzinfo=timezone.utc)
    ctrl.telemetry.start_dt_utc = dt0
    ctrl.telemetry.speed_samples = [(dt0, 32.5)]
    ctrl.telemetry.track_samples = [(dt0, 100.0)]
    ctrl.telemetry.alt_samples = [(dt0, 50.0)]

    options = {
        "encoder": "cpu",
        "resolution": "source",
        "output": str(tmp_path / "out.mp4"),
    }

    # Must NOT raise RuntimeError("Brak pliku metadanych JSON.")
    stats = ctrl._render_pipeline(options)
    assert stats is not None
    assert mock_stream_overlay.called

    # Verify telemetry passed to stream_overlay_to_ffmpeg came from self.telemetry
    kwargs = mock_stream_overlay.call_args.kwargs
    assert kwargs["speed_samples"] == [(dt0, 32.5)]
    assert kwargs["track_samples"] == [(dt0, 100.0)]
    assert kwargs["alt_samples"] == [(dt0, 50.0)]
    assert kwargs["start_dt_utc"] == dt0
    assert kwargs["rotation_degrees"] == 0


@patch("src.gui.qt._mixins.render_mixin.stream_overlay_to_ffmpeg")
@patch("src.gui.qt._mixins.render_mixin.ffprobe_stream_info")
@patch("src.gui.qt._mixins.render_mixin.get_container_rotation")
@patch("src.gui.qt._mixins.render_mixin.detect_best_encoder")
def test_render_preparation_with_legacy_json_compatibility(
    mock_detect_encoder,
    mock_container_rotation,
    mock_ffprobe_info,
    mock_stream_overlay,
    tmp_path,
):
    mock_detect_encoder.return_value = "cpu"
    mock_container_rotation.return_value = 0
    mock_ffprobe_info.return_value = {
        "streams": [{"width": 1920, "height": 1080, "r_frame_rate": "30/1"}]
    }

    dummy_video = tmp_path / "clip_with_json.MP4"
    dummy_video.write_bytes(b"dummy mp4")

    # Create legacy .json sidecar with rotation metadata
    meta_json = dummy_video.with_suffix(".json")
    meta_json.write_text('[{"Main:Rotation": 180}]', encoding="utf-8")
    assert meta_json.exists()

    ctrl = DummyRenderController(dummy_video)
    options = {
        "encoder": "cpu",
        "resolution": "source",
        "output": str(tmp_path / "out.mp4"),
    }

    stats = ctrl._render_pipeline(options)
    assert stats is not None
    assert mock_stream_overlay.called

    kwargs = mock_stream_overlay.call_args.kwargs
    # Should have read rotation from metadata JSON
    assert kwargs["rotation_degrees"] == 180


@patch("src.gui.qt._mixins.render_mixin.stream_overlay_to_ffmpeg")
@patch("src.gui.qt._mixins.render_mixin.ffprobe_stream_info")
@patch("src.gui.qt._mixins.render_mixin.get_container_rotation")
@patch("src.gui.qt._mixins.render_mixin.detect_best_encoder")
def test_render_preparation_multifile_without_json(
    mock_detect_encoder,
    mock_container_rotation,
    mock_ffprobe_info,
    mock_stream_overlay,
    tmp_path,
):
    mock_detect_encoder.return_value = "cpu"
    mock_container_rotation.return_value = 0
    mock_ffprobe_info.return_value = {
        "streams": [{"width": 3840, "height": 2160, "r_frame_rate": "60/1"}]
    }

    clip1 = tmp_path / "GX010001.MP4"
    clip2 = tmp_path / "GX010002.MP4"
    clip1.write_bytes(b"dummy 1")
    clip2.write_bytes(b"dummy 2")

    ctrl = DummyRenderController(clip1, video_paths=[clip1, clip2])
    ctrl.video_timeline = MagicMock()
    ctrl.video_duration_s = 120.0

    options = {
        "encoder": "cpu",
        "resolution": "source",
        "output": str(tmp_path / "multi_out.mp4"),
    }

    stats = ctrl._render_pipeline(options)
    assert stats is not None
    assert mock_stream_overlay.called

    kwargs = mock_stream_overlay.call_args.kwargs
    assert kwargs["input_files"] == [clip1, clip2]
    assert kwargs["video_timeline"] == ctrl.video_timeline
    assert kwargs["duration_s"] == 120.0
