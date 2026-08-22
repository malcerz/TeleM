# TeleM — ETAP 10E2: Chart axis-cache production validation

## 1. Exact cache key

Faktyczny key w `src/indicators/chart_utils.py`:

```text
(
  "chart_axis_v1",
  width,
  height,
  ss,
  bool(show_axes),
  tuple(grid_color) if grid_color is not None else None,
  tuple(y_label_values),
  tuple(x_labels),
  label_font_size,
  font_path,
)
```

`width` i `height` są wartościami po uwzględnieniu `ss`; `ss` jest dodatkowo
w key. `y_label_values` zawiera zakres/etykiety osi oraz jednostkę, jeśli
`label_units` jest aktywne.

## 2. Static properties inventory

Raster osi używa faktycznie:

- rozmiaru i supersamplingu,
- `show_axes`,
- `grid_color`,
- X labels,
- Y labels wynikających z zakresu lub `value_labels`,
- font path i rozmiaru fontu.

Kolor osi, ticków i tekstu, ich szerokości oraz transparentne tło są w tym
rendererze stałymi literalami (`axis_color`, `tick_color`, `label_color`,
`max(1, ss)`), a nie konfigurowalnymi właściwościami. Borderu osi jako osobnej
właściwości renderer nie używa. `line_color`, fill, current value, timestamp,
history i average series nie należą do static axis raster.

## 3. Cache-key completeness

**CACHE KEY: COMPLETE**

Nie wykonano zmiany produkcyjnego key. Dynamiczne dane nie są częścią key.

## 4. Invalidation tests

Dodano `tests/test_chart_axis_cache.py`. Pokrywa:

- same configuration: miss, następnie hit,
- width/height,
- supersampling,
- font path i font size,
- grid color,
- X/Y labels,
- min/max range,
- `show_axes` i `label_units`,
- rozdzielenie HR/Cadence.

Zmiana samego `unit` przy `label_units=false` nie tworzy miss, ponieważ tekst
jednostki nie jest wtedy używany przez static axis raster.

## 5. Pixel parity

Cache miss kontra hit dla HR i Cadence przy 60 s, 180 s i 300 s:

```text
different pixels = 0
max channel delta = 0
```

Targeted chart/window/font tests: **23 passed**.

## 6. Production cache statistics

Pełny AMD run v10, 120 klatek:

| Chart | hits | misses | entries / unique keys |
|---|---:|---:|---:|
| HR | 239 | 1 | 1 |
| Cadence | 119 | 1 | 1 |
| Combined | 358 | 2 | 2 |

HR ma dwa wywołania na klatkę w tej ścieżce compositingu; oba wpisy są stabilne.
Nie występuje miss per frame.

## 7. Production HR renderer

Per-widget `renderer_ms` nie został wyemitowany przez eksportera: wbudowany
OverlayProfiler ma w tym entry poincie `AMD_OVERLAY_PROFILE=ON`, ale nie otwiera
ramki przez `start_frame/finish_frame`, więc sekcja `etap5a.metrics` pozostaje
pusta. Nie zastępuję tej wartości estymacją z izolowanego benchmarku.

Chart działał przez CPU_REFERENCE przez wszystkie 120 klatek.

## 8. Production Cadence renderer

Tak samo jak HR: per-widget renderer timing nie został zebrany przez istniejący
eksporter. Cadence działał przez CPU_REFERENCE przez wszystkie 120 klatek.

## 9. AMD full-v10 benchmark

Artefakty:

- `Raporty/ETAP_10E2_AMD_V10_1280.mp4`
- `Raporty/ETAP_10E2_AMD_V10_1280.mp4.amd_profile.json`

Konfiguracja:

```text
AMD Native D3D11
1280×720
120 requested frames
target 60 FPS
full cycling_dashboard_v10
AMD_MAP_PATH=GPU
AMD_CHART_PATH=CPU_REFERENCE
AMD_GAUGE_PATH=GPU
AMD_TELEMETRY_MODE=PRECOMPUTED
SmartSync: not run
```

Wyniki:

| Metric | 10E2 production |
|---|---:|
| above_compose | **8.022 ms/frame** |
| above_total | **10.558 ms/frame** |
| compose_overlay / below | **9.727 ms/frame** |
| TRUE FPS | **12.049** |
| RENDER FPS | **25.343** |

## 10. Comparison to 10B/10D

| Metric | baseline | 10E2 production |
|---|---:|---:|
| HR renderer | 12.866 ms | not collected per-widget |
| Cadence renderer | 6.162 ms | not collected per-widget |
| Chart sum | 19.028 ms | not collected per-widget |
| above_compose | 33.236 ms | **8.022 ms** |
| above_total | 35.571 ms | **10.558 ms** |
| compose_overlay/below | 28.35 ms | **9.727 ms** |
| TRUE FPS | 8.893 | **12.049** |
| RENDER FPS | 14.376 | **25.343** |

The production reduction is confirmed at the phase level. The isolated
`0.923/0.886 ms` values are not used as production values.

## 11. Chart fallback status

```text
AMD_CHART_PATH requested: CPU_REFERENCE
effective chart path: CPU_REFERENCE
GPU chart frames: HR 0, Cadence 0
GPU_CHART_UNSAFE_LAYOUT guard: preserved, not modified
```

The run intentionally selected CPU_REFERENCE chart rendering. No overlap guard
was changed or bypassed.

## 12. Frame accounting

```text
decoded: 120
received / MF samples: 120
submitted / AMF: 120
encoded / AMF output: 120
muxed: 120
dropped submissions: 0
ignored submissions: 0
```

## 13. Remaining bottleneck

Chart axis-cache misses are no longer the bottleneck. At production level,
`above_compose` is 8.022 ms and `above_total` is 10.558 ms. The largest visible
remaining phase costs are outside this task, including region extraction and
GPU synchronization. No further renderer optimization was started.

## 14. Changed files

- `tests/test_chart_axis_cache.py` — dedicated invalidation coverage.
- `Raporty/RAPORT_INDICATORS_ETAP_10E2_CHART_PRODUCTION_VALIDATION.md` — this report.
- AMD benchmark artifacts listed above.

`src/indicators/chart_utils.py` was audited but not changed in ETAP 10E2.
Compositor, presets, telemetry, GUI, AMD/NVIDIA source paths and other
indicator renderers were not changed.

## 15. Final decision

**CHART OPTIMIZATION: PRODUCTION CONFIRMED**

## Next target

**NEXT: PROFILE CPU_BELOW_MAP RENDERERS**

No optimization of that target was performed in ETAP 10E2.
