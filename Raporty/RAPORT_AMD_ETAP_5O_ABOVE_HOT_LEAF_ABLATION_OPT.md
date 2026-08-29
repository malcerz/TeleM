# TeleM — AMD ETAP 5O — ABOVE hot-leaf ablation, single-change optimization & production acceptance

## TASK:

AMD ETAP 5O — ABOVE HOT-LEAF ABLATION, SINGLE-CHANGE OPTIMIZATION & PRODUCTION ACCEPTANCE

## STATUS:

**NO CPU OPTIMIZATION.** The canonical, correctly configured ablation matrix did not prove a stable >=3% E2E gain for ALT, SPEED or DISTANCE. No production optimization was implemented and no kill-switch was added to production code.

## BRANCH / HEAD:

- Branch: `amd-render`
- HEAD: `3ab0b8927b7b9a93dbcba87900275e100b29091f`

## CANONICAL WORKLOAD:

- video = `Video/GX020079.MP4` (repository spelling `GX020079.mp4`)
- fit = `Video/GX020079.fit`
- layout = `C:\_DEV\TeleM\def_layout.json`
- layout SHA256 = `0b937ccdee699809f4dc7cbef5c563140e6d7b9265d21d8c0d2ebc3346b2bbce`
- frames = 1131 at 3840x2160 / 29.97 fps
- runtime = AMD_NATIVE_D3D11, ASYNC, queue 2, STATIC_CACHE, DRAIN_READY, GPU map, GPU_SPLIT charts, GPU gauge, FUSED NV12, AMD_ABOVE_BATCHED=0

## BASELINE:

The prior 5N.1 canonical baseline remains the production reference:

- TRUE FPS = approximately 38.95
- RENDER FPS = approximately 40.7
- USER EFFECTIVE FPS = approximately 37.9
- video wall = approximately 27.8 s
- total export = approximately 29.8 s
- above_compose = approximately 7.21 ms/frame

The ablation output was written to the explicitly named temporary volume `\\192.168.1.99\Torrenty\TeleM_5O` to avoid the full repository disk. All ablation runs encoded 1131 frames.

## ALT AUDIT:

Production accounting identified `alt_text` as a bar-form indicator at rotation 0, captured in the CPU ABOVE compositor and ultimately transferred through the ABOVE dirty-region path. Its measured total was approximately 1.953 ms/frame in the 5N.1 canonical accounting run.

- total = approximately 1.953 ms/frame
- resolve = included in producer telemetry/frame preparation; separately isolated value timing = NOT PROVEN
- cache = bar renderer has `_BAR_INDICATOR_CACHE` and static subcaches; per-frame hit/miss counts were not emitted by the production profile
- render = included in the widget total
- rotation = 0°; no rotation operation is required by the active layout
- paste = included in compositor widget total
- bbox = included in compositor geometry/dirty work
- other = bar construction, raster primitives, annotation and compositor bookkeeping
- cache hit rate = NOT PROVEN for the 1131-frame production run
- unique states = NOT PROVEN; value/state key enumeration was not exported

The earlier 5N.1 timer is an end-to-end widget bucket, not a claim that 1.953 ms is pure rasterization. A production-safe optimization was therefore not inferred from this number alone.

## SPEED AUDIT:

Production `speed_text` is `form=gauge`, layout-resolved as the active GPU AFTER-MAP gauge. The CPU work is preparation of the CPU raster/capture source for the existing GPU path; it is not pasted into the final CPU ABOVE canvas when GPU gauge capture is active.

- total = approximately 1.884 ms/frame CPU preparation/capture source
- resolve = telemetry value and formatted-value preparation in compositor
- static = cached gauge background/ticks/ring in `_STATIC_CACHE`
- dynamic = needle and current-value text; value-keyed dynamic raster cache exists
- cache = gauge background and dynamic raster caches exist; exact 1131-frame hit/miss counters were NOT PROVEN in the production profile
- paste = no duplicate CPU canvas paste when GPU capture is active
- capture = full gauge source object is prepared before AUTO dynamic-region extraction
- upload prep = AUTO region extraction and byte preparation are downstream of the source raster
- other = gauge state/signature calculation and persistent-canvas restoration
- duplicate work = no evidence of a second final CPU gauge composition; the visible CPU cost is GPU-capture source preparation

Logical flow:

```text
FIT speed value -> CPU gauge state/value preparation -> cached static background
                  + dynamic needle/value raster -> GPU capture source
                  -> AUTO dynamic-region upload -> AFTER-MAP GPU blend -> final NV12
```

STATIC work is layout/style/background dependent; dynamic work is value/needle/text dependent; capture/upload is per frame while the gauge is active. The current architecture already reuses the static background and AUTO upload regions, so a new full gauge renderer would be out of scope.

## DISTANCE:

- total = approximately 0.740 ms/frame in the 5N.1 widget accounting run
- form = bar
- no separately exported 1131-frame cache/state breakdown = NOT PROVEN

## LOCAL ABLATION:

Each variant used one warmup and three measured full exports. The first exploratory matrix used SYNC/REFERENCE and is explicitly rejected. The following matrix used the required ASYNC/queue2/STATIC_CACHE/DRAIN_READY settings and is the valid result.

| Variant | Total export mean | Video wall mean | TRUE FPS mean | Effective FPS mean | ABOVE mean | Producer mean |
|---|---:|---:|---:|---:|---:|---:|
| REF | 33,922.3 ms | 27,860.0 ms | 34.275 | 33.342 | 8.192 ms | 12.967 ms |
| ALT_BYPASS | 39,352.5 ms (one severe outlier) | 30,427.2 ms | 30.410 | 29.666 | 5.523 ms | 8.945 ms |
| SPEED_BYPASS | 33,572.9 ms | 27,739.8 ms | 34.654 | 33.691 | 6.082 ms | 10.288 ms |
| DISTANCE_BYPASS | 33,706.0 ms | 27,797.6 ms | 34.529 | 33.556 | 6.756 ms | 11.426 ms |

All runs reported the canonical video/FIT/layout lines. The bypass is diagnostic-only and changes the in-memory layout for that process.

## E2E HEADROOM:

Relative to the valid REF mean:

- ALT = no gain; median ALT total was approximately 34,187.0 ms, and the mean was invalidated by a 49,819.2 ms outlier
- SPEED = approximately **1.03%** total-export improvement and approximately **0.43%** video-wall improvement
- DISTANCE = approximately **0.64%** total-export improvement and approximately **0.22%** video-wall improvement

None reaches the 3% acceptance threshold. SPEED is locally interesting but remains below production acceptance and is not an authorization to change gauge architecture.

## SELECTED TARGET:

NONE

## SELECTION REASON:

- ALT local cost is real but not critical enough in stable E2E terms.
- SPEED bypass removes a visible local producer cost, but valid E2E gain is only ~1.03%.
- DISTANCE bypass is below 1% E2E.
- No candidate meets the required >=3% production gain or demonstrates a safe exact-parity implementation opportunity.

## ROOT CAUSE:

CPU ABOVE leaf time is partially hidden by the asynchronous producer/consumer pipeline. The largest local leaf is not automatically the end-to-end critical path. For SPEED specifically, the CPU work is preparation of an existing GPU capture source, not duplicate final CPU composition.

## IMPLEMENTATION:

No CPU optimization implemented. The only task-scoped code change is the diagnostic benchmark switch `AMD_5O_BYPASS` in `scratch/run_etap5g_export.py`; it is validated-key-only, process-local, and defaults to NONE. `def_layout.json` was not modified.

## KILL SWITCH:

`AMD_5O_BYPASS=alt_text|speed_text|fit_distance_text` is diagnostic bypass only. There is no production 5O optimization flag because no optimization was accepted.

## PARITY:

- Canonical `python scratch/test_etap5j_golden_parity.py`: PASS
- Checkpoints: 0, 50, 100, 300, 500, 750, 900, 965, 1130
- MaxDiff = 0
- DifferentPixels = 0

No candidate production change exists to parity-test.

## DYNAMIC REGION PARITY:

Candidate dynamic-region parity for an accepted optimization = NOT APPLICABLE. Existing GPU gauge AUTO path remained unchanged.

## GHOSTING:

No production renderer change was made. Existing gauge AUTO dirty-region behavior was not altered. New 5O ghosting acceptance = NOT APPLICABLE.

## PREVIEW:

No preview/editor code changed. Diagnostic bypass is exporter-runner-only and cannot alter GUI layout persistence.

## BAR SAFETY:

No bar implementation changed. Existing bar test coverage from 5N.1 was preserved. Full new BAR matrix for a candidate = NOT APPLICABLE because target selection was NONE.

## BEFORE 5-RUN:

The required candidate BEFORE/AFTER 5-pair benchmark was not authorized because no candidate passed the ablation gate. Valid REF ablation subset (3 runs):

- TRUE FPS mean = 34.275
- median = approximately 34.366
- CV = 0.52%
- video wall = 27,860.0 ms mean
- selected local cost = no selected target

## AFTER 5-RUN:

NOT RUN — no candidate selected.

## PAIRED GAIN:

- TRUE FPS = NOT APPLICABLE
- video wall = NOT APPLICABLE
- local = NOT APPLICABLE

## DECISION:

**NO CPU OPTIMIZATION**

The valid matrix does not justify KEEP DEFAULT ON, LOCAL PASS DEFAULT OFF, or a production rollback. There is simply no accepted CPU candidate.

## GPU DISCOVERY:

- performed = limited 300-frame diagnostic probes, no production GPU change
- GPU_REF = 11,612.1 ms total export, 27.912 TRUE FPS
- VP_REFERENCE = 11,617.1 ms, 27.806 TRUE FPS; no headroom versus GPU_REF
- MAP_CPU = 11,282.4 ms, 28.254 TRUE FPS; this is a semantic CPU map replacement, not a safe GPU bypass, and is not accepted as GPU headroom proof
- HUD_CPU = BLOCKED by existing producer `NameError: cannot access free variable 'lean_cfg'`; no headroom claim
- VP headroom = NOT PROVEN by a safe bypass in this stage
- HUD headroom = BLOCKED / NOT PROVEN
- MAP headroom = NOT PROVEN by a safe GPU bypass

The 5N.1 canonical GPU timestamp run remains evidence of cost allocation: GPU span ~14.82 ms, VP ~7.92 ms, HUD ~4.01 ms, map ~2.89 ms. It is not a bypass/headroom measurement and must not be misreported as one. The HUD_CPU producer failure is an existing diagnostic-path defect to isolate before ETAP 5P; it is not a production-path regression.

## NEXT TRUE TARGET:

GPU critical-path discovery, starting with a technically safe VP/HUD/MAP control ablation. The next stage must prove E2E headroom before any native redesign.

## ETAP 5P RECOMMENDATION:

Run GPU-only diagnostic ablations under the exact canonical configuration, with one warmup and repeated measured runs, preserving output correctness checks. Do not combine a GPU change with ALT/SPEED/DISTANCE CPU changes.

## FILES CHANGED:

- `scratch/run_etap5g_export.py` — diagnostic `AMD_5O_BYPASS` support
- `Raporty/RAPORT_AMD_ETAP_5O_ABOVE_HOT_LEAF_ABLATION_OPT.md` — this report

## PRE-EXISTING USER CHANGES PRESERVED:

YES. The working tree was already heavily modified. No existing user modifications were reverted, and `def_layout.json` was not changed.
