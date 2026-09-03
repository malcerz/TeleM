"""Unit tests for the expanded TeleM icon set and renderer."""

from PIL import Image

from src.indicators.icons import (
    ICON_NAMES,
    ICON_LABELS,
    ICON_ALIASES,
    render_icon,
    clear_icon_cache,
)


def test_all_icon_names_exist_and_render_valid_rgba():
    clear_icon_cache()
    valid_icons = [name for name in ICON_NAMES if name != "none"]
    assert len(valid_icons) >= 70, f"Expected at least 70 icons, got {len(valid_icons)}"

    for name in valid_icons:
        img_16 = render_icon(name, 16)
        img_32 = render_icon(name, 32)
        img_64 = render_icon(name, 64)

        assert img_16 is not None, f"Icon {name} returned None at 16px"
        assert img_32 is not None, f"Icon {name} returned None at 32px"
        assert img_64 is not None, f"Icon {name} returned None at 64px"

        assert isinstance(img_16, Image.Image)
        assert img_16.mode == "RGBA"
        assert img_32.height > img_16.height
        assert img_64.height > img_32.height

        # Must have non-transparent pixels
        bbox = img_32.getchannel("A").getbbox()
        assert bbox is not None, f"Icon {name} has empty alpha channel"


def test_icon_aliases_resolve_properly():
    for alias, target in ICON_ALIASES.items():
        img_alias = render_icon(alias, 24)
        img_target = render_icon(target, 24)
        assert img_alias is not None, f"Alias {alias} returned None"
        assert img_target is not None, f"Target {target} returned None"
        assert img_alias.size == img_target.size


def test_none_and_falsy_return_none():
    for val in (None, "", "none", "0", "false", "off", "invalid_icon_xyz"):
        assert render_icon(val, 24) is None


def test_icon_tinting():
    red_fill = (255, 0, 0, 255)
    img_red = render_icon("heart", 32, fill=red_fill, outline=(0, 0, 0, 0))
    assert img_red is not None
    # Check that pixels have dominant red channel
    r, g, b, a = img_red.split()
    r_max = max(r.getdata())
    g_max = max(g.getdata())
    assert r_max > 200
    assert g_max == 0


def test_icon_outline_creation():
    img_no_outline = render_icon("speedometer", 32, outline=(0, 0, 0, 0))
    img_with_outline = render_icon("speedometer", 32, outline=(0, 0, 0, 255))
    assert img_no_outline is not None
    assert img_with_outline is not None
    # Outline padding makes the image slightly larger for contrast border
    assert img_with_outline.width >= img_no_outline.width
    assert img_with_outline.height >= img_no_outline.height


def test_icon_labels_cover_all_names():
    for name in ICON_NAMES:
        assert name in ICON_LABELS, f"Missing human-readable label for icon: {name}"
        assert len(ICON_LABELS[name]) > 0
