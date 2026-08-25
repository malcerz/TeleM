# TeleM — ETAP 7B: naprawa AMD chart parity przy `GPU map + charts after map`

Data: 2026-08-21  
Preset: `presets/cycling_dashboard_v3.json` — niezmieniony, SHA-256:
`43FE007A69E8F282BA5B20C1E4F5BF1BB9AA848C34FD25EB3681B62304A8799`

## 1. Root cause

ETAP 7A potwierdził, że po ordered-map split zmienna `compose_layout` wskazywała na `below-map`. Ten layout był przekazywany do `init_worker()`, `build_telemetry_cache()` oraz chart discovery. Ponieważ cadence i heart-rate znajdowały się po `track_map`, znikały z `_precomputed_chart_data`; `CPU_ABOVE_MAP` dostawał `chart_data={}` i renderer przechodził na fallback z osią procentową.

## 2. Implementowany fix

Zmieniono wyłącznie `src/ffmpeg/amd_native_exporter.py`:

- dodano `_amd_layout_roles()`;
- pełny layout użytkownika jest zachowany jako `semantic_layout`;
- `compose_layout` jest tworzony tylko dla partycji compositingu;
- `init_worker()`, `_live_frame_data()` i `build_telemetry_cache()` otrzymują `semantic_layout`;
- GPU chart discovery używa pełnego layoutu z wyłączonym `track_map` z listy renderowanych kluczy;
- rzeczywiste `compose_overlay()` below-map nadal otrzymuje wyłącznie `compose_layout`;
- `track_map.enabled=false` nie uruchamia ordered splitu;
- overlap guard `GPU_CHART_UNSAFE_LAYOUT` pozostał bez zmian.

Nie zmieniano `worker_cache.py`, chart rendererów ani telemetry precompute.

## 3. Semantic layout vs compose layout

```text
semantic_layout = pełny layout v3
  → worker chart precompute
  → telemetry precompute
  → frame data
  → GPU chart discovery

compose_layout = below-map partition
  → CPU_BELOW_MAP

map_above_layout = above-map partition
  → CPU_ABOVE_MAP
```

Przekazanie pełnego layoutu do precompute nie powoduje renderowania widgetów after-map w warstwie below-map.

## 4. Worker/precompute

Przed poprawką worker dostawał `below-map`, a chart data było puste. Po poprawce worker dostaje pełny layout i przygotowuje obie historie:

```text
fit_cadence_text:     scope=window, window=60 s
fit_heart_rate_text:  scope=window, window=60 s
```

W klatce probe oba rekordy miały 60 próbek, początek `NOW-60 s`, koniec `NOW` i zero próbek przyszłych.

## 5. Ordered-map behavior

Runtime AMD potwierdził:

```text
CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
```

Oba charty pozostały w `CPU_ABOVE_MAP`; nie zmieniano ich kolejności w v3.

## 6. Chart discovery i GPU fallback

Discovery analizuje teraz pełny layout. W probe oba charty zostały wykryte, ale istniejący guard odrzucił ich capture GPU:

```text
GPU charts fallback -> CPU_REFERENCE
GPU_CHART_UNSAFE_LAYOUT -> all charts CPU_REFERENCE
```

Powód: overlap z istniejącym widgetem distance. Jest to poprawny i zachowany fallback; charty nadal są renderowane nad mapą przez `CPU_ABOVE_MAP`.

## 7. CPU vs AMD data parity

Probe: ten sam materiał GX030120, fragment od 60 s, v3, 3840×2160, 60 klatek AMD.

| Pole | CPU reference | AMD precomputed/fallback |
|---|---:|---:|
| cadence start | `2026-08-18 04:46:26.700` | `2026-08-18 04:46:26.700` |
| cadence end | `2026-08-18 04:47:26.700` | `2026-08-18 04:47:26.700` |
| cadence sample count | 60 | 60 |
| cadence first value | 64.0 | 64.0 |
| cadence last value | 58.0 | 58.0 |
| HR start | `2026-08-18 04:46:26.700` | `2026-08-18 04:46:26.700` |
| HR end | `2026-08-18 04:47:26.700` | `2026-08-18 04:47:26.700` |
| HR sample count | 60 | 60 |
| HR first value | 100.0 | 100.0 |
| HR last value | 102.0 | 102.0 |
| cursor | `2026-08-18 04:47:26.700` | `2026-08-18 04:47:26.700` |

AMD użył wspólnego precomputed payloadu; chart GPU nie został użyty z powodu guardu.

## 8. CPU vs AMD visual result

Artefakty:

- [CPU frame](INDICATORS_ETAP_7B_CPU_FRAME.png)
- [AMD frame](INDICATORS_ETAP_7B_AMD_FRAME.png)
- [CPU charts crop](INDICATORS_ETAP_7B_CPU_CHARTS.png)
- [AMD charts crop](INDICATORS_ETAP_7B_AMD_CHARTS.png)

Obie klatki pokazują osie:

```text
-60 s, -45 s, -30 s, -15 s, 0 s
```

Nie występuje fallback `0%, 25%, 50%, 75%, 100%`.

## 9. `track_map.enabled=false`

Poprawiono lokalny warunek: obecność klucza `track_map` nie wystarcza do uruchomienia ordered splitu. Wymagany jest aktywny widget. Dodano test dla tego przypadku.

## 10. Map parity regression

`tests/test_map_first_render_parity.py` przechodzi. Nie zmieniano `moving_map.py` ani map parity fixu z ETAPU 5B.

## 11. NVIDIA static regression

Nie zmieniano `streaming.py`, `command_builder.py`, CUDA, NVENC ani innych ścieżek NVIDIA. NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 12. Performance sanity

Runtime AMD probe:

```text
precompute build:       14.064 ms
telemetry cache lookup:  0.148 ms/frame average
CPU_ABOVE_MAP total:    44.787 ms/frame average
render FPS:             12.626
effective FPS:          10.102
```

Fix nie buduje chart data per klatkę i nie kopiuje pełnej historii per klatkę. Pełny layout jest używany podczas inicjalizacji/precompute; warstwy compositingu pozostają filtrowane.

## 13. Testy

Nowy test:

```text
tests/test_amd_chart_map_split.py
```

Zestaw regresji ETAP 7B:

```text
111 passed in 7.02s
```

Zakres obejmował chart window/fixed timeline/static assembly/cache, telemetry precompute, AMD chart/ordered-map/above-map, runtime layout/parity, map parity 5B oraz NVIDIA chart/map regression. Dodatkowo `py_compile` eksportera przeszedł poprawnie.

Pełna regresja repozytorium:

```text
584 passed, 17 skipped in 41.08s
```

## 14. Lista zmienionych plików

```text
src/ffmpeg/amd_native_exporter.py
tests/test_amd_chart_map_split.py
Raporty/INDICATORS_ETAP_7B_CPU_FRAME.png
Raporty/INDICATORS_ETAP_7B_AMD_FRAME.png
Raporty/INDICATORS_ETAP_7B_CPU_CHARTS.png
Raporty/INDICATORS_ETAP_7B_AMD_CHARTS.png
Raporty/RAPORT_INDICATORS_ETAP_7B_AMD_CHART_MAP_SPLIT_FIX.md
```

## 15. Preserved

- `presets/cycling_dashboard_v3.json` pozostał bez zmian;
- CPU_REFERENCE i semantyka chartów pozostały bez zmian;
- AMD map path i ordered z-order pozostały aktywne;
- overlap guard GPU chartów pozostał aktywny;
- `worker_cache.py`, `chart.py`, `chart_builder.py`, `telemetry_precompute.py`, `frame_data.py`, `moving_map.py` pozostały bez zmian w ETAPIE 7B;
- NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 16. Remaining risks

- Oba charty v3 nadal trafiają do CPU_REFERENCE z powodu istniejącego overlap guardu; jest to poprawne, ale nie daje GPU acceleration dla tych chartów.
- Probe runtime wykonano na AMD; runtime NVIDIA pozostaje niewalidowany na tej maszynie.
- Pełny benchmark przed/po nie był celem ETAPU 7B.
