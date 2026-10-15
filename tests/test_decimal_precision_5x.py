"""ETAP 5X: one decimals/decimal_places rule for every renderer."""
import pytest

from src.indicators.helpers import config_decimals, resolve_decimal_places
from src.telemetry_resolver import configured_precision, resolve_presentation_precision


@pytest.mark.parametrize("cfg, default, expected", [
    ({"decimals": 0}, 1, 0),
    ({"decimals": 1}, 0, 1),
    ({"decimals": 2}, 0, 2),
    ({"decimals": 5}, 0, 2),                      # clamped
    ({"decimals": -1}, 1, 0),
    ({"decimals": "x"}, 1, 1),                    # unparsable → default (was a crash in bar.py)
    ({"decimals": None}, 1, 1),
    ({}, 1, 1),
    ({"decimal_places": 2}, 0, 2),                # legacy alias for non-chart forms
    ({"decimals": 0, "decimal_places": 2}, 1, 0),  # non-chart: decimals wins
    ({"form": "chart", "decimals": 0, "decimal_places": 2}, 1, 2),  # chart: decimal_places wins
    ({"form": "chart", "decimals": 1}, 0, 1),     # chart legacy alias
])
def test_configured_precision(cfg, default, expected):
    assert configured_precision(cfg, default) == expected
    assert config_decimals(cfg, default) == expected


def test_semantic_rule_still_applied_on_top():
    assert resolve_presentation_precision({"decimals": 2}, 1, field="heart_rate") == 0
    assert resolve_decimal_places({"decimals": 2}, 1, field="speed") == 2


@pytest.mark.parametrize("value, decimals, text", [
    (25.4321, 0, "25"), (25.4321, 1, "25.4"), (25.4321, 2, "25.43"),
    (-12.75, 1, "-12.8"), (0.0, 2, "0.00"),
])
def test_formatting_examples(value, decimals, text):
    assert f"{value:.{config_decimals({'decimals': decimals}, 1)}f}" == text


def test_bar_renderers_follow_shared_rule():
    from src.indicators.widget_cache import compute_segment_bar_visual_signature  # noqa: F401
    import inspect
    import src.indicators.bar as bar
    import src.indicators.lean as lean
    for mod in (bar, lean):
        assert 'cfg.get("decimals"' not in inspect.getsource(mod)
