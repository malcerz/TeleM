"""FFmpeg and hardware acceleration pipeline integration package.
"""

from __future__ import annotations

from src.ffmpeg.detection import (
    _test_hwaccel,
    detect_gpu_decoder,
    _test_encoder,
    detect_best_encoder,
)
from src.ffmpeg.intel_backend import (
    IntelDeviceSelection,
    intel_device_selection,
    intel_ffmpeg_device_args,
    enumerate_d3d11_adapters,
    find_intel_adapter,
    resolve_intel_force,
    IntelBackendError,
    IntelResolution,
)
from src.ffmpeg.worker_cache import (
    WORKER_CACHE,
    init_worker,
    _get_source_samples,
    _resolve_cache_value,
    _resolve_cache_samples,
)
from src.ffmpeg.frame_renderer import (
    render_overlay_frame,
    render_overlay_job,
    render_frame_bytes_job,
)
from src.ffmpeg.shared_memory import (
    SharedFramePool,
    _init_shm_in_worker,
    _close_shm_in_worker,
    _init_worker_with_shm,
    render_frame_shm_job,
)
from src.ffmpeg.command_builder import (
    RESOLUTION_MAP,
    scale_filter_for_resolution,
    append_bitrate_args,
)
from src.ffmpeg.streaming import (
    _pipe_writer_thread,
    stream_overlay_to_ffmpeg,
    _report_stream_progress,
    run_ffmpeg_with_progress,
)
from src.ffmpeg.second_pass import (
    generate_overlay_sequence,
    build_overlay_video,
    apply_overlay_video,
)

__all__ = [
    "detect_gpu_decoder",
    "detect_best_encoder",
    "enumerate_d3d11_adapters",
    "find_intel_adapter",
    "resolve_intel_force",
    "IntelDeviceSelection",
    "intel_device_selection",
    "intel_ffmpeg_device_args",
    "IntelBackendError",
    "IntelResolution",
    "init_worker",
    "render_overlay_frame",
    "render_overlay_job",
    "render_frame_bytes_job",
    "SharedFramePool",
    "stream_overlay_to_ffmpeg",
    "scale_filter_for_resolution",
    "append_bitrate_args",
    "generate_overlay_sequence",
    "build_overlay_video",
    "apply_overlay_video",
    "RESOLUTION_MAP",
    "WORKER_CACHE",
    "run_ffmpeg_with_progress",
]
