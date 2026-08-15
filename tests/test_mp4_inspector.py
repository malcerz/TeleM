"""Testy inspekcji MP4 (ffprobe) i panelu informacji w zakładce Wczytywanie.

Obejmują:
- konwersje/etykiety (rozmiar, czas, FPS, bitrate, codec, kolor, audio),
- parsowanie wyniku ffprobe (przez zamockowany subprocess),
- formatowanie bloku tekstu dla GUI,
- asynchroniczną aktualizację LoadTab (bez blokowania GUI),
- przycisk „Analiza QP”.
"""

from __future__ import annotations

import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtWidgets import QApplication

from src.gui.qt import mp4_inspector as mi
from src.gui.qt.mp4_inspector import (
    _fmt_bitrate,
    _fmt_duration,
    _fmt_fps,
    _fmt_size,
    _parse_color,
    _video_codec_label,
    _audio_codec_label,
    _channel_label,
    _fps_value,
    format_file_info_text,
    inspect_mp4,
    QP_PLACEHOLDER,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _wait_until(app, cond, timeout_ms=3000) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


# ---------------------------------------------------------------------------
# Konwersje i etykiety
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_size_bytes(self):
        assert _fmt_size(9_375_000_000) == "8.73 GB"
        assert _fmt_size(1_024) == "1.00 KB"
        assert _fmt_size(512) == "512 B"
        assert _fmt_size(None) == "—"

    def test_duration(self):
        assert _fmt_duration(767) == "00:12:47"
        assert _fmt_duration(3723) == "01:02:03"
        assert _fmt_duration(None) == "—"

    def test_fps(self):
        assert _fmt_fps(59.940059) == "59.94"
        assert _fmt_fps(29.970029) == "29.97"
        assert _fmt_fps(30.0) == "30"
        assert _fmt_fps(None) == "—"

    def test_fps_from_avg_frame_rate(self):
        stream = {"avg_frame_rate": "60000/1001", "r_frame_rate": "60/1"}
        fps = _fps_value(stream)
        assert fps is not None and abs(fps - 59.940059) < 0.001

    def test_fps_missing(self):
        assert _fps_value({"avg_frame_rate": "", "r_frame_rate": "0/0"}) is None

    def test_bitrate(self):
        assert _fmt_bitrate(92_400_000) == "92.4 Mb/s"
        assert _fmt_bitrate(192_000) == "192 kb/s"
        assert _fmt_bitrate(1_500_000_000) == "1.50 Gb/s"
        assert _fmt_bitrate(None) == "—"

    def test_codec_labels(self):
        assert _video_codec_label("hevc") == "HEVC / H.265"
        assert _video_codec_label("h264") == "H.264 / AVC"
        assert _audio_codec_label("aac") == "AAC"
        assert _video_codec_label("") == "—"

    def test_channel_label(self):
        assert _channel_label(2, "stereo") == "Stereo"
        assert _channel_label(6, "") == "5.1"
        assert _channel_label(2, "") == "Stereo"
        assert _channel_label(None, "") == "—"

    def test_parse_color(self):
        stream = {
            "color_primaries": "bt2020",
            "color_transfer": "arib-std-b67",
            "color_space": "bt2020nc",
            "color_range": "tv",
        }
        c = _parse_color(stream)
        assert c["summary"] == "BT.2020 / HLG"
        assert c["range"] == "Limited"

    def test_parse_color_missing(self):
        c = _parse_color(None)
        assert c["summary"] == "—"
        assert c["range"] == "—"


# ---------------------------------------------------------------------------
# Parsowanie ffprobe (zamockowany subprocess)
# ---------------------------------------------------------------------------

class TestInspectMp4:
    @staticmethod
    def _mock_ffprobe(monkeypatch, json_data, gpmf_index=None):
        import json
        from unittest import mock

        class _Proc:
            def __init__(self, stdout, stderr, returncode=0):
                self.stdout = stdout
                self.stderr = stderr
                self.returncode = returncode

        def fake_run(cmd, **kwargs):
            return _Proc(json.dumps(json_data), "")

        monkeypatch.setattr("src.gui.qt.mp4_inspector.subprocess.run", fake_run)
        monkeypatch.setattr(
            "src.gui.qt.mp4_inspector.find_gpmf_stream_index",
            lambda *a, **k: gpmf_index,
        )

    @staticmethod
    def _hevc_main10_hlg():
        return {
            "streams": [
                {
                    "index": 0, "codec_type": "video", "codec_name": "hevc",
                    "profile": "Main 10", "width": 3840, "height": 2160,
                    "pix_fmt": "yuv420p10le", "avg_frame_rate": "60000/1001",
                    "bit_rate": "92400000", "bits_per_raw_sample": "10",
                    "color_primaries": "bt2020", "color_transfer": "arib-std-b67",
                    "color_space": "bt2020nc", "color_range": "tv",
                },
                {
                    "index": 1, "codec_type": "audio", "codec_name": "aac",
                    "sample_rate": "48000", "channels": 2,
                    "channel_layout": "stereo", "bit_rate": "192000",
                },
            ],
            "format": {"duration": "767.04", "size": "9375000000", "bit_rate": "97800000"},
        }

    def test_full_hevc_hlg_with_gpmf(self, monkeypatch):
        self._mock_ffprobe(monkeypatch, self._hevc_main10_hlg(), gpmf_index=2)
        info = inspect_mp4("GX010123.MP4", "ffprobe")

        assert info["filename"] == "GX010123.MP4"
        assert info["size_text"] == "8.73 GB"
        assert info["duration_text"] == "00:12:47"
        v = info["video"]
        assert v["codec_label"] == "HEVC / H.265"
        assert v["profile"] == "Main 10"
        assert v["resolution"] == "3840 × 2160"
        assert v["fps_text"] == "59.94"
        assert v["pix_fmt"] == "yuv420p10le"
        assert v["bit_depth_text"] == "10 bit"
        assert v["bitrate_text"] == "92.4 Mb/s"
        c = info["color"]
        assert c["summary"] == "BT.2020 / HLG"
        assert c["range"] == "Limited"
        a = info["audio"]
        assert a["codec_label"] == "AAC"
        assert a["sample_rate_text"] == "48 kHz"
        assert a["channels_text"] == "Stereo"
        assert a["bitrate_text"] == "192 kb/s"
        assert info["gpmf"] is True

    def test_no_gpmf_no_audio(self, monkeypatch):
        data = {
            "streams": [
                {
                    "index": 0, "codec_type": "video", "codec_name": "h264",
                    "profile": "High", "width": 1920, "height": 1080,
                    "pix_fmt": "yuv420p", "avg_frame_rate": "30000/1001",
                    "color_primaries": "bt709", "color_transfer": "bt709",
                    "color_space": "bt709", "color_range": "tv",
                },
            ],
            "format": {"duration": "60.0", "size": "200000000"},
        }
        self._mock_ffprobe(monkeypatch, data, gpmf_index=None)
        info = inspect_mp4("plain.MP4", "ffprobe")

        assert info["gpmf"] is False
        assert info["audio"] is None
        assert info["video"]["codec_label"] == "H.264 / AVC"
        assert info["video"]["fps_text"] == "29.97"
        assert info["color"]["summary"] == "BT.709 / BT.709"

    def test_error_raises(self, monkeypatch):
        class _Proc:
            returncode = 1
            stdout = ""
            stderr = "Invalid data found"

        monkeypatch.setattr(
            "src.gui.qt.mp4_inspector.subprocess.run",
            lambda *a, **k: _Proc(),
        )
        with pytest.raises(RuntimeError):
            inspect_mp4("broken.MP4", "ffprobe")


# ---------------------------------------------------------------------------
# Formatowanie bloku tekstu
# ---------------------------------------------------------------------------

class TestFormatText:
    @staticmethod
    def _info(gpmf=True, audio=True):
        info = {
            "filename": "GX010123.MP4",
            "size_text": "8.73 GB",
            "duration_text": "00:12:47",
            "video": {
                "resolution": "3840 × 2160",
                "fps_text": "59.94",
                "codec_label": "HEVC / H.265",
                "profile": "Main 10",
                "pix_fmt": "yuv420p10le",
                "bit_depth_text": "10 bit",
                "bitrate_text": "92.4 Mb/s",
            },
            "color": {"summary": "BT.2020 / HLG", "range": "Limited", "space": "BT.2020 NC"},
            "audio": (
                {
                    "codec_label": "AAC",
                    "sample_rate_text": "48 kHz",
                    "channels_text": "Stereo",
                    "bitrate_text": "192 kb/s",
                }
                if audio
                else None
            ),
            "gpmf": gpmf,
        }
        return info

    def test_full_text(self):
        text = format_file_info_text(self._info(gpmf=True, audio=True))
        assert "Nazwa pliku: GX010123.MP4" in text
        assert "Rozmiar: 8.73 GB" in text
        assert "Czas: 00:12:47" in text
        assert "FPS: 59.94" in text
        assert "Kodek: HEVC / H.265" in text
        assert "Profil: Main 10" in text
        assert "Bit depth: 10 bit" in text
        assert "Bitrate: 92.4 Mb/s" in text
        assert "BT.2020 / HLG" in text
        assert "Range: Limited" in text
        assert "Audio:" in text
        assert "AAC" in text
        assert "48 kHz" in text
        assert "Stereo" in text
        assert "192 kb/s" in text
        assert "GPMF: TAK" in text

    def test_no_audio_no_gpmf(self):
        text = format_file_info_text(self._info(gpmf=False, audio=False))
        assert "Audio: BRAK" in text
        assert "GPMF: NIE" in text

    def test_missing_values_use_dash(self):
        info = self._info()
        info["video"] = {
            "resolution": "—", "fps_text": "—", "codec_label": "—",
            "profile": "—", "pix_fmt": "—", "bit_depth_text": "—",
            "bitrate_text": "—",
        }
        text = format_file_info_text(info)
        assert "Rozdzielczość: —" in text
        assert "FPS: —" in text
        assert "Kodek: —" in text


# ---------------------------------------------------------------------------
# LoadTab — asynchroniczna inspekcja i przycisk Analiza QP
# ---------------------------------------------------------------------------

class TestLoadTabInspection:
    def _make_tab(self, qapp):
        from src.gui.qt.tabs.load_tab import LoadTab
        return LoadTab()

    def _inspect_result(self):
        return {
            "filename": "test.MP4",
            "size_text": "1.00 GB",
            "duration_text": "00:01:00",
            "video": {
                "resolution": "1920 × 1080", "fps_text": "30",
                "codec_label": "H.264 / AVC", "profile": "High",
                "pix_fmt": "yuv420p", "bit_depth_text": "8 bit",
                "bitrate_text": "20.0 Mb/s",
            },
            "color": {"summary": "BT.709 / BT.709", "range": "Limited", "space": "BT.709"},
            "audio": None,
            "gpmf": True,
        }

    def test_info_appears_without_load(self, qapp, monkeypatch):
        import src.gui.qt.tabs.load_tab as lt
        tab = self._make_tab(qapp)
        tab.show()

        monkeypatch.setattr(lt, "resolve_ffprobe", lambda: "ffprobe")
        monkeypatch.setattr(lt, "inspect_mp4", lambda path, ffprobe: self._inspect_result())

        tab._video_paths = ["C:/videos/test.MP4"]
        tab._start_info_inspection()

        ok = _wait_until(qapp, lambda: "GPMF: TAK" in tab.lbl_file_info.text())
        assert ok, f"Nie doczekano informacji: {tab.lbl_file_info.text()!r}"
        assert "Nazwa pliku: test.MP4" in tab.lbl_file_info.text()
        assert "FPS: 30" in tab.lbl_file_info.text()
        # Wczytaj nie był wciśnięty — przycisk nadal aktywny
        assert tab.btn_load.isEnabled()

    def test_error_handled(self, qapp, monkeypatch):
        import src.gui.qt.tabs.load_tab as lt
        tab = self._make_tab(qapp)
        tab.show()

        monkeypatch.setattr(lt, "resolve_ffprobe", lambda: "ffprobe")
        monkeypatch.setattr(lt, "inspect_mp4", lambda path, ffprobe: (_ for _ in ()).throw(RuntimeError("bad")))

        tab._video_paths = ["C:/videos/broken.MP4"]
        tab._start_info_inspection()

        ok = _wait_until(
            qapp,
            lambda: tab.lbl_file_info.text() == "Nie udało się odczytać informacji o filmie.",
        )
        assert ok, f"Nie doczekano błędu: {tab.lbl_file_info.text()!r}"

    def test_rapid_switch_ignores_stale_result(self, qapp, monkeypatch):
        import src.gui.qt.tabs.load_tab as lt
        tab = self._make_tab(qapp)
        tab.show()

        monkeypatch.setattr(lt, "resolve_ffprobe", lambda: "ffprobe")
        calls = {"count": 0}

        def fake_inspect(path, ffprobe):
            if "first" in str(path):
                time.sleep(0.2)  # stary plik — wolniejsza analiza
                info = self._inspect_result()
                info["filename"] = "first.MP4"
                return info
            info = self._inspect_result()
            info["filename"] = "second.MP4"
            return info

        monkeypatch.setattr(lt, "inspect_mp4", fake_inspect)

        tab._video_paths = ["C:/videos/first.MP4"]
        tab._start_info_inspection()  # gen 1 (wolna)
        tab._video_paths = ["C:/videos/second.MP4"]
        tab._start_info_inspection()  # gen 2 (szybka)

        ok = _wait_until(qapp, lambda: "second.MP4" in tab.lbl_file_info.text())
        assert ok, f"Nie doczekano drugiego pliku: {tab.lbl_file_info.text()!r}"
        # Po chwili stary wynik (first.MP4) nie może nadpisać nowego
        _wait_until(qapp, lambda: False, timeout_ms=400)
        assert "second.MP4" in tab.lbl_file_info.text()

    def test_clear_resets_panel(self, qapp):
        tab = self._make_tab(qapp)
        tab.show()
        tab._video_paths = ["C:/videos/test.MP4"]
        tab.lbl_file_info.setText("dowolny tekst")
        tab.btn_analyze_qp.setEnabled(True)
        tab._on_clear()
        assert tab.lbl_file_info.text() == "Wybierz plik MP4, aby zobaczyć informacje o filmie."
        assert not tab.btn_analyze_qp.isEnabled()

    def test_analyze_qp_button(self, qapp, tmp_path):
        tab = self._make_tab(qapp)
        tab.show()
        # początkowo wyłączony i z placeholderem wyniku
        assert not tab.btn_analyze_qp.isEnabled()
        assert "Średni" in tab.lbl_qp_result.text()
        assert "Mediana" in tab.lbl_qp_result.text()
        assert QP_PLACEHOLDER is not None
        # brak pliku -> czytelny błąd, bez crasha; przycisk wraca do stanu
        tab._video_paths = [str(tmp_path / "nie_istnieje.MP4")]
        tab._on_analyze_qp()
        assert "Nie udało się odczytać QP" in tab.lbl_qp_result.text()
        assert tab.btn_analyze_qp.text() == "Analiza QP"
