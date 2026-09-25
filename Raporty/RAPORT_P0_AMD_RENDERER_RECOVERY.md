# P0 — AMD renderer recovery after orientation experiments

## Status

`CASE=BLOCKED`

`STATUS=Native AMD dispatch restored, but the real 8K->4K 30F gate terminated before the first source frame; 300F was not started.`

This task deliberately did not repair output orientation or create another
rotation contract.

## Orientation audit

`ORIENTATION_EXPERIMENT_HUNKS_FOUND=`

| File / function | Origin | Finding |
|---|---|---|
| `src/ffmpeg/streaming.py` / `stream_overlay_to_ffmpeg` | `RAPORT_P0_VALIDATION_STALE_TIME_AND_ROTATION_FIX`, then `RAPORT_RESTORE_KNOWN_GOOD_ORIENTATION` | Probe of container rotation, `amd_native_rotation == 0` dispatch gate, and `native_rotation_guard -> software decode/CPU HUD/AMF` branch. This was the direct performance regression. |
| `src/gui/qt/_mixins/render_mixin.py` / `_render_pipeline` | P0 orientation work | Chose `committed_video_info.rotation` and emitted a rotation-contract log instead of using the existing direct container probe. |
| `tests/test_mp4_orientation_metadata_only.py` | metadata-only experiment | Entire test file asserted the CPU/native rotation guard contract. |
| `tests/test_fit_gpx_file_validation.py` / trailing orientation tests | P0/metadata-only follow-up | Four tests covered rotation propagation and the experimental export contract, not FIT/GPX validation. |
| `src/ffmpeg/command_builder.py` | historical baseline | AMD `vflip/hflip/transpose` branches already exist in `0ef407e`; retained because they predate the orientation experiments and are not the native dispatch path. |
| `src/ffmpeg/displaymatrix.py`, `_inject_rot180_displaymatrix` | NVIDIA-only historical path | Retained; the call site is guarded by `nv_rot180_cuda`, not AMD. |
| `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`, `src/ffmpeg/amd_native_exporter.py`, queue/tab/project state | metadata-only report | Current source already had the metadata-only removals reversed before this task: the native source-rotation setter again reaches `SetStreamRotation`; no AMD post-mux tkhd writer or `source_rotation_degrees` / `source_display_matrix` propagation remains. No additional change was made here. |

`ORIENTATION_HUNKS_REMOVED=`

- `stream_overlay_to_ffmpeg`: removed the AMD non-zero-rotation native bypass,
  software-decoder assignment, CPU HUD path diagnostic and
  `native_rotation_guard` branch.
- `_render_pipeline`: restored direct `get_container_rotation(...)` lookup.
- Removed the orientation-only test module and four orientation-only tests
  appended to the FIT/GPX test module.
- Restored the historical comment/test wording changed by the earlier
  physical-transform experiment.

## Preserved functionality

`FIT_VALIDATION_PRESERVED=True`

`FIT_VALIDATION_RESULT=VALID/TIME_OVERLAP`

`VALIDATION_USES_CANDIDATE_VIDEO=True`

Real pair:

```text
GX010312.MP4: 2026-09-23 04:26:17.100 .. 04:56:12.193 UTC (exact)
Poranna_jazda_na_rowerze.fit: 04:25:22 .. 04:55:18 UTC
FIT points: 1797
```

`GPMF_NATIVE_FIX_PRESERVED=True`

`GPMF_CACHE_SECOND_LOAD=True (covered by tests/test_gpmf_native_perf_and_cache_clear.py; the real candidate video probe also logged TELEMETRY CACHE status=HIT)`

No map, HUD, queue, YouTube, capability-gate, shader-downscale, SmartSync or
GPMF production code was intentionally changed.

## Native 30-frame gate

Workload:

```text
F:\GoPro\2026-09-23\GX010312.MP4
F:\GoPro\2026-09-23\Poranna_jazda_na_rowerze.fit
def_layout.json (Full HUD)
8K -> 4K, AMD Quality, 30 frames
```

The corrected production dispatcher emitted:

```text
RENDER PATH: mode=single exporter=amd_native_exporter
decode=selected_native_mode video_frame_path=GPU
hud=amd_native map=amd_native encode=AMF fallback_reason=none
AMD DECODE: GPU / D3D11VA
```

It then completed D3D11 device creation, `ID3D11VideoDevice` and
`ID3D11VideoContext` QI, AMF initialization, compositor configuration, map
cache setup and first HUD-frame preparation. It exited at `first source frame`
with no encoded output, no profile JSON and an empty `.mp4.part` file.

```text
AMD_NATIVE_D3D11=True (dispatcher/native initialization reached)
D3D11VA=True
SHADER_DOWNSCALE=NOT PROVEN (no source frame reached)
AMD_NATIVE_HUD=INITIALIZED; NOT PROVEN ON A COMPOSITED FRAME
AMF=True (initialized)

SOFTWARE_DECODE=False
CPU_VIDEO_FRAME_PATH=False
CPU_HUD=False
NATIVE_ROTATION_GUARD=False

30F_RESULT=FAIL — native process terminated before first source frame
300F_RESULT=NOT STARTED — required 30F gate failed
RENDER_FPS_300F=NOT MEASURABLE
RENDER_PERFORMANCE_RECOVERED=False
ORIENTATION_STATUS=UNRESOLVED (intentionally untouched)
```

The evidence rules out the orientation fallback as the current CPU/0.5-FPS
path: it is removed and the native dispatcher is selected. The remaining
blocker is a native runtime failure before frame processing. Earlier 8K/4K
runtime reports document a recurring `VideoProcessorBlt E_FAIL (0x80004005)`;
this run ended before it emitted a matching HRESULT, so that mechanism is
context only and is not claimed as a proven cause for this exact failure.

## Tests

```text
python -m pytest -q tests/test_fit_gpx_file_validation.py
                    tests/test_gpmf_native_perf_and_cache_clear.py
                    tests/test_amd_direct_mp4_mux.py

36 passed, 1 failed
```

The failure is `test_direct_mp4_mux_with_range_start_offset`: an existing
`MagicMock` from `frame_to_absolute()` reaches datetime normalization and
raises `TypeError`. It occurs before a real native frame and is unrelated to
the removed orientation fallback. It was not changed.

`PY_COMPILE=PASS` for `streaming.py`, `render_mixin.py`, `project_mixin.py`,
and `amd_native_exporter.py`.

`NATIVE_DLL_REBUILD=PASS` using `C:\tools\mingw64\bin\cmake.exe --build native/d3d11_amf_pipeline/build --target telem_amd_native`.

`DIFF_CHECK=PASS` for files changed by this recovery.

## Files

`MODIFIED_FILES=src/ffmpeg/streaming.py; src/gui/qt/_mixins/render_mixin.py; tests/test_fit_gpx_file_validation.py; tests/test_video_helpers.py; ntfy_result.txt`

`CREATED_FILES=Raporty/RAPORT_P0_AMD_RENDERER_RECOVERY.md`

`REMOVED_CREATED_TEST=tests/test_mp4_orientation_metadata_only.py`

## NTFY

`NTFY_SUCCESS=True`

Three HTTP 200 warning notifications were sent:

```text
AMD renderer recovery blocked: native process terminated before first source frame after D3D11VA/AMF init.
```

## Timing

```text
TOTAL_STAGE_WALL_TIME=approximately 35 minutes
AUDIT_TIME=approximately 10 minutes
REPRO_TIME=approximately 8 minutes
IMPLEMENTATION_TIME=approximately 5 minutes
VALIDATION_TIME=approximately 12 minutes
LONGEST_SINGLE_COMMAND_SECONDS=approximately 31 seconds (native DLL rebuild)
```

## Final

`CASE=BLOCKED`

The targeted orientation experiments that forced the AMD CPU fallback were
removed safely. Native dispatch is again selected for rotated GoPro input, but
the native runtime cannot complete even 30 frames on the current machine, so
performance is not recovered and no 300F run was authorized.
