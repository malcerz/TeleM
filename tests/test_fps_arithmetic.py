import pytest

def compute_fps_metrics(
    total_frames: int,
    t_export_start: float,
    t_first_frame_begin: float,
    t_video_render_end: float,
    t_export_end: float,
):
    video_render_wall_s = max(0.0001, t_video_render_end - t_first_frame_begin)
    total_wall_s = max(0.0001, t_export_end - t_export_start)
    
    render_fps = total_frames / video_render_wall_s
    true_fps = total_frames / total_wall_s
    
    return {
        "video_render_wall_s": video_render_wall_s,
        "total_wall_s": total_wall_s,
        "render_fps": render_fps,
        "true_fps": true_fps,
    }


def test_fps_arithmetic_cases():
    # Case 1: frames=2001, active render wall=80.0 s -> render FPS = 25.0125
    m1 = compute_fps_metrics(
        total_frames=2001,
        t_export_start=0.0,
        t_first_frame_begin=2.0,
        t_video_render_end=82.0,
        t_export_end=85.0,
    )
    assert m1["video_render_wall_s"] == pytest.approx(80.0)
    assert m1["render_fps"] == pytest.approx(25.0125, rel=1e-6)
    assert m1["true_fps"] == pytest.approx(2001.0 / 85.0, rel=1e-6)

    # Case 2: frames=300, active render wall=10.0 s -> render FPS = 30.0
    m2 = compute_fps_metrics(
        total_frames=300,
        t_export_start=0.0,
        t_first_frame_begin=1.0,
        t_video_render_end=11.0,
        t_export_end=13.0,
    )
    assert m2["video_render_wall_s"] == pytest.approx(10.0)
    assert m2["render_fps"] == pytest.approx(30.0, rel=1e-6)

    # Case 3: frames=5395, active render wall=180.0 s -> render FPS = 29.9722
    m3 = compute_fps_metrics(
        total_frames=5395,
        t_export_start=0.0,
        t_first_frame_begin=3.0,
        t_video_render_end=183.0,
        t_export_end=186.0,
    )
    assert m3["video_render_wall_s"] == pytest.approx(180.0)
    assert m3["render_fps"] == pytest.approx(5395.0 / 180.0, rel=1e-6)
