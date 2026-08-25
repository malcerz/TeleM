# TeleM — INTEL ETAP 3A: GPU-resident vertical slice

Data: 2026-08-24

## Environment

```text
ACTIVE_FFMPEG_PATH: F:\\_DEV\\TeleM\\ffmpeg.exe
ACTIVE_FFMPEG_VERSION: 2026-08-17-git-426841da9d-full_build-www.gyan.dev
```

## Hardware

DXGI enumeration from the current TeleM Intel backend:

| index | adapter | vendor_id | device_id | d3d11 |
|---:|---|---:|---:|---|
| 0 | NVIDIA Quadro P400 | `0x10DE` | `0x1CB3` | OK |
| 1 | Intel(R) UHD Graphics 730 | `0x8086` | `0x4692` | OK |
| 2 | Microsoft Basic Render Driver | `0x1414` | `0x008C` | OK |

## Baseline runtime render

Material available in the repository:

```text
Video/GX020079.MP4
```

The source is 3840x2160 HEVC Main 10, `yuv420p10le`, BT.2020/HLG. It is not a safe first SDR native-slice input.

A 5-second Intel CPU-composite baseline was started at 1280x720 with the existing QSV decode + CPU `scale/overlay` graph. The render did not complete in the allowed observation window and left no active FFmpeg process; it was stopped safely. A 1-second retry showed the same pipe/writer stall. Therefore no valid baseline FPS or output is claimed.

## Baseline performance

```text
INTEL_CPU_COMPOSITE_BASELINE: NOT MEASURED
reason: existing CPU filter/pipe run stalled on the 10-bit source before a valid completed export
```

The logs are in `scratch/intel_etap3a/baseline.log` and `baseline_1s.log`.

## Root cause

The previous Intel command decoded to QSV hardware frames, then passed the video through a CPU filter graph:

```text
QSV decode surface
 -> CPU scale
 -> CPU overlay with raw RGBA HUD pipe
 -> conversion/upload required for QSV encode
```

The first full-frame GPU-to-CPU boundary is the handoff from the QSV video frame to the CPU-only `scale`/`overlay` graph. The graph did not contain an explicit `hwdownload`, but the incompatible QSV-to-CPU transition necessarily requires the equivalent download/conversion in FFmpeg.

## Frame lifecycle BEFORE

```text
input file: HEVC 10-bit or SDR video
decode: QSV/D3D11, AV_PIX_FMT_QSV surface
filter graph: CPU scale + CPU overlay
HUD: CPU RGBA rawvideo pipe
video: QSV surface -> CPU frame/conversion (implicit full-frame boundary)
composite: CPU
encode: hevc_qsv, NV12-compatible output
```

## Selected design

The smallest safe vertical slice uses FFmpeg QSV filters already present in the active build:

```text
QSV decode
 -> optional scale_qsv
 -> overlay_qsv
 -> QSV encode
```

The existing CPU-generated HUD remains the source. It is converted to BGRA and uploaded with `hwupload=derive_device=qsv`. No indicator renderer, telemetry resolver, map, timeline, AMD path or NVIDIA path was redesigned.

Native path eligibility is deliberately limited to:

- Intel encoder;
- one input file;
- rotation 0 and no container rotation;
- no cut regions;
- 720p, 1080p or source resolution;
- single-file 8-bit SDR input;
- normal HUD enabled.

Other configurations use the existing Intel CPU_REFERENCE path. HDR/10-bit is explicitly rejected for this slice.

## Changed files

- `src/ffmpeg/command_builder.py` — Intel-specific `scale_qsv`/`overlay_qsv` graph and no CUDA path.
- `src/ffmpeg/streaming.py` — native-path eligibility, SDR probe, diagnostics and `-filter_hw_device` wiring.
- `tests/test_video_helpers.py` — native graph and NVIDIA-leakage assertions.
- `Raporty/RAPORT_INTEL_ETAP_3A_GPU_RESIDENT.md` — this report.

Earlier ETAP 2 Intel device-pinning changes remain in `intel_backend.py` and related tests. AMD/NVIDIA code was not modified for this stage.

## Intel GPU-resident implementation

Representative generated filter graph:

```text
[0:v]scale_qsv=1280:720[base];
[1:v]setpts=PTS-STARTPTS,format=bgra,scale=1280:720,hwupload=derive_device=qsv[ov];
[base][ov]overlay_qsv=x=0:y=0:shortest=1[vtemp]
```

Device arguments remain dynamically generated from Intel Vendor ID `0x8086`:

```text
-init_hw_device qsv=intel_qsv,child_device=1,child_device_type=d3d11va
-hwaccel qsv -hwaccel_device intel_qsv -hwaccel_output_format qsv
-qsv_device 1
-filter_hw_device intel_qsv
```

The numeric `1` above is the observed runtime result, not a hardcoded source constant.

## Overlay path

HUD generation remains on CPU. The HUD is supplied as the existing RGBA rawvideo stream, converted to BGRA, and uploaded to the Intel QSV device. This is an upload of the overlay layer; it is not a video-frame readback.

Current slice uploads the configured HUD canvas. Further HUD-region reduction is deferred because it would require additional geometry/transport changes.

## Frame lifecycle AFTER

For the native SDR slice:

```text
input file: SDR 8-bit video
decode: QSV/D3D11, Intel surface
scale: scale_qsv, Intel video memory
HUD: CPU RGBA -> BGRA -> hwupload derive_device=qsv
composite: overlay_qsv, QSV VPP video-memory input/output
encode: hevc_qsv, Intel QSV
```

The runtime log contained:

```text
VPP: input is video memory surface
VPP: output is video memory surface
```

## Full video frame readback

```text
FULL_VIDEO_FRAME_GPU_TO_CPU_READBACK: NO
```

This is proven for the tested native SDR vertical slice by the `overlay_qsv` VPP log and the absence of CPU `overlay`/`hwdownload` in the generated graph. It is not claimed for the fallback path.

## NVIDIA isolation

```text
NVIDIA_USED_BY_INTEL_PIPELINE: NO
```

The native command contains no `cuda`, `nvdec`, `nvenc`, `overlay_cuda`, `scale_cuda` or `hwupload_cuda`. Adapter diagnostics show Quadro ignored under `INTEL_FORCE`.

## Visual parity

A representative native output frame was extracted to `scratch/intel_etap3a/native_frame.png` and inspected. The video and HUD render correctly at the smoke-test level.

Formal A/B pixel parity against a completed CPU baseline: `NOT VERIFIED`, because the CPU baseline stalled before producing a valid matching export.

## Runtime final render

Native Intel vertical slice: `PASS`.

Test input: a 2-second, 1280x720, 8-bit BT.709 SDR derivative of `GX020079.MP4`, created only as a controlled SDR runtime probe. Output:

```text
scratch/intel_etap3a/INTEL_GPU_RESIDENT_SDR.mp4
frames: 60
FFmpeg exit code: 0
output size: 9,646,870 bytes
encoder: hevc_qsv
device: Intel 8086:4692
```

The original HDR/10-bit source correctly selected `CPU_REFERENCE` fallback and was not falsely labeled native SDR.

## Tests

```text
python -m pytest tests/test_intel_backend.py tests/test_video_helpers.py tests/test_gpu_compositor.py tests/test_amd_native_overlay_handoff.py -q
51 passed
```

Also executed:

- current FFmpeg `overlay_qsv` PoC with QSV input/output;
- actual H.264/HEVC QSV probes;
- actual Intel native TeleM streaming export;
- Python bytecode compilation of changed modules.

## Performance

| metric | before | after | delta | speedup |
|---|---:|---:|---:|---:|
| completed comparable export | NOT MEASURED | 2 s / 60 frames | N/A | N/A |
| effective FPS | NOT MEASURED | NOT MEASURED | N/A | N/A |
| full-frame readback | YES/implicit in old graph | NO in native slice | eliminated in slice | N/A |
| FFmpeg write benchmark | stalled baseline | avg 29.97 ms, p95 51.35 ms | not comparable | N/A |

No performance improvement claim is made because the baseline did not complete.

## Fallbacks

Native path falls back to `CPU_REFERENCE` for:

- HDR, BT.2020/HLG/PQ or non-8-bit input;
- multiple input files;
- non-zero rotation;
- cut regions;
- unsupported resolution/configuration;
- disabled/no HUD native case.

Fallback never selects AMD or NVIDIA.

## Preserved

```text
AMD path preserved.
NVIDIA path preserved.
CPU path preserved.
Telemetry semantics preserved.
Multi-file semantics preserved.
```

AMD/NVIDIA runtime was intentionally not tested.

## Remaining bottleneck

The native slice still generates and uploads a full HUD canvas on the CPU. The CPU baseline is also affected by the existing streaming/writer behavior on the tested HDR source. Formal performance comparison and full CPU/GPU A/B parity remain outstanding.

## Recommendation — INTEL ETAP 3B

First add a reliable completed CPU-reference A/B harness for the same SDR input and matching HUD, then reduce HUD upload to bounded regions while preserving z-order. After parity is proven, extend native eligibility cautiously to safe rotations and supported color formats. Do not alter AMD/NVIDIA or HDR color semantics without separate runtime evidence.
