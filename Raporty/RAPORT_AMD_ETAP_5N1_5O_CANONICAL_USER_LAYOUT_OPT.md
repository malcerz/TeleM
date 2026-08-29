# TeleM — AMD ETAP 5N.1 + warunkowy 5O — canonical user layout

## TASK

Rebase ETAP 5N.1 accounting, profiling and conditional optimization decision on the real production user layout. Preserve AMD-only scope and do not change `def_layout.json`.

## STATUS

**5N.1 PASS. 5O NOT AUTHORIZED / NOT EXECUTED.**

The accounting gates pass on the canonical workload. The measurements identify the current critical path, but no single 5O change was proven by a controlled before/after E2E experiment with parity, so no optimization was silently introduced.

## BRANCH / HEAD

- Branch: `amd-render`
- HEAD: `3ab0b8927b7b9a93dbcba87900275e100b29091f`
- Working tree contained extensive pre-existing user changes; they were preserved.

## CANONICAL USER WORKLOAD

- Video: `Video/GX020079.MP4` (repository spelling: `Video/GX020079.mp4`)
- FIT: `Video/GX020079.fit`
- Layout: `C:\_DEV\TeleM\def_layout.json`
- Layout SHA-256: `0b937ccdee699809f4dc7cbef5c563140e6d7b9265d21d8c0d2ebc3346b2bbce`
- Layout elements: 22 indicators, 0 custom texts
- Output: 3840x2160, 29.97 fps, 1131 frames
- Runtime: `AMD_NATIVE_D3D11`, ASYNC queue 2, STATIC_CACHE, DRAIN_READY, GPU map, GPU_SPLIT charts, GPU gauge, FUSED NV12, `AMD_ABOVE_BATCHED=0`

## V10 AUDIT / RUNTIME IMPACT

The benchmark runner `scratch/run_etap5g_export.py` now defaults to `def_layout.json` and prints the absolute path, hash and element count. Historical v10 references remain in older tests, scratch experiments and reports; they are not production runtime defaults. The GUI startup path loads `def_layout.json`; an explicit `_startup_preset` may override it by user/project configuration. `def_layout.json` was not edited by this task.

## GUI PROOF

Code path inspected: controller startup loads `def_layout.json`; project loading may explicitly select `_startup_preset`; `RenderMixin._render_pipeline` passes the current `self.layout` to `stream_overlay_to_ffmpeg`; the AMD exporter consumes that layout. Therefore preview/export use the same canonical user layout unless an explicit startup preset is configured.

## IMPLEMENTATION

- Added debug-gated production accounting for producer stages and compositor widget totals.
- Added sequential producer stage boundaries, removing the previous unmeasured producer residual.
- Added consumer exclusive stage accounting and accounted/unaccounted validation.
- Added ABOVE widget totals and an explicit compositor bookkeeping bucket.
- Extended timeline trace checkpoints to include the full workload’s critical frames.
- Fixed the normal profile writer to tolerate accounting-disabled runs (no behavior change to rendering).
- Rebased `scratch/test_etap5j_golden_parity.py` default layout to `def_layout.json`; `ETAP5J_LAYOUT` remains available for explicit historical tests.

## OVERHEAD GATE — 3 PAIRS / 6 FULL RUNS

Interleaved canonical runs, warmup excluded:

- OFF total export mean: **29,834.698 ms**
- ON total export mean: **29,805.368 ms**
- measured delta: **-0.098%** (within the <=3% gate and preferred <=2%)
- OFF TRUE FPS mean: 38.951; ON: 38.967

The ON instrumentation overhead gate passes. The GPU timestamp run below is a separate diagnostic and is not included in this gate.

## PRODUCER ACCOUNTING

From `5n1_final_on_1.mp4.amd_profile.json`, 1131 frames:

- parent average: 11.3473 ms
- sequential children average: 11.3468 ms
- accounting error: 0.0043% of parent; max absolute error 0.0052 ms
- producer gate: **PASS**

Largest producer stages: ABOVE/map compose and capture 9.2968 ms, map CPU preparation 1.2070 ms, BELOW/map compose 0.7276 ms.

## ABOVE ACCOUNTING

From the same canonical profile:

- ABOVE compose parent: 7.2100 ms/frame
- explicitly timed widget/custom buckets plus compositor bookkeeping: 7.2100 ms/frame
- reported unexplained accounting error: 0.0%
- producer/ABOVE accounting gate: **PASS**

The bookkeeping bucket is sourced as the difference between the measured `compose_overlay(map_above_layout)` interval and the explicitly timed widget/custom intervals; it is not presented as a widget cost.

## TOP 10 CPU ABOVE CONTRIBUTORS

Average per frame, canonical diagnostic run:

1. `alt_text`: 1.9527 ms
2. `speed_text`: 1.8837 ms
3. `fit_distance_text`: 0.7403 ms
4. `fit_heart_rate_text`: 0.4511 ms (CPU capture/accounting path only; active chart is GPU_SPLIT)
5. `lean_indicator`: 0.4051 ms
6. `fit_cadence_text`: 0.3121 ms (CPU capture/accounting path only; active chart is GPU_SPLIT)
7. `fit_gopro_battery_text`: 0.2513 ms
8. `iso_text`: 0.1361 ms
9. `exposure_text`: 0.0907 ms
10. `temp_text`: 0.0852 ms

The list is diagnostic evidence, not authorization for 5O.

## CHART FALLBACK / GPU PATH

Canonical logs explicitly report GPU_SPLIT active for `fit_cadence_text` and `fit_heart_rate_text`, with CPU ABOVE copies disabled. No fallback or CPU readback was observed in the canonical smoke/full logs. The native profile’s chart counters are zero because the chart work is handled by the split/cache path rather than the legacy native chart-counter bucket; this is recorded as an instrumentation limitation, not interpreted as chart absence.

## CONSUMER ACCOUNTING / WAITS

From the canonical ON profile:

- consumer accounted: **99.9899%**
- median unaccounted: 0.0019 ms; p95 0.0027 ms
- consumer native call average: 17.4125 ms
- consumer upload average: 5.5675 ms
- consumer queue wait average: 0.4264 ms
- producer queue wait average: 13.1017 ms
- GPU wait/synchronization legacy CPU timing bucket: 0 ms in normal overhead runs

Consumer accounting gate: **PASS**.

## GPU TIMESTAMP RUN

Separate canonical run: `5n1_gpu_timestamps.mp4.gpu_timeline.csv`, 1115 ready/non-disjoint rows.

- GPU span: average 14.8163 ms, median 11.8679 ms, p95 29.8265 ms
- VP: average 7.9205 ms, median 6.1481 ms, p95 14.0237 ms
- map: average 2.8854 ms, median 2.4099 ms, p95 9.4279 ms
- HUD: average 4.0063 ms, median 3.2564 ms, p95 8.7753 ms
- chart and gauge GPU spans were each approximately 0.0006 ms average

The timestamp run proves the real native critical path is VP/map/HUD work plus producer ABOVE preparation; it does not justify a particular 5O patch by itself.

## AMF / OUTPUT

All measured full runs encoded and muxed 1131 frames with audio present. The normal canonical baseline means were approximately 29.8 s total export and 37.91 effective FPS across the uninstrumented/interleaved baseline set. The timestamp diagnostic intentionally reduces throughput because it synchronizes GPU queries and is not a production baseline.

## GOLDEN PARITY

`python scratch/test_etap5j_golden_parity.py` using `def_layout.json` passed checkpoints 0, 50, 100, 300, 500, 750, 900, 965 and 1130:

- MaxDiff: **0**
- DifferentPixels: **0**

The older `tests/test_golden_parity_etap4.py` golden fixture is stale relative to the current user-edited `def_layout.json` (it expects `track_map`/pixels not present in that layout); it failed 2 tests and was not used as the canonical 5N.1 parity verdict.

## 5N.1 VERDICT

**PASS.** Instrumentation overhead, producer accounting, ABOVE accounting, consumer accounting, canonical GPU activation and canonical parity satisfy the applicable gates. The fallback-counter limitation is explicitly recorded and does not show a runtime fallback in logs.

## 5O AUTHORIZATION / DECISION

- Authorization condition: gates pass and one unambiguous critical-path bottleneck must be selected.
- Gate condition: **PASS**.
- Unambiguous optimization target with proven E2E gain: **NOT PROVEN**.
- 5O implementation: **NOT EXECUTED**.
- Decision: stop at 5N.1; do not start the next optimization stage automatically.

## BACKEND ISOLATION

Changes are scoped to AMD production accounting/harness/parity defaults. No NVIDIA, Intel, QSV, CUDA, NVENC, or unrelated CPU reference path was intentionally changed.

## CHANGED FILES

- `src/indicators/profiling.py`
- `src/indicators/compositor.py`
- `src/ffmpeg/amd_native_exporter.py`
- `scratch/run_etap5g_export.py`
- `scratch/test_etap5j_golden_parity.py`
- this report

## TESTS / ARTIFACTS

- Python compilation: PASS for modified Python files.
- Focused AMD/chart/precompute tests: **14 passed, 1 skipped**.
- Canonical golden parity: PASS, MaxDiff 0 / DifferentPixels 0.
- Full canonical baseline: 5 measured uninstrumented runs available across the final baseline set, plus warmup; each completed 1131 frames.
- GPU timestamp/frame trace artifacts: generated and inspected.
- Legacy ETAP4 golden fixture: 2 failures due stale fixture/layout mismatch; NOT a 5N.1 failure.

## PRE-EXISTING CHANGES / RISKS

The repository was already heavily modified and contained many untracked reports, scripts and artifacts. They were preserved. The main residual risk is that chart fallback counters are not emitted into the native profile for the GPU_SPLIT/cache path; runtime activation and absence of fallback were verified from logs, but a future task may add a dedicated split-path counter.

## NEXT BOTTLENECK / RECOMMENDATION

The next evidence-led candidate is the combined producer ABOVE/map capture path, with `alt_text` and `speed_text` as the largest measured CPU ABOVE leaves. Run a dedicated single-change 5O ablation with 5-pair/10-run A/B, canonical def_layout, pre-encode parity and ghosting/Z-order checks before accepting any change.

