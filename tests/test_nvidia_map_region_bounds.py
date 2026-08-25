from pathlib import Path

from src.ffmpeg.command_builder import get_layout_hud_regions
from src.gui.layout_manager import normalize_layout


def test_map_region_is_tall_enough_for_square_map_tile() -> None:
    layout = normalize_layout(Path("def_layout.json"), 1920, 1080)
    layout["indicators"] = {
        "track_map": layout["indicators"]["track_map"],
    }

    _atlas_w, _atlas_h, regions = get_layout_hud_regions(
        layout, 1920, 1080, max_regions=5
    )
    map_cfg = layout["indicators"]["track_map"]
    map_x = round(map_cfg["x"] / 100.0 * 1920)
    map_y = round(map_cfg["y"] / 100.0 * 1080)
    owner = next(region for region in regions if (
        region[0] <= map_x < region[0] + region[4]
        and region[1] <= map_y < region[1] + region[5]
    ))

    map_side = round((map_cfg["size"] / 100.0) * 1920)
    assert owner[5] >= map_side + 60
