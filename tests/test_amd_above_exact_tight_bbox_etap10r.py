"""ETAP 10R: AMD ABOVE — EXACT tight-bbox propagation (Variant A) tests.

Targeted tests for:
- cluster membership tracking (identical candidate rects to SCAN),
- alpha-tight bbox semantics (A == 0 / RGB != 0 pixels excluded),
- rotation 0 / 90 / 180 / 270,
- None transitions,
- dynamic text width,
- moving widget,
- overlap,
- SCAN vs EXACT region geometry + RGBA bytes parity,
- per-cluster SCAN fallback (missing / clipped / invalid),
- mode parsing (EXACT / SCAN / CANDIDATE / unknown fallback).

The CPU-level SCAN vs EXACT region parity here is the strongest pre-encode
test: it compares the *actual upload geometry and bytes* (not just the
reconstructed overlay), which is exactly what the GPU ClearPreviousAboveMap
erase contract depends on.
"""

from __future__ import annotations

import os
from PIL import Image, ImageDraw

from src.ffmpeg.amd_native_exporter import (
    _cluster_above_bboxes,
    _cluster_above_bboxes_members,
    _extract_above_regions,
    _extract_exact_above_regions,
    _resolve_above_dirty_mode,
)
from src.indicators.rotated_paste import rotated_paste

CANVAS_W, CANVAS_H = 640, 360


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _widget(w: int, h: int, content_box, dirty_zero: bool = False) -> Image.Image:
    """RGBA overlay of size (w, h) with opaque content in *content_box* and
    transparent padding.  With *dirty_zero*, adds A==0 / RGB!=0 pixels in the
    padding (the alpha-tight bbox must ignore them exactly like SCAN)."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = content_box
    d.rectangle((x0, y0, x1, y1), fill=(200, 100, 50, 255))
    if dirty_zero:
        img.putpixel((0, 0), (255, 0, 0, 0))
        img.putpixel((w - 1, h - 1), (0, 255, 0, 0))
    return img


def _build_canvas(widgets: list[tuple[Image.Image, int, int, int, str]]):
    """widgets: (overlay, cx, cy, rotation, key). Returns
    (canvas, declared_bboxes, tight_bboxes)."""
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    bboxes = {}
    tight = {}
    for overlay, cx, cy, rotation, key in widgets:
        w, h = overlay.size
        bw, bh = (h, w) if rotation in (90, 270) else (w, h)
        bboxes[key] = (int(cx - bw // 2), int(cy - bh // 2), bw, bh)
        rotated_paste(
            canvas, overlay, cx, cy, rotation,
            cache_key=key, tight_bboxes=tight, tight_key=key,
        )
    return canvas, bboxes, tight


def _scan(canvas, bboxes):
    clusters = _cluster_above_bboxes(bboxes, CANVAS_W, CANVAS_H, pad=16, merge_dist=32)
    return _extract_above_regions(canvas, clusters, "SCAN")


def _exact(canvas, bboxes, tight, canvas_w=CANVAS_W, canvas_h=CANVAS_H):
    clusters = _cluster_above_bboxes_members(
        bboxes, canvas_w, canvas_h, pad=16, merge_dist=32
    )
    return _extract_exact_above_regions(
        canvas, clusters, tight, canvas_w, canvas_h
    )


def _assert_region_parity(scan, exact) -> None:
    sr, ss = scan
    er, es = exact
    assert [(r[0], r[1], r[2], r[3]) for r in sr] == [
        (r[0], r[1], r[2], r[3]) for r in er
    ], "region geometry differs between SCAN and EXACT"
    assert [r[4] for r in sr] == [r[4] for r in er], "region RGBA bytes differ"
    assert ss["uploaded_pixels"] == es["uploaded_pixels"]
    assert ss["uploaded_bytes"] == es["uploaded_bytes"]


# ---------------------------------------------------------------------------
# Cluster membership
# ---------------------------------------------------------------------------


def test_cluster_members_match_plain_clustering() -> None:
    cases = [
        {"a": (10, 10, 40, 20), "b": (600, 300, 30, 30)},        # far apart -> 2
        {"a": (10, 10, 40, 20), "b": (30, 15, 30, 30)},          # overlapping -> 1
        {"a": (10, 10, 40, 20), "b": (70, 26, 30, 30)},          # near -> merge
        {"a": (10, 10, 40, 20)},                                 # single
        {},                                                      # empty
    ]
    for bboxes in cases:
        plain = _cluster_above_bboxes(bboxes, CANVAS_W, CANVAS_H, pad=16, merge_dist=32)
        members = _cluster_above_bboxes_members(bboxes, CANVAS_W, CANVAS_H, pad=16, merge_dist=32)
        assert [r for r, _ in members] == plain, f"rect mismatch for {bboxes}"
        # Every member key must be present in exactly one cluster.
        all_keys = [k for _, ms in members for k in ms]
        assert sorted(all_keys) == sorted(k for k in bboxes if bboxes[k] and bboxes[k][2] > 0 and bboxes[k][3] > 0)


# ---------------------------------------------------------------------------
# SCAN vs EXACT region parity
# ---------------------------------------------------------------------------


def test_exact_parity_rotation_0() -> None:
    ov = _widget(120, 40, (10, 5, 110, 35))
    canvas, bboxes, tight = _build_canvas([(ov, 200, 100, 0, "w0")])
    _assert_region_parity(_scan(canvas, bboxes), _exact(canvas, bboxes, tight))


def test_exact_parity_rotations_90_180_270() -> None:
    for rot in (90, 180, 270):
        ov = _widget(120, 40, (10, 5, 110, 35))
        canvas, bboxes, tight = _build_canvas([(ov, 200, 100, rot, "w0")])
        _assert_region_parity(_scan(canvas, bboxes), _exact(canvas, bboxes, tight))


def test_exact_parity_multiple_widgets_merged() -> None:
    # Two widgets within merge distance -> one cluster; EXACT union must equal
    # SCAN's cluster alpha bbox.
    canvas, bboxes, tight = _build_canvas([
        (_widget(80, 30, (5, 4, 75, 26)), 120, 90, 0, "a"),
        (_widget(80, 30, (5, 4, 75, 26)), 240, 110, 0, "b"),
    ])
    clusters = _cluster_above_bboxes(bboxes, CANVAS_W, CANVAS_H, pad=16, merge_dist=32)
    assert len(clusters) == 1
    _assert_region_parity(_scan(canvas, bboxes), _exact(canvas, bboxes, tight))


def test_exact_parity_overlap() -> None:
    canvas, bboxes, tight = _build_canvas([
        (_widget(100, 100, (0, 0, 99, 99)), 150, 120, 0, "a"),
        (_widget(100, 100, (0, 0, 99, 99)), 200, 170, 0, "b"),
    ])
    _assert_region_parity(_scan(canvas, bboxes), _exact(canvas, bboxes, tight))


def test_exact_alpha_tight_ignores_a0_rgb_nonzero() -> None:
    # A=0/RGB!=0 pixels in the padding must be excluded, exactly like
    # getchannel("A").getbbox() used by SCAN.
    ov = _widget(120, 40, (10, 5, 110, 35), dirty_zero=True)
    canvas, bboxes, tight = _build_canvas([(ov, 200, 100, 0, "w0")])
    # Confirm the tight bbox excludes the dirty-zero corner pixels: the paste
    # origin is (140, 80) and the content rect (10,5,110,35) is inclusive, so
    # the alpha bbox is (150, 85, 101, 31) — corners (0,0)/(119,39) excluded.
    assert tight["w0"]["rect"] == (150, 85, 101, 31), tight["w0"]
    _assert_region_parity(_scan(canvas, bboxes), _exact(canvas, bboxes, tight))


def test_exact_none_transition_no_region() -> None:
    # Fully transparent widget -> SCAN produces no region, EXACT too.
    ov = _widget(120, 40, (10, 5, 110, 35))
    transparent = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
    canvas, bboxes, tight = _build_canvas([(transparent, 200, 100, 0, "w0")])
    sr, ss = _scan(canvas, bboxes)
    er, es = _exact(canvas, bboxes, tight)
    assert sr == [] and er == []
    assert ss["uploaded_pixels"] == 0 and es["uploaded_pixels"] == 0


def test_exact_dynamic_text_width_parity() -> None:
    # Text-like widgets whose tight bbox grows/shrinks must track SCAN.
    for width in (40, 90, 130, 60):
        ov = _widget(width, 30, (0, 0, width - 1, 29))
        canvas, bboxes, tight = _build_canvas([(ov, 300, 100, 0, "txt")])
        _assert_region_parity(_scan(canvas, bboxes), _exact(canvas, bboxes, tight))


def test_exact_moving_marker_parity() -> None:
    # Widget moves A -> B; each frame's EXACT region must equal SCAN.
    for cx in (60, 160, 260, 480):
        ov = _widget(60, 24, (0, 0, 59, 23))
        canvas, bboxes, tight = _build_canvas([(ov, cx, 100, 0, "marker")])
        _assert_region_parity(_scan(canvas, bboxes), _exact(canvas, bboxes, tight))


# ---------------------------------------------------------------------------
# Fallback rules
# ---------------------------------------------------------------------------


def test_exact_fallback_missing_tight_bbox() -> None:
    ov = _widget(80, 30, (5, 4, 75, 26))
    canvas, bboxes, tight = _build_canvas([(ov, 120, 90, 0, "a")])
    # Remove the tight bbox -> the cluster must fall back to SCAN.
    del tight["a"]
    er, es = _exact(canvas, bboxes, tight)
    sr, ss = _scan(canvas, bboxes)
    assert es["exact_clusters"] == 0
    assert es["scan_fallback_clusters"] == 1
    assert es["fallback_reason"].get("missing_tight_bbox") == 1
    # Fallback output must equal SCAN byte-for-byte.
    _assert_region_parity(_scan(canvas, bboxes), (er, es))


def test_exact_fallback_clipped_widget() -> None:
    # A widget whose paste rect extends past the canvas edge is "clipped" and
    # must fall back to SCAN for its cluster.
    ov = _widget(200, 60, (0, 0, 199, 59))
    canvas, bboxes, tight = _build_canvas([(ov, CANVAS_W - 10, 100, 0, "edge")])
    assert tight["edge"]["clipped"] is True
    er, es = _exact(canvas, bboxes, tight)
    assert es["exact_clusters"] == 0
    assert es["scan_fallback_clusters"] == 1
    assert es["fallback_reason"].get("clipped_widget") == 1
    _assert_region_parity(_scan(canvas, bboxes), (er, es))


def test_exact_fallback_invalid_rect() -> None:
    # A tight bbox with invalid geometry (fully outside canvas) -> fallback.
    ov = _widget(80, 30, (5, 4, 75, 26))
    canvas, bboxes, tight = _build_canvas([(ov, 120, 90, 0, "a")])
    tight["a"] = {"rect": (10000, 10000, 40, 20), "clipped": False}
    er, es = _exact(canvas, bboxes, tight)
    assert es["scan_fallback_clusters"] == 1
    assert es["fallback_reason"].get("invalid_exact_rect") == 1
    _assert_region_parity(_scan(canvas, bboxes), (er, es))


def test_exact_mixed_transparent_and_visible_members() -> None:
    # One visible + one fully-transparent member in one cluster: the union
    # uses only the visible tight bbox (matches SCAN).
    ov_a = _widget(80, 30, (5, 4, 75, 26))
    ov_b = Image.new("RGBA", (80, 30), (0, 0, 0, 0))
    canvas, bboxes, tight = _build_canvas([
        (ov_a, 120, 90, 0, "a"),
        (ov_b, 240, 110, 0, "b"),
    ])
    _assert_region_parity(_scan(canvas, bboxes), _exact(canvas, bboxes, tight))


# ---------------------------------------------------------------------------
# Mode parsing
# ---------------------------------------------------------------------------


def test_exact_mode_accepted_and_unknown_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("AMD_ABOVE_DIRTY_MODE", "EXACT")
    assert _resolve_above_dirty_mode() == "EXACT"
    monkeypatch.setenv("AMD_ABOVE_DIRTY_MODE", "SCAN")
    assert _resolve_above_dirty_mode() == "SCAN"
    monkeypatch.setenv("AMD_ABOVE_DIRTY_MODE", "CANDIDATE")
    assert _resolve_above_dirty_mode() == "CANDIDATE"
    monkeypatch.setenv("AMD_ABOVE_DIRTY_MODE", "XYZ")
    assert _resolve_above_dirty_mode() == "SCAN"
