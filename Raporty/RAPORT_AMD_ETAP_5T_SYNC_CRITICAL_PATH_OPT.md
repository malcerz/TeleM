# TeleM — AMD ETAP 5T — SYNC Critical-Path Split

## TASK:

AMD ETAP 5T — SYNC critical-path split, ABOVE vs native headroom proof and conditional single optimization.

## STATUS:

**PASS — instrumentation and attribution complete. NO PRODUCTION OPTIMIZATION.**

## BRANCH / HEAD:

- Branch: `amd-render`
- HEAD: `3ab0b89`
- Backend: `AMD_NATIVE_D3D11`

## CANONICAL:

```text
video = Video/GX020079.MP4
fit = Video/GX020079.fit
layout = C:\_DEV\TeleM\def_layout.json
frames = 1131
config fingerprint = 368da1af2cfa05a105995ad65a677a25290a1a699e7265b9af8de81c31c97bd8
```

GX010115 + Lunch FIT measurements were excluded.

## PROFILER:

Required 300f OFF/ON/OFF/ON/OFF/ON probe:

```text
OFF video_render_wall mean = 7977.957 ms
ON  video_render_wall mean = 7931.495 ms
overhead = -0.582%
gate = PASS (<=3%)
```

## SYNC FRAME:

Added diagnostic-only `AMD_SYNC_FRAME_ACCOUNTING=1`. It measures one parent
from before CPU preparation through normal synchronous native/output handling.
The parent is split into sequential `producer_prepare`, `consumer_setup`,
`decode_read_sample`, `upload`, `native_process_call`,
`consumer_post_native`, and `residual_other` stages. No GUI default, encoder
setting, GPU readback, image semantics, or other backend was changed.

Fresh canonical 1131f diagnostic run:

```text
parent avg / median / p95 / p99 = 24.840 / 18.225 / 46.750 / 135.066 ms
children sum avg / median         = 24.823 / 18.214 ms
residual avg / median              = 0.016 / 0.013 ms
parent-child error                = 0.066%
```

Children average: producer 10.244 ms, setup 0.022 ms, decode 0.841 ms, upload
3.927 ms, native process 9.733 ms, post-native 0.056 ms.

## ABOVE:

Separate 100f allocation/per-widget diagnostic:

```text
above parent = 6.166 ms avg
other_compose_bookkeeping = 0.827 ms avg
accounting error = 0.000%
```

Per-widget averages:

```text
alt_text 1.828 ms; speed_text 1.551 ms; fit_distance_text 0.507 ms
fit_heart_rate_text 0.364 ms; lean_indicator 0.356 ms
fit_cadence_text 0.236 ms; fit_gopro_battery_text 0.213 ms
iso_text 0.119 ms; exposure_text 0.081 ms; temp_text 0.081 ms
custom_text_loop 0.002 ms
```

The global ABOVE residual is measured rather than hidden as a large `other`
bucket. Allocation audit found producer allocated blocks averaging 519.3/frame
(median 148, p95 320.7); consumer median was 33/frame. No allocation reuse was
implemented.

## UPLOAD:

Representative canonical averages:

```text
ABOVE 1.754 ms; MAP 1.247 ms; GAUGE 0.378 ms; CHART 0.000 ms; HUD 0.139 ms
consumer_upload total 3.925 ms
```

Gauge transfer was 298,482,020 bytes total (0.252 MiB/frame), 2252 calls, with
1121 regional and 10 full-refresh frames. No chart CPU readback occurred.

## CONSUMER NATIVE:

Native frame-accounting CSV, fresh SYNC:

```text
process_frame total avg/median/p95/p99/max = 9.710 / 2.040 / 28.272 / 123.123 / 128.960 ms
surface acquire                         = 0.035 / 0.031 / 0.060 / 0.073 ms
VP total                                = 8.930 / 1.268 / 27.402 / 122.527 ms
VP setup                                = 8.682 / 1.018 / 27.131 / 122.269 ms
VP SetStream                            = 8.679 / 1.016 / 27.126 / 122.266 ms
VP Blt                                  = 0.188 / 0.171 / 0.269 / 0.330 / 4.251 ms
AMF SubmitInput                         = 0.366 / 0.297 / 0.468 / 0.723 ms
AMF QueryOutput                         = 0.158 / 0.148 / 0.266 / 0.354 ms
packet write                            = 0.123 / 0.111 / 0.237 / 0.352 ms
```

`VP SetStream`/VP setup is API-wall/driver-blocking time, not CPU rendering.
The low-median, high-tail native variance is concentrated there. VP Blt has no
medium, stall, or severe tail in fresh SYNC data; that direction is closed.

## BLOCKING/API WALL TOP10:

1. VP SetStream/setter-format wall: p95 27.126 ms, p99 122.266 ms.
2. VP setup total: p95 27.131 ms, p99 122.269 ms.
3. VP total: p95 27.402 ms, p99 122.527 ms.
4. process-frame total: p95 28.272 ms, p99 123.123 ms.
5. AMF SubmitInput: p95 0.468 ms, p99 0.723 ms.
6. VP submit window: p95 0.346 ms, p99 0.405 ms.
7. AMF QueryOutput: p95 0.266 ms, p99 0.354 ms.
8. packet write: p95 0.237 ms, p99 0.352 ms.
9. VP Blt: p95 0.269 ms, p99 0.330 ms.
10. surface acquire: p95 0.060 ms, p99 0.073 ms.

## ACTIVE TOP15 / VARIANCE TOP10:

Mutually-exclusive active path is producer preparation/ABOVE, native process,
upload and decode. Native nested attribution must not be added to that parent
ranking. Variance is dominated by VP SetStream and VP setup; it is not dominated
by ABOVE leaf rendering, VP Blt, AMF query, or packet write.

## HEADROOM CANDIDATES:

Fresh canonical 300f, one warmup plus three measured runs per case, with the
SYNC parent enabled:

| case | mean video wall | delta vs REF | parent frames | parent error |
|---|---:|---:|---:|---:|
| REF | 7961.485 ms | 0.000% | 301 | 0.075% |
| A `AMD_ABOVE_BATCHED=1` | 7915.091 ms | −0.583% | 301 | 0.076% |
| B `AMD_ABOVE_FINE_DIRTY=1` | 7909.827 ms | −0.649% | 301 | 0.076% |
| C `AMD_HUD_BUFFER_MODE=OPTIMIZED` | 7873.043 ms | **−1.111%** | 301 | 0.075% |

All cases maintained 301/301 native, submitted, output and muxed frames. None
reached the required ≥3% E2E gate.

## SELECTED TARGET:

- None.
- 5T optimization authorized: **NO**.
- Kill switch: **NOT APPLICABLE**.

## PARITY / TEMPORAL / VISUAL / HDR / FULL A/B:

- Focused production suite: **48 passed, 5 documented skips**.
- Existing renderer parity/ghosting safeguards: PASS where exercised.
- New full pre-encode pixel parity: **NOT TESTED**; no candidate passed the gate.
- New temporal 100-frame A/B: **NOT TESTED**.
- Candidate HDR/color comparison: **NOT TESTED**; no native surface change.
- Full paired A/B: **0 pairs**, not authorized.

## DECISION:

**NO PRODUCTION OPTIMIZATION.** Keep SYNC/Q0/VP REFERENCE/pool 8/AMF
REFERENCE, GPU map, GPU_SPLIT charts, GPU gauge/lean, GPU_HUD, DIRTY upload,
FUSED NV12 and ABOVE batched OFF. Do not return to historical ASYNC hypotheses.

## NEXT TRUE BOTTLENECK:

VP stream-state setup / `SetStream` driver/API wall and its p95/p99 tail. A
future diagnostic stage may isolate same-semantics setter caching or ordering;
do not increase the pool blindly.

## FILES CHANGED:

- `src/ffmpeg/amd_native_exporter.py` — SYNC parent accounting and ABOVE global accounting fix.
- `Raporty/RAPORT_AMD_ETAP_5T_SYNC_CRITICAL_PATH_OPT.md` — this report.
- Diagnostic artifacts under `scratch/etap5t_*`.

## PRE-EXISTING PRESERVED:

YES. Existing dirty-worktree changes, `def_layout.json`, governance/test fixes,
and other backend files were preserved. NVIDIA, Intel and generic CPU paths
were not changed.
