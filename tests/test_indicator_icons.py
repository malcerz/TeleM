from PIL import Image

from src.indicators.icons import ICON_NAMES, render_icon


def test_all_procedural_icons_are_non_empty_and_scaled():
    for name in ICON_NAMES[1:]:
        small = render_icon(name, 16)
        large = render_icon(name, 48)
        assert small is not None and large is not None
        assert small.getbbox() is not None
        assert large.width > small.width and large.height > small.height


def test_none_and_unknown_preserve_no_icon_contract():
    assert render_icon(None, 24) is None
    assert render_icon("none", 24) is None
    assert render_icon("not-a-glyph", 24) is None
