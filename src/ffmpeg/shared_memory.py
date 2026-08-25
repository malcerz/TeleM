"""Shared Memory support for FFmpeg overlay rendering.

Avoids large IPC serialization penalties by writing rendered frame bytes
directly to shared memory buffers instead of pickling them through multiprocessing pipes.
"""

from __future__ import annotations

import os
import queue
import time
from multiprocessing import shared_memory
from typing import Any

from src.ffmpeg.worker_cache import WORKER_CACHE, init_worker
from src.ffmpeg.frame_renderer import _direct_region_members, render_overlay_frame
from src.ffmpeg.shm_image import close_writable_image, writable_rgba_image


class SharedFramePool:
    """Pool of pre-allocated shared memory blocks for zero-copy IPC.

    Each slot holds one raw RGBA frame (overlay_w × overlay_h × 4 bytes).
    Workers acquire a slot, write frame data, and release it after the
    main thread has consumed it.
    """

    def __init__(self, n_slots: int, frame_size_bytes: int) -> None:
        self.n_slots = n_slots
        self.frame_size = frame_size_bytes
        self._shm_blocks: list[shared_memory.SharedMemory] = []
        self._free: queue.Queue[int] = queue.Queue()
        for i in range(n_slots):
            shm = shared_memory.SharedMemory(create=True, size=frame_size_bytes)
            self._shm_blocks.append(shm)
            self._free.put(i)

    def shm_names(self) -> list[str]:
        """Return list of SHM block names (for passing to worker processes)."""
        return [shm.name for shm in self._shm_blocks]

    def acquire(self, timeout: float = 30.0) -> int:
        """Acquire a free slot index (blocks until one is available)."""
        return self._free.get(timeout=timeout)

    def release(self, slot: int) -> None:
        """Release a slot back to the free pool."""
        self._free.put(slot)

    def read(self, slot: int) -> bytes:
        """Read raw frame bytes from a slot (zero-copy via memoryview)."""
        return bytes(self._shm_blocks[slot].buf[:self.frame_size])

    def get_memview(self, slot: int) -> memoryview:
        """Return memoryview of the shared memory slot directly without copying."""
        return self._shm_blocks[slot].buf[:self.frame_size]

    def read_into(self, slot: int, dest: Any) -> None:
        """Write slot contents directly to a writable file-like object."""
        dest.write(self._shm_blocks[slot].buf[:self.frame_size])

    def close(self) -> None:
        """Close and unlink all shared memory blocks."""
        for shm in self._shm_blocks:
            try:
                buf = getattr(shm, "_buf", None)
                if buf is not None:
                    try:
                        buf.release()
                    except Exception:
                        pass
                shm.close()
                shm.unlink()
            except Exception:
                pass
        self._shm_blocks.clear()


# Global references set by worker initialiser — one per child process.
_SHM_BLOCKS: list[shared_memory.SharedMemory | None] = []
_SHM_FRAME_SIZE: int = 0


def _init_shm_in_worker(shm_names: list[str], frame_size: int) -> None:
    """Attach to existing shared memory blocks in a child worker process."""
    global _SHM_BLOCKS, _SHM_FRAME_SIZE
    _SHM_FRAME_SIZE = frame_size
    _SHM_BLOCKS = []
    for name in shm_names:
        _SHM_BLOCKS.append(shared_memory.SharedMemory(name=name, create=False))


def _close_shm_in_worker() -> None:
    """Detach from shared memory (called at worker shutdown via atexit)."""
    global _SHM_BLOCKS
    for shm in _SHM_BLOCKS:
        if shm is not None:
            try:
                buf = getattr(shm, "_buf", None)
                if buf is not None:
                    try:
                        buf.release()
                    except Exception:
                        pass
                shm.close()
            except Exception:
                pass
    _SHM_BLOCKS = []


def _init_worker_with_shm(
    shm_names: list[str], frame_size: int,
    *init_worker_args: Any,
) -> None:
    """Combined initialiser: set up WORKER_CACHE + attach SHM blocks."""
    import atexit
    init_worker(*init_worker_args)
    _init_shm_in_worker(shm_names, frame_size)
    atexit.register(_close_shm_in_worker)


def render_frame_shm_job(job: tuple) -> tuple[int, int]:
    """Render one overlay frame into a shared memory slot.

    Args:
        job: (frame_index, shm_slot_id)

    Returns:
        (frame_index, shm_slot_id) — only ~50 bytes through pickle.
    """
    index, slot = job[:2]
    audit_enabled = len(job) >= 3 and bool(job[2])
    if audit_enabled:
        worker_started_ns = time.perf_counter_ns()
    start_dt_utc = WORKER_CACHE.get("start_dt_utc")
    tz_offset_hours = WORKER_CACHE.get("tz_offset_hours")
    speed_samples = WORKER_CACHE.get("speed_samples")
    track_samples = WORKER_CACHE.get("track_samples")
    alt_samples = WORKER_CACHE.get("alt_samples")
    target_fps = WORKER_CACHE.get("target_fps")
    update_rate_step = WORKER_CACHE.get("update_rate_step", 1)
    import numpy as np
    shm_buf = _SHM_BLOCKS[slot].buf
    layout = WORKER_CACHE.get("layout", {})
    hud_regions = WORKER_CACHE.get("hud_regions")
    zero_copy_requested = os.environ.get("TELEM_ZERO_COPY_SHM", "1").strip().lower() not in {
        "0", "false", "no", "off"
    }
    zero_copy_target = None
    zero_copy = False
    clear_started_ns = None
    clear_finished_ns = None
    if (
        zero_copy_requested
        and hud_regions
        and layout.get("_nvidia_direct_region")
        and _direct_region_members(layout, hud_regions) is not None
    ):
        atlas_size = layout.get("_nvidia_atlas_size")
        if atlas_size is None:
            atlas_size = (
                max(region[2] + region[4] for region in hud_regions),
                max(region[3] + region[5] for region in hud_regions),
            )
        atlas_w, atlas_h = map(int, atlas_size)
        frame_bytes = atlas_w * atlas_h * 4
        try:
            clear_started_ns = time.perf_counter_ns() if audit_enabled else None
            clear_arr = np.frombuffer(shm_buf[:frame_bytes], dtype=np.uint8, count=frame_bytes)
            clear_arr.fill(0)
            del clear_arr
            clear_finished_ns = time.perf_counter_ns() if audit_enabled else None
            zero_copy_target = writable_rgba_image(shm_buf, (atlas_w, atlas_h))
            zero_copy = True
        except Exception:
            close_writable_image(zero_copy_target)
            zero_copy_target = None
            zero_copy = False

    if audit_enabled:
        worker_render_started_ns = time.perf_counter_ns()
    try:
        img = render_overlay_frame(
            index, start_dt_utc, tz_offset_hours,
            speed_samples, track_samples, alt_samples,
            target_fps, update_rate_step,
            target_image=zero_copy_target,
        )
    except Exception:
        if not zero_copy:
            raise
        # Keep the existing safe path as a per-job fallback if a Pillow
        # operation cannot work with the mapped target in a future build.
        close_writable_image(zero_copy_target)
        zero_copy_target = None
        zero_copy = False
        img = render_overlay_frame(
            index, start_dt_utc, tz_offset_hours,
            speed_samples, track_samples, alt_samples,
            target_fps, update_rate_step,
            target_image=None,
        )
    if audit_enabled:
        worker_render_finished_ns = time.perf_counter_ns()

    if zero_copy:
        # No PIL->NumPy conversion and no full-atlas memcpy in this branch.
        # Mark the transfer complete before releasing Pillow's mapped wrapper;
        # the release is lifetime bookkeeping, not a frame-data transfer.
        shm_copy_finished_ns = (
            worker_render_finished_ns if audit_enabled else None
        )
        close_writable_image(zero_copy_target)
        del zero_copy_target
        del shm_buf
    else:
        frame_bytes = img.height * img.width * 4
        shm_arr = np.frombuffer(shm_buf[:frame_bytes], dtype=np.uint8).reshape((img.height, img.width, 4))
        img_arr = np.asarray(img)
        np.copyto(shm_arr, img_arr)
        del shm_arr
        del shm_buf
    if audit_enabled:
        if not zero_copy:
            shm_copy_finished_ns = time.perf_counter_ns()
        return (
            index, slot, os.getpid(), worker_started_ns,
            worker_render_started_ns, worker_render_finished_ns,
            shm_copy_finished_ns, clear_started_ns, clear_finished_ns,
            zero_copy,
        )
    return index, slot
