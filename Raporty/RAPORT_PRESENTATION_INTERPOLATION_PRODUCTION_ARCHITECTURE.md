# Production presentation interpolation architecture

## Root cause and fix

Real GUI reproduction used `GX010246.MP4` and `D:\\GoPro\\2026-09-02\\Poranna_jazda_na_rowerze.fit`, normal `QApplication → AppController → MainWindow`, Battery `fit_garmin_battery_percent_text`, `decimals=2`.

Before: source interval was `96.0 @ 04:34:57 → 95.0 @ 04:35:57`; 14 seconds / 68 accepted Preview updates remained visibly `96.00%`. Evidence: `D:\\TeleM_live_acceptance\\presentation_before.log` and `presentation_architecture\\before`.

The manager does not own `layout` in production. Its old resolver read `self.layout`, fell back to `{}`, resolved precision as zero and STEP-held the value. Tests had assigned a manager layout and hid this. Separately PRECOMPUTED vectorized dynamic FIT fields with STEP lookup.

The shared fix is `resolve_current_presentation(samples, target_dt, field, cfg)` in `src/telemetry_resolver.py`. It owns canonical dynamic FIT mapping, `FieldSemantics`, effective precision (`decimals`, legacy `decimal_places`, then default), source resolution, linear/step choice and gap policy. Preview manager, worker cache, frame data and PRECOMPUTED use it. Raw samples remain unchanged.

Continuous Battery has native resolution 1.0: 0 DP is STEP; 1–3 DP are linear. Voltage has 0.001 V. ISO, SHUT/exposure, GPS fix, mode, status, IDs and counters are forced STEP. Unknown fields are conservative STEP. Before first is `None`; after final preserves final hold. A conservative lower-median gap gate prevents an actual `60 s, 600 s` data outage becoming a false ramp.

## Lifecycle / isolation

```
raw FIT/GPMF/GPX → source mapping → canonical presentation value
→ frame data / telemetry cache → compositor full float → backend submission
```

GUI Preview enters through `TelemetryDataManager.resolve_value`; CPU Final through `worker_cache._resolve_cache_value`; PRECOMPUTED through `build_telemetry_cache`; AMD native uses either shared frame data or this cache before native submission. Intel/NVIDIA use the shared worker/frame-data input. No backend-specific Battery interpolation exists. AMD/Intel/NVIDIA implementations, Hybrid, PreparedVideoFrame, audio, GPMF anchoring and Lean math were not modified.

`TELEM_PRESENTATION_INTERP_DEBUG=1` is default-off and records cfg/precision, neighbours, cadence/gap, fraction, resolved/frame-data/compositor values, text, bar input, cache state and generation. Metadata is cached per immutable source series; lookup is binary-search O(log N), not an interpolated table scan. Dynamic FIT participates in frame atlas invalidation. Bar receives the full display float; gauge receives the full normalized fraction; segment active count is never the text value.

## Real GUI evidence

Normal Windows GUI `after_evidence` captured live desktop and separate top-level HUD (both PASS). Twelve playback samples over >20 seconds visibly progressed:

`95.73, 95.70, 95.67, 95.63, 95.60, 95.57, 95.54, 95.50, 95.47, 95.43, 95.40, 95.37%`.

Seek matrix: 0/10/25/50/75/90/100% of the real interval produced `96.00, 95.90, 95.75, 95.50, 95.25, 95.10, 95.00%`. At the same paused midpoint, changing property without moving time yielded 0 DP `96%`, 1 DP `95.5%`, 2 DP `95.50%`, 3 DP `95.500%`; resumed playback also updated values. Visible assets: `D:\\TeleM_live_acceptance\\presentation_architecture\\after_evidence\\play_01_hud.png` and `property_2_hud.png`.

## Final / regressions / performance

Short real Final-worker smoke on the same parsed FIT transition visibly rendered 25/50/75% as `95.75%`, `95.50%`, `95.25%` in `D:\\TeleM_live_acceptance\\presentation_architecture\\final_worker`. This is Final overlay-worker parity, not a long video export.

Multi-file/cut semantics are data/timeline driven: a file edge alone does not block interpolation, while a real telemetry gap, active-time pause or merged-distance segment boundary holds prior value. No cut engine changed.

Fresh native GPMF regression inventory:

| File | ISO/SHUT | TMPC | ACCL/GYRO |
|---|---:|---:|---:|
| GX010246 | 61,339 | 2,045 | 406,684 / 406,684 |
| GX010115 | 17,760 | 592 | 117,728 / 117,728 |
| GX010258 | 4,867 | 163 | 32,268 / 32,269 |

10,000 real Battery warm lookups: STEP median/p95/total `7.7 µs / 8.8 µs / 79.49 ms`; linear `9.5 µs / 9.9 µs / 95.94 ms`.

Focused suite result: **58 passed** (`test_presentation_architecture`, display precision, GPMF first sample, chart decimals, Lean/bar label, FIT distance parity); `compileall` passed. Tests cover precision precedence, dynamic mapping, sparse source resolution, before/exact/after/gap, discrete protection, Preview/precomputed parity, no repeated full scan, full-float segment input, GPMF/Lean and cut boundary.

## Status

Changed shared presentation files: resolver, telemetry manager, worker cache, precompute, frame-data, Preview/RenderTab callbacks, compositor/helpers, bar/gauge, frame renderer and tests/manual GUI harness. No commit/push.

All requested presentation gates are PASS. Hardware-specific long full-video export was intentionally not run; shared pre-backend contracts and a short Final worker smoke were verified.

**STATUS = PRESENTATION INTERPOLATION PRODUCTION READY**
