import os
import warnings
import pytest
from src.ffmpeg.shared_memory import (
    get_intel_direct_shm_config,
    is_intel_direct_shm_enabled,
)


@pytest.fixture(autouse=True)
def restore_environ():
    orig = os.environ.get("TELEM_INTEL_HUD_DIRECT_SHM")
    yield
    if orig is None:
        os.environ.pop("TELEM_INTEL_HUD_DIRECT_SHM", None)
    else:
        os.environ["TELEM_INTEL_HUD_DIRECT_SHM"] = orig


def test_intel_direct_shm_default_unset():
    os.environ.pop("TELEM_INTEL_HUD_DIRECT_SHM", None)
    enabled, source = get_intel_direct_shm_config()
    assert enabled is True
    assert source == "default"
    assert is_intel_direct_shm_enabled() is True


@pytest.mark.parametrize(
    "val",
    ["1", "true", "yes", "on", " TRUE ", " Yes ", "ON"],
)
def test_intel_direct_shm_explicit_true(val):
    os.environ["TELEM_INTEL_HUD_DIRECT_SHM"] = val
    enabled, source = get_intel_direct_shm_config()
    assert enabled is True
    assert source == "env"
    assert is_intel_direct_shm_enabled() is True


@pytest.mark.parametrize(
    "val",
    ["0", "false", "no", "off", " 0 ", " FALSE ", "No", "OFF"],
)
def test_intel_direct_shm_explicit_false(val):
    os.environ["TELEM_INTEL_HUD_DIRECT_SHM"] = val
    enabled, source = get_intel_direct_shm_config()
    assert enabled is False
    assert source == "env legacy-fallback"
    assert is_intel_direct_shm_enabled() is False


def test_intel_direct_shm_garbage_warning():
    import src.ffmpeg.shared_memory as sm
    sm._WARNED_UNKNOWN_DIRECT_SHM = False
    os.environ["TELEM_INTEL_HUD_DIRECT_SHM"] = "garbage_value_xyz"
    with pytest.warns(UserWarning, match="unrecognized value"):
        enabled, source = get_intel_direct_shm_config()
    assert enabled is True
    assert source == "default"
    assert is_intel_direct_shm_enabled() is True
