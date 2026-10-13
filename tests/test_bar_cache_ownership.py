"""Owned public tiles and immutable borrowed tiles share pixels, never edits."""
from copy import deepcopy
import subprocess
import types

import numpy as np
from PIL import Image

from src.indicators.bar import (
    _render_bar_indicator, _render_bar_indicator_borrowed,
    clear_bar_cache, get_bar_cache_stats,
)
from src.indicators.dispatcher import render_value_indicator, render_value_indicator_borrowed
from src.indicators.effects import apply_indicator_effects, clear_effects_cache
from src.indicators.raster_ownership import get_owned_copy_stats
from src.indicators.widget_cache import WidgetRenderCache, reset_widget_cache


def test_bar_owned_miss_hit_and_reference_parity_matrix():
    reference = types.ModuleType("bar_5n_reference")
    source = subprocess.check_output(
        ["git", "show", "8465744675c5e75b1ce19a6edde7792ee6da7adc:src/indicators/bar.py"],
        text=True, encoding="utf-8",
    )
    exec(compile(source, "bar_5n_reference", "exec"), reference.__dict__)
    for canvas in ((960, 540), (3840, 2160)):
        for style, orientation in (("ruler", "horizontal"), ("ruler", "vertical"), ("segments", "horizontal")):
            for ss in (1, 2):
                for font in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\consola.ttf"):
                    cfg = dict(x=50, y=50, bar_style=style, orientation=orientation,
                               size=30, min_val=0, max_val=100, show_value=True,
                               show_label=True, shadow_enabled=True, shadow_distance=3,
                               shadow_length=5, shadow_fade=.5, shadow_opacity=.7,
                               outline_enabled=True, outline_width=2)
                    frozen_cfg = deepcopy(cfg)
                    def args(value):
                        return (*canvas, {"indicators": {"bar": cfg}}, font,
                                "bar", value, "%", "BATTERY", cfg, min(canvas),
                                1, 18, None, 0, 100, 10, 3, canvas[0] // 3, ss)
                    clear_bar_cache()
                    first = _render_bar_indicator(*args(25))[0]
                    expected_a = np.asarray(first).copy()
                    # Mutate the MISS result and nested Pillow metadata.
                    first.putpixel((0, 0), (9, 8, 7, 6))
                    first.info["nested"] = {"edited": True}
                    hit = _render_bar_indicator(*args(25))[0]
                    assert np.array_equal(np.asarray(hit), expected_a)
                    assert "nested" not in hit.info
                    assert get_bar_cache_stats()["hits"] >= 1
                    hit.putpixel((0, 0), (1, 2, 3, 4))
                    b = _render_bar_indicator(*args(75))[0]
                    a_again = _render_bar_indicator(*args(25))[0]
                    assert np.array_equal(np.asarray(a_again), expected_a)
                    assert b.size != a_again.size or not np.array_equal(np.asarray(b), expected_a)
                    reference.clear_bar_cache()
                    before = reference._render_bar_indicator(*args(25))[0]
                    assert before.size == a_again.size
                    assert before.tobytes() == a_again.tobytes()
                    clear_effects_cache()
                    styled_before = apply_indicator_effects(before, cfg, min(canvas))
                    clear_effects_cache()
                    styled_after = apply_indicator_effects(a_again, cfg, min(canvas))
                    assert styled_before.size == styled_after.size
                    assert styled_before.tobytes() == styled_after.tobytes()
                    assert cfg == frozen_cfg


def test_widget_cache_isolates_input_output_metadata_and_two_consumers():
    cache = WidgetRenderCache(enabled=True)
    source = Image.new("RGBA", (32, 24), (20, 40, 60, 255))
    source.info["nested"] = {"value": 1}
    metadata = {"bbox": [1, 2, 3, 4], "nested": {"value": 1}}
    def request():
        return cache.get_or_render("a", "segment_bar", lambda: (1,),
                                   lambda: (source, 3, 4, metadata))
    first = request()
    source.putpixel((0, 0), (0, 0, 0, 0))
    source.info["nested"]["value"] = 99
    metadata["bbox"][0] = 99
    first[0].putpixel((1, 1), (0, 0, 0, 0))
    first[0].info["nested"]["value"] = 88
    first[3]["nested"]["value"] = 88
    second = request()
    assert second[0].getpixel((0, 0)) == (20, 40, 60, 255)
    assert second[0].getpixel((1, 1)) == (20, 40, 60, 255)
    assert second[0].info["nested"] == {"value": 1}
    assert second[3] == {"bbox": [1, 2, 3, 4], "nested": {"value": 1}}
    second[0].putalpha(0)
    second[3]["bbox"][0] = 77
    third = request()
    assert third[0].getpixel((0, 0)) == (20, 40, 60, 255)
    assert third[3]["bbox"][0] == 1
    assert cache.get_stats()["total_hits"] == 2
    assert cache.get_stats()["total_misses"] == 1


def test_dispatcher_effects_owned_and_compositor_borrowed_do_not_copy_hud():
    from src.indicators.compositor import compose_overlay
    for form, style in (("bar", "ruler"), ("segment_bar", "segments")):
        for color in ("#FFD42A", "#00FF80"):
            cfg = dict(enabled=True, form=form, bar_style=style, x=50, y=50,
                       size=25, font_size=1.2, min_val=0, max_val=100,
                       marker_color=color, text_color=color, shadow_enabled=True,
                       shadow_distance=3, shadow_length=5, shadow_fade=.5,
                       outline_enabled=True, outline_width=2)
            layout = {"indicators": {"bar": cfg}}
            clear_bar_cache()
            clear_effects_cache()
            reset_widget_cache(enabled=True)
            kwargs = dict(canvas_w=3840, canvas_h=2160, layout=layout,
                          font_path=r"C:\Windows\Fonts\arial.ttf", key="bar",
                          value=25, unit="%", label="BAR")
            borrowed = render_value_indicator_borrowed(**kwargs)[0]
            initial = borrowed.tobytes()
            public = render_value_indicator(**kwargs)[0]
            assert public.tobytes() == initial
            public.putalpha(0)
            assert render_value_indicator(**kwargs)[0].tobytes() == initial
            stats = get_owned_copy_stats()
            # Two successive exports/preview compositions keep the source
            # immutable. Only the HUD destination receives paste/alpha edits.
            frames = [compose_overlay(3840, 2160, layout, "", "", "", 0, 0,
                      indicator_values={"bar": 25}, render_keys={"bar"},
                      reuse_canvas=False).tobytes() for _ in range(2)]
            assert frames[0] == frames[1]
            assert borrowed.tobytes() == initial
            assert get_owned_copy_stats() == stats

            # Cache eviction/value changes cannot invalidate a held raster.
            render_value_indicator_borrowed(**{**kwargs, "value": 75})
            clear_bar_cache()
            reset_widget_cache(enabled=True)
            assert borrowed.tobytes() == initial
            # Public API also accepts cfg_override as its ninth positional arg.
            positional = (3840, 2160, {"indicators": {"bar": {"form": "text"}}},
                          kwargs["font_path"], "bar", 25, "%", "BAR", cfg)
            public_override = render_value_indicator(*positional)[0]
            expected = public_override.tobytes()
            assert not hasattr(public_override, "_dynamic_key")
            public_override.putalpha(0)
            assert render_value_indicator(*positional)[0].tobytes() == expected
