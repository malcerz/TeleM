"""Re-opening a project must keep the layout edited in this app session.

Before the fix ``bg_load`` re-read def_layout.json from disk on every MP4
open, so compass edits (e.g. ``compass_heading_mode = gps_imu``) silently
reverted to the last explicitly saved file.
"""
from src.gui.qt._mixins.project_mixin import _working_layout_copy


def test_working_copy_keeps_every_compass_property_and_drops_runtime_keys():
    compass = {
        "enabled": True, "form": "gauge", "gauge_style": "compass", "size": 12.5,
        "compass_heading_mode": "gps_imu", "compass_reference_source": "fit",
        "compass_ring_width": 4, "compass_needle_width": 9, "compass_tick_color": "#12AB34",
        "_presentation_video_start": "runtime", "_presentation_video_end": "runtime",
    }
    layout = {"indicators": {"compass": compass}, "_indicator_availability": {"compass": True},
              "cut_regions": [[1, 2]], "global": {"font": "Digital-7"}}
    copy = _working_layout_copy(layout)
    got = copy["indicators"]["compass"]
    for key, value in compass.items():
        if key.startswith("_presentation"):
            assert key not in got
        else:
            assert got[key] == value
    assert "_indicator_availability" not in copy and "cut_regions" not in copy
    assert copy["global"] == {"font": "Digital-7"}
    # detached: later edits of the copy never leak into the previous project
    got["size"] = 1.0
    assert compass["size"] == 12.5


def test_working_copy_rejects_non_layouts():
    assert _working_layout_copy(None) is None
    assert _working_layout_copy({"indicators": []}) is None
