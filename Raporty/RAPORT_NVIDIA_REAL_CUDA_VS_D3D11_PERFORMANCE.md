# TeleM — NVIDIA real GUI CUDA Legacy vs Native D3D11 performance

## Scope

This stage stopped visual-parity work and measured only performance. No production renderer, backend, font, map, bar, counter, or cadence code was changed. Each main run used the same `MainWindow → RenderTab → EKSPORTUJ` path, canonical `GX020079.MP4` + `GX020079.fit`, `def_layout.json`, 1131 frames, 3840×2160, 30000/1001 fps, HEVC Fast, 40M, 10-bit, Full HUD frequency, Auto HUD resolution, the same indicators/map/charts, and the same audio default.

`scratch/nvidia_real_perf_truth/config_compare.json` was written before the benchmark and records `CONFIG_EQUIVALENT=True`.

The six-run order was exactly:

```text
Legacy #1, Native #1, Native #2, Legacy #2, Legacy #3, Native #3
```

The reported true FPS is output frames divided by the GUI export wall interval from the Render button click through the completed output/mux signal. Full process wall time (including GUI startup/project warm-up and close) is also recorded in `performance_summary.csv`.

## Required result

```text
PERFORMANCE_COMPARISON_VALID=True

LEGACY_FPS_RUN1=82.741
LEGACY_FPS_RUN2=83.827
LEGACY_FPS_RUN3=84.505

NATIVE_FPS_RUN1=106.236
NATIVE_FPS_RUN2=106.648
NATIVE_FPS_RUN3=105.821

LEGACY_MEDIAN_FPS=83.827
NATIVE_MEDIAN_FPS=106.236
REAL_GAIN_PERCENT=26.73

LEGACY_CRITICAL_PATH_MS=11.929
NATIVE_CRITICAL_PATH_MS=7.801

DEVICE_B_HUD_RENDER_MS=7.172
CROSS_DEVICE_SYNC_MS=NOT_INSTRUMENTED
TOTAL_DEVICE_B_OVERHEAD_MS=7.172 (HUD wall interval; sync is not exposed separately)

MAP_COST_MS=1.014 (full-minus-map Device-B HUD aggregate, 300f diagnostic)
CHART_COST_MS=3.771 (full-minus-charts Device-B HUD aggregate, 300f diagnostic)

NATIVE_MINIMAL_HUD_FPS=341.037
NATIVE_STATIC_HUD_FPS=107.130 (static flag ineffective for the GUI-forced separate-HUD branch; NOT_PROVEN)

HIDDEN_FRAME_LIMITER=NOT_PROVEN
QUEUE_WAIT_BOTTLENECK=NOT_PROVEN
KEYED_MUTEX_BOTTLENECK=NOT_INSTRUMENTED
D2D_HUD_BOTTLENECK=True
VP_BOTTLENECK=False
NVENC_BOTTLENECK=False

PRIMARY_BOTTLENECK=Device-B full-HUD D2D/render-completion wall time
REALISTIC_OPTIMIZATION_HEADROOM=~10-20% plausible without redesign; minimal-HUD 341 FPS is a diagnostic ceiling, not production headroom

DECISION=B — Native has a real measured gain, but Device-B HUD is a large isolated bottleneck

USER_OBSERVED_LEGACY_FPS≈110
USER_OBSERVED_NATIVE_FPS≈113

MODIFIED_FILES=NONE (production renderer/backend)
CREATED_FILES=scratch/nvidia_real_perf_truth benchmark harness and artifacts
CASE=CASE B
```

The full process wall medians were 17.541 s (64.477 FPS) Legacy and 14.640 s (77.254 FPS) Native. These include process startup, project/telemetry warm-up, export, mux/close, and are retained alongside the export-wall result rather than silently replacing it.

Every main output passed the validity check: 1131 video frames, HEVC Main 10, `3840x2160`, `30000/1001`, `yuv420p10le`, and AAC stereo audio. No output-frame loss was observed (`dropped_frames_observed=0`); an explicit backend dropped-frame counter is `NOT_INSTRUMENTED`.

## Stage timing and bottleneck interpretation

Legacy has no equivalent per-stage timing ABI in this path. Its `decode_ms`, `HUD_render_ms`, `GPU_upload_ms`, `composite_ms`, `encode_ms`, and `mux_ms` are therefore `NOT_INSTRUMENTED`; only GUI wall-derived frame total and existing aggregate preparation/stream diagnostics are retained.

Native public stats provide aggregate means: decode `0.326–0.341 ms`, Device-B HUD `7.157–7.191 ms`, VP `0.066–0.069 ms`, NVENC submit `0.140–0.142 ms`, and native loop wall `9.162–9.202 s` for 1131 frames. `Device_B_HUD_ms` is a CPU wall interval around the Device-B D2D render/completion operation. It is not a GPU timestamp and must not be added to VP/NVENC as if the stages were serial. The current ABI exposes no independent AcquireSync, ReleaseSync, keyed-mutex, D3D11 EVENT, GetData-spin, Device-A↔Device-B, or mux durations; these remain `NOT_INSTRUMENTED` in `wait_breakdown.csv`.

The native lifecycle QPC deltas give a median frame-start critical path of 7.801 ms. The 300-frame diagnostics show a full Device-B HUD at 8.233 ms, minimal HUD at 1.057 ms (341 FPS native loop ceiling), full-minus-map at 7.219 ms, and full-minus-charts at 4.462 ms. The chart/map deltas are D2D aggregate evidence; short 300-frame wall FPS is noisy. The static-HUD flag does not bypass the GUI-forced separate `NVENC` Device-B full-HUD branch, so dynamic-HUD savings are not proven.

No fixed per-frame sleep or hidden 60/120/144 FPS limiter was proven. `GetData`/fence loops and keyed mutex calls exist in the native implementation, but their durations were not instrumented in this run. GPU utilization was not sampled during the six main runs; `gpu_utilization.csv` contains a clearly labeled post-run `nvidia-smi` snapshot only.

## Artifacts and reproducibility

All requested CSV/TXT/MD artifacts are under `scratch/nvidia_real_perf_truth/`, including raw GUI logs/results, output MP4s, Native stats copies, frame timelines, wait breakdown, widget diagnostics, root cause, decision, manifest, and reproduction commands. The benchmark harness files are diagnostic orchestration only; no production default/backend was changed. No AV1, H264, or default-backend work was started.

## Final status

```text
PERFORMANCE_COMPARISON_VALID=True
CASE=CASE B
USER_VISUAL_ACCEPTANCE=UNCHANGED (not part of this performance stage)
PRODUCTION_OPTIMIZATION=NOT_STARTED
```
