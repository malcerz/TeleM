"""Telemetry sync belongs to the project's material, never to a HUD preset."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.telemetry_sync import TelemetrySyncState  # noqa: E402

START = datetime(2026, 10, 5, 4, 29, 0)


@pytest.fixture()
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    return tmp_path


def _wait(app, cond, timeout=20.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    return cond()


def _project(app, tmp_path, n_clips=1):
    """Controller with a loaded FIT and n consecutive clips of 100 s."""
    from telemetry_fit import FitRecords
    from src.gui.qt.controller import AppController
    ctrl = AppController()
    ctrl._render_preview = lambda *a, **k: None
    videos = []
    clips = []
    for i in range(n_clips):
        v = tmp_path / f"DJI_000{i}.MP4"
        if not v.exists():          # reopening must see the same files
            v.write_bytes(b"v" * (i + 1))
        videos.append(v)
        a = START + timedelta(seconds=120 * i)
        clips.append(SimpleNamespace(absolute_start_dt=a, absolute_end_dt=a + timedelta(seconds=100)))
    fit = tmp_path / "ride.fit"
    if not fit.exists():
        fit.write_bytes(b"f")
    recs = FitRecords([{"timestamp": START + timedelta(seconds=s), "heart_rate": 60 + s % 120,
                        "speed": 20.0, "lat": 54.0 + s * 1e-5, "lon": 18.0} for s in range(-60, 120 * n_clips + 60)])
    assert ctrl.telemetry.load_fit(videos[0], START, manual_path=fit, preparsed=recs)
    ctrl.video_paths, ctrl.video_path, ctrl.fit_path = videos, videos[0], fit
    ctrl.video_timeline = SimpleNamespace(clips=clips, clip_count=n_clips)
    return ctrl


def _hr(ctrl, dt):
    for t, v in ctrl.telemetry.fit_data["heart_rate"]:
        if t == dt:
            return v
    return None


def test_saved_preset_has_no_sync_keys(app, appdata, tmp_path):
    ctrl = _project(app, tmp_path)
    ctrl.set_telemetry_sync_state(TelemetrySyncState(offset_s=-3.2, method="manual"))
    _wait(app, lambda: ctrl._sync_worker is None)
    assert ctrl.layout["telemetry_sync_offset_s"] == pytest.approx(-3.2)
    out = tmp_path / "preset.json"
    with patch("src.gui.qt._mixins.preset_mixin.QFileDialog.getSaveFileName", return_value=(str(out), "")):
        ctrl._on_save_preset()
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert not any(k.startswith("telemetry_sync") for k in saved)
    # the default layout is a HUD layout as well
    ctrl.base_dir = tmp_path
    ctrl._save_current_layout_to_default()
    default = json.loads((tmp_path / "def_layout.json").read_text(encoding="utf-8"))
    assert not any(k.startswith("telemetry_sync") for k in default)
    # saving never changes the live offset
    assert ctrl.telemetry.telemetry_sync_offset_s == pytest.approx(-3.2)


def test_loading_old_preset_keeps_current_sync(app, appdata, tmp_path):
    ctrl = _project(app, tmp_path)
    ctrl.set_telemetry_sync_state(TelemetrySyncState(offset_s=1.5, method="smartsync_imu",
                                                     confidence=0.8, confidence_level="high"))
    _wait(app, lambda: ctrl._sync_worker is None)
    probe = START + timedelta(seconds=30)
    hr_before = _hr(ctrl, probe)
    old = dict(ctrl.layout)
    old.update({"telemetry_sync_offset_s": 99.0, "telemetry_sync_method": "manual",
                "telemetry_sync_clip_offsets_s": {"0": 5.0}})
    preset = tmp_path / "old_preset.json"
    preset.write_text(json.dumps(old, default=str), encoding="utf-8")
    with patch("src.gui.qt._mixins.preset_mixin.QFileDialog.getOpenFileName", return_value=(str(preset), "")):
        ctrl._on_load_preset()
    _wait(app, lambda: ctrl._sync_worker is None)
    assert ctrl.telemetry.telemetry_sync_offset_s == pytest.approx(1.5)
    assert ctrl.telemetry.telemetry_sync_clip_offsets_s == {}
    assert ctrl.layout["telemetry_sync_offset_s"] == pytest.approx(1.5)
    assert ctrl.layout["telemetry_sync_method"] == "smartsync_imu"
    assert "telemetry_sync_clip_offsets_s" not in ctrl.layout
    assert _hr(ctrl, probe) == hr_before          # data not re-shifted
    # manual nudges keep working after the preset load
    ctrl.signals.sig_sync_offset_nudge.emit(0.1)
    _wait(app, lambda: ctrl._sync_worker is None and abs(ctrl.telemetry.telemetry_sync_offset_s - 1.6) < 1e-9)
    assert ctrl.telemetry.telemetry_sync_offset_s == pytest.approx(1.6)


def test_reopen_restores_per_clip_offsets(app, appdata, tmp_path):
    ctrl = _project(app, tmp_path, n_clips=3)
    ctrl.set_telemetry_sync_state(TelemetrySyncState(offset_s=2.0, clip_offsets_s={1: 5.0}, method="smartsync_imu"))
    _wait(app, lambda: ctrl._sync_worker is None)
    # Reopen: a fresh controller, telemetry loaded from scratch at offset 0
    ctrl2 = _project(app, tmp_path, n_clips=3)
    ctrl2._reset_telemetry_sync_for_load()
    ctrl2._restore_telemetry_sync_for_project()
    tm = ctrl2.telemetry
    assert tm.telemetry_sync_offset_s == pytest.approx(2.0)
    assert tm.telemetry_sync_clip_offsets_s == {1: 5.0}
    assert ctrl2.layout["telemetry_sync_clip_offsets_s"] == {"1": 5.0}
    # clip 0 shows FIT(t+2), clip 1 shows FIT(t+7), clip 2 shows FIT(t+2)
    for clip, eff in ((0, 2), (1, 7), (2, 2)):
        shown = START + timedelta(seconds=120 * clip + 50)
        assert _hr(ctrl2, shown) == 60 + (120 * clip + 50 + eff) % 120
    # a different material does not inherit it
    (tmp_path / "other").mkdir()
    other = _project(app, tmp_path / "other", n_clips=1)
    other._reset_telemetry_sync_for_load()
    other._restore_telemetry_sync_for_project()
    assert other.telemetry.telemetry_sync_offset_s == 0.0
