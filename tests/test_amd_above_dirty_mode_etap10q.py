"""ETAP 10Q: AMD ABOVE dirty-region mode — SCAN (legacy) vs CANDIDATE.

Targeted tests for the ``AMD_ABOVE_DIRTY_MODE`` runtime contract in
``src/ffmpeg/amd_native_exporter.py``:

- mode parsing + unknown / reserved-EXACT fail-safe fallback to SCAN,
- SCAN path preserved (byte-identical legacy extraction),
- CANDIDATE skips the alpha scan and the tight final crop,
- CPU-level pixel parity proof (SCAN and CANDIDATE reconstruct the same final
  overlay; candidate transparent padding has alpha == 0),
- None/value transitions (no stale content),
- overlapping widgets,
- rotation = 90,
- map-under-ABOVE (transparent padding must not change the layer below).

These are pure CPU tests of the deterministic pre-encode extraction point.
They prove that the *content* uploaded by CANDIDATE is a strict superset of
SCAN's with only fully-transparent padding.

NOTE (ETAP 10Q final verdict): CPU content parity is NOT sufficient for GPU
final parity.  The CANDIDATE mode FAILED the end-to-end A/B: the larger
uploaded rect becomes ``ClearPreviousAboveMap``'s erase region, which wipes
map pixels under the transparent padding that the map redraw (bounded by
``map_dst``) does not restore -> the final raster differs from SCAN.  SCAN
remains the production default; CANDIDATE is env-opt-in diagnostic only.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from src.ffmpeg.amd_native_exporter import (
    _ABOVE_DIRTY_MODE_DEFAULT,
    _cluster_above_bboxes,
    _extract_above_regions,
    _resolve_above_dirty_mode,
)

CANVAS_W = 640
CANVAS_H = 360


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _draw_widgets(
    widgets: list[dict],
    w: int = CANVAS_W,
    h: int = CANVAS_H,
) -> tuple[Image.Image, dict[str, tuple[int, int, int, int]]]:
    """Build a transparent ABOVE canvas with the given widgets.

    Each widget dict: ``{x, y, w, h, color, rotation, pad}``.  ``pad`` insets
    the drawn content inside the declared raster to simulate transparent
    padding (e.g. rotated corners).  For ``rotation`` 90/270 the declared
    raster dims are swapped (exactly like the compositor: ``bw, bh =
    res.height, res.width``) and the content is a vertical strip.
    """
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bboxes: dict[str, tuple[int, int, int, int]] = {}
    for i, wd in enumerate(widgets):
        x, y, ww, hh = wd["x"], wd["y"], wd["w"], wd["h"]
        color = wd.get("color", (255, 255, 255, 255))
        rotation = wd.get("rotation", 0) % 360
        pad = int(wd.get("pad", 0))
        if rotation in (90, 270):
            rw, rh = hh, ww  # declared raster dims after rotation (swapped)
            draw.rectangle(
                (x + pad, y + pad, x + rw - 1 - pad, y + rh - 1 - pad),
                fill=color,
            )
            bboxes[f"w{i}"] = (x, y, rw, rh)
        else:
            draw.rectangle(
                (x + pad, y + pad, x + ww - 1 - pad, y + hh - 1 - pad),
                fill=color,
            )
            bboxes[f"w{i}"] = (x, y, ww, hh)
    return img, bboxes


def _extract(img: Image.Image, bboxes: dict, mode: str):
    clusters = _cluster_above_bboxes(bboxes, CANVAS_W, CANVAS_H, pad=16, merge_dist=32)
    return _extract_above_regions(img, clusters, mode)


def _region_image(w: int, h: int, r_bytes: bytes) -> Image.Image:
    return Image.frombytes("RGBA", (w, h), r_bytes)


def _reconstruct(size, region) -> Image.Image:
    rx, ry, rw, rh, r_bytes = region
    recon = Image.new("RGBA", size, (0, 0, 0, 0))
    recon.alpha_composite(_region_image(rw, rh, r_bytes), (rx, ry))
    return recon


def _content_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    b = img.getchannel("A").getbbox()
    if b is None:
        return None
    return b[0], b[1], b[2] - b[0], b[3] - b[1]


# ---------------------------------------------------------------------------
# Mode parsing / fail-safe
# ---------------------------------------------------------------------------


def test_default_mode_is_exact(monkeypatch) -> None:
    # ETAP 10R flipped the production default to EXACT after region parity,
    # final GPU parity, ghosting, map-underneath and frame accounting passed.
    monkeypatch.delenv("AMD_ABOVE_DIRTY_MODE", raising=False)
    assert _ABOVE_DIRTY_MODE_DEFAULT == "EXACT"
    assert _resolve_above_dirty_mode() == "EXACT"


def test_scan_and_candidate_modes_accepted(monkeypatch) -> None:
    monkeypatch.setenv("AMD_ABOVE_DIRTY_MODE", "scan")
    assert _resolve_above_dirty_mode() == "SCAN"
    monkeypatch.setenv("AMD_ABOVE_DIRTY_MODE", "Candidate")
    assert _resolve_above_dirty_mode() == "CANDIDATE"


def test_unknown_mode_falls_back_to_scan_with_warning(monkeypatch, capsys) -> None:
    monkeypatch.setenv("AMD_ABOVE_DIRTY_MODE", "XYZ")
    assert _resolve_above_dirty_mode() == "SCAN"
    out = capsys.readouterr().out
    assert "unknown AMD_ABOVE_DIRTY_MODE" in out


def test_exact_mode_accepted() -> None:
    # ETAP 10R implements EXACT; it is a first-class mode (no fallback).
    import os
    os.environ["AMD_ABOVE_DIRTY_MODE"] = "EXACT"
    try:
        assert _resolve_above_dirty_mode() == "EXACT"
    finally:
        os.environ.pop("AMD_ABOVE_DIRTY_MODE", None)


# ---------------------------------------------------------------------------
# SCAN preserved + CANDIDATE skips scan
# ---------------------------------------------------------------------------


def test_scan_path_matches_legacy_inline_logic() -> None:
    img, bboxes = _draw_widgets([
        {"x": 40, "y": 30, "w": 90, "h": 40, "color": (255, 0, 0, 255)},
        {"x": 300, "y": 120, "w": 120, "h": 60, "color": (0, 255, 0, 200)},
    ])
    clusters = _cluster_above_bboxes(bboxes, CANVAS_W, CANVAS_H, pad=16, merge_dist=32)
    regions, stats = _extract_above_regions(img, clusters, "SCAN")

    # Legacy inline reference (pre-10Q production logic).
    ref_regions = []
    for cx, cy, cw, ch in clusters:
        candidate_image = img.crop((cx, cy, cx + cw, cy + ch))
        local_alpha_bbox = candidate_image.getchannel("A").getbbox()
        if local_alpha_bbox is not None:
            lx, ly, rx, by = local_alpha_bbox
            reg_w, reg_h = rx - lx, by - ly
            if reg_w > 0 and reg_h > 0:
                reg_img = candidate_image.crop(local_alpha_bbox)
                ref_regions.append(
                    (cx + lx, cy + ly, reg_w, reg_h, reg_img.tobytes("raw", "RGBA"))
                )

    assert [(r[0], r[1], r[2], r[3]) for r in regions] == [
        (r[0], r[1], r[2], r[3]) for r in ref_regions
    ]
    assert [r[4] for r in regions] == [r[4] for r in ref_regions]
    assert stats["scanned_pixels"] > 0
    assert stats["uploaded_pixels"] < stats["candidate_pixels"]


def test_candidate_skips_alpha_scan_and_final_crop() -> None:
    img, bboxes = _draw_widgets([
        {"x": 40, "y": 30, "w": 90, "h": 40, "color": (255, 0, 0, 255)},
        {"x": 300, "y": 120, "w": 120, "h": 60, "color": (0, 255, 0, 200)},
    ])
    clusters = _cluster_above_bboxes(bboxes, CANVAS_W, CANVAS_H, pad=16, merge_dist=32)
    regions, stats = _extract_above_regions(img, clusters, "CANDIDATE")

    assert stats["scanned_pixels"] == 0
    assert stats["candidate_pixels"] == stats["uploaded_pixels"]
    assert stats["uploaded_bytes"] == stats["candidate_pixels"] * 4
    # Each CANDIDATE region uploads exactly its candidate cluster rectangle.
    assert len(regions) == len(clusters)
    for (rx, ry, rw, rh, r_bytes), (cx, cy, cw, ch) in zip(regions, clusters):
        assert (rx, ry, rw, rh) == (cx, cy, cw, ch)
        assert len(r_bytes) == rw * rh * 4
    # CANDIDATE must never run the alpha scan / tight crop timers.
    assert stats["alpha_scan_ms"] == 0.0
    assert stats["final_crop_ms"] == 0.0


# ---------------------------------------------------------------------------
# Pixel parity (SCAN vs CANDIDATE reconstruct the same final overlay)
# ---------------------------------------------------------------------------


def test_pixel_parity_scalar_widgets() -> None:
    img, bboxes = _draw_widgets([
        {"x": 40, "y": 30, "w": 90, "h": 40, "color": (255, 0, 0, 255)},
        {"x": 300, "y": 120, "w": 120, "h": 60, "color": (0, 255, 0, 200)},
        {"x": 500, "y": 250, "w": 70, "h": 50, "color": (0, 0, 255, 128)},
    ])
    scan_regions, scan_stats = _extract(img, bboxes, "SCAN")
    cand_regions, cand_stats = _extract(img, bboxes, "CANDIDATE")

    assert len(scan_regions) >= 1 and len(cand_regions) >= 1
    # Both reconstructions equal the source overlay (final raster identical).
    for regions in (scan_regions, cand_regions):
        recon = Image.new("RGBA", img.size, (0, 0, 0, 0))
        for rx, ry, rw, rh, r_bytes in regions:
            recon.alpha_composite(_region_image(rw, rh, r_bytes), (rx, ry))
        assert recon.tobytes() == img.tobytes()

    # CANDIDATE region union is a superset of SCAN content (covers all widgets).
    scan_bbox = _content_bbox(img)
    assert scan_bbox is not None
    sx, sy, sw, sh = scan_bbox
    un_x0 = min(r[0] for r in cand_regions)
    un_y0 = min(r[1] for r in cand_regions)
    un_x1 = max(r[0] + r[2] for r in cand_regions)
    un_y1 = max(r[1] + r[3] for r in cand_regions)
    assert un_x0 <= sx and un_y0 <= sy
    assert un_x1 >= sx + sw and un_y1 >= sy + sh

    # Transparent padding inside the candidate has alpha == 0 (no-op on GPU).
    for rx, ry, rw, rh, r_bytes in cand_regions:
        cand_img = _region_image(rw, rh, r_bytes)
        alpha = cand_img.getchannel("A")
        for yy in range(rh):
            for xx in range(rw):
                global_x = rx + xx
                global_y = ry + yy
                inside_content = (
                    sx <= global_x < sx + sw and sy <= global_y < sy + sh
                )
                if not inside_content and alpha.getpixel((xx, yy)) != 0:
                    raise AssertionError(
                        "CANDIDATE padding contains non-transparent pixels"
                    )


def test_pixel_parity_rotation_90() -> None:
    # Altitude-like widget: rotation = 90 -> declared raster dims swapped
    # (bw, bh = res.height, res.width), content inset leaving transparent
    # corners exactly like Pillow transpose.
    img, bboxes = _draw_widgets([
        {"x": 60, "y": 100, "w": 30, "h": 140, "rotation": 90, "pad": 3,
         "color": (0, 170, 255, 255)},
        {"x": 200, "y": 60, "w": 80, "h": 36, "color": (255, 255, 255, 255)},
    ])
    scan_regions, _ = _extract(img, bboxes, "SCAN")
    cand_regions, _ = _extract(img, bboxes, "CANDIDATE")

    for regions in (scan_regions, cand_regions):
        recon = Image.new("RGBA", img.size, (0, 0, 0, 0))
        for rx, ry, rw, rh, r_bytes in regions:
            recon.alpha_composite(_region_image(rw, rh, r_bytes), (rx, ry))
        assert recon.tobytes() == img.tobytes()

    # SCAN must trim the transparent corners (upload < candidate).
    _, scan_stats = _extract(img, bboxes, "SCAN")
    _, cand_stats = _extract(img, bboxes, "CANDIDATE")
    assert scan_stats["uploaded_pixels"] < cand_stats["uploaded_pixels"]


def test_pixel_parity_overlapping_widgets() -> None:
    img, bboxes = _draw_widgets([
        {"x": 100, "y": 100, "w": 100, "h": 100, "color": (0, 0, 255, 200)},
        {"x": 150, "y": 150, "w": 100, "h": 100, "color": (255, 0, 0, 128)},
    ])
    clusters = _cluster_above_bboxes(bboxes, CANVAS_W, CANVAS_H, pad=16, merge_dist=32)
    assert len(clusters) == 1, "Overlapping widgets must merge into one cluster"

    for mode in ("SCAN", "CANDIDATE"):
        regions, _ = _extract_above_regions(img, clusters, mode)
        recon = Image.new("RGBA", img.size, (0, 0, 0, 0))
        for rx, ry, rw, rh, r_bytes in regions:
            recon.alpha_composite(_region_image(rw, rh, r_bytes), (rx, ry))
        assert recon.tobytes() == img.tobytes()


# ---------------------------------------------------------------------------
# None / value transitions (no stale content)
# ---------------------------------------------------------------------------


def test_none_transition_value_to_none() -> None:
    # Frame N: widget visible; Frame N+1: widget gone (all transparent).
    img_n, bboxes_n = _draw_widgets([
        {"x": 40, "y": 30, "w": 90, "h": 40, "color": (255, 255, 255, 255)},
    ])
    img_none, bboxes_none = _draw_widgets([
        {"x": 40, "y": 30, "w": 90, "h": 40, "color": (0, 0, 0, 0)},
    ])

    # SCAN: no visible content -> no region uploaded (nothing to draw).
    scan_regions_none, scan_stats_none = _extract(img_none, bboxes_none, "SCAN")
    assert scan_regions_none == []
    assert scan_stats_none["uploaded_pixels"] == 0

    # CANDIDATE: still uploads the candidate region, but every byte is
    # transparent — the GPU blend is a no-op, so no stale content is drawn.
    cand_regions_none, cand_stats_none = _extract(img_none, bboxes_none, "CANDIDATE")
    assert cand_regions_none, "CANDIDATE uploads the candidate region"
    assert cand_stats_none["uploaded_pixels"] > 0
    for rx, ry, rw, rh, r_bytes in cand_regions_none:
        assert all(b == 0 for b in r_bytes), "CANDIDATE None frame must be transparent"

    # Ghosting precondition: both modes upload a region that covers the
    # previous frame's content bbox, so the GPU clear can erase it.
    prev_content = _content_bbox(img_n)
    assert prev_content is not None
    for regions in (scan_regions_none, cand_regions_none):
        for rx, ry, rw, rh, _ in regions:
            # Union coverage is enough for the next-frame clear.
            assert rx <= prev_content[0] and ry <= prev_content[1]
            assert rx + rw >= prev_content[0] + prev_content[2]
            assert ry + rh >= prev_content[1] + prev_content[3]


def test_uploaded_region_covers_content_both_modes() -> None:
    # Widget shrinks and widens across frames; the uploaded region must always
    # cover the visible content (the next-frame GPU clear erases it fully).
    sizes = [(30, 20), (90, 40), (50, 25), (120, 48)]
    for i, (ww, hh) in enumerate(sizes):
        img, bboxes = _draw_widgets([
            {"x": 80, "y": 90, "w": ww, "h": hh, "color": (255, 255, 255, 255)},
        ])
        content = _content_bbox(img)
        assert content is not None
        for mode in ("SCAN", "CANDIDATE"):
            regions, _ = _extract(img, bboxes, mode)
            assert regions, f"frame {i} mode {mode} must upload a region"
            rx, ry, rw, rh, _ = regions[0]
            assert rx <= content[0] and ry <= content[1]
            assert rx + rw >= content[0] + content[2]
            assert ry + rh >= content[1] + content[3]


# ---------------------------------------------------------------------------
# Map underneath ABOVE (transparent padding must not change the layer below)
# ---------------------------------------------------------------------------


def test_map_underneath_transparent_padding_preserved() -> None:
    img, bboxes = _draw_widgets([
        {"x": 200, "y": 120, "w": 120, "h": 90, "color": (255, 255, 255, 255)},
    ])
    cand_regions, _ = _extract(img, bboxes, "CANDIDATE")
    assert len(cand_regions) == 1
    rx, ry, rw, rh, r_bytes = cand_regions[0]

    # Simulated GPU map underneath: opaque background.
    bg = Image.new("RGBA", img.size, (40, 80, 120, 255))
    bg_after = bg.copy()
    bg_after.alpha_composite(_region_image(rw, rh, r_bytes), (rx, ry))

    # The candidate's transparent padding must leave the map unchanged.
    cand_img = _region_image(rw, rh, r_bytes)
    alpha = cand_img.getchannel("A")
    for yy in range(rh):
        for xx in range(rw):
            if alpha.getpixel((xx, yy)) == 0:
                assert bg_after.getpixel((rx + xx, ry + yy)) == bg.getpixel(
                    (rx + xx, ry + yy)
                ), "transparent ABOVE pixel changed the map underneath"
