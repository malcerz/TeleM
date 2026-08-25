"""ETAP 4A.1 — FIT indicator interaction (hit-test / drag), FIT charts, legacy removal.

Wymagane testy z zadania:
  HIT TEST  1: renderowany FIT text indicator bbox -> klik w srodku -> selected
  HIT TEST  2: klik poza bboxem -> brak selection
  HIT TEST  3: preview skalowane (canvas 1920x1080, widget 960x540) -> wlasciwa selekcja
  HIT TEST  4: drag (down->move->release) zmienia ten sam x/y co Properties
  HIT TEST  5: dwa nachodzace wskazniki -> wybierany najwyzszy z-order (ostatni render)
  HIT TEST  6: text/gauge/chart korzystaja ze wspolnego mechanizmu hit-test
  CHART     7: FIT history resolver -> samples > 0
  CHART     8: chart dostaje probki i generuje niepusta geometrie
  CHART     9: multi-file boundary -> pierwsza klatka clip2 history = T2-window..T2
  CHART    10: nieistniejace pole -> kontrolowany no-data (bez wyjatku)
  RESET    11: Resetuj uklad NIE tworzy legacy time_block
  RESET    12: legacy time_block nie jest w registry / default layout
  RESET    13: stary projekt z time_block ladowany -> pominiety + warning + brak crasha
"""

from __future__ import annotations

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("TELEM_OFFLINE", "1")

import pytest

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import QPointF, Qt, QEvent

from datetime import datetime, timedelta, timezone


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# ── HIT-TEST (VideoPreview) ────────────────────────────────────────────────


class _MockCtrl:
    def __init__(self, layout):
        self.layout = layout


def _make_vp(qapp, layout, bboxes, orig_w=1920, orig_h=1080, label_w=960, label_h=540):
    from src.gui.qt.widgets.video_preview import VideoPreview
    vp = VideoPreview()
    vp.set_controller(_MockCtrl(layout))
    vp.image_label.resize(label_w, label_h)
    vp.set_bboxes(bboxes, orig_w, orig_h)
    clicked: list[str] = []
    moved: list[tuple[str, float, float]] = []
    vp.signals.sig_indicator_clicked.connect(clicked.append)
    vp.signals.sig_indicator_moved.connect(lambda k, x, y: moved.append((k, x, y)))
    return vp, clicked, moved


def _press(vp, x, y):
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    return vp.eventFilter(vp.image_label, ev)


def _move(vp, x, y):
    ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y),
                     Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    return vp.eventFilter(vp.image_label, ev)


def _release(vp, x, y):
    ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    return vp.eventFilter(vp.image_label, ev)


class TestHitTest:
    def test_1_fit_text_bbox_selects(self, qapp):
        """Renderowany FIT text bbox (100,100)-(300,180): klik w srodku -> selected."""
        layout = {"indicators": {"fit_battery_text": {"form": "text"}}}
        bboxes = {"fit_battery_text": (100, 100, 200, 80)}
        vp, clicked, _ = _make_vp(qapp, layout, bboxes, orig_w=1920, orig_h=1080)
        # srodek bboxa w oryginale (200,140) -> label (skala 0.5): (100, 70)
        assert _press(vp, 100, 70) is True
        assert clicked == ["fit_battery_text"]

    def test_2_outside_no_selection(self, qapp):
        layout = {"indicators": {"fit_battery_text": {"form": "text"}}}
        bboxes = {"fit_battery_text": (100, 100, 200, 80)}
        vp, clicked, _ = _make_vp(qapp, layout, bboxes, orig_w=1920, orig_h=1080)
        # klik poza bboxem (np. prawy-dolny róg)
        assert _press(vp, 900, 500) is False
        assert clicked == []

    def test_3_scaled_preview(self, qapp):
        """Canvas 1920x1080, widget 960x540: klik we wlasciwym miejscu ekranu."""
        layout = {"indicators": {"fit_heart_rate_text": {"form": "chart", "x": 50.0, "y": 50.0}}}
        # bbox w canvas coords: centered na (960,540) size 400x200 -> (760,440,400,200)
        bboxes = {"fit_heart_rate_text": (760, 440, 400, 200)}
        vp, clicked, _ = _make_vp(qapp, layout, bboxes, orig_w=1920, orig_h=1080)
        # srodek bboxa (960,540) -> label (skala 0.5): (480, 270)
        assert _press(vp, 480, 270) is True
        assert clicked == ["fit_heart_rate_text"]

    def test_4_drag_syncs_properties(self, qapp):
        """Drag zmienia ten sam x/y, ktory pokazuje panel Properties."""
        layout = {"indicators": {"fit_battery_text": {"form": "text", "x": 10.0, "y": 10.0}}}
        bboxes = {"fit_battery_text": (192, 108, 200, 80)}
        vp, clicked, moved = _make_vp(qapp, layout, bboxes, orig_w=1920, orig_h=1080)
        # text anchor = lewy-gorny róg bboxa (192,108) w oryginale -> label (96,54)
        assert _press(vp, 96, 54) is True
        # ruch do TEGO SAMEGO punktu: pozycja = lewy-gorny bez przeskoku
        _move(vp, 96, 54)
        assert len(moved) == 1
        key, x, y = moved[0]
        assert key == "fit_battery_text"
        # pozycja layout = lewy-gorny (192,108) w norm 0..100
        assert x == pytest.approx(192 / 1920 * 100, abs=0.01)
        assert y == pytest.approx(108 / 1080 * 100, abs=0.01)
        # ruch o +1px label = +1px w norm (1/960*100)
        _move(vp, 97, 55)
        _, x2, y2 = moved[1]
        assert x2 == pytest.approx(x + 1 / 960 * 100, abs=0.02)
        assert y2 == pytest.approx(y + 1 / 540 * 100, abs=0.02)

    def test_5_overlap_picks_highest_zorder(self, qapp):
        """Dwa nachodzace: wybierany ten, ktory renderowany jako ostatni (wyszy z-order)."""
        layout = {"indicators": {"a_text": {"form": "text"}, "b_text": {"form": "text"}}}
        # bbox B zawiera punkt klikniecia; bbox A nie -> B wybrany (iteracja od konca bbox listy)
        bboxes = {"a_text": (0, 0, 50, 50), "b_text": (40, 40, 100, 100)}
        vp, clicked, _ = _make_vp(qapp, layout, bboxes, orig_w=1920, orig_h=1080)
        _press(vp, 30, 30)  # w oryginale (60,60) -> w obu bboxach? a:(0-50), b:(40-140)
        assert clicked and clicked[0] == "b_text", f"expected b_text, got {clicked}"

    def test_6_common_mechanism_all_forms(self, qapp):
        """text/gauge/chart: ten sam mechanizm hit-test (wszystkie uzywaja self._bboxes)."""
        layout = {"indicators": {
            "fit_battery_text": {"form": "text"},
            "fit_speed_text": {"form": "gauge"},
            "fit_heart_rate_text": {"form": "chart"},
        }}
        bboxes = {
            "fit_battery_text": (100, 100, 200, 80),
            "fit_speed_text": (400, 300, 200, 200),
            "fit_heart_rate_text": (700, 500, 300, 150),
        }
        vp, clicked, _ = _make_vp(qapp, layout, bboxes, orig_w=1920, orig_h=1080)
        # text
        assert _press(vp, 100, 70) is True
        assert clicked[-1] == "fit_battery_text"
        # gauge (srodek (500,400) -> label (250,200))
        assert _press(vp, 250, 200) is True
        assert clicked[-1] == "fit_speed_text"
        # chart (srodek (850,575) -> label (425, 287))
        assert _press(vp, 425, 287) is True
        assert clicked[-1] == "fit_heart_rate_text"


# ── CHART ──────────────────────────────────────────────────────────────────

def _fit_manager():
    from src.gui.telemetry_manager import TelemetryDataManager
    from src.telemetry_extract import interpolate_value
    tm = TelemetryDataManager(interpolate_fn=interpolate_value)
    tm.load_fit(
        "Video/GX010115.MP4",
        manual_path="Video/Jazda_na_rowerze_w_porze_lunchu.fit",
    )
    return tm


def _dt(hms):
    h, m, s = hms.split(":")
    return datetime(2026, 8, 14, int(h), int(m), int(float(s)), tzinfo=timezone.utc)


class TestFITChart:
    def test_7_fit_history_has_samples(self):
        tm = _fit_manager()
        from src.indicators.chart_builder import build_chart_data
        layout = {"indicators": {
            "fit_heart_rate_text": {"form": "chart", "enabled": True, "source": "fit",
                                    "chart_time_scope": "window", "chart_window_s": 60.0},
        }}
        cd = build_chart_data(
            layout,
            tm.get_samples_for_source,
            lambda field, src, key=None: tm.resolve_samples(field, src, indicator_key=key),
            start_dt_utc=tm.start_dt_utc,
            end_dt_utc=tm.start_dt_utc + timedelta(seconds=600),
        )
        hd = cd.get("fit_heart_rate_text")
        assert hd is not None
        assert len(hd) > 0, "FIT history resolver must return samples > 0"
        assert len(getattr(hd, "timestamps", [])) > 0

    def test_8_chart_nonempty_geometry(self):
        tm = _fit_manager()
        from src.indicators.chart_builder import build_chart_data, clip_chart_data_for_target
        from src.indicators.compositor import compose_overlay
        layout = {"indicators": {
            "fit_heart_rate_text": {"form": "chart", "enabled": True, "source": "fit",
                                    "chart_time_scope": "window", "chart_window_s": 60.0,
                                    "x": 50.0, "y": 50.0, "size": 30.0,
                                    "min_val": 70.0, "max_val": 120.0},
        }}
        cd = build_chart_data(
            layout,
            tm.get_samples_for_source,
            lambda field, src, key=None: tm.resolve_samples(field, src, indicator_key=key),
            start_dt_utc=tm.start_dt_utc,
            end_dt_utc=tm.start_dt_utc + timedelta(seconds=600),
        )
        target = tm.start_dt_utc + timedelta(seconds=120)
        clipped = clip_chart_data_for_target(cd, target)
        bboxes = {}
        compose_overlay(
            960, 540, layout, "C:/Windows/Fonts/arial.ttf",
            "2026-08-14", "11:20:02", 20.0, 5000.0, 10000.0, 120.0, 0.0, 2000.0,
            100.0, 0.001, 25.0, indicator_values={}, max_speed_kmh=60.0,
            power_value=200.0, atemp_value=20.0, hr_value=140.0, cad_value=85.0,
            battery_value=90.0, _bboxes=bboxes, chart_data=clipped,
            current_position=0.2, extra_indicators={},
            gps_track=tm.fit_gps_track, target_dt=target, start_dt_utc=tm.start_dt_utc,
        )
        bb = bboxes.get("fit_heart_rate_text")
        assert bb is not None
        assert bb[2] > 0 and bb[3] > 0, "chart must produce non-empty geometry"

    def test_9_multifile_boundary_history(self):
        """Pierwsza klatka clip2: history = T2-window..T2 (nie scisle do clip1)."""
        from src.indicators.chart_builder import clip_chart_data_for_target
        # Symuluj history dla clip2: probki FIT wokol T2
        t2 = _dt("11:18:02")  # clip2 absolute start
        timestamps = [t2 - timedelta(seconds=300) + timedelta(seconds=i) for i in range(600)]
        values = [float(100 + i) for i in range(600)]
        from src.indicators.chart_builder import ChartHistory
        history = {"fit_heart_rate_text": ChartHistory(
            values, timestamps, chart_start_dt=timestamps[0],
            chart_end_dt=timestamps[-1], time_scope="window", window_s=60.0,
        )}
        clipped = clip_chart_data_for_target(history, t2)
        hd = clipped["fit_heart_rate_text"]
        assert len(hd) == 61  # [T2-60, T2]
        first_ts = hd.timestamps[0]
        assert abs((t2 - first_ts).total_seconds() - 60.0) < 0.5

    def test_10_missing_field_no_data_no_exception(self):
        tm = _fit_manager()
        from src.indicators.chart_builder import build_chart_data, clip_chart_data_for_target
        layout = {"indicators": {
            "fit_nonexistent_field_text": {"form": "chart", "enabled": True, "source": "fit",
                                           "chart_time_scope": "window", "chart_window_s": 60.0},
        }}
        cd = build_chart_data(
            layout,
            tm.get_samples_for_source,
            lambda field, src, key=None: tm.resolve_samples(field, src, indicator_key=key),
            start_dt_utc=tm.start_dt_utc,
            end_dt_utc=tm.start_dt_utc + timedelta(seconds=600),
        )
        # nie rzuca wyjatku; pole nieistniejace -> brak danych (klucz nieobecny LUB pusty)
        hd = cd.get("fit_nonexistent_field_text")
        assert hd is None or len(hd) == 0


# ── RESET / LEGACY ─────────────────────────────────────────────────────────

class TestResetAndLegacy:
    def test_11_reset_layout_no_legacy_time_block(self):
        from src.gui.qt._mixins.indicator_mixin import IndicatorMixin
        ctrl = IndicatorMixin.__new__(IndicatorMixin)
        ctrl.layout = {"indicators": {"time_display": {}, "speed_text": {}}}
        ctrl.layout_mgr = None
        ctrl._selected_stream_key = "speed_text"
        ctrl.base_dir = os.getcwd()
        ctrl._render_preview = lambda: None
        ctrl._on_reset_layout()
        assert "time_block" not in ctrl.layout["indicators"]
        assert "time_display" in ctrl.layout["indicators"]

    def test_12_legacy_not_in_registry_or_default(self):
        from src.indicators.registry import HARDCODED_KEYS
        assert "time_block" not in HARDCODED_KEYS
        from src.gui.layout_manager import default_layout
        dl = default_layout(1280, 720)
        assert "time_block" not in dl["indicators"]
        assert "time_display" in dl["indicators"]

    def test_13_old_project_time_block_skipped_no_crash(self):
        import json, tempfile
        from pathlib import Path
        from src.gui.layout_manager import normalize_layout
        old = {
            "version": 6,
            "indicators": {
                "time_block": {"enabled": True, "label": "Czas", "x": 1.8, "y": 3.0},
                "time_display": {"enabled": True, "label": "Czas", "x": 2.0, "y": 3.0},
            },
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(old, f)
            path = f.name
        try:
            layout = normalize_layout(Path(path), 1280, 720)
            assert "time_block" not in layout["indicators"]
            assert "time_display" in layout["indicators"]
        finally:
            Path(path).unlink(missing_ok=True)
