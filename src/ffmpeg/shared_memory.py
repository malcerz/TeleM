"""Shared Memory support for FFmpeg overlay rendering.

Avoids large IPC serialization penalties by writing rendered frame bytes
directly to shared memory buffers instead of pickling them through multiprocessing pipes.
"""

from __future__ import annotations

import queue
from multiprocessing import shared_memory
from typing import Any

from src.ffmpeg.worker_cache import WORKER_CACHE, init_worker
from src.ffmpeg.frame_renderer import render_overlay_frame


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

    def read_into(self, slot: int, dest: Any) -> None:
        """Write slot contents directly to a writable file-like object."""
        dest.write(self._shm_blocks[slot].buf[:self.frame_size])

    def close(self) -> None:
        """Close and unlink all shared memory blocks."""
        for shm in self._shm_blocks:
            try:
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
    index, slot = job
    start_dt_utc = WORKER_CACHE.get("start_dt_utc")
    tz_offset_hours = WORKER_CACHE.get("tz_offset_hours")
    speed_samples = WORKER_CACHE.get("speed_samples")
    track_samples = WORKER_CACHE.get("track_samples")
    alt_samples = WORKER_CACHE.get("alt_samples")
    target_fps = WORKER_CACHE.get("target_fps")
    update_rate_step = WORKER_CACHE.get("update_rate_step", 1)
    img = render_overlay_frame(
        index, start_dt_utc, tz_offset_hours,
        speed_samples, track_samples, alt_samples,
        target_fps, update_rate_step,
    )
    raw = img.tobytes()
    _SHM_BLOCKS[slot].buf[:_SHM_FRAME_SIZE] = raw
    return index, slot
