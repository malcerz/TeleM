from datetime import datetime, timezone

from PIL import Image

from src.gui.layout_manager import normalize_layout
from src.gui.map_context import MapContext
from src.gui.qt._mixins.project_mixin import _map_provider_from_layout
from src.indicators.dispatcher import render_value_indicator
from src.indicators.map_prepare import set_current_map_context


def test_initial_map_preload_uses_saved_def_layout_provider():
    layout = normalize_layout("def_layout.json", 1280, 720)
    assert layout["indicators"]["track_map"]["map_style"] == "satellite"
    assert _map_provider_from_layout(layout) == "satellite"


def test_saved_satellite_map_renders_after_same_indicator_context_becomes_ready():
    layout = {
        "global": {},
        "indicators": {
            "track_map": {
                "enabled": True, "form": "map", "x": 10, "y": 10,
                "size": 30, "map_style": "satellite", "marker_size": 7,
            },
        },
    }
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    track = [(start, 52.0, 21.0), (start, 52.001, 21.001)]
    ctx = MapContext()
    ctx.reset("satellite", 2)
    ctx.set_geometry(
        "fit", track, (52.0, 21.0, 52.001, 21.001),
        (52.0005, 21.0005), 12, 4, generation=2,
    )
    ctx.set_ready(Image.new("RGBA", (32, 32), (150, 180, 210, 255)), generation=2)
    set_current_map_context(ctx)

    image, _, _, _ = render_value_indicator(
        640, 480, layout, "", "track_map", 0, "", "",
        gps_track=track, target_dt=start, async_map=True,
    )
    assert image is not None
    assert image.getpixel((image.width // 2, image.height // 2))[:3] != (24, 26, 30)
