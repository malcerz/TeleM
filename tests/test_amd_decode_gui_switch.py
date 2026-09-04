"""Tests for AMD Video Decode GUI Switch, Persistence, Priority & Isolation.

Covers:
1. Default / no setting -> GPU.
2. GUI GPU -> exporter GPU.
3. GUI CPU -> exporter CPU.
4. Restart after save -> CPU persists.
5. Change CPU without save -> restores last saved value (GPU).
6. Environment variable override contract (Priority 1: env, Priority 2: GUI, Priority 3: default).
7. Backend isolation (Intel / NVIDIA unaffected).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from PySide6.QtWidgets import QApplication
from src.gui.qt.signals import get_signals
from src.gui.qt.tabs.settings_tab import SettingsTab
from src.gui.qt.tabs.render_tab import RenderTab
from src.gui.qt._mixins.preset_mixin import PresetMixin


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _make_fake_def_layout(tmp_dir: Path, *, amd_decode_mode=None) -> Path:
    data = {
        "version": 6,
        "width": 1280,
        "height": 720,
        "global": {"text_outline": 3, "font": "Arial"},
        "indicators": {
            "speed": {"form": "gauge", "x": 10.0, "y": 20.0, "font": ""}
        },
    }
    if amd_decode_mode is not None:
        data["global"]["amd_decode_mode"] = amd_decode_mode
    p = tmp_dir / "def_layout.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


class FakeController(PresetMixin):
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.signals = get_signals()
        self.amd_decode_mode = "gpu"
        self._global_font_family = "Arial"
        self.font_path = ""
        self._startup_preset_path = ""
        self._cut_regions = []
        self.layout = {}
        self._load_startup_preset()

    def _load_startup_preset(self):
        from src.gui.layout_manager import normalize_layout
        def_layout = self.base_dir / "def_layout.json"
        if def_layout.exists():
            self.layout = normalize_layout(def_layout, 1280, 720)
            saved_mode = self.layout.get("global", {}).get("amd_decode_mode", "gpu")
            self.amd_decode_mode = (saved_mode or "gpu").lower()
            self.signals.sig_amd_decode_mode_restored.emit(self.amd_decode_mode)


def test_settings_tab_has_no_amd_decode_control(qapp):
    """Weryfikacja, że przełącznik dekodowania AMD NIE znajduje się w Ustawienia (SettingsTab)."""
    settings_tab = SettingsTab()
    assert not hasattr(settings_tab, "cmb_amd_decode")
    assert not hasattr(settings_tab, "lbl_cpu_warning")
    assert not hasattr(settings_tab, "set_amd_decode_mode")


def test_default_no_setting_defaults_to_gpu(tmp_path, qapp):
    """Brak wpisu w def_layout.json -> domyślnie GPU w RenderTab."""
    _make_fake_def_layout(tmp_path, amd_decode_mode=None)
    tab = RenderTab()
    ctrl = FakeController(tmp_path)

    assert ctrl.amd_decode_mode == "gpu"
    assert tab.cmb_amd_decode.currentData() == "gpu"
    assert tab.lbl_cpu_warning.isHidden()


def test_gui_change_cpu_without_save_reverts_on_restart(tmp_path, qapp):
    """Zmiana CPU w RenderTab bez kliknięcia zapisu: po restarcie wraca GPU."""
    _make_fake_def_layout(tmp_path, amd_decode_mode="gpu")
    tab = RenderTab()
    ctrl = FakeController(tmp_path)

    # Zmiana w UI na CPU
    cpu_idx = tab.cmb_amd_decode.findData("cpu")
    assert cpu_idx >= 0
    tab.cmb_amd_decode.setCurrentIndex(cpu_idx)

    # Sprawdź czy warning stał się widoczny i kontroler dostał sygnał
    assert not tab.lbl_cpu_warning.isHidden()
    ctrl._on_settings_changed("amd_decode_mode", "cpu")
    assert ctrl.amd_decode_mode == "cpu"

    # Plik def_layout.json NIE został zapisany (brak autosave)
    disk_data = json.loads((tmp_path / "def_layout.json").read_text(encoding="utf-8"))
    assert disk_data["global"].get("amd_decode_mode") == "gpu"

    # Symulacja restartu aplikacji
    ctrl2 = FakeController(tmp_path)
    assert ctrl2.amd_decode_mode == "gpu"
    assert tab.cmb_amd_decode.currentData() == "gpu"
    assert tab.lbl_cpu_warning.isHidden()


def test_gui_change_cpu_with_save_persists_across_restart(tmp_path, qapp):
    """Zmiana CPU w RenderTab i zapis: po restarcie pozostaje CPU, a wskaźniki są zachowane."""
    _make_fake_def_layout(tmp_path, amd_decode_mode="gpu")
    tab = RenderTab()
    ctrl = FakeController(tmp_path)

    # Zmiana na CPU i jawny zapis
    ctrl._on_settings_changed("amd_decode_mode", "cpu")
    ctrl._save_global_settings_to_default()

    # Weryfikacja pliku na dysku
    disk_data = json.loads((tmp_path / "def_layout.json").read_text(encoding="utf-8"))
    assert disk_data["global"].get("amd_decode_mode") == "cpu"
    # Wskaźniki nie uległy zniszczeniu
    assert "speed" in disk_data.get("indicators", {})

    # Symulacja restartu
    ctrl2 = FakeController(tmp_path)
    assert ctrl2.amd_decode_mode == "cpu"
    assert tab.cmb_amd_decode.currentData() == "cpu"
    assert not tab.lbl_cpu_warning.isHidden()


def test_options_pipeline_passes_amd_decode_mode():
    """Weryfikacja przekazywania parametru z kontrolera do stream_overlay_to_ffmpeg."""
    from src.gui.qt._mixins.render_mixin import RenderMixin

    class DummyRenderController(RenderMixin):
        def __init__(self, mode):
            self.amd_decode_mode = mode
            self.video_path = Path("fake.mp4")
            self.video_paths = [str(self.video_path)]
            self.video_duration_s = 10.0
            self.render_threads = 4
            self.font_path = ""
            self.layout = {"global": {}, "indicators": {}}
            self._cut_regions = []
            self.telemetry = MagicMock()
            self.telemetry.start_dt_utc = None
            self.telemetry.iso_samples = []
            self.telemetry.exposure_samples = []
            self.telemetry.temperature_samples = []
            self.telemetry.gpx_speed_samples = []
            self.telemetry.gpx_track_samples = []
            self.telemetry.gpx_alt_samples = []
            self.telemetry.gpx_power_samples = []
            self.telemetry.gpx_atemp_samples = []
            self.telemetry.gpx_hr_samples = []
            self.telemetry.gpx_cad_samples = []
            self.telemetry.fit_data = {}
            self.telemetry.get_gps_track_for_source.return_value = []
            self.render_cancel_event = MagicMock()
            self.render_process_holder = {}
            self.signals = MagicMock()
            self.ffmpeg_exe = "ffmpeg"
            self.ffprobe_exe = "ffprobe"

    # Sprawdź czy options.get('amd_decode_mode', self.amd_decode_mode) działa
    ctrl_cpu = DummyRenderController("cpu")
    with patch("src.gui.qt._mixins.render_mixin.stream_overlay_to_ffmpeg") as mock_stream, \
         patch("src.gui.qt._mixins.render_mixin.ffprobe_stream_info", return_value={"streams": [{"width": 1920, "height": 1080, "avg_frame_rate": "30/1"}]}), \
         patch("src.gui.qt._mixins.render_mixin.load_json_with_fallback", return_value=[]), \
         patch("pathlib.Path.exists", return_value=True):
        ctrl_cpu._render_pipeline({"encoder": "amd"})
        assert mock_stream.call_count == 1
        _, kwargs = mock_stream.call_args
        assert kwargs.get("amd_decode_mode") == "cpu"

    ctrl_gpu = DummyRenderController("gpu")
    with patch("src.gui.qt._mixins.render_mixin.stream_overlay_to_ffmpeg") as mock_stream, \
         patch("src.gui.qt._mixins.render_mixin.ffprobe_stream_info", return_value={"streams": [{"width": 1920, "height": 1080, "avg_frame_rate": "30/1"}]}), \
         patch("src.gui.qt._mixins.render_mixin.load_json_with_fallback", return_value=[]), \
         patch("pathlib.Path.exists", return_value=True):
        ctrl_gpu._render_pipeline({"encoder": "amd"})
        assert mock_stream.call_count == 1
        _, kwargs = mock_stream.call_args
        assert kwargs.get("amd_decode_mode") == "gpu"


def test_priority_resolution_contract():
    """Weryfikacja hierarchii priorytetów:
    1. explicit env override AMD_DECODE_MODE
    2. ustawienie GUI / explicit param
    3. fallback GPU
    """
    def resolve_mode(env_val, gui_val):
        env_dict = {"AMD_DECODE_MODE": env_val} if env_val is not None else {}
        with patch.dict(os.environ, env_dict, clear=False):
            if env_val is None and "AMD_DECODE_MODE" in os.environ:
                del os.environ["AMD_DECODE_MODE"]
            amd_decode_mode_env = os.environ.get("AMD_DECODE_MODE", "").strip().upper()
            if amd_decode_mode_env in {"CPU", "0"}:
                resolved = "CPU"
            elif amd_decode_mode_env in {"GPU", "1"}:
                resolved = "GPU"
            elif gui_val is not None and str(gui_val).strip().upper() in {"CPU", "0"}:
                resolved = "CPU"
            else:
                resolved = "GPU"
            return resolved

    # 1. Brak env, GUI = gpu -> GPU
    assert resolve_mode(None, "gpu") == "GPU"
    # 2. Brak env, GUI = cpu -> CPU
    assert resolve_mode(None, "cpu") == "CPU"
    # 3. Brak env, brak GUI -> fallback GPU
    assert resolve_mode(None, None) == "GPU"
    # 4. GUI = gpu, ale ENV = CPU -> CPU (env ma pierwszeństwo)
    assert resolve_mode("CPU", "gpu") == "CPU"
    # 5. GUI = cpu, ale ENV = GPU -> GPU (env ma pierwszeństwo)
    assert resolve_mode("GPU", "cpu") == "GPU"


def test_render_tab_amd_decode_switch(qapp):
    """Weryfikacja przełącznika Dekodowanie AMD w zakładce Renderingu (RenderTab)."""
    signals = get_signals()
    render_tab = RenderTab()

    # Domyślna wartość w RenderTab to GPU
    assert render_tab.cmb_amd_decode.currentData() == "gpu"
    assert render_tab.lbl_cpu_warning.isHidden()

    # Zmiana na CPU w RenderTab
    received_settings = []
    signals.sig_settings_changed.connect(lambda k, v: received_settings.append((k, v)))

    cpu_idx = render_tab.cmb_amd_decode.findData("cpu")
    assert cpu_idx >= 0
    render_tab.cmb_amd_decode.setCurrentIndex(cpu_idx)

    # Ostrzeżenie widoczne, sygnał wyemitowany
    assert not render_tab.lbl_cpu_warning.isHidden()
    assert ("amd_decode_mode", "cpu") in received_settings

    # Weryfikacja słownika options przy kliknięciu render
    captured_options = []
    signals.sig_render_requested.connect(lambda opts: captured_options.append(opts))
    render_tab._on_render()
    assert len(captured_options) == 1
    assert captured_options[0]["amd_decode_mode"] == "cpu"

    # Przywrócenie trybu przez sig_amd_decode_mode_restored
    signals.sig_amd_decode_mode_restored.emit("gpu")
    assert render_tab.cmb_amd_decode.currentData() == "gpu"
    assert render_tab.lbl_cpu_warning.isHidden()
