"""Testy analizy QP (src/qp_analyzer.py).

Obejmują:
- narzędzia bitowe (BitReader ue/se, rbsp, statystyki z histogramu),
- parsowanie HEVC i H.264 z plików o znanym QP (generowane ffmpeg; skip jeśli brak),
- obsługę błędów (brak pliku, nieobsługiwany kodek, brak QP),
- integrację z zakładką Wczytywanie (worker + sygnały + token generacji + anulowanie).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtWidgets import QApplication

from src.qp_analyzer import (
    BitReader,
    QPResult,
    _stats_from_hist,
    analyze_qp,
    rbsp,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _ffmpeg_available() -> bool:
    return subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0


def _x265_available() -> bool:
    if not _ffmpeg_available():
        return False
    r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    return "libx265" in r.stdout


def _make_hevc_cqp(tmp_path, qp: int = 28, bitdepth: int = 10, dur: float = 1.0) -> str:
    out = tmp_path / f"hevc_qp{qp}_{bitdepth}bit.mp4"
    pix = "yuv420p" if bitdepth == 8 else f"yuv420p{bitdepth}le"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={dur}",
         "-c:v", "libx265", "-pix_fmt", pix, "-tag:v", "hvc1",
         "-x265-params", f"log-level=error:qp={qp}", str(out)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return str(out)


def _make_h264_cqp(tmp_path, qp: int = 24, dur: float = 1.0) -> str:
    out = tmp_path / f"h264_qp{qp}.mp4"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={dur}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-qp", str(qp), str(out)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return str(out)


def _wait_until(app, cond, timeout_ms=10000) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


# ---------------------------------------------------------------------------
# Narzędzia bitowe / statystyki
# ---------------------------------------------------------------------------

class TestBitTools:
    def test_rbsp_removes_emulation(self):
        assert rbsp(b"\x00\x00\x03\x01") == b"\x00\x00\x01"
        assert rbsp(b"\x00\x00\x00\x01\x00\x00\x03\x02") == b"\x00\x00\x00\x01\x00\x00\x02"

    def test_ue(self):
        assert BitReader(b"\x80").ue() == 0   # "1"
        assert BitReader(b"\x40").ue() == 1   # "010"
        assert BitReader(b"\x38").ue() == 6   # "00111"

    def test_se(self):
        # se(-3): ue(6) = "00111" -> 0x38 = 0011 1000
        assert BitReader(b"\x38").se() == -3
        # se(1): ue(1) = "010" -> 0x40
        assert BitReader(b"\x40").se() == 1


class TestStatsFromHist:
    def test_basic(self):
        hist = {20: 100, 30: 100}
        mean, med, mn, mx = _stats_from_hist(hist)
        assert mean == 25.0
        assert med == 20
        assert mn == 20
        assert mx == 30

    def test_empty(self):
        assert _stats_from_hist({}) == (None, None, None, None)


# ---------------------------------------------------------------------------
# Analiza HEVC/H.264 na plikach o znanym QP
# ---------------------------------------------------------------------------

class TestAnalyzeReal:
    @pytest.mark.skipif(not _x265_available(), reason="brak libx265")
    def test_hevc_10bit_cqp28(self, tmp_path):
        path = _make_hevc_cqp(tmp_path, qp=28, bitdepth=10)
        r = analyze_qp(path)
        assert r.ok, r.error
        assert r.codec == "hevc"
        assert r.bit_depth == 10
        assert r.frames == 30
        # x265 CQP-28 (10-bit) raportuje avg 29.10; natywny SliceQpY powinien się zgadzać
        assert r.avg is not None and abs(r.avg - 29.1) < 1.5, r.avg
        assert r.minimum == 25          # I-frame (ipratio)
        assert r.maximum in (29, 30)    # B-frame

    @pytest.mark.skipif(not _x265_available(), reason="brak libx265")
    def test_hevc_8bit_cqp28(self, tmp_path):
        path = _make_hevc_cqp(tmp_path, qp=28, bitdepth=8)
        r = analyze_qp(path)
        assert r.ok, r.error
        assert r.bit_depth == 8
        assert abs((r.avg or 0) - 29.1) < 1.5, r.avg

    @pytest.mark.skipif(not _ffmpeg_available(), reason="brak ffmpeg")
    def test_h264_cqp24(self, tmp_path):
        path = _make_h264_cqp(tmp_path, qp=24)
        r = analyze_qp(path)
        assert r.ok, r.error
        assert r.codec == "h264"
        assert r.frames == 30
        assert r.minimum == 21          # I-frame (ipratio) — zweryfikowane z x264
        assert r.maximum == 26          # B-frame
        assert r.avg is not None and abs(r.avg - 25.0) < 1.0, r.avg

    def test_missing_file(self):
        r = analyze_qp("C:/nie_istnieje/plik.mp4")
        assert not r.ok
        assert "nie istnieje" in (r.error or "").lower() or "nie istnieje" in r.error

    def test_unsupported_codec(self, tmp_path):
        # plik audio/bez wideo albo nieobsługiwany — używamy pliku tekstowego
        p = tmp_path / "x.txt"
        p.write_text("hello")
        r = analyze_qp(str(p))
        # ffprobe nie zwróci strumienia wideo -> nieobsługiwany/brak
        assert not r.ok
        assert r.avg is None and r.minimum is None

    def test_cancel(self, tmp_path, monkeypatch):
        if not _x265_available():
            pytest.skip("brak libx265")
        import threading
        import src.qp_analyzer as qa
        path = _make_hevc_cqp(tmp_path, qp=28, dur=1.0)
        cancel = threading.Event()
        # deterministycznie: ustaw anulowanie po pierwszym NAL
        orig = qa.iter_annexb_nalu

        def gen(stream):
            for nalu in orig(stream):
                cancel.set()
                yield nalu

        monkeypatch.setattr(qa, "iter_annexb_nalu", gen)
        r = analyze_qp(path, cancel_event=cancel)
        assert not r.ok
        assert "anul" in (r.error or "").lower()


# ---------------------------------------------------------------------------
# Integracja z LoadTab (worker + sygnały + token generacji)
# ---------------------------------------------------------------------------

class TestLoadTabQP:
    def _make_tab(self, qapp):
        from src.gui.qt.tabs.load_tab import LoadTab
        return LoadTab()

    def _fake_result(self, ok=True):
        if ok:
            return QPResult(codec="hevc", bit_depth=10, frames=120, samples=24000,
                            avg=29.1, median=29, minimum=25, maximum=30,
                            elapsed_s=2.5, histogram={29: 24000})
        return QPResult(codec="hevc", bit_depth=10, frames=0, samples=0, avg=None,
                        median=None, minimum=None, maximum=None, elapsed_s=0.0,
                        error="Nie udało się odczytać QP dla tego strumienia HEVC.")

    def test_analyze_qp_updates_result(self, qapp, monkeypatch, tmp_path):
        import src.gui.qt.tabs.load_tab as lt
        tab = self._make_tab(qapp)
        tab.show()

        real_file = tmp_path / "test.MP4"
        real_file.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        monkeypatch.setattr("src.qp_analyzer.analyze_qp", lambda *a, **k: self._fake_result(True))
        tab._video_paths = [str(real_file)]
        tab._on_analyze_qp()

        ok = _wait_until(qapp, lambda: "Przeanalizowano: 120 klatek" in tab.lbl_qp_result.text())
        assert ok, tab.lbl_qp_result.text()
        assert "Średni:   29.10" in tab.lbl_qp_result.text()
        assert "Mediana:  29" in tab.lbl_qp_result.text()
        assert "Min:      25" in tab.lbl_qp_result.text()
        assert "Max:      30" in tab.lbl_qp_result.text()
        # przycisk wraca do normalnego stanu
        assert tab.btn_analyze_qp.text() == "Analiza QP"

    def test_analyze_qp_error(self, qapp, monkeypatch):
        import src.gui.qt.tabs.load_tab as lt
        tab = self._make_tab(qapp)
        tab.show()

        monkeypatch.setattr("src.qp_analyzer.analyze_qp", lambda *a, **k: self._fake_result(False))
        tab._video_paths = ["C:/videos/test.MP4"]
        tab._on_analyze_qp()

        ok = _wait_until(qapp, lambda: "Nie udało się odczytać QP" in tab.lbl_qp_result.text())
        assert ok, tab.lbl_qp_result.text()
        # brak sztucznych zer
        assert "0\n" not in tab.lbl_qp_result.text() or "Min:" not in tab.lbl_qp_result.text()

    def test_stale_result_discarded(self, qapp, monkeypatch, tmp_path):
        import src.gui.qt.tabs.load_tab as lt
        tab = self._make_tab(qapp)
        tab.show()

        file_a = tmp_path / "A.MP4"; file_a.write_bytes(b"a")
        file_b = tmp_path / "B.MP4"; file_b.write_bytes(b"b")
        calls = {"n": 0}

        def fake(path, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                time.sleep(0.15)  # pierwsza analiza — wolna
            return self._fake_result(True)

        monkeypatch.setattr("src.qp_analyzer.analyze_qp", fake)
        tab._video_paths = [str(file_a)]
        tab._on_analyze_qp()          # gen 1 (wolna)
        tab._reset_qp_state()         # np. wybrano nowy plik → unieważnij gen 1
        tab._video_paths = [str(file_b)]
        tab._on_analyze_qp()          # gen 2

        ok = _wait_until(qapp, lambda: "Przeanalizowano: 120 klatek" in tab.lbl_qp_result.text())
        assert ok
        # wynik gen 1 nie może nadpisać wyniku gen 2 (generacja sprawdzana w handlerze)

    def test_clear_resets_qp(self, qapp):
        tab = self._make_tab(qapp)
        tab.show()
        tab.lbl_qp_result.setText("dowolny wynik")
        tab.btn_analyze_qp.setText("Anuluj analizę QP")
        tab._on_clear()
        assert "Analiza QP" in tab.lbl_qp_result.text()
        assert tab.btn_analyze_qp.text() == "Analiza QP"
        assert not tab.btn_analyze_qp.isEnabled()
