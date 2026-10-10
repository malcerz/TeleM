# AMD 8K checkpoint — pure shader verification

Date: 2026-09-22  
Repository: `C:\_DEV\SportCamHUD-amd`  
Checkpoint: `0ef407e9ce71cb192f43289abebf6b60c8259839`  

## Result fields

```text
CHECKPOINT_SHA=0ef407e9ce71cb192f43289abebf6b60c8259839
BUILD=PASS

X265_INITIALIZED=False
READBACK_INITIALIZED=False
STAGING_POOL_CREATED=False

PURE_SHADER_1F=PASS
PURE_SHADER_2F=PASS
PURE_SHADER_10F=PASS
PURE_SHADER_100F=BLOCKED
PURE_SHADER_300F=BLOCKED

DEVICE_REMOVED_REASON=0x0 through completed pure 10F run; later 100F/300F harness run did not yield a stable HRESULT and ended in harness process hang/TDR

CHECKPOINT_MISSING_SYNC_HUNK=False

CHECKPOINT_SHADER_PATH_VERIFIED=False
SAFE_TO_PUSH=False

MAIN_WORKTREE_UNCHANGED=True

TOTAL_STAGE_WALL_TIME=approximately 25 minutes
LONGEST_SINGLE_COMMAND_SECONDS=30.2
```

## Verification

An isolated temporary C++ harness was built only in the checkpoint worktree. It
loaded the checkpoint DLL, enabled D3D11VA decode, and used the returned decoder
surface directly for:

```text
decoder surface 7680x4320 P010
→ CopySubresourceRegion
→ ordinary 8K BIND_SHADER_RESOURCE texture
→ P010 Y/UV SRV
→ 1:1 compute shader
→ 8K output pool
→ event-query completion
```

The harness did not initialize x265, FFmpeg stdin, CPU readback, Map, EOS drain,
or a CPU readback staging pool. The output pool was GPU-only. The first three
gates passed with `DEVICE_REASON_AFTER_COPY=0x0` and
`DEVICE_REASON_AFTER_SHADER=0x0`; 2F reported both decoder slices and both
frames completed successfully.

The first 100F attempt used per-frame resource creation and failed at frame 12
with a process access violation. A persistent-pool/event-query variant then
hung during a later dispatch and was stopped as a temporary diagnostic process.
This is not accepted as a checkpoint regression because the failure was in the
standalone harness/resource-lifetime experiment, not a stable device-removal
result from the checkpoint path. Therefore 100F and 300F are `BLOCKED`, not
`PASS`.

## Previous FAIL contamination

The committed Python gate harness hardcodes `AMD_NATIVE_ENCODER_MODE=x265`.
Consequently it necessarily creates the x265 staging/query ring and reaches the
readback/flush lifecycle. Its previous 2F FAIL therefore was not a pure
copy+shader-only result. A flush-bypassed run still used that contaminated
initialization and was not accepted as a pure gate.

## Sync-hunk audit

The main dirty working tree was compared with the checkpoint only for the AMD
pipeline files and only for event-query ownership, decoder-copy reuse, and
output-pool synchronization. No checkpoint-required synchronization hunk was
missing from the commit:

```text
CHECKPOINT_MISSING_SYNC_HUNK=False
```

The remaining main-tree changes in those files are unrelated map,
ALT_VISUAL, AMF/QP, and telemetry work and were not copied, reverted, staged,
or committed.

## Build and cleanup

The clean worktree was configured and built with the native AMD target:

```text
ninja -C native\d3d11_amf_pipeline\build telem_amd_native
```

The build passed and generated
`native\d3d11_amf_pipeline\bin\telem_amd_native.dll` from the checkpoint.
The temporary worktree and temporary harness were removed after the worktree
was verified clean. No push was performed. The main dirty tree was preserved.

## Final interpretation

The evidence does **not** show a 1F/2F/10F regression in the checkpoint's
decoder-copy/SRV/compute interoperability. It does show that the earlier 2F
FAIL was contaminated by x265/readback initialization. A 300-frame pure
shader stability proof is still `NOT PROVEN`; true 8K x265 end-to-end and
8K readback remain separate blockers.
