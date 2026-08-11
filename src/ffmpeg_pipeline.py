"""FFmpeg overlay rendering and encoding pipeline.

Legacy wrapper that re-exports from the modularized ``src.ffmpeg`` package
to maintain backwards compatibility with existing imports.
"""

from __future__ import annotations

from src.ffmpeg import (
    detect_gpu_decoder,
    detect_best_encoder,
    init_worker,
    render_overlay_frame,
    render_overlay_job,
    render_frame_bytes_job,
    SharedFramePool,
    stream_overlay_to_ffmpeg,
    scale_filter_for_resolution,
    append_bitrate_args,
    generate_overlay_sequence,
    build_overlay_video,
    apply_overlay_video,
    RESOLUTION_MAP,
    WORKER_CACHE,
    run_ffmpeg_with_progress,
)

# Re-export internal/undocumented symbols if any legacy code/tests rely on them
from src.ffmpeg.detection import _test_hwaccel, _test_encoder, _nt_startupinfo
from src.ffmpeg.worker_cache import _get_source_samples, _resolve_cache_value, _resolve_cache_samples
from src.ffmpeg.shared_memory import _init_shm_in_worker, _close_shm_in_worker, _init_worker_with_shm, render_frame_shm_job
from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd
from src.ffmpeg.streaming import _pipe_writer_thread, _report_stream_progress
