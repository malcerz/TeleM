"""HLG shows only the "Tryb HDR" selector (no descriptive paragraph); real problems keep a message."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def tab():
    app = QApplication.instance() or QApplication([])
    from src.gui.qt.tabs.render_tab import RenderTab
    t = RenderTab()
    t.show()
    app.processEvents()
    yield t
    t.close()


def _apply(tab, summary):
    tab._on_source_color_ready(summary)
    QApplication.processEvents()


def test_hlg_shows_selector_without_paragraph(tab):
    _apply(tab, {"kind": "hlg", "full_range": True, "error": "", "clips": []})
    assert tab.widget_hdr_mode.isVisibleTo(tab)
    assert not tab.lbl_hdr_source_info.isVisibleTo(tab) and tab.lbl_hdr_source_info.text() == ""
    assert tab.cmb_hdr_mode.currentData() == "preserve_hlg"          # default
    labels = [tab.cmb_hdr_mode.itemText(i) for i in range(tab.cmb_hdr_mode.count())]
    assert labels == ["Zachowaj HDR (HLG 10-bit)", "Konwertuj do SDR (tone mapping)"]


def test_sdr_hides_everything(tab):
    _apply(tab, {"kind": "sdr", "full_range": None, "error": "", "clips": []})
    assert not tab.widget_hdr_mode.isVisibleTo(tab)
    assert not tab.lbl_hdr_source_info.isVisibleTo(tab)


@pytest.mark.parametrize("kind", ["ambiguous", "unknown", "pq", "mixed"])
def test_problem_messages_kept(tab, kind):
    msg = "Nie można jednoznacznie ustalić formatu HDR nagrania. Eksport wstrzymany, aby uniknąć nieprawidłowych kolorów."
    _apply(tab, {"kind": kind, "full_range": None, "error": msg, "clips": []})
    assert tab.lbl_hdr_source_info.isVisibleTo(tab)
    assert tab.lbl_hdr_source_info.text().startswith("HDR: ")
    assert not tab.widget_hdr_mode.isVisibleTo(tab)


def test_mode_choice_still_works(tab):
    _apply(tab, {"kind": "hlg", "full_range": True, "error": "", "clips": []})
    seen = []
    tab.signals.sig_settings_changed.connect(lambda n, v: seen.append((n, v)))
    tab.set_amd_hdr_mode("tonemap_sdr")
    assert tab.cmb_hdr_mode.currentData() == "tonemap_sdr" and ("amd_hdr_mode", "tonemap_sdr") in seen
    assert tab._build_options_from_gui()["amd_hdr_mode"] == "tonemap_sdr"
    tab._on_amd_hdr_mode_restored("preserve_hlg")                  # restore path (saved settings)
    assert tab.cmb_hdr_mode.currentData() == "preserve_hlg"
