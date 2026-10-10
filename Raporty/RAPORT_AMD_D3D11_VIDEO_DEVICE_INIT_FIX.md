# AMD D3D11 Video Device init diagnostics

Date: 2026-09-22  
Repository: `C:\_DEV\SportCamHUD-amd`  
Branch: `amd-bikeridehud`  
Checkpoint: `0ef407e`

## Result

```text
CASE=BLOCKED
CASE_DETAIL=The reported ID3D11VideoDevice initialization failure is not reproducible in a fresh process. The current 4K production gate reaches and passes both QI calls, then fails at VideoProcessorBlt on frame 0.
SAFE_TO_PUSH=False
```

The initial working tree was already substantially dirty. No existing user changes
were reset, stashed, cleaned, or committed.

## Device creation contract

```text
ADAPTER_DESCRIPTION=AMD Radeon (TM) Graphics
ADAPTER_VENDOR_ID=0x1002
ADAPTER_DEVICE_ID=0x15e7
ADAPTER_LUID=000000000000B7D5 (production log: 0x00000b7d5)

D3D11_DRIVER_TYPE=HARDWARE
D3D11_CREATE_DEVICE_FLAGS=0x800
VIDEO_SUPPORT_FLAG_PRESENT=True
D3D_FEATURE_LEVEL=0xb100 (D3D_FEATURE_LEVEL_11_1)
D3D11_CREATE_DEVICE_HRESULT=0x0 S_OK
```

The minimal probe enumerated the complete adapter set:

```text
ADAPTER_0=AMD Radeon (TM) Graphics, vendor=0x1002, device=0x15e7, SOFTWARE=False
ADAPTER_1=Microsoft Basic Render Driver, vendor=0x1414, device=0x8c, SOFTWARE=True
SELECTED_ADAPTER_VENDOR=AMD
```

## QueryInterface and removal state

Production 4K creation log:

```text
ID3D11VideoDevice_QI_HRESULT=0x0 S_OK
ID3D11VideoContext_QI_HRESULT=0x0 S_OK
DEVICE_REMOVED_REASON_AT_INIT=0x0 S_OK
```

The failure path now logs the exact HRESULT and calls
`GetDeviceRemovedReason()` immediately after a failed QI. No failed-QI path was
observed in this run.

## Checkpoint comparison

```text
COMMON_INIT_DIFF_FOUND=True
```

The `True` value is limited to the AMF initialization/configuration area:

```text
native/d3d11_amf_pipeline/src/telem_amd_native.cpp
  git diff 0ef407e -- .../telem_amd_native.cpp
  hunk @@ -1908,14 +1982,82 @@
  extended AMF Initialize(...) arguments and diagnostic skipAmf handling
```

No checkpoint diff was found in the production `D3D11CreateDevice` call,
adapter selection, device flags, requested feature levels, or
`D3D11VideoProcessorPipeline::Initialize` QI sequence. The production call
already contains `D3D11_CREATE_DEVICE_VIDEO_SUPPORT`.

## Minimal fresh-process probe

The existing probe was reused; it was first made runnable with the required
MinGW runtime PATH. It performs DXGI enumeration, explicit AMD adapter
selection, device creation, both QI calls, and exits without TeleM, AMF, decode,
shader, or x265.

```text
MINIMAL_D3D11_DEVICE_CREATE=PASS (0x0 S_OK)
MINIMAL_VIDEO_DEVICE_QI=PASS (0x0 S_OK)
MINIMAL_VIDEO_CONTEXT_QI=PASS (0x0 S_OK)
PROBE_CURRENT_FLAGS=0x800 / PASS
PROBE_WITH_VIDEO_SUPPORT_FLAG=0x800 / PASS
PROBE_BASE_FLAGS=0x0 / PASS
DEVICE_REMOVED_REASON=0x0 S_OK
```

```text
PRE_RESTART_PROBE=PASS
POST_RESTART_PROBE=NOT RUN (restart not justified; fresh-process probe passed)
```

## Production gates

The native DLL was rebuilt after adding contract/QI diagnostics.

```text
BUILD=PASS
4K_AMF_10F=FAIL
4K_FAILURE_STAGE=VideoProcessorBlt frame 0
4K_FAILURE_HRESULT=0x80004005 E_FAIL
4K_DEVICE_REMOVED_REASON=0x0
```

The same VP failure reproduced with `AMD_DEBUG_NO_AMF=1` and HUD disabled, so
AMF initialization is not the immediate cause. A colorspace mode 2 retry did
not change the result.

```text
SHADER_ONLY_10F=NOT RUN (4K gate failed)
SHADER_ONLY_100F=NOT TESTED
SHADER_ONLY_300F=NOT TESTED
DEVICE_REMOVED_REASON_AFTER_SHADER=NOT TESTED
```

Per the requested gate, no 8K shader-only run, readback, or x265 work was
started after the 4K failure.

## Root cause and fix

```text
ROOT_CAUSE=NOT CONFIRMED for the previously reported common D3D11 QI failure; the fresh minimal probe and current production init both pass. Current blocker is a separate VideoProcessorBlt E_FAIL on 4K frame 0 with removal reason 0x0.
FIX=Added diagnostic logging only: full device contract, adapter identity, exact QI HRESULTs/symbols, and immediate device-removal reason logging. No rendering behavior or 8K architecture was changed by this task.
```

This is therefore `CASE=BLOCKED`, not a proven 8K shader regression and not a
proven TDR.

## Files

```text
MODIFIED_FILES=
- native/d3d11_amf_pipeline/src/telem_amd_native.cpp (device contract logging)
- native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp (QI HRESULT/removal diagnostics)
- ntfy_result.txt (three successful warning notifications)

CREATED_FILES=
- scratch/amd_d3d11_init_gate_host.cpp
- scratch/amd_d3d11_init_gate_host.exe
- Raporty/RAPORT_AMD_D3D11_VIDEO_DEVICE_INIT_FIX.md
```

The existing `scratch/probe_d3d11_video_device.cpp/.exe` was pre-existing and
reused, not recreated by this task.

## Timing and notifications

```text
TOTAL_STAGE_WALL_TIME=approximately 25 minutes
AUDIT_TIME=approximately 6 minutes
REPRO_TIME=approximately 9 minutes
IMPLEMENTATION_TIME=approximately 7 minutes
VALIDATION_TIME=approximately 3 minutes
LONGEST_SINGLE_COMMAND_SECONDS=10.3
NTFY_SUCCESS=True
NTFY_ATTEMPTS=3
```

All three NTFY warning attempts returned HTTP client exit code 0 and are
recorded in `ntfy_result.txt`.

## Backend isolation / final summary

Only the shared AMD native D3D11 diagnostic logging and a diagnostic host were
touched. NVIDIA, Intel, CPU/reference, shaders, readback, x265, map, GPMF,
and UI paths were not intentionally modified or tested.

```text
FINAL=BLOCKED
4K gate required to continue: FAIL
8K SHADER_ONLY gates: NOT TESTED
SAFE_TO_PUSH=False
```
