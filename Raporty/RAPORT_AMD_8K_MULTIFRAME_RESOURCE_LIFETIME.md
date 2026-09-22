# Raport AMD — 8K multiframe resource lifetime / synchronization

## Task

Validate the true 8K CPU-x265 path:

```text
8K HEVC P010 -> D3D11VA 7680x4320 -> ordinary 8K SRV texture
-> GPU 1:1 compositor -> 8K NV12 -> readback -> libx265
```

The 4K downscale path and `VideoProcessorBlt` output-view path are explicitly
out of scope for this task.

```text
TRUE_8K_REQUIRED=True
FINAL_OUTPUT=7680x4320
4K_DOWNSCALE_AS_8K_SOLUTION=False
```

## Initial state

The previous multiframe reproducer reported an access violation around frame
7. A traced run showed the earlier GPU failure more precisely: after the 8K
compute dispatch on frame 7 the device reported `0x887A0006`
(`DXGI_ERROR_DEVICE_HUNG`), and the later CPU access violation was therefore
treated as a secondary symptom. One-frame copy/SRV/shader/readback/x265 had
previously passed.

```text
ROOT_CAUSE=GPU ownership/synchronization hazard on reusable 8K copy/output resources; fixed for copy+shader with an event-query wait. A separate staging/readback driver failure remains.
```

Required crash fields:

```text
ACCESS_VIOLATION_FRAME=7 (historical reproducer)
ACCESS_VIOLATION_ADDRESS=NOT_CAPTURED
ACCESS_VIOLATION_READ_WRITE_EXEC=WRITE (NOT PROVEN; derived from prior harness wording)
FAULTING_FUNCTION=NOT_CAPTURED
FAULTING_SOURCE_FILE=NOT_CAPTURED
FAULTING_SOURCE_LINE=NOT_CAPTURED
STACK_TRACE=NOT_CAPTURED (GDB run did not crash; the traced failure was device removal)
```

The Windows D3D11 debug layer was unavailable. Creating the device with the
debug flag returned `0x887A002D`, so no debug-layer message stream could be
used.

## Exact implementation

Changed AMD native code keeps the CPU-x265 path compute-only:

- output pool is `7680x4320`;
- no `VideoProcessorBlt` and no `VideoProcessorOutputView` dependency;
- decoder-array SRV is not created;
- the decoder surface is copied with `CopySubresourceRegion` to one ordinary
  8K texture with `D3D11_BIND_SHADER_RESOURCE`;
- SRVs are created only on that copied texture;
- the 1:1 compute path writes the 8K output pool;
- an event query records compute completion and the next frame waits for that
  ownership before reusing the copy/output resources;
- normal frames do not call `Flush()` for synchronization;
- x265 end-of-stream drain performs one `Flush()` before waiting for the
  staging-query ring. This is not a per-frame flush.

Resource/lifetime audit:

```text
COPY_TEXTURE_LIFETIME=single reusable ordinary 8K SRV-only texture
COPY_TEXTURE_COUNT=1
COPY_TEXTURE_RECREATED_PER_FRAME=False
DECODER_SURFACE_LIFETIME=IMFSample/IMFMediaBuffer provides decoder texture; pPendingDecodedTex is held through ProcessFrame and released after submission
GPU_COPY_COMPLETION_GUARANTEE=event query wait before next CopySubresourceRegion; no permanent per-frame Flush
OUTPUT_POOL_SIZE=8
COPY_POOL_SIZE=1
STAGING_POOL_SIZE=3
INDEX_SEQUENCE_FIRST_20=0,1,2,3,4,5,6,7,0,1,...
DOUBLE_RELEASE_FOUND=False (trace/audit)
DANGLING_POINTER_FOUND=NOT_PROVEN (no direct dangling pointer; old CPU AV was secondary to device removal)
POOL_INDEX_BUG_FOUND=False
GPU_SYNC_BUG_FOUND=True (fixed for copy+shader ownership)
```

## Tests

All copy+shader tests used the 8K input and `AMD_8K_GATE=SHADER_1TO1`, with
HUD off. The historical script labels were retained for compatibility, but
these runs did not perform readback or x265.

```text
COPY_SHADER_2F=PASS
COPY_SHADER_10F=PASS
COPY_SHADER_100F=PASS
COPY_SHADER_300F=PASS
COPY_8K_TO_SRV_TEXTURE=PASS
SRV_ON_COPIED_8K_TEXTURE=PASS
8K_SHADER_1TO1=PASS
DEVICE_REASON_AFTER_COPY=0
DEVICE_REASON_AFTER_DISPATCH=0 through 300 frames
```

The traced pre-fix run reproduced the original GPU failure:

```text
FRAME=7
STAGE=after DownscaleCompute
DEVICE_REMOVED_REASON=0x887A0006 (DXGI_ERROR_DEVICE_HUNG)
```

After the event-query fix, the 300-frame run completed without device
removal. The final 8K output pool remained 8K throughout; no 4K VP output
view was used.

## Readback / x265 gate

The next gate exposed a separate blocker in the 8K GPU-to-CPU staging path.
Before the final-drain fix, a 10-frame x265 test stalled in the drain for
120 seconds. After adding the one-time end-of-stream `Flush()`, a traced
2-frame run reached the staging/readback drain but reported
`0x887A0020` (`DXGI_ERROR_DRIVER_INTERNAL_ERROR`). The test harness was
corrected so a failed native flush cannot be reported as PASS.

```text
READBACK_10F=FAIL_DEVICE_REMOVAL 0x887A0020 during x265 staging drain
READBACK_100F=NOT RUN (fail-fast after 10f failure)
READBACK_FORMAT=NV12 (configured)
READBACK_BYTES=49766400 (configured bytes/frame; 47.46 MiB)
READBACK_MS=NOT MEASURED for a completed multiframe readback; previous 1f result was 23.0324 ms
X265_1F=PASS (previous stage)
X265_10F=NOT PROVEN (first attempt stalled; no accepted result)
X265_30F=NOT RUN
X265_FRAME_ENCODE_MS=NOT RUN
4K_AMF_REGRESSION=NOT RUN (stage stopped at first downstream failure)
```

The 2-frame trace showed copy and frame 0 compute submission succeeding; the
device was removed while the following multiframe path was being drained.
This is now a readback/staging interoperability blocker, not evidence that
the decoder-array-to-ordinary-8K-SRV copy failed.

## Build and timing

```text
BUILD=PASS telem_amd_native (CMake/Ninja target)
FULL_CMAKE_BUILD=NOT RUN; unrelated pre-existing d3d11_etap2c_poc target remains broken
TOTAL_STAGE_WALL_TIME=~40 min (estimated from command timestamps)
AUDIT_TIME=~5 min
REPRO_TIME=~18 min
IMPLEMENTATION_TIME=~10 min
VALIDATION_TIME=~7 min
LONGEST_SINGLE_COMMAND_SECONDS=120 (aborted x265/readback drain after no progress)
```

The 300-frame diagnostic copy+shader run reported approximately 1.88 s total
wall time and 0.21 ms mean GPU-process time, but this is not a production
benchmark because the gate mode enables diagnostic synchronization.

## Risks and backend isolation

- `DXGI_ERROR_DRIVER_INTERNAL_ERROR` remains unresolved for the 8K staging
  readback ring; the full true-8K CPU-x265 export is therefore not proven.
- The D3D11 debug layer was unavailable, so validation relies on explicit
  pointer/ref/lifetime tracing and device-removal checks.
- The patch is scoped to `AMD_NATIVE_D3D11` 8K CPU-x265 resource ownership and
  drain behavior. NVIDIA, Intel, 4K AMF, map, chart, and production GPU-gauge
  paths were not changed by intent.
- Existing working-tree modifications were preserved; this report does not
  claim unrelated dirty files are part of this task.

## Final summary

```text
CASE=PARTIAL — multiframe 8K copy+shader synchronization fixed and proven; 8K staging readback remains blocked
GATE_A_COPY=PASS
GATE_B_SRV=PASS
GATE_C_SHADER_1TO1=PASS 2/10/100/300f
GATE_D_READBACK=FAIL 0x887A0020 at multiframe drain
FINAL_8K_X265_EXPORT=NOT PROVEN
STATUS=PARTIAL/BLOCKED at readback-staging interoperability
```
