"""
Unit tests for Intel Chart Fastpath configuration parser and default policy (ETAP 3C.1).
"""
import os
import pytest
import warnings
from src.indicators.chart import (
    get_intel_chart_fastpath_config,
    is_chart_fastpath_enabled,
)

@pytest.fixture(autouse=True)
def clean_env():
    old = os.environ.get("TELEM_INTEL_CHART_FASTPATH")
    yield
    if old is None:
        os.environ.pop("TELEM_INTEL_CHART_FASTPATH", None)
    else:
        os.environ["TELEM_INTEL_CHART_FASTPATH"] = old

@pytest.mark.parametrize("val,expected_enabled,expected_src", [
    (None, False, "default"),
    ("", False, "default"),
    ("   ", False, "default"),
    ("1", True, "env"),
    ("true", True, "env"),
    ("TRUE", True, "env"),
    ("True", True, "env"),
    ("yes", True, "env"),
    ("YES", True, "env"),
    ("on", True, "env"),
    ("ON", True, "env"),
    ("both", True, "env"),
    ("0", False, "env legacy-fallback"),
    ("false", False, "env legacy-fallback"),
    ("FALSE", False, "env legacy-fallback"),
    ("no", False, "env legacy-fallback"),
    ("NO", False, "env legacy-fallback"),
    ("off", False, "env legacy-fallback"),
    ("OFF", False, "env legacy-fallback"),
])
def test_chart_fastpath_flag_matrix(val, expected_enabled, expected_src):
    if val is None:
        os.environ.pop("TELEM_INTEL_CHART_FASTPATH", None)
    else:
        os.environ["TELEM_INTEL_CHART_FASTPATH"] = val
    enabled, src = get_intel_chart_fastpath_config()
    assert enabled is expected_enabled
    assert src == expected_src
    assert is_chart_fastpath_enabled() is expected_enabled

def test_chart_fastpath_selective_cadence():
    os.environ["TELEM_INTEL_CHART_FASTPATH"] = "cadence"
    assert is_chart_fastpath_enabled("fit_cadence_text") is True
    assert is_chart_fastpath_enabled("fit_heart_rate_text") is False

def test_chart_fastpath_selective_hr():
    os.environ["TELEM_INTEL_CHART_FASTPATH"] = "hr"
    assert is_chart_fastpath_enabled("fit_cadence_text") is False
    assert is_chart_fastpath_enabled("fit_heart_rate_text") is True

def test_chart_fastpath_unknown_warns_and_defaults_off():
    os.environ["TELEM_INTEL_CHART_FASTPATH"] = "invalid_turbo_mode"
    with pytest.warns(UserWarning, match="unrecognized value"):
        enabled, src = get_intel_chart_fastpath_config()
    assert enabled is False
    assert src == "default"
