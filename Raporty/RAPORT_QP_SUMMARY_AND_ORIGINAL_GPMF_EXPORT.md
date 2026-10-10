# Raport: QP summary and original GoPro GPMF export

## Scope and initial state

- Task: preserve already collected live average QP in the completion summary and add opt-in stream-copy preservation of original GoPro GPMF.
- Initial repository state: branch `main`, HEAD `3e679f2`.
- The initial working tree already had a deleted user CSV, untracked reports, AMD diagnostics, and `telem_amd_native.dll.fresh-backup`. They were left untouched and excluded from commits.
- AMD runtime DLL initial SHA-256: `90BE5AF56BB56A73CDC161A0508B0D6A2C71987BE44A565712C37AA5B5D66647`.

## Implementation

- QP live values are read from `avg_qp`, `qp_avg`, or `mean_qp`; `QP avg: …` text is a compatibility fallback. The render controller clears its cached value at the start of each generation and tags every live value with that generation. Completion stats prefer canonical encoder values, then use the live average only when generation IDs match.
- Intel AV1 `base_q_idx` remains a Quantizer metric and is excluded from classical QP fallback.
- No post-export QP analysis or MP4 scan was added.
- Added `Dołącz oryginalny GPMF` to Rendering, default OFF. The boolean flows through direct options, queue snapshots, and session/project export settings.
- Enabled finalization detects the actual source stream by `codec_tag_string=gpmd` or GoPro MET handler properties. It copies output video/audio plus that source metadata stream with FFmpeg `-c copy`, validates the output `gpmd` stream, then atomically replaces the rendered file.
- The finalizer sets output data-stream tag `gpmd` explicitly; this FFmpeg build also passed a real 3-second HEVC/AAC/GPMF tag smoke.
- Trimmed exports are explicitly unsupported and left unchanged. A duration mismatch also prevents attachment. Multi-file exports are explicitly unsupported; the implementation never chooses only the first input.
- When the option is OFF, the existing finalization returns without running another mux.

## Real FFmpeg/GPMF validation

The canonical `GX020079.MP4` has no `gpmd` stream. Before using another dataset, the proposed pairing was reported: `C:\_DEV\SportCamHUD-amd\Video\GX010298.MP4` + `GX010298.fit`, solely for GPMF validation (noncanonical; not a performance benchmark). The remux itself does not consume the FIT file.

The project FFmpeg at `C:\tools\ffmpeg.exe` successfully stream-copied the 23:18 source into MP4. A separate stream-copy OFF smoke contained HEVC video and AAC audio and no data stream. The ON finalizer attach completed on the real source/output and passed ffprobe validation.

```text
GPMF_SOURCE_DETECTED=YES
GPMF_SOURCE_STREAM_INDEX=3
SOURCE_GPMF_CODEC_TAG=gpmd
SOURCE_HANDLER=GoPro MET
SOURCE_DURATION=1398.664000 s

OUTPUT_GPMF_TRACK=YES
OUTPUT_GPMF_STREAM_INDEX=2
OUTPUT_GPMF_CODEC_TAG=gpmd
OUTPUT_HANDLER=GoPro MET
OUTPUT_DURATION=1398.664000 s

SOURCE_GPMF_SAMPLES=1398
OUTPUT_GPMF_SAMPLES=1398
SOURCE_GPMF_PAYLOAD_BYTES=30705128
OUTPUT_GPMF_PAYLOAD_BYTES=30705128
SOURCE_PAYLOAD_SHA256=68163dac967dcc09eaa2d38c88eec5044e763c811a4374a696b4097a80d5d5ca
OUTPUT_PAYLOAD_SHA256=68163dac967dcc09eaa2d38c88eec5044e763c811a4374a696b4097a80d5d5ca
FIRST_MIDDLE_LAST_PAYLOAD_HASHES_MATCH=YES
GPMF_PAYLOAD_PRESERVED=YES
```

The first, middle (sample 699), and last sample payloads and timestamps matched. The TeleM native GPMF parser read the attached output successfully: GPS/track 13,490 samples, gyro 277,943, accelerometer 277,943, temperature 1,398, ISO 41,918, and exposure 41,918. The compiled parser was loaded from the sibling AMD checkout; its `gpmf_bindings.cpp` SHA-256 matches this checkout.

The OFF smoke output had streams `0: hevc/hvc1` and `1: aac/mp4a`, with no `gpmd` data track. The ON attached output had `0: hevc/hvc1`, `1: aac/mp4a`, and `2: bin_data/gpmd`.

## Required status fields

```text
QP_DATA_SOURCE=live encoder progress average; canonical terminal encoder stats preferred
QP_LOST_AT=handoff from live progress state to terminal stats consumed by RenderTab completion popup
QP_FIX=generation-scoped cache and same-generation completion fallback
LIVE_QP_AVAILABLE=YES (focused runtime-state test: 27.6)
FINAL_POPUP_QP_AVAILABLE=YES (same test: 27.6)
QP_MATCH_PASS=YES
POST_EXPORT_QP_ANALYSIS_USED=NO

GPMF_GUI_OPTION=Dołącz oryginalny GPMF
GPMF_DEFAULT=OFF
GPMF_SOURCE_DETECTED=YES (GX010298.MP4)
GPMF_SOURCE_STREAM_INDEX=3
GPMF_MUX_METHOD=FFmpeg MP4 stream-copy remux of rendered video/audio and detected source gpmd stream; atomic replacement after ffprobe validation
SOURCE_GPMF_CODEC_TAG=gpmd
OUTPUT_GPMF_CODEC_TAG=gpmd
GPMF_PAYLOAD_PRESERVED=YES
TRIMMED_GPMF_SYNC_PASS=NO; explicitly disabled for trimmed exports, with duration mismatch protection
MULTIFILE_GPMF_BEHAVIOR=explicitly unsupported; no source stream is attached
DIRECT_GPMF_OPTION_PASS=YES (GUI option snapshot and common finalizer tests)
QUEUE_GPMF_OPTION_PASS=YES (queue persistence and shared option snapshot tests)
EXPORTED_GPMF_PARSE_PASS=YES (attached real-source stream-copy MP4; TeleM native parser)
VIDEO_STREAM_COPY_DURING_GPMF_ATTACH=YES (`-c copy`; no second encode)
AUDIO_BEHAVIOR_UNCHANGED=YES (AAC audio retained by stream copy)
FINALIZATION_GPMF_OFF_SECONDS=0.000 added GPMF mux time (OFF bypasses the optional attach)
FINALIZATION_GPMF_ON_SECONDS=78.890 (8 GB full-duration stream-copy attach on this workstation)
AMD_NATIVE_DLL_UNCHANGED=YES; SHA-256 remains 90BE5AF56BB56A73CDC161A0508B0D6A2C71987BE44A565712C37AA5B5D66647
NEW_REGRESSIONS=none found in 96 focused pytest regressions; full TeleM render performance not measured
```

## Tests and limits

- `96 passed` across the new focused suite and existing queue, render-tab, progress, finalization, and cancellation lifecycle suites.
- The real GPMF attach was run through the new finalizer helper against a full-duration real GoPro MP4. The GPMF OFF check used a real FFmpeg stream-copy output.
- A full TeleM GUI/AMD video render with the option OFF and ON was **NOT TESTED**. The render-stage 39 FPS path and application end-to-end output therefore remain **NOT PROVEN** by this report.
- Trimmed and multi-file preservation are intentionally not available yet; both leave the valid rendered output unchanged and log the limitation.
- The 78.890-second attach time is copy/mux overhead for this 8 GB file and local storage; it is not an application render benchmark.

## Changed files

- `src/ffmpeg/export_stats.py`
- `src/ffmpeg/gpmf_export.py`
- `src/gui/qt/_mixins/render_mixin.py`
- `src/gui/qt/_mixins/preset_mixin.py`
- `src/gui/qt/tabs/render_tab.py`
- `tests/test_export_gpmf_and_qp_summary.py`
- `Raporty/RAPORT_QP_SUMMARY_AND_ORIGINAL_GPMF_EXPORT.md`

```text
COMMIT=dfc234e
PUSH_RESULT=SUCCESS; dfc234e pushed to origin/main with a normal non-force push
FINAL_STATUS=PARTIAL_TELEM_RENDER_NOT_TESTED
```
