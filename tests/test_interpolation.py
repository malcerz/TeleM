"""Testy interpolacji wartości telemetrycznych (src/telemetry_extract.py).

Weryfikują, że:
- prędkość i dystans są interpolowane LINIOWO (płynnie co klatkę),
- pozostałe pola (HR, moc, kadencja, temperatura, bateria, fit_*) są SCHODKOWE
  (trzymają poprzednią próbkę FIT ~1 s),
- ISO/ekspozycja są schodkowe (dane dyskretne kamery).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.telemetry_extract import (
    interpolate_value,
    interpolate_speed,
    interpolate_distance,
    interpolate_altitude,
    interpolate_iso,
    interpolate_exposure,
)


def _samples(base, values, step_s=1.0):
    return [
        (base + timedelta(seconds=i * step_s), v)
        for i, v in enumerate(values)
    ]


BASE = datetime(2026, 7, 29, 6, 30, 0)


class TestInterpolateValueStep:
    """interpolate_value jest SCHODKOWE (poprzednia wartość do następnej próbki)."""

    def test_midpoint_holds_previous(self):
        """Środek między próbkami 1 s → poprzednia wartość, NIE średnia."""
        samples = _samples(BASE, [100.0, 120.0])  # HR 100 → 120
        mid = BASE + timedelta(seconds=0.5)
        assert interpolate_value(samples, mid) == 100.0

    def test_exact_sample_value(self):
        """Tuż przed następną próbką → nadal poprzednia (schodek)."""
        samples = _samples(BASE, [100.0, 120.0, 140.0])
        assert interpolate_value(samples, BASE + timedelta(seconds=0.99)) == 100.0

    def test_before_first_clamps_to_first(self):
        """Przed pierwszą próbką → wartość pierwszej próbki."""
        samples = _samples(BASE, [100.0, 120.0])
        assert interpolate_value(samples, BASE - timedelta(seconds=5)) == 100.0

    def test_after_last_clamps_to_last(self):
        """Po ostatniej próbce → wartość ostatniej próbki."""
        samples = _samples(BASE, [100.0, 120.0])
        assert interpolate_value(samples, BASE + timedelta(seconds=99)) == 120.0

    def test_empty_returns_zero(self):
        assert interpolate_value([], BASE) == 0.0

    def test_negative_values_preserved(self):
        """Temperatura ujemna nie jest przycinana do 0."""
        samples = _samples(BASE, [-5.0, -1.0])
        assert interpolate_value(samples, BASE + timedelta(seconds=0.5)) == -5.0

    def test_timezone_aware_samples(self):
        """Próbki ze strefą czasową (GPMF) działają z naive target."""
        samples = [
            (BASE.replace(tzinfo=timezone.utc), 100.0),
            (BASE.replace(tzinfo=timezone.utc) + timedelta(seconds=1), 120.0),
        ]
        mid = BASE + timedelta(seconds=0.5)  # naive
        assert interpolate_value(samples, mid) == 100.0


class TestInterpolateSpeed:
    def test_linear(self):
        """Prędkość: interpolacja LINIOWA (płynna co klatkę)."""
        samples = _samples(BASE, [10.0, 20.0])
        mid = BASE + timedelta(seconds=0.5)
        assert interpolate_speed(samples, mid) == pytest.approx(15.0)

    def test_clamped_to_zero(self):
        """Prędkość jest przycinana do 0 (nie może być ujemna)."""
        samples = _samples(BASE, [10.0, -2.0])
        assert interpolate_speed(samples, BASE + timedelta(seconds=1)) == 0.0


class TestInterpolateDistance:
    def test_linear(self):
        """Dystans: interpolacja LINIOWA."""
        samples = _samples(BASE, [0.0, 100.0])
        mid = BASE + timedelta(seconds=0.5)
        assert interpolate_distance(samples, mid) == pytest.approx(50.0)


class TestInterpolateAltitude:
    def test_linear(self):
        samples = _samples(BASE, [50.0, 60.0])
        mid = BASE + timedelta(seconds=0.5)
        assert interpolate_altitude(samples, mid) == pytest.approx(55.0)


class TestDiscreteStepFields:
    """ISO / ekspozycja pozostają schodkowe (dane kamery, wartości dyskretne)."""

    def test_iso_step(self):
        samples = [(BASE, 100), (BASE + timedelta(seconds=1), 200)]
        # 0.5 s → poprzednia wartość (100), a nie 150 (brak interpolacji liniowej)
        assert interpolate_iso(samples, BASE + timedelta(seconds=0.5)) == 100
        # 0.99 s → nadal 100 (schodek do następnej próbki)
        assert interpolate_iso(samples, BASE + timedelta(seconds=0.99)) == 100
        # po ostatniej próbce → ostatnia wartość
        assert interpolate_iso(samples, BASE + timedelta(seconds=2)) == 200

    def test_exposure_step(self):
        samples = [(BASE, 60), (BASE + timedelta(seconds=1), 120)]
        assert interpolate_exposure(samples, BASE + timedelta(seconds=0.5)) == 60
