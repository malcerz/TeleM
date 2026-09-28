# P0 — stale video time and preview/export rotation contract

## Result

`STATUS=PASS_WITH_DOCUMENTED_NONBLOCKING_TEST_GAP`

`STALE_VIDEO_TIME_REPRODUCED=YES` before the patch: validation read the already committed `self.video_timeline` and could validate a newly selected FIT/GPX against the previous MP4.

`VALIDATION_VIDEO_TIME_SOURCE_BEFORE=self.video_timeline.clips (previous committed project)`

`VALIDATION_VIDEO_TIME_SOURCE_AFTER=candidate video_paths -> probe_clip_time_interval -> resolve_clip_timestamp/GPMF candidate cache`

`CANDIDATE_VIDEO_TIME_USED=True`

`PREVIOUS_VIDEO_TIME_USED=False`

`ROTATION_BUG_REPRODUCED=YES` before the patch: native AMD 1F output for `GX010312` was upside-down although preview/FFmpeg autorotation was upright.

## Real candidate data

`REAL_GX010312_VIDEO_START=2026-09-23 04:26:17.100 UTC`

`REAL_GX010312_VIDEO_END=2026-09-23 04:56:12.193 UTC`

`REAL_FIT_START=2026-09-23 04:25:22 UTC`

`REAL_FIT_END=2026-09-23 04:55:18 UTC`

`REAL_VALIDATION_RESULT=VALID/TIME_OVERLAP`

## Rotation trace

`SOURCE_ROTATION_METADATA=ffprobe side_data rotation=-180; normalized effective rotation=180 degrees`

`SOURCE_DISPLAY_MATRIX=rotation=-180 degrees`

`PREVIEW_ROTATION_APPLIED=one FFmpeg/QMediaPlayer autorotation transform`

`EXPORT_ROTATION_APPLIED=exactly once: -noautorotate plus vflip+hflip; no output rotate metadata`

`EXPORT_ROTATION_APPLIED_AFTER=one -noautorotate + vflip+hflip transform in the guarded FFmpeg AMD contract; output metadata rotate=0`

`ROTATION_STATE_REGRESSION_FROM_VALIDATION_PATCH=NO`

`FIRST_ROTATION_BEHAVIOR_DIFFERENCE=AMD_NATIVE_D3D11 native 1F: source_rotation=180 was logged, but the 7680x4320 -> 3840x2160 shader-downscale branch bypassed effective VP rotation and emitted raw upside-down pixels.`

`ROOT_CAUSE_VALIDATION=pre-commit validation resolved time from the old committed timeline before candidate MP4 probing.`

`ROOT_CAUSE_ROTATION=the native source-rotation setter does not affect pixels when the existing 8K->4K shader-downscale branch is selected; changing that renderer/downscale was explicitly out of scope.`

## Fix

`FIX_VALIDATION=probe every explicitly supplied candidate video before FIT/GPX validation; parse candidate telemetry into temporary variables; commit video, rotation metadata, paths, and parsed telemetry only after acceptance.`

`FIX_ROTATION=probe effective container rotation before AMD native dispatch; non-zero rotation uses the existing FFmpeg single-transform contract. The AMD rotated path now sets both rotation arguments, disables hardware decode for CPU filters, and emits NV12 before AMF. Unrotated AMD clips retain native D3D11 dispatch.`

`PREVIEW_ORIENTATION_AFTER=PASS; same source preview is upright.`

`EXPORT_1F_ORIENTATION_AFTER=PASS; MAE to upright autorotated 4K reference=4.959, MAE to 180-degree reference=17.841.`

`EXPORT_3F_ORIENTATION_AFTER=PASS; MAE to upright autorotated 4K reference=1.082, MAE to 180-degree reference=14.330.`

`NORMAL_HORIZONTAL_CLIP_AFTER=NOT TESTED with a real zero-matrix production clip; all available GoPro source clips inspected in this workspace carry -180 display metadata. A synthetic zero-matrix 10-bit input smoke was attempted but failed before frame output in the existing native input pipeline, so it is not used as acceptance evidence.`

## Tests and files

`PYTEST=21 passed (tests/test_fit_gpx_file_validation.py); 47 passed including tests/test_activity_ux_timeline.py. The pre-existing tests/test_render_no_legacy_json.py remains 1 failed because the legacy-sidecar compatibility assertion still receives rotation=0; this is unrelated to candidate-time validation and is NOT claimed as fixed.`

`SMOKE=real GX010312 AMD request: 1F PASS, 3F PASS; rotated path log=ffmpeg_rotation_contract; native pre-fix 1F reproduced upside-down output.`

`MODIFIED_FILES=src/gui/qt/_mixins/project_mixin.py; src/gui/qt/_mixins/render_mixin.py; src/ffmpeg/streaming.py; src/ffmpeg/command_builder.py; tests/test_fit_gpx_file_validation.py; ntfy_result.txt`

`CREATED_FILES=Raporty/RAPORT_P0_VALIDATION_STALE_TIME_AND_ROTATION_FIX.md`

`TOTAL_STAGE_WALL_TIME=approximately 35 minutes (manual audit + short repro + implementation + validation)`

`LONGEST_SINGLE_COMMAND_SECONDS=10.2 (three-frame extraction command); longest export command=3.0 seconds`

`CASE=stale candidate-time validation plus rotated GoPro source; rotation fixed with scoped non-native fallback, no shader/downscale or native HUD changes`

## Risks / isolation

- Rotated GoPro exports use the existing CPU-filter/AMF path and therefore do not receive the native AMD HUD compositor performance profile.
- No native C++ renderer, GPMF parser, central cache, map, NVIDIA, Intel, queue, or AMF capability code was changed for this P0.
- The known legacy JSON compatibility failure remains documented and is outside this task.

`FINAL=PASS for P0 stale-time acceptance and real 1F/3F export orientation; normal zero-matrix production clip remains NOT TESTED.`
