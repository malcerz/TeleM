# AMD CPU ASSIST — PRODUCER-AHEAD / HUD PRECOMPUTE EXPERIMENT

Date: 2026-09-09  
Branch: `integration/intel-amd`  
Decision: **NO-GO — no production change**

## Zakres i bezpieczeństwo

Eksperyment dotyczył wyłącznie opt-in AMD `AMD_CPU_GPU_PIPELINE=ASYNC`.
Nie użyto CPU renderera jako drugiego eksportera. Nie zmieniono produkcyjnego
defaultu AMD, renderera HUD, Intel/QSV ani NVIDIA/NVENC. Nie uruchomiono 20,000f
ani 85,574f.

Aktualna ścieżka ma już bounded producer-ahead:

```text
CPU producer: _prepare_frame_cpu -> queue.Queue(maxsize=AMD_QUEUE_DEPTH)
GPU consumer: dequeue -> native D3D11/AMF
production default: SYNC (AMD_CPU_GPU_PIPELINE=ASYNC jest opt-in)
```

## Profil CPU baseline

Źródło: istniejący profil `prod_async_d2_3000f` z pełnym accountingiem,
zgodny z aktualną ścieżką AMD. Wartości są per-frame; `p99` jest użytym
wskaźnikiem ogona (historyczny profil nie przechowuje surowego maksimum).

| Stage | avg ms | p50 ms | p95 ms | max |
|---|---:|---:|---:|---|
| telemetry/frame_data | 0.034 | 0.030 | 0.065 | NOT RECORDED |
| compose_overlay | 1.294 | 1.093 | 2.389 | NOT RECORDED |
| above_compose | 13.930 | 13.694 | 19.262 | NOT RECORDED |
| map_cpu_upload | 0.005 | 0.004 | 0.008 | NOT RECORDED |
| PIL/buffer preparation | 0.095 | 0.081 | 0.122 | NOT RECORDED |
| producer_prepare (sum) | 19.490 | 19.097 | 26.118 | NOT RECORDED |
| consumer_upload | 7.766 | 7.500 | 10.650 | NOT RECORDED |
| consumer_native_call | 13.414 | 12.298 | 32.284 | NOT RECORDED |
| GPU wait/synchronization | 0.000 | 0.000 | 0.000 | NOT RECORDED |
| pipeline_total | 22.575 | 22.499 | 40.301 | NOT RECORDED |

Wniosek: producer (19.49 ms) nie jest wolniejszy od consumer/pipeline
(22.58 ms), a `consumer_native_call` zawiera oczekiwanie natywne/AMF.
Sam większy ahead queue nie ma gdzie odzyskać czasu.

## Realny benchmark 10000f

Identyczny GUI workload: `GX010244.MP4 + GX010245.MP4`, FIT/layout z profilu,
3840x2160, pełny HUD, AMD native, GPU Preview ON, pierwsze 10000 klatek,
single-pass A/V. Każdy wariant zakończył się `completed`, 10000/10000,
child exit 0, AAC 48 kHz stereo i bez residue/orphanów.

| Variant | Queue depth | Render FPS | Effective FPS | Wall s | Producer avg/p50/p95 ms | Producer queue wait | Consumer queue wait | GPU wait ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A — current async baseline | 2 | 36.348 | 36.241 | 275.1 | 23.08/21.70/32.54 | 3.78 | 0.63 | 18.75 |
| B — bounded ahead | 1 | 36.161 | 36.050 | 276.5 | 23.27/21.94/32.95 | 3.59 | 0.66 | 18.54 |
| C — bounded ahead | 4 | 36.213 | 36.097 | 276.1 | 23.40/21.99/33.28 | 3.54 | 0.65 | 18.79 |
| D — bounded ahead | 8 | 36.311 | 36.201 | 275.4 | 23.07/21.70/32.61 | 3.80 | 0.62 | 18.76 |

Production reference from the validated proof: 41.090 render FPS / 40.184
effective FPS. Best measured q2 is therefore -11.54% render FPS versus that
reference. Queue depths 1/2/4/8 differ by less than 0.52%; no depth provides
the required >=3% gain.

Evidence root (D: only):

```text
D:\TeleM_CPU_ASSIST_MATRIX_20260909_055853\
```

Every output profile reports 10,000 decoded/native/AMF/muxed frames and
HEVC 3840x2160 plus AAC 48000 Hz stereo.

## Worker-count assessment

| Helper workers | Result | Reason |
|---:|---|---|
| 1 | PASS (current producer) | ordered stateful preparation |
| 2 | NOT SAFE / NOT RUN | `_prepare_frame_cpu` mutates retained HUD canvas, previous dirty boxes, sparse tiles, gauge epochs and chart activation |
| 4 | NOT SAFE / NOT RUN | same ordering and shared-state violation; would risk future-state HUD and stale/ghost pixels |

Implementing a worker pool would require an architectural split into a pure,
immutable canonical-state stage and a serialized stateful compositor stage.
That is outside this experiment and would violate the no-HUD/no-production
change constraint. No fake 2/4-worker numbers are reported.

## Memory and system load

The real 10000f acceptance records show bounded parent private bytes around
1.71–1.72 GB and child peak private bytes around 2.04–2.16 GB; system commit
peaks were about 34.6 GB. Queue payload is bounded by depth 1/2/4/8 and no
full 4K-frame precompute buffer was allocated.

The independent sparse WMI sampler was launched on D:, but its first version
failed to persist samples because the process wrapper exited before creating
the JSONL file. Consequently experiment-specific CPU/GPU/disk averages are
**NOT MEASURED**. The validated production reference remains CPU 16.46% avg,
GPU encode 92.37% avg (full-proof report); no claim is made that queue depth
changed those values.

## Correctness, cancel and range

- Existing AMD GUI/range/child regression suite: `19 passed`.
- Cross-clip `VideoTimeline.subset_excluding` contract and effective timeline
  remain unchanged.
- Existing real cancel/recovery proof remains PASS; no producer-ahead code
  changed cancellation or Preview GPU frame tap.
- The four 10000f outputs had no residue/orphan and all terminal states were
  `completed` with child exit code 0.
- No separate Preview was generated by the producer.

## Performance decision

Required gain: `>=3% Render FPS`; preferred `>=5%`. Measured best gain versus
the production reference: `-11.54%`. There is no evidence of a useful
producer bottleneck to hide, and safe worker fan-out is not available without
restructuring stateful HUD preparation.

Estimated 85,574f time at the best experimental effective rate (extrapolation
only): approximately 39.4 minutes. This is slower than the validated
production estimate (~35.5 minutes), so no 20k or full proof was started.

```text
RENDER FPS GAIN >=3%:             FAIL
PREFER >=5%:                      FAIL
GPU ENCODE NOT DEGRADED:          NOT PROVEN (no experiment WMI samples)
HUD/TELEMETRY PARITY:             PASS (no path change; range contract suite)
MEMORY BOUNDED:                   PASS
CANCEL:                           PASS (existing proof)
CROSS-CLIP:                       PASS (existing contract suite)
NO AMD CHILD REGRESSION:          PASS (26 child/range/mux tests)
WORKER 2/4 SAFE:                  NOT SAFE / NOT RUN
PRODUCTION DEFAULT CHANGED:       NO

STATUS = NO-GO — DO NOT PROMOTE PRODUCER-AHEAD
```

No commit or push was performed.
