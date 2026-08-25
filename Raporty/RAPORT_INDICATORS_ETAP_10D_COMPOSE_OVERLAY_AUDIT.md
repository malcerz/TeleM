# TeleM — ETAP 10D: audyt `compose_overlay`

Data: 2026-08-22  
Tryb: audit-only; brak zmian produkcyjnych.  
Materiał: `Video/GX010115.MP4`, `Video/GX010115.json`, `Video/Jazda_na_rowerze_w_porze_lunchu.fit`  
Preset: `presets/cycling_dashboard_v10.json`  
Rozdzielczość: 1280×720, 120 klatek, AMD Native, bez SmartSync.

## 1. Call path

Rzeczywista ścieżka AMD:

```text
AMD producer frame
  -> compose_overlay(layout=compose_layout, reuse_canvas="below")
       -> CPU_BELOW_MAP
  -> native GPU map upload/resize/blend
  -> compose_overlay(layout=map_above_layout, reuse_canvas="above")
       -> CPU_ABOVE_MAP
  -> candidate bbox crop
  -> local alpha bbox scan
  -> final region crop
  -> PIL RGBA tobytes
  -> native HUD region upload/composite
```

W `src/ffmpeg/amd_native_exporter.py` są to odpowiednio: `_producer_frame` → `compose_overlay` → `_cluster_above_bboxes` / `_rendered_bbox_union` → `crop` / `getchannel("A").getbbox()` / `tobytes`.

W `src/indicators/compositor.py`:

```text
compose_overlay
  -> prepare time block/display
  -> per-indicator loop
       -> render_value_indicator (dispatcher)
          -> renderer: chart/gauge/bar/text
       -> widget geometry/bbox
       -> rotated_paste
          -> optional transpose for 90/180/270
          -> composite_final
             -> local getbbox
             -> local crop when useful
             -> local alpha_composite or paste
       -> annotations/range labels
  -> custom texts
  -> reusable canvas state update
```

## 2. CPU_ABOVE_MAP widgets

```text
compass, slope_text, iso_text, exposure_text, temp_text,
alt_visual, fit_curVpower_text, fit_cadence_text,
fit_enhanced_speed_text, fit_heart_rate_text
```

## 3. Per-widget renderer vs compositor cost

Measured with the existing OverlayProfiler around the real above-map `compose_overlay` path, 120 frames. `placement/blend` is the existing `paste_composite` scope; `total` is the complete compositor indicator scope.

| Widget | renderer ms | placement/blend ms | total ms |
|---|---:|---:|---:|
| Compass | 0.305 | 0.465 | 0.843 |
| Slope | 2.128 | 0.628 | 2.817 |
| ISO | 0.594 | 0.083 | 0.732 |
| Shutter | 1.163 | 0.070 | 1.281 |
| Temp | 0.155 | 0.078 | 0.282 |
| Altitude | 2.096 | 0.360 | 2.513 |
| Virtual Power | 1.951 | 0.384 | 2.392 |
| Cadence | 6.162 | 0.224 | 6.452 |
| Speed Gauge | 1.591 | 0.372 | 2.032 |
| HR | 12.866 | 0.184 | 13.120 |
| **Sum** | **29.010** | **2.847** | **32.464** |

This corrects the 10C local-chart measurement: its simplified history input made Chart appear near 0.09 ms. On the real precomputed moving-window data used by AMD `CPU_REFERENCE`, HR and Cadence are approximately 19.0 ms together.

## 4. Allocation count

For the above phase, the profiler measured approximately 9.9 `Image.new` calls/frame and 0.127 ms/frame. These are local renderer/helper images; they total about 149k pixels/frame.

The major compositor canvases are persistent reusable canvases. They are not allocated once per widget or once per frame after warm-up.

## 5. Full-frame buffer count

At 1280×720, one RGBA frame is:

```text
1280 × 720 × 4 = 3,686,400 bytes = 3.52 MiB
```

Actual steady state: **0 new full-frame RGBA buffers/frame**. One persistent below canvas and one persistent above canvas are retained per worker. The AMD probe creates one additional temporary full-frame canvas during the first safety probe; it is not a per-frame allocation.

There is no `canvas.copy()` or `Image.alpha_composite(full_canvas, full_canvas)` per widget in this path.

## 6. Alpha-composite calls

Above-map profiler totals:

```text
Image.alpha_composite / instance alpha_composite: 8.625 calls/frame
time: 1.004 ms/frame
aggregated processed pixels: ~3,053,886/frame
```

These are local renderer/placement operations. `composite_final` never promotes a widget to a full 1280×720 overlay. It composites the local raster or a local content crop at its destination.

The code contains `paste(..., mask)`-style local operations and `alpha_composite`; the profiler reports about 25.225 paste calls/frame and 0.766 ms/frame. Its generic pixel counter is based on the receiver image and therefore overstates the actually changed rectangle for canvas-region clears; it must not be interpreted as 25 full-frame writes.

## 7. Paste/crop/copy cost

Above-map profiler:

| Operation | calls/frame | ms/frame | Actual role |
|---|---:|---:|---|
| `copy()` | 8.992 | 0.247 | local renderer/static-layer copies |
| `crop()` | 8.992 | 0.308 | local content crops and renderer work |
| `paste()` | 25.225 | 0.766 | local placement plus reusable-canvas regional clears |
| `getbbox()` | 11.683 | 0.078 | local alpha/content bounds |

After `compose_overlay`, AMD CPU_ABOVE_MAP adds candidate crop, alpha scan, final crop and region conversion. The 10B profile measured approximately 0.630 ms candidate crop, 0.392 ms local alpha scan, 0.466 ms final crop and 0.993 ms `tobytes`/region conversion per frame.

## 8. Rotation cost

There is no steady-state `rotate()` call. The only above-map rotation is `alt_visual` at 90°, handled by `transpose`; profiler cost was approximately:

```text
1 transpose/frame, 0.030 ms/frame
```

The existing `rotated_paste` computes the final rotated raster dimensions before placement, so the final bbox is already rotation-aware.

## 9. Resize cost

No above-map `resize()` cost was observed in the steady-state profile. Renderer resizing is cache/static-build work or not used for these final-size widgets; the compositor does not resize every widget after rendering.

## 10. Conversion cost

- No PIL↔NumPy conversion is performed by `compose_overlay` in the steady state.
- `_clean_transparency` may use NumPy for a one-time cache safety check; it is not a per-frame conversion after the cache is warm.
- No RGBA↔BGRA/RGB conversion occurs in CPU compositing.
- `PIL Image.tobytes("raw", "RGBA")` occurs after above composition for each compact upload region, not inside `compose_overlay`; the existing 10B timing was approximately 0.993 ms/frame.

## 11. CPU_BELOW_MAP comparison

The same direct profiler run measured below renderer work as:

| Component | ms/frame |
|---|---:|
| time_display renderer | 11.306 |
| Distance renderer | 2.963 |
| Battery renderer | 6.025 |
| Solar renderer | 3.545 |
| **Below renderer subtotal** | **23.839** |
| Below placement/blend subtotal | 1.269 |
| Below annotations | ~0.067 |

The instrumented AMD export reported `compose_overlay` (below) at 29.166 ms/frame. Thus below compositor overhead outside renderer scopes was approximately 5.3 ms/frame, including loop setup, canvas-state work and measurement boundary noise.

For above, renderer subtotal was 29.010 ms, placement/blend 2.847 ms and complete widget scopes 32.464 ms. The instrumented AMD export reported `above_compose` 31.907 ms and `above_total` 34.234 ms. The post-compose CPU region extraction therefore adds roughly 2.3 ms in this run.

## 12. `compose_overlay` decomposition

For CPU_ABOVE_MAP:

```text
real widget renderer calls       ~29.010 ms
placement / local blend           ~2.847 ms
annotations and widget overhead   ~0.6 ms inside total scopes
compose_overlay                   ~31.9 ms in AMD export
post-compose crop/alpha/tobytes   ~2.3 ms
above_total                       ~34.2 ms in instrumented export
```

The largest Pillow-level operations were not full-frame blends but text/chart work:

```text
textbbox/getbbox                   24.571 ms/frame aggregated
text drawing                       13.204 ms/frame aggregated
alpha_composite                     1.004 ms/frame
paste                               0.766 ms/frame
copy                                0.247 ms/frame
crop                                0.308 ms/frame
```

Operation timings are nested observations, so they must not be arithmetically summed with renderer scopes; they identify where time is spent, not independent wall-clock stages.

## 13. Reconciliation of the ~20 ms missing overhead

The apparent missing ~20 ms is explained by the measurement mismatch, not by 20 ms of hidden full-frame compositing.

The 10C local benchmark used simplified history objects and exercised the cached/static-friendly chart path. The real AMD CPU fallback uses precomputed moving-window chart data. In the real above frame:

```text
Cadence renderer  ~6.162 ms
HR renderer      ~12.866 ms
```

Together they account for approximately 19.028 ms of the previously unaccounted gap. The remaining time is ordinary per-widget compositor scope work, local placement and the post-compose region extraction.

```text
UNACCOUNTED ≈ 0–1 ms at the compose boundary
```

The exact residual varies with instrumentation and frame data; there is no evidence for an unmeasured 20 ms full-frame allocation/blend stage.

## 14. Memory traffic estimate

Measured local alpha-composite processing is approximately 3.05M pixels/frame, or:

```text
3.05M × 4 B ≈ 12.2 MB/frame
≈ 0.73 GB/s at 60 FPS
```

For comparison, a hypothetical full-frame RGBA blend for every one of the 10 above widgets would touch about 35.2 MiB/frame, or 2.11 GiB/s at 60 FPS. The current compositor does not perform that hypothetical operation.

## 15. 4K projection

Pixel ratio:

```text
(3840×2160) / (1280×720) = 9×
```

Any genuinely full-frame operation would project to roughly 9× its 720p pixel work. Current local widget placement does not automatically become a 9× full-frame blend, but large chart/gauge local rasters will still scale with their configured dimensions.

No 4K export was run.

## 16. Regional compositing feasibility

The requested regional model is already present in `rotated_paste` / `composite_final`:

| Widget type | Regional compositing |
|---|---|
| text | SAFE; existing local bbox path |
| chart | SAFE; preserve chart order and local final raster |
| gauge | SAFE; local bbox and alpha semantics already preserved |
| Compass | SAFE; static/dynamic local raster |
| bar/ruler | SAFE; existing local raster placement |
| Slope | SAFE; existing local raster placement |
| rotated widget | NEEDS ROTATION BBOX; existing helper already handles it |

No widget in the audited path requires a full-frame overlay solely for placement.

## 17. Z-order/parity implications

Replacing a local `alpha_composite` with another regional implementation is mathematically safe only when it uses the same destination region, source-over alpha order and widget sequence. The existing helper already keeps prior bboxes and falls back to alpha compositing when transparent-destination paste cannot be proven equivalent.

The overlap guards and `CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP` order were not changed.

## 18. Recommended ETAP 10E

Do not start with regional compositor work; it is already implemented and contributes only about 2.8 ms/frame in above placement/blend.

The concrete next optimization should target the real CPU_REFERENCE chart renderer, prioritizing `fit_heart_rate_text`, then `fit_cadence_text`: reduce repeated `textbbox`/dynamic chart assembly while preserving moving-window semantics and byte parity. The benchmark must use the real precomputed chart data, not a simplified history list.

## 19. Changed files

```text
none production
```

No temporary instrumentation file was retained. No preset, test, telemetry, GUI, AMD pipeline or NVIDIA path was changed.

## 20. Final decision

`NEXT: COMPOSITOR NOT THE MAIN BOTTLENECK`

The suspected ~20 ms is primarily real chart renderer cost under the AMD CPU fallback, not full-frame allocation/copy/blend overhead.
