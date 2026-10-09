import os
import sys
import tempfile
from pathlib import Path
import pytest
from PIL import Image, ImageDraw, ImageFont

from PySide6.QtWidgets import QApplication

from src.indicators.helpers import (
    get_arial_fallback_font,
    split_text_degree_chunks,
    measure_text_with_degree_fallback,
    draw_text_with_degree_fallback,
    load_font,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_degree_symbol_arial_fallback():
    """Weryfikuje, że symbol '°' korzysta z fontu Arial, a pozostałe znaki z fontu głównego."""
    # Użyjmy fontu domyślnego lub systemowego jako głównego
    main_font = load_font("arial", 24)
    chunks = split_text_degree_chunks("25°C", main_font)
    assert len(chunks) == 3
    assert chunks[0][0] == "25"
    assert chunks[0][1] == main_font
    assert chunks[1][0] == "°"
    # Symbol stopnia ma mieć font z Arial resolvera
    assert chunks[1][1] is not None
    assert chunks[2][0] == "C"
    assert chunks[2][1] == main_font

    # Tekst bez stopnia
    chunks_no_deg = split_text_degree_chunks("100 km/h", main_font)
    assert len(chunks_no_deg) == 1
    assert chunks_no_deg[0][0] == "100 km/h"
    assert chunks_no_deg[0][1] == main_font

    # Pomiar i rysowanie
    img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h, bbox = measure_text_with_degree_fallback(draw, "45°", main_font)
    assert w > 0
    assert h > 0

    rendered_bbox = draw_text_with_degree_fallback(
        draw, (10, 10), "45°", font=main_font, fill=(255, 255, 255, 255), anchor="la"
    )
    assert rendered_bbox[2] > rendered_bbox[0]
    assert rendered_bbox[3] > rendered_bbox[1]


def test_settings_tab_no_thread_spin_and_dash_source(qapp):
    """Weryfikuje usunięcie liczby wątków z GUI i etykietę '--' dla braku źródła aktywności."""
    from src.gui.qt.tabs.settings_tab import SettingsTab
    tab = SettingsTab()

    # Brak spin_threads w atrybutach/layout
    assert not hasattr(tab, "spin_threads") or tab.spin_threads is None

    # Etykieta '--' zamiast 'Nic'
    first_label = tab.cmb_auto_source.itemText(0)
    assert first_label == "--"
    assert tab.cmb_auto_source.itemData(0) == "none"


def test_settings_persistence_auto_source(qapp, tmp_path):
    """Weryfikuje persystencję auto_activity_source w def_layout.json."""
    from src.gui.qt.tabs.settings_tab import SettingsTab
    tab = SettingsTab()
    tab.base_dir = tmp_path

    # Zmiana źródła na garmin
    idx = tab.cmb_auto_source.findData("garmin")
    assert idx >= 0
    tab.cmb_auto_source.setCurrentIndex(idx)
    tab._ensure_disk_persistence()

    def_layout_path = tmp_path / "def_layout.json"
    assert def_layout_path.exists()
    import json
    data = json.loads(def_layout_path.read_text(encoding="utf-8"))
    assert data.get("integrations", {}).get("auto_activity_source") == "garmin"

    # Przywrócenie ustawień
    tab.cmb_auto_source.setCurrentIndex(0)  # reset do '--'
    tab._load_settings()
    assert tab.cmb_auto_source.currentData() == "garmin"


def test_main_tabs_state_lock_and_unlock(qapp):
    """Weryfikuje blokadę zakładki Projekt bez wideo i odblokowanie po załadowaniu."""
    from src.gui.qt.main_window import MainWindow

    win = MainWindow()
    project_idx = win.tabs.indexOf(win._project_tab)
    render_idx = win.tabs.indexOf(win._render_tab)
    settings_idx = win.tabs.indexOf(win._settings_tab)
    load_idx = win.tabs.indexOf(win._load_tab)

    # Przed załadowaniem wideo: Projekt DISABLED, pozostałe ENABLED
    assert not win.tabs.isTabEnabled(project_idx)
    assert win.tabs.isTabEnabled(render_idx)
    assert win.tabs.isTabEnabled(settings_idx)
    assert win.tabs.isTabEnabled(load_idx)
    assert win.tabs.currentWidget() == win._load_tab

    # Symulacja przypięcia kontrolera z wideo
    class DummyCtrl:
        video_paths = ["C:/dummy/video.mp4"]
        video_path = "C:/dummy/video.mp4"
        def clear_project(self):
            self.video_paths = []
            self.video_path = None

    win._controller = DummyCtrl()
    win._update_main_tabs_state()
    assert win.tabs.isTabEnabled(project_idx)

    # Czyszczenie projektu
    win.clear_project()
    assert not win.tabs.isTabEnabled(project_idx)
    assert win.tabs.currentWidget() == win._load_tab


def test_default_export_dir_resolution(qapp, tmp_path):
    """Weryfikuje wyznaczanie domyślnego katalogu eksportu: wideo parent, last_export_dir, brak CWD."""
    from src.gui.qt.tabs.render_tab import RenderTab

    tab = RenderTab()
    video_dir = tmp_path / "source_video_dir"
    video_dir.mkdir(parents=True)
    dummy_video = video_dir / "clip01.mp4"
    dummy_video.touch()

    # 1. Na podstawie źródłowego pliku wideo
    class DummyCtrl:
        video_paths = [str(dummy_video)]
        video_path = str(dummy_video)
        layout = {}

    tab._controller = DummyCtrl()
    resolved = tab.resolve_default_export_dir()
    assert resolved == video_dir
    assert resolved != Path.cwd()

    # 2. Na podstawie zapisanego last_export_dir
    custom_dir = tmp_path / "custom_exports"
    custom_dir.mkdir(parents=True)
    tab._controller.layout = {"global": {"last_export_dir": str(custom_dir)}}
    resolved_custom = tab.resolve_default_export_dir()
    assert resolved_custom == custom_dir

    # 3. Jeśli custom_dir nie istnieje -> fallback do video_dir
    tab._controller.layout = {"global": {"last_export_dir": str(tmp_path / "non_existent_dir")}}
    resolved_fallback = tab.resolve_default_export_dir()
    assert resolved_fallback == video_dir


def test_instant_hud_request_refresh():
    """Weryfikuje, że request_preview_refresh wymusza reset _preview_telemetry_loading i wywołanie _render_preview."""
    from src.gui.qt._mixins.preview_mixin import PreviewMixin

    class DummyPreviewController(PreviewMixin):
        def __init__(self):
            self._preview_telemetry_loading = True
            self.video_path = "C:/dummy/video.mp4"
            self.rendered_ts = None
        def _render_preview(self, seek_seconds=None):
            self.rendered_ts = seek_seconds

    ctrl = DummyPreviewController()
    assert ctrl._preview_telemetry_loading is True
    ctrl.request_preview_refresh(0.0)
    assert ctrl._preview_telemetry_loading is False
    assert ctrl.rendered_ts == 0.0
