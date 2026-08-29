# TeleM — AMD ETAP 5V — VP driver-wait origin and first-call serialization

## TASK

AMD ETAP 5V — VP DRIVER WAIT ORIGIN, FIRST-CALL SERIALIZATION PROOF &
CONDITIONAL PROCESSOR-RING OPTIMIZATION.

## STATUS

**PASS — diagnostic evidence complete. NO PRODUCTION OPTIMIZATION.**

The first-call serialization hypothesis is proven for the tested AMD D3D11
path. The evidence points to unfinished prior GPU/Video Engine work being
observed at the first per-frame Video Processor state call. A dependency on a
particular processor object is not proven, so the processor ring was not
authorized.

## BRANCH / HEAD

- Branch: `amd-render`
- HEAD at task start: `3ab0b89`
- Backend: `AMD_NATIVE_D3D11`
- Platform: AMD Ryzen 7 7730U, Windows 11, Max Performance

## CANONICAL

```text
video = Video/GX020079.MP4
fit = Video/GX020079.fit
layout = C:\_DEV\TeleM\def_layout.json
frames = 1131
resolution = 3840x2160
```

All new measurements used `--production-defaults`; diagnostic variables were
explicitly labelled with `--set-amd`. Earlier GX010115 + Lunch FIT results
were excluded.

## PRODUCTION

```text
pipeline = SYNC
queue = 0
VP state = REFERENCE
VP processor count = 1
VP output pool = 8
AMF = REFERENCE
```

No production default changed.

## IMPLEMENTATION

Added diagnostic-only instrumentation in the AMD native pipeline:

- per-frame first-setter identity and wall time;
- explicit setter orders `FORMAT_SRC_DST`, `SRC_FORMAT_DST`, and
  `DST_SRC_FORMAT`;
- persistent 64-slot `D3D11_QUERY_EVENT` ring for a marker immediately after
  VP Blt and a second marker after TeleM-side local D3D11 work;
- non-blocking status checks with `D3D11_ASYNC_GETDATA_DONOTFLUSH` at the next
  frame and at same-output-slot reuse;
- decoder texture/subresource, output slot, processor, enumerator, and
  VideoContext identities in the native CSV.

No `Flush`, blocking `GetData`, sleep, fence wait, or per-frame event wait was
added. The existing output texture pool remains size 8.

## PROFILER/QUERY OVERHEAD

Six canonical 300-frame runs in `OFF, ON, OFF, ON, OFF, ON` order:

| probe | runs | mean video wall |
|---|---:|---:|
| OFF | 1, 3, 5 | 9255.3 ms |
| ON | 2, 4, 6 | 9358.4 ms |

Delta: **+1.11%**, gate **PASS (<=3%)** and preferred <=2%.

## VP CALL ORDER

Actual per-frame state-call order in the production path is:

```text
VideoProcessorSetStreamFrameFormat
VideoProcessorSetStreamSourceRect
VideoProcessorSetStreamDestRect
VideoProcessorBlt
```

All three order variants retained the same three setter calls and values.

## REFERENCE

The representative canonical 300-frame REF trace contained 301 rows because
the current runner emits the initial frame in addition to the requested 300.
The first API was FMT on 301/301 frames.

```text
first VP API = FrameFormat
first API avg / median / p95 / p99 / max = 10.0879 / 1.0604 / 33.2622 / 101.144 / 139.527 ms
setter total (SetStream)                 = 10.0966 / 1.0719 / 33.2759 / 101.153 / 139.537 ms
Blt                                       = 0.1994 / 0.1789 / 0.2831 / 0.3286 / 4.0427 ms
VP total                                  = 10.3660 / 1.3920 / 33.5561 / 101.524 / 139.824 ms
process_frame                             = 11.3164 / 2.4353 / 34.2964 / 102.710 / 141.112 ms
```

The tuple order in each line is avg / median / p95 / p99 / max.

## STATIC CACHE

Same instrumented 300-frame shape, with `AMD_VP_STATE_MODE=STATIC_CACHE`:

```text
first VP API = VideoProcessorBlt (300 frames; first frame FMT)
first API avg / median / p95 / p99 / max = 10.8513 / 1.2952 / 33.1551 / 114.802 / 127.047 ms
setter total (SetStream)                 = 0.0004 / 0.0003 / 0.0007 / 0.0012 / 0.0133 ms
Blt                                       = 10.8645 / 1.3361 / 33.1551 / 114.802 / 127.047 ms
VP total                                  = 10.9348 / 1.4185 / 33.2765 / 114.906 / 127.112 ms
process_frame                             = 11.8673 / 2.4643 / 34.4055 / 115.590 / 128.009 ms
```

The three setter calls were skipped on 300/301 frames. The wait moved from
SetStream to Blt rather than disappearing.

## WAIT CONSERVATION

**PROVEN qualitatively / driver wait relocation proven.**

The clean ETAP 5U interleaved R0/R1 result remains the E2E gate: STATIC_CACHE
was approximately 1.236% slower. In the current trace, REF has approximately
10.10 ms SetStream plus 0.20 ms Blt, while STATIC_CACHE has approximately
0.00 ms SetStream plus 10.86 ms Blt. This is consistent with wait
conservation/relocation and rejects setter cache as a production optimization.

## REORDER / SETTER ORDER TEST

All variants used one warmup and three measured 300-frame runs with completion
probe enabled.

| order | first API | mean wall | first API avg / median / p95 / p99 / max | VP total avg / median / p95 / p99 |
|---|---|---:|---:|---:|
| FORMAT→SRC→DST | FMT | 9241.3 ms | 10.0879 / 1.0604 / 33.2622 / 101.144 / 139.527 ms | 10.3660 / 1.3920 / 33.5561 / 101.524 ms |
| SRC→FORMAT→DST | SRC | 9305.8 ms | 11.1417 / 0.9606 / 30.9939 / 113.473 / 122.461 ms | 11.4111 / 1.3000 / 31.4859 / 113.729 ms |
| DST→SRC→FORMAT | DST | 9304.6 ms | 10.3725 / 1.3174 / 30.9717 / 107.580 / 118.568 ms | 10.6574 / 1.8012 / 31.2681 / 107.830 ms |

The first API identity was exactly 1/2/3 for FMT/SRC/DST respectively on all
301 rows in each variant. The long wait therefore follows the API selected as
the first call. **FIRST-VP-CALL SERIALIZATION = PROVEN.** The small E2E
differences are below the production gate and were not treated as wins.

The pre-existing `REORDER` mode remains a safe diagnostic ordering mode; it
still applies all required setters before Blt. The new three-way order probe is
also diagnostic-only.

## GETTER PROBE

Performed: **NO**. No safe read-only VideoContext getter that would add useful
VP-state evidence without potentially changing driver behavior was identified.

Result: **SKIPPED — correct for this proof.**

## VP QUERY

Representative REF trace:

```text
prev VP query READY     = 11
prev VP query NOT_READY = 289
first frame / unavailable = 1
READY first API avg      = 1.1527 ms
NOT_READY first API avg  = 10.4628 ms
READY VP total avg       = 1.4478 ms
NOT_READY VP total avg   = 10.7267 ms
```

The correlation is strong: when the previous VP marker is already complete,
the next frame's first API is short; when it is not complete, the first API
absorbs the long wait.

## LOCAL FRAME QUERY

Representative REF trace:

```text
prev local query READY     = 8
prev local query NOT_READY = 292
READY first API avg        = 0.9191 ms
NOT_READY first API avg    = 10.3736 ms
```

The local marker covers TeleM-side D3D11 work only and does not include
internal AMF encoding. It provides independent evidence that prior local GPU
work is often incomplete before the next frame enters VP state calls.

## OUTPUT SLOT REUSE

```text
pool = 8
steady reuse distance = 8 frames
same-slot READY = 300/300 reusable rows
same-slot NOT_READY = 0/300
stall correlation = NOT PROVEN; evidence argues against it
```

The same-slot query was ready on every measured reuse in the representative
trace. **OUTPUT SURFACE REUSE HAZARD = DISPROVEN for this sample.** This does
not change the pool or claim that all possible driver lifetime behavior is
solved.

## INPUT RESOURCE

The trace records decoder texture pointer/id, array index, and subresource.
The existing canonical 5T audit found a stable decoder texture identity and no
AMF input-full/retry condition. A direct causal input-surface reuse correlation
was not established.

```text
texture count = one persistent decoder identity in the captured audit
subresources = recorded per frame; no anomalous state transition observed
reuse pattern = NOT a proven cause
stall correlation = NOT PROVEN
```

No decoder architecture or pool change was made.

## VP PROCESSOR

The post-instrumentation identity smoke showed one persistent object for the
whole context:

```text
VP processor identity = 1947009164064
VP enumerator identity = 1947023803648
VP VideoContext identity = 1947023835128
reuse = one persistent VideoProcessor / VideoContext for the context
```

Object identity alone does not prove that serialization is specific to that
processor object; order and query evidence instead support a broader
VideoContext/Video Engine synchronization point.

## AMF CORRELATION

AMF remains `REFERENCE`. Existing fresh canonical accounting found small AMF
SubmitInput/QueryOutput tails relative to VP setup and no `AMF_INPUT_FULL` or
retry path. The current 5V probe did not change AMF policy or add a causal AMF
dependency. **AMF RESOURCE DEPENDENCY = NOT PROVEN.**

## ROOT CAUSE CLASSIFICATION

```text
A SAME VP PROCESSOR STATE SERIALIZATION       = NOT PROVEN
B VIDEO CONTEXT / VIDEO ENGINE SERIALIZATION  = STRONGLY SUPPORTED
C VP OUTPUT SURFACE REUSE                     = DISPROVEN in measured reuse
D DECODER INPUT AVAILABILITY                  = NOT PROVEN
E AMF RESOURCE / ENCODER DEPENDENCY           = NOT PROVEN
F GENERAL D3D11 DRIVER THROTTLING             = POSSIBLE, not isolated
G NOT PROVEN                                  = not the best final classification
```

The precise driver wait target cannot be identified further from this API
surface without vendor-driver instrumentation. The tested evidence proves
that the first suitable VP call is the serialization observation point.

## PROCESSOR RING AUTHORIZED

**NO.** A ring changes the processor-object reuse distance, but the evidence
does not show that the stall belongs to the object identity rather than the
shared VideoContext/Video Engine path. No P1/P2/P3 ring screening was run.

```text
P1 = NOT RUN
P2 = NOT RUN
P3 = NOT RUN
selected target = NONE
full A/B authorized = NO
```

Running a ring without that prerequisite would violate the conditional scope
of ETAP 5V.

## CORRECTNESS / ACCEPTANCE

- Native AMD target build: **PASS**.
- Focused production/regression suite: **25 passed**.
- 300-frame diagnostic runs: complete native traces and 301/301 output rows.
- Setter order semantics: **PASS**; all three setters remain before Blt.
- Non-blocking query rule: **PASS**; persistent ring, delayed checks, no flush,
  no spin, no blocking GetData.
- Full 1131-frame query acceptance: **NOT TESTED**; no production candidate was
  authorized.
- Pre-encode pixel parity and temporal 100-frame equality: **NOT TESTED**;
  diagnostics do not alter production output and no candidate was promoted.
- HDR/color lifecycle validation: **NOT TESTED**; no production resource
  lifecycle change.
- Multi-file, cancel/second-export, repeated-export lifecycle: **NOT TESTED**;
  production lifecycle was unchanged.
- Driver errors in measured runs: none observed; no device removed/hung/reset.

## PRODUCTION DEFAULT CHANGED

**NO.** SYNC/Q0/VP REFERENCE/processor 1/output pool 8/AMF REFERENCE remains
the production configuration.

## FINAL PRODUCTION / DECISION

**NO PRODUCTION OPTIMIZATION.**

Keep the production default on REFERENCE. Keep STATIC_CACHE, individual setter
caches, setter ordering, completion probe, and any future processor ring as
diagnostic-only mechanisms. Do not increase the output pool or switch ASYNC,
queue depth, or AMF query policy in this stage.

## NEXT TRUE BOTTLENECK

The remaining bottleneck is the upstream unfinished GPU/Video Engine work that
is serialized at the first per-frame VP state API. The evidence is not a case
for more setter-cache/order hacks. If investigation continues, it requires
vendor/driver-level queue attribution or a separately authorized resource
dependency experiment.

## FILES CHANGED

- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h`
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
- `src/ffmpeg/amd_config.py`
- `Raporty/RAPORT_AMD_ETAP_5V_VP_DRIVER_WAIT_ORIGIN_OPT.md`
- diagnostic artifacts under `scratch/etap5v_*`

## PRE-EXISTING PRESERVED

**YES.** Existing dirty-worktree changes and governance/test infrastructure were
preserved. NVIDIA, Intel, generic CPU, map, HUD, gauge, charts, ABOVE,
queue-depth, AMF policy, and output pool production behavior were not changed.
