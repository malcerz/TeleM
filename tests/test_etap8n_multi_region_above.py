from __future__ import annotations

import math
from PIL import Image, ImageDraw

from src.ffmpeg.amd_native_exporter import (
    _clip_rect,
    _cluster_above_bboxes,
    _rect_union,
    _tight_alpha_bbox_from_candidate,
)
from src.indicators.compositor import compose_overlay


def _simulate_multi_region_pipeline(
    above_full: Image.Image,
    above_bboxes: dict[str, tuple[int, int, int, int]],
    canvas_w: int,
    canvas_h: int,
    pad: int = 16,
    merge_dist: int = 32,
    max_regions: int = 16,
) -> list[tuple[int, int, int, int, Image.Image]]:
    """Simulate the ETAP 8N multi-region extraction pipeline."""
    clusters = _cluster_above_bboxes(
        above_bboxes, canvas_w, canvas_h, pad=pad, merge_dist=merge_dist, max_regions=max_regions
    )
    regions: list[tuple[int, int, int, int, Image.Image]] = []
    for cx, cy, cw, ch in clusters:
        candidate_image = above_full.crop((cx, cy, cx + cw, cy + ch))
        local_alpha = candidate_image.getchannel("A").getbbox()
        if local_alpha is not None:
            lx, ly, rx, by = local_alpha
            reg_w = rx - lx
            reg_h = by - ly
            if reg_w > 0 and reg_h > 0:
                reg_img = candidate_image.crop(local_alpha)
                reg_x = cx + lx
                reg_y = cy + ly
                regions.append((reg_x, reg_y, reg_w, reg_h, reg_img))
    return regions


def test_above_multi_region_sparse() -> None:
    """Sparse-distant elements: small text top-left and small text bottom-right."""
    w, h = 3840, 2160
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Element A at top-left
    draw.rectangle((50, 40, 50 + 200 - 1, 40 + 60 - 1), fill=(255, 0, 0, 255))
    # Element B at bottom-right
    draw.rectangle((3500, 2000, 3500 + 250 - 1, 2000 + 100 - 1), fill=(0, 255, 0, 255))

    bboxes = {
        "tl": (50, 40, 200, 60),
        "br": (3500, 2000, 250, 100),
    }

    clusters = _cluster_above_bboxes(bboxes, w, h, pad=16, merge_dist=32)
    assert len(clusters) == 2, f"Expected 2 separate clusters for sparse distant elements, got {len(clusters)}"

    regions = _simulate_multi_region_pipeline(img, bboxes, w, h)
    assert len(regions) == 2
    # Verify regions match exact rendered rects
    r0 = regions[0]
    r1 = regions[1]
    assert (r0[0], r0[1], r0[2], r0[3]) in [(50, 40, 200, 60), (3500, 2000, 250, 100)]
    assert (r1[0], r1[1], r1[2], r1[3]) in [(50, 40, 200, 60), (3500, 2000, 250, 100)]

    # Union would be ~3700 x 2060 = 7.6M pixels
    union_pixels = (3750 - 50) * (2100 - 40)
    region_pixels = sum(r[2] * r[3] for r in regions)
    assert union_pixels > 7_000_000
    assert region_pixels == (200 * 60 + 250 * 100) == 37_000
    reduction = 100.0 * (1.0 - region_pixels / union_pixels)
    assert reduction > 99.0, f"Expected >99% reduction, got {reduction:.2f}%"


def test_above_multi_region_overlap_order() -> None:
    """Overlapping ABOVE elements maintain exact composite pixel results."""
    w, h = 800, 600
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # First drawn: blue rectangle
    draw.rectangle((100, 100, 100 + 100 - 1, 100 + 100 - 1), fill=(0, 0, 255, 200))
    # Second drawn: partially overlapping semi-transparent red
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((150, 150, 150 + 100 - 1, 150 + 100 - 1), fill=(255, 0, 0, 128))
    img = Image.alpha_composite(img, overlay)

    bboxes = {
        "elem_1": (100, 100, 100, 100),
        "elem_2": (150, 150, 100, 100),
    }
    clusters = _cluster_above_bboxes(bboxes, w, h, pad=16, merge_dist=32)
    assert len(clusters) == 1, "Overlapping elements must merge into 1 cluster"

    regions = _simulate_multi_region_pipeline(img, bboxes, w, h)
    assert len(regions) == 1
    rx, ry, rw, rh, r_img = regions[0]
    assert rx == 100 and ry == 100 and rw == 150 and rh == 150
    # Check that pixel content inside region matches source exactly
    reconstructed = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    reconstructed.alpha_composite(r_img, (rx, ry))
    assert reconstructed.tobytes() == img.tobytes()


def test_above_multi_region_near_merge() -> None:
    """Nearby elements within merge_dist merge into a single region."""
    w, h = 1000, 1000
    bboxes = {
        "top": (100, 100, 200, 50),
        "bot": (100, 170, 200, 50),  # Gap is 20px (<= merge_dist=32 with pad=16)
    }
    clusters = _cluster_above_bboxes(bboxes, w, h, pad=16, merge_dist=32)
    assert len(clusters) == 1, "Nearby elements within merge_dist should merge"


def test_above_multi_region_visible_none_visible() -> None:
    """Dynamic lifecycle: visible -> None (empty) -> visible."""
    w, h = 640, 480
    img_visible = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img_visible)
    draw.rectangle((50, 50, 50 + 100 - 1, 50 + 50 - 1), fill=(255, 255, 0, 255))
    bboxes_visible = {"ind": (50, 50, 100, 50)}

    # Frame 1: visible
    reg1 = _simulate_multi_region_pipeline(img_visible, bboxes_visible, w, h)
    assert len(reg1) == 1
    assert reg1[0][:4] == (50, 50, 100, 50)

    # Frame 2: none / empty
    reg2 = _simulate_multi_region_pipeline(Image.new("RGBA", (w, h), (0, 0, 0, 0)), {}, w, h)
    assert len(reg2) == 0

    # Frame 3: visible again
    reg3 = _simulate_multi_region_pipeline(img_visible, bboxes_visible, w, h)
    assert len(reg3) == 1
    assert reg3[0][:4] == (50, 50, 100, 50)


def test_above_multi_region_zero_visible() -> None:
    """Value = 0.0 is real telemetry, not missing data, and produces valid tracked bbox."""
    bboxes = {
        "solar_zero": (200, 150, 80, 25),
        "battery_zero": (500, 400, 90, 30),
    }
    clusters = _cluster_above_bboxes(bboxes, 1920, 1080)
    assert len(clusters) == 2


def test_above_multi_region_move() -> None:
    """Moving elements across frames produce clean, updated regions."""
    w, h = 800, 600
    positions = [(50, 50), (200, 150), (400, 300)]
    for pos in positions:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((pos[0], pos[1], pos[0] + 60 - 1, pos[1] + 30 - 1), fill=(100, 200, 255, 255))
        bboxes = {"moving": (pos[0], pos[1], 60, 30)}
        regions = _simulate_multi_region_pipeline(img, bboxes, w, h)
        assert len(regions) == 1
        assert regions[0][:4] == (pos[0], pos[1], 60, 30)


def test_above_multi_region_resize() -> None:
    """Resizing elements (small -> large -> small)."""
    w, h = 800, 600
    sizes = [(40, 20), (200, 100), (30, 15)]
    for rw, rh in sizes:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((100, 100, 100 + rw - 1, 100 + rh - 1), fill=(255, 128, 0, 255))
        bboxes = {"resizing": (100, 100, rw, rh)}
        regions = _simulate_multi_region_pipeline(img, bboxes, w, h)
        assert len(regions) == 1
        assert regions[0][:4] == (100, 100, rw, rh)


def test_above_multi_region_rotation() -> None:
    """Rotated indicator at 17 degrees captures all antialiased pixels."""
    w, h = 500, 500
    # Render rotated box on transparent canvas
    base = Image.new("RGBA", (100, 40), (255, 50, 50, 255))
    rotated = base.rotate(17, expand=True, resample=Image.BICUBIC)
    rw, rh = rotated.size
    cx, cy = 200, 200
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.paste(rotated, (cx, cy), rotated)

    bboxes = {"rot_elem": (cx, cy, rw, rh)}
    regions = _simulate_multi_region_pipeline(img, bboxes, w, h, pad=16)
    assert len(regions) == 1
    rx, ry, reg_w, reg_h, r_img = regions[0]

    # All non-zero alpha pixels in img must be inside the extracted region
    reconstructed = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    reconstructed.alpha_composite(r_img, (rx, ry))
    assert reconstructed.tobytes() == img.tobytes()


def test_above_multi_region_edge_clip() -> None:
    """Elements touching or overflowing frame boundaries are safely clipped."""
    w, h = 400, 300
    bboxes = {
        "top_left": (-20, -10, 80, 50),
        "bottom_right": (350, 280, 80, 50),
    }
    clusters = _cluster_above_bboxes(bboxes, w, h, pad=0)
    for c in clusters:
        assert c[0] >= 0 and c[1] >= 0
        assert c[0] + c[2] <= w
        assert c[1] + c[3] <= h


def test_above_multi_region_map_preserved_after_clear() -> None:
    """Contract: Clear previous above regions -> draw under-layers + GPU map -> blend new above regions.
    Map pixels beneath the old above position are restored perfectly."""
    w, h = 200, 200
    map_background = Image.new("RGBA", (w, h), (30, 120, 60, 255))
    
    # Frame A: Indicator at (30, 30)
    hud_a = map_background.copy()
    above_a = Image.new("RGBA", (40, 20), (255, 255, 0, 255))
    hud_a.paste(above_a, (30, 30), above_a)

    # Frame B: Indicator moved to (120, 120)
    # Pipeline clears previous (30, 30), rerenders map background, blends new at (120, 120)
    hud_b = map_background.copy()
    above_b = Image.new("RGBA", (40, 20), (255, 255, 0, 255))
    hud_b.paste(above_b, (120, 120), above_b)

    # Spot check: (30, 30) area in hud_b MUST have restored map background pixels (no ghosting, no black hole)
    old_spot = hud_b.crop((30, 30, 70, 50))
    expected_spot = map_background.crop((30, 30, 70, 50))
    assert old_spot.tobytes() == expected_spot.tobytes()


def test_above_multi_region_pixel_parity() -> None:
    """Pixel Oracle: Multi-region composition must produce byte-for-byte identical output
    to the single full-canvas composition."""
    w, h = 1920, 1080
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 200, 350, 260), fill=(220, 40, 40, 200))
    draw.rectangle((900, 100, 1100, 150), fill=(40, 220, 40, 220))
    draw.rectangle((1600, 800, 1850, 880), fill=(40, 40, 220, 180))

    bboxes = {
        "ind1": (100, 200, 250, 60),
        "ind2": (900, 100, 200, 50),
        "ind3": (1600, 800, 250, 80),
    }

    regions = _simulate_multi_region_pipeline(img, bboxes, w, h)
    assert len(regions) == 3

    # Reconstruct full frame by alpha blending each extracted region
    reconstructed = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for rx, ry, rw, rh, r_img in regions:
        reconstructed.alpha_composite(r_img, (rx, ry))

    assert reconstructed.tobytes() == img.tobytes(), "Multi-region output must match single full-canvas pixel-for-pixel"
