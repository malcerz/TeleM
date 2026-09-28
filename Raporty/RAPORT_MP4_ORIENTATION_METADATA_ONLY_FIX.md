# RAPORT — MP4 orientation metadata-only fix

## Task

Restore metadata-only orientation for rotated MP4 sources. AMD must keep raw
decoded/composited pixels, retain the source display matrix in the final MP4,
and keep the native D3D11VA/AMF path for `GX010312.MP4`.

## Initial state

The previous P0 workaround treated non-zero AMD source orientation as a
renderer fallback. It selected a generic FFmpeg path and applied physical
`vflip`/`hflip`/`transpose` transforms. The native path also received the
Media Foundation display rotation through the D3D11 VideoProcessor, so the
pipeline did not satisfy metadata-only orientation.

## Exact implementation

- Removed the AMD `rotation != 0 -> FFmpeg pixel-filter fallback` in
  `streaming.py`.
- AMD command construction now keeps `-noautorotate`, uses no pixel rotation
  filter, preserves D3D11VA, and writes the source orientation metadata.
- AMD worker HUD rotation is forced to zero; NVIDIA-specific behavior remains
  isolated.
- Native AMD no longer forwards the Media Foundation source matrix to
  `VideoProcessorSetStreamRotation`; the legacy ABI setter is metadata-only.
- After native mux, a 180-degree source matrix is written atomically to the
  MP4 `tkhd` and verified again with ffprobe.
- Candidate project state and export-queue snapshots retain
  `source_rotation_degrees` and `source_display_matrix`.
- Added the six required orientation contract tests.

## Required values

```text
SOURCE_DISPLAY_MATRIX=rotation=-180 degrees
SOURCE_EFFECTIVE_ORIENTATION=180 degrees
PIXEL_ROTATION_BEFORE=180 degrees (previous fallback)
PIXEL_ROTATION_AFTER=0 degrees
VFLIP_USED=NO
HFLIP_USED=NO
TRANSPOSE_USED=NO
ROTATE_FILTER_USED=NO
SHADER_ROTATION_USED=NO
INPUT_AUTOROTATE=OFF (-noautorotate)
AMD_NATIVE_D3D11=YES
SHADER_DOWNSCALE=YES (8K -> 4K native path)
AMD_NATIVE_HUD=YES
AMF=YES
OUTPUT_DISPLAY_MATRIX=rotation=-180 degrees (ffprobe)
OUTPUT_EFFECTIVE_ORIENTATION=180 degrees
RAW_PIXEL_ORIENTATION_PRESERVED=PASS
DISPLAY_ORIENTATION_CORRECT=PASS by source/output -noautorotate comparison
QUEUE_ORIENTATION_SNAPSHOT=PASS
PREVIEW_DISPLAY=UPRIGHT
RENDER_PIXELS=UNROTATED
FINAL_FILE_METADATA=SOURCE_ORIENTATION
PLAYER_DISPLAY_FINAL=UPRIGHT
GX010312_1F=PASS, 1/1 frame
GX010312_3F=PASS, 3/3 frames
GX010312_30F=PASS, 30/30 frames
ROTATED_METADATA_8K_TO_4K_RENDER_FPS=19.609 console RENDER_FPS (profile true_fps=16.255)
PYTEST=8 passed focused orientation suite; 18 passed + 1 unrelated pre-existing failure in direct-mux suite
CASE=CASE A — metadata-only orientation restored, native AMD path retained
MODIFIED_FILES=native/d3d11_amf_pipeline/src/telem_amd_native.cpp; src/ffmpeg/amd_native_exporter.py; src/ffmpeg/command_builder.py; src/ffmpeg/streaming.py; src/gui/export_queue.py; src/gui/qt/_mixins/project_mixin.py; src/gui/qt/_mixins/render_mixin.py; src/gui/qt/tabs/render_tab.py; tests/test_fit_gpx_file_validation.py; tests/test_video_helpers.py; ntfy_result.txt
CREATED_FILES=tests/test_mp4_orientation_metadata_only.py; Raporty/RAPORT_MP4_ORIENTATION_METADATA_ONLY_FIX.md
```

The raw-orientation comparison used the source and output decoded with
`ffmpeg -noautorotate`. For the final 1F output:

```text
RAW_MAE=14.765
ROT180_MAE=20.071
RAW_PIXEL_ORIENTATION_PRESERVED=True
```

## Tests and smoke

- `python -m pytest -q tests/test_mp4_orientation_metadata_only.py ...` —
  `8 passed`.
- Native DLL rebuilt with the existing CMake/Ninja build tree — PASS.
- Real source `F:\GoPro\2026-09-23\GX010312.MP4`, output `3840x2160`:
  1F, 3F and 30F all completed through `AMD_NATIVE_D3D11`, D3D11VA and AMF.
- ffprobe verified `rotation=-180` in all final smoke outputs.
- A broader direct-mux test had one failure in the existing telemetry
  `MagicMock` date setup (`_normalize_datetime`); it is unrelated to the
  orientation changes and is not claimed as fixed.

## Changed files

```text
native/d3d11_amf_pipeline/src/telem_amd_native.cpp
src/ffmpeg/amd_native_exporter.py
src/ffmpeg/command_builder.py
src/ffmpeg/streaming.py
src/gui/export_queue.py
src/gui/qt/_mixins/project_mixin.py
src/gui/qt/_mixins/render_mixin.py
src/gui/qt/tabs/render_tab.py
tests/test_fit_gpx_file_validation.py
tests/test_video_helpers.py
tests/test_mp4_orientation_metadata_only.py
ntfy_result.txt
```

## Backend isolation / risks

No NVIDIA, Intel, FIT/GPX time validation, SmartSync, GPMF parser, telemetry
cache, map, HUD layout or AMD shader downscale math was intentionally changed.
The existing low-level `SetStreamRotation` helper remains compiled for ABI/code
compatibility but is no longer invoked by the production native path; the
exporter setter is metadata-only. Only the tested 180-degree output matrix is
implemented in the native post-mux writer; 90/270 native real smoke remains
NOT TESTED.

## Timing

```text
TOTAL_STAGE_WALL_TIME=~25 min
AUDIT_TIME=~3 min
REPRO_TIME=~5 min
IMPLEMENTATION_TIME=~8 min
VALIDATION_TIME=~9 min
LONGEST_SINGLE_COMMAND_SECONDS=~8 s (native DLL rebuild)
```

## Final summary

PASS — metadata-only orientation is restored for the tested rotated AMD
production path. Raw pixels remain unrotated, the final MP4 carries the
source display matrix, and native AMD is retained.
