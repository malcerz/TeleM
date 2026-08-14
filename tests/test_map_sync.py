"""Testy synchronizacji pozycji na mapie z czasem.

Weryfikują:
1. ``render_preview`` przekazuje ``target_dt`` do ``compose_overlay`` (naprawa
   przeskakiwania pozycji mapy — bez tego mapa wpada w fallback current_position
   i marker sunie 0→100% trasy w trakcie krótkiego wideo).
2. ``MovingMapRenderer._idx`` poprawnie znajduje pozycję dla czasu wideo
   (z przesuniętym trackiem FIT: start wideo = ~95% trasy, nie 0%).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from PIL import Image


def _fit_track():
    """Symulowany track FIT (przesunięty) — 1 próbka/sek., 60 s."""
    base = datetime(2026, 7, 29, 5, 31, 46)
    track = []
    for i in range(60):
        track.append((base + timedelta(seconds=i), 54.0 + i * 0.0001, 18.0 + i * 0.0001))
    return track


def _layout():
    return {
        "version": 6,
        "global": {"text_outline": 3},
        "custom_texts": [],
        "indicators": {},
    }


class TestRenderPreviewForwardsTargetDt:
    def test_target_dt_passed_to_compose_overlay(self):
        """render_preview przekazuje target_dt do compose_overlay (klucz dla mapy)."""
        from src.indicators import compositor

        captured = {}

        def fake_compose_overlay(w, h, layout, font_path, date_text, time_text,
                                 speed_value, distance_m, *a, **kw):
            captured["target_dt"] = kw.get("target_dt")
            captured["gps_track"] = kw.get("gps_track")
            captured["current_position"] = kw.get("current_position")
            return Image.new("RGBA", (w, h), (0, 0, 0, 0))

        target_dt = datetime(2026, 7, 29, 6, 27, 54, tzinfo=timezone.utc)
        gps = _fit_track()

        with mock.patch.object(compositor, "compose_overlay", fake_compose_overlay):
            img = compositor.render_preview(
                Image.new("RGBA", (320, 180), (0, 0, 0, 0)),
                _layout(), None,
                "2026-07-29", "06:27:54",
                15.0, 1000.0, 2000.0, 20.0, 10.0, 30.0,
                None, None, None,
                gps_track=gps,
                target_dt=target_dt,
                current_position=0.0,
            )
            assert img is not None

        # KLUCZOWE: target_dt MUSI dotrzeć do compose_overlay (nie None)
        assert captured["target_dt"] == target_dt
        assert captured["gps_track"] is gps
        assert captured["current_position"] == 0.0


class TestMovingMapIdx:
    def test_idx_at_video_start_near_end_of_shifted_track(self):
        """Start wideo (06:27:54) po przesunięciu FIT = ~95% trasy, nie 0%."""
        from src.moving_map import MovingMapRenderer

        track = _fit_track()
        renderer = MovingMapRenderer(track, zoom=15)
        # symulacja obliczenia ts w _render_moving_map_indicator (z target_dt aware)
        target_dt = datetime(2026, 7, 29, 6, 27, 54, tzinfo=timezone.utc)
        gps0 = track[0][0]
        target_epoch = target_dt.timestamp()
        gps0_ts = gps0.replace(tzinfo=timezone.utc).timestamp()
        ts = target_epoch - gps0_ts
        idx = renderer._idx(ts)
        # 06:27:54 - 05:31:46 = 3368s; track ma tylko 60s → poza zakresem → koniec
        assert idx == len(track) - 1

    def test_idx_scales_with_time(self):
        """ts=30 (środek 60 s) → indeks ~30."""
        from src.moving_map import MovingMapRenderer

        track = _fit_track()
        renderer = MovingMapRenderer(track, zoom=15)
        assert renderer._idx(30) == 30

    def test_idx_clamps_negative_to_start(self):
        """Ujemne ts (np. błędna strefa czasowa) → clamped do początku (0%)."""
        from src.moving_map import MovingMapRenderer

        renderer = MovingMapRenderer(_fit_track(), zoom=15)
        assert renderer._idx(-100) == 0

    def test_timezone_robust_ts(self):
        """Naive target_dt traktowany jako UTC (nie lokalnie) — ta sama pozycja."""
        from src.moving_map import MovingMapRenderer

        track = _fit_track()
        renderer = MovingMapRenderer(track, zoom=15)
        # aware target
        aware = datetime(2026, 7, 29, 6, 27, 54, tzinfo=timezone.utc)
        gps0 = track[0][0]
        gps0_ts = gps0.replace(tzinfo=timezone.utc).timestamp()
        ts_aware = aware.timestamp() - gps0_ts
        # naive target — NOWA logika normalizuje do UTC
        naive = aware.replace(tzinfo=None)
        target_epoch = naive.replace(tzinfo=timezone.utc).timestamp()
        ts_naive = target_epoch - gps0_ts
        assert ts_naive == ts_aware
        assert renderer._idx(ts_naive) == renderer._idx(ts_aware)


class TestMovingMapInterpPos:
    """_interp_pos: liniowa interpolacja pozycji między próbkami (płynny ruch)."""

    def test_midpoint_between_samples(self):
        """ts=0.5 (między próbką 0 i 1) → środek między pozycjami."""
        from src.moving_map import MovingMapRenderer

        renderer = MovingMapRenderer(_fit_track(), zoom=15)
        x0, y0 = renderer._px_x[0], renderer._px_y[0]
        x1, y1 = renderer._px_x[1], renderer._px_y[1]
        ix, iy = renderer._interp_pos(0.5)
        assert ix == pytest.approx((x0 + x1) / 2, abs=0.5)
        assert iy == pytest.approx((y0 + y1) / 2, abs=0.5)

    def test_exact_sample(self):
        """ts=10 → dokładnie pozycja próbki 10."""
        from src.moving_map import MovingMapRenderer

        renderer = MovingMapRenderer(_fit_track(), zoom=15)
        ix, iy = renderer._interp_pos(10)
        assert ix == pytest.approx(renderer._px_x[10], abs=0.5)
        assert iy == pytest.approx(renderer._px_y[10], abs=0.5)

    def test_smooth_monotonic(self):
        """Ruch między klatkami jest monotoniczny (nie skacze co 1 s)."""
        from src.moving_map import MovingMapRenderer

        renderer = MovingMapRenderer(_fit_track(), zoom=15)
        prev = None
        for k in range(0, 21):
            x, y = renderer._interp_pos(k / 10)  # co 0.1 s
            if prev is not None:
                # pozycja nie może cofać się o więcej niż krok 0.1s
                assert x >= prev[0] - 0.5
            prev = (x, y)

    def test_clamps_before_first_and_after_last(self):
        """Przed startem i po końcu → odpowiednio pierwsza i ostatnia pozycja."""
        from src.moving_map import MovingMapRenderer

        renderer = MovingMapRenderer(_fit_track(), zoom=15)
        ix0, iy0 = renderer._interp_pos(-50)
        assert (ix0, iy0) == (renderer._px_x[0], renderer._px_y[0])
        ixN, iyN = renderer._interp_pos(1e9)
        assert (ixN, iyN) == (renderer._px_x[-1], renderer._px_y[-1])

    def test_render_draws_full_track_no_crash(self):
        """render() rysuje CAŁĄ trasę + marker (offline — szare kafelki, bez wyjątku)."""
        from src.moving_map import MovingMapRenderer

        renderer = MovingMapRenderer(_fit_track(), zoom=15)
        img = renderer.render(0.0, 200, 130, download_missing=False)
        assert img is not None
        assert img.size == (200, 130)
        img2 = renderer.render(30.5, 200, 130, download_missing=False)
        assert img2.size == (200, 130)


class TestMapShape:
    """Kształt mapy: kwadrat (domyślnie) lub okrąg (maska alfa)."""

    def test_square_shape_unchanged(self):
        """Kształt 'square' → obraz bez maski (bez zmian)."""
        from src.indicators.helpers import apply_map_shape

        img = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        out = apply_map_shape(img, "square")
        # kwadrat: rogi są w pełni nieprzezroczyste
        assert out.getpixel((0, 0))[3] == 255
        assert out.getpixel((99, 99))[3] == 255

    def test_round_shape_cuts_corners(self):
        """Kształt 'round' → rogi przezroczyste, środek nieprzezroczysty."""
        from src.indicators.helpers import apply_map_shape

        img = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        out = apply_map_shape(img, "round")
        # róg (1,1) poza okręgiem → alpha 0
        assert out.getpixel((1, 1))[3] == 0
        # środek → alpha 255
        assert out.getpixel((50, 50))[3] == 255

    def test_map_is_square_dimensions(self):
        """Renderer zwraca KWADRATOWY obraz (wsk. mapy woła map_w==map_h)."""
        from src.moving_map import MovingMapRenderer

        renderer = MovingMapRenderer(_fit_track(), zoom=15)
        img = renderer.render(5.0, 200, 200, download_missing=False)
        assert img.size == (200, 200)  # square, nie 200x130


class TestMapPreviewExportParity:
    """Configured map zoom describes one viewport at every render resolution."""

    @pytest.mark.parametrize(
        ("canvas_w", "widget_size", "effective_zoom", "working_size"),
        [
            (960, 173, 14, 173),
            (1920, 346, 15, 346),
            (3840, 691, 16, 692),
        ],
    )
    def test_render_plan_preserves_logical_viewport(
        self, canvas_w, widget_size, effective_zoom, working_size
    ):
        from src.indicators.moving_map import _map_render_plan

        plan = _map_render_plan(canvas_w, widget_size, 14)
        assert plan["effective_zoom"] == effective_zoom
        assert plan["working_size"] == working_size

        # Geographic span is proportional to crop pixels / world-pixel
        # density.  It must stay stable after rounding the widget size.
        span = plan["working_size"] / (2 ** plan["effective_zoom"])
        reference_span = 173 / (2 ** 14)
        assert span == pytest.approx(reference_span, rel=0.003)

    def test_non_power_of_two_scale_uses_residual_resize(self):
        from src.indicators.moving_map import _map_render_plan

        plan = _map_render_plan(1280, 230, 14)
        assert plan["effective_zoom"] == 14
        assert plan["working_size"] == pytest.approx(173, abs=1)
        assert plan["output_resize_scale"] == pytest.approx(4 / 3, rel=0.01)
