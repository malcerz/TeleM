"""Opt-in real GUI RenderJob serialization proof for AMD Windows spawn.

The test uses ``RenderMixin._render_pipeline`` to build the job, then replaces
only the child launch boundary.  No output video is rendered by this test.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest

from src.ffmpeg.amd_child_process import inspect_render_job_pickle
from src.ffmpeg.amd_hevc_preview import AMDGPUNativeFrameTapPreview
from src.gui.qt._mixins.project_mixin import ProjectMixin
from src.gui.qt._mixins.render_mixin import RenderMixin
from src.gui.telemetry_manager import TelemetryDataManager
from src.multifile import build_timeline_from_paths
from src.telemetry_processed_cache import apply_processed_cache


class _Signal:
    def emit(self, *_args):
        pass


class _Signals:
    sig_progress = _Signal()
    sig_render_progress = _Signal()


def _required_path(env_name: str) -> Path:
    raw = os.environ.get(env_name)
    if not raw:
        pytest.skip(f"{env_name} is required for the opt-in real spawn test")
    path = Path(raw)
    if not path.is_file():
        pytest.fail(f"real test path does not exist: {path}")
    return path


def test_real_gui_render_job_pickle_contract(monkeypatch, tmp_path):
    clip_1 = _required_path("TELEM_AMD_CHILD_CLIP_1")
    clip_2 = _required_path("TELEM_AMD_CHILD_CLIP_2")
    fit_path = _required_path("TELEM_AMD_CHILD_FIT")
    layout_path = _required_path("TELEM_AMD_CHILD_LAYOUT")
    paths = [clip_1, clip_2]

    owner = SimpleNamespace(
        signals=_Signals(),
        ffmpeg_exe="ffmpeg",
        ffprobe_exe="ffprobe",
        exiftool_path="exiftool",
        base_dir=Path(__file__).resolve().parents[1],
        telemetry=TelemetryDataManager(),
    )
    for index, path in enumerate(paths):
        fields, records = ProjectMixin._load_single_clip_telemetry(
            owner, path, clip_idx=index, total_clips=len(paths)
        )
        if index == 0:
            apply_processed_cache(owner.telemetry, fields)
            owner.telemetry.records = records or []
        else:
            ProjectMixin._merge_clip_telemetry(owner, fields, records)

    timeline = build_timeline_from_paths(paths, ffprobe_exe="ffprobe")
    assert owner.telemetry.load_fit(
        clip_1, timeline.clips[0].absolute_start_dt, manual_path=fit_path
    )

    captured = {}

    def capture_child(**kwargs):
        captured["render_kwargs"] = kwargs["render_kwargs"]
        captured["diagnostics"] = inspect_render_job_pickle(
            kwargs["render_kwargs"]
        )
        return {"child_exitcode": 0}

    import src.ffmpeg.amd_child_process as child_module
    import src.gui.qt._mixins.render_mixin as render_module

    monkeypatch.setattr(child_module, "run_amd_render_child", capture_child)
    monkeypatch.setattr(render_module, "_test_encoder", lambda *_args: True)

    owner.video_path = clip_1
    owner.video_paths = paths
    owner.video_timeline = timeline
    owner.video_duration_s = timeline.project_duration_s
    owner.layout = json.loads(layout_path.read_text(encoding="utf-8"))
    owner._cut_regions = []
    owner.font_path = "arial.ttf"
    owner.render_threads = 4
    owner.render_process_holder = {}
    owner.render_cancel_event = SimpleNamespace(is_set=lambda: False)
    owner.amd_decode_mode = "gpu"

    RenderMixin._render_pipeline(owner, {
        "encoder": "amd",
        "resolution": "source",
        "output": str(tmp_path / "real_render_job.mp4"),
        "bitrate": "40M",
        "hud_resolution_scale": "Auto",
        "_render_generation_id": 244245,
        "_amd_export_preview_config": {
            "enabled": True, "width": 960, "height": 540, "target_fps": 2.0,
        },
    })

    diagnostics = captured["diagnostics"]
    lazy_paths = [item["path"] for item in diagnostics["lazy_sample_lists"]]
    assert diagnostics["pickle_size"] > 0
    assert diagnostics["pickle_time_ms"] >= 0.0
    assert lazy_paths
    assert all(
        not item["state"] == "materialized"
        for item in diagnostics["lazy_sample_lists"]
    )
    print(f"REAL_RENDER_JOB_DIAGNOSTICS={diagnostics}")


def test_real_amd_child_preview_on_off_short_render(tmp_path):
    if os.environ.get("TELEM_AMD_CHILD_REAL_RENDER") != "1":
        pytest.skip("set TELEM_AMD_CHILD_REAL_RENDER=1 for the AMD hardware smoke")

    clip_1 = _required_path("TELEM_AMD_CHILD_CLIP_1")
    clip_2 = _required_path("TELEM_AMD_CHILD_CLIP_2")
    fit_path = _required_path("TELEM_AMD_CHILD_FIT")
    layout_path = _required_path("TELEM_AMD_CHILD_LAYOUT")
    paths = [clip_1, clip_2]
    timeline_full = build_timeline_from_paths(paths, ffprobe_exe="ffprobe")
    fps = timeline_full.clips[0].fps
    seconds_per_side = 150.0 / fps
    timeline = timeline_full.subset([
        (
            0,
            timeline_full.clips[0].local_end_s - seconds_per_side,
            timeline_full.clips[0].local_end_s,
        ),
        (1, 0.0, seconds_per_side),
    ])
    assert sum(timeline.output_frame_counts(fps)) == 300

    owner = SimpleNamespace(
        signals=_Signals(),
        ffmpeg_exe="ffmpeg",
        ffprobe_exe="ffprobe",
        exiftool_path="exiftool",
        base_dir=Path(__file__).resolve().parents[1],
        telemetry=TelemetryDataManager(),
    )
    for index, path in enumerate(paths):
        fields, records = ProjectMixin._load_single_clip_telemetry(
            owner, path, clip_idx=index, total_clips=len(paths)
        )
        if index == 0:
            apply_processed_cache(owner.telemetry, fields)
            owner.telemetry.records = records or []
        else:
            ProjectMixin._merge_clip_telemetry(owner, fields, records)
    assert owner.telemetry.load_fit(
        clip_1, timeline_full.clips[0].absolute_start_dt, manual_path=fit_path
    )

    owner.video_path = clip_1
    owner.video_paths = paths
    owner.video_timeline = timeline
    owner.video_duration_s = timeline.project_duration_s
    owner.layout = json.loads(layout_path.read_text(encoding="utf-8"))
    owner._cut_regions = []
    owner.font_path = "arial.ttf"
    owner.render_threads = 4
    owner.amd_decode_mode = "gpu"
    os.environ["AMD_RENDER_CHILD_PROCESS"] = "1"

    for preview_enabled in (True, False):
        output = tmp_path / f"amd-child-preview-{'on' if preview_enabled else 'off'}.mp4"
        frames = []
        preview = None
        preview_config = None
        if preview_enabled:
            preview = AMDGPUNativeFrameTapPreview(
                width=960,
                height=540,
                target_fps=2.0,
                on_frame=lambda raw, width, height: frames.append(
                    (len(raw), width, height)
                ),
            )
            assert preview.start()
            preview_config = {
                "enabled": True, "width": 960, "height": 540, "target_fps": 2.0,
            }

        owner.render_process_holder = {}
        owner.render_cancel_event = threading.Event()
        RenderMixin._render_pipeline(owner, {
            "encoder": "amd",
            "resolution": "source",
            "output": str(output),
            "bitrate": "40M",
            "hud_resolution_scale": "Auto",
            "_render_generation_id": 244245 + int(preview_enabled),
            "_amd_export_preview_session": preview,
            "_amd_export_preview_config": preview_config,
        })
        if preview is not None:
            preview.stop("test_complete")

        assert output.is_file() and output.stat().st_size > 0
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_frames", "-of", "default=nw=1:nk=1",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert int(probe.stdout.strip()) == 300
        if preview_enabled:
            assert frames
            assert all((width, height) == (960, 540) for _size, width, height in frames)
        assert owner.render_process_holder.get("process") is None

    cancel_output = tmp_path / "amd-child-cancelled.mp4"
    cancelled_at = []
    cancelled_child_pid = []
    owner.render_process_holder = {}
    owner.render_cancel_event = threading.Event()

    def cancel_after_120(completed, _total, _elapsed, _fps, _hud_state):
        if completed >= 120 and not owner.render_cancel_event.is_set():
            cancelled_at.append(int(completed))
            cancelled_child_pid.append(owner.render_process_holder.get("child_pid"))
            owner.render_cancel_event.set()

    owner._emit_render_progress_callback = cancel_after_120
    RenderMixin._render_pipeline(owner, {
        "encoder": "amd",
        "resolution": "source",
        "output": str(cancel_output),
        "bitrate": "40M",
        "hud_resolution_scale": "Auto",
        "_render_generation_id": 244247,
        "_amd_export_preview_session": None,
        "_amd_export_preview_config": None,
    })
    assert cancelled_at and cancelled_at[0] >= 120
    assert owner.render_cancel_event.is_set()
    assert owner.render_process_holder.get("process") is None
    active_pids = {process.pid for process in __import__("multiprocessing").active_children()}
    assert all(pid not in active_pids for pid in cancelled_child_pid if pid is not None)
