from __future__ import annotations

import io
import queue
import threading

from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd, _fps_rational_arg
from src.ffmpeg.streaming import _pipe_writer_thread


class _Pool:
    def __init__(self):
        self.released = []

    def release(self, slot):
        self.released.append(slot)


def _run_writer(write_stream, item, pool=None):
    q = queue.Queue()
    done = threading.Event()
    stats = {
        "first_frame_time": None,
        "last_frame_time": None,
        "frames_written": 0,
        "partial_write_frames": 0,
    }
    q.put(item)
    q.put(None)
    thread = threading.Thread(
        target=_pipe_writer_thread,
        args=(q, write_stream, done, pool, stats, None),
    )
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    return stats


def test_writer_uses_one_memoryview_write_and_releases_slot():
    stream = io.BytesIO()
    pool = _Pool()
    payload = memoryview(bytearray(b"atlas"))
    stats = _run_writer(stream, (7, payload), pool)

    assert stream.getvalue() == b"atlas"
    assert pool.released == [7]
    assert stats["frames_written"] == 1


def test_writer_exception_does_not_hold_slot_or_thread():
    class Broken:
        def write(self, _):
            raise OSError("synthetic writer failure")

    pool = _Pool()
    payload = memoryview(bytearray(b"atlas"))
    _run_writer(Broken(), (11, payload), pool)
    assert pool.released == [11]


# ── ETAP 5B: normal-EOF writer drain contract ────────────────────────────────
def _run_writer_5b(items, done_before_start=False, discard=False, pool=None):
    q = queue.Queue()
    done = threading.Event()
    disc = threading.Event() if discard else None
    if done_before_start:
        done.set()
    if discard:
        disc.set()
    for it in items:
        q.put(it)
    q.put(None)
    stream = io.BytesIO()
    thread = threading.Thread(
        target=_pipe_writer_thread,
        args=(q, stream, done, pool, None, None, None, disc),
    )
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    return stream.getvalue()


def test_writer_writes_full_backlog_when_done_set_with_queued_frames():
    # ETAP 5B primary root cause regression: done_event means 'end of input',
    # NOT 'drop whatever is still queued'.  Pre-fix this wrote 0/5 frames.
    payloads = [memoryview(bytearray(f"f{i}".encode())) for i in range(5)]
    pool = _Pool()
    data = _run_writer_5b([(9 + i, p) for i, p in enumerate(payloads)],
                          done_before_start=True, pool=pool)
    assert data == b"f0f1f2f3f4"
    assert sorted(pool.released) == [9, 10, 11, 12, 13]


def test_sentinel_never_precedes_final_frame_writes():
    # FIFO order: every frame enqueued before the sentinel must be written,
    # in submission order.
    payloads = [memoryview(bytearray(bytes([65 + i]))) for i in range(8)]
    data = _run_writer_5b([(i, p) for i, p in enumerate(payloads)],
                          done_before_start=True)
    assert data == bytes(range(65, 73))


def test_writer_discards_backlog_only_when_discard_pending():
    # Cancel semantics stay intact: explicit discard_pending drops queued
    # frames (releasing SHM slots) instead of writing them.
    pool = _Pool()
    payloads = [memoryview(bytearray(b"xyz")) for _ in range(4)]
    data = _run_writer_5b([(5 + i, p) for i, p in enumerate(payloads)],
                          done_before_start=True, discard=True, pool=pool)
    assert data == b""
    assert sorted(pool.released) == [5, 6, 7, 8]


# ── ETAP 5B: rational -r contract for the HUD rawvideo input ────────────────
def test_fps_rational_arg_exact_camera_rationals():
    assert _fps_rational_arg(29.97002997002997) == "30000/1001"
    assert _fps_rational_arg(59.94005994005994) == "60000/1001"
    assert _fps_rational_arg(23.976023976023978) == "24000/1001"
    assert _fps_rational_arg(30.0) == "30"
    assert _fps_rational_arg(25.0) == "25"
    assert _fps_rational_arg(60.0) == "60"


def test_stream_cmd_declares_rational_hud_rate_for_ntsc_source():
    # The HUD rawvideo input rate must be declared on the same PTS grid as a
    # 30000/1001 base stream, otherwise overlay shortest=1 drops the final
    # frame (209/210 tail loss reproduced in ETAP 5B PoC).
    cmd, _fc = _build_stream_ffmpeg_cmd(
        "ffmpeg", ["-i", "in.mp4"], "out.mp4",
        generation_fps=29.97002997002997, encoder="cpu",
        overlay_w=1280, overlay_h=720,
    )
    i = cmd.index("-r")
    assert cmd[i + 1] == "30000/1001"

