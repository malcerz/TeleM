from __future__ import annotations

import ctypes

from src.ffmpeg.amd_hevc_preview import AMDGPUNativeFrameTapPreview


class _FakeNative:
    def __init__(self) -> None:
        self.enabled = []
        self.ready = True
        self.telem_amd_set_preview_tap = _FakeCallable(self._set)
        self.telem_amd_poll_preview_tap = _FakeCallable(self._poll)

    def _set(self, handle, enabled, width, height, interval):
        self.enabled.append((handle, enabled, width, height, interval))
        return 1

    def _poll(
        self, handle, out_bgra, capacity, out_width, out_height,
        out_frame, out_readback_ms,
    ):
        if not self.ready:
            return 0
        width, height = 4, 2
        payload = bytes(range(width * height * 4))
        ctypes.memmove(out_bgra, payload, len(payload))
        out_width._obj.value = width
        out_height._obj.value = height
        out_frame._obj.value = 42
        out_readback_ms._obj.value = 0.25
        self.ready = False
        return 1


class _FakeCallable:
    def __init__(self, fn):
        self.fn = fn

    def __call__(self, *args):
        return self.fn(*args)


def test_gpu_frame_tap_is_latest_only_and_has_no_workers():
    frames = []
    native = _FakeNative()
    preview = AMDGPUNativeFrameTapPreview(
        width=4, height=2, target_fps=2.0,
        on_frame=lambda raw, w, h: frames.append((raw, w, h)),
    )
    preview.configure_input_rate(30000, 1001)
    assert preview.start()
    assert preview.bind_native(native, "ctx")
    assert preview.poll_native_frame()
    assert not preview.poll_native_frame()
    assert len(frames) == 1
    assert frames[0][1:] == (4, 2)
    stats = preview.stats()
    assert stats["backend"] == "gpu_frame_tap"
    assert stats["updates"] == 1
    assert stats["capture_inflight"] == 0
    assert stats["avg_capture_ms"] == 0.25
    preview.stop()
    assert native.enabled[-1][1] == 0
