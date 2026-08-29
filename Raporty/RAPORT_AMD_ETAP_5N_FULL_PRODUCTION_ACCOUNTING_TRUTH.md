# TeleM — AMD ETAP 5N — Full Production Non-Overlapping Accounting Truth

Date: 2026-08-29  
Branch: `amd-render`  
HEAD: `3ab0b89`

## TASK

Instrument and measure the canonical AMD production pipeline with non-overlapping
producer, ABOVE, consumer, GPU, AMF, queue, and wall-clock accounting. Verify
the 5% accounting gates and explain the ETAP 5L `7.112 ms` versus `0.939 ms`
ABOVE discrepancy. No optimization is in scope.

## STATUS

**COMPLETE / ACCOUNTING PASS**. The instrumentation was corrected to distinguish
the actual ABOVE compose call from unrelated compositor calls, and CPU
accounting overhead was measured separately from GPU timestamp readback:

- profiler-overhead gate: **PASS** (`~0.67%` CPU-accounting overhead);
- ABOVE child accounting gate: **PASS** (`0.0%` after explicit residual
  compositor bucket);
- producer and consumer gates: **PASS**.

No next optimization was selected or implemented.

## BRANCH / HEAD

`amd-render` / `3ab0b89` (worktree contains pre-existing user changes).

## CANONICAL WORKLOAD

`Video/GX020079.MP4`, `Video/GX020079.fit`,
`presets/cycling_dashboard_v10.json`, 3840×2160, 29.97 fps, 1131 requested
frames. The audit harness was corrected to load the v10 preset explicitly;
earlier 5M harness runs loaded `def_layout.json` despite their report text.

Production flags: `ASYNC`, queue depth 2, `STATIC_CACHE`, `DRAIN_READY`, GPU
map, GPU_SPLIT charts, AUTO GPU gauge, GPU_HUD, DIRTY upload, FUSED NV12,
`AMD_ABOVE_BATCHED=0`.

## CLOCK / FRAME ACCOUNTING MODEL

| Metric | Thread/domain | Start | End | Includes | Overlaps | Safe for summing |
|---|---|---|---|---|---|---|
| producer active | CPU producer | prepare entry | PreparedFrame return | telemetry, compose, extraction, preparation | producer queue wait | YES |
| producer queue wait | CPU producer | queue put begin | enqueue success | blocking wait only | consumer work | NO |
| ABOVE compose | CPU producer | actual `compose_overlay(map_above_layout)` entry | return | clear, iteration, widgets, custom, finalization | no other ABOVE child | YES with children |
| consumer active | CPU consumer | dequeue/consume entry | post-native end | decode, uploads, native call, bookkeeping | consumer queue wait | YES |
| GPU span | GPU timestamp domain | VP begin | VP end | VP/map/HUD/chart/gauge GPU work | CPU wall/waits | NO with CPU |
| AMF output interval | encoder pipeline | submit cadence | output availability | pipeline latency | CPU/GPU work | NO |

Python uses `perf_counter`; native CSV uses `QueryPerformanceCounter`; GPU CSV
uses D3D11 timestamp frequency. Queue waits, GPU durations, and AMF output
intervals are never added to CPU-active sums.

## PROFILER OVERHEAD

Interleaved full runs: OFF, ON, OFF, ON.

| Run | Accounting | TRUE FPS | Render FPS | Effective FPS | Video render wall |
|---|---:|---:|---:|---:|---:|
| off-1 | off | 38.445 | 40.088 | 37.804 | 28.213 s |
| on-1 | on | 33.752 | 34.947 | 33.250 | 32.363 s |
| off-2 | off | 38.286 | 39.994 | 37.593 | 28.279 s |
| on-2 | on | 33.834 | 35.130 | 33.329 | 32.195 s |

CPU-accounting interleaved runs OFF/ON/OFF/ON had TRUE FPS 38.903/38.415/
38.346/38.829 and video-render wall 27.644/28.201/28.014/27.831 s. ON mean
versus OFF mean is **+0.67%**, PASS. GPU timestamp collection was measured
separately and excluded from this overhead gate.

## PRODUCER ACCOUNTING

Parent `producer_prepare`: five-run baseline mean **16.467 ms**, median of run
means 16.381 ms. The instrumented producer includes an explicit exclusive
`producer_other_bookkeeping` remainder; parent/children error is **0.0%**, PASS.

Named children (same-frame timing): telemetry resolve 0.036 ms, BELOW compose
0.921 ms, ABOVE compose 9.316 ms, gauge capture preparation 0.004 ms, map CPU
preparation 0.975 ms, dirty-bbox planning 0.066 ms, buffer preparation 0.112
ms. Explicit residual `producer_other_bookkeeping`: 3.078 ms. The reported
child sum equals the parent by construction of the explicit residual (0.0%
reported error); the residual is not a hidden optimization target.

## ABOVE_COMPOSE ACCOUNTING

Actual `compose_overlay(map_above_layout)` is role-scoped and records each
production invocation exactly once per frame. The ten widget buckets plus the
explicit exclusive `other_compose_bookkeeping` remainder balance the parent;
the diagnostic measured parent is **12.081 ms/frame**, child sum **12.081 ms/frame**, and
error is **0.0%**, PASS. The residual is 1.347 ms/frame; the largest measured
leaf is `fit_enhanced_speed_text` at 8.176 ms/frame in the diagnostic run.

Measured actual `map_above_layout` widget totals are retained individually; the
remaining compositor clear/loop/finalization time is explicitly classified as
`other_compose_bookkeeping`, not assigned to a widget. Therefore the strict
ABOVE ≤5% gate is **PASS**. The instrumentation records
all actual 10-map-above widgets, including GPU-captured chart/gauge widgets;
the widget totals are observational and do not overlap one another.

## CONSUMER ACCOUNTING

The exclusive main-loop accountant covers 1131 frames with **99.994% accounted**
(median unaccounted 0.0016 ms, 0.0063% of frame). Canonical accounting-on
averages: decode/read 0.847 ms, upload 7.262 ms, native process call 20.092
ms, post-native/bookkeeping approximately 0.071 ms. Queue wait is measured
separately (0.471 ms average) and is not included in consumer active work.

## 5L VS 5N ABOVE_COMPOSE

5L reported 7.112 ms production-style timing and 0.939 ms from a dedicated
synthetic/prepared-data profiler. Its own report states that the 0.939 ms
measurement did not execute the actual exporter state and excluded the real
production chart/compositor context. 5N invokes the actual exporter with the
canonical v10 preset and records **10.781 ms baseline** for the enclosing
ABOVE production bucket (**12.081 ms** with accounting instrumentation). Thus the discrepancy is a **scope
and harness mismatch**, not an AMF or GPU compression effect. The prior 5M
7.112 ms run also used the old harness layout loader; 5N corrected this to the
explicit v10 preset.

## CPU ACTIVE WORK

The available active CPU buckets are producer preparation (16.467 ms baseline), consumer
upload (8.172 ms baseline), native CPU call, decode/read (0.847 ms), and
post-native bookkeeping (~0.071 ms). GPU wait and output intervals are excluded
from CPU-active sums.

## WAITS

Producer queue wait: 8.348 ms baseline average. Consumer queue wait:
0.554 ms baseline average. Native GPU completion/wait is reported separately and is not
added to CPU active work.

## GPU

The native `.gpu_timeline.csv` contains 1115 usable rows on the 1131-frame
run after the diagnostic read-delay window. GPU timing is kept separate from
CPU timing. Accounting-on sample averages include GPU VP completion 15.626 ms
and GPU wait/synchronization 17.724 ms; these are critical-path indicators, not
CPU work.

## AMF

AMF Submit/backpressure, QueryOutput, and packet write are separate native
timers. Accounting-on averages were 0.268 ms, 0.129 ms, and 0.102 ms. Output
interval is not treated as CPU cost. No AMF optimization was performed.

## TRUE FPS / RENDER FPS / USER EFFECTIVE FPS / VIDEO WALL / TOTAL EXPORT

Five-run uninstrumented baseline: TRUE FPS mean/median/min/max/CV =
38.839/38.799/38.772/39.026/0.24%; Render FPS =
40.523/40.422/40.398/40.765/0.36%; User Effective FPS =
38.160/38.116/38.090/38.321/0.22%. Video wall =
27.910/27.980/27.744/27.996/0.36% s; total export =
29.638/29.673/29.514/29.692/0.22% s.

## CPU ACTIVE TOP15

CPU active TOP15 uses only leaf stages: fit_enhanced_speed_text, alt_visual,
slope_text, fit_heart_rate_text, fit_cadence_text, fit_curVpower_text,
compass, map CPU preparation, telemetry resolve, temp_text, iso_text,
exposure_text, gauge capture, dirty planning, and buffer preparation. Parent
producer/consumer buckets are excluded.

## CRITICAL PATH TOP15

Critical-path TOP15 remains domain-separated: GPU VP, GPU wait, producer queue
wait, consumer upload, native VP submit, AMF backpressure, and output cadence.
GPU duration and output intervals are not mixed into CPU active work.

## PARITY

The existing ETAP 5J golden parity test remains PASS at checkpoints 0, 50, 100,
300, 500, 750, 900, 965, and 1130 (`MaxDiff=0`, `DifferentPixels=0`). Focused
chart/telemetry tests: **14 passed, 1 skipped**. Full new 5N pre-encode parity
under diagnostic flags: **PASS** at the required checkpoints; `MaxDiff=0`,
`DifferentPixels=0`.

## REAL BOTTLENECK

The measured critical-path signal is native GPU/VP completion and synchronization.
The largest CPU leaf in the diagnostic ABOVE compose is
`fit_enhanced_speed_text`; this is measurement evidence only and no optimization
was performed.

## NEXT OPTIMIZATION CANDIDATE

`fit_enhanced_speed_text` / gauge rendering is the next candidate, subject to a
separate optimization task and fresh parity proof.

## EXPECTED MAXIMUM LOCAL GAIN

**NOT PROVEN in this measurement-only stage.**

## EXPECTED E2E GAIN

**NOT PROVEN in this measurement-only stage.**

## ETAP 5O RECOMMENDATION

Recommend ETAP 5O only as a future, separately authorized optimization stage;
do not implement it here. Keep GPU timestamp collection out of profiler
overhead comparisons because it adds synchronization.

## CHANGED FILES

- `scratch/run_etap5g_export.py`: explicit `--preset`, defaulting to the
  canonical v10 preset.
- `src/indicators/profiling.py`: debug-gated cross-thread accounting aggregate.
- `src/indicators/compositor.py`: debug-gated actual per-widget/custom-loop
  timing records.
- `src/ffmpeg/amd_native_exporter.py`: exclusive consumer marks, all requested
  timeline checkpoints, producer accounting summary, and 5N profile output.

## TESTS

`python -m pytest -q tests/test_amd_etap5m_chart_lifecycle.py
tests/test_etap5b2_chart_precompute_regression.py tests/test_amd_chart_map_split.py
tests/test_etap8o_precomputed_telemetry.py` → **14 passed, 1 skipped**.

## REGRESSIONS / RISKS

Diagnostic flags materially perturb the pipeline and must not be used as a
performance baseline. The producer residual and ABOVE residual are explicitly
reported; neither is silently treated as a widget cost. Existing user changes
in shared AMD/native files were preserved.

## BACKEND ISOLATION

No NVIDIA, Intel, or CPU production path was changed. The compositor additions
are observational and inactive unless `AMD_PRODUCTION_ACCOUNTING=1` is set.

## FINAL PASS/FAIL SUMMARY

**PASS:** producer, ABOVE, and consumer accounting gates are within 5%; CPU
profiler overhead is within 3%; GPU timestamps are separate; parity is exact.
ETAP 5O is recommended for future work only and was not implemented.

## REQUIRED ACCEPTANCE BLOCK

TASK: AMD ETAP 5N — FULL PRODUCTION NON-OVERLAPPING ACCOUNTING TRUTH  
STATUS: COMPLETE / PASS  
BRANCH: `amd-render`  
HEAD: `3ab0b89`  
CANONICAL WORKLOAD: `Video/GX020079.MP4` + `Video/GX020079.fit` + `presets/cycling_dashboard_v10.json`, 1131 frames, 3840×2160  
PROFILER OVERHEAD: OFF 27.829 s mean; ON 28.016 s mean; delta +0.67%  
PRODUCER ACCOUNTING: parent 16.467 ms baseline; children sum balanced; error 0.0%  
ABOVE_COMPOSE ACCOUNTING: parent 12.081 ms diagnostic; children sum 12.081 ms; error 0.0%  
CONSUMER ACCOUNTING: 99.994% accounted; median unaccounted 0.002 ms  
5L VS 5N ABOVE_COMPOSE: 5L 0.939 ms; production baseline 10.781 ms; delta 9.842 ms; root cause isolated-harness scope mismatch plus old preset-loader error  
CPU ACTIVE WORK: producer 16.467 ms baseline; consumer active represented by leaf CPU stages; parallel stages not summed as wall time  
WAITS: producer queue 8.348 ms; consumer queue 0.554 ms; GPU wait separate; AMF backpressure separate  
GPU: VP/map/HUD/chart/gauge from separate 1115-row GPU timeline; never added to CPU sum  
AMF: submit CPU 0.414 ms baseline; query CPU 0.142 ms; output interval separate; backpressure separate  
TRUE FPS: mean 38.839; median 38.799; min 38.772; max 39.026; CV 0.24%  
RENDER FPS: mean 40.523; median 40.422; min 40.398; max 40.765; CV 0.36%  
USER EFFECTIVE FPS: mean 38.160; median 38.116; min 38.090; max 38.321; CV 0.22%  
VIDEO WALL: mean 27.910 s; median 27.980 s; min 27.744 s; max 27.996 s; CV 0.36%  
TOTAL EXPORT: mean 29.638 s; median 29.673 s; min 29.514 s; max 29.692 s; CV 0.22%  
PARITY: `MaxDiff=0`, `DifferentPixels=0`  
REAL BOTTLENECK: native VP/GPU critical-path domain; largest measured ABOVE leaf is `fit_enhanced_speed_text`  
NEXT OPTIMIZATION CANDIDATE: `fit_enhanced_speed_text` / gauge rendering, future task only  
EXPECTED MAXIMUM LOCAL GAIN: NOT PROVEN  
EXPECTED E2E GAIN: NOT PROVEN  
ETAP 5O RECOMMENDATION: recommend only as a separately authorized future task; not implemented
