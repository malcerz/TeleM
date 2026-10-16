"""ETAP 5Z.4: editor preview (libmpv) presents HLG with the export's static BT.2390 model."""
import pytest

from src.gui.qt.mpv_hwdec import build_mpv_options


@pytest.mark.parametrize("vendor", ["amd", "nv", "intel", "auto", "cpu"])
def test_hdr_presentation_options_for_every_vendor(vendor):
    opts = build_mpv_options(vendor)
    assert opts["tone_mapping"] == "bt.2390"
    assert opts["hdr_compute_peak"] == "no"          # static, like the export (no dynamic peak detection)
    assert opts["gamut_mapping_mode"] == "relative"
    assert opts["hdr_contrast_recovery"] == "0"
    assert opts["keep_open"] == "yes"
