# TeleM — NVIDIA ETAP 5C: Direct-Region HUD Rendering

## A. Stary CPU HUD producer

Aktualny call graph przed zmianą:

```text
stream_overlay_to_ffmpeg → ProcessPoolExecutor → render_frame_shm_job
→ render_overlay_frame → compose_overlay(1920×1080)
→ Image.crop regionów → Image.new atlasu → Image.paste
→ np.asarray → np.copyto do SHM
```

Plan geometrii pozostał identyczny jak po 5B.5: MAX4, GRID16, atlas `1900×762`, `69.821%`.

## B. Nowa architektura Direct-Region

Rozszerzono istniejący `compose_overlay` o `target_image`, `coordinate_origin` i `render_keys`. Każdy region renderuje swoje indicatory bezpośrednio do wspólnego atlasu. Nie powstał drugi renderer indicatorów i nie zmieniono rendererów chart/gauge/map/text/time/bar.

Normalna ścieżka NVIDIA nie tworzy już pośredniego rastra `1920×1080`.

## C. Coordinate transform

Dla `(source_x, source_y, atlas_x, atlas_y, w, h)` używany jest:

```text
origin = (source_x - atlas_x, source_y - atlas_y)
target_x = global_x - origin_x
target_y = global_y - origin_y
```

Renderer nadal otrzymuje logiczne `canvas_w=1920`, `canvas_h=1080`, więc zachowuje istniejące kontrakty anchorów i rozmiarów.

## D. Region assignment

| Region | Source bbox | Atlas bbox | Members |
|---:|---|---|---|
| 0 | `(1646,414,102,20)` | `(0,0,102,20)` | `fit_temperature_text` |
| 1 | `(1472,118,448,244)` | `(106,0,448,244)` | `track_map` |
| 2 | `(46,754,1828,326)` | `(0,248,1828,326)` | `fit_cadence_text`, `fit_enhanced_speed_text`, `fit_heart_rate_text` |
| 3 | `(30,30,64,514)` | `(1832,248,64,514)` | `time_block`, `iso_text`, `exposure_text`, `temp_text` |

Phantom keys nadal są wyłączone z transportu: `fit_battery_pct_text`, `fit_battery_text`, `fit_solar_pct_text`.

Ownership jest sprawdzany diagnostycznie; przy niepowodzeniu zostaje użyty legacy `FULL_CANVAS → CROP → PACK`. Dla badanego layoutu fallback nie wystąpił.

## E. Z-order

W obrębie regionu zachowana jest kolejność `layout["indicators"]`, taka sama jak w `compose_overlay`. Regiony nie nachodzą na siebie. ROT180 wykonuje ten sam obrót regionu co legacy producer.

## F. Buffer allocation

Direct tworzy atlas `1900×762 RGBA` oraz lokalne rastry generowane przez istniejące renderery. Nie tworzy pełnego canvasa. Reuse atlasu nie wdrożono, ponieważ świeży atlas był bezpieczniejszy i nie był głównym hotspotem.

## G. PIL / NumPy analysis

Aktualnie:

```text
np.asarray(atlas): shape=(762,1900,4)
C_CONTIGUOUS=True, WRITEABLE=False, OWNDATA=False, base=bytes
```

`np.asarray` nie daje writable bufora współdzielonego z Pillow; `np.copyto` do SHM pozostaje wymagane. Nie zastosowano hacku Pillow/SHM.

## H. Fallback

Proces główny loguje raz:

```text
[NVIDIA] HUD producer: DIRECT_REGION
```

W przypadku błędu ownership używany jest:

```text
[NVIDIA] HUD producer: LEGACY_FULL_CANVAS fallback: region ownership assertion failed
```

## I. Pixel parity

Legacy i Direct porównano przed HEVC dla klatek `0, 540, 1350, 2700, 4050, 4860, 5399`.

W każdym przypadku:

```text
max_diff = 0
different_pixels = 0
```

Identyczny wynik uzyskano dla ROT180 CUDA fast path.

## J. Worker profiler przed/po

Świeży pomiar: 300 steady-state frames po 40 warm-up, z lokalną konwersją/copy odpowiadającą SHM.

| Phase | BEFORE avg ms | AFTER avg ms | Reduction |
|---|---:|---:|---:|
| worker-like total | 8.601 | 7.835 | −8.9% |
| `pillow.crop` | 0.606 | 0.190 | −68.7% |
| `pillow.paste` | 0.348 | 0.097 | −72.0% |
| `pillow.alpha_composite` | 1.786 | 1.748 | −2.1% |

Worker-like mediana: `8.394 → 7.654 ms`; p95: `10.469 → 9.255 ms`. Zysk wynosi `0.766 ms/frame`. Kryterium `worker -20%` nie zostało osiągnięte.

## K. Benchmark 3×

Pełne eksporty `GX030120.MP4` + FIT, 5400 klatek, workers=4, MAX_IN_FLIGHT=8, ten sam atlas i ustawienia NVENC/NVDEC:

| Run | FRAME_PIPELINE | FPS | PRODUCTION_TOTAL | REAL_EXPORT_FPS | write avg | write p95 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 27.278 s | 197.8 | 28.921 s | 186.7 | 2.59 ms | 4.78 ms |
| 2 | 26.558 s | 203.3 | 27.985 s | 193.0 | 2.89 ms | 7.37 ms |
| 3 | 26.481 s | 203.9 | 27.881 s | 193.7 | 3.19 ms | 7.38 ms |
| **median** | **26.558 s** | **203.3** | **27.985 s** | **193.0** | **2.89 ms** | **7.37 ms** |

Względem 5B.5: `FRAME_PIPELINE 181.96 → 203.3 FPS (+11.8%)`, `REAL_EXPORT 173.1 → 193.0 FPS (+11.5%)`. Preferowany cel `>210 FPS` i minimalne `+15%` nie zostały osiągnięte; nie dodawano kolejnej optymalizacji.

## L. CPU/GPU utilization

Direct usuwa CPU koszt pełnego canvasa, cropów i atlas repack. CUDA graph oraz NVENC/NVDEC pozostały bez zmian. Pozostały koszt jest przede wszystkim po stronie renderowania indicatorów i alpha compositingu. `pillow.alpha_composite` pozostaje pojedynczym największym mierzonym hotspotem około `1.75 ms/frame`.

## M. Nowy bottleneck

Po usunięciu pełnego canvasa wąskim gardłem jest właściwy rendering chart/gauge oraz alpha compositing Pillow, nie transport atlasu.

## Full timeline safety

Direct wykonano dla wszystkich 5400 klatek bez błędu ownership, clippingu, `queue.Empty`, `BufferError` ani zmiany rozmiaru atlasu. Existing precise text bounds i parity pokryły clipping oraz pełną historię chartów z tego samego precomputed cache.

Testy regresyjne: `34 passed`.

## Zmienione pliki

- `src/indicators/compositor.py` — target atlas, coordinate origin, render keys;
- `src/ffmpeg/frame_renderer.py` — Direct-Region producer, ownership i fallback;
- `src/ffmpeg/streaming.py` — przekazanie planu i jednorazowy log;
- `Raporty/RAPORT_NVIDIA_ETAP_5C_DIRECT_REGION_RENDERING.md` — raport.

Nie zmieniono MAX4/GRID16, clustering, shelf packera, telemetry precompute, rendererów indicatorów, workers, MAX_IN_FLIGHT, FFmpeg graph ani parametrów NVENC/NVDEC.

## Konkluzja

Pełny canvas `1920×1080` usunięto z normalnej ścieżki NVIDIA Direct-Region. Usunięto średnio `0.766 ms/frame` z worker-like jobu. Atlas Direct jest bit-identyczny z legacy dla sprawdzonych punktów oraz ROT180. Nowy medianowy `FRAME_PIPELINE` to `203.3 FPS`. Największym hotspotem CPU pozostaje `pillow.alpha_composite` oraz rendering chart/gauge.

