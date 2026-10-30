from types import SimpleNamespace
from unittest.mock import patch
import json
from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd
from src.ffmpeg.render_errors import validate_partial_output


def test_cpu_hlg_and_rotation_graph():
    cmd, graph = _build_stream_ffmpeg_cmd(
        ffmpeg_exe='ffmpeg', input_args=['-noautorotate', '-i', 'in.mp4'], output_file='out.mp4',
        overlay_w=1920, overlay_h=1080, generation_fps=30, encoder='cpu', gpu=0,
        video_bitrate='40M', render_w=1920, render_h=1080, resolution_name='source',
        container_rotation=180, rotation_degrees=180, is_10bit=True,
        cpu_color_range='pc', max_frames=45, cpu_output_duration_s=1.5,
    )
    assert 'vflip' not in graph and 'hflip' not in graph
    assert 'overlay=' in graph and ':format=yuv420p10' in graph
    assert cmd[cmd.index('-profile:v') + 1] == 'main10'
    assert cmd[cmd.index('-pix_fmt', cmd.index('-c:v')) + 1] == 'yuv420p10le'
    assert cmd[cmd.index('-t') + 1] == '1.500000000'
    assert cmd[cmd.index('-color_range') + 1] == 'pc'


def test_cpu_validator_rejects_audio_tail(tmp_path):
    mp4 = tmp_path / 'output.mp4'
    mp4.write_bytes(b'placeholder')
    def result(audio_duration):
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({
            'format': {'duration': '1.5015'},
            'streams': [
                {'codec_type': 'video', 'start_time': '0', 'duration': '1.5015'},
                {'codec_type': 'audio', 'start_time': '0', 'duration': str(audio_duration), 'sample_rate': '48000'},
            ],
        }))
    with patch('src.ffmpeg.render_errors.subprocess.run', return_value=result(172.6933)):
        assert validate_partial_output('ffprobe', mp4, 0, check_av_timing=True)[2]['timing_error'] == 'audio_video_timing_mismatch'
    with patch('src.ffmpeg.render_errors.subprocess.run', return_value=result(1.4933)):
        assert validate_partial_output('ffprobe', mp4, 0, check_av_timing=True)[0]
