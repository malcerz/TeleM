# AMD production SHADER_ONLY verification

Date: 2026-09-22  
Repository: `C:\_DEV\BikeRideHUD-amd`  
Branch: `amd-bikeridehud`  
Checkpoint baseline: `0ef407e9ce71cb192f43289abebf6b60c8259839`

## Required result fields

```text
BUILD=PASS

DIAGNOSTIC_MODE=AMD_8K_GATE=SHADER_ONLY
X265_INITIALIZED=False
READBACK_INITIALIZED=False
STAGING_POOL_CREATED=False
VIDEO_PROCESSOR_BLT_USED=False

COPY_TEXTURE_COUNT=NOT REACHED
OUTPUT_POOL_SIZE=NOT REACHED
INDEX_SEQUENCE_FIRST_20=NOT REACHED

SHADER_ONLY_10F=BLOCKED
SHADER_ONLY_100F=NOT TESTED (10F gate blocked)
SHADER_ONLY_300F=NOT TESTED (10F gate blocked)

FAIL_FRAME=NOT REACHED
FAIL_STAGE=D3D11VideoProcessorPipeline::Initialize / ID3D11VideoDevice QueryInterface
DEVICE_REMOVED_REASON=NOT REACHED (no frame context was created)

CHECKPOINT_PRODUCTION_SHADER_300F=NOT PROVEN
CHECKPOINT_SHADER_PATH_VERIFIED=False

4K_AMF_10F=BLOCKED at the same ID3D11VideoDevice initialization stage

SAFE_TO_PUSH=False

MODIFIED_FILES=
- native/d3d11_amf_pipeline/src/telem_amd_native.cpp
- scratch/test_amd_production_shader_only.py

CREATED_FILES=
- Raporty/RAPORT_AMD_8K_PRODUCTION_SHADER_ONLY_VERIFY.md

TOTAL_STAGE_WALL_TIME=approximately 10 minutes
LONGEST_SINGLE_COMMAND_SECONDS=6.9
```

## Implementation

Added the minimal production diagnostic mode `AMD_8K_GATE=SHADER_ONLY`.
It selects the existing 8K compute-only topology by setting the same pipeline
CPU-x265 topology flag used by the production 8K path, while keeping
`isX265=False`. In this mode the DLL does not initialize encoded output, AMF,
x265 staging/query resources, CPU readback, or the upload staging texture.

The existing production `telem_amd_process_frame` remains the frame entrypoint.
It uses the existing decoder ownership wait, persistent decoder-copy texture,
existing 8K output pool, SRV creation, compute dispatch, and event-query
completion path. No standalone resource lifecycle or per-frame diagnostic pool
was added.

The diagnostic log is limited to the first 20 frames and then every 50th frame,
and reports decoder slice, output index, copy/output pointers, query wait, copy
device reason, shader device reason, and process result.

## Tests

The native target was rebuilt successfully:

```text
ninja -C native\d3d11_amf_pipeline\build telem_amd_native
BUILD=PASS
```

The new production-path harness was invoked for `SHADER_ONLY 10F`. It did not
reach `telem_amd_process_frame`: `D3D11VideoProcessorPipeline::Initialize`
failed while querying `ID3D11VideoDevice`. The existing capability probe also
reported `AMFInit failed: 1`. A separate 4K AMF 10F smoke stopped at the same
`ID3D11VideoDevice` initialization failure.

Because the 10F gate did not pass, 100F and 300F were not started. This avoids
repeating the same pre-frame failure and avoids misclassifying it as a
copy/SRV/shader regression.

## Case and risk

```text
CASE=BLOCKED
CASE_DETAIL=C — diagnostic-mode runtime initialization blocker
```

This run does not prove a checkpoint regression and does not prove production
8K shader stability. The current machine/driver D3D11 video-device
initialization state must be restored or revalidated before the required
10F/100F/300F production gates can run. Readback and x265 remain untested by
this diagnostic mode.

No commit and no push were performed. Unrelated dirty files were preserved.
