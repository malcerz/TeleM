"""AMD queue jobs retain their own trim regions after GUI edits and JSON reload."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from src.gui.export_queue import ExportJob
from src.gui.qt.tabs.render_tab import RenderTab


def make_tab(encoder):
    ctrl=SimpleNamespace(video_paths=[Path("source.mp4")],video_path=Path("source.mp4"),
                         fit_path=None,gpx_path=None,layout={"indicators":{"track_map":{"enabled":True}}},
                         _cut_regions=[(0.0,120.0),(146.7,900.0)],
                         telemetry=SimpleNamespace(speed_samples=[1],gps_track=[1]))
    queue=Mock()
    text=lambda value:SimpleNamespace(text=lambda:value)
    tab=SimpleNamespace(_controller=ctrl,_export_queue=queue,_init_export_queue=lambda:None,
                        _build_options_from_gui=lambda:{"encoder":encoder,"output":"render.mp4"},
                        _ensure_range_applied=Mock(),_refresh_queue_ui=lambda:None,
                        edit_output=text("render.mp4"),chk_yt_enabled=SimpleNamespace(isChecked=lambda:False),
                        edit_yt_title=text(""),cmb_yt_privacy=SimpleNamespace(currentData=lambda:"private"),
                        edit_yt_desc=text(""))
    return tab,ctrl,queue


def test_amd_queue_snapshot_and_restore_preserves_trim():
    tab,ctrl,queue=make_tab("amd")
    RenderTab._on_add_to_queue(tab)
    job=queue.add_job.call_args.args[0]
    assert job.options["_amd_cut_regions"]==[(0.0,120.0),(146.7,900.0)]
    tab._ensure_range_applied.assert_called_once()
    ctrl._cut_regions[0]=(0.0,200.0)
    assert job.options["_amd_cut_regions"][0]==(0.0,120.0)
    # Queue persistence uses JSON-compatible region lists.
    job.options["_amd_cut_regions"]=[[0.0,120.0],[146.7,900.0]]
    RenderTab._restore_job_snapshot_onto_controller(tab,job)
    assert ctrl._cut_regions==[(0.0,120.0),(146.7,900.0)]
    ctrl._cut_regions.append((300,400))
    assert len(job.options["_amd_cut_regions"])==2


@pytest.mark.parametrize("encoder",["intel","nv"])
def test_other_encoders_keep_existing_queue_contract(encoder):
    tab,ctrl,queue=make_tab(encoder)
    RenderTab._on_add_to_queue(tab)
    job=queue.add_job.call_args.args[0]
    assert "_amd_cut_regions" not in job.options
    tab._ensure_range_applied.assert_not_called()
    RenderTab._restore_job_snapshot_onto_controller(tab,job)
    assert ctrl._cut_regions==[]


def test_legacy_amd_job_has_no_implicit_trim():
    tab,ctrl,_=make_tab("amd")
    job=ExportJob(video_paths=["source.mp4"],layout=ctrl.layout,options={"encoder":"amd"})
    RenderTab._restore_job_snapshot_onto_controller(tab,job)
    assert ctrl._cut_regions==[]


def test_auto_resolved_amd_preserves_trim():
    tab,ctrl,queue=make_tab("auto")
    with patch("src.ffmpeg.detect_best_encoder", return_value="amd"):
        RenderTab._on_add_to_queue(tab)
    job=queue.add_job.call_args.args[0]
    ctrl._cut_regions=[]
    RenderTab._restore_job_snapshot_onto_controller(tab,job)
    assert ctrl._cut_regions==[(0.0,120.0),(146.7,900.0)]
