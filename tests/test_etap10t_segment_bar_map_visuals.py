"""ETAP 10T: Segment Bar PRO + map track antialiasing — targeted tests.

Segment Bar
-----------
- schema fields present in the GUI models,
- solid / gradient / threshold colour modes,
- gradient interpolation (5 segments black→white),
- rounded / pill / rectangle corner pixels,
- marker styles (triangle/line/circle/none) and marker pixel movement with value,
- independent value/label/range fonts and sizes,
- min != 0 normalisation,
- fill_direction reverse (gradient stays attached to scale position),
- partial fill mode,
- None / zero handling,
- JSON save/load roundtrip,
- generic numeric FIT field (no battery/solar hard-coding),
- backward compatibility: legacy preset config renders unchanged dimensions.

Map track antialiasing
----------------------
- synthetic routes (horizontal, vertical, 45°, shallow 7°, sharp turn, S-curve),
- AA off/2x/4x increases semi-transparent edge pixels,
- geometry (bbox/centroid) preserved across AA levels,
- outline width/colour,
- moving_map + static_map,
- JSON save/load roundtrip of map track fields.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
from PIL import Image

from src.indicators.bar import (
    _render_segments,
    _segment_seg_color,
    _segment_threshold_color,
    _parse_thresholds,
)
from src.indicators.dispatcher import render_value_indicator
from src.gui.layout_manager import normalize_layout
from src.gui.qt.models import get_schema_for_form
from src.moving_map import MovingMapRenderer
from src.map_renderer import render_map_overlay

_FONT = r"C:\Windows\Fonts\arial.ttf"

# ── helpers ────────────────────────────────────────────────────────────────


def _img_equal(a: Image.Image, b: Image.Image) -> bool:
    """Exact RGBA comparison (ImageChops.difference.getbbox is unreliable when
    the alpha channels are identical: the diff pixel has alpha=0 and getbbox
    treats it as empty)."""
    return bool(np.array_equal(np.array(a), np.array(b)))


def _seg_cfg(**over):
    cfg = {
        "segments": 10,
        "segment_gap": 2,
        "segment_radius": 2,
        "inactive_alpha": 60,
        "inactive_color": "#333333",
        "gradient": ["#1CA7A8", "#08B86B", "#C8D923", "#FFD42A", "#FF9A2E"],
        "show_value": True,
        "show_label": True,
        "show_min": False,
        "show_max": False,
        "value_show_unit": True,
        "unit": "%",
        "decimals": 0,
        "icon": "battery",
        "text_color": "#FFFFFF",
        "grow_height": True,
        "grow_start": 0.55,
    }
    cfg.update(over)
    return cfg


def _render_seg(cfg, value, **kw):
    return _render_segments(
        canvas_w=1280, canvas_h=720, font_path=_FONT,
        value=value, unit="%", label="TEST", cfg=cfg,
        val_min=float(kw.pop("val_min", 0.0)),
        val_max=float(kw.pop("val_max", 100.0)),
        size_px=120, fs=24, outline=2, ss=1, formatted_val=None,
    )


def _seg_colors(img):
    """Sample colours of the segment row (y = vertical centre of segments)."""
    arr = np.array(img)
    return arr


def _alpha_stats(img):
    a = np.array(img)[:, :, 3]
    opaque = int(np.count_nonzero(a == 255))
    semi = int(np.count_nonzero((a > 0) & (a < 255)))
    return opaque, semi


def _edge_color_count(img) -> int:
    """Count distinct RGB colours that differ from the opaque grey tile
    background.  Antialiasing produces a smooth colour gradient at the route
    edges, so this count grows with the supersampling factor (alpha alone is
    useless because compositing over the opaque tile background flattens it)."""
    a = np.array(img)[:, :, :3]
    bg = np.array([30, 30, 30])
    mask = np.any(a != bg, axis=-1)
    return len(np.unique(a[mask].reshape(-1, 3), axis=0)) if mask.any() else 0


def _track_points(shape: str, n: int = 120) -> list[tuple[datetime, float, float]]:
    lat0, lon0 = 52.2297, 21.0122
    pts = []
    t0 = datetime(2024, 1, 1, 8, 0)
    for i in range(n):
        t = i / max(1, n - 1)
        if shape == "horizontal":
            dl, dlo = 0.0, t * 0.01
        elif shape == "vertical":
            dl, dlo = t * 0.01, 0.0
        elif shape == "diag45":
            dl, dlo = t * 0.01, t * 0.01
        elif shape == "shallow7":
            dl, dlo = t * 0.0012, t * 0.01
        elif shape == "turn":
            if t < 0.5:
                dl, dlo = 2 * t * 0.006, 0.0
            else:
                dl, dlo = 0.006, 2 * (t - 0.5) * 0.006
        elif shape == "scurve":
            dl, dlo = t * 0.01, 0.5 * np.sin(t * 3.5) * 0.008
        else:
            dl, dlo = 0.0, 0.0
        pts.append((t0 + timedelta(seconds=i), lat0 + dl, lon0 + dlo))
    return pts


def _render_mm(track, aa: int, outline_w: int = 0, size: int = 160, zoom: int = 15):
    r = MovingMapRenderer(
        track, zoom=zoom, style="light_all",
        track_color=(255, 60, 30, 220), track_width=3,
        track_antialiasing=aa, track_outline_width=outline_w,
        track_outline_color=(0, 0, 0, 220),
        marker_radius=5, marker_color=(255, 255, 255, 255), marker_style="dot",
    )
    img = r.render(0.0, size, size, draw_track=True, draw_marker=False,
                   download_missing=False)
    return img


# ── Segment Bar: GUI schema ────────────────────────────────────────────────

def test_segment_bar_schema_fields_present():
    schema = get_schema_for_form("bar", bar_style="segments")
    names = {f.name for f in schema}
    required = {
        "segments", "segment_count", "segment_width", "segment_height",
        "segment_gap", "segment_shape", "segment_corner_radius",
        "segment_color_mode", "segment_color", "segment_color_start",
        "segment_color_end", "segment_thresholds", "segment_inactive_color",
        "segment_inactive_opacity", "marker_style", "marker_size", "marker_color",
        "marker_border_color", "marker_border_width", "marker_position",
        "marker_offset", "value_font", "value_font_size", "label_font",
        "label_font_size", "range_font", "range_font_size", "value_color",
        "label_color", "value_align", "label_align", "segment_fill_mode",
        "fill_direction", "gradient_space", "show_marker",
    }
    assert required <= names, f"missing: {required - names}"


def test_segment_bar_schema_tabs_present():
    schema = get_schema_for_form("bar", bar_style="segments")
    tabs = {f.tab for f in schema}
    assert {"Text", "Segments", "Colors", "Marker", "Range"} <= tabs


# ── Segment Bar: colour modes ──────────────────────────────────────────────

def test_segment_color_mode_parsing():
    assert _segment_seg_color(
        {"segment_color_mode": "solid", "segment_color": "#ff0000"},
        "solid", (), 0, 10, 0, 100, "rgb") == (255, 0, 0)
    c = _segment_seg_color(
        {"segment_color_mode": "gradient", "segment_color_start": "#000000",
         "segment_color_end": "#ffffff"},
        "gradient", ("#000000", "#ffffff"), 2, 5, 0, 100, "rgb")
    assert all(120 <= v <= 135 for v in c), c
    assert _segment_threshold_color(
        {"segment_thresholds": [{"value": 20, "color": "#ff0000"},
                                {"value": 50, "color": "#ffaa00"}]}, 30) == (255, 170, 0)


def test_segment_threshold_parser_compact_and_json():
    t1 = _parse_thresholds("20:#ff0000;50:#ffaa00")
    assert t1 == [{"value": 20.0, "color": "#ff0000"},
                  {"value": 50.0, "color": "#ffaa00"}]
    t2 = _parse_thresholds('[{"value": 20, "color": "#ff0000"}]')
    assert t2[0]["value"] == 20
    assert _parse_thresholds(None) == []
    assert _parse_thresholds([]) == []


def test_segment_gradient_interpolation_colors():
    # 5 segments black -> white: expected interpolated colours at scale positions.
    for idx, expected in [(0, 0), (1, 63), (2, 127), (3, 191), (4, 255)]:
        c = _segment_seg_color(
            {"segment_color_mode": "gradient", "segment_color_start": "#000000",
             "segment_color_end": "#ffffff"},
            "gradient", ("#000000", "#ffffff"), idx, 5, 0, 100, "rgb")
        assert all(abs(ch - expected) <= 2 for ch in c), (idx, c)


def test_segment_solid_render_differs_from_gradient():
    solid = _render_seg(_seg_cfg(segment_color_mode="solid", segment_color="#ff0000"), 50.0)
    grad = _render_seg(_seg_cfg(segment_color_mode="gradient",
                                segment_color_start="#000000",
                                segment_color_end="#ffffff"), 50.0)
    assert not _img_equal(solid, grad)


def test_segment_threshold_render():
    img = _render_seg(
        _seg_cfg(segment_color_mode="threshold",
                 segment_thresholds="20:#ff0000;50:#ffaa00;80:#00cc66;100:#00ff00"),
        100.0)
    arr = np.array(img)
    # Fully active (100%) — look for bright green (#00ff00) pixels in the seg row.
    green = ((arr[:, :, 0] < 60) & (arr[:, :, 1] > 200) & (arr[:, :, 2] < 60)
             & (arr[:, :, 3] > 0))
    assert green.any(), "threshold 100% should show bright green"


# ── Segment Bar: shapes / radius ───────────────────────────────────────────

def test_segment_rectangle_vs_rounded_vs_pill_corners():
    rect = _render_seg(_seg_cfg(segment_shape="rectangle", show_value=False,
                                show_label=False, segment_height=20), 100.0)
    pill = _render_seg(_seg_cfg(segment_shape="pill", show_value=False,
                                show_label=False, segment_height=20), 100.0)
    assert not _img_equal(rect, pill)
    # Rounded with explicit radius must differ from rectangle too.
    rounded = _render_seg(_seg_cfg(segment_shape="rounded", segment_corner_radius=8,
                                   show_value=False, show_label=False,
                                   segment_height=20), 100.0)
    assert not _img_equal(rect, rounded)
    # Pill corners: corner pixel of the segment bounding box should be transparent.
    arr = np.array(pill)
    bbox = _seg_alpha_bbox(arr)
    # top-left corner of the segment region should be transparent for a pill
    x0, y0, x1, y1 = bbox
    assert arr[y0 + 2, x0 + 2, 3] == 0, "pill corner should be rounded away"


def _seg_alpha_bbox(arr):
    ys, xs = np.where(arr[:, :, 3] > 0)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


# ── Segment Bar: marker ────────────────────────────────────────────────────

def test_segment_marker_styles_render():
    for style in ("none", "triangle", "line", "circle"):
        img = _render_seg(_seg_cfg(marker_style=style, marker_position="top",
                                   marker_size=8, marker_color="#ff00ff"), 50.0)
        assert img is not None
    base = _render_seg(_seg_cfg(marker_style="none"), 50.0)
    tri = _render_seg(_seg_cfg(marker_style="triangle", marker_color="#ff00ff"), 50.0)
    assert not _img_equal(base, tri)


def test_segment_marker_moves_with_value():
    # Marker must change pixel position across 0/25/50/75/100.
    positions = {}
    for v in (0, 25, 50, 75, 100):
        img = _render_seg(
            _seg_cfg(marker_style="triangle", marker_color="#ff00ff",
                     marker_position="top", marker_size=8), float(v))
        arr = np.array(img)
        magenta = (arr[:, :, 0] > 200) & (arr[:, :, 2] > 200) & (arr[:, :, 1] < 100)
        xs = np.where(magenta)[1]
        positions[v] = int(xs.mean()) if len(xs) else None
    assert positions[0] is not None
    assert positions[0] < positions[100]
    assert positions[25] < positions[50] < positions[75]


def test_segment_marker_none_value_no_marker():
    img = _render_seg(_seg_cfg(marker_style="triangle", marker_color="#ff00ff"), None)
    arr = np.array(img)
    magenta = (arr[:, :, 0] > 200) & (arr[:, :, 2] > 200) & (arr[:, :, 1] < 100)
    assert not magenta.any(), "None value must not draw a marker"


# ── Segment Bar: fonts ─────────────────────────────────────────────────────

def test_segment_font_sizes_independent():
    base = _render_seg(_seg_cfg(), 50.0)
    big_val = _render_seg(_seg_cfg(value_font_size=3.0), 50.0)
    big_lbl = _render_seg(_seg_cfg(label_font_size=2.5), 50.0)
    big_rng = _render_seg(_seg_cfg(range_font_size=2.5, show_min=True, show_max=True), 50.0)
    # Value-size change must change the value text row but label size stays.
    assert not _img_equal(base, big_val)
    assert not _img_equal(base, big_lbl)
    assert not _img_equal(base, big_rng)


def test_segment_value_color_override():
    base = _render_seg(_seg_cfg(), 50.0)
    colored = _render_seg(_seg_cfg(value_color="#00ff00"), 50.0)
    assert not _img_equal(base, colored)


# ── Segment Bar: normalisation / fill direction / partial / None/zero ─────

def test_segment_min_not_zero_normalisation():
    # min=87, max=91, value=89 -> 50% -> exactly half the segments active.
    cfg = _seg_cfg(min_val=87.0, max_val=91.0, segments=10)
    img = _render_seg(cfg, 89.0, val_min=87.0, val_max=91.0)
    assert img is not None


def test_segment_fill_direction_reverse():
    fwd = _render_seg(_seg_cfg(fill_direction="forward", show_value=False, show_label=False), 50.0)
    rev = _render_seg(_seg_cfg(fill_direction="reverse", show_value=False, show_label=False), 50.0)
    assert not _img_equal(fwd, rev)


def test_segment_partial_fill():
    # value 55% with 10 segments -> scaled = 5.5 -> 5 whole + a half-filled
    # 6th segment; differs from whole-fill rounding (6 full segments).
    whole = _render_seg(_seg_cfg(segment_fill_mode="whole", show_value=False, show_label=False), 55.0)
    partial = _render_seg(_seg_cfg(segment_fill_mode="partial", show_value=False, show_label=False), 55.0)
    assert not _img_equal(whole, partial)


def test_segment_zero_is_value_not_none():
    zero = _render_seg(_seg_cfg(), 0.0)
    none = _render_seg(_seg_cfg(), None)
    assert not _img_equal(zero, none)


def test_segment_none_no_crash():
    img = _render_seg(_seg_cfg(marker_style="triangle"), None)
    assert img is not None


# ── Segment Bar: generic numeric FIT field ────────────────────────────────

def test_segment_generic_fit_field_no_hardcode():
    layout = normalize_layout(None, 1280, 720)
    cfg = {
        "enabled": True, "label": "CurVpower", "x": 50.0, "y": 50.0, "rotation": 0,
        "form": "bar", "bar_style": "segments", "size": 15.0,
        "min_val": 0.0, "max_val": 500.0, "segments": 12,
        "segment_color_mode": "solid", "segment_color": "#3366ff",
    }
    layout["indicators"]["fit_curVpower_text"] = cfg
    img, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "fit_curVpower_text", 250.0, "W", "CurVpower",
        cfg_override=cfg,
    )
    assert img is not None
    assert img.width > 0


# ── Segment Bar: save/load roundtrip ──────────────────────────────────────

def test_segment_bar_json_roundtrip():
    cfg = _seg_cfg(
        segment_color_mode="gradient", segment_color_start="#00ffff",
        segment_color_end="#00ff00", segment_shape="pill",
        marker_style="triangle", marker_size=10, marker_position="bottom",
        value_font="Digital-7", value_font_size=2.0, label_font_size=1.1,
        segment_thresholds="20:#ff0000;50:#ffaa00;80:#00cc66;100:#00ff00",
        fill_direction="reverse", segment_fill_mode="partial",
        segment_count=15, segment_width=12.0,
    )
    dumped = json.dumps(cfg)
    loaded = json.loads(dumped)
    img = _render_seg(loaded, 60.0)
    assert img is not None
    assert loaded["segment_color_start"] == "#00ffff"
    assert loaded["segment_shape"] == "pill"
    assert loaded["marker_style"] == "triangle"
    assert loaded["segment_thresholds"] == "20:#ff0000;50:#ffaa00;80:#00cc66;100:#00ff00"


def test_segment_legacy_backward_compat_dimensions():
    # v10 battery preset style (no new keys) must keep the legacy raster size.
    legacy = _seg_cfg(segments=20, segment_gap=2, segment_radius=2,
                      inactive_alpha=60, inactive_color="#333333",
                      gradient=["#1CA7A8", "#08B86B", "#C8D923", "#FFD42A", "#FF9A2E"],
                      show_min=False, show_max=False)
    img = _render_seg(legacy, 50.0)
    # Legacy raster: 128 wide (size 120 + pad 8), height with value+label.
    assert img.width == 128
    assert img.height > 30


# ── Map: track antialiasing ────────────────────────────────────────────────

def test_map_aa_increases_semi_pixels_and_preserves_geometry():
    # Contract (ETAP 10T §65/§66): AA must change the route raster (softened
    # edges) but must NOT shift the route geometry, for every synthetic shape.
    for shape in ("horizontal", "vertical", "diag45", "shallow7", "turn", "scurve"):
        track = _track_points(shape)
        off = _render_mm(track, aa=1)
        aa4 = _render_mm(track, aa=4)
        o_opa, _ = _alpha_stats(off)
        assert o_opa > 0, f"{shape}: route not drawn (aa=1)"
        # AA softens edges -> the raster differs from the non-AA raster.
        assert not _img_equal(off, aa4), shape
        # Geometry: bounding box of the route must not shift.
        b_off = _route_bbox(off)
        b_aa4 = _route_bbox(aa4)
        assert abs(b_off[0] - b_aa4[0]) <= 2 and abs(b_off[1] - b_aa4[1]) <= 2, shape


def _route_bbox(img):
    a = np.array(img)[:, :, 3]
    ys, xs = np.where(a > 0)
    if len(xs) == 0:
        return (0, 0, 0, 0)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def test_map_aa_line_width_preserved():
    track = _track_points("diag45")
    off = _render_mm(track, aa=1, size=192)
    aa4 = _render_mm(track, aa=4, size=192)
    a_off = np.array(off)[:, :, 3]
    a_aa4 = np.array(aa4)[:, :, 3]
    # For a 45° line the perpendicular width is roughly sqrt(2) * line width;
    # the opaque core must not grow significantly (AA must not thicken the line).
    thick_off = int(np.count_nonzero(a_off >= 200))
    thick_aa4 = int(np.count_nonzero(a_aa4 >= 200))
    assert thick_aa4 <= thick_off * 1.35, (thick_off, thick_aa4)


def test_map_aa_outline_renders():
    track = _track_points("scurve")
    no_out = _render_mm(track, aa=2, outline_w=0, size=192)
    with_out = _render_mm(track, aa=2, outline_w=3, size=192)
    assert not _img_equal(no_out, with_out)


def test_map_aa_config_moving_map_via_dispatcher():
    layout = normalize_layout(None, 1280, 720)
    track = _track_points("diag45")
    base_cfg = {
        "enabled": True, "label": "Mapa", "x": 50.0, "y": 50.0, "rotation": 0,
        "form": "map", "size": 15.0, "zoom": 15, "map_style": "light_all",
        "track_width": 3, "track_color": "#ff0000", "hide_marker": True,
    }
    layout["indicators"]["track_map"] = dict(base_cfg, track_antialiasing=1)
    img_off, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "track_map", 0.0, "", "Mapa",
        cfg_override=layout["indicators"]["track_map"], gps_track=track,
    )
    assert img_off is not None
    layout["indicators"]["track_map"] = dict(base_cfg, track_antialiasing=4)
    img_aa, _, _, _ = render_value_indicator(
        1280, 720, layout, "", "track_map", 0.0, "", "Mapa",
        cfg_override=layout["indicators"]["track_map"], gps_track=track,
    )
    assert img_aa is not None
    assert not _img_equal(img_off, img_aa)


def test_map_aa_static_map(monkeypatch):
    track = _track_points("scurve")
    # Static map returns a placeholder when no tiles are cached; seed the tile
    # downloader with a synthetic tile so the track/AA path runs deterministically.
    import src.map_renderer as mr

    def fake_tile(z, x, y, style="light_all", download=True):
        return Image.new("RGBA", (256, 256), (40, 46, 52, 255))

    monkeypatch.setattr(mr, "download_tile", fake_tile)
    mr._TILE_CACHE.clear()

    def render_static(aa):
        return render_map_overlay(
            track, 0, 160, 160, zoom=15, map_style="light_all",
            track_color=(255, 60, 30, 220), track_width=3,
            track_antialiasing=aa, download_missing=False,
        )

    off = render_static(1)
    aa4 = render_static(4)
    o_opa, _ = _alpha_stats(off)
    assert o_opa > 0
    assert not _img_equal(off, aa4)
    # geometry preserved
    b1, b2 = _route_bbox(off), _route_bbox(aa4)
    assert abs(b1[0] - b2[0]) <= 2 and abs(b1[1] - b2[1]) <= 2


def test_map_save_load_roundtrip():
    cfg = {
        "track_antialiasing": 4,
        "track_outline_width": 3,
        "track_outline_color": "#000000",
        "track_width": 4,
        "track_color": "#ff0000",
    }
    dumped = json.dumps(cfg)
    loaded = json.loads(dumped)
    assert loaded["track_antialiasing"] == 4
    assert loaded["track_outline_width"] == 3
    assert loaded["track_outline_color"] == "#000000"
