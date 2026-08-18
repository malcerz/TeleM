from __future__ import annotations

from PIL import Image, ImageDraw

from src.ffmpeg.amd_native_exporter import (
    _rendered_bbox_union,
    _tight_alpha_bbox_from_candidate,
)
from src.indicators.compositor import compose_overlay


def test_none_and_zero_values_follow_rendered_bbox_contract() -> None:
    assert _rendered_bbox_union({}, 100, 80) is None
    # A zero-valued telemetry sample is rendered geometry, not missing data.
    assert _rendered_bbox_union({"zero_value": (10, 20, 8, 6)}, 100, 80, pad=0) == (
        10, 20, 8, 6
    )


def test_union_is_clipped_and_handles_multiple_above_elements() -> None:
    result = _rendered_bbox_union(
        {"left": (-20, 5, 30, 12), "right": (88, 70, 30, 20)},
        100,
        80,
        pad=0,
    )
    assert result == (0, 5, 100, 75)


def test_local_alpha_scan_reconstructs_exact_visible_pixels() -> None:
    image = Image.new("RGBA", (160, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((31, 24, 48, 38), fill=(255, 20, 30, 180))
    draw.ellipse((108, 65, 124, 82), fill=(20, 220, 40, 90))
    candidate = _rendered_bbox_union(
        {"a": (30, 23, 20, 17), "b": (107, 64, 19, 19)},
        160,
        100,
        pad=2,
    )
    final_bbox, scanned = _tight_alpha_bbox_from_candidate(image, candidate)
    assert candidate == (28, 21, 100, 64)
    assert final_bbox == (31, 24, 94, 59)
    assert scanned == 100 * 64

    old_bbox = image.getchannel("A").getbbox()
    old_crop = image.crop(old_bbox)
    assert old_bbox == (
        final_bbox[0], final_bbox[1],
        final_bbox[0] + final_bbox[2], final_bbox[1] + final_bbox[3],
    )
    new_crop = image.crop((
        final_bbox[0], final_bbox[1],
        final_bbox[0] + final_bbox[2], final_bbox[1] + final_bbox[3],
    ))
    reconstructed = Image.new("RGBA", image.size, (0, 0, 0, 0))
    reconstructed.alpha_composite(new_crop, final_bbox[:2])
    assert reconstructed.tobytes() == image.tobytes()
    assert old_crop.tobytes() == new_crop.tobytes()


def test_move_resize_and_empty_transition_have_no_stale_bbox() -> None:
    image = Image.new("RGBA", (120, 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cases = [
        {"text": (5, 8, 20, 10)},
        {"text": (70, 42, 35, 22)},
        {},
        {"text": (8, 10, 12, 8)},
    ]
    boxes = [_rendered_bbox_union(case, 120, 80, pad=4) for case in cases]
    assert boxes[0] is not None
    assert boxes[1] is not None and boxes[1] != boxes[0]
    assert boxes[2] is None
    assert boxes[3] is not None
    draw.rectangle((8, 10, 19, 17), fill=(255, 255, 255, 128))
    final_bbox, _ = _tight_alpha_bbox_from_candidate(image, boxes[3])
    assert final_bbox == (8, 10, 12, 8)


def test_partial_alpha_and_frame_edges_are_preserved() -> None:
    image = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
    px = image.load()
    px[0, 0] = (10, 20, 30, 1)
    px[63, 47] = (40, 50, 60, 127)
    candidate = _rendered_bbox_union({"edge": (-5, -5, 74, 58)}, 64, 48, pad=0)
    assert candidate == (0, 0, 64, 48)
    bbox, scanned = _tight_alpha_bbox_from_candidate(image, candidate)
    assert bbox == (0, 0, 64, 48)
    assert scanned == 64 * 48


def test_custom_text_is_included_in_rendered_bbox_metadata() -> None:
    bboxes: dict[str, tuple[int, int, int, int]] = {}
    image = compose_overlay(
        canvas_w=320,
        canvas_h=180,
        layout={
            "indicators": {},
            "custom_texts": [{
                "enabled": True,
                "text": "ABOVE",
                "x": 50,
                "y": 50,
                "font_size": 4,
                "rotation": 0,
            }],
        },
        font_path="include/fonts/Roboto-Bold.ttf",
        date_text="",
        time_text="",
        speed_value=0.0,
        distance_m=0.0,
        alt_value=0.0,
        _bboxes=bboxes,
        reuse_canvas=False,
    )
    assert image.getchannel("A").getbbox() is not None
    assert "custom_text:0" in bboxes
    assert _rendered_bbox_union(bboxes, 320, 180, pad=0) == bboxes["custom_text:0"]
