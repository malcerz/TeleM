# ETAP 7A — RESULT

Data: 2026-08-18. Audyt read-only; kod, layout i testy produkcyjne nie były modyfikowane.

## A. Current AMD map architecture

`compose_overlay()` iteruje `layout["indicators"]` w kolejności insertion order. Enabled indicators są renderowane i wklejane przez `rotated_paste`; `track_map` jest częścią tego samego ordered CPU pass.

`amd_native_exporter.py:export_amd_native_d3d11` tworzy snapshot layoutu. Przy `CPU_REFERENCE` mapa pozostaje w Pillow RGBA HUD. Przy GPU map `track_map` jest usuwany z `compose_layout`, CPU generuje map working image przez `render_map_working_image`, a native D3D11 uploaduje ją do texture, skaluje i blenduje na GPU HUD. Charts i gauge są analogicznie CPU-generated RGBA textures uploadowanymi do GPU. Finalny video composition wykonuje native D3D11/VideoProcessor, a kodowanie AMF.

GPU map jest więc modelem mieszanym: CPU raster mapy, GPU upload/resize/blend.

## B. Real z-order

Enabled order z `def_layout.json`:

| order | indicator |
|---:|---|
| 1 | time_block |
| 2 | fit_cadence_text |
| 3 | fit_enhanced_speed_text |
| 4 | fit_heart_rate_text |
| 5 | fit_temperature_text |
| 6 | iso_text |
| 7 | exposure_text |
| 8 | temp_text |
| 9 | track_map |
| 10 | fit_battery_text |

CPU daje dokładnie `A → map → B`; kolejność nie jest sortowana po pozycji ani typie widgetu.

## C. Unsafe-layout condition

Plik `src/ffmpeg/amd_native_exporter.py`, funkcja `_map_gpu_layout_safe(layout)`. Budowana jest lista `enabled_keys`; GPU map jest safe tylko gdy `enabled_keys[-1] == "track_map"`. W przeciwnym razie zwracany jest powód `track_map is not the last rendered indicator ... GPU map-on-top would change z-order`.

Decyzja następuje w `export_amd_native_d3d11`: `AMD_MAP_PATH=GPU` plus unsafe guard daje log `GPU_MAP_UNSAFE_LAYOUT` i aktywny `CPU_REFERENCE`.

## D. Why GPU map changes z-order

GPU map jest wykonywany jako końcowy osobny native blend pass. CPU HUD ma już zawartość zarówno sprzed, jak i po mapie, a późniejszy GPU map kładzie się nad całością. Dla `A → map → B` wynik byłby `A+B → map`, więc zmieniłby warstwowanie. Obecny fallback chroni poprawność obrazu.

## E. Conditional visibility

Potwierdzona potencjalna false-unsafe classification:

| element po mapie | enabled | value/available | rendered | guard |
|---|---:|---|---:|---|
| fit_battery_text | yes | None/unavailable | no | nadal blokuje GPU |

Guard bada statyczne `enabled`, nie faktyczną rasteryzację. Dynamic FIT skonfigurowany, lecz niedostępny, również pozostaje elementem planu statycznego.

## F. Chart GPU_SPLIT

Chart capture jest sprawdzany bboxowo. GPU_SPLIT używa CPU-generated chart RGBA, static layer oraz dynamic cursor/value tiles. Chart może wejść na GPU tylko bez rotacji i bez overlapu z innymi widgetami oraz mapą. Dzięki temu jego blend jest ograniczony do bezpiecznego regionu i nie łamie z-order.

To jest częściowy split-layer model, ale obecnie nie jest uogólniony na mapę.

## G. Gauge

Gauge ma analogiczny bbox guard i jest blendowany przed GPU mapą. W realnym probe: `AMD_GAUGE_PATH=GPU`, bbox `(1544,1632,648,648)`, reason `gauge z-order disjoint -> GPU safe`. Gauge może być pomiędzy innymi widgetami, jeśli jest rozłączny. Mapa nie korzysta z tego modelu, bo jej aktualny pass jest końcowy.

## H. Candidate solutions

| rozwiązanie | z-order | ryzyko | ocena |
|---|---|---|---|
| ordered GPU compositor | pełny | wysokie | zbyt szeroki |
| CPU below → GPU map → CPU above | poprawny | średnie | najmniejszy lokalny kandydat |
| generalized ordered layers | pełny | wysokie | przyszły model |
| map texture w ordered pipeline | poprawny | średnie | możliwe |
| reuse GPU_SPLIT dla mapy | poprawny warunkowo | średnie | zgodny z istniejącą architekturą |

## I. Smallest safe candidate

Rekomendowany przyszły kierunek to `CPU_BELOW_MAP → GPU_MAP → CPU_ABOVE_MAP`, bez przenoszenia mapy na koniec layoutu. Generalized compositor byłby potrzebny dopiero dla wielu map lub wielu nakładających się GPU indicators.

## J. Runtime real layout

Krótki AMD Native probe na `GX030120.MP4`:

| ustawienie | wynik |
|---|---|
| AMD_MAP_PATH requested | GPU |
| AMD_MAP_PATH effective | CPU_REFERENCE |
| reason | track_map is not last; last=fit_battery_text |
| AMD_CHART_PATH | GPU_SPLIT |
| AMD_GAUGE_PATH | GPU |
| AMF output | 6 |
| dropped | 0 |
| HW decode proof | YES |

## K. Runtime diagnostic map-last

Na kopii layoutu wyłącznie w pamięci przeniesiono `track_map` na koniec. Wynik: `AMD_MAP_PATH effective=GPU`, map geometry `dst=(3035,137), src=692x692, out=691x691`, GPU charts/gauge active, AMF output 6, dropped 0, HW decode proof YES. Potwierdza to, że blockerem jest guard z-order, nie DLL/GPU/track/geometria.

## L. CPU_REFERENCE vs GPU parity

Dla canvasu 960×540:

| pomiar | wartość |
|---|---|
| CPU_REFERENCE bbox | `(759,34,173,173)` |
| GPU map destination | `(759,34,173,173)` |
| GPU working image | `173x173` |

Final GPU użył working source `692x692` i output `691x691`, zgodnie ze skalą 3840×2160. Pixel-identical A/B readback nie był wykonywany; kod posiada osobny diagnostic readback.

## M. Performance baseline

| path | obserwacja |
|---|---|
| CPU_REFERENCE | compose_overlay avg około 40,5 ms; mapa w pełnym Pillow HUD |
| GPU map | compose avg około 15,5 ms; map CPU preparation około 2,8 ms; native upload około 0,8 ms; resize/blend submit około 0,08 ms |

Wall-clock probe był zdominowany przez audio mux.

## N. Transfer/synchronization/alpha

CPU_REFERENCE uploaduje pełny/dirty RGBA HUD. GPU path uploaduje map texture oraz HUD bez mapy; nie wykonuje produkcyjnego GPU→CPU readback. D3D11 texture copy i VideoProcessor obsługują resample/blend, a native flush/VP completion synchronizuje przed AMF. GPU chart/gauge/map używają straight-alpha RGBA over; map resample stosuje premultiplied-alpha resampling dla zgodności z Pillow LANCZOS.

## O. Existing tests

Uruchomiono bez zmian: `test_gpu_compositor.py`, `test_map_sync.py`, `test_amd_native_etap1.py`, `test_amd_native_etap2.py`, `test_amd_native_etap3.py`, `test_amd_native_etap5b.py` — **60 passed**. Nie znaleziono osobnego testu `GPU_MAP_UNSAFE_LAYOUT`/ordered map compositing.

## P. Existing AMD failure

`tests/test_amd_native_etap4.py` jest **UNRELATED**: failure dotyczy oczekiwanego ABI 4 przy aktualnym ABI 8, nie z-order ani map guardu.

## Q. Confirmed issues

1. **MEDIUM — TRACK_MAP_ONLY false-unsafe**: `_map_gpu_layout_safe` traktuje enabled `fit_battery_text` z value `None` jako blokujący element, mimo że compositor go nie rasteruje.
2. **MEDIUM — TRACK_MAP_ONLY ordered GPU limitation**: map removal from CPU layout plus final GPU map blend nie obsługuje elementów po mapie.

## R. Recommended ETAP 7B

`ETAP 7B — targeted ordered map compositing`: dynamiczna klasyfikacja visible/rasterized indicators oraz split CPU-before-map → GPU-map → CPU-after-map, z zachowaniem insertion order. Nie implementowano tego w ETAPIE 7A.

**ETAP 7A zakończony.**
