# Restore known-good MP4 orientation contract

## Result

`STATUS=WAITING_FOR_USER_MANUAL_CHECK`

`CASE=CASE B — root cause identified, waiting for user manual playback verification`

The previous metadata-only orientation change is not accepted: the user
reported that manual playback still failed. The implementation is restored to
the older physical-transform contract proven by the P0 evidence. A real 300f
4K export completed, but this environment cannot replace the user's final
player check.

## Required trace

`LAST_KNOWN_GOOD_COMMIT=0ef407e (orientation baseline in HEAD; FIT/GPX validation report and its follow-up changes were uncommitted working-tree changes)`

`FIRST_VALIDATION_CHANGE=working-tree changes associated with Raporty/RAPORT_FIT_GPX_FILE_VALIDATION.md; no Git commit exists for that report`

`KNOWN_GOOD_ORIENTATION_FLOW=source rotation -180 -> normalized 180 -> -noautorotate -> existing FFmpeg vflip+hflip -> 4K scale/overlay -> AMF; output rotation=0 and no Display Matrix`

`CURRENT_BAD_ORIENTATION_FLOW=metadata-only native path retained raw pixels and wrote a 180-degree output matrix; the user manual playback check reported wrong orientation`

`FIRST_BEHAVIOR_DIFFERENCE=the metadata-only change removed the established physical vflip+hflip contract, kept the rotated AMD native path, and added custom output tkhd metadata handling`

`SOURCE_ROTATION=ffprobe side_data rotation=-180; effective rotation=180 degrees`

`KNOWN_GOOD_OUTPUT_ROTATION=0; ffprobe reports no Display Matrix and no rotate tag`

`CURRENT_BAD_OUTPUT_ROTATION=-180; prior metadata-only smoke reported a 180-degree Display Matrix`

`SOURCE_TKHD_MATRIX=180-degree matrix: -65536,0,0 / 0,-65536,0 / translation 503316480,283115520 (ffprobe displaymatrix)`

`KNOWN_GOOD_TKHD_MATRIX=identity/no Display Matrix in the known-good output`

`CURRENT_BAD_TKHD_MATRIX=180-degree matrix: -65536,0,0 / 0,-65536,0 / translation 251658240,141557760 (prior 3840x2160 metadata-only output)`

`SOURCE_RAW_PIXEL_ORIENTATION=raw noautorotate frame is upside down relative to upright playback`

`KNOWN_GOOD_RAW_PIXEL_ORIENTATION=physically transformed upright pixels`

`CURRENT_BAD_RAW_PIXEL_ORIENTATION=raw source pixels preserved; metadata/player interpretation was not accepted after manual playback`

`ROOT_CAUSE=metadata-only orientation did not reproduce the established end-to-end player contract; the old working behavior applied the source rotation exactly once in pixels and emitted a neutral output orientation`

`RESTORED_CODE_PATH=AMD non-zero single-file rotation is guarded before native dispatch and uses the existing FFmpeg one-pass path; AMD native D3D11 remains selected for zero-rotation sources`

`FIT_VALIDATION_STILL_PASS=YES; GX010312.MP4 + Poranna_jazda_na_rowerze.fit => VALID/TIME_OVERLAP; 1797 FIT points; video 2026-09-23 04:26:17.100..04:56:12.193 UTC; FIT 04:25:22..04:55:18 UTC`

`AMD_NATIVE_D3D11=NO for rotated single-file export by the restored guard; YES remains retained for rotation=0`

`SHADER_DOWNSCALE=NOT USED in rotated fallback; existing native 8K->4K shader/downscale path was not changed for rotation=0`

`AMD_NATIVE_HUD=NO for rotated fallback; existing native HUD path retained for rotation=0`

`AMF=YES; real 300f export encoded with hevc_amf`

`SUSTAINED_RENDER_FPS=NOT directly reported by this smoke; ffmpeg_write average 61.00 ms/frame implies approximately 16.4 fps, not comparable to the native ~37 fps reference`

## Implementation

Restored the existing P0 behavior:

- AMD rotation probe prevents the rotated single-file source from entering
  the native D3D11 path.
- `-noautorotate` is retained and the existing `vflip,hflip` transform is
  applied once for 180 degrees.
- The output is explicitly neutral (`rotate=0`); no AMD post-mux tkhd writer
  is used.
- Native AMD source rotation setters remain available for the ABI and native
  zero-rotation path, but are not used to claim metadata-only orientation.
- Candidate/project orientation state uses the existing `rotation` field; no
  new source orientation state is retained.

The previous `RAPORT_MP4_ORIENTATION_METADATA_ONLY_FIX.md` remains in the
working tree as historical evidence, but its manual-playback PASS conclusion
is contradicted by the user's latest manual test and is not reused.

## Tests and evidence

`AUTOMATED_TESTS=54 passed, 2 failures in existing Intel rotation assertions; the failures are pre-existing backend-specific mismatches and were not changed during this AMD task`

`ORIENTATION_CONTRACT_TESTS=passed: physical vflip+hflip, -noautorotate, rotate=0, AMD native rotation guard, existing rotation state`

`FIT_GPX_UNIT_TESTS=passed within the targeted run`

`REAL_EXPORT=PASS; F:\\GoPro\\2026-09-23\\GX010312.MP4; 300 frames; 3840x2160; output C:\\Users\\Malcerz\\AppData\\Local\\Temp\\brh_known_good_orientation_300f.mp4; 49,404,410 bytes`

`REAL_EXPORT_PATH=ffmpeg_rotation_contract; decode=software; video_frame_path=CPU; hud=cpu; encode=AMF; fallback_reason=native_rotation_guard`

`FFPROBE_OUTPUT=3840x2160, 30000/1001, no side_data_list Display Matrix, no rotate tag`

`VISUAL_FRAME_SUPPORT=source autorotated vs restored export MAE=1.366 at 960x540; source raw vs restored export MAE=14.284; this is supporting evidence only, not a substitute for manual playback`

`USER_MANUAL_CHECK_REQUIRED=True`

`FINAL_VIDEO_MANUAL_ORIENTATION=NOT PROVEN; user must play the generated MP4 for 3–10 seconds and confirm upright output`

## Backend isolation / risks

- NVIDIA and Intel production code was not changed for this restore.
- FIT/GPX validation remains active and passed on the real requested pair.
- Rotated AMD exports intentionally lose the native D3D11 HUD/performance
  path and use the existing software-filter + AMF path.
- The two Intel test failures must not be interpreted as an AMD regression;
  they assert an unrelated Intel autorotation contract already present in the
  dirty tree.
- The final acceptance remains pending until the user confirms playback.

## Timing

`TOTAL_STAGE_WALL_TIME=approximately 20 minutes`

`AUDIT_TIME=approximately 5 minutes`

`REPRO_TIME=approximately 4 minutes`

`IMPLEMENTATION_TIME=approximately 5 minutes`

`VALIDATION_TIME=approximately 6 minutes`

`LONGEST_SINGLE_COMMAND_SECONDS=approximately 120 seconds (aborted 8K frame extraction helper); successful 300f export was approximately 17 seconds`

## NTFY

`NTFY=3 successful HTTP 200 attempts via curl.exe`

`NTFY_MESSAGE=Known-good orientation restore blocked: manual playback verification required.`

`NTFY_TITLE=TeleM GoPro — UWAGA`

`NTFY_TAG=warning`

`NTFY_RESULT=recorded in ntfy_result.txt`

## Files

`MODIFIED_FILES=native/d3d11_amf_pipeline/src/telem_amd_native.cpp; src/ffmpeg/amd_native_exporter.py; src/ffmpeg/command_builder.py; src/ffmpeg/streaming.py; src/gui/qt/_mixins/project_mixin.py; src/gui/qt/_mixins/render_mixin.py; tests/test_fit_gpx_file_validation.py; tests/test_video_helpers.py; tests/test_mp4_orientation_metadata_only.py; ntfy_result.txt`

`CREATED_FILES=Raporty/RAPORT_RESTORE_KNOWN_GOOD_ORIENTATION.md`

`FINAL=NOT PROVEN until user manual playback verification; code path and real 300f export restored successfully`
