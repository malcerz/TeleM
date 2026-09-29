"""
TeleM NVIDIA Stage 8F — Native C++ Pipeline Runner
Orchestrates the native telem_nvenc_native.dll for D3D11 + MF + D2D + VP + NVENC 13.1.
Python is strictly used for setup, telemetry precomputation, progress monitoring, and teardown.
"""

import sys
import os
import time
import argparse
from pathlib import Path
import ctypes
from datetime import timedelta

# Ensure repo root is on sys.path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# ── CTYPES STRUCTURES ─────────────────────────────────────────────────────────

class TelemFrameState(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ('frame_index', ctypes.c_uint32),
        ('timestamp_sec', ctypes.c_double),
        ('speed_kmh', ctypes.c_float),
        ('heart_rate_bpm', ctypes.c_float),
        ('time_str', ctypes.c_char * 32),
        ('speed_str', ctypes.c_char * 32),
        ('hr_str', ctypes.c_char * 32),
    ]

class TelemNvencConfig(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ('width', ctypes.c_uint32),
        ('height', ctypes.c_uint32),
        ('fps_num', ctypes.c_uint32),
        ('fps_den', ctypes.c_uint32),
        ('ring_size', ctypes.c_uint32),
        ('bit_depth', ctypes.c_uint32),
        ('preset_p1_to_p7', ctypes.c_uint32),
        ('tuning_info', ctypes.c_uint32),
        ('async_nvenc', ctypes.c_int32),
        ('enable_debug_layer', ctypes.c_int32),
    ]

class TelemProgressInfo(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ('completed_frames', ctypes.c_uint32),
        ('total_frames', ctypes.c_uint32),
        ('elapsed_sec', ctypes.c_double),
        ('current_fps', ctypes.c_double),
        ('is_active', ctypes.c_int32),
        ('is_cancelled', ctypes.c_int32),
        ('is_finished', ctypes.c_int32),
        ('error_code', ctypes.c_int32),
        ('error_message', ctypes.c_char * 256),
    ]

class TelemPipelineStats(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ('completed_frames', ctypes.c_uint32),
        ('wall_time_sec', ctypes.c_double),
        ('throughput_fps', ctypes.c_double),
        ('total_bitstream_bytes', ctypes.c_uint64),
        ('bitrate_mbps', ctypes.c_double),
        
        ('avg_latency_ms', ctypes.c_double),
        ('median_latency_ms', ctypes.c_double),
        ('p95_latency_ms', ctypes.c_double),
        ('p99_latency_ms', ctypes.c_double),
        ('max_latency_ms', ctypes.c_double),
        
        ('decode_acquire_ms', ctypes.c_double),
        ('telemetry_lookup_ms', ctypes.c_double),
        ('hud_d2d_ms', ctypes.c_double),
        ('vp_composite_ms', ctypes.c_double),
        ('nvenc_submit_ms', ctypes.c_double),
        ('bitstream_handling_ms', ctypes.c_double),
        
        ('ram_start_bytes', ctypes.c_uint64),
        ('ram_peak_bytes', ctypes.c_uint64),
        ('ram_end_bytes', ctypes.c_uint64),
        ('vram_budget_bytes', ctypes.c_uint64),
        ('vram_usage_bytes', ctypes.c_uint64),
    ]

# ── NATIVE DLL BINDINGS ───────────────────────────────────────────────────────

class NativeNvencPipeline:
    def __init__(self, dll_path: Path):
        self.handle = None
        if not dll_path.exists():
            raise FileNotFoundError(f"Native DLL not found at: {dll_path}")
        try:
            os.add_dll_directory(str(dll_path.parent))
        except (AttributeError, OSError):
            pass
        self.dll = ctypes.CDLL(str(dll_path))
        self._bind_functions()
        self.handle = self.dll.telem_nvenc_create()
        if not self.handle:
            raise RuntimeError("Failed to create native telem_nvenc instance")

    def _bind_functions(self):
        self.dll.telem_nvenc_create.restype = ctypes.c_void_p
        self.dll.telem_nvenc_create.argtypes = []

        self.dll.telem_nvenc_configure.restype = ctypes.c_int
        self.dll.telem_nvenc_configure.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemNvencConfig)]

        self.dll.telem_nvenc_open_video.restype = ctypes.c_int
        self.dll.telem_nvenc_open_video.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]

        self.dll.telem_nvenc_set_telemetry.restype = ctypes.c_int
        self.dll.telem_nvenc_set_telemetry.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemFrameState), ctypes.c_uint32]

        self.dll.telem_nvenc_start_export.restype = ctypes.c_int
        self.dll.telem_nvenc_start_export.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int]

        self.dll.telem_nvenc_cancel.restype = None
        self.dll.telem_nvenc_cancel.argtypes = [ctypes.c_void_p]

        self.dll.telem_nvenc_wait_completion.restype = ctypes.c_int
        self.dll.telem_nvenc_wait_completion.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

        self.dll.telem_nvenc_get_progress.restype = None
        self.dll.telem_nvenc_get_progress.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemProgressInfo)]

        self.dll.telem_nvenc_get_stats.restype = None
        self.dll.telem_nvenc_get_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemPipelineStats)]

        self.dll.telem_nvenc_close_video.restype = None
        self.dll.telem_nvenc_close_video.argtypes = [ctypes.c_void_p]

        self.dll.telem_nvenc_destroy.restype = None
        self.dll.telem_nvenc_destroy.argtypes = [ctypes.c_void_p]

    def configure(self, config: TelemNvencConfig) -> bool:
        return bool(self.dll.telem_nvenc_configure(self.handle, ctypes.byref(config)))

    def open_video(self, video_path: str) -> bool:
        return bool(self.dll.telem_nvenc_open_video(self.handle, video_path))

    def set_telemetry(self, states_array) -> bool:
        count = len(states_array)
        ptr = (TelemFrameState * count)(*states_array)
        return bool(self.dll.telem_nvenc_set_telemetry(self.handle, ptr, count))

    def start_export(self, output_path: str, start_frame: int, frame_count: int, include_hud: bool = True) -> bool:
        return bool(self.dll.telem_nvenc_start_export(self.handle, output_path, start_frame, frame_count, 1 if include_hud else 0))

    def cancel(self):
        self.dll.telem_nvenc_cancel(self.handle)

    def wait_completion(self, timeout_ms: int = 0) -> bool:
        return bool(self.dll.telem_nvenc_wait_completion(self.handle, timeout_ms))

    def get_progress(self) -> TelemProgressInfo:
        prog = TelemProgressInfo()
        self.dll.telem_nvenc_get_progress(self.handle, ctypes.byref(prog))
        return prog

    def get_stats(self) -> TelemPipelineStats:
        stats = TelemPipelineStats()
        self.dll.telem_nvenc_get_stats(self.handle, ctypes.byref(stats))
        return stats

    def close_video(self):
        self.dll.telem_nvenc_close_video(self.handle)

    def destroy(self):
        if self.handle:
            self.dll.telem_nvenc_destroy(self.handle)
            self.handle = None

    def __del__(self):
        self.destroy()

# ── TELEMETRY PRECOMPUTATION ──────────────────────────────────────────────────

def precompute_telemetry(fit_path: str, total_frames: int = 5395, fps_num: int = 30000, fps_den: int = 1001):
    print(f"[TELEMETRY] Precomputing frame state for {total_frames} frames from {fit_path}...")
    t0 = time.perf_counter()
    from src.gui.telemetry_manager import TelemetryDataManager
    from src.telemetry_extract import interpolate_speed, interpolate_value

    tdm = TelemetryDataManager()
    tdm.load_fit(video_path="Video/GX030120.MP4", manual_path=Path(fit_path))

    speed_samples = tdm.fit_data.get('speed', [])
    hr_samples = tdm.fit_data.get('heart_rate', [])
    if not speed_samples or not hr_samples:
        raise RuntimeError("Failed to extract speed or heart_rate from FIT file")

    start_dt = speed_samples[0][0]
    fps = fps_num / fps_den

    states = []
    for f in range(total_frames):
        t_sec = f / fps
        curr_dt = start_dt + timedelta(seconds=t_sec)
        spd = interpolate_speed(speed_samples, curr_dt)
        hr = interpolate_value(hr_samples, curr_dt)
        if hr is None:
            hr = hr_samples[0][1]

        m = int(t_sec // 60)
        s = int(t_sec % 60)
        tenth = int((t_sec % 1) * 10)
        time_str = f"{m:02d}:{s:02d}.{tenth:01d}"
        speed_str = f"{spd:.1f}"
        hr_str = f"{int(round(hr))}"

        state = TelemFrameState(
            frame_index=f,
            timestamp_sec=t_sec,
            speed_kmh=spd,
            heart_rate_bpm=hr,
            time_str=time_str.encode('utf-8'),
            speed_str=speed_str.encode('utf-8'),
            hr_str=hr_str.encode('utf-8'),
        )
        states.append(state)

    t_precompute = time.perf_counter() - t0
    print(f"[TELEMETRY] Precomputed {len(states)} frame states in {t_precompute*1000:.2f} ms ({len(states)/t_precompute:.1f} states/s)")
    return states

# ── RUN BENCHMARK FUNCTION ────────────────────────────────────────────────────

def run_pipeline(mode: str, frames: int, out_hevc: str, fit_path: str = None, cancel_after: float = 0.0, debug_layer: bool = False):
    dll_path = ROOT / "native" / "d3d11_nvenc_pipeline" / "bin" / "telem_nvenc_native.dll"
    video_path = str(ROOT / "Video" / "GX030120.MP4")
    if not fit_path:
        fit_path = str(ROOT / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit")

    print(f"\n=======================================================")
    print(f"=== NVIDIA STAGE 8F — NATIVE C++ PIPELINE BENCHMARK ===")
    print(f"=======================================================")
    print(f"Mode:         {mode.upper()}")
    print(f"Frames:       {frames}")
    print(f"Video:        {video_path}")
    print(f"FIT:          {fit_path}")
    print(f"Output HEVC:  {out_hevc}")
    print(f"Debug Layer:  {debug_layer}")
    if cancel_after > 0:
        print(f"Cancel After: {cancel_after:.2f} seconds")
    print(f"=======================================================\n")

    # 1. Precompute telemetry outside hot loop
    telemetry_states = precompute_telemetry(fit_path, total_frames=frames)

    # 2. Instantiate native pipeline
    pipe = NativeNvencPipeline(dll_path)

    # 3. Configure
    config = TelemNvencConfig(
        width=3840,
        height=2160,
        fps_num=30000,
        fps_den=1001,
        ring_size=4,
        bit_depth=8,             # NV12 output for Stage 8F
        preset_p1_to_p7=1,       # P1 Fastest
        tuning_info=1,           # HIGH_QUALITY
        async_nvenc=1 if mode == "async" else 0,
        enable_debug_layer=1 if debug_layer else 0
    )

    if not pipe.configure(config):
        raise RuntimeError("pipe.configure failed")
    print("[NATIVE] Configured D3D11, Direct2D, VideoProcessor, NVENC")

    # 4. Open video
    if not pipe.open_video(video_path):
        raise RuntimeError(f"pipe.open_video failed for {video_path}")
    print(f"[NATIVE] Media Foundation opened {video_path} (HEVC Main10 P010)")

    # 5. Set telemetry
    if not pipe.set_telemetry(telemetry_states):
        raise RuntimeError("pipe.set_telemetry failed")
    print(f"[NATIVE] Transferred {len(telemetry_states)} frame states to C++ table")

    # 6. Start export
    import psutil
    proc = psutil.Process()
    cpu_before = proc.cpu_times()

    t_start = time.perf_counter()
    if not pipe.start_export(out_hevc, start_frame=0, frame_count=frames, include_hud=True):
        raise RuntimeError("pipe.start_export failed")
    print(f"[NATIVE] Hot frame loop started in dedicated worker thread...\n")

    # 7. Progress polling loop (~10 Hz)
    last_print = 0
    cancelled = False
    try:
        while True:
            prog = pipe.get_progress()
            now = time.perf_counter()
            elapsed = now - t_start

            if cancel_after > 0 and elapsed >= cancel_after and not cancelled:
                print(f"\n[CANCEL] Requesting atomic cancel after {elapsed:.2f}s...")
                pipe.cancel()
                cancelled = True

            if now - last_print >= 0.2 or prog.is_finished:
                last_print = now
                pct = (prog.completed_frames / prog.total_frames * 100.0) if prog.total_frames > 0 else 0
                print(f"\r[PROGRESS] {prog.completed_frames:5d}/{prog.total_frames:5d} ({pct:5.1f}%) | "
                      f"FPS: {prog.current_fps:6.1f} | Elapsed: {prog.elapsed_sec:5.2f}s", end='', flush=True)

            if prog.is_finished:
                print()
                break

            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[USER] Interrupted! Requesting cancel...")
        pipe.cancel()

    # 8. Wait completion
    pipe.wait_completion()
    cpu_after = proc.cpu_times()

    # 9. Get stats
    stats = pipe.get_stats()
    pipe.close_video()
    pipe.destroy()

    cpu_user = cpu_after.user - cpu_before.user
    cpu_sys = cpu_after.system - cpu_before.system
    cpu_total_time = cpu_user + cpu_sys
    cpu_pct = (cpu_total_time / stats.wall_time_sec * 100.0) if stats.wall_time_sec > 0 else 0.0
    cpu_count = psutil.cpu_count(logical=True) or 1
    cpu_pct_norm = cpu_pct / cpu_count

    print(f"\n=======================================================")
    print(f"=== NATIVE PIPELINE EXECUTION SUMMARY ({mode.upper()}) ===")
    print(f"=======================================================")
    print(f"Completed Frames:      {stats.completed_frames}")
    print(f"Wall Time:             {stats.wall_time_sec:.3f} s")
    print(f"Throughput FPS:        {stats.throughput_fps:.2f} FPS")
    print(f"Total Bitstream Bytes: {stats.total_bitstream_bytes:,} bytes ({stats.total_bitstream_bytes / (1024*1024):.2f} MB)")
    print(f"Bitrate:               {stats.bitrate_mbps:.2f} Mbps")
    print(f"-------------------------------------------------------")
    print(f"Per-Frame Latency Breakdown:")
    print(f"  Avg Latency:         {stats.avg_latency_ms:.3f} ms")
    print(f"  Median Latency:      {stats.median_latency_ms:.3f} ms")
    print(f"  P95 Latency:         {stats.p95_latency_ms:.3f} ms")
    print(f"  P99 Latency:         {stats.p99_latency_ms:.3f} ms")
    print(f"  Max Latency:         {stats.max_latency_ms:.3f} ms")
    print(f"Stage Timings (Avg ms/frame):")
    print(f"  1. MF Decode Acquire:{stats.decode_acquire_ms:.3f} ms")
    print(f"  2. Telemetry Lookup: {stats.telemetry_lookup_ms:.4f} ms")
    print(f"  3. Direct2D HUD:     {stats.hud_d2d_ms:.3f} ms")
    print(f"  4. VideoProcessor:   {stats.vp_composite_ms:.3f} ms")
    print(f"  5. NVENC Submit:     {stats.nvenc_submit_ms:.3f} ms")
    print(f"  6. Bitstream Handle: {stats.bitstream_handling_ms:.3f} ms")
    print(f"CPU & Memory Metrics:")
    print(f"  Process CPU Time:    {cpu_total_time:.2f} s (user={cpu_user:.2f}s, sys={cpu_sys:.2f}s)")
    print(f"  Process CPU Usage:   {cpu_pct:.1f}% (total) / {cpu_pct_norm:.1f}% (per-core across {cpu_count} threads)")
    print(f"  RAM Start:           {stats.ram_start_bytes / (1024*1024):.1f} MB")
    print(f"  RAM Peak:            {stats.ram_peak_bytes / (1024*1024):.1f} MB")
    print(f"  RAM End:             {stats.ram_end_bytes / (1024*1024):.1f} MB")
    print(f"  VRAM Usage:          {stats.vram_usage_bytes / (1024*1024):.1f} MB")
    print(f"  VRAM Budget:         {stats.vram_budget_bytes / (1024*1024):.1f} MB")
    print(f"=======================================================\n")

    res_dict = {
        "mode": mode,
        "completed_frames": stats.completed_frames,
        "wall_time_sec": stats.wall_time_sec,
        "throughput_fps": stats.throughput_fps,
        "total_bitstream_bytes": stats.total_bitstream_bytes,
        "bitrate_mbps": stats.bitrate_mbps,
        "avg_latency_ms": stats.avg_latency_ms,
        "median_latency_ms": stats.median_latency_ms,
        "p95_latency_ms": stats.p95_latency_ms,
        "p99_latency_ms": stats.p99_latency_ms,
        "max_latency_ms": stats.max_latency_ms,
        "decode_acquire_ms": stats.decode_acquire_ms,
        "telemetry_lookup_ms": stats.telemetry_lookup_ms,
        "hud_d2d_ms": stats.hud_d2d_ms,
        "vp_composite_ms": stats.vp_composite_ms,
        "nvenc_submit_ms": stats.nvenc_submit_ms,
        "bitstream_handling_ms": stats.bitstream_handling_ms,
        "cpu_total_time_sec": cpu_total_time,
        "cpu_user_sec": cpu_user,
        "cpu_sys_sec": cpu_sys,
        "cpu_pct_total": cpu_pct,
        "cpu_pct_norm": cpu_pct_norm,
        "ram_start_mb": stats.ram_start_bytes / (1024*1024),
        "ram_peak_mb": stats.ram_peak_bytes / (1024*1024),
        "ram_end_mb": stats.ram_end_bytes / (1024*1024),
        "vram_usage_mb": stats.vram_usage_bytes / (1024*1024),
        "vram_budget_mb": stats.vram_budget_bytes / (1024*1024),
    }
    return res_dict

if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description="TeleM NVIDIA Stage 8F Native Pipeline Runner")
    parser.add_argument('--mode', choices=['sync', 'async'], default='sync', help="NVENC bitstream retrieval mode")
    parser.add_argument('--frames', type=int, default=5395, help="Number of frames to export (default 5395)")
    parser.add_argument('--output', type=str, default=None, help="Output HEVC bitstream path")
    parser.add_argument('--cancel-after', type=float, default=0.0, help="Simulate cancel after N seconds")
    parser.add_argument('--debug-layer', action='store_true', help="Enable D3D11 Debug Layer")
    parser.add_argument('--fit', type=str, default=None, help="Path to FIT telemetry file")
    parser.add_argument('--save-json', type=str, default=None, help="Path to save JSON benchmark summary")
    args = parser.parse_args()

    out_file = args.output
    if not out_file:
        out_file = str(ROOT / "scratch" / f"nvidia_stage8f_{args.mode}_output.hevc")

    res = run_pipeline(mode=args.mode, frames=args.frames, out_hevc=out_file, fit_path=args.fit, cancel_after=args.cancel_after, debug_layer=args.debug_layer)
    if args.save_json:
        with open(args.save_json, 'w') as f:
            json.dump(res, f, indent=2)
        print(f"[BENCHMARK] Saved results JSON to {args.save_json}")
