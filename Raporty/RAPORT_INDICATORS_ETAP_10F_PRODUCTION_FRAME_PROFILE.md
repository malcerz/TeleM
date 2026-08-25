# TeleM — ETAP 10F: production frame profile

## 1. Zakres i metoda

Audit-only dla jednego rzeczywistego eksportu AMD Native, bez SmartSync i bez zmian optymalizacyjnych:

- 1280×720, 120 klatek, 60 FPS, pełny `cycling_dashboard_v10`;
- `AMD_MAP_PATH=GPU`, `AMD_CHART_PATH=CPU_REFERENCE`, `AMD_GAUGE_PATH=GPU`;
- `AMD_TELEMETRY_MODE=PRECOMPUTED`, `AMD_NATIVE_HUD_MODE=GPU_HUD`, `AMD_NATIVE_DECODE_MODE=GPU_HUD_D3D11VA`;
- tymczasowy timer per-widget wokół istniejącego renderera i `rotated_paste`, usunięty po eksporcie.

Źródła: `Video/GX010115.MP4`, `Video/GX010115.json`, `Video/Jazda_na_rowerze_w_porze_lunchu.fit`, `presets/cycling_dashboard_v10.json`.

## 2. Call path

Rzeczywista ścieżka jednej klatki:

```text
MF D3D11VA sample
  -> prepare_frame / PRECOMPUTED telemetry lookup
  -> compose_overlay(... reuse_canvas="below", compose_layout)
       -> time_display / dist_visual / fit_battery_pct_text / fit_solar_pct_text
       -> render_value_indicator -> renderer family
       -> rotated_paste -> reusable below RGBA canvas
  -> render_map_working_image -> map RGBA bytes / GPU map payload
  -> CPU_BELOW_MAP HUD update
  -> native D3D11 GPU map stage
  -> compose_overlay(... reuse_canvas="above", map_above_layout)
       -> compass / slope_text / iso_text / exposure_text / temp_text
       -> alt_visual / fit_curVpower_text / fit_cadence_text
       -> fit_enhanced_speed_text / fit_heart_rate_text
       -> renderer -> rotated_paste -> reusable above RGBA canvas
  -> _cluster_above_bboxes / crop / alpha scan / final crop / tobytes
  -> telem_amd_update_above_region (dirty region upload)
  -> VideoProcessor submit + GPU completion/wait
  -> AMF submit/query/output -> packet write -> mux
```

`compose_layout` is the actual CPU_BELOW_MAP layout. `map_above_layout` is the actual CPU_ABOVE_MAP layout. The exporter calls are in `src/ffmpeg/amd_native_exporter.py`; widget composition is in `src/indicators/compositor.py`.

## 3. CPU_BELOW_MAP widgets

Steady-state means samples 10–119. Values are per frame; `total` includes the measured widget scope, while `renderer` and `placement/blend` are the temporary direct timers.

| Widget | renderer ms | placement/blend ms | total ms | share of below total |
|---|---:|---:|---:|---:|
| time_display | 3.450 | 0.385 | 3.834 | 37.0% |
| dist_visual | 0.808 | 0.848 | 1.709 | 16.5% |
| fit_battery_pct_text | 2.533 | 0.318 | 2.897 | 28.0% |
| fit_solar_pct_text | 1.557 | 0.323 | 1.921 | 18.5% |

The direct widget totals sum to about 10.36 ms steady-state. The exporter’s complete `compose_overlay` scope is 10.49 ms average (8.47 ms median), so the residual is about 0.13 ms plus timer/scope boundary effects.

First-frame widget totals were respectively 9.178, 5.350, 2.819, and 1.411 ms; this is expected font/cache warm-up and must not be used as steady-state cost.

## 4. CPU_ABOVE_MAP sanity

Steady-state per-widget totals:

| Widget | renderer ms | placement/blend ms | total ms |
|---|---:|---:|---:|
| Compass | 0.280 | 0.572 | 0.890 |
| Slope | 0.884 | 0.813 | 1.741 |
| ISO | 0.220 | 0.099 | 0.352 |
| Shutter | 0.315 | 0.090 | 0.431 |
| Temp | 0.035 | 0.086 | 0.148 |
| Altitude | 0.502 | 0.434 | 0.969 |
| Virtual Power | 0.379 | 0.523 | 0.939 |
| Cadence | 0.623 | 0.223 | 0.890 |
| Speed | 0.311 | 0.361 | 0.715 |
| HR | 0.926 | 0.224 | 1.193 |

The listed above widgets account for about 8.27 ms of direct widget scopes; the exporter’s `above_compose` scope is 8.61 ms average.

## 5. Production frame timings

| Stage | average ms/frame |
|---|---:|
| CPU_BELOW_MAP `compose_overlay` | 10.491 |
| map CPU preparation / bytes (`map_cpu_upload`) | 1.408 |
| native GPU map upload | 0.000 (not separately reported) |
| native GPU map resize/blend submit | 0.000 (not separately reported) |
| CPU_ABOVE_MAP `above_compose` | 8.607 |
| above region extraction (`above_bbox_crop`) | 1.698 |
| bbox tracking | 0.069 |
| candidate crop | 0.703 |
| local alpha scan | 0.389 |
| final crop | 0.538 |
| region RGBA→bytes | 1.091 |
| above region upload | 0.270 |
| HUD dirty extraction | 0.330 |
| HUD texture upload | 0.071 |
| GPU wait/synchronization | 3.560 |
| VideoProcessor GPU completion | 7.606 (diagnostic scope; overlaps wait) |
| AMF submit/backpressure | 0.496 |
| AMF QueryOutput | 0.198 |
| packet write | 0.169 |

`above_total` was 11.396 ms average. Region extraction plus conversion/upload is therefore about 4.70 ms/frame; it is material but smaller than the combined below/above CPU renderer work.

The directly measured, mostly non-overlapping Python-side sequence (`compose below + map preparation + above_total + telemetry + decode availability`) is approximately `32.0 ms/frame`. Adding the separately reported AMF submit/query/packet scopes gives `32.9 ms/frame`; GPU wait is reported separately because it overlaps the native completion scope. Against the clean 10E2 reference budget of `39.46 ms/frame`, roughly `6.6 ms` remains in native VideoProcessor/queue/bridge and measurement-boundary overhead. The exporter’s nested scopes must not be arithmetically summed as independent work: `producer_prepare=23.916 ms`, `consumer_native_call=10.900 ms`, and `pipeline_total=13.900 ms` overlap the stage table.

## 6. Frame accounting and cache sanity

`decoded/received/submitted/encoded/muxed = 120/120/120/120/120`. Native processed and VP processed were both 120; D3D11 surfaces were 120. `HR GPU=0`, `Cadence GPU=0`, confirming CPU_REFERENCE chart fallback. `GPU_CHART_UNSAFE_LAYOUT` remains effective through `AMD_CHART_PATH=CPU_REFERENCE`; no guard was changed.

The temporary widget run was intentionally limited to frame timing and did not alter the chart cache. The existing 10E2 production cache result remains the relevant cache sanity check: HR 239 hits / 1 miss / 1 entry and Cadence 119 hits / 1 miss / 1 entry.

## 7. Allocation and copy observations

The current path uses reusable below/above RGBA canvases keyed by canvas size. It does not create one new full-frame overlay per widget and does not call full-frame `Image.alpha_composite` for each widget. CPU placement is local `rotated_paste`; above-map handoff crops regions before `tobytes` and upload.

There are two persistent 1280×720 RGBA canvas buffers in the compositor’s below/above reusable-canvas stores: `1280×720×4 = 3,686,400 B = 3.516 MiB` each, about `7.031 MiB` total. This is resident allocation, not 2 new buffers per frame. The map image and local region temporaries are additional, variable-size allocations.

No separate CPU conversion stage was measured in this run: `PIL tobytes=0` for the full canvas, chart/gauge upload paths were inactive, and the active above conversion was the measured region `RGBA→bytes` stage.

## 8. Warm-up versus steady state

First-frame costs were substantially higher for most text widgets (for example `time_display=9.178 ms`, `dist_visual=5.350 ms`, `Slope=3.179 ms`, `Speed=3.868 ms`) than samples 10–119. This is consistent with font/raster/cache warm-up. There was no evidence of a per-frame cache-miss pattern in the existing chart cache data.

## 9. Remaining bottleneck

At the 25.343 FPS baseline cited by ETAP 10E2, the nominal frame budget is about 39.46 ms. This run reported `RENDER FPS=26.376`, `TRUE FPS=12.240`; instrumentation was active, so these are diagnostic production-run values rather than a clean regression comparison.

The largest attributable CPU indicator group is `CPU_BELOW_MAP`, led by `time_display` (3.834 ms), battery (2.897 ms), and solar (1.921 ms). GPU synchronization is also material at 3.560 ms, but the measured renderer work is larger and is directly actionable without changing the protected GPU pipeline.

## 10. Recommended ETAP 10G

Do not optimize in this audit. The single next target is:

```text
NEXT: OPTIMIZE TIME_DISPLAY
```

`time_display` is the largest individual remaining widget and its renderer, rather than placement, is the dominant part of its cost. Battery/solar should remain the following candidates after that targeted measurement.

## 11. Changed files

No production instrumentation remains. The temporary `compositor.py` hook and scratch runner were removed. This ETAP adds only audit artifacts:

- `Raporty/RAPORT_INDICATORS_ETAP_10F_PRODUCTION_FRAME_PROFILE.md`
- `Raporty/ETAP_10F_AMD_V10_1280.mp4`
- `Raporty/ETAP_10F_AMD_V10_1280.mp4.amd_profile.json`
- `Raporty/ETAP_10F_WIDGET_PROFILE.json`

Pre-existing worktree changes were not modified or reverted.

## 12. Final decision

```text
FRAME PROFILE: RENDERER BOTTLENECK
```

The dominant measurable remaining cost is CPU indicator rendering in `CPU_BELOW_MAP`, not full-frame alpha compositing. Region extraction/upload and GPU synchronization are secondary measurable costs. No full pytest suite was run.

NVIDIA path was preserved statically; NVIDIA runtime validation was not performed on this AMD machine.
