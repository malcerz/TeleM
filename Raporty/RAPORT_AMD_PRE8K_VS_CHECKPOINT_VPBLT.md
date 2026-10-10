# Raport AMD PRE_8K_BASE vs checkpoint — 4K VideoProcessorBlt

Data: 2026-09-23  
Repozytorium: `C:\_DEV\SportCamHUD-amd`  
Branch glowny: `amd-bikeridehud`

## Wynik

```text
CHECKPOINT=0ef407e9ce71cb192f43289abebf6b60c8259839
CHECKPOINT_PARENT=1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98
TEST_BASE_COMMIT=1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98
LAST_KNOWN_GOOD_4K=NOT PROVEN for this exact runtime/workload; historical 4K reports are not an equivalent A/B baseline
CASE=CASE B
CODE_REGRESSION_FROM_8K_NOT_PROVEN=True
DRIVER_RUNTIME_STATE_SUSPECTED=True
REGRESSION_INTRODUCED_BY_8K_CHECKPOINT=False (not proven)
SAFE_TO_PUSH=False
```

PRE_8K_BASE reproduces the same 4K `VideoProcessorBlt` `E_FAIL` as the
checkpoint. Therefore the 8K changes cannot be identified as the cause from
this A/B test. No source change or diff-isolation was performed.

## Initial state and parent selection

```text
CHECKPOINT_PARENT_COMMAND=git show --no-patch --oneline 0ef407e^
CHECKPOINT_PARENT=1b5485c test: add regression coverage and pre-AMD validation reports
PRE8K_WORKTREE=C:\_DEV\SportCamHUD-amd-pre8k
PRE8K_HEAD=1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98
PRE8K_WORKTREE_CLEAN_BEFORE_TEST=True
MAIN_DIRTY_TREE_PRESERVED=True
```

The parent is the direct pre-8K parent of the requested checkpoint. Existing
main-tree modifications were not reset, stashed, cleaned, committed, or
pushed.

## Exact workload

```text
VIDEO=C:\_DEV\SportCamHUD-amd\Video\GX020079.MP4
INPUT=3840x2160
OUTPUT=3840x2160
DECODE=D3D11VA / Media Foundation
HUD=OFF
ENCODER=AMF ON
FRAMES_REQUESTED=1 for the deciding smoke
```

The existing init-gate host was run from the isolated worktree so that
`native\d3d11_amf_pipeline\bin\telem_amd_native.dll` came from the selected
revision. No `AMD_DEBUG_NO_AMF` or `AMD_DEBUG_NO_MF` override was present.

## Build and PRE_8K_BASE result

```text
PRE8K_CMAKE_CONFIGURE=PASS
PRE8K_BUILD=PASS
PRE8K_BUILD_TARGET=telem_amd_native
PRE8K_4K_VP_1F=FAIL
PRE8K_4K_VP_10F=NOT TESTED (1F failed; required stop rule)
PRE8K_VP_BLT_HRESULT=0x80004005 E_FAIL
PRE8K_FRAMES_PROCESSED=0
PRE8K_FAILURE_FRAME=0
PRE8K_DEVICE_REMOVED_REASON=0x0
PRE8K_VIDEO_PROCESSOR_BLT_USED=True (direct path in parent source)
PRE8K_INPUT_DESC=NOT OBSERVED (parent build predates comparable contract dump)
PRE8K_OUTPUT_DESC=NOT OBSERVED (parent build predates comparable contract dump)
PRE8K_SRC_RECT=NOT OBSERVED
PRE8K_DST_RECT=NOT OBSERVED
```

The first 1F run and a fresh-process 1F rerun both returned the same result.
There was no stale init-gate host process before the rerun.

## Checkpoint comparison

The already validated clean-checkpoint run from the preceding A/B report was:

```text
CHECKPOINT_BUILD=PASS
CHECKPOINT_4K_VP_1F=FAIL
CHECKPOINT_4K_VP_10F=FAIL
CHECKPOINT_VP_BLT_HRESULT=0x80004005 E_FAIL
CHECKPOINT_FRAMES_PROCESSED=0
CHECKPOINT_FAILURE_FRAME=0
CHECKPOINT_DEVICE_REMOVED_REASON=0x0
```

The dirty-tree diagnostic run also failed at frame 0 with the same HRESULT;
its observed contract was:

```text
CHECKPOINT_DIRTY_INPUT=3840x2160, DXGI_FORMAT=104 (P010), ArraySize=11, BindFlags=0x208, MiscFlags=0x0, subresource=0, arraySlice=0
CHECKPOINT_DIRTY_OUTPUT=3840x2160, DXGI_FORMAT=103 (NV12), ArraySize=1, BindFlags=0xa8, outputView!=nullptr
CHECKPOINT_DIRTY_SRC_RECT=(0,0,3840,2160)
CHECKPOINT_DIRTY_DST_RECT=(0,0,3840,2160)
CHECKPOINT_FOR_SHADER_SCALER_4K=False
CHECKPOINT_BYPASS_CAN_USE_INPUT_SURFACE_4K=False
CHECKPOINT_COMPUTE_ONLY_TOPOLOGY_4K=False
CHECKPOINT_USE_SHADER_SCALER_4K=False
CHECKPOINT_FRAME_FORMAT=PROGRESSIVE
CHECKPOINT_STREAM_ENABLED=True
```

## Decision and scope stop

```text
CASE_A=NOT APPLICABLE (PRE8K did not PASS)
CASE_B=PASS: PRE8K and checkpoint both fail with VideoProcessorBlt E_FAIL
CASE_C=NOT USED; the exact pre-8K reproduction supplied a stronger A/B result
DIFF_ISOLATION=NOT PERFORMED by stop rule
MINIMAL_FIX=NONE
8K_TESTS=NOT TESTED
READBACK=NOT TESTED
X265=NOT TESTED
```

The result points to a common driver/runtime state or common VP resource/view
contract issue, but does not prove which one. Per procedure, the next
diagnostic action requires a Windows/driver restart. No restart was executed
in this run; no further 8K or code experiments were started.

```text
RESTART_REQUIRED=True
RESTART_EXECUTED=False
```

## Notifications

```text
NTFY_TOPIC=MalcerzPOP
NTFY_ATTEMPTS=3
NTFY_RESULTS=3/3 successful, EXIT_CODE=0
NTFY_MESSAGE=AMD PRE8K vs checkpoint: PRE8K 4K VideoProcessorBlt=FAIL 0x80004005 frame 0; checkpoint=FAIL; CASE B common runtime/driver state suspected; restart required.
```

The three response IDs were `7suUohZsEQbE`, `g8mwvzfQ0h0F`, and
`W0glUeWPEeSz`; they were appended to the existing `ntfy_result.txt`.

## Timing

```text
TOTAL_STAGE_WALL_TIME=NOT INSTRUMENTED; measured tool wall-time for build, two PRE8K runs, inspection, and NTFY was approximately 10.3 seconds
AUDIT_TIME=NOT INSTRUMENTED
REPRO_TIME=1.9 seconds measured for the two PRE8K process calls
IMPLEMENTATION_TIME=0 seconds (no code change)
VALIDATION_TIME=0 seconds after CASE B stop
LONGEST_SINGLE_COMMAND_SECONDS=6.4 (configure/build command)
```

## Backend isolation and final summary

No NVIDIA, Intel, CPU/reference, or unrelated AMD renderer code was changed.
Only this report and the existing notification log were updated in the main
repository; the PRE8K build and tests used a separate worktree.

```text
FINAL=FAIL / CASE B / BLOCKED pending Windows or driver restart
CHECKPOINT_4K_VP=FAIL
PRE8K_4K_VP=FAIL
REGRESSION_AFTER_8K=NOT PROVEN
SAFE_TO_PUSH=False
```
