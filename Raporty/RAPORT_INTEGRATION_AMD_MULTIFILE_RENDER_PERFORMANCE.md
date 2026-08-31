# TeleM — AMD multi-file render path audit

## Task

Determine why AMD multi-file rendering is slower than single-file rendering,
prove the selected paths, and avoid changing visual output or unrelated
backends.

## Initial state

The canonical inputs are `C:\_DEV\TeleM\Video\GX010115.MP4` plus
`GX010114_116.fit` for single-file, and the ordered 014/015/016 files plus the
same FIT for multi-file. The old repository was used read-only.

## Findings

`stream_overlay_to_ffmpeg()` computes `is_multi_file` from `VideoTimeline`.
For AMD, multi-file unconditionally sets `amd_native_multi_guard=True`.
Consequently it skips `export_amd_native_d3d11()` and continues into the
standard FFmpeg concat renderer. The native exporter currently does:

```python
input_file = input_files[0]
```

and the native DLL creates one Media Foundation source reader. Removing the
guard would therefore silently render only the first clip; it would not make
multi-file native. This is the confirmed root cause of the path regression.

## Runtime audit

Added concise diagnostics in `streaming.py`:

```text
RENDER PATH: mode=multifile exporter=standard_amd_amf decode=ffmpeg_concat
video_frame_path=CPU hud=cpu_compositor map=cpu_or_standard_amd encode=AMF
fallback_reason=amd_native_exporter_accepts_only_input_files[0]
```

The corresponding single-file audit identifies `amd_native_exporter`, native
decode mode, GPU frame residency, AMD native HUD/map, and AMF encoding.
Existing native logs independently confirm D3D11VA decode, native D3D11
compositor, and AMF encode for the single-file path.

## Timing comparison

**NOT TESTED / NOT PROVEN:** a new apples-to-apples hardware benchmark was not
run in this audit. Existing instrumentation provides native timings such as
`producer_prepare`, `above_compose`, native submit, and encode, but the
multi-file fallback path must first be benchmarked with a runnable production
invocation rather than compared to unrelated historical profiles.

The observed ~9.8 FPS multi-file result is consistent with the confirmed CPU
concat/compositor path, but no new numeric attribution is claimed here.

## Implementation

Only explicit path-audit logging was added. The unsupported native multi-file
route remains guarded to prevent partial 014-only output. No visual layout,
telemetry timing, map geometry, encoder implementation, or other backend was
changed.

## Tests

- Existing targeted multi-file/lifecycle/GPMF suite: `53 passed, 1 skipped`.
- `git diff --check`: passed.
- Real 014/015/016 timestamp and GUI lifecycle validation: recorded in
  `RAPORT_INTEGRATION_MULTIFILE_HUD_DUPLICATION_FIX.md`.
- New native multi-file performance benchmark: **NOT TESTED**.
- Real 015→016 AMD native export: **BLOCKED** by the current one-source native
  DLL contract; standard fallback export was not used as proof of native parity.

## Backend isolation and risks

The patch affects only AMD route diagnostics and leaves the guard intact.
NVIDIA, Intel, CPU/reference, HUD geometry, and final-render semantics are
unchanged. The architectural fix requires extending the existing native
decoder/exporter with clip-source switching or a native virtual input source;
that is a separate implementation stage and was not fabricated here.

## Final verdict

**PARTIAL** — root cause and actual routing are proven; multi-file does not use
the AMD native path. The requested performance repair and post-repair benchmark
remain outstanding because the current native ABI cannot consume multiple
source files safely.

No commit or push was performed.

## AMD NATIVE MULTI-FILE IMPLEMENTATION

### ABI and clip switching

The old ABI exposed one `telem_amd_create(input_path, ...)` source reader and
had no source-switch operation. The new ABI adds:

```text
telem_amd_switch_source(handle, wchar_t* input_path) -> int
```

Python keeps `VideoTimeline` as the time authority and passes the active clip
path at each global timeline boundary. This is a deliberately minimal
descriptor contract: the native side receives only the source path; global and
local time mapping remains in Python. One active MF reader exists at a time.
On switch, only the old reader and pending sample are released, then the new
reader is attached to the existing DXGI device manager. D3D11 device, VP
compositor, HUD/map resources, AMF encoder, frame numbering, and output session
remain alive.

### Format and fallback policy

The new reader negotiates P010 first and NV12 second, refreshes its media type,
and rejects a switch if width, height, or DXGI format differs from the active
source. Failure returns a controlled native-export failure; `streaming.py` can
then use the existing standard fallback. A DLL without the new symbol is also
reported as a controlled multi-file capability failure.

### Audio

Native export still encodes video only. Multi-file mux now feeds FFmpeg a concat
list containing the same ordered timeline clips and limits audio to the native
video duration. It does not mux audio from clip 014 alone or extend the output
to the full source duration.

### Real smoke results

Using read-only files from `C:\_DEV\TeleM\Video`, a shortened 15-second
three-source timeline (5 seconds per source) produced 450 video frames and
exercised both switches 014→015 and 015→016. Logs showed:

```text
RENDER PATH: mode=multifile exporter=amd_native_exporter
decode=D3D11VA video_frame_path=GPU hud=amd_native map=amd_native encode=AMF
fallback_reason=none
```

The native profile reported `decoder_output_format=DXGI_FORMAT_P010`,
`hardware_acceleration_confirmed=true`, 450 D3D11 surfaces, 450 direct decoder
surface frames, and zero decoder GPU-copy frames. Both source switches completed
successfully. Output validation: HEVC video 15.015 s / 450 frames and AAC
audio 15.019 s / 704 frames; no crash and no CPU video fallback.

Single-file smoke (015, 150 frames / 5 seconds) used the same native path:
25.480 render FPS, 21.615 effective FPS, 23.337 true FPS. Multi-file smoke:
26.833 render FPS, 25.140 effective FPS, 25.929 true FPS. These are short
smokes, not the canonical long benchmark; CPU/GPU utilization was not captured
by application instrumentation.

| component | SINGLE native ms/frame | MULTI native ms/frame | delta |
|---|---:|---:|---:|
| producer_prepare | 15.802 | 15.526 | -0.276 |
| above_compose | 13.086 | 13.385 | +0.299 |
| VideoProcessor CPU submit | 0.515 | 0.520 | +0.005 |
| consumer_native_call | 20.738 | 18.181 | -2.557 |
| pipeline_total | 24.313 | 21.939 | -2.374 |
| AMF submit/backpressure | 0.223 | 0.219 | -0.004 |
| MF ReadSample/decode availability | 1.669 | 1.789 | +0.120 |

The profiles were collected in separate short runs and are directional rather
than a governed apples-to-apples benchmark. The key acceptance result is that
multi-file no longer selects the old CPU concat path and remains GPU-resident
inside clips.

### Parity and remaining validation

Audio/video duration and frame count passed for the three-source smoke. A full
pre-encode pixel parity comparison across all HUD layers and long canonical
014/015/016 benchmark remains **NOT PROVEN**. The shortened smoke uses explicit
five-second descriptors to exercise source switching and is not a replacement
for the full project-duration export. CPU/GPU Task Manager utilization is also
**NOT TESTED**.

### Build

- compiler: MinGW GCC/G++ 16.2.0
- configuration: CMake Release, MinGW Makefiles
- DLL: `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`
- size: 3,061,024 bytes
- SHA256: `B19C39A4296FB185EBD0A1EBB650358E49049A8E7C374ED652C00FFA02937175`
- build ID: `telem-amd-native/1.0.0+feb04820bbcd.src3b2ee95b961e`

### Changed files and verdict

- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
- `src/ffmpeg/amd_native_exporter.py`
- `src/ffmpeg/streaming.py`
- `scratch/run_amd_multifile_native_smoke.py`
- this report

The implementation diff stat for the three tracked implementation files is
`3 files changed, 263 insertions(+), 95 deletions(-)`; the worktree already
contained unrelated modifications, so this stat is not a clean-tree total.

Targeted tests after implementation: `20 passed, 2 skipped`; C++ Release DLL
build: PASS; real three-source native smoke: PASS; audio duration alignment:
PASS; full visual parity and governed benchmark: **NOT PROVEN**.

Final verdict: **PARTIAL**. The requested native multi-file source switching
path is implemented and exercised on real 014/015/016 inputs, but full visual
parity and a canonical utilization benchmark remain outstanding.
