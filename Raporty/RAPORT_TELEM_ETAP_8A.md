# TeleM — ETAP 8A — RESULT

## A. Environment

```text
CPU       AMD Ryzen 5 5500U, 6 cores / 12 threads
GPU       AMD Radeon(TM) Graphics
video     GX030120.MP4, HEVC, 3840x2160, 30000/1001
decoder   GPU_HUD_D3D11VA / D3D11VA, hardware proof YES
VP        D3D11 VideoProcessor
encoder   AMF HEVC, 3840x2160, CQP 28/28 Speed
ABI       8
backend   AMD_NATIVE_D3D11
HUD       GPU_HUD
map       GPU
order     CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
charts    GPU_SPLIT requested; no active GPU chart widgets in this layout
gauge     GPU
telemetry PRECOMPUTED
```

The input layout was loaded from the unchanged `def_layout.json`. No source code, DLL or layout was modified during ETAP 8A.

## B. Baseline throughput

The valid reference run used 900 frames from `GX030120.MP4`.

| Run | Frames | Video/render wall | Mux | Total wall | FPS |
|---|---:|---:|---:|---:|---:|
| Full current layout | 900 | approximately 30.54 s | 2.449 s | 32.989 s | 27.282 |
| Frontend `AMF_MODE=BYPASS` | 900 | 30.268 s | 0 | 30.268 s | 29.735 |

The reported full-run FPS includes final audio remux wall time. The bypass run has no encoder and no mux, so it is a frontend-only control, not a pure video-only/no-overlay decode benchmark.

## C. Frame accounting

Full run:

```text
decoded / processed / VP / AMF submitted / AMF output = 900 / 900 / 900 / 900 / 900
dropped = 0
AMF_INPUT_FULL = 0
AMF retries = 0
```

The frame-accounting instrumentation covered 100% of the measured frame time; median unaccounted time was approximately 0.002 ms.

## D. Stage timings — full run

Existing stage timers, 900 frames. Values are average / p50 / p95 / p99 in milliseconds. A true maximum is not exposed by the existing profiler and is therefore `NOT INSTRUMENTED`.

| Stage | Avg | p50 | p95 | p99 | CPU/GPU | Serial/async |
|---|---:|---:|---:|---:|---|---|
| MF ReadSample / decode availability | 2.070 | 1.022 | 6.702 | 8.702 | CPU wait on decoder | serial at frame acquire |
| Decoder surface acquisition | 0.016 | 0.008 | 0.052 | 0.070 | CPU | serial |
| Telemetry/frame_data | 0.189 | 0.136 | 0.406 | 0.686 | CPU | serial |
| compose_overlay | 5.270 | 4.543 | 9.896 | 16.333 | CPU | serial |
| chart_upload accounting | 13.191 | 12.524 | 20.699 | 25.561 | CPU path | serial |
| map upload accounting | 2.373 | 2.148 | 3.420 | 7.762 | CPU/upload | serial submission |
| gauge upload accounting | 1.677 | 1.530 | 2.496 | 5.169 | CPU/upload | serial submission |
| native process_frame | 2.480 | 2.182 | 4.071 | 7.693 | native CPU submit | async GPU/VP |
| VideoProcessor CPU submit | 0.580 | 0.548 | 0.931 | 1.281 | CPU submit | GPU async |
| GPU gauge blend submit | 0.106 | 0.091 | 0.191 | 0.564 | GPU submit | async |
| AMF submit/backpressure | 0.442 | 0.353 | 1.398 | 1.942 | CPU/AMF | queue async |
| AMF QueryOutput | 0.225 | 0.201 | 0.843 | 1.024 | CPU/AMF | async |
| packet write | 0.334 | 0.299 | 1.158 | 1.549 | CPU/I/O | serial write |
| Audio mux | 2449 ms total | — | — | — | CPU/process | after video |

`max` is not available per stage from the existing timing schema. The frame accountant exposes p99; no new instrumentation was added.

The `chart_upload` accounting bucket is large although the profile reports no active GPU chart widgets. Therefore the measured fact is a costly chart-related CPU/upload bucket; the exact internal sub-operation is not separately instrumented and must not be guessed.

## E. Serial versus asynchronous work

`compose_overlay`, telemetry preparation, map/gauge preparation and Python/native submission are on the serial frame loop. D3D11 GPU work and AMF output are queued asynchronously. The profiler does not expose a complete end-to-end GPU wait duration; the corresponding GPU wait bucket is `0` because no production blocking wait was recorded.

## F. CPU utilization

Historical per-process and per-thread CPU utilization was not captured by the existing exporter profiler. `NOT AVAILABLE` for this run. Frame accounting does show a serial CPU path and a stable approximately 29–37 ms frame cadence.

## G. GPU utilization

No trustworthy concurrent 3D/video-decode/video-process/video-encode utilization sample was available from the existing runtime diagnostics. `NOT AVAILABLE`; no system monitoring framework was added in 8A.

## H. Upload and copy volume

Full 900-frame run:

| Resource | Total | Per frame |
|---|---:|---:|
| HUD dirty upload | 264,598,180 B | about 0.281 MiB |
| GPU map upload | 1,723,910,400 B | 1.827 MiB |
| GPU gauge upload | 1,231,718,400 B | 1.305 MiB |
| CPU_ABOVE_MAP crop | 96,199,200 B | about 0.102 MiB |

The production path uses dirty/crop updates, not a full-frame HUD upload. `Native HUD CPU copy`, NV12 staging memcpy and `CopyResource submission` timers were zero in the GPU_HUD/D3D11VA path.

## I. Synchronization and flush audit

For the current layout, production `Flush()` calls are approximately 4 per frame:

```text
GPU map resample pass       1
GPU map blend pass          1
GPU gauge blend             1
CPU_ABOVE_MAP blend         1
```

GPU chart blend contributes zero because no GPU chart widget is active. AMF `Flush()` occurs once at end-of-stream, not once per frame.

The GPU timestamp ring reported 7956 `GetData` calls for 884 profiled frames, with 0 not-ready results. This is delayed polling, not a blocking per-frame wait. Production GPU→CPU readback was `NO`; staging `Map`/readback paths are diagnostic-only.

## J. Decode and VideoProcessor

```text
MF video samples / D3D11 surfaces / direct VP frames = 900 / 900 / 900
decoder GPU copy = 0
hardware decode proof = YES
```

Decode availability averaged 2.070 ms with p95 6.702 ms. VP CPU submit averaged 0.580 ms with p95 0.931 ms. GPU completion was not independently blocking in the production path.

## K. AMF

```text
submitted/output       = 900/900
AMF_INPUT_FULL         = 0
retry                  = 0
dropped                = 0
outstanding queue      = average 4.97, median 5, p95 5, max 5
```

The queue stayed stable and did not overflow. AMF is a measurable contributor, but the data does not support classifying the run as AMF-bound by itself. `BYPASS` reached 29.735 FPS, only about 2.45 FPS above the full encoded run.

## L. Telemetry and precompute

```text
PRECOMPUTED build      = 4739.5 ms one-time
precompute memory      = 0.146 MiB
per-frame telemetry    = avg 0.189 ms, p95 0.406 ms
resolver calls/frame   = 4
interpolation/frame    = 6
GPMF lookups/frame     = 3
```

The one-time precompute cost is not the 28.7 FPS steady-state bottleneck.

## M. Map

The map is regenerated/uploaded on all 900 frames. The GPU path is active and ordered correctly. CPU-side map preparation/upload timing was approximately 2.2 ms in the clean 7D profile and 2.373 ms in the fully instrumented 8A run. Turning the GPU map off reduced GPU work but made CPU composition much slower: 22.964 FPS versus 27.282 FPS. This confirms that GPU map is beneficial; it is not evidence that GPU map is the dominant current bottleneck.

## N. Chart

The requested `GPU_SPLIT` path resolved to no active GPU chart widgets for this unchanged layout. Nevertheless, the frame accountant recorded `chart_upload` at median 12.524 ms and average 13.191 ms. The chart ablation improved throughput from 27.282 to 25.192 FPS in this run, so the run-to-run result is noisy and does not by itself isolate the bucket. The large measured chart bucket remains the strongest confirmed target for the next focused audit/optimization, but its exact internal operation is `SUSPECTED`, not fully decomposed.

## O. Gauge

Gauge GPU was active for 900 frames. It uploaded 1.305 MiB/frame; GPU blend submit averaged 0.106 ms. CPU gauge serialization/upload accounting was median 1.530 ms. Disabling the GPU gauge reduced the measured run to 25.557 FPS, but this single-run delta is not treated as a precise causal speedup because the runs are not synchronized and include system variance.

## P. ABOVE layer

```text
active/visible frames     = 900/900
crop bytes total          = 96,199,200 B
average crop              = approximately 106.9 KB/frame
full-frame upload         = NO
GPU→CPU readback          = NO
```

The existing profiler has no independent `above_prepare`, `above_upload` or `above_blend` timing fields. They are therefore `NOT INSTRUMENTED` separately; the native blend is included in native frame processing.

## Q. Ablation matrix

All runs below used the required `GX030120` material, 900 frames, unchanged layout and existing runtime flags.

| Mode | FPS | Total wall | AMF output | Dropped |
|---|---:|---:|---:|---:|
| Full GPU layout | 27.282 | 32.989 s | 900 | 0 |
| Map off (`CPU_REFERENCE`) | 22.964 | 39.191 s | 900 | 0 |
| Charts off | 25.192 | 35.726 s | 900 | 0 |
| Gauge off | 25.557 | 35.215 s | 900 | 0 |
| HUD off | 27.599 | 32.610 s | 900 | 0 |
| AMF bypass, frontend only | 29.735 | 30.268 s | 0 by design | 0 |

There was no existing single runtime flag that provided a pure decode-only/no-telemetry baseline. No new mode was created.

## R. Critical path model

The measured serial frame cadence is approximately:

```text
full encoded total       = 32.989 s / 900 = 36.65 ms/frame end-to-end
full video before mux    = approximately 30.54 s / 900 = 33.93 ms/frame
frontend bypass          = 30.268 s / 900 = 33.63 ms/frame
60 FPS target            = 16.667 ms/frame
```

The stage timings overlap with GPU and AMF queues, so their sum must not be treated as latency. The critical path is a mixed serial CPU-preparation/submission path plus asynchronous VP/AMF progression and final mux. Stable AMF queue occupancy shows that encode participates in throughput, but `AMF_INPUT_FULL=0` rules out explicit encoder backpressure as the sole cause.

## S. Top bottlenecks

1. `chart_upload` accounting bucket: median 12.524 ms, p95 20.699 ms. Confirmed measured cost; exact sub-operation not separately instrumented.
2. CPU `compose_overlay`: average 5.270 ms, p95 9.896 ms.
3. Native/map/gauge serial preparation and submission: map accounting median 2.148 ms, gauge accounting median 1.530 ms, native `process_frame` median 2.182 ms.
4. Decoder surface availability: average 2.070 ms, p95 6.702 ms.
5. AMF and packet path: AMF submit average 0.442 ms, query 0.225 ms, packet write 0.334 ms; plus the stable queue of about five frames.

## T. Classification

```text
MIXED
CPU_SERIAL_PREPARATION = confirmed
GPU_3D/VP              = active, no independent utilization proof
AMF_ENCODE             = measurable contributor, not proven sole limiter
SYNC_BOUND             = not confirmed; no blocking production wait observed
```

## U. 60 FPS feasibility

Current end-to-end effective period is about 34.8–36.7 ms/frame depending on whether the mux-inclusive or steady-state reference is used. The target is 16.667 ms/frame, so the gap is approximately 17.3–20.0 ms/frame. 4K60 is not feasible on the current measured path without removing a substantial serial CPU cost. The largest confirmed candidate is the chart-related CPU/upload bucket, not `compose_overlay` alone.

## V. Confirmed performance issues

| Severity | Path | Measured cost | Finding |
|---|---|---:|---|
| HIGH | chart preparation/upload accounting | median 12.524 ms | Large CPU-side bucket remains despite GPU_SPLIT request; internal split unavailable |
| MEDIUM | CPU compose | avg 5.270 ms | Significant serial overlay composition cost |
| MEDIUM | map/gauge data upload | map 2.148 ms median; gauge 1.530 ms median | Repeated per-frame upload volume |
| LOW | final mux | 2.449 s/run | Adds end-to-end wall time, but occurs after video frames |

## W. Suspected or unavailable issues

- The exact operation represented by `chart_upload` is not isolated by the existing profiler.
- CPU/GPU utilization percentages and per-thread saturation were not available from existing diagnostics.
- Maximum per-stage timing, decoder queue depth and complete GPU execution latency were not exposed.
- No confirmed hidden full-frame copy or production GPU→CPU readback was found.

## X. Recommended ETAP 8B

`ETAP 8B — targeted chart_upload path audit and reduction`.

Scope should be limited to identifying why the unchanged layout records approximately 12.5 ms median in `chart_upload` while `GPU_SPLIT` reports no active GPU chart widgets, then measuring one narrowly scoped reduction. Do not change encoder settings or correctness contracts in that stage.

## Final classification

```text
ETAP 8A = COMPLETE
READ-ONLY AUDIT = PASS
CODE MODIFICATIONS = NONE
```
