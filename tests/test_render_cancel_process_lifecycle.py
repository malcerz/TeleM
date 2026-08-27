"""Bounded process/pipe cancellation contracts."""

import threading
import time
import json
import shutil
import subprocess

from src.ffmpeg import streaming


class _FakeProcess:
    def __init__(self, terminate_exits=True):
        self.pid = 12345
        self.returncode = None
        self.stdin = None
        self.terminate_exits = terminate_exits
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if self.terminate_exits:
            self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_cancel_process_uses_bounded_terminate_fallback(monkeypatch):
    proc = _FakeProcess(terminate_exits=False)
    monkeypatch.setattr(streaming.os, "name", "posix")
    outcomes = iter([False, False, True])
    monkeypatch.setattr(streaming, "_wait_process_bounded", lambda *_args: next(outcomes))

    rc = streaming._stop_ffmpeg_process(proc, time.perf_counter())

    assert proc.terminated is True
    assert proc.killed is True
    assert rc == -9


def test_writer_writes_backlog_on_done_and_discards_only_on_explicit_cancel():
    # ETAP 5B contract change: done_event alone means "producer finished
    # submitting" - the writer MUST write everything still queued (this was
    # the normal-EOF tail-loss bug).  Dropping queued frames is reserved for
    # an explicit cancel via the discard_pending event.
    q = streaming.queue.Queue()
    done = threading.Event()
    discard = threading.Event()
    written = []

    class Sink:
        def write(self, value):
            written.append(value)

    q.put(b"pending")
    writer = threading.Thread(
        target=streaming._pipe_writer_thread,
        args=(q, Sink(), done),
    )
    writer.start()
    done.set()
    writer.join(timeout=1.0)
    assert not writer.is_alive()
    assert written == [b"pending"]

    q2 = streaming.queue.Queue()
    written2 = []
    sink2 = Sink()
    sink2.write = lambda v: written2.append(v)
    discard.set()
    q2.put(b"pending")
    writer2 = threading.Thread(
        target=streaming._pipe_writer_thread,
        args=(q2, sink2, done, None, None, None, None, discard),
    )
    writer2.start()
    writer2.join(timeout=1.0)
    assert not writer2.is_alive()
    assert written2 == []


def test_rawvideo_eof_produces_probeable_partial_mp4(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        return
    output = tmp_path / "partial.mp4"
    proc = subprocess.Popen(
        [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", "64x36", "-r", "10", "-i", "pipe:0",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    frame = bytes([20, 80, 160, 255]) * (64 * 36)
    for _ in range(20):
        proc.stdin.write(frame)
    proc.stdin.close()
    assert proc.wait(timeout=10) == 0

    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration:stream=codec_type", "-of", "json", str(output)],
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert probe.returncode == 0
    data = json.loads(probe.stdout)
    assert float(data["format"]["duration"]) > 0
    assert any(s.get("codec_type") == "video" for s in data["streams"])
