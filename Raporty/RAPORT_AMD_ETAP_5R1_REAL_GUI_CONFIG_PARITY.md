# TeleM — AMD ETAP 5R.1 — REAL GUI PRODUCTION CONFIG TRUTH, HARNESS PARITY & CONDITIONAL FAST-PATH ENABLEMENT

## TASK

Establish the effective AMD configuration used by a normal GUI export, compare
it with the benchmark harness, and conditionally enable the fast path only if
an apples-to-apples test proves a safe >=3% end-to-end gain.

## STATUS

COMPLETE — NO PRODUCTION ENABLEMENT.

The GUI/exporter defaults are demonstrably `SYNC/Q0/REFERENCE/REFERENCE`.
The harness does not hard-code the fast scheduling flags; previous fast runs
received them from the invoking environment. The controlled R3 result did not
beat R0, so no AMD defaults were changed and ETAP 5S must not start.

## BRANCH / HEAD

Branch: `amd-render`  
HEAD at start: `3ab0b89`  

The worktree was already heavily modified, including deleted diagnostic
artifacts and many untracked reports/results. Those changes were preserved.

## CANONICAL WORKLOAD

```text
video = Video/GX020079.mp4
fit = Video/GX020079.fit
layout = C:\_DEV\TeleM\def_layout.json
layout SHA-256 = 0B937CCDEE6998094DC7CBEF5C563140E6D7B9265D21D8C0D2EBC3346B2BBCE
output = local C:\_DEV\TeleM\scratch\etap5r1_*
resolution = 3840x2160
fps = 29.97
frames = 1131 for full R0; 301 emitted for --frames 300 screening
```

`def_layout.json` was not edited by this task.

## CURRENT GUI EFFECTIVE CONFIG

The supplied real-GUI log is evidence for:

```text
pipeline = SYNC
queue = 0
VP state = REFERENCE
VP pool = 8
AMF query = REFERENCE
map = GPU
charts = GPU_SPLIT
gauge = GPU
lean = GPU
HUD = GPU_HUD
HUD upload = DIRTY
NV12 compositor = FUSED
AMD_ABOVE_BATCHED = 0
```

The code independently proves the first four scheduling/state values: the
Python exporter resolves `AMD_CPU_GPU_PIPELINE` with default `SYNC`, derives
queue depth 0 for SYNC, and defaults VP state and AMF query to REFERENCE
(`src/ffmpeg/amd_native_exporter.py:2230-2236`). The native DLL independently
defaults VP state and AMF query to REFERENCE and pool size to 8
(`native/d3d11_amf_pipeline/src/telem_amd_native.cpp:1134-1174`).

## HARNESS EFFECTIVE CONFIG

`scratch/run_etap5g_export.py` loads `def_layout.json` by default and calls the
same `stream_overlay_to_ffmpeg` path as the GUI, but it does not assign
`AMD_CPU_GPU_PIPELINE`, `AMD_QUEUE_DEPTH`, `AMD_VP_STATE_MODE`, or
`AMD_AMF_QUERY_MODE`. Therefore:

```text
HARNESS FORCES FAST CONFIG = NO
```

When invoked with the benchmark environment, its effective configuration is:

```text
pipeline = ASYNC
queue = 2
VP state = STATIC_CACHE
VP pool = 8
AMF query = DRAIN_READY
map = GPU
charts = GPU_SPLIT
gauge = GPU (AUTO)
lean = GPU
HUD = GPU_HUD
HUD upload = DIRTY
NV12 compositor = FUSED
AMD_ABOVE_BATCHED = 0
```

The effective-config block printed by `amd_native_exporter.py` is the common
runtime evidence for both callers.

## CONFIG DIFFERENCES

| setting | GUI default | harness without env | prior benchmark env |
|---|---|---|---|
| pipeline | SYNC | SYNC | ASYNC |
| queue | 0 | 0 | 2 |
| VP state | REFERENCE | REFERENCE | STATIC_CACHE |
| VP pool | 8 | 8 | 8 |
| AMF query | REFERENCE | REFERENCE | DRAIN_READY |
| map/charts/gauge/lean/HUD/NV12 | GPU production defaults | same | same |

## CONFIG SOURCE OF TRUTH / PRECEDENCE

The actual precedence is:

```text
Python exporter fallback defaults
    ↓
process environment AMD_* overrides
    ↓
runtime safety/layout guards and derived effective values
    ↓
native DLL environment parsing and native fallback defaults
```

The GUI render action collects encoder, resolution, bitrate, output, and HUD
scale, then calls `RenderMixin._render_pipeline` and
`stream_overlay_to_ffmpeg`; it does not set the four scheduling/state
environment variables (`render_tab.py:452-487`, `render_mixin.py:31-65`).
The GUI also persists a normalized copy of its editable layout to
`def_layout.json` on render (`render_mixin.py:39-41`), an existing behavior
not changed here.

`BENCHMARKS.md:123-126` documents ASYNC/Q2/STATIC_CACHE/DRAIN_READY as the
benchmark environment, not as executable GUI defaults. Git history shows the
exporter defaults were introduced through earlier stabilization commits
(`e019a6b`, `f455ff6`, `c4dc477`, `8efdd35`); no reliable history evidence was
found that authorizes changing the GUI defaults now. The supplied GUI log is
consistent with the current source.

## WHY GUI WAS SYNC

The present code provides no GUI setting or controller assignment for ASYNC.
SYNC is simply the exporter fallback default, and queue depth is derived as 0
under SYNC. The exact historical rationale is NOT PROVEN from the available
history; likely stability concerns may not be asserted as fact.

## WHY HARNESS WAS ASYNC

The harness itself does not force ASYNC. The earlier benchmark invocations
explicitly exported the fast flags in the shell. This explains why benchmark
reports measured a configuration different from a normal GUI click.

## CONTROLLED SHORT SCREENING

All four variants used the same local output class, source, FIT, layout, and
GPU feature settings. Only the requested scheduling/state variables changed.
Each used one warmup and two measured 300-frame exports.

| variant | pipeline | queue | VP state | AMF query | measured render walls | mean |
|---|---|---:|---|---|---:|---:|
| R0 | SYNC | 0 | REFERENCE | REFERENCE | 7714.868 / 7826.792 ms | 7770.830 ms |
| R1 | ASYNC | 2 | REFERENCE | REFERENCE | 7904.395 / 7837.014 ms | 7870.705 ms |
| R2 | SYNC | 0 | STATIC_CACHE | DRAIN_READY | 7803.376 / 7637.157 ms | 7720.267 ms |
| R3 | ASYNC | 2 | STATIC_CACHE | DRAIN_READY | 7786.402 / 7856.608 ms | 7821.505 ms |

Attribution from these short runs:

```text
R0 -> R1: -1.28% (pipeline/queue slower)
R0 -> R2: +0.65% (state/query combination, within short-run noise)
R2 -> R3: -1.31% (adding ASYNC/Q2 slower)
R0 -> R3: -0.65% (R3 slower, not a fast-path candidate)
```

Producer/consumer timing also showed no R3 advantage. R3 had higher measured
consumer-native and producer timing in both short runs. This is not a valid
>=3% enablement signal.

## FULL R0 LOCAL BASELINE

Because screening did not show R3 >=3% faster, the conditional 5-pair full
R0/R3 benchmark was **NOT AUTHORIZED**. A fresh full R0 baseline was still
collected locally with one warmup and three measured runs:

| metric | run 1 | run 2 | run 3 |
|---|---:|---:|---:|
| video render wall | 28674.481 ms | 28822.901 ms | 28556.274 ms |
| total export | 31124.815 ms | 30876.853 ms | 30642.490 ms |
| TRUE FPS | 37.266 | 37.568 | 37.870 |
| RENDER FPS | 39.443 | 39.240 | 39.606 |
| USER EFFECTIVE FPS | 36.338 | 36.629 | 36.910 |

```text
FULL R0 mean wall = 28684.552 ms
FULL R0 median    = 28674.481 ms
FULL R0 CV        = 0.466%
```

Each run encoded and muxed 1131 frames and reported audio present.

## R1 / R2 / R3 FULL A/B

NOT RUN. The brief makes this conditional on short-screening evidence of R3
>=3% improvement; that condition failed.

## VP STATE CALLS

The native source applies the stream state setters on every frame in
REFERENCE, while STATIC_CACHE skips them after a stable state signature
(`d3d11_vp_pipeline.cpp:3350-3396`). The existing per-frame accounting field
`setters_skipped` provides runtime evidence. A dedicated full call-count
export was not run because R3 did not qualify for full A/B; exact calls/export
for both modes are therefore NOT TESTED here.

## AMF QUERY

REFERENCE performs the normal single query policy; DRAIN_READY loops over
immediately available packets (`telem_amd_native.cpp:1755-1790`). The 5R
canonical evidence recorded no `AMF_INPUT_FULL` or retries and approximately
one output per input frame. A dedicated R0/R3 full AMF query comparison was
NOT RUN because R3 failed screening.

## ASYNC QUEUE

The earlier 5Q canonical queue evidence remains applicable to the explicitly
configured ASYNC/Q2 harness: approximately 62.2% producer full-before-put,
0.12% consumer empty-before-get, producer wait about 13.0 ms, and consumer
wait about 0.44 ms. The local R0–R3 screening did not show those waits producing
an end-to-end gain.

## CORRECTNESS GATE

No production candidate existed, so the following conditional gates were not
claimed:

```text
pixel parity R0 vs R3       NOT TESTED
100-frame temporal parity   NOT TESTED
telemetry alignment         NOT TESTED
HDR/color                   NOT TESTED
cancel sequence             NOT TESTED
repeated GUI exports        NOT TESTED
```

The focused test suite was run:

```text
42 passed, 8 failed
```

The failures are pre-existing or unrelated to this task: stale ABI-8 mocks
against the current ABI-9 DLL, a `PreparedFrame` constructor contract mismatch,
an existing visible-to-none compositing failure, shader variant parity
failures, and a stale source assertion. No failure was used to justify a
production change.

## MAP / LEAN / GAUGE / CHARTS / BAR

The controlled exports logged GPU map, GPU lean, GPU gauge AUTO, and GPU_SPLIT
charts active for `def_layout.json`. No visual or backend implementation was
changed. Full R0-vs-R3 image, temporal, HDR, and widget parity was NOT TESTED
because no candidate reached the performance gate.

## FRAME INTEGRITY / AUDIO / A-V

Fresh full R0 runs: 1131 encoded frames, 1131 muxed frames, audio present.
Detailed PTS/A-V comparison against R3 was NOT TESTED because R3 full A/B was
not authorized.

## CANCEL / REPEATED EXPORT

NOT TESTED for a production fast-path candidate. Existing focused lifecycle
tests were included but several failed before reaching the intended mocked
path due the ABI mismatch; see the focused-test section above.

## MEMORY

Peak working-set R0 versus R3 was NOT MEASURED. No production path was enabled,
and no new persistent resource class was introduced by this task.

## PRODUCTION ENABLEMENT

```text
YES / NO = NO
```

The required >=3% video-wall gain and correctness gate were not met. Do not
change GUI defaults, queue depth, VP state, AMF query policy, or begin ETAP 5S.

## FINAL PRODUCTION DEFAULT

```text
pipeline = SYNC
queue = 0
VP state = REFERENCE
VP pool = 8
AMF query = REFERENCE
```

GUI == HARNESS DEFAULT: **NO** for the four scheduling/state values. This
dualism is now explicitly identified and documented; changing it requires a
separate deliberate production decision backed by a qualifying full A/B.

## FILES CHANGED

- `Raporty/RAPORT_AMD_ETAP_5R1_REAL_GUI_CONFIG_PARITY.md` — this audit report.

No source, GUI default, layout, or backend implementation file was changed for
ETAP 5R.1.

## PRE-EXISTING USER CHANGES PRESERVED

YES. The pre-existing modified and untracked worktree contents were not
reverted, cleaned, or overwritten.

## NEXT TRUE BOTTLENECK

The next actionable issue is configuration governance, not VP micro-optimization:
decide whether the GUI should remain conservative SYNC/REFERENCE or whether a
future controlled enablement project should first repair the focused test/ABI
baseline and then repeat a valid full R0/R3 correctness/performance study.

## ETAP 5S RECOMMENDATION

Do not start 5S. First make the GUI-versus-harness policy an explicit product
decision and, if fast-path enablement is desired, establish a single tested
source of truth plus the missing correctness/cancel/repeat evidence.

