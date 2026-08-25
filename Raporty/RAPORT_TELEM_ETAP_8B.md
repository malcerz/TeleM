# TeleM — ETAP 8B — RESULT

## A. Old `chart_upload` timer scope

The old bucket was in:

```text
file:     src/ffmpeg/amd_native_exporter.py
function: export_amd_native_d3d11(), main per-frame loop
start:    previous frame-accounting marker: frame_acct.mark("compose")
stop:     frame_acct.mark("chart_upload")
scope:    everything after the main compose marker and before gauge upload
```

The stop marker was inside `if gpu_capture:`. `gpu_capture` is non-empty when the GPU gauge is captured, even when `gpu_chart_keys` is empty. Therefore the old marker ran for the current layout despite zero GPU charts.

The interval included:

```text
CPU_ABOVE_MAP compose_overlay()
alpha getchannel("A").getbbox()
above_map crop()
empty/no-op chart upload loop
```

It did not represent a chart upload.

The ETAP 8A baseline was:

```text
old chart_upload avg    = 13.191 ms
old chart_upload median = 12.524 ms
old chart_upload p95    = 20.699 ms
```

## B. Active chart inventory

The unchanged `def_layout.json` contains these chart-form indicators:

| Indicator | Form | Configured | CPU rendered | GPU captured | Result/reason |
|---|---|---:|---:|---:|---|
| `fit_cadence_text` | `chart` | yes | 0 | 0 | frame data has no cadence value at the tested target times |
| `fit_heart_rate_text` | `chart` | yes | 0 | 0 | frame data has no HR value at the tested target times |

Runtime logs reported:

```text
GPU charts fallback -> CPU_REFERENCE (no active chart widgets)
```

The overlay profiler confirmed zero `graph.*` metrics, zero chart geometry entries, and zero chart render calls across 900 frames. This is stronger than merely observing `active_gpu_charts = []`: no CPU chart raster was produced either.

The GPU gauge was captured, so `gpu_capture` itself was non-empty. That was the condition that exposed the old accounting bug.

## C. Diagnostic instrumentation

Only observational timing was added to `src/ffmpeg/amd_native_exporter.py`. Rendering behavior, chart algorithms, GPU selection, map, gauge, AMF and correctness contracts were not changed.

New diagnostic timers:

| Sub-bucket | Meaning |
|---|---|
| `above_compose` | CPU `compose_overlay()` for the post-map `CPU_ABOVE_MAP` layout |
| `above_bbox_crop` | alpha-channel bbox scan plus `crop()` for ABOVE |
| `chart_plan` | setup before the chart upload loop |
| `chart_rgba_conversion` | chart image/tile `tobytes()` conversions |
| `chart_upload_call` | actual Python-to-native chart update calls |
| `chart_native_submit` | same native submission wall interval, diagnostic alias for attribution |
| `chart_gpu_submit` | GPU execution timing; unavailable without a chart GPU timestamp |
| `chart_other` | residual chart-block wall time |

The existing `chart_cpu_tobytes`, `chart_python_upload`, `chart_dynamic_tobytes` and `chart_dynamic_upload` timers remain available as nested detail.

## D. Timer overlap and double accounting

There is no overlap between the main `compose_overlay` timer and the old bucket: the main compose timer ends before the ABOVE layout starts. The problem is scope attribution, not double-counting the same operation in both timers.

The old bucket was effectively:

```text
old chart_upload ≈ above_compose + above_bbox_crop + tiny chart-block remainder
```

The corrected exclusive frame accounting separates those stages. A post-fix verification run reported:

```text
above_compose    median 1.417 ms, p95 2.457 ms
above_bbox_crop  median 11.007 ms, p95 19.115 ms
chart_other      median 0.005 ms, p95 0.008 ms
chart_upload_call          0.000 ms
chart_rgba_conversion      0.000 ms
```

The old median of 12.524 ms is explained by approximately 1.4 + 11.0 ms, not by chart work.

## E. Repeated full-layout runs

Three full runs used 900 frames, `GX030120.MP4`, real unchanged layout, `AMD_NATIVE_D3D11`, GPU map/gauge, and `PRECOMPUTED` telemetry.

| Run | FPS | `above_compose` median | `above_bbox_crop` median | chart upload call |
|---|---:|---:|---:|---:|
| full1 | 26.764 | 1.370 ms | 10.716 ms | 0.000 ms |
| full2 | 25.844 | 1.459 ms | 11.066 ms | 0.000 ms |
| full3 | 26.891 | 1.431 ms | 10.811 ms | 0.000 ms |
| **median / min / max FPS** | **26.764 / 25.844 / 26.891** | — | — | — |

`full4` was an additional post-boundary-change verification: 25.863 FPS, `above_compose` median 1.385 ms, `above_bbox_crop` median 10.999 ms, chart upload call 0 ms.

All full runs completed 900/900 frames with AMF output 900 and `AMF_INPUT_FULL = 0`.

## F. Repeated charts-off runs

The existing runtime diagnostic was used through a runtime layout copy with both potential chart indicators disabled; `def_layout.json` was not written.

| Run | FPS | `above_compose` median | `above_bbox_crop` median | chart upload call |
|---|---:|---:|---:|---:|
| charts0_1 | 27.209 | 1.449 ms | 10.692 ms | 0.000 ms |
| charts0_2 | 26.836 | 1.366 ms | 10.744 ms | 0.000 ms |
| charts0_3 | 27.009 | 1.455 ms | 10.756 ms | 0.000 ms |
| **median / min / max FPS** | **27.009 / 26.836 / 27.209** | — | — | — |

The small FPS difference is ordinary run-to-run variance. The ABOVE crop cost remains unchanged, proving that the old bucket was independent of chart count.

## G. Controlled 0/1/2 chart cases

Runtime copies were tested with zero, one and two chart indicators configured:

| Configured chart count | CPU chart render calls | GPU capture count | chart upload call | Result |
|---:|---:|---:|---:|---|
| 0 | 0 | 0 | 0 ms | no chart data/work |
| 1 | 0 | 0 | 0 ms | no chart data/work |
| 2 | 0 | 0 | 0 ms | no chart data/work |

The one- and two-chart cases cannot become a real chart workload with this material/time range because the FIT-derived HR/cadence values supplied to the frame path are `None`. The controlled result is nevertheless conclusive for the anomaly: the old ~12 ms bucket persists with zero actual chart work and is unchanged when chart configuration is changed.

## H. Detailed chart path

For the real 900-frame workload:

| Operation | Count | Median | p95 | Status |
|---|---:|---:|---:|---|
| chart history preparation / clipping | 0 | 0 | 0 | NOT APPLICABLE: no chart value/history reached renderer |
| chart CPU raster | 0 | 0 | 0 | NOT APPLICABLE |
| PIL chart surface creation | 0 | 0 | 0 | NOT APPLICABLE |
| RGBA conversion | 0 | 0 | 0 | NOT APPLICABLE |
| native chart upload | 0 | 0 | 0 | NOT APPLICABLE |
| GPU chart blend | 0 | 0 | 0 | N/A: no GPU chart capture |
| residual chart block | 900 | about 0.005 ms | about 0.008 ms | measured |

The large old bucket was therefore not chart history, rasterization, conversion, upload, native submission or GPU execution.

## I. Allocation and copy inventory

For chart work on this input:

```text
chart surfaces created/frame = 0
chart history slices/frame  = 0
chart byte buffers/frame    = 0
chart NumPy arrays/frame    = 0
chart upload bytes/frame    = 0
```

The measured large allocation/copy is the ABOVE path’s alpha scan and crop, not a chart surface.

## J. Representative frame timeline

The corrected exclusive order for a normal frame is:

```text
decode/read
→ telemetry
→ main compose_overlay                         compose
→ CPU_ABOVE_MAP compose_overlay                 above_compose ~1.4 ms
→ alpha getbbox + above crop                    above_bbox_crop ~10.7–11.0 ms
→ chart plan / empty chart block                ~0.005 ms
→ gauge upload
→ map upload/preparation
→ HUD dirty extraction/update
→ native process_frame / VP / AMF
```

Frame-accounting p95 for ABOVE crop was about 19 ms. This matches the old `chart_upload` p95 of 20.699 ms when the tiny ABOVE compose and chart-block remainder are included.

## K. Corrected critical path

The corrected serial CPU ranking is:

1. `above_bbox_crop`: median approximately 10.7–11.0 ms, p95 approximately 18.8–19.3 ms.
2. Main `compose_overlay`: median approximately 5.6–7.7 ms in repeated runs.
3. Native `process_frame`: median approximately 2.3 ms.
4. Map upload/preparation and gauge upload: each approximately 1.5–2.4 ms median depending on run.
5. Decode availability and telemetry are smaller on average, with decode p95 spikes.

The previous chart ranking was invalid. The actual dominant unexplained serial CPU operation is `CPU_ABOVE_MAP` alpha bbox/crop preparation.

## L. Actual top bottleneck

```text
SEVERITY:       HIGH
EXACT OPERATION: above_full.getchannel("A").getbbox() + above_full.crop(alpha_bbox)
FILE/FUNCTION:  src/ffmpeg/amd_native_exporter.py / export_amd_native_d3d11()
MEASURED COST:  median about 10.7–11.0 ms, p95 about 19 ms
WHY SERIAL:     executed synchronously in the Python frame loop before native upload
```

This operation is not a chart operation. It is the post-map ABOVE layer preparation required by the ETAP 7D z-order contract.

## M. 60 FPS gap correction

The steady-state encoded period remains approximately 34–37 ms/frame in the repeated profiled runs, versus 16.667 ms/frame for 60 FPS. The largest confirmed serial component is now the ABOVE alpha scan/crop, not chart upload.

The old `chart_upload` bucket should no longer be used in critical-path conclusions.

## N. Instrumentation overhead

The new timing calls are `perf_counter()` reads and existing frame-accounting marks. They do not alter render decisions, image contents, GPU paths or encoder settings. The repeated runs show normal variance of several FPS, so the exact overhead cannot be isolated from these runs alone. The detailed subtimers themselves are negligible relative to the 10+ ms ABOVE crop.

## O. Tests and regression

Targeted tests after instrumentation:

```text
13 passed
```

Full suite:

```text
330 passed, 3 failed, 17 skipped
```

The three failures are unchanged known failures:

```text
tests/test_amd_native_etap4.py
tests/test_qp_analyzer.py
tests/test_render_tab.py
```

No new unrelated failure was introduced. The diagnostic runner is `scratch/etap8b_runner.py`; it uses only runtime layout copies and the required real material.

## P. Confirmed performance issue

```text
CONFIRMED:
The old chart_upload bucket was mis-scoped. It measured the CPU_ABOVE_MAP
compose plus alpha bbox/crop interval, while actual chart work was zero.
```

## Q. Recommended ETAP 8C

```text
ETAP 8C — targeted optimization: CPU_ABOVE_MAP alpha bbox/crop preparation
```

The next stage should measure and reduce the exact `getchannel("A").getbbox()` / `crop(alpha_bbox)` cost while preserving the ETAP 7D z-order and pixel-correctness contract. No optimization is implemented in ETAP 8B.

## Final classification

```text
ETAP 8B = COMPLETE
CHART_UPLOAD_ROOT_CAUSE = IDENTIFIED
REAL_CHART_UPLOAD_COST = 0 ms for GX030120 workload
ACTUAL_BOTTLENECK = CPU_ABOVE_MAP alpha bbox/crop
```
