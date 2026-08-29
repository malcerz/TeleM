# TeleM — AMD ETAP 5R.2 — Production Rebaseline / 5S Screening

## TASK / STATUS

Production benchmark governance, focused-test baseline repair, fresh SYNC/Q0
rebaseline and conditional 5S screening.

**STATUS: PASS — governance and test baseline complete; NO 5S OPTIMIZATION.**

## BRANCH / HEAD

- Branch: `amd-render`
- HEAD at task start: `3ab0b89`
- Backend: `AMD_NATIVE_D3D11` only

## CANONICAL WORKLOAD

Per `BENCHMARKS.md` and the corrected `AGENTS.md` primary single-file pairing:

```text
Video/GX020079.MP4
Video/GX020079.fit
C:\_DEV\TeleM\def_layout.json
3840x2160
1131 frames
AMD_NATIVE_D3D11
```

All GX010115 + Lunch FIT measurements made during the interrupted investigation
were excluded from this baseline and from the screening decision.

## PRODUCTION DEFAULT / BENCHMARK GOVERNANCE

Added the canonical runner mode `--production-defaults`. It removes governed
ambient AMD overrides, records every ignored value, and resolves:

```text
SYNC / queue 0 / VP REFERENCE / VP pool 8 / AMF REFERENCE
GPU map / GPU_SPLIT charts / GPU gauge / GPU_HUD / DIRTY upload / FUSED NV12
ABOVE batched OFF / ABOVE dirty EXACT / ABOVE upload DIRECT
```

Explicit experiments use repeatable `--set-amd NAME=VALUE`; those profiles are
marked `EXPLICIT_ABLATION`. Every exporter benchmark profile now contains the
effective configuration, workload identity, layout SHA-256 and a stable
configuration/workload fingerprint. The fingerprint is independent of output
filename.

`BENCHMARKS.md` explicitly separates real production defaults from historical
ASYNC/Q2/STATIC_CACHE/DRAIN_READY experiments. GUI defaults were not changed.

## AMBIENT ENV TEST

PASS. An injected ambient `ASYNC/Q2/STATIC_CACHE/DRAIN_READY/CPU_REFERENCE`
environment was ignored by `--production-defaults`; the profile reported
`SYNC/Q0/REFERENCE/REFERENCE/GPU` and recorded the ignored values.

## TEST BASELINE BEFORE / FAILURE TRIAGE

5R.1 focused result was 42 passed / 8 failed. The failures were triaged as:

- stale `PreparedFrame` fixtures missing `map_heading`;
- stale ABI-8 mocks against the current ABI-9 contract;
- stale fused-compositor source assertion;
- visible-to-none test asserting the old blank semantics and comparing a
  reused mutable image instead of a snapshot;
- non-canonical shader-variant parity harness failures (experimental kernels,
  unrelated GX030120/FIT pairing), not production regressions.

## STALE TEST FIXES / REAL BUGS FOUND

Fixed the ABI-9 mocks, `PreparedFrame` fixture, visible-to-none snapshot
assertion, and fused-source assertion. The shader-variant module is explicitly
skipped from the production baseline pending reconstruction on the canonical
workload. No AMD production renderer bug was found by this triage.

## TEST BASELINE AFTER

Focused suite: **48 passed, 5 skipped**. The five skips are the documented
non-canonical shader-variant harness. No unexpected failures remain.

## PROFILER OVERHEAD

NOT TESTED as a new dedicated 5R.2 A/B. The measured baseline used native frame
accounting for truth data; profiler-overhead conclusions from earlier stages
were not reused as fresh 5R.2 measurements.

## SYNC CANONICAL BASELINE

One warmup plus five measured runs, all 1131/1131 frames:

| run | total from export start (ms) | video render (ms) | render FPS | user effective FPS |
|---:|---:|---:|---:|---:|
| 1 | 30072.909 | 27907.096 | 40.527 | 37.609 |
| 2 | 30538.008 | 28163.654 | 40.158 | 37.036 |
| 3 | 29925.422 | 27678.111 | 40.863 | 37.794 |
| 4 | 30505.013 | 28419.497 | 39.797 | 37.076 |
| 5 | 31023.377 | 28863.557 | 39.184 | 36.456 |
| **mean** | **30412.946** | **28206.383** | **40.106** | **37.194** |

Total-wall variance: CV **1.274%**, min **29925.422 ms**, max **31023.377 ms**.
All five profiles share fingerprint
`368da1af2cfa05a105995ad65a677a25290a1a699e7265b9af8de81c31c97bd8`.

## SYNC FRAME ACCOUNTING / VP / AMF

The canonical profile reports source/requested/decoded/native/VP/AMF output and
muxed frames all **1131**, with MF null samples **0** and stream ticks **0**.
SYNC queue waits are **0.0 ms**; VP pool is **8**, state is REFERENCE, and AMF
query is REFERENCE. Map GPU was active for 1131 frames. Audio was present and
remuxed.

## ABOVE TOP 15 / CPU-SYNC TOP 15

Representative five-run timing averages identify the active critical path:

```text
pipeline_total                         14.621 ms
consumer_native_call                   10.236 ms
producer_prepare                       10.277 ms
above_total                             7.277 ms
above_compose                           6.121 ms
consumer_upload                         3.405 ms
map_cpu_upload                          1.209 ms
MF ReadSample/decode availability       0.846 ms
HUD texture upload                      0.152 ms
AMF QueryOutput                         0.160 ms
AMF submit/backpressure                 0.390 ms
VideoProcessor CPU submit               0.254 ms
PIL/buffer preparation                  0.063 ms
```

The largest actionable CPU-side region is ABOVE compose/region upload; no
candidate tested here produced the required end-to-end headroom.

## VARIANCE TOP 10 / HEADROOM CANDIDATES

The five-run variance screen is dominated by end-to-end/native-call timing and
not by a stable single micro-stage. Three 300-frame candidates were screened
against production REF, each with warmup plus three measured runs:

| candidate | mean total (ms) | delta vs REF |
|---|---:|---:|
| REF | 9938.78 | 0.000% |
| `AMD_ABOVE_BATCHED=1` | 9979.22 | −0.407% |
| `AMD_ABOVE_FINE_DIRTY=1` | 9987.76 | −0.493% |
| `AMD_HUD_BUFFER_MODE=OPTIMIZED` | 9930.91 | **+0.079%** |

All candidates accounted for 301/301 native, submitted, output and muxed
frames. No candidate reached **+3% E2E headroom**.

## ABLATION REF / A / B / C

- REF: production defaults, 9938.78 ms mean.
- A: ABOVE batched, slower by 0.407%.
- B: fine dirty, slower by 0.493% and higher short-run variance.
- C: optimized HUD buffer, statistically neutral/slightly slower by 0.079%.
- Selected target: **none**.

## CONDITIONAL 5S

**NO 5S OPTIMIZATION.** The ≥3% E2E gate was not met. No production code was
changed for a 5S target.

## PARITY / TEMPORAL / VISUAL / HDR / OUTPUT

- Production-focused renderer tests: PASS.
- Temporal/ghosting and map-underneath regression coverage in the existing
  focused suite: PASS where exercised.
- New five-run encoded-output pixel parity: NOT TESTED.
- HDR output comparison: NOT TESTED in this governance/rebaseline stage.
- Output accounting and mux continuity: PASS, 1131/1131 and audio present.

## FULL A/B / DECISION

No full 1131-frame A/B was authorized after the 300-frame candidates failed the
headroom gate. Decision: retain current production defaults; do not start 5S.

## FINAL CONFIG / NEXT TRUE BOTTLENECK / ETAP 5T

Final canonical benchmark configuration remains SYNC/Q0/REFERENCE/pool8/AMF
REFERENCE with the validated GPU map, GPU_SPLIT charts, GPU gauge, GPU_HUD,
DIRTY upload and FUSED NV12 path. The next true bottleneck is the measured
ABOVE/consumer-native critical path, but it is deferred to a separately scoped
future stage. ETAP 5T: **not started**.

## FILES / PRESERVED

Changed for this task:

- `AGENTS.md` benchmark-discipline section aligned to the authoritative
  canonical dataset rules.
- `BENCHMARKS.md` production-default governance documentation.
- `src/ffmpeg/amd_config.py` shared resolver and fingerprinting.
- `src/ffmpeg/amd_native_exporter.py` profile governance metadata.
- `scratch/run_etap5g_export.py` production-defaults and explicit-ablation CLI.
- focused test fixes and `tests/test_amd_benchmark_governance.py`.

Pre-existing dirty-worktree changes, including `def_layout.json`, other AMD
work, reports and unrelated backend files, were preserved. NVIDIA and Intel
paths were not modified.

## FINAL SUMMARY

**PASS:** governance, canonical primary workload, frame accounting and focused
test baseline. **NO 5S:** no candidate met the 3% E2E gate. **NOT TESTED:** new
full pixel parity and profiler-overhead A/B.
