"""Real QMediaPlayer EOF regression check for the 014 -> 015 -> 016 project.

The script intentionally uses the production AppController and QMediaPlayer,
but stubs only expensive HUD painting.  It seeks each real source near EOF and
waits for QMediaPlayer's EndOfMedia signal to drive the production boundary
handler and resume the next source.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time

os.environ["TELEM_MULTIFILE_DEBUG"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
from src.gui.qt.signals import get_signals


VIDEO_ROOT = Path(r"C:\_DEV\TeleM\Video")
FFMPEG = r"C:\tools\ffmpeg.exe"
FFPROBE = r"C:\tools\ffprobe.exe"
PATHS = [VIDEO_ROOT / f"GX01011{n}.MP4" for n in (4, 5, 6)]


def wait_for(app: QApplication, predicate, timeout_s: float, label: str) -> bool:
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
    # Exercise the QMediaPlayer frame-ready/delayed-seek generation path
    # explicitly; MPV has its own synchronous source switch path.
    if controller.mpv_player is not None:
        controller.mpv_player.terminate()
        controller.mpv_player = None
    controller.media_player.setVideoOutput(controller.video_widget)
    get_signals().sig_files_selected.emit(
        [str(path) for path in PATHS], "",
        str(VIDEO_ROOT / "GX010114_116.fit"),
    )
    if not wait_for(
        app,
        lambda: controller.video_timeline is not None
        and controller.video_timeline.clip_count == 3
        and bool(controller.telemetry.fit_data),
        45.0,
        "real_project_loaded",
    ):
        return 1
    timeline = controller.video_timeline
    positions: list[float] = []
    statuses: list[str] = []
    controller.signals.sig_seek_position.connect(
        lambda value: positions.append(float(value))
    )
    controller.media_player.mediaStatusChanged.connect(
        lambda status: statuses.append(str(status))
    )
    controller.media_player.errorOccurred.connect(
        lambda *_: print(f"ERROR|{controller.media_player.errorString()}", flush=True)
    )

    controller.media_player.setSource(QUrl.fromLocalFile(str(PATHS[0])))
    if not wait_for(
        app,
        lambda: controller.media_player.duration() > 0,
        15.0,
        "014_loaded",
    ):
        return 1

    controller._playing = True
    controller.media_player.setPosition(max(0, controller.media_player.duration() - 750))
    controller.media_player.play()
    if not wait_for(
        app,
        lambda: controller._active_preview_clip_index == 1
        and abs(controller.media_player.duration() / 1000.0 - timeline.clips[1].duration_s) < 1.0
        and controller.media_player.position() > 50
        and controller.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState,
        12.0,
        "014_to_015_auto_switch",
    ):
        print(
            f"DIAG|status={controller.media_player.mediaStatus()}|"
            f"state={controller.media_player.playbackState()}|"
            f"duration={controller.media_player.duration()}|"
            f"position={controller.media_player.position()}|"
            f"error={controller.media_player.errorString()}|statuses={statuses}",
            flush=True,
        )
        return 1
    first_boundary_global = timeline.clips[1].global_start_s
    print(
        f"BOUNDARY|014_to_015|global={first_boundary_global:.3f}|"
        f"slider_last={positions[-1] if positions else None}|playing={controller._playing}|"
        f"local={controller.media_player.position() / 1000.0:.3f}",
        flush=True,
    )

    if not wait_for(app, lambda: controller.media_player.duration() > 0, 10.0, "015_loaded"):
        return 1
    controller.media_player.setPosition(max(0, controller.media_player.duration() - 750))
    controller.media_player.play()
    if not wait_for(
        app,
        lambda: controller._active_preview_clip_index == 2
        and abs(controller.media_player.duration() / 1000.0 - timeline.clips[2].duration_s) < 1.0
        and controller.media_player.position() > 50
        and controller.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState,
        12.0,
        "015_to_016_auto_switch",
    ):
        print(
            f"DIAG|status={controller.media_player.mediaStatus()}|"
            f"state={controller.media_player.playbackState()}|"
            f"duration={controller.media_player.duration()}|"
            f"position={controller.media_player.position()}|"
            f"error={controller.media_player.errorString()}|statuses={statuses}",
            flush=True,
        )
        return 1
    second_boundary_global = timeline.clips[2].global_start_s
    print(
        f"BOUNDARY|015_to_016|global={second_boundary_global:.3f}|"
        f"slider_last={positions[-1] if positions else None}|playing={controller._playing}|"
        f"local={controller.media_player.position() / 1000.0:.3f}",
        flush=True,
    )
    print(f"STATUS_COUNT|{len(statuses)}", flush=True)

    # Bidirectional real seek audit.  Wait until the new source generation is
    # accepted and a canonical HUD state is produced for every transition.
    import json
    seek_points = [
        timeline.clips[0].global_end_s - 1.0,
        timeline.clips[1].global_start_s + 1.0,
        timeline.clips[2].global_start_s + 1.0,
        timeline.clips[1].global_start_s + 1.0,
        timeline.clips[0].global_end_s - 1.0,
    ]
    for sequence, global_time in enumerate(seek_points):
        expected_clip = timeline.global_to_clip(global_time)[0]
        controller._render_preview(global_time)
        if not wait_for(
            app,
            lambda: isinstance(
                getattr(controller, "_preview_canonical_state", None), dict
            )
            and controller._preview_canonical_state.get("clip_index") == expected_clip
            and controller._preview_canonical_state.get("accepted") is True
            and controller._preview_canonical_state.get("hud_layer_count") == 1,
            12.0,
            f"seek_{sequence}_clip_{expected_clip}",
        ):
            return 1
        print(
            "STATE|" + json.dumps(
                controller._preview_canonical_state,
                default=str, sort_keys=True,
            ),
            flush=True,
        )
        window.grab().save(str(
            Path(__file__).resolve().parent
            / f"qt_multifile_seek_{sequence}_clip_{expected_clip}.png"
        ))
    controller._on_playback_stop()
    controller._comp_worker_running = False
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
