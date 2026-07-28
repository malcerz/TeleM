"""Testy end-to-end dla funkcji wycinania fragmentów (A-B → ✂).

Weryfikują: SeekBar.set_range → VideoPreview._on_cut → Controller.add_cut_region
→ sygnały → SeekBar.set_cut_regions (skrócona oś czasu).
"""

from __future__ import annotations

import sys
import os
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def ctrl():
    class Mock:
        def __init__(self):
            self._cut_regions: list[tuple[float, float]] = []
        def add_cut_region(self, a, b):
            if b > a:
                self._cut_regions.append((a, b))
                self._cut_regions.sort()
        def undo_cut_region(self):
            if self._cut_regions:
                self._cut_regions.pop()
        def clear_cut_regions(self):
            self._cut_regions.clear()
    return Mock()


@pytest.fixture
def vp(qapp, ctrl):
    from src.gui.qt.widgets.video_preview import VideoPreview
    vp = VideoPreview()
    vp.set_controller(ctrl)
    return vp


# ---------------------------------------------------------------------------
# Testy SeekBar
# ---------------------------------------------------------------------------

class TestSeekBar:
    def test_default_range(self, qapp):
        from src.gui.qt.widgets.seek_bar import SeekBar
        sb = SeekBar()
        a, b = sb.get_range()
        assert a == 0.0
        assert b == 100.0

    def test_range_after_duration(self, qapp):
        from src.gui.qt.widgets.seek_bar import SeekBar
        sb = SeekBar()
        sb.set_duration(45.0)
        a, b = sb.get_range()
        assert a == 0.0
        assert b == 45.0

    def test_default_range_is_not_a_cut_selection(self, qapp):
        from src.gui.qt.widgets.seek_bar import SeekBar
        sb = SeekBar()
        sb.set_duration(60.0)
        assert not sb.has_selection()

    def test_set_range_ordered(self, qapp):
        from src.gui.qt.widgets.seek_bar import SeekBar
        sb = SeekBar()
        sb.set_duration(60.0)
        sb.set_range(50.0, 5.0)
        a, b = sb.get_range()
        assert a == 5.0
        assert b == 50.0

    def test_cut_regions_stored(self, qapp):
        from src.gui.qt.widgets.seek_bar import SeekBar
        sb = SeekBar()
        sb.set_duration(60.0)
        sb.set_cut_regions([(10.0, 20.0), (40.0, 50.0)])
        assert len(sb._cut_regions) == 2
        assert sb._cut_regions[0] == (10.0, 20.0)
        assert sb.get_range() == (0.0, 40.0)


# ---------------------------------------------------------------------------
# Testy flow: przeciągnij A-B → kliknij ✂
# ---------------------------------------------------------------------------

class TestCutFlow:
    def test_cut_adds_region(self, vp, ctrl):
        vp.on_duration_ready(60.0)
        vp.seek_bar.set_range(10.0, 25.0)
        vp._on_cut()
        assert len(ctrl._cut_regions) == 1
        assert ctrl._cut_regions[0] == (10.0, 25.0)

    def test_cut_resets_ab_range(self, vp, ctrl):
        """Po cięciu A-B wraca do pełnego zakresu."""
        vp.on_duration_ready(60.0)
        vp.seek_bar.set_range(10.0, 25.0)
        vp._on_cut()
        a, b = vp.seek_bar.get_range()
        assert a == 0.0
        assert b == 60.0

    def test_tiny_range_ignored(self, vp, ctrl):
        vp.on_duration_ready(60.0)
        vp.seek_bar.set_range(10.0, 10.05)
        vp._on_cut()
        assert len(ctrl._cut_regions) == 0

    def test_no_controller_no_crash(self, vp, ctrl):
        vp._controller = None
        vp.on_duration_ready(60.0)
        vp.seek_bar.set_range(5.0, 15.0)
        vp._on_cut()  # nie powinno crashować
        # controller nie dostał danych, bo vp._controller = None
        assert len(ctrl._cut_regions) == 0

    def test_multiple_cuts(self, vp, ctrl):
        vp.on_duration_ready(60.0)
        vp.seek_bar.set_range(10.0, 20.0)
        vp._on_cut()
        vp.seek_bar.set_range(30.0, 40.0)
        vp._on_cut()
        assert len(ctrl._cut_regions) == 2
        assert ctrl._cut_regions == [(10.0, 20.0), (30.0, 40.0)]

    def test_second_cut_maps_from_shortened_timeline(self, vp, ctrl):
        vp.on_duration_ready(60.0)
        ctrl.add_cut_region(10.0, 20.0)
        vp._on_cut_region_changed()

        vp.seek_bar.set_range(20.0, 30.0)
        vp._on_cut()

        assert ctrl._cut_regions == [(10.0, 20.0), (30.0, 40.0)]

    def test_undo_removes_last(self, vp, ctrl):
        vp.on_duration_ready(60.0)
        vp.seek_bar.set_range(10.0, 20.0)
        vp._on_cut()
        vp.seek_bar.set_range(30.0, 40.0)
        vp._on_cut()
        assert len(ctrl._cut_regions) == 2
        vp._on_undo_cut()
        assert ctrl._cut_regions == [(10.0, 20.0)]

    def test_restore_clears_all(self, vp, ctrl):
        vp.on_duration_ready(60.0)
        for r in [(5, 10), (20, 25)]:
            vp.seek_bar.set_range(*r)
            vp._on_cut()
        assert len(ctrl._cut_regions) == 2
        vp._on_restore_cut()
        assert len(ctrl._cut_regions) == 0

    def test_cut_region_visible_on_seekbar(self, vp, ctrl):
        """Po _on_cut + _on_cut_region_changed, seek_bar ma cięcia."""
        vp.on_duration_ready(60.0)
        vp.seek_bar.set_range(10.0, 20.0)
        vp._on_cut()
        vp._on_cut_region_changed()
        assert len(vp.seek_bar._cut_regions) == 1
        assert vp.seek_bar._cut_regions[0] == (10.0, 20.0)

    def test_cut_btn_click(self, vp, ctrl):
        """Kliknięcie myszą na ✂ wyzwala _on_cut."""
        vp.on_duration_ready(60.0)
        vp.seek_bar.set_range(15.0, 35.0)
        QTest.mouseClick(vp.cut_btn, Qt.LeftButton)
        assert len(ctrl._cut_regions) == 1
        assert ctrl._cut_regions[0] == (15.0, 35.0)

    def test_undo_btn_click(self, vp, ctrl):
        vp.on_duration_ready(60.0)
        vp.seek_bar.set_range(10.0, 20.0)
        vp._on_cut()
        assert len(ctrl._cut_regions) == 1
        QTest.mouseClick(vp.undo_cut_btn, Qt.LeftButton)
        assert len(ctrl._cut_regions) == 0

    def test_restore_btn_click(self, vp, ctrl):
        vp.on_duration_ready(60.0)
        for r in [(5, 10), (20, 25)]:
            vp.seek_bar.set_range(*r)
            vp._on_cut()
        assert len(ctrl._cut_regions) == 2
        QTest.mouseClick(vp.restore_cut_btn, Qt.LeftButton)
        assert len(ctrl._cut_regions) == 0


# ---------------------------------------------------------------------------
# Testy skipowania pozycji
# ---------------------------------------------------------------------------

class TestSkipCutRegions:
    def test_skip_forward(self):
        """Pozycja wewnątrz cięcia → przeskakuje na koniec."""
        cuts = [(10.0, 20.0), (30.0, 40.0)]

        def skip(s, fwd=True):
            for cs, ce in cuts:
                m = 0.1
                if fwd and cs - m <= s <= ce:
                    return ce + m
            return s

        assert skip(5.0) == 5.0
        assert skip(15.0) == 20.1
        assert skip(25.0) == 25.0
        assert skip(35.0) == 40.1

    def test_skip_multiple_cuts(self):
        """Dwa cięcia, drugie też pomija."""
        cuts = [(5.0, 10.0), (20.0, 25.0)]

        def skip(s, fwd=True):
            for cs, ce in cuts:
                m = 0.1
                if fwd and cs - m <= s <= ce:
                    return ce + m
            return s

        assert skip(7.0) == 10.1
        assert skip(22.0) == 25.1
        assert skip(15.0) == 15.0

    def test_playback_seek_physically_skips_cut(self, monkeypatch):
        import src.gui.qt.controller as controller_module

        class Player:
            def __init__(self):
                self.positions: list[int] = []

            def setPosition(self, position: int) -> None:
                self.positions.append(position)

        class Signals:
            class SeekPosition:
                def emit(self, _seconds: float) -> None:
                    pass

            sig_seek_position = SeekPosition()

        class Playback:
            _skip_cut_regions = controller_module.AppController._skip_cut_regions

            def __init__(self):
                self._playing = True
                self._playback_pos = 9.95
                self._cut_regions = [(10.0, 20.0)]
                self.fps = 10.0
                self.video_duration_s = 60.0
                self.media_player = Player()
                self.signals = Signals()
                self._playback_step = lambda: None

        monkeypatch.setattr(controller_module, "_QT_MULTIMEDIA_AVAILABLE", True)
        monkeypatch.setattr(
            controller_module.QTimer,
            "singleShot",
            lambda _interval, _callback: None,
        )

        playback = Playback()
        controller_module.AppController._playback_step(playback)

        assert playback._playback_pos == pytest.approx(20.1)
        assert playback.media_player.positions == [20100]


# ---------------------------------------------------------------------------
# Testy wstrzykiwania cut_regions do layoutu
# ---------------------------------------------------------------------------

class TestLayoutInjection:
    def test_cut_regions_in_layout(self):
        layout = {"indicators": {}, "width": 1920, "height": 1080}
        cuts = [(5.0, 15.0), (30.0, 45.0)]
        layout_with_cuts = dict(layout, cut_regions=list(cuts))
        assert layout_with_cuts["cut_regions"] == cuts
        assert "cut_regions" not in layout

    def test_empty_cuts(self):
        layout = {"indicators": {}}
        cuts: list = []
        layout_with_cuts = dict(layout, cut_regions=list(cuts))
        assert layout_with_cuts["cut_regions"] == []


# ---------------------------------------------------------------------------
# Testy mapowania efektywny <-> oryginalny czas
# ---------------------------------------------------------------------------

class TestTimeMapping:
    """Testy eff_to_orig i orig_to_eff dla SeekBar."""

    def test_no_cuts_identity(self, qapp):
        """Bez cięć: eff==orig (identyczność)."""
        from src.gui.qt.widgets.seek_bar import SeekBar
        sb = SeekBar()
        sb.set_duration(100.0)
        assert sb.eff_to_orig(50.0) == 50.0
        assert sb.orig_to_eff(50.0) == 50.0

    def test_single_cut_mapping(self, qapp):
        """Pojedyncze cięcie (20,30): eff po cięciu przesuwa się o 10."""
        from src.gui.qt.widgets.seek_bar import SeekBar
        sb = SeekBar()
        sb.set_duration(100.0)
        sb.set_cut_regions([(20.0, 30.0)])

        # eff=15 → orig=15 (przed cięciem)
        assert sb.eff_to_orig(15.0) == pytest.approx(15.0)
        # eff=25 → orig=35 (po cięciu 10s)
        assert sb.eff_to_orig(25.0) == pytest.approx(35.0)
        #反向: orig=35 → eff=25
        assert sb.orig_to_eff(35.0) == pytest.approx(25.0)
        # effective duration = 100 - 10 = 90
        assert sb.get_effective_duration() == pytest.approx(90.0)

    def test_multiple_cuts_mapping(self, qapp):
        """Dwa cięcia: (10,15) i (30,40) → eff duration = 75."""
        from src.gui.qt.widgets.seek_bar import SeekBar
        sb = SeekBar()
        sb.set_duration(100.0)
        sb.set_cut_regions([(10.0, 15.0), (30.0, 40.0)])

        # effective duration = 100 - 5 - 10 = 85
        assert sb.get_effective_duration() == pytest.approx(85.0)

        # eff=5 → orig=5 (przed pierwszym cięciem)
        assert sb.eff_to_orig(5.0) == pytest.approx(5.0)
        # eff=10 → orig=15 (na granicy pierwszego cięcia, po 5s = 10s przed cięciem + 0)
        assert sb.eff_to_orig(10.0) == pytest.approx(15.0)
        # eff=15 → orig=20 (po pierwszym cięciu: 5s dodatkowego przesunięcia)
        assert sb.eff_to_orig(15.0) == pytest.approx(20.0)
        # eff=25 → orig=40 (na granicy drugiego cięcia — przeskakuje za nie)
        assert sb.eff_to_orig(25.0) == pytest.approx(40.0)
        # eff=30 → orig=45 (po drugim cięciu: 10s dodatkowego przesunięcia)
        assert sb.eff_to_orig(30.0) == pytest.approx(45.0)

        #反向 tests
        assert sb.orig_to_eff(5.0) == pytest.approx(5.0)
        assert sb.orig_to_eff(20.0) == pytest.approx(15.0)
        assert sb.orig_to_eff(45.0) == pytest.approx(30.0)

    def test_boundary_values(self, qapp):
        """Testy na granicach: 0 i koniec."""
        from src.gui.qt.widgets.seek_bar import SeekBar
        sb = SeekBar()
        sb.set_duration(100.0)
        sb.set_cut_regions([(20.0, 30.0)])

        # eff=0 → orig=0
        assert sb.eff_to_orig(0.0) == pytest.approx(0.0)
        assert sb.orig_to_eff(0.0) == pytest.approx(0.0)

        # eff=90 (koniec) → orig=100 (koniec)
        assert sb.eff_to_orig(90.0) == pytest.approx(100.0)
        assert sb.orig_to_eff(100.0) == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# Uruchamianie
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])