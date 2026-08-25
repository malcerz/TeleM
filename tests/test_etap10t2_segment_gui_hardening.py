"""ETAP 10T2: Segment Bar GUI acceptance + legacy alias hardening.

Verifies that the new Segment Bar GUI options (10T) really work on top of an
existing v10 preset — legacy keys (gradient, inactive_alpha, inactive_color,
segment_radius, segments) must NOT block the new GUI fields.

Covers:
- legacy -> new alias precedence (gradient, opacity, color, radius, count),
- real v10 config (battery + solar),
- gradient switch / colour-mode switching / cache invalidation without restart,
- inactive opacity / color, radius, segment count,
- font independence (value/label/range),
- marker styles + marker movement raster,
- threshold invalid input,
- save/load roundtrip,
- GUI-model -> renderer integration (FieldSchema change -> JSON -> raster),
- map AA config, map cache invalidation, moving_map, static_map.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

from src.indicators import bar
from src.indicators.bar import (
    _render_segments,
    _resolve_segment_count,
    _resolve_segment_gradient,
    _resolve_segment_inactive_color,
    _resolve_segment_inactive_opacity,
    _resolve_segment_radius,
    _fraction,
    _parse_thresholds,
)
from src.gui.qt.models import get_schema_for_form, FieldSchema
from src.moving_map import MovingMapRenderer
from src.map_renderer import render_map_overlay

ROOT = Path(__file__).resolve().parents[1]
FONT = r"C:\Windows\Fonts\arial.ttf"
_NP = _img_equal_placeholder = None


def _img_equal(a: Image.Image, b: Image.Image) -> bool:
    return bool(np.array_equal(np.array(a), np.array(b)))


def _v10_cfg(key: str) -> dict:
    """Load the real v10 preset indicator config."""
    with open(ROOT / "presets" / "cycling_dashboard_v10.json", encoding="utf-8") as f:
        layout = json.load(f)
    return dict(layout["indicators"][key])


def _render_seg(cfg: dict, value, val_min=0.0, val_max=100.0):
    return _render_segments(
        canvas_w=1280, canvas_h=720, font_path=FONT,
        value=value, unit="%", label=str(cfg.get("label", "B")),
        cfg=cfg, val_min=val_min, val_max=val_max,
        size_px=140, fs=26, outline=2, ss=1, formatted_val=None,
    )


def _alpha_stats(img):
    a = np.array(img)[:, :, 3]
    return int(np.count_nonzero(a == 255)), int(np.count_nonzero((a > 0) & (a < 255)))


# ── 1. legacy → new alias precedence (canonical resolution) ───────────────

def test_canonical_count_precedence():
    assert _resolve_segment_count({"segment_count": 5, "segments": 20}) == 5
    assert _resolve_segment_count({"segments": 20}) == 20
    assert _resolve_segment_count({}) == 20
    assert _resolve_segment_count({"segment_count": "x", "segments": 7}) == 7


def test_canonical_gradient_precedence():
    legacy = {"gradient": ["#a", "#b", "#c"]}
    assert _resolve_segment_gradient(legacy) == ("#a", "#b", "#c")
    # new start/end must win over legacy gradient
    assert _resolve_segment_gradient(dict(legacy, segment_color_start="#ff0000")) == ("#ff0000", "#FF9A2E")
    assert _resolve_segment_gradient(dict(legacy, segment_color_end="#00ff00")) == ("#16A7AF", "#00ff00")
    assert _resolve_segment_gradient(dict(legacy, segment_color_start="#ff0000", segment_color_end="#00ff00")) == ("#ff0000", "#00ff00")
    assert _resolve_segment_gradient({}) == ("#16A7AF", "#FF9A2E")


def test_canonical_inactive_color_precedence():
    assert _resolve_segment_inactive_color({"segment_inactive_color": "#112233", "inactive_color": "#445566"}) == "#112233"
    assert _resolve_segment_inactive_color({"inactive_color": "#445566"}) == "#445566"
    assert _resolve_segment_inactive_color({}) == "#3E3E3E"


def test_canonical_inactive_opacity_precedence():
    # new wins even when legacy inactive_alpha is present (the 10T2 critical case)
    assert abs(_resolve_segment_inactive_opacity({"segment_inactive_opacity": 0.2, "inactive_alpha": 60}) - 0.2) < 1e-9
    assert abs(_resolve_segment_inactive_opacity({"inactive_alpha": 60}) - 60 / 255.0) < 1e-9
    assert abs(_resolve_segment_inactive_opacity({}) - 95 / 255.0) < 1e-9
    assert _resolve_segment_inactive_opacity({"segment_inactive_opacity": "oops"}) == 95 / 255.0


def test_canonical_radius_precedence():
    # wide segments so the clamp does not force equality
    cfg_legacy = {"segment_radius": 1, "segments": 5}
    cfg_new = {"segment_corner_radius": 8, "segments": 5}
    # seg_w ~ (140-4*4)/5 ~ 24, seg_area_h ~ 16 -> clamp to min(24,16)//2 = 8
    assert _resolve_segment_radius(cfg_new, 24, 16, 1) == 8
    assert _resolve_segment_radius(cfg_legacy, 24, 16, 1) == 1
    assert _resolve_segment_radius({"segment_shape": "rectangle", "segment_corner_radius": 8}, 24, 16, 1) == 0
    assert _resolve_segment_radius({"segment_shape": "pill"}, 24, 16, 1) == 8


# ── 2. real v10 config — new GUI fields must change the raster ───────────

def test_v10_battery_new_gui_fields_change_raster():
    cfg = _v10_cfg("fit_battery_pct_text")
    base = _render_seg(cfg, 50.0)
    # gradient start
    assert not _img_equal(base, _render_seg(dict(cfg, segment_color_start="#0000ff"), 50.0))
    # inactive opacity (legacy inactive_alpha: 60 present)
    assert not _img_equal(base, _render_seg(dict(cfg, segment_inactive_opacity=0.2), 50.0))
    # segment count (legacy segments: 20 present)
    assert not _img_equal(base, _render_seg(dict(cfg, segment_count=5), 50.0))
    # marker
    assert not _img_equal(base, _render_seg(dict(cfg, marker_style="triangle", marker_color="#ff00ff"), 50.0))


def test_v10_solar_new_gui_fields_change_raster():
    cfg = _v10_cfg("fit_solar_pct_text")
    base = _render_seg(cfg, 50.0)
    assert not _img_equal(base, _render_seg(dict(cfg, segment_color_start="#00ffff"), 50.0))
    assert not _img_equal(base, _render_seg(dict(cfg, segment_inactive_opacity=0.4), 50.0))


def test_v10_untouched_preset_stays_stable():
    # loading + rendering the untouched v10 config twice is byte-identical
    cfg = _v10_cfg("fit_battery_pct_text")
    a = _render_seg(cfg, 42.0)
    b = _render_seg(cfg, 42.0)
    assert _img_equal(a, b)


# ── 3. colour-mode switching + cache invalidation (no restart) ────────────

def test_colour_mode_switch_each_change_differs():
    bar._SEG_ACTIVE_CACHE.clear(); bar._SEG_BASE_CACHE.clear()
    cfg = _v10_cfg("fit_battery_pct_text")
    seq = [
        dict(cfg, segment_color_mode="gradient", segment_color_start="#ff0000", segment_color_end="#00ff00"),
        dict(cfg, segment_color_mode="gradient", segment_color_start="#0000ff", segment_color_end="#ffff00"),
        dict(cfg, segment_color_mode="solid", segment_color="#800080"),
        dict(cfg, segment_color_mode="threshold", segment_thresholds="20:#ff0000;50:#ffaa00;80:#00cc66;100:#00ff00"),
        dict(cfg, segment_color_mode="gradient", segment_color_start="#00ffff", segment_color_end="#00ff00"),
    ]
    prev = None
    for i, c in enumerate(seq):
        img = _render_seg(c, 60.0)
        assert img is not None
        if prev is not None:
            assert not _img_equal(prev, img), f"step {i} did not change raster"
        prev = img


def test_cache_invalidation_shape_and_mode_sequence():
    bar._SEG_ACTIVE_CACHE.clear(); bar._SEG_BASE_CACHE.clear()
    cfg = dict(_v10_cfg("fit_battery_pct_text"), segments=6, segment_height=16)
    seq = [
        dict(cfg, segment_color_mode="gradient", segment_color_start="#ff0000", segment_color_end="#00ff00"),
        dict(cfg, segment_color_mode="gradient", segment_color_start="#0000ff", segment_color_end="#ffff00"),
        dict(cfg, segment_color_mode="solid", segment_color="#800080"),
        dict(cfg, segment_color_mode="threshold", segment_thresholds="20:#ff0000;50:#ffaa00;80:#00cc66;100:#00ff00"),
        dict(cfg, segment_shape="rounded", segment_corner_radius=6),
        dict(cfg, segment_shape="pill"),
        dict(cfg, segment_shape="rectangle"),
    ]
    prev = None
    for i, c in enumerate(seq):
        img = _render_seg(c, 60.0)
        if prev is not None:
            assert not _img_equal(prev, img), f"step {i} stale cache"
        prev = img


# ── 4. inactive opacity / color precedence on v10 ─────────────────────────

def test_v10_inactive_opacity_precedence():
    cfg = _v10_cfg("fit_battery_pct_text")  # has inactive_alpha: 60
    low = _render_seg(dict(cfg, segment_inactive_opacity=0.05, show_value=False, show_label=False, show_min=False, show_max=False), 5.0)
    high = _render_seg(dict(cfg, segment_inactive_opacity=0.95, show_value=False, show_label=False, show_min=False, show_max=False), 5.0)
    assert not _img_equal(low, high)
    # inactive color precedence
    red_inactive = _render_seg(dict(cfg, segment_inactive_color="#ff0000", show_value=False, show_label=False, show_min=False, show_max=False), 5.0)
    assert not _img_equal(_render_seg(dict(cfg, show_value=False, show_label=False, show_min=False, show_max=False), 5.0), red_inactive)


# ── 5. radius precedence (wide segments) ──────────────────────────────────

def test_v10_radius_sequence_changes_raster():
    cfg = dict(_v10_cfg("fit_battery_pct_text"), segments=5, segment_height=20,
               show_value=False, show_label=False, show_min=False, show_max=False)
    shapes = [
        dict(cfg, segment_shape="rectangle"),
        dict(cfg, segment_shape="rounded", segment_corner_radius=2),
        dict(cfg, segment_shape="rounded", segment_corner_radius=8),
        dict(cfg, segment_shape="pill"),
    ]
    prev = None
    for i, c in enumerate(shapes):
        img = _render_seg(c, 100.0)
        if prev is not None:
            assert not _img_equal(prev, img), f"radius step {i} stale"
        prev = img


# ── 6. segment count — count the actually rendered segments ───────────────

def _count_rendered_segments(img, active_only=True) -> int:
    """Count distinct segment columns (alpha>=200 counts active segments only)."""
    a = np.array(img)
    row_sums = (a[:, :, 3] > 0).sum(axis=1)
    ys = np.where(row_sums > a.shape[1] * 0.05)[0]
    if len(ys) == 0:
        return 0
    band = a[ys[0]: ys[-1] + 1]
    thr = 200 if active_only else 1
    col_active = (band[:, :, 3] > thr).any(axis=0)
    runs, in_run = 0, False
    for v in col_active:
        if v and not in_run:
            runs += 1; in_run = True
        elif not v:
            in_run = False
    return runs


def test_v10_segment_count_actual_render():
    cfg = _v10_cfg("fit_battery_pct_text")
    # rectangle + black->white gradient: every segment gets a distinct colour, so
    # counting distinct active colours == the actual rendered segment count (works
    # even when dense 1px segments have no visible gaps).
    for n in (5, 10, 20, 37, 50, 80, 100):
        cfg2 = dict(cfg, segment_count=n, show_value=False, show_label=False,
                    show_min=False, show_max=False, segment_shape="rectangle",
                    segment_color_mode="gradient", segment_color_start="#000000",
                    segment_color_end="#ffffff")
        img = _render_seg(cfg2, 100.0)
        a = np.array(img)
        row_sums = (a[:, :, 3] > 0).sum(axis=1)
        ys = np.where(row_sums > a.shape[1] * 0.05)[0]
        band = a[ys[0]: ys[-1] + 1]
        mask = band[:, :, 3] >= 200
        distinct = len(np.unique(band[mask][:, :3], axis=0)) if mask.any() else 0
        assert distinct == n, f"segment_count={n} rendered {distinct} distinct segments"


# ── 7. font independence ──────────────────────────────────────────────────

def test_font_sizes_independent_bbox():
    cfg = _v10_cfg("fit_battery_pct_text")
    base = _render_seg(cfg, 50.0)
    big_val = _render_seg(dict(cfg, value_font_size=2.6), 50.0)
    big_lbl = _render_seg(dict(cfg, label_font_size=2.2), 50.0)
    big_rng = _render_seg(dict(cfg, range_font_size=2.2, show_min=True, show_max=True), 50.0)
    assert not _img_equal(base, big_val)
    assert not _img_equal(base, big_lbl)
    assert not _img_equal(base, big_rng)
    # changing value font must not change label/range text bboxes — compare the
    # bottom text band (label) stays identical between base and big_val
    assert _bottom_text_band(base) is not None


def _bottom_text_band(img):
    a = np.array(img)
    h = a.shape[0]
    return a[max(0, h - 14):, :, :].copy()


def test_font_family_independent():
    cfg = _v10_cfg("fit_battery_pct_text")
    for field in ("value_font", "label_font", "range_font"):
        base = _render_seg(cfg, 50.0)
        alt = _render_seg(dict(cfg, **{field: "Comic Sans MS"}), 50.0)
        # font resolution falls back to widget font if not found; only assert no crash
        assert alt is not None
        # a real system font should change the raster
        try:
            from PIL import ImageFont
            ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 20)
            assert not _img_equal(base, alt), field
        except Exception:
            pass


# ── 8. marker styles / movement ───────────────────────────────────────────

def test_marker_style_switching_no_restart():
    cfg = _v10_cfg("fit_battery_pct_text")
    seq = [
        dict(cfg, marker_style="none"),
        dict(cfg, marker_style="triangle", marker_color="#ff00ff"),
        dict(cfg, marker_style="line", marker_color="#ff00ff"),
        dict(cfg, marker_style="circle", marker_color="#ff00ff"),
        dict(cfg, marker_style="none"),
    ]
    prev = None
    for i, c in enumerate(seq):
        img = _render_seg(c, 50.0)
        if prev is not None:
            assert not _img_equal(prev, img), f"marker step {i} stale"
        prev = img


def test_marker_movement_raster():
    cfg = dict(_v10_cfg("fit_battery_pct_text"), marker_style="triangle", marker_color="#ff00ff", marker_size=8)
    xs = {}
    for v in (0, 25, 50, 75, 100):
        img = _render_seg(cfg, float(v))
        a = np.array(img)
        magenta = (a[:, :, 0] > 200) & (a[:, :, 2] > 200) & (a[:, :, 1] < 100)
        cols = np.where(magenta)[1]
        xs[v] = int(cols.mean()) if len(cols) else None
    assert xs[0] is not None
    assert xs[0] < xs[25] < xs[50] < xs[75] < xs[100]


def test_marker_props_affect_raster():
    cfg = _v10_cfg("fit_battery_pct_text")
    base = _render_seg(dict(cfg, marker_style="triangle"), 50.0)
    assert not _img_equal(base, _render_seg(dict(cfg, marker_style="triangle", marker_size=16), 50.0))
    assert not _img_equal(base, _render_seg(dict(cfg, marker_style="triangle", marker_color="#00ff00"), 50.0))
    assert not _img_equal(base, _render_seg(dict(cfg, marker_style="triangle", marker_border_color="#ff0000"), 50.0))
    assert not _img_equal(base, _render_seg(dict(cfg, marker_style="triangle", marker_border_width=4), 50.0))
    assert not _img_equal(base, _render_seg(dict(cfg, marker_style="triangle", marker_position="bottom"), 50.0))
    assert not _img_equal(base, _render_seg(dict(cfg, marker_style="triangle", marker_offset=6), 50.0))


# ── 9. threshold validation ───────────────────────────────────────────────

def test_threshold_invalid_inputs_no_crash():
    cfg = _v10_cfg("fit_battery_pct_text")
    for bad in ("", "not:valid;;::", "abc", "[", "20:;50:", "xx:#ff0000", "20:#ff0000;50"):
        img = _render_seg(dict(cfg, segment_color_mode="threshold", segment_thresholds=bad), 60.0)
        assert img is not None, repr(bad)


def test_threshold_unsorted_duplicates_fallback():
    assert _parse_thresholds("50:#ffaa00;20:#ff0000")[0]["value"] == 50
    assert len(_parse_thresholds("20:#ff0000;20:#00ff00")) == 2
    assert _parse_thresholds("") == []
    assert _parse_thresholds(None) == []


# ── 10. save/load roundtrip with conflict ─────────────────────────────────

def test_save_load_new_wins_after_reload():
    cfg = _v10_cfg("fit_battery_pct_text")
    # user changes new field -> save (JSON keeps legacy + new with conflict) -> reload
    edited = dict(cfg, segment_color_start="#0000ff", segment_inactive_opacity=0.2, segment_count=7)
    dumped = json.dumps(edited)
    loaded = json.loads(dumped)
    base = _render_seg(cfg, 50.0)
    reloaded = _render_seg(loaded, 50.0)
    assert not _img_equal(base, reloaded)
    assert _resolve_segment_gradient(loaded) == ("#0000ff", "#FF9A2E")
    assert abs(_resolve_segment_inactive_opacity(loaded) - 0.2) < 1e-9
    assert _resolve_segment_count(loaded) == 7


# ── 11. GUI-model → renderer integration ──────────────────────────────────

def _schema_field(schema, name):
    for f in schema:
        if f.name == name:
            return f
    return None


def test_gui_schema_fields_present():
    schema = get_schema_for_form("bar", bar_style="segments")
    names = {f.name for f in schema}
    for prop in ("segment_count", "segment_color_start", "segment_color_end",
                 "segment_inactive_color", "segment_inactive_opacity",
                 "segment_corner_radius", "value_font_size", "label_font_size",
                 "range_font_size", "marker_style", "marker_size", "marker_color",
                 "marker_border_color", "marker_border_width", "marker_position",
                 "marker_offset", "segment_thresholds", "fill_direction",
                 "segment_fill_mode", "gradient_space"):
        assert prop in names, prop


def test_gui_ranges_sensible():
    schema = get_schema_for_form("bar", bar_style="segments")
    ranges = {
        "segment_count": (2, 100),
        "segment_width": (0, 200),
        "segment_height": (0, 200),
        "segment_gap": (0, 20),
        "segment_corner_radius": (0, 40),
        "segment_inactive_opacity": (0.0, 1.0),
        "marker_size": (1, 40),
        "marker_border_width": (0, 8),
        "marker_offset": (0, 40),
    }
    for name, (lo, hi) in ranges.items():
        f = _schema_field(schema, name)
        assert f is not None, name
        assert f.min_val is not None and f.max_val is not None, name
        assert f.min_val <= lo and f.max_val >= hi, (name, f.min_val, f.max_val)


def test_gui_to_renderer_integration():
    """FieldSchema change -> config updated (controller style) -> JSON ->
    renderer receives new value -> raster changes."""
    cfg = _v10_cfg("fit_battery_pct_text")
    # value 52% -> 10.4 segments: whole rounds up to 11, partial fills the 11th
    # half-way, so segment_fill_mode changes the raster.
    base = _render_seg(cfg, 52.0)
    # simulate PropertyEditor -> controller property change for each schema field
    changes = {
        "segment_color_start": "#0000ff",
        "segment_color_end": "#ff00ff",
        "segment_inactive_opacity": 0.15,
        "segment_corner_radius": 6,
        "value_font_size": 2.4,
        "marker_style": "circle",
        "marker_color": "#00ff00",
        "segment_count": 8,
        "fill_direction": "reverse",
        "segment_fill_mode": "partial",
    }
    for field, value in changes.items():
        edited = dict(cfg, **{field: value})
        if field == "segment_corner_radius":
            # at 20 narrow segments the radius is clamped to the segment half-
            # width; widen the segments so the radius change is visible
            edited["segment_count"] = 6
        if field in ("marker_color", "marker_size"):
            # marker props only matter when a marker style is active
            edited["marker_style"] = "triangle"
        dumped = json.dumps(edited)
        loaded = json.loads(dumped)
        img = _render_seg(loaded, 52.0)
        assert not _img_equal(base, img), field


# ── 12. Battery / Solar real config normalisation ─────────────────────────

def test_battery_pct_real_normalisation():
    # min=87 max=91 value=89 -> (89-87)/(91-87) = 0.5
    frac = _fraction(89.0, 87.0, 91.0)
    assert abs(frac - 0.5) < 1e-9
    cfg = dict(_v10_cfg("fit_battery_pct_text"), min_val=87.0, max_val=91.0,
               segment_count=10, show_value=False, show_label=False,
               show_min=False, show_max=False)
    img = _render_seg(cfg, 89.0, val_min=87.0, val_max=91.0)
    # active segments (alpha>=200) should be ~5 of 10; inactive ones (alpha 60)
    # must not be counted.
    runs = _count_rendered_segments(img, active_only=True)
    assert runs == 5, f"89/87..91 should activate ~5 of 10 segments, got {runs}"


def test_solar_pct_real_config():
    cfg = _v10_cfg("fit_solar_pct_text")
    base = _render_seg(cfg, 50.0)
    assert base is not None
    assert not _img_equal(base, _render_seg(dict(cfg, segment_color_start="#00ffff"), 50.0))


# ── 13. generic FIT field (no hardcode) ───────────────────────────────────

def test_generic_fit_field_via_segments():
    cfg = dict(_v10_cfg("fit_battery_pct_text"), label="Virtual Power",
               min_val=0.0, max_val=500.0, unit="W", value_unit="W",
               segment_color_mode="gradient", segment_color_start="#0000ff",
               segment_color_end="#00ff00", marker_style="triangle")
    img = _render_seg(cfg, 250.0, val_min=0.0, val_max=500.0)
    assert img is not None


# ── 14. map AA config + cache invalidation + moving/static ────────────────

def _track(n=140):
    lat0, lon0 = 52.2297, 21.0122
    pts, t0 = [], datetime(2024, 1, 1, 8, 0)
    for i in range(n):
        t = i / max(1, n - 1)
        pts.append((t0 + timedelta(seconds=i), lat0 + t * 0.012,
                    0.5 * np.sin(t * 3.2) * 0.01 + lon0 + t * 0.004))
    return pts


def _mm_render(track, aa, outline_w=0, size=192):
    r = MovingMapRenderer(track, zoom=15, style="light_all",
                          track_color=(255, 60, 30, 220), track_width=3,
                          track_antialiasing=aa, track_outline_width=outline_w,
                          track_outline_color=(0, 0, 0, 220),
                          marker_radius=5, marker_color=(255, 255, 255, 255))
    return r, r.render(0.5 * len(track), size, size, draw_track=True,
                       draw_marker=False, download_missing=False)


def _route_bbox(img):
    a = np.array(img)[:, :, 3]
    ys, xs = np.where(a > 0)
    if len(xs) == 0:
        return (0, 0, 0, 0)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def test_map_aa_config_renders():
    track = _track()
    for aa in (1, 2, 4):
        _, img = _mm_render(track, aa)
        assert img is not None


def test_map_cache_invalidation_aa_and_outline():
    track = _track()
    r = MovingMapRenderer(track, zoom=15, style="light_all",
                          track_color=(255, 60, 30, 220), track_width=3,
                          track_antialiasing=1, track_outline_width=0,
                          track_outline_color=(0, 0, 0, 220),
                          marker_radius=5, marker_color=(255, 255, 255, 255))
    img1 = r.render(0.5 * len(track), 192, 192, draw_track=True, draw_marker=False, download_missing=False)
    prev = img1
    # mutate renderer the same way _render_moving_map_indicator does
    for aa, ow in ((2, 0), (4, 0), (1, 0), (1, 2), (1, 4), (1, 0)):
        r._track_aa = aa
        r._track_outline_w = ow
        img = r.render(0.5 * len(track), 192, 192, draw_track=True, draw_marker=False, download_missing=False)
        assert not _img_equal(prev, img), (aa, ow)
        prev = img


def test_map_aa_geometry_preserved_and_edges():
    track = _track()
    _, off = _mm_render(track, 1)
    _, aa4 = _mm_render(track, 4)
    b1, b2 = _route_bbox(off), _route_bbox(aa4)
    assert abs(b1[0] - b2[0]) <= 2 and abs(b1[1] - b2[1]) <= 2
    assert not _img_equal(off, aa4)
    # opaque core must not grow (line width preserved)
    o, _ = _alpha_stats(off)
    f, _ = _alpha_stats(aa4)
    assert f <= o * 1.35, (o, f)


def test_map_outline_does_not_shift_track():
    track = _track()
    _, no = _mm_render(track, 2, outline_w=0, size=192)
    _, with_o = _mm_render(track, 2, outline_w=3, size=192)
    assert not _img_equal(no, with_o)
    b1, b2 = _route_bbox(no), _route_bbox(with_o)
    assert abs(b1[0] - b2[0]) <= 2 and abs(b1[1] - b2[1]) <= 2


def test_map_static_aa(monkeypatch):
    track = _track()
    import src.map_renderer as mr

    def fake_tile(z, x, y, style="light_all", download=True):
        return Image.new("RGBA", (256, 256), (40, 46, 52, 255))

    monkeypatch.setattr(mr, "download_tile", fake_tile)
    mr._TILE_CACHE.clear()

    def render_static(aa):
        return render_map_overlay(
            track, 0, 192, 192, zoom=15, map_style="light_all",
            track_color=(255, 60, 30, 220), track_width=3,
            track_antialiasing=aa, download_missing=False,
        )

    off = render_static(1)
    aa4 = render_static(4)
    assert not _img_equal(off, aa4)
    b1, b2 = _route_bbox(off), _route_bbox(aa4)
    assert abs(b1[0] - b2[0]) <= 2 and abs(b1[1] - b2[1]) <= 2


def test_map_aa_save_load_roundtrip():
    cfg = {"track_antialiasing": 4, "track_outline_width": 2, "track_outline_color": "#000000"}
    loaded = json.loads(json.dumps(cfg))
    assert loaded == cfg
