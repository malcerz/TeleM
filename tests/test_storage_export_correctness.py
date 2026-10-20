from types import SimpleNamespace
import shutil
import pytest
from src.ffmpeg.render_errors import preflight_export_storage, StorageError, RuntimeStorageMonitor
from src.multifile import VideoClip, VideoTimeline
from pathlib import Path


def probe(duration, fps="30/1"):
    return {'format': {'duration': duration}, 'streams': [
        {'codec_type': 'video', 'avg_frame_rate': fps},
        {'codec_type': 'audio', 'bit_rate': '384000'}]}


@pytest.mark.parametrize('count', [1, 2, 3])
def test_all_clips_and_cfr(tmp_path, monkeypatch, count):
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: SimpleNamespace(free=10**12))
    result = preflight_export_storage(tmp_path/'out.mp4', [str(i) for i in range(count)],
        {'bitrate': '60M', 'target_fps': 30}, probe=lambda p: probe(100))
    assert result['duration_s'] == count * 100
    assert result['budget_bitrate_bps'] == 90000000


@pytest.mark.parametrize('queued', [False, True])
def test_real_two_clip_incident_blocks_before_encode(tmp_path, monkeypatch, queued):
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: SimpleNamespace(free=24*1024**3))
    options = {'bitrate': '60M'}
    if queued:
        options['_queue_job_id'] = 'job'
    with pytest.raises(StorageError) as caught:
        preflight_export_storage(tmp_path/'out.mp4', ['a', 'b'], options,
            probe=lambda p: probe(2047.4454, "30000/1001"))
    assert caught.value.code == 'ENOSPC'
    assert caught.value.details['duration_s'] == pytest.approx(4094.8908)
    assert caught.value.details['required_bytes'] > 4094.89 * 90000000 / 8
    assert 'Brakuje:' in caught.value.user_message
    assert 'Szacowany rozmiar pliku:' in caught.value.user_message


def test_trimmed_canonical_timeline_not_full_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: SimpleNamespace(free=10**12))
    timeline = VideoTimeline([VideoClip(Path('a'), duration_s=100), VideoClip(Path('b'), duration_s=100)])
    # Keep 10s from each source; pauses/HUD cadence do not change movie duration.
    result = preflight_export_storage(tmp_path/'out.mp4', ['a','b'],
        {'bitrate':'60M', 'charts_skip_pauses':True, 'update_rate_step':4},
        probe=lambda p: probe(100), timeline=timeline, cut_regions=[(10,190)])
    assert result['duration_s'] == 20


@pytest.mark.parametrize('failure', ['probe', 'duration', 'bitrate', 'disk', 'directory'])
def test_fail_closed(tmp_path, monkeypatch, failure):
    def broken_probe(path):
        if failure == 'probe':
            raise OSError('ffprobe failed')
        return probe('nan' if failure == 'duration' else 100)
    def disk(path):
        if failure == 'disk':
            raise OSError('network unavailable')
        return SimpleNamespace(free=10**12)
    monkeypatch.setattr(shutil, 'disk_usage', disk)
    with pytest.raises(StorageError):
        preflight_export_storage((tmp_path/'missing' if failure=='directory' else tmp_path)/'out.mp4',
            ['a'], {'bitrate':'bad' if failure=='bitrate' else '60M'}, probe=broken_probe)


def test_runtime_query_failure_stops_producer(tmp_path, monkeypatch):
    callbacks=[]
    monitor=RuntimeStorageMonitor(tmp_path/'out.mp4', on_low_space_callback=lambda *args:callbacks.append(args))
    monkeypatch.setattr(shutil,'disk_usage',lambda p:(_ for _ in ()).throw(OSError('gone')))
    monitor._monitor_loop()
    assert monitor.stop_requested_low_space.is_set()
    assert callbacks[0][0] == -1
    assert isinstance(monitor.last_error, StorageError)
    assert monitor.last_error.pause_queue


@pytest.mark.parametrize('queued', [False, True])
def test_actual_gui_pipeline_blocks_before_render_initialization(tmp_path, monkeypatch, queued):
    from src.gui.qt._mixins.render_mixin import RenderMixin
    from src.ffmpeg import backend_capabilities, render_errors
    from threading import Event
    paths=[tmp_path/'GX010381.MP4',tmp_path/'GX010382.MP4']
    for path in paths:
        path.write_bytes(b'fake')
    monkeypatch.setattr(backend_capabilities,'query_backend_capabilities',lambda: {})
    monkeypatch.setattr(backend_capabilities,'validate_backend_available',lambda *a:(True,''))
    monkeypatch.setattr(render_errors,'probe_export_storage_media',lambda *a:probe(2047.4454, "30000/1001"))
    monkeypatch.setattr(shutil,'disk_usage',lambda p:SimpleNamespace(free=24*1024**3))
    owner=SimpleNamespace(video_path=paths[0],video_paths=paths,ffprobe_exe='ffprobe',
        video_timeline=None,_cut_regions=[],render_cancel_event=Event(),
        _resolve_render_output_path=lambda p:Path(p))
    options={'encoder':'intel','bitrate':'60M','output':str(tmp_path/'out.mp4')}
    if queued:
        options['_queue_job_id']='job'
    with pytest.raises(StorageError) as error:
        RenderMixin._render_pipeline(owner,options)
    assert error.value.code=='ENOSPC'
    assert not hasattr(owner,'_active_storage_monitor')


@pytest.mark.parametrize('rate', ['0/0','1/0','invalid'])
def test_invalid_output_fps_is_not_silently_defaulted(tmp_path,rate):
    with pytest.raises(StorageError) as caught:
        preflight_export_storage(tmp_path/'out.mp4',['a'],
            {'bitrate':'60M','target_fps':rate},probe=lambda p:probe(100))
    assert caught.value.code=='STORAGE_ESTIMATE_FAILED'
