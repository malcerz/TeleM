# NVIDIA Device-B HUD optimization

## Scope

This stage addressed only Native D3D11 Device-B HUD performance. The canonical GUI path remained `MainWindow → RenderTab → EKSPORTUJ`, using `GX020079.MP4` + `GX020079.fit`, `def_layout.json`, 3840×2160, 1131 frames, HEVC Main10, and the existing separate Device-B HUD architecture. No telemetry semantics, layout, colors, fonts, chart data, map provider/raster, VP/NVENC settings, bitrate, or output codec was changed.

## Required result

```text
HUD_MS_BEFORE=7.172
HUD_MS_AFTER=7.023
CADENCE_CHART_MS_BEFORE=0.709
CADENCE_CHART_MS_AFTER=0.312
HR_CHART_MS_BEFORE=0.473
HR_CHART_MS_AFTER=0.131
MAP_MS_BEFORE=0.019
MAP_MS_AFTER=0.014
KEYED_MUTEX_WAIT_MS=0.038 mean (1131f profile)
EVENT_WAIT_MS=0.463 mean (1131f profile)
GETDATA_WAIT_MS=0.202 mean (VP completion profile)
LEGACY_MEDIAN_FPS=77.638 final six-run sequence; entry baseline was 83.827
NATIVE_MEDIAN_FPS_BEFORE=106.236
NATIVE_MEDIAN_FPS_AFTER=105.087 final six-run sequence
REAL_GAIN_PERCENT_AFTER=35.36 same-sequence GUI wall FPS; entry baseline gain was 26.73%
VISUAL_REGRESSION=PASS
FULL_FRAME_READBACK_COUNT=0
PRIMARY_OPTIMIZATION=Static chart grid geometry and text-layout cache
SECONDARY_OPTIMIZATION=Diagnostic wait/chart/map/widget profiling; no production sync redesign
USER_APPROVAL_REQUIRED=NO
MODIFIED_FILES=native/d3d11_nvenc_pipeline/CMakeLists.txt; native/d3d11_nvenc_pipeline/src/hud_profile.h; native/d3d11_nvenc_pipeline/src/hud_profile.cpp; native/d3d11_nvenc_pipeline/src/d3d11_nvenc_pipeline.cpp; native/d3d11_nvenc_pipeline/src/indicators/chart_indicator.h; native/d3d11_nvenc_pipeline/src/indicators/chart_indicator.cpp; native/d3d11_nvenc_pipeline/src/indicators/map_indicator.cpp
CASE=CASE C
```

The six-run result is subject to the same GUI-machine variance as the entry benchmark: the final Legacy median was 77.638 FPS and Native median 105.087 FPS. The optimization acceptance therefore uses the isolated Device-B HUD and per-chart measurements, not a claimed total-FPS improvement. The optimized 1131-frame profile run measured 7.023 ms HUD and 124.253 native loop FPS.

## Instrumentation

With `TELEM_NATIVE_HUD_PROFILE=1`, the native DLL records mean/median/p95/max/count into `scratch/nvidia_hud_opt/`. Instrumented waits include Device-B keyed-mutex acquire/release, Device-A consume acquire/release, D3D11 EVENT completion, and VP `GetData` completion. Chart rows separately cover sample preparation, grid, axis/header labels, geometry creation, fill, outline, and cursor. Map rows cover layer setup, position transform, tile lookup/draw, route, marker, and border. Widget rows measure each indicator render call.

The pre-cache 100-frame snapshots are retained as `wait_breakdown_before.csv`, `chart_profile_before.csv`, and `map_profile_before.csv`; the required `wait_breakdown.csv`, `chart_profile.csv`, and `map_profile.csv` contain the final 1131-frame profile.

The direct chart profile shows the largest removable static work was chart labels/grid. The map profile is already sub-0.02 ms/frame, while the Device-B completion event averages about 0.463 ms and has no evidence of a dominant mean wait bottleneck.

## Implementation

`ChartIndicator` now creates static grid geometry and static axis/time/title `IDWriteTextLayout` objects once per device-resource lifetime. Every dynamic history sample, fill polygon, outline stroke, cursor, live value, brush, alpha, coordinate, and draw order remains on the existing path. The profiler is disabled unless explicitly enabled by environment variable and has no production effect when disabled.

No map optimization or cross-device synchronization redesign was applied because measured map cost and wait means did not justify a riskier change in this stage.

## Tests

- Native 100-frame pre-cache and post-cache GUI runs: PASS.
- Native 300-frame post-cache run: PASS.
- Native 300-frame repeat runs ×3: PASS; HUD 7.685/7.586/7.406 ms.
- Native 1131-frame optimized production run: PASS; 1131 completed frames, D2D/VP success, full-frame readback count 0.
- Final six fresh GUI processes in required order: PASS; all return codes 0.
- Sampled frame comparison: frames 0 and 50 had `MAE=0`, `different_pixels=0`; frame 99 manual inspection showed unchanged HUD geometry and appearance (independent HEVC runs are not claimed byte-identical).

## Artifacts

All stage artifacts are in `scratch/nvidia_hud_opt/`: wait/chart/map/widget profiles, before/after performance CSVs, optimized MP4s, visual regression notes, root causes, modified/created files, manifest, reproduction commands, and the NTFY result. The canonical six-run raw results remain in `scratch/nvidia_real_perf_truth/`.

## Risks and isolation

The static cache is scoped to `ChartIndicator` device resources and is rebuilt on resource discard. It does not alter AMD, Intel, CPU/reference, VP, NVENC, or codec behavior. Full total-HUD target ≤5 ms was not reached; further reduction would require a broader live-widget/text renderer redesign and is intentionally STOPPED under CASE C.

`AMD_NATIVE_D3D11` smoke was not run: all production changes are confined to the NVIDIA native DLL and its NVIDIA-only diagnostic profiler; no AMD source path was touched.

```text
STATUS=PASS — CASE C
FINAL_PREVIEW_TO_MP4_PARITY=NOT_RETESTED (outside this performance task)
AV1=NOT_STARTED
H264=NOT_STARTED
DEFAULT_BACKEND=NOT_STARTED
```
