"""Hardware-independent contracts plus a real Windows spawn round trip."""
import os
import subprocess
import time
from types import SimpleNamespace

import pytest

from src.ffmpeg import intel_backend, intel_native_exporter, streaming


def test_process_executor_ignores_package_lazy_proxy(monkeypatch):
    import concurrent.futures
    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", object())
    with streaming._RenderExecutor(max_workers=1) as executor:
        assert executor._mp_context.get_start_method() == "spawn"
        assert executor.submit(os.getpid).result(timeout=30) != os.getpid()


def test_qt_background_thread_can_start_real_spawn_worker(tmp_path):
    """Regression: Qt/Shiboken + Python 3.15 leaks the package's lazy export."""
    import sys
    from pathlib import Path
    script = tmp_path / "qt_spawn.py"
    repo = str(Path(__file__).resolve().parents[1])
    script.write_text(
        "import sys, os, threading, multiprocessing\n"
        f"sys.path.insert(0, {repo!r})\n"
        "from PySide6.QtWidgets import QApplication\n"
        "def run():\n"
        " from src.ffmpeg.streaming import _RenderExecutor\n"
        " with _RenderExecutor(max_workers=1) as pool:\n"
        "  assert pool.submit(os.getpid).result(timeout=30) != os.getpid()\n"
        "if __name__ == '__main__':\n"
        " multiprocessing.freeze_support()\n"
        " app = QApplication([])\n"
        " errors = []\n"
        " def target():\n"
        "  try: run()\n"
        "  except BaseException as exc: errors.append(exc)\n"
        " thread = threading.Thread(target=target)\n"
        " thread.start(); thread.join(timeout=40)\n"
        " assert not thread.is_alive()\n"
        " assert not errors, errors\n", encoding="utf-8")
    result = subprocess.run([sys.executable, "-s", "-E", str(script)],
                            capture_output=True, text=True, timeout=50)
    assert result.returncode == 0, result.stderr


def test_qsv_probe_checks_depth_and_intel_device_without_disk_cache(monkeypatch):
    commands = []
    def run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=1 if "av1_qsv" in cmd else 0, stderr="unsupported")
    monkeypatch.setattr(intel_backend.subprocess, "run", run)
    monkeypatch.setattr(intel_backend, "_QSV_CODECS_CACHE", {})
    result = intel_backend.probe_qsv_codecs("portable-ffmpeg")
    assert result == {"h264_qsv": True, "hevc_qsv": True, "hevc_main10": True, "av1_qsv": False}
    assert all("d3d11va=intel_probe:,vendor_id=0x8086" in cmd for cmd in commands)
    assert {cmd[cmd.index("-profile:v") + 1] for cmd in commands} >= {"main", "main10", "high"}


def test_failed_probe_never_enables_encoders(monkeypatch):
    def fail(*args):
        raise RuntimeError("driver missing")
    monkeypatch.setattr(intel_backend, "probe_qsv_codecs", fail)
    assert not any(intel_native_exporter.query_intel_capabilities("missing").values())


def test_main_is_not_main10_and_hdr_is_not_silently_replaced(monkeypatch):
    monkeypatch.setattr(intel_backend, "probe_qsv_codecs", lambda *_: {"hevc_qsv": True, "h264_qsv": True})
    caps = intel_native_exporter.query_intel_capabilities("test")
    assert caps["HEVC_8BIT"] and not caps["HEVC_10BIT"]
    assert intel_native_exporter.validate_intel_codec("hevc_sdr", "test") == "hevc_sdr"
    with pytest.raises(ValueError, match="HDR nie zostało zmienione na SDR"):
        intel_native_exporter.validate_intel_codec("hevc", "test")


def test_gui_disables_av1_and_keeps_hdr_default(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from src.gui.qt.tabs.render_tab import RenderTab
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(intel_native_exporter, "query_intel_capabilities", lambda: {
        "H264_8BIT": True, "HEVC_8BIT": True, "HEVC_10BIT": True, "AV1_10BIT": False})
    tab = RenderTab()
    assert tab.cmb_intel_codec.currentData() == "hevc"
    assert not tab.cmb_intel_codec.model().item(tab.cmb_intel_codec.findData("av1")).isEnabled()
    assert tab.cmb_intel_codec.model().item(tab.cmb_intel_codec.findData("hevc_sdr")).isEnabled()
    tab.close()


def test_gui_requires_explicit_sdr_selection_if_no_hdr(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from src.gui.qt.tabs.render_tab import RenderTab
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(intel_native_exporter, "query_intel_capabilities", lambda: {"H264_8BIT": True})
    tab = RenderTab()
    assert tab.cmb_intel_codec.currentIndex() == -1
    tab.close()


def test_gui_rejects_restored_unavailable_codec_with_queue_reason(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from src.gui.qt.tabs.render_tab import RenderTab
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(intel_native_exporter, "query_intel_capabilities", lambda *args: {"H264_8BIT": True})
    tab = RenderTab()
    assert not tab._start_render({"encoder": "intel", "intel_codec": "av1"})
    assert "AV1 10-bit HDR" in tab._render_start_rejection
    assert "H.264 8-bit SDR" in tab._render_start_rejection
    tab.close()


def test_initialization_abort_kills_real_child_without_grace_period():
    import sys
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], stdin=subprocess.PIPE)
    started = time.perf_counter()
    try:
        streaming._stop_ffmpeg_process(process, graceful_timeout=0)
        assert process.poll() is not None
        assert time.perf_counter() - started < 3
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)


def test_cleanup_logs_advance_without_cancel_event(monkeypatch):
    messages = []
    monkeypatch.setattr(streaming, "print", lambda text, **_: messages.append(text))
    class Process:
        pid = 123
        stdin = None
        returncode = None
        def poll(self):
            return self.returncode
        def terminate(self):
            self.returncode = -1
    streaming._stop_ffmpeg_process(Process(), graceful_timeout=0.15)
    elapsed = [float(m.split("elapsed=")[1].split("s ")[0]) for m in messages if "elapsed=" in m]
    assert max(elapsed) >= 0.1


def test_graceful_stop_finalizes_mp4_with_audio_from_original(tmp_path):
    import json
    from pathlib import Path
    from src.runtime_paths import get_ffmpeg_exe, get_ffprobe_exe
    source = Path(os.environ.get("TELEM_TEST_VIDEO", r"C:\GoPro\GX010378.MP4"))
    if not source.is_file():
        pytest.skip("Original MP4 for live audio mux test is not available")
    output = tmp_path / "graceful_with_audio.mp4"
    process = subprocess.Popen([
        str(get_ffmpeg_exe()), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", "64x36", "-r", "10", "-i", "pipe:0", "-i", str(source),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-t", "2", "-shortest", str(output)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        process.stdin.write(bytes([20, 80, 160, 255]) * (64 * 36 * 20))
        assert streaming._stop_ffmpeg_process(process) == 0
        assert process._telem_cancel_mode == "graceful"
        probe = subprocess.run([str(get_ffprobe_exe()), "-v", "error", "-show_streams", "-of", "json", str(output)],
                               capture_output=True, text=True, check=True, timeout=10)
        streams = json.loads(probe.stdout)["streams"]
        assert {s["codec_type"] for s in streams} == {"video", "audio"}
        assert int(streams[0]["nb_frames"]) == 20
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
