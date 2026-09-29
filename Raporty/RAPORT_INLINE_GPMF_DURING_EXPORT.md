# Inline GPMF during export

## Task and initial state

The GUI checkbox default was OFF. With it ON, production finished video/audio MP4 first, then `attach_original_gpmf()` read the entire result into a second MP4 and replaced the output. The pre-existing working tree included an unrelated deleted CSV and untracked reports, scratch files and a DLL backup; none were staged or modified by this task.

CURRENT_HEAD=3eab028 (start of task)
AMD_DLL_SHA256=90BE5AF56BB56A73CDC161A0508B0D6A2C71987BE44A565712C37AA5B5D66647
AMD_DLL_UNCHANGED=YES (hash checked before and after real AMD exports)
OLD_GPMF_ARCHITECTURE=completed video/audio MP4 -> second full-file FFmpeg remux -> replace
NEW_GPMF_ARCHITECTURE=detect/prepare source gpmd before render -> map gpmd into the existing final video/audio mux -> finish `.part` MP4 and rename

## Implementation and backend isolation

Changed files: `src/ffmpeg/gpmf_export.py`, `src/ffmpeg/amd_native_exporter.py`, `src/ffmpeg/intel_native_exporter.py`, `src/ffmpeg/nvidia_native_exporter.py`, `src/ffmpeg/nvidia_child_process.py`, `src/ffmpeg/command_builder.py`, `src/ffmpeg/streaming.py`, `src/gui/qt/_mixins/render_mixin.py`, `tests/test_amd_direct_mp4_mux.py`, `tests/test_inline_gpmf_export.py`, `tests/test_inline_gpmf_amd_real.py`, and this report.

`prepare_inline_gpmf()` detects the actual `gpmd` index. A complete single source is passed directly to the final mux. A trim or multi-file timeline is assembled from data-only segment copies and a data-only concat before rendering; the rendered video is never used by those helpers. If one of several clips lacks `gpmd`, the plan disables GPMF and logs the incomplete-set message. The same plan and mux argument helper are used by AMD, Intel, NVIDIA and the generic FFmpeg path. The normal GUI worker no longer calls the post-render attachment method; its old helper remains for legacy callers/tests. OFF sends no plan and adds no mux options. No native code, ABI or DLL was changed.

AMD_VIDEO_MUX_PATH=native D3D11/AMF HEVC -> named pipe -> Python pump -> FFmpeg stdin -> `.part` MP4
AMD_AUDIO_MUX_PATH=existing AAC source/cache or concat input in the same FFmpeg process
GPMF_MUX_PATH=source or metadata-only timeline as another input to that same FFmpeg process, explicit stream index, `-c:d copy -tag:d:0 gpmd`
AMD_MUX_START_TIME=before native frame loop; FFmpeg receives encoded video during render
AMD_MUX_PROCESS=existing single-pass FFmpeg final mux
MUX_PROCESS_COUNT=1 for measured AMD final export
VIDEO_ENCODE_PASS_COUNT=1
FINAL_MP4_FULL_REMUX_COUNT=0
POST_RENDER_GPMF_CODEPATH_ACTIVE=NO for the GUI production path

## Verification

Short standalone source: 25 s stream-copy excerpt beginning 120 s into `C:\_DEV\BikeRideHUD-amd\Video\GX010298.MP4`; this diagnostic source was explicitly disclosed before use. Both AMD runs used the same 746-frame, 1080p, 25 Mb/s, 29.97 fps workload with a minimal static HUD. This is not the canonical benchmark and is not used to compare against prior canonical performance results. Watchdog observed process/child PIDs and growing `.part` files every approximately 5 s. Source/output GPMF both contain 25 payloads and 545,860 raw data bytes. Native parser reads 250 speed/GPS samples, 4,973 accelerometer and gyroscope samples, 750 ISO/exposure samples, and 25 temperature samples from both source and ON export. OFF has no `gpmd`; ON has video, AAC and `gpmd`. The final ON file was 125,498,385 bytes. There was one `.part` MP4 and no second full-size file.

INLINE_GPMF_SINGLE_FILE=YES, real AMD production run
TRIMMED_GPMF_INLINE_PASS=metadata-only preparation and timestamp rebasing tested with real FFmpeg; complete rendered trim NOT TESTED
MULTIFILE_GPMF_INLINE_PASS=metadata-only two-segment timeline tested with real FFmpeg; complete rendered multi-file export NOT TESTED
PARTIAL_MULTIFILE_GPMF_POLICY=SAFE: explicit log and disable if any selected source lacks gpmd (unit tested)
NO_GPMF_SOURCE_RENDER_PASS=planner skips GPMF, but complete render NOT TESTED
DIRECT_INLINE_GPMF=YES, real AMD
QUEUE_INLINE_GPMF=same GUI render entrypoint and options path, queue contract tested; real queued GPMF render NOT TESTED
SOURCE_GPMF_SHA256=5e79cd572572b096b59e1d356e6a1e5f2f941d9299dacaf754970b670cf08862
OUTPUT_GPMF_SHA256=5e79cd572572b096b59e1d356e6a1e5f2f941d9299dacaf754970b670cf08862
GPMF_PAYLOAD_HASH_MATCH=YES
AUDIO_PARITY_PASS=YES for codec AAC, 48 kHz, two channels, duration 24.896 s and 1,167 packets; fine A/V sync measurement NOT TESTED
QP_POPUP_PASS=unit test for numeric popup passed; manual GUI popup NOT TESTED because computer-control runtime could not initialize
AMD_INLINE_GPMF_PASS=YES for full single-file production path
INTEL_INLINE_GPMF_CODEPATH_PASS=code wired into existing mux and adjacent contract tests pass; hardware NOT TESTED
NVIDIA_INLINE_GPMF_CODEPATH_PASS=code wired into existing mux and adjacent contract tests pass; hardware NOT TESTED
EXPORTED_GPMF_PARSE_PASS=YES, native parser channels match source

GPMF_OFF_RENDER_FPS=79.228
GPMF_ON_RENDER_FPS=78.937
FPS_REGRESSION_PERCENT=0.368 (one short run; noisy)
GPMF_OFF_EFFECTIVE_FPS=74.011
GPMF_ON_EFFECTIVE_FPS=74.252
GPMF_OFF_FINALIZATION_S=0.108 (video-render-end to export-end, profile milestones)
GPMF_ON_FINALIZATION_S=0.106 (same definition)
FINAL_VIDEO_FRAME_TIME=9.940 s after export start (ON profile video-render-end)
MUX_CLOSE_TIME=10.015 s after export start (ON profile mux-end)
OUTPUT_READY_TIME=10.047 s after export start (ON profile export-end)
GPMF_POST_ATTACH_SECONDS=0
SECOND_FULL_SIZE_MP4_CREATED=NO in observed AMD A/B; metadata-only temp files are used only for cuts/multi
STOP_INLINE_GPMF_PASS=existing AMD cancel/partial cleanup tests pass; live GPMF ON stop NOT TESTED
ORPHAN_PROCESS_COUNT=0 after observed completed A/B; stopped-run orphan count NOT TESTED
REAL_AMD_INLINE_GPMF_PASS=YES

Tests: `tests/test_inline_gpmf_export.py` with a real source: 7 passed; `tests/test_inline_gpmf_amd_real.py` opt-in real AMD A/B with native parser: 1 passed; focused existing GPMF/AMD suite: 39 passed, 2 skipped before enabling real-source tests; queue/Intel/NVIDIA/lifecycle adjacent suite: 32 passed, 2 skipped. `git diff --check` passed. Intel/NVIDIA hardware, full trimmed/multi render, real queue and STOP, GPU utilization, disk-write counters and manual QP popup remain NOT TESTED. No benchmark comparison to the canonical 4K/1131-frame workload is claimed. No known regression was seen on the exercised paths.

NEW_REGRESSIONS=focused planner, metadata timeline, payload/audio, AMD OFF/ON mux lifecycle and opt-in real AMD parser harness
COMMIT=82251d5 (source and tests); this report is committed separately
PUSH_RESULT=source/tests pushed normally to origin/main; report push is the follow-up commit
FINAL_STATUS=INLINE_GPMF_EXPORT_PASS for the stated real AMD direct-export/no-second-remux gate; remaining end-to-end criteria above are NOT TESTED and are not claimed complete.
