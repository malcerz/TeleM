from datetime import datetime, timezone, timedelta

from PIL import Image

from src.gui.map_context import MapContext
from src.indicators.dispatcher import render_value_indicator
from src.indicators.map_prepare import set_current_map_context


def _track():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        (start, 52.0, 21.0),
        (start + timedelta(seconds=10), 52.001, 21.001),
    ]


def _context_with_overview_still_preparing():
    ctx = MapContext()
    ctx.reset(provider="light_all", generation=1)
    ctx.set_geometry(
        "fit", _track(), (52.0, 21.0, 52.001, 21.001),
        (52.0005, 21.0005), 12, 4, generation=1,
    )
    ctx.set_ready(Image.new("RGBA", (32, 32), (180, 210, 230, 255)), generation=1)
    # Simulate detail/provider refinement while retaining usable overview data.
    with ctx._lock:
        ctx.status = "preparing"
        ctx.loaded_tiles = 1
        ctx.required_tiles = 8
        ctx.progress = 0.125
    set_current_map_context(ctx)
    return ctx


def _layout(form):
    return {
        "global": {},
        "indicators": {
            "map": {
                "enabled": True,
                "form": form,
                "x": 0.1,
                "y": 0.1,
                "size": 0.5,
                "map_style": "light_all",
            }
        },
    }


def test_static_map_keeps_overview_visible_while_detail_prepares():
    _context_with_overview_still_preparing()
    img, _, _, _ = render_value_indicator(
        640, 480, _layout("static_map"), "", "map", 0, "", "",
        gps_track=_track(), target_dt=_track()[0][0], async_map=True,
    )
    assert img is not None
    assert img.getpixel((img.width // 2, img.height // 2))[:3] != (24, 26, 30)


def test_moving_map_keeps_overview_visible_while_detail_prepares(monkeypatch):
    _context_with_overview_still_preparing()

    class FakeRenderer:
        def __init__(self, *args, **kwargs):
            pass

        def viewport_tile_coverage(self, *args):
            return 0.0

        def viewport_precache(self, *args, **kwargs):
            pass

    import src.moving_map as moving_map
    monkeypatch.setattr(moving_map, "MovingMapRenderer", FakeRenderer)
    img, _, _, _ = render_value_indicator(
        640, 480, _layout("map"), "", "map", 0, "", "",
        gps_track=_track(), target_dt=_track()[0][0], async_map=True,
    )
    assert img is not None
    assert img.getpixel((img.width // 2, img.height // 2))[:3] != (24, 26, 30)
