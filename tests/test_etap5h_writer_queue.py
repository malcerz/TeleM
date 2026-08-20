from __future__ import annotations

import io
import queue
import threading

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
