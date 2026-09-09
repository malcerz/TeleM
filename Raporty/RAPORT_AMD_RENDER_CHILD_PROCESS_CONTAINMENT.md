# AMD — render child-process containment and native RAII cleanup

## Task

Move the production AMD native export out of the long-lived Qt process and
harden partial native initialization cleanup, without changing NVIDIA/Intel
paths or HUD composition semantics.

## Initial state

The AMD D3D11/MF/AMF exporter ran in the GUI process. Previous measurements
showed process-private growth across sequential exports (approximately
663.8 → 1847.6 → 2610.4 → 3342.9 MiB) despite Python allocations staying near
170 MiB. The post-render audit also recorded D3D/DWM memory-exhaustion events.

## Implementation

- Added `src/ffmpeg/amd_child_process.py`.
  - Every real-file AMD export uses Windows multiprocessing `spawn`.
  - The child receives only the serializable render job and owns the native
    exporter, MF, D3D11 and AMF lifetime.
  - IPC has a single writer, bounded control queue, latest-only preview slot,
    reliable terminal/error messages, progress and warning forwarding, and a
    per-generation diagnostics log.
  - Cancellation is an explicit IPC message. The child gets 15 seconds for
    graceful shutdown; the fallback kills the child process tree only.
  - The parent exposes a Popen-compatible handle to existing GUI cancellation
    and finalization code; the GUI process is never killed.
- AMD preview remains a 1–2 FPS, downscaled GPU tap. The parent receives only
  bounded BGRA frames through `accept_external_frame`; Preview OFF creates no
  child-side tap.
- Added idempotent `ReleaseResources()` / `Shutdown()` boundaries for the VP
  pipeline and AMF encoder. `telem_amd_create` now checks `MFStartup` and all
  partial-failure exits pair cleanup with `MFShutdown`.

## Changed files

- `src/ffmpeg/amd_child_process.py`
- `src/ffmpeg/amd_hevc_preview.py`
- `src/gui/qt/_mixins/render_mixin.py`
- `src/gui/qt/tabs/render_tab.py`
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h/.cpp`
- `native/d3d11_amf_pipeline/src/d3d11_amf_encoder.h/.cpp`
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
- `tests/test_amd_child_process.py`

## Tests and verification

PASS — Python compilation/import check for all changed Python modules.

PASS — targeted tests:

```
python -m pytest -q tests/test_amd_child_process.py \
  tests/test_amd_gpu_frame_tap_preview.py \
  tests/test_amd_decode_gui_switch.py
11 passed
```

The same target set plus `tests/test_render_tab.py` was rerun after the final
diagnostic-surface change: **31 passed**.

PASS — native production target:

```
C:\tools\mingw64\bin\mingw32-make.exe -C \
  native/d3d11_amf_pipeline/build-integration-mingw telem_amd_native -j4
Built target telem_amd_native
```

The all-target make also attempted `d3d11_etap2c_poc` and failed in its
pre-existing demo source because `CreateHUDTexture` is not a member of the
current pipeline. The production DLL target itself completed successfully.

PASS — exported DLL contains `telem_amd_set_preview_tap` and
`telem_amd_poll_preview_tap`.

NOT TESTED — five sequential 4K GUI renders with parent RSS/private/handle
plateau, because this environment does not provide a safe repeatable Qt + AMD
hardware session.

NOT TESTED — 10,000-frame full-HUD child render, controlled native failure,
live cancel timing, ffprobe output parity, and Explorer/DWM/GPU-driver event
reproduction. These require the user's Windows GUI/GPU workload and must be
run before declaring production READY.

Post-test read-only event check (last two hours): no Application Error/WER
event naming `explorer.exe`, `dwmcore.dll`, `dwmredir.dll`, Python/D3D11/AMF,
and no Display/dxgkrnl driver-reset event was observed. This is a clean
snapshot, not proof that a long AMD render cannot trigger the historical
failure mode.

The unfiltered repository test run was intentionally stopped after unrelated
GUI/mpv tests produced repeated Windows fatal exception `0xe24c4a02` and
background worker/event-handler threads; it is not evidence against the
targeted child-process tests.

## Backend isolation

The containment branch is selected only for encoder `amd`/`amd_native` and
real input files. NVIDIA and Intel dispatch code is unchanged. The legacy
direct seam remains available for synthetic/non-file test inputs and for an
explicit `AMD_RENDER_CHILD_PROCESS=0` diagnostic override.

## Benchmark

NOT TESTED — no comparable 4K AMD benchmark was run in this environment. The
containment change is expected to add only process startup/IPC overhead; it
does not alter the native frame compositor or encoder settings. Measure using
the authoritative VIDEO/FIT pairing from `BENCHMARKS.md` after GUI validation.

## Risks / follow-up acceptance

- Spawn requires every render-job value to remain picklable; production
  `VideoClip`/`VideoTimeline` data is pure Python data. A real GUI run should
  verify the complete project/preset serialization path.
- The native DLL build is verified, but driver-side cleanup and desktop
  stability still need the requested five-run and failure/cancel matrix.
- No pagefile, registry, driver, or unrelated optimization changes were made.

## Final status

IMPLEMENTED — containment, bounded IPC, child cancellation/error reporting,
GPU preview relay, and partial-init RAII are in place and targeted-tested.

NOT READY TO CLAIM FULL ACCEPTANCE — the hardware/GUI acceptance matrix listed
above remains untested in this environment.
