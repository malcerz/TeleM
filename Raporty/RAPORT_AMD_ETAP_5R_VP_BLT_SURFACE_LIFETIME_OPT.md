# TeleM — AMD ETAP 5R — VideoProcessorBlt stall / surface-lifetime truth

## TASK

Determine whether reuse of the persistent D3D11 Video Processor output pool is
too early, and whether increasing the pool produces a safe, reproducible
production win.

## STATUS

COMPLETE — NO PRODUCTION OPTIMIZATION.

The experiment did not prove a surface-reuse hazard. P10 and P12 were rejected
by resource creation and safely degraded to an effective pool of 8, so there is
no valid larger-pool dose-response. The production default remains pool 8.

## BRANCH HEAD

Branch `amd-render`, HEAD `3ab0b89` at task start. The worktree contained
pre-existing changes; they were preserved.

## CANONICAL WORKLOAD

The fresh baseline used `Video/GX020079.mp4`, `Video/GX020079.fit`,
`def_layout.json`, 3840x2160, AMD_NATIVE_D3D11, ASYNC queue depth 2,
STATIC_CACHE, DRAIN_READY, GPU map/GPU_SPLIT/gauge/HUD/FUSED NV12, and
`AMD_ABOVE_BATCHED=0`. The runner produced 1131 accounted frames. The pool
screening used the same configuration for 300-frame runs (the runner emitted
301 frames).

## PROFILER

The native frame accounting CSV and optional queue truth diagnostics were
enabled without GPU readback, blocking `GetData`, or per-frame D3D11 flush.
Four 300-frame runs, OFF/ON/OFF/ON, gave render walls:

| run | render wall |
|---|---:|
| OFF-1 | 7691.378 ms |
| ON-1 | 7774.010 ms |
| OFF-2 | 7802.062 ms |
| ON-2 | 7749.301 ms |

OFF mean was 7746.720 ms and ON mean 7761.656 ms: +0.19%, within the 3%
overhead gate.

## VP RESOURCE ARCHITECTURE

The pipeline owns a persistent array of NV12 `ID3D11Texture2D` output surfaces,
one Video Processor output view per surface, and the corresponding Y/UV UAVs.
Each frame selects a slot modulo the effective pool size, creates a temporary
input view for the decoder P010 texture, performs `VideoProcessorBlt`, then
returns the selected NV12 texture to the caller. The native caller submits
that same texture directly to AMF.

## VP OUTPUT SURFACE LIFETIME

The pool retains its COM references until pipeline destruction. The per-frame
output pointer is borrowed by the caller; there is no explicit per-frame
`Release` of the pool-owned output surface. The current implementation has no
GPU fence or completion query before a slot is selected again. Therefore COM
ownership is correct, but asynchronous GPU reuse safety is not independently
proven by reference counts.

The existing lifecycle counter records slot bookkeeping and pool creation /
release counts. It does not establish GPU completion. No production lifetime
change was made.

## AMF RESOURCE LIFETIME

`D3D11AMFEncoder::SubmitTexture` wraps the borrowed D3D11 texture with
`CreateSurfaceFromDX11Native`, sets PTS, and calls `SubmitInput`. The local
`AMFSurfacePtr` is released after the call; AMF may retain the native resource
asynchronously. `AMF_INPUT_FULL` was not observed in the canonical runs.
`Drain()` is used only at end-of-stream; there is no per-frame AMF flush.

## BASELINE VP BLT STATS AND CLASSES

Fresh P8 canonical measured runs:

| run | render wall | VP Blt mean | median | p95 | max |
|---|---:|---:|---:|---:|---:|
| 1 | 28846.549 ms | 16.436 ms | 9.155 ms | 41.599 ms | 151.112 ms |
| 2 | 28482.708 ms | 16.200 ms | 7.211 ms | 38.700 ms | 164.398 ms |
| 3 | 28694.580 ms | 16.357 ms | 7.706 ms | 42.143 ms | 148.180 ms |

P8 run 1 classes (`fast <8`, `medium 8–20`, `stall 20–50`, `severe >50`
ms): 547/1131 fast (48.4%), 315 medium (27.9%), 217 stall (19.2%), and
52 severe (4.6%).

## POOL INDEX TABLE — P8 RUN 1

| slot | frames | VP Blt mean | p95 |
|---:|---:|---:|---:|
| 0 | 142 | 22.34 ms | 120.82 ms |
| 1 | 142 | 13.74 ms | 35.61 ms |
| 2 | 142 | 16.72 ms | 36.32 ms |
| 3 | 141 | 12.40 ms | 34.83 ms |
| 4 | 141 | 19.05 ms | 54.27 ms |
| 5 | 141 | 13.37 ms | 39.74 ms |
| 6 | 141 | 17.76 ms | 40.36 ms |
| 7 | 141 | 16.08 ms | 97.25 ms |

## REUSE / MODULO-8 CORRELATION

Steady-state reuse distance is eight frames for P8 slots. The modulo-8 means
match the pool-slot pattern above, but the high variance is not isolated to a
single modulo class and no time-to-completion signal is available in the CSV.
`time_since_previous_use` is therefore NOT AVAILABLE. A surface-reuse hazard
is NOT PROVEN.

## AMF CORRELATION

Canonical runs had no `AMF_INPUT_FULL`, no retry path, and approximately one
AMF output per input frame. AMF submission/query timings are much smaller than
the VP Blt tail; this does not identify AMF as the cause of the VP stall.

## PACKET CORRELATION

In P8 run 1, the next-frame VP Blt mean was 23.04 ms after packet writes below
1 ms versus 11.38 ms after writes at least 1 ms. This is an observational
correlation in a serialized wall-clock trace, not evidence that packet writing
causes the VP stall; packet activity occurs after the VP operation and cannot
prove a surface-lifetime dependency.

## LOCAL SANITY

All measured runs produced complete encoded output with 1131 accounted frames;
no AMF input-full/retry failure was observed. No GPU readback or per-frame
flush was added. A/V and PTS behavior were not changed.

## POOL SCREENING — 300 FRAMES, 1 WARMUP + 2 MEASURED

| requested pool | effective pool | mean render wall | mean VP Blt | measured walls |
|---:|---:|---:|---:|---:|
| P6 | 6 | 8046.960 ms | 15.154 ms | 7985.572 / 8108.347 ms |
| P8 | 8 | 7975.442 ms | 14.888 ms | 7975.998 / 7974.886 ms |
| P10 | 8 | 7928.644 ms | 14.796 ms | 7917.434 / 7939.853 ms |
| P12 | 8 | 7867.947 ms | 14.962 ms | 7889.214 / 7846.680 ms |

P10 and P12 logs explicitly report `effective pool size = 8 (requested 10/12)`.
Consequently the apparent P10/P12 improvement is not a larger-pool result.
P6 versus P8 is not a monotonic dose-response and was not a production win.

## MEMORY COST

At 3840x2160 NV12, the theoretical payload is about 11.86 MiB per surface:
P6 ≈71.2 MiB, P8 ≈94.9 MiB, P10 ≈118.6 MiB, and P12 ≈142.3 MiB, before
driver alignment and view overhead. P10/P12 allocation failure prevented this
additional memory from being committed in the experiment.

## VP STATE COUNTERS

The native trace records pool index, decoder texture identity, array index,
state signature, skipped setters, and AMF counters. STATIC_CACHE remained
active; no state invalidation or setter anomaly was found in the accounting
artifacts. The decoder texture identity was constant in the captured trace,
so input identity did not explain the slot pattern.

## INPUT-SIDE HAZARD

NOT PROVEN. The present trace lacks GPU completion timestamps/fences and cannot
distinguish an actual producer-side resource wait from a driver-internal VP
queue or input-surface hazard. A future diagnostic should add non-blocking
identity/completion evidence around the VP submission without changing the
production queue or synchronization policy.

## DECISION

NO PRODUCTION OPTIMIZATION. Do not increase the default pool, change queue
depth, add a per-frame flush, or alter AMF policy. The required conditions — a
valid pool-size dose-response, at least 3% canonical video-wall improvement,
and unchanged semantics — were not met.

## FILES CHANGED

For this ETAP, the diagnostic control was added in:

- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp` — accepts diagnostic
  requests 6/8/10/12 while retaining default 8.
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp` — tries requested
  12/10/8/6/4 candidates with safe fallback; no default change.
- This report.

The native target was rebuilt successfully with Ninja. Pre-existing changes in
the worktree, including earlier ETAP compositor and accounting work, were
preserved and were not treated as 5R optimization changes.

## PRE-EXISTING PRESERVED

No NVIDIA, Intel, queue-default, AMF-policy, map, chart, gauge, HUD, layout,
or CPU-ABOVE production behavior was changed by the 5R decision.

## NEXT STAGE

If investigation continues, instrument the VP/input submission path with
non-blocking completion/identity evidence and separate driver queue waits from
surface reuse. Do not promote a larger pool based on the present data.

