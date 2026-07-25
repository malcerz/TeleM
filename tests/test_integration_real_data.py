"""Integration tests using real telemetry data files (FIT, JSON).

These tests require the `video/` directory with sample files.
They are skipped automatically if the files are not present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Paths to real test data
VIDEO_DIR = Path(__file__).resolve().parent.parent / "video"
FIT_FILE = VIDEO_DIR / "Popołudniowa_jazda_na_rowerze.fit"
JSON_FILE = VIDEO_DIR / "GX020530.json"

# ---- Fixtures for loading the main module ----


@pytest.fixture(scope="session")
def telemain():
    """Load the main TeleMGP0.16.9 module via importlib (dot in filename)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "telem_main",
        Path(__file__).resolve().parent.parent / "TeleMGP0.16.9.py",
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---- FIT Tests ----


@pytest.mark.skipif(not FIT_FILE.exists(), reason=f"FIT file not found: {FIT_FILE}")
class TestFitRealData:
    """Integration tests with the real Garmin FIT file."""

    def test_parse_fit(self):
        """parse_fit should load real FIT data."""
        from telemetry_fit import parse_fit

        points = parse_fit(FIT_FILE)
        assert points is not None
        assert len(points) > 100
        # Check HR data exists (dict key)
        has_hr = any(p.get("heart_rate") is not None for p in points)
        assert has_hr, "Should have heart rate data"

    def test_parse_fit_first_point(self):
        """First point should have reasonable timestamp."""
        from telemetry_fit import parse_fit

        points = parse_fit(FIT_FILE)
        dt = points[0]["timestamp"]
        assert dt.year == 2026
        assert dt.month == 6
        assert dt.hour == 13  # ~13:03 UTC start time

    def test_parse_fit_has_speed(self):
        """Should have speed data."""
        from telemetry_fit import parse_fit

        points = parse_fit(FIT_FILE)
        has_speed = any(p.get("speed") is not None for p in points)
        assert has_speed

    def test_parse_fit_has_cadence(self):
        """Should have cadence data."""
        from telemetry_fit import parse_fit

        points = parse_fit(FIT_FILE)
        has_cad = any(p.get("cadence") is not None for p in points)
        assert has_cad

    def test_parse_fit_has_power(self):
        """Should have power data."""
        from telemetry_fit import parse_fit

        points = parse_fit(FIT_FILE)
        has_power = any(p.get("curVpower") is not None for p in points)
        assert has_power

    def test_parse_fit_has_temperature(self):
        """Should have ambient temperature data."""
        from telemetry_fit import parse_fit

        points = parse_fit(FIT_FILE)
        has_atemp = any(p.get("temperature") is not None for p in points)
        assert has_atemp

    def test_sync_fit_to_video(self):
        """sync_fit_to_video should produce sample dict."""
        from telemetry_fit import parse_fit, sync_fit_to_video

        points = parse_fit(FIT_FILE)
        result = sync_fit_to_video(points, points[0]["timestamp"])
        assert result is not None
        assert isinstance(result, dict)
        assert len(result.get("speed", [])) > 0
        assert len(result.get("heart_rate", [])) > 0
        assert len(result.get("cadence", [])) > 0
        assert len(result.get("curVpower", [])) > 0
        assert len(result.get("temperature", [])) > 0


# ---- JSON (GoPro ExifTool) Tests ----


@pytest.mark.skipif(not JSON_FILE.exists(), reason=f"JSON file not found: {JSON_FILE}")
class TestJsonRealData:
    """Integration tests with the real GoPro ExifTool JSON file."""

    @pytest.fixture
    def records(self, telemain):
        """Load records from the real JSON file."""
        with open(JSON_FILE) as f:
            data = json.load(f)
        return telemain.ensure_records_list(data)

    def test_extract_speed(self, telemain, records):
        """extract_speed_samples should return valid GoPro GPS speed data."""
        speed = telemain.extract_speed_samples(records)
        assert len(speed) > 500
        # Speed should be in km/h (typical GoPro ~10-40 km/h)
        speeds = [s for _, s in speed]
        assert max(speeds) > 5
        assert min(speeds) >= 0

    def test_extract_track(self, telemain, records):
        """extract_track_samples should return cumulative distance."""
        track = telemain.extract_track_samples(records)
        assert len(track) > 500
        # Distance should be cumulative and increasing
        distances = [d for _, d in track]
        assert distances[-1] > distances[0]

    def test_extract_altitude(self, telemain, records):
        """extract_altitude_samples should return altitude in metres."""
        alt = telemain.extract_altitude_samples(records)
        assert len(alt) > 500
        alts = [a for _, a in alt]
        assert max(alts) > 0

    def test_extract_iso(self, telemain, records):
        """extract_iso_samples should return ISO values."""
        iso = telemain.extract_iso_samples(records)
        assert len(iso) > 100
        values = [v for _, v in iso]
        assert all(v > 0 for v in values)

    def test_extract_exposure(self, telemain, records):
        """extract_exposure_samples should return shutter speed values."""
        exp = telemain.extract_exposure_samples(records)
        assert len(exp) > 100
        values = [v for _, v in exp]
        assert all(v > 0 for v in values)

    def test_extract_temperature(self, telemain, records):
        """extract_temperature_samples should return camera temperature."""
        temp = telemain.extract_temperature_samples(records)
        assert len(temp) > 50
        temps = [t for _, t in temp]
        assert max(temps) > 0

    def test_rotation_from_metadata(self, telemain, records):
        """get_rotation_from_metadata should detect 180° (AutoRotation: Down)."""
        rotation = telemain.get_rotation_from_metadata(records)
        assert rotation == 180

    def test_start_dt(self, telemain, records):
        """find_gps_anchor should return the video start time."""
        anchor = telemain.find_gps_anchor(records)
        assert anchor is not None
        assert anchor.year == 2026

    def test_haversine_m(self, telemain):
        """haversine_m should compute reasonable distances."""
        dist = telemain.haversine_m(54.0, 18.0, 54.001, 18.001)
        assert 100 < dist < 200  # ~130m for these coordinates


# ---- Rendering tests (optional, requires PIL) ----


@pytest.mark.skipif(
    not JSON_FILE.exists(), reason=f"JSON file not found: {JSON_FILE}"
)
class TestPreviewWithRealData:
    """Test that overlay rendering produces valid images with real data."""

    def test_render_preview_returns_image(self, telemain, tmp_path):
        """render_preview should produce a valid PIL Image."""
        from PIL import Image

        with open(JSON_FILE) as f:
            data = json.load(f)
        records = telemain.ensure_records_list(data)

        # Load layout
        layout = telemain.default_layout(1920, 1080)
        font_path = "Arial"

        # Get real speed data
        speed = telemain.extract_speed_samples(records)
        track = telemain.extract_track_samples(records)
        alt = telemain.extract_altitude_samples(records)

        # Take a sample value
        speed_val = speed[0][1] if speed else 0.0
        dist_val = track[-1][1] if track else 0.0
        alt_val = alt[0][1] if alt else 0.0

        # Create a test source image
        src = Image.new("RGB", (1920, 1080), (30, 30, 30))

        # Render
        result = telemain.render_preview(
            src,
            layout,
            font_path,
            "2026-06-19",
            "14:04:40",
            speed_val,
            dist_val,
            dist_val,
            alt_val,
            0,
            100,
            100,
            500,
            25,
            indicator_values={},
            max_speed_kmh=speed_val,
        )

        assert result is not None
        assert result.size == (1920, 1080)
        # Should not be all-black (overlay was rendered)
        pixels = list(result.getdata())
        unique = set(pixels[:100])  # Check first 100 pixels
        assert len(unique) > 1 or max(pixels[0]) > 30  # Has some overlay content
