# TeleM — AMD ETAP 5U — VP SetStream driver-stall isolation and static-cache proof

## Task

Isolate the wall-clock cost of the three per-frame D3D11 Video Processor
stream setters on the canonical AMD production workload, validate the existing
`AMD_VP_STATE_MODE=STATIC_CACHE`, and screen at most three individual setter
cache candidates.

## Initial state

- Branch: `amd-render`
- HEAD at task start: `3ab0b89`
- Canonical video: `Video/GX020079.MP4`
- Canonical FIT: `Video/GX020079.fit`
- Canonical layout: `C:\_DEV\TeleM\def_layout.json`
- Workload: 3840x2160, 1131 frames, `AMD_NATIVE_D3D11`
- Production baseline: `SYNC / Q0 / VP REFERENCE / pool8 / AMF REFERENCE`
- Earlier GX010115 + Lunch FIT measurements were not used.

The working tree contained extensive prior-stage changes. They were preserved;
no unrelated backend or governance changes were reverted.

## VP setter inventory and state proof

The actual per-frame `ProcessFrame` stream setters are:

1. `VideoProcessorSetStreamFrameFormat`
2. `VideoProcessorSetStreamSourceRect`
3. `VideoProcessorSetStreamDestRect`

The other Video Processor state setters found in `SetupVideoProcessor`,
including color-space setup and stream rotation setup, are context/setup-time
operations rather than per-frame SetStream calls.

The existing state signature combines progressive frame format, source width
and height, destination width and height, input DXGI format, and stream
rotation. The canonical 300-frame trace had exactly one signature for all 301
recorded frames (including the initial frame).

## Implementation

Added three diagnostic-only, opt-in flags:

- `AMD_VP_CACHE_FRAME_FORMAT`
- `AMD_VP_CACHE_SOURCE_RECT`
- `AMD_VP_CACHE_DEST_RECT`

Each candidate caches only its own setter and invalidates on a changed state
signature. The flags apply only in `REFERENCE` mode. `REORDER` remains an
ordering diagnostic, and the existing full `STATIC_CACHE` path remains
unchanged. New per-context cache state is initialized with the pipeline and
there is no production-default enablement.

The benchmark governance resolver now exposes all three flags as zero-valued
production defaults and includes them in the effective configuration and
fingerprint.

## Existing full STATIC_CACHE result

Fresh short canonical R0/R1 sequence (warmups followed by interleaved R0/R1
triplets, 300 frames per measured run):

| mode | mean wall time | mean render FPS | VP setter calls |
|---|---:|---:|---:|
| R0 REFERENCE | 7755.764 ms | 38.813 | all 3 on 301/301 frames |
| R1 STATIC_CACHE | 7851.661 ms | 38.337 | first frame only; 300 skipped |

`STATIC_CACHE` was approximately **1.236% slower** than R0 in this clean short
sequence, therefore it did not meet the >=3% E2E gate.

Native accounting also showed the expected mechanism: REFERENCE spent the
SetStream wall time in `VideoProcessorSetStreamFrameFormat` (mean 9.2289 ms in
the sampled run), while STATIC_CACHE removed setter calls but moved the wait
into `VideoProcessorBlt` (mean VP Blt 8.3048 ms). This is a driver/API wait
relocation, not a free CPU optimization.

## Individual setter screening

Each row used canonical 300-frame exports with one warmup and three measured
runs. REF and each candidate were run with the same production defaults,
SYNC/Q0/pool8/AMF REFERENCE, and diagnostic accounting enabled.

| candidate | mean wall time | mean render FPS | setter skipped | E2E delta vs REF |
|---|---:|---:|---:|---:|
| REF | 9854.8 ms | 30.559 | 0 | reference |
| FMT (`AMD_VP_CACHE_FRAME_FORMAT=1`) | 9835.3 ms | 30.655 | 300/301 | -0.20% |
| SRC (`AMD_VP_CACHE_SOURCE_RECT=1`) | 10193.9 ms | 29.544 | 300/301 | +3.44% slower |
| DST (`AMD_VP_CACHE_DEST_RECT=1`) | 9964.5 ms | 30.234 | 300/301 | +1.11% slower |

The native traces confirm that each candidate skipped exactly its selected
setter while the other setters continued to execute. The one-frame initial
application and the single state signature were preserved.

The setter-level timing from representative first measured traces was:

| mode | FrameFormat avg | SourceRect avg | DestRect avg |
|---|---:|---:|---:|
| REF | 2.1023 ms | 0.0092 ms | 0.0018 ms |
| FMT | 0 ms after first frame | 8.961 ms | 0.0072 ms |
| SRC | 1.3121 ms | 0 ms after first frame | 0.0117 ms |
| DST | 2.9768 ms | 0.0094 ms | 0 ms after first frame |

The apparent wall time is noisy across sequential short exports; the clean
interleaved full-cache R0/R1 result is the authoritative STATIC_CACHE gate.
The individual screen still rejects all candidates because none reaches the
required 3% E2E improvement, and two regress.

## Correctness, lifecycle, and backend isolation

- State signature contains the relevant format, dimensions, input format, and
  rotation state.
- Individual caches invalidate independently when that signature changes.
- State is per native pipeline context; no global cache was introduced.
- `STATIC_CACHE` and `REORDER` behavior were not repurposed.
- Production defaults remain `VP REFERENCE`; no candidate is enabled.
- Focused regression suite: **25 passed**.
- Native AMD DLL target build: **PASS**.
- Full repository build: **NOT TESTED / BLOCKED** by the pre-existing,
  unrelated `d3d11_etap2c_poc` target referring to missing
  `CreateHUDTexture`; the production `telem_amd_native` target linked
  successfully.
- Pre-encode pixel parity for a newly enabled candidate: **NOT TESTED**,
  because no candidate passed the performance gate and none is production
  enabled.
- Full 1131-frame candidate acceptance, HDR/temporal validation, and
  multi-file/context-reset acceptance: **NOT TESTED**, because the >=3% gate
  failed before production acceptance.

No NVIDIA, Intel, ASYNC, queue-depth, pool, AMF, map, HUD, gauge, chart, or
ABOVE behavior was changed.

## Final decision

**NO PRODUCTION OPTIMIZATION.**

The existing full `STATIC_CACHE` is retained as an explicit diagnostic mode,
but remains non-production. None of the three individual setter caches is
promoted. The true remaining bottleneck is the driver/API wait associated with
the VP critical path, which is exposed rather than removed by SetStream
skipping.

## Changed files

- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h`
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
- `src/ffmpeg/amd_config.py`
- `Raporty/RAPORT_AMD_ETAP_5U_VP_SETSTREAM_STATIC_CACHE_OPT.md`

## Final PASS/FAIL summary

| acceptance item | result |
|---|---|
| actual per-frame SetStream inventory | PASS |
| state-signature and lifecycle audit | PASS |
| full STATIC_CACHE >=3% E2E | FAIL (approximately -1.236%) |
| individual setter candidate >=3% E2E | FAIL (none) |
| production default change justified | NO |
| backend isolation | PASS |
| ETAP 5U production optimization | **NO PRODUCTION OPTIMIZATION** |
