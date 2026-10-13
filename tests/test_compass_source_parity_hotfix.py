from datetime import datetime, timedelta, timezone
import numpy as np
from src.render_preparation import RenderPreparationService
from src.ffmpeg.worker_cache import init_worker


def build(source, gpmf, fit):
    layout={"indicators":{"compass":{"enabled":True,"source":source,"field":"heading"}}}
    init_worker(640,360,"",layout,{"heading_samples":gpmf},fit_data={"heading":fit})
    return RenderPreparationService.build_telemetry_cache_vectorized(
        layout=layout,base_dt=datetime(2026,1,1),start_dt_utc=datetime(2026,1,1),
        fit_data={"heading":fit},track_samples=[(datetime(2026,1,1),1234.0)],
        total_frames=3,target_fps=1,
    )


def test_compass_honors_gpmf_source_instead_of_fit_or_distance():
    base=datetime(2026,1,1,tzinfo=timezone.utc)
    cache=build("gpmf",[(base,359.0),(base+timedelta(seconds=2),1.0)],[(base,180.0)])
    assert [cache.lookup(i)["extra_indicators"]["compass"][0] for i in range(3)]==[359.0,0.0,1.0]
    assert cache.columns["heading"][0]==180.0  # Other consumers keep their existing contract.


def test_compass_honors_fit_source():
    base=datetime(2026,1,1,tzinfo=timezone.utc)
    cache=build("fit",[(base,90.0)],[(base,270.0)])
    assert cache.lookup(1)["extra_indicators"]["compass"][0]==270.0


def test_compass_missing_gps_is_not_distance_as_heading():
    cache=build("gpmf",[],[])
    assert cache.lookup(1)["extra_indicators"]["compass"][0] is None


def test_compass_preserves_missing_markers_and_normalizes_utc():
    base=datetime(2026,1,1,2,tzinfo=timezone(timedelta(hours=2)))
    cache=build("gpmf",[(base,90.0),(base+timedelta(seconds=1),None),(base+timedelta(seconds=2),180.0)],[])
    assert [cache.lookup(i)["extra_indicators"]["compass"][0] for i in range(3)]==[90.0,None,180.0]


def test_both_compass_modes_render_and_cache_independently():
    from tests.test_compass_rendering import _render_compass, _compass_cfg, _red_points
    from src.indicators.gauge import _render_gauge_indicator
    from src.gui.qt.models import compass_indicator_fields
    fields = {f.name: f for f in compass_indicator_fields()}
    assert [value for value, _ in fields["compass_rotation_mode"].choices] == ["needle", "rose"]
    north = _render_compass(0)
    east = _render_compass(90)
    cfg = _compass_cfg(compass_rotation_mode="rose")
    rose = _render_gauge_indicator(
        1920, 1080, {"indicators": {"compass": cfg}}, "", "compass",
        90, "deg", "Compass", cfg, 1080, 1, 18, None, 0, 360, 0, 10,
        100, 1, formatted_val="090deg",
    )[0]
    assert north.tobytes() != east.tobytes()
    assert rose.tobytes() != east.tobytes()
    points = _red_points(rose)
    assert len(points) > 0
    assert points[:, 0].mean() < 120
    assert abs(points[:, 1].mean() - 120) < 3


def test_rose_final_raster_rotates_cardinals_and_keeps_needle_fixed(monkeypatch):
    """Observe final pixels, using asymmetric colored glyph fiducials, no OCR."""
    import math
    import numpy as np
    from PIL import ImageDraw
    from tests.test_compass_rendering import _compass_cfg
    from src.indicators.gauge import _render_gauge_indicator, clear_gauge_cache, clear_compass_cache
    colors = {
        "N": ((240, 20, 30), (130, 10, 20)),
        "E": ((20, 240, 30), (10, 130, 20)),
        "S": ((20, 30, 240), (10, 20, 130)),
        "W": ((240, 20, 240), (130, 10, 130)),
    }
    original = ImageDraw.ImageDraw.text
    def glyph_marker(draw, xy, text, *args, **kwargs):
        if text not in colors:
            return original(draw, xy, text, *args, **kwargs)
        x, y = xy
        # Two unequal/off-axis marks encode both identity and glyph orientation.
        # Offset from the centerline keeps the stationary needle from hiding N.
        head, tail = colors[text]
        draw.rectangle((x + 7, y - 4, x + 13, y + 2), fill=(*head, 255))
        draw.rectangle((x + 19, y + 8, x + 23, y + 12), fill=(*tail, 255))
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", glyph_marker)
    cfg = _compass_cfg(
        compass_rotation_mode="rose", compass_show_heading=False,
        compass_needle_color="#FFFFFF", compass_ring_color="#808080",
        compass_tick_color="#606060", shadow_enabled=False,
    )
    def render(heading):
        clear_gauge_cache()
        clear_compass_cache()
        image = _render_gauge_indicator(
            1920, 1080, {}, "", "compass", heading, "", "", cfg,
            1080, 0, 18, None, 0, 360, 0, 10, 100, 1,
        )[0]
        return np.asarray(image).copy()
    def point(frame, rgb):
        mask = np.all(frame[:, :, :3] == rgb, axis=2) & (frame[:, :, 3] == 255)
        ys, xs = np.where(mask)
        assert len(xs) >= 3, "Final raster lost a cardinal fiducial"
        return np.array([xs.mean(), ys.mean()])
    base = render(0)
    center = np.array([(base.shape[1] - 1) / 2, (base.shape[0] - 1) / 2])
    needle = np.all(base[:, :, :3] == 255, axis=2) & (base[:, :, 3] == 255)
    assert needle.sum() > 20
    for heading in (0, 30, 90, 180, 270, 359, 1, 360):
        frame = render(heading)
        theta = math.radians(heading)
        rotation = np.array([[math.cos(theta), math.sin(theta)],
                             [-math.sin(theta), math.cos(theta)]])
        for cardinal, (head, tail) in colors.items():
            for rgb in (head, tail):
                expected = center + rotation @ (point(base, rgb) - center)
                assert np.linalg.norm(point(frame, rgb) - expected) < 1.1
            # The asymmetric glyph axis rotates with the dial, never upright.
            expected_axis = rotation @ (point(base, tail) - point(base, head))
            assert np.linalg.norm((point(frame, tail) - point(frame, head)) - expected_axis) < 1.1
        actual_needle = np.all(frame[:, :, :3] == 255, axis=2) & (frame[:, :, 3] == 255)
        assert np.array_equal(actual_needle, needle)
    assert np.array_equal(render(360), base)
    # Symmetric small steps around wrap have the same geometric displacement.
    n_minus, n_zero, n_plus = [point(render(h), colors["N"][0]) for h in (359, 0, 1)]
    assert abs(np.linalg.norm(n_minus - n_zero) - np.linalg.norm(n_plus - n_zero)) < 1.1


def test_compass_preview_final_surface_parity_on_bright_background():
    from PIL import Image
    from src.indicators.compositor import compose_overlay
    from src.telemetry_heading import interpolate_heading
    base = datetime(2026,1,1,tzinfo=timezone.utc)
    samples = [(base,359.0),(base+timedelta(seconds=2),1.0)]
    for mode in ("needle", "rose"):
        cache = build("gpmf", samples, [(base,180.0)])
        layout = {"global":{"text_outline":3}, "indicators":{"compass":{
            "enabled":True,"form":"gauge","gauge_style":"compass","x":50,"y":50,
            "size":15,"font_size":1.5,"compass_rotation_mode":mode}}}
        for width,height in ((960,540),(1920,1080),(3840,2160)):
            for i in range(3):
                preview_value = interpolate_heading(samples,base+timedelta(seconds=i))
                final_value = cache.lookup(i)["extra_indicators"]["compass"][0]
                def render(value):
                    hud = compose_overlay(width,height,layout,r"C:\Windows\Fonts\arial.ttf","","",0,0,
                        indicator_values={"compass":value},render_keys={"compass"},reuse_canvas=False)
                    return Image.alpha_composite(Image.new("RGBA",(width,height),"white"),hud)
                assert render(preview_value).tobytes() == render(final_value).tobytes()
