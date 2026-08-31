"""Visible production MainWindow + MPV multi-file preview validation."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
from src.gui.qt.signals import get_signals


VIDEO_ROOT = Path(r"C:\_DEV\TeleM\Video")
PATHS = [VIDEO_ROOT / f"GX01011{number}.MP4" for number in (4, 5, 6)]


def wait_for(app, predicate, timeout_s: float, label: str) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            print(f"PASS|{label}", flush=True)
            return True
        time.sleep(0.02)
    print(f"FAIL|{label}", flush=True)
    return False


def main() -> int:
    app = QApplication.instance() or QApplication([])
    controller = AppController()
    window = MainWindow()
    window.set_controller(controller)
    window.showMaximized()
    if controller.mpv_player is None:
        print("FAIL|mpv_unavailable", flush=True)
        return 1
    get_signals().sig_files_selected.emit(
        [str(path) for path in PATHS], "",
        str(VIDEO_ROOT / "GX010114_116.fit"),
    )
    if not wait_for(
        app,
        lambda: controller.video_timeline is not None
        and controller.video_timeline.clip_count == 3
        and bool(controller.telemetry.fit_data),
        45.0, "real_project_loaded",
    ):
        return 1
    timeline = controller.video_timeline
    expected_initial_source = str(PATHS[0]).lower()
    if not wait_for(
        app,
        lambda: isinstance(getattr(controller, "_preview_canonical_state", None), dict)
        and str(controller._preview_canonical_state.get("source_path", "")).lower()
        == expected_initial_source
        and controller._preview_canonical_state.get("hud_layer_count") == 1,
        20.0, "initial_preview_settled",
    ):
        return 1
    time.sleep(0.5)
    app.processEvents()

    points = [
        timeline.clips[0].global_end_s - 1.0,
        timeline.clips[1].global_start_s + 1.0,
        timeline.clips[2].global_start_s + 1.0,
        timeline.clips[1].global_start_s + 1.0,
        timeline.clips[0].global_end_s - 1.0,
    ]
    for sequence, global_time in enumerate(points):
        expected = timeline.global_to_clip(global_time)[0]
        controller._on_seek_changed(global_time)
        if not wait_for(
            app,
            lambda: getattr(controller, "_active_preview_clip_index", None) == expected
            and isinstance(getattr(controller, "_preview_canonical_state", None), dict)
            and controller._preview_canonical_state.get("hud_layer_count") == 1
            and abs(
                float(controller._preview_canonical_state.get("global_time", -1.0))
                - global_time
            ) < 0.20
            and controller._preview_canonical_state.get("accepted") is True,
            10.0, f"mpv_seek_{sequence}_clip_{expected}",
        ):
            print("DIAG|active=" + repr(getattr(controller, "_active_preview_clip_index", None)))
            print("DIAG|state=" + json.dumps(
                getattr(controller, "_preview_canonical_state", None),
                default=str, sort_keys=True,
            ))
            return 1
        time.sleep(0.35)
        app.processEvents()
        print("STATE|" + json.dumps(
            controller._preview_canonical_state, default=str, sort_keys=True,
        ), flush=True)
        app.primaryScreen().grabWindow(0).save(str(
            Path(__file__).resolve().parent
            / f"qt_mpv_seek_{sequence}_clip_{expected}.png"
        ))

    # Active PLAY through both real source boundaries.
    controller._on_seek_changed(timeline.clips[0].global_end_s - 0.75)
    controller._on_playback_start()
    if not wait_for(
        app, lambda: controller._active_preview_clip_index == 1,
        12.0, "mpv_play_014_to_015",
    ):
        return 1
    controller._on_seek_changed(timeline.clips[1].global_end_s - 0.75)
    controller._on_playback_start()
    if not wait_for(
        app, lambda: controller._active_preview_clip_index == 2,
        12.0, "mpv_play_015_to_016",
    ):
        return 1

    controller._on_playback_stop()
    controller._comp_worker_running = False
    window.close()
    print("PASS|visible_mpv_preview_complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
