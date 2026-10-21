"""HUD_PREPARING tracker: real stages, honest progress, terminates, ordered."""
from __future__ import annotations

from src.gui.hud_preparation import HUD_PREPARING, HUD_READY, HudPreparation


def _tracker(gen=1):
    out = []
    return HudPreparation(gen, out.append), out


def test_active_until_every_stage_finishes_and_errors_do_not_block():
    prep, out = _tracker()
    for key in ("telemetry", "compass", "hud_frame"):
        prep.add(key)
    prep.start("telemetry")
    assert out[-1]["state"] == HUD_PREPARING and out[-1]["stage_key"] == "telemetry"
    prep.finish("telemetry")
    prep.start("compass")
    prep.finish("compass", error="CORI gravity-frame consistency failed")
    assert out[-1]["active"]  # hud_frame still pending
    prep.start("hud_frame")
    prep.finish("hud_frame")
    last = out[-1]
    assert last["state"] == HUD_READY and not last["active"]
    assert last["errors"] == [{"stage": "compass", "label": "Analiza IMU i kalibracja kompasu",
                               "indicator": "Kompas", "error": "CORI gravity-frame consistency failed"}]


def test_progress_is_determinate_only_with_real_counts():
    prep, out = _tracker()
    prep.start("hud_frame")
    assert out[-1]["determinate"] is False and out[-1]["fraction"] is None
    prep.start("map")
    prep.finish("hud_frame")
    prep.progress("map", 12, 48)
    snap = out[-1]
    assert snap["determinate"] and snap["done"] == 12 and snap["total"] == 48 and snap["fraction"] == 0.25


def test_close_publishes_inactive_and_ignores_late_worker_events():
    prep, out = _tracker()
    prep.start("telemetry")
    prep.close()
    assert out[-1]["active"] is False and out[-1]["cancelled"] is True
    n = len(out)
    prep.finish("telemetry")
    prep.start("compass")
    assert len(out) == n


def test_snapshot_order_is_monotonic_across_trackers_of_one_generation():
    first, out1 = _tracker(7)
    first.start("telemetry")
    first.close()
    second, out2 = _tracker(7)  # e.g. late FIT attach
    second.start("fit_sync")
    assert out2[0]["seq"] > out1[-1]["seq"]
