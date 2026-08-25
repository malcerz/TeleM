"""ETAP 5E.5: transparent-ROI plain paste safety tests."""

from PIL import Image, ImageChops
import numpy as np

from src.indicators.rotated_paste import rotated_paste


def _diff(left, right):
    diff = np.abs(np.asarray(left, dtype=np.int16) - np.asarray(right, dtype=np.int16))
    return (bool(np.any(diff != 0)), int(diff.max()))


def _ready_overlay():
    image = Image.new("RGBA", (32, 24), (0, 0, 0, 0))
    image.putpixel((8, 8), (220, 30, 80, 128))
    image.putpixel((20, 15), (40, 180, 240, 255))
    return image


def _composite_reference(base, overlay, xy):
    result = base.copy()
    result.alpha_composite(overlay, xy)
    return result


def test_empty_transparent_roi_plain_paste_is_pixel_exact_for_ready_rgba():
    overlay = _ready_overlay()
    optimized = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    reference = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    rotated_paste(
        optimized, overlay, 40, 30, 0, prior_bboxes=[],
        cache_key="test_etap5e5_empty", destination_proven_empty=True,
    )
    reference = _composite_reference(reference, overlay, (24, 18))
    assert _diff(optimized, reference) == (False, 0)


def test_rectangle_overlap_forces_alpha_composite_fallback():
    overlay = _ready_overlay()
    optimized = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    reference = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    # Opaque content sits where the source is transparent.  Plain paste would
    # erase it, so this catches an unsafe overlap shortcut.
    optimized.putpixel((24, 18), (10, 20, 30, 255))
    reference.putpixel((24, 18), (10, 20, 30, 255))
    rotated_paste(
        optimized, overlay, 40, 30, 0,
        prior_bboxes=[(20, 14, 8, 8)],
        cache_key="test_etap5e5_overlap", destination_proven_empty=True,
    )
    reference = _composite_reference(reference, overlay, (24, 18))
    assert _diff(optimized, reference) == (False, 0)


def test_dirty_transparent_source_does_not_use_plain_paste():
    overlay = _ready_overlay()
    # RGB under alpha=0 is semantically invisible but is not byte-safe for a
    # plain paste into a transparent destination.
    overlay.putpixel((3, 3), (9, 8, 7, 0))
    optimized = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    reference = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    rotated_paste(
        optimized, overlay, 40, 30, 0, prior_bboxes=[],
        cache_key="test_etap5e5_dirty", destination_proven_empty=True,
    )
    reference = _composite_reference(reference, overlay, (24, 18))
    assert _diff(optimized, reference) == (False, 0)


def test_alpha_only_nonoverlap_is_still_conservative_rectangle_overlap():
    overlay = _ready_overlay()
    optimized = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    reference = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    # The previous widget rectangle overlaps the transparent part of the
    # source, even though it contributes no visible pixels there.  Geometry
    # alone cannot prove the destination empty, so the fast path must fallback.
    optimized.putpixel((24, 18), (10, 20, 30, 255))
    reference.putpixel((24, 18), (10, 20, 30, 255))
    rotated_paste(
        optimized, overlay, 40, 30, 0,
        prior_bboxes=[(24, 18, 1, 1)],
        cache_key="test_etap5e5_alpha_only_overlap",
        destination_proven_empty=True,
    )
    reference = _composite_reference(reference, overlay, (24, 18))
    assert _diff(optimized, reference) == (False, 0)


def test_transparent_roi_fast_path_preserves_rotation_dimensions():
    overlay = _ready_overlay()
    for rotation in (0, 90, 180, 270):
        if rotation in (90, 270):
            expected_source = overlay.transpose(Image.Transpose.ROTATE_90 if rotation == 90 else Image.Transpose.ROTATE_270)
        else:
            expected_source = overlay.transpose(Image.Transpose.ROTATE_180) if rotation == 180 else overlay
        optimized = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
        reference = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
        rotated_paste(
            optimized, overlay, 40, 40, rotation, prior_bboxes=[],
            cache_key=f"test_etap5e5_rotation_{rotation}",
            destination_proven_empty=True,
        )
        x = 40 - expected_source.width // 2
        y = 40 - expected_source.height // 2
        reference = _composite_reference(reference, expected_source, (x, y))
        assert _diff(optimized, reference) == (False, 0), rotation
