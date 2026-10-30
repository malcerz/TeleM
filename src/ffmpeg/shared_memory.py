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

import warnings

_WARNED_UNKNOWN_DIRECT_SHM = False


def get_intel_direct_shm_config() -> tuple[bool, str]:
    """Return (enabled, source_description) for Intel Direct SHM rendering.

    Default: ON (Direct SHM) when TELEM_INTEL_HUD_DIRECT_SHM is absent or empty.
    Explicit ON: 1, true, yes, on
    Explicit OFF: 0, false, no, off
    Unknown values: warn once and use default Direct SHM (ON).
    """
    global _WARNED_UNKNOWN_DIRECT_SHM
    raw = os.environ.get("TELEM_INTEL_HUD_DIRECT_SHM")
    if raw is None or not raw.strip():
        return True, "default"
    cleaned = raw.strip().lower()
    if cleaned in ("1", "true", "yes", "on"):
        return True, "env"
    if cleaned in ("0", "false", "no", "off"):
        return False, "env legacy-fallback"
    if not _WARNED_UNKNOWN_DIRECT_SHM:
        _WARNED_UNKNOWN_DIRECT_SHM = True
        warnings.warn(
            f"TELEM_INTEL_HUD_DIRECT_SHM has unrecognized value {raw!r}; using default Direct SHM (ON).",
            UserWarning,
            stacklevel=2,
        )
    return True, "default"


def is_intel_direct_shm_enabled() -> bool:
    """Check whether Intel Direct SHM rendering is active."""
    enabled, _ = get_intel_direct_shm_config()
    return enabled


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
        self._shm_addrs: list[int] = []
        for i in range(n_slots):
            shm = shared_memory.SharedMemory(create=True, size=frame_size_bytes)
            self._shm_blocks.append(shm)
            self._free.put(i)
            import ctypes
            ptr = (ctypes.c_char * frame_size_bytes).from_buffer(shm.buf)
            self._shm_addrs.append(ctypes.addressof(ptr))
            del ptr

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

    def get_ptr_addr(self, slot: int) -> int:
        """Return raw memory address of the shared memory slot directly (zero-copy)."""
        return self._shm_addrs[slot]

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


_TRACE_FIRST_JOB_DONE = False
_WIDGET_AUDIT: dict = {"jobs": 0, "sums": {}}


def _accumulate_widget_audit(breakdown: dict) -> None:
    """Diagnostics only: mean per-widget render cost in this worker."""
    _WIDGET_AUDIT["jobs"] += 1
    sums = _WIDGET_AUDIT["sums"]
    for key, value in breakdown.items():
        if isinstance(value, (int, float)) and (key.endswith(".total") or key.endswith("_ms")):
            sums[key] = sums.get(key, 0.0) + float(value)
    if _WIDGET_AUDIT["jobs"] % 200 == 0:
        import json
        n = _WIDGET_AUDIT["jobs"]
        means = {k: round(v / n, 3) for k, v in sorted(sums.items(), key=lambda kv: -kv[1])}
        print(f"[HUD WIDGET COST] pid={os.getpid()} jobs={n} mean_ms={json.dumps(means)}", flush=True)


class WorkerInitBlob:
    """Worker initargs pickled once into one shared memory block.

    Spawned workers receive only the block name. Passing tens of MB of
    initargs through each spawn pipe makes the parent block until every
    child has booted and read them, so workers would start one by one.
    """

    def __init__(self, init_args: tuple) -> None:
        import pickle
        payload = pickle.dumps(init_args, protocol=pickle.HIGHEST_PROTOCOL)
        self.size = len(payload)
        self._shm = shared_memory.SharedMemory(create=True, size=max(1, self.size))
        self._shm.buf[:self.size] = payload
        self.name = self._shm.name

    def close(self) -> None:
        if self._shm is None:
            return
        try:
            self._shm.close()
            self._shm.unlink()
        except Exception:
            pass
        self._shm = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _init_worker_with_prepared_blob(blob_name, blob_size, shm_names, frame_size):
    import pickle
    blob = shared_memory.SharedMemory(name=blob_name)
    try:
        payload = pickle.loads(bytes(blob.buf[:blob_size]))
    finally:
        blob.close()
    _init_worker_with_shm(shm_names, frame_size, *payload["init_args"])
    from src.project_preparation import install_export_map_seed, enter_worker_export_phase
    install_export_map_seed(payload["map_seed"])
    enter_worker_export_phase("prepared_hud_worker")


def _init_worker_with_shm_blob(
    blob_name: str, blob_size: int, shm_names: list[str], frame_size: int,
) -> None:
    """Initialiser variant that reads init_worker args from a WorkerInitBlob."""
    import pickle
    blob = shared_memory.SharedMemory(name=blob_name, create=False)
    try:
        init_worker_args = pickle.loads(bytes(blob.buf[:blob_size]))
    finally:
        blob.close()
    _init_worker_with_shm(shm_names, frame_size, *init_worker_args)


class LateSeedChannel:
    """One pickled object published to spawned workers after they started.

    Lets HUD workers boot while the parent is still fetching start-up data.
    Layout: byte 0 = ready flag, bytes 8..16 = payload length, then payload.
    Publishing ``None`` (or an oversized payload) releases waiting workers
    without data, so a failed fetch never costs more than a normal start.
    """

    _HEADER = 16

    def __init__(self, capacity: int) -> None:
        self.capacity = max(self._HEADER + 1, int(capacity))
        self._shm = shared_memory.SharedMemory(create=True, size=self.capacity)
        self._shm.buf[:self._HEADER] = bytes(self._HEADER)
        self.name = self._shm.name
        self.published_bytes = 0

    def publish(self, obj: Any) -> None:
        import pickle
        if self._shm is None or self._shm.buf[0]:
            return
        payload = b"" if obj is None else pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        if len(payload) > self.capacity - self._HEADER:
            payload = b""
        self._shm.buf[self._HEADER:self._HEADER + len(payload)] = payload
        self._shm.buf[8:16] = len(payload).to_bytes(8, "little")
        self._shm.buf[0] = 1  # written last: readers see a complete payload
        self.published_bytes = len(payload)

    def close(self) -> None:
        if self._shm is None:
            return
        try:
            self._shm.close()
            self._shm.unlink()
        except Exception:
            pass
        self._shm = None


def read_late_seed(name: str, timeout_s: float) -> Any:
    """Worker side of ``LateSeedChannel``; returns ``None`` on timeout/no data."""
    import pickle
    try:
        shm = shared_memory.SharedMemory(name=name, create=False)
    except FileNotFoundError:
        return None
    try:
        deadline = time.monotonic() + max(0.0, timeout_s)
        while not shm.buf[0]:
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.005)
        size = int.from_bytes(bytes(shm.buf[8:16]), "little")
        if size <= 0:
            return None
        return pickle.loads(bytes(shm.buf[LateSeedChannel._HEADER:LateSeedChannel._HEADER + size]))
    finally:
        shm.close()


def _init_worker_with_shm_blob_seeded(
    blob_name: str, blob_size: int, shm_names: list[str], frame_size: int,
    seed_channel_name: str | None = None, seed_wait_s: float = 0.0,
) -> None:
    """Blob initialiser for payload ``{"init_args": ..., "map_session_seed": ...}``.

    ``map_session_seed`` is the project's prepared map imagery (memory only,
    credential-bound).  The worker installs it and enters the export phase:
    no network, unprepared tiles are contract violations.  ``seed_channel_name``
    keeps the older late-channel hand-off available.
    """
    import pickle
    blob = shared_memory.SharedMemory(name=blob_name, create=False)
    try:
        payload = pickle.loads(bytes(blob.buf[:blob_size]))
    finally:
        blob.close()
    _init_worker_with_shm(shm_names, frame_size, *payload["init_args"])
    if os.environ.get("TELEM_INTEL_WIDGET_CACHE", "0") == "1":
        from src.indicators.dispatcher import enable_intel_output_cache
        enable_intel_output_cache()
    seed = payload.get("map_session_seed")
    if seed_channel_name:
        t_wait = time.perf_counter()
        seed = read_late_seed(seed_channel_name, seed_wait_s)
        if os.environ.get("TELEM_HUD_STARTUP_TRACE") == "1":
            print(f"[HUD STARTUP TRACE] worker pid={os.getpid()} map_seed_wait_ms={(time.perf_counter() - t_wait) * 1000.0:.1f}", flush=True)
    _enter_intel_worker_export(seed)


def _enter_intel_worker_export(seed) -> None:
    from src.project_preparation import enter_worker_export_phase, install_export_map_seed
    t_seed = time.perf_counter()
    installed = install_export_map_seed(seed)
    print(f"[HUD MAP PREPARED] worker pid={os.getpid()} tiles={installed}/{len((seed or {}).get('tiles', {}))} "
          f"install_ms={(time.perf_counter() - t_seed) * 1000.0:.1f}", flush=True)
    WORKER_CACHE["_intel_draw_bounds"] = True
    enter_worker_export_phase("intel_hud_worker")


def _init_intel_worker_with_shm(shm_names, frame_size, init_args, map_session_seed=None):
    _init_worker_with_shm(shm_names, frame_size, *init_args)
    if os.environ.get("TELEM_INTEL_WIDGET_CACHE", "0") == "1":
        from src.indicators.dispatcher import enable_intel_output_cache
        enable_intel_output_cache()
    _enter_intel_worker_export(map_session_seed)


def _init_worker_with_shm(
    shm_names: list[str], frame_size: int,
    *init_worker_args: Any,
) -> None:
    """Combined initialiser: set up WORKER_CACHE + attach SHM blocks."""
    import atexit
    if os.environ.get("TELEM_INTEL_HUD_PRIORITY") == "BELOW_NORMAL":
        try:
            import psutil
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass
    trace = os.environ.get("TELEM_HUD_STARTUP_TRACE") == "1"
    t_init0 = time.time()
    init_worker(*init_worker_args)
    _init_shm_in_worker(shm_names, frame_size)
    atexit.register(_close_shm_in_worker)
    if trace:
        try:
            import psutil
            created = psutil.Process().create_time()
        except Exception:
            created = 0.0
        print(f"[HUD STARTUP TRACE] worker pid={os.getpid()} created={created:.3f} "
              f"init_begin={t_init0:.3f} init_end={time.time():.3f}", flush=True)


def render_frame_shm_job(job: tuple) -> tuple[int, int]:
    """Render one overlay frame into a shared memory slot.

    Args:
        job: (frame_index, shm_slot_id)

    Returns:
        (frame_index, shm_slot_id) — only ~50 bytes through pickle.
    """
    output_index, slot = job[:2]
    index = output_index + (int(job[4]) if len(job) >= 5 else 0)
    if os.environ.get("TELEM_INTEL_FROZEN_HUD") == "1" and index > 0:
        return output_index, slot
    audit_enabled = len(job) >= 3 and bool(job[2])
    # Optional 4th element: this frame's precomputed telemetry record, for a
    # worker cache initialised without records (progressive Intel cache).
    job_record_cache = None
    if len(job) >= 4 and job[3] is not None:
        job_record_cache = WORKER_CACHE.get("_telemetry_cache")
        job_record_cache.records[index] = job[3]
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
    from src.project_preparation import contract as _prepare_contract
    map_misses_before = _prepare_contract.map_misses()
    hud_regions = WORKER_CACHE.get("hud_regions")
    zero_copy_requested = os.environ.get("TELEM_ZERO_COPY_SHM", "1").strip().lower() not in {
        "0", "false", "no", "off"
    }
    zero_copy_target = None
    zero_copy = False
    clear_started_ns = None
    clear_finished_ns = None
    intel_direct_shm = is_intel_direct_shm_enabled()
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
    elif zero_copy_requested and intel_direct_shm:
        overlay_w = int(WORKER_CACHE.get("video_width", 2560))
        overlay_h = int(WORKER_CACHE.get("video_height", 1440))
        frame_bytes = overlay_w * overlay_h * 4
        try:
            clear_started_ns = time.perf_counter_ns() if audit_enabled else None
            clear_arr = np.frombuffer(shm_buf[:frame_bytes], dtype=np.uint8, count=frame_bytes)
            clear_arr.fill(0)
            del clear_arr
            clear_finished_ns = time.perf_counter_ns() if audit_enabled else None
            zero_copy_target = writable_rgba_image(shm_buf, (overlay_w, overlay_h))
            zero_copy = True
        except Exception:
            close_writable_image(zero_copy_target)
            zero_copy_target = None
            zero_copy = False

    paint_bounds = {} if WORKER_CACHE.get("_intel_draw_bounds") else None
    breakdown = {} if audit_enabled else None
    widget_audit = os.environ.get("TELEM_INTEL_HUD_WIDGET_AUDIT") == "1"
    if widget_audit:
        breakdown = {}
    startup_trace = os.environ.get("TELEM_HUD_STARTUP_TRACE") == "1" and index < 4
    if startup_trace:
        breakdown = {}
        print(f"[HUD FIRST COMPOSE BEGIN] pid={os.getpid()} frame={index} epoch={time.time():.6f}",flush=True)
    # Measurement-only: profile the first compose per worker (opt-in env).
    start_profile_dir = os.environ.get("TELEM_START_PROFILE_DIR") if startup_trace else None
    start_profiler = None
    if start_profile_dir:
        import cProfile
        start_profiler = cProfile.Profile()
        start_profiler.enable()
    if audit_enabled:
        worker_render_started_ns = time.perf_counter_ns()
    try:
        img = render_overlay_frame(
            index, start_dt_utc, tz_offset_hours,
            speed_samples, track_samples, alt_samples,
            target_fps, update_rate_step,
            target_image=zero_copy_target,
            breakdown=breakdown,
            paint_bounds=paint_bounds,
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
            breakdown=breakdown,
            paint_bounds=paint_bounds,
        )
    if audit_enabled:
        worker_render_finished_ns = time.perf_counter_ns()
    if job_record_cache is not None:
        job_record_cache.records.pop(index, None)
    if _prepare_contract.export_active and _prepare_contract.map_misses() != map_misses_before:
        # Never hand a frame with grey (unprepared) map cells to the encoder.
        raise RuntimeError(f"Map export: frame {index} needs map tiles that were not prepared with the project")
    if widget_audit and breakdown is not None and index >= 30:
        _accumulate_widget_audit(breakdown)
    if start_profiler is not None:
        start_profiler.disable()
        start_profiler.dump_stats(os.path.join(start_profile_dir, f"worker_{os.getpid()}_frame{index}.prof"))
    if startup_trace:
        import json
        print(f"[HUD FIRST COMPOSE END] pid={os.getpid()} frame={index} epoch={time.time():.6f} breakdown={json.dumps(breakdown)}",flush=True)

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
        copied = False
        target = None
        try:
            target = writable_rgba_image(shm_buf, (img.width, img.height))
            target.paste(img, (0, 0))
            copied = True
        except Exception:
            pass
        finally:
            if target is not None:
                close_writable_image(target)
                del target
        if not copied:
            frame_bytes = img.height * img.width * 4
            shm_arr = np.frombuffer(shm_buf[:frame_bytes], dtype=np.uint8).reshape((img.height, img.width, 4))
            img_arr = np.asarray(img)
            np.copyto(shm_arr, img_arr)
            del shm_arr
            del img_arr
        del shm_buf
    global _TRACE_FIRST_JOB_DONE
    if not _TRACE_FIRST_JOB_DONE and os.environ.get("TELEM_HUD_STARTUP_TRACE") == "1":
        _TRACE_FIRST_JOB_DONE = True
        print(f"[HUD STARTUP TRACE] worker pid={os.getpid()} first_job frame={index} done={time.time():.3f}", flush=True)
    if audit_enabled:
        if not zero_copy:
            shm_copy_finished_ns = time.perf_counter_ns()
        return (
            index, slot, os.getpid(), worker_started_ns,
            worker_render_started_ns, worker_render_finished_ns,
            shm_copy_finished_ns, clear_started_ns, clear_finished_ns,
            zero_copy, breakdown,
        )
    if paint_bounds is not None:
        return output_index, slot, paint_bounds
    return output_index, slot
