# TeleM — NVIDIA ETAP 5B.5: Adaptive HUD Geometry + Region Count

## A. Baseline

Audyt wykonano na aktualnym repozytorium po ETAPIE 5B.4, dla:

- `GX030120.MP4`, 5400 klatek, 1920×1080 HUD, 29.97 FPS;
- `Poranna_jazda_na_rowerze.fit`;
- NVIDIA, NVDEC → CUDA → `overlay_cuda` → HEVC NVENC;
- `workers=4`, `MAX_IN_FLIGHT=8`;
- próg `FULL_FRAME=70%`.

Baseline po 5B.4: MAX3, atlas `1828×854`, `75.285%`, `5.955 MB/frame`, więc wybierany był `FULL_FRAME`.

## B. Geometry MAX 3–6

Wartości po precise text bbox i wykluczeniu phantom bboxów:

| Geometry | Regions | Members / charakterystyka | Atlas | Area | MB/frame | Packing efficiency |
|---|---:|---|---:|---:|---:|---:|
| MAX3, GRID OFF | 3 | bottom charts+gauge; right map/text; left time+texts | 1828×854 | 75.285% | 5.955 | 50.3% |
| MAX4, GRID OFF | 4 | osobny fit temperature; right map; bottom; left | 1898×768 | 70.296% | 5.561 | 51.7% |
| MAX5, GRID OFF | 5 | dodatkowe rozdzielenie małych grup | 1828×582 | 51.307% | 4.058 | 68.6% |
| MAX6, GRID OFF | 6 | dalsze rozdzielenie grup | 1240×668 | 39.946% | 3.160 | 85.6% |

MAX4 bez geometrii pozostaje minimalnie ponad progiem. MAX5 schodzi niżej, ale wymaga dodatkowego regionu.

## C. GRID OFF / 8 / 16

| Grid | MAX3 area | MAX4 area | MAX5 area | MAX6 area |
|---|---:|---:|---:|---:|
| OFF | 75.285% | 70.296% | 51.307% | 39.946% |
| 8 px | 75.648% | 70.257% | 51.194% | 40.120% |
| 16 px | 74.566% | **69.821%** | 48.843% | 39.165% |

GRID8 nie przechodzi progu z MAX4. GRID16 + MAX4 przechodzi próg i jest prostsze od MAX5/MAX6.

## D. Bottom cluster optimization

Nie zmieniano rozmiarów chartów ani gauge. GRID16 przesunął kotwice bottom cluster do najbliższych pozycji siatki:

- `fit_cadence_text`: +1.34 px X, +6.11 px Y;
- `fit_enhanced_speed_text`: −6.08 px X, −2.05 px Y;
- `fit_heart_rate_text`: +7.49 px X, +4.60 px Y.

Wynikowy bottom region ma `1828×326` zamiast baseline’owego `1824×332`. Zysk wynika z połączenia snapowania i rozdzielenia regionów przez MAX4, nie ze zmiany rendererów.

## E. Text/time cluster optimization

Lewy region po GRID16 ma `64×514` i pozostaje osobnym regionem. Pozycje `time_block`, `iso_text`, `exposure_text` i `temp_text` zostały snapnięte maksymalnie o 7.47 px. Precise text bbox pokrywał rzeczywisty alpha bbox przez wszystkie 5400 klatek: `0 violations`.

Phantom bboxy nadal są wyłączone z transportu:

```text
fit_battery_pct_text
fit_battery_text
fit_solar_pct_text
```

## F. Region-count tradeoff

MAX3 nie przechodzi progu w żadnym sprawdzonym wariancie. MAX4+GRID16 jest najmniejszym zestawem regionów schodzącym poniżej 70%. MAX5/MAX6 zmniejszają atlas bardziej, ale zwiększają liczbę gałęzi CUDA bez potrzeby dla celu tego etapu.

## G. CUDA benchmark

NO-OP benchmark: 5400 klatek, ten sam input, transparentny atlas, NVDEC → CUDA atlas graph → NVENC → null, 3 uruchomienia na wariant.

| Candidate | Median FPS | Median elapsed | Avg SM | Avg NVENC | Avg NVDEC |
|---|---:|---:|---:|---:|---:|
| MAX3 + GRID OFF | 377.20 | 14.316 s | 54.6% | 69.4% | 94.4% |
| MAX4 + GRID OFF | 373.16 | 14.471 s | 57.2% | 70.2% | 95.6% |
| **MAX4 + GRID16** | **409.97** | **13.172 s** | 48.5% | 76.1% | 91.0% |

Średnie GPU są diagnostyczne i zależą od próbkowania `nvidia-smi`; decyzję oparto przede wszystkim na medianie czasu/FPS i geometrii.

## H. Wybrany wariant

Wdrożono:

```text
NVIDIA_HUD_MAX_REGIONS = 4
NVIDIA_HUD_GRID_PX = 16
```

Snapowanie działa wyłącznie na runtime’owej kopii layoutu w ścieżce NVIDIA. `def_layout.json` nie został zmieniony. AMD i pozostałe backendy zachowują dotychczasową geometrię.

## I. Zmiany pozycji

| Indicator | Old X/Y px | New X/Y px | Delta X | Delta Y | Grid |
|---|---:|---:|---:|---:|---:|
| time_block | 30.99 / 33.51 | 32 / 32 | +1.01 | −1.51 | 16 |
| fit_cadence_text | 382.66 / 921.89 | 384 / 928 | +1.34 | +6.11 | 16 |
| fit_enhanced_speed_text | 934.08 / 978.05 | 928 / 976 | −6.08 | −2.05 | 16 |
| fit_heart_rate_text | 1528.51 / 923.40 | 1536 / 928 | +7.49 | +4.60 | 16 |
| fit_temperature_text | 1650.05 / 423.47 | 1648 / 416 | −2.05 | −7.47 | 16 |
| iso_text | 33.41 / 450.47 | 32 / 448 | −1.41 | −2.47 | 16 |
| exposure_text | 32.45 / 492.80 | 32 / 496 | −0.45 | +3.20 | 16 |
| temp_text | 31.68 / 534.38 | 32 / 528 | +0.32 | −6.38 | 16 |
| track_map | 1689.98 / 240.95 | 1696 / 240 | +6.02 | −0.95 | 16 |

Nie zmieniano skali, z-order ani rendererów. Phantom indicators zostały snapnięte w kopii layoutu, ale nie są transportowane.

## J. Atlas przed/po

```text
before: MAX3, 1828×854, 75.285%, 5.955 MB/frame, FULL_FRAME
after:  MAX4+GRID16, 1900×762, 69.821%, 5.523 MB/frame, MULTI_REGION_ATLAS
```

Po wdrożeniu atlas ma 30.2% mniej powierzchni niż pełny canvas i SHM około 44.2 MB dla 8 slotów.

## K. Visual correctness

- 7 punktów kontrolnych w całym timeline: brak clippingu na granicach canvasu;
- precise text bbox: 0 naruszeń przez 5400 klatek;
- zachowane phantom/source isolation i pełne dane FIT;
- testy rotacji 0/90/180/270 oraz NVIDIA ROT180 CUDA fast path: zaliczone w istniejącym zestawie testów;
- testy: `34 passed` (`test_nvidia_etap5b4_precise_text_bbox.py` + `test_video_helpers.py`).

Przesunięcia są celowe, mieszczą się w limicie GRID16 i nie zmieniają treści, stylu ani skali HUD.

## L. Produkcyjny benchmark 3×

Pełny eksport `GX030120.MP4` + FIT, ustawienia identyczne dla wszystkich 3 uruchomień:

| Run | HUD mode | Atlas | FRAME_PIPELINE | PRODUCTION_TOTAL | REAL_EXPORT_FPS | write avg | write p95 |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | MULTI_REGION_ATLAS, 4 | 1900×762, 69.8% | 29.676 s / 181.96 FPS | 31.299 s | 172.5 | 2.12 ms | 3.90 ms |
| 2 | MULTI_REGION_ATLAS, 4 | 1900×762, 69.8% | 29.761 s / 181.44 FPS | 31.189 s | 173.1 | 2.14 ms | 4.10 ms |
| 3 | MULTI_REGION_ATLAS, 4 | 1900×762, 69.8% | 29.449 s / 183.39 FPS | 30.801 s | 175.3 | 2.06 ms | 3.83 ms |
| **median** | **MULTI_REGION_ATLAS, 4** | **1900×762, 69.821%** | **181.96 FPS** | **31.189 s** | **173.1 FPS** | **2.12 ms** | **3.90 ms** |

Względem podanego baseline’u `FRAME_PIPELINE≈111.7 FPS`, `REAL_EXPORT≈94.2 FPS`, nowy wariant jest odpowiednio około `1.63×` i `1.84×` szybszy. Różnica obejmuje również zmianę z FULL_FRAME na atlas po 5B.4; benchmarki pozostają porównaniem tego samego materiału i ustawień produkcyjnych.

## M. Nowy bottleneck

Po zejściu poniżej progu transport nie wymusza już FULL_FRAME. Pozostały koszt jest po stronie producenta HUD/Pillow, synchronizacji 4 workerów i właściwego CUDA graph; GPU nie jest ograniczeniem w sposób wskazany przez NO-OP benchmark. Dalsze zwiększanie liczby regionów zmniejszyłoby bufor, ale nie jest obecnie uzasadnione kosztowo ani prostotą.

## Zmienione pliki

- `src/ffmpeg/streaming.py` — runtime NVIDIA GRID16 i MAX4;
- `Raporty/RAPORT_NVIDIA_ETAP_5B5_ADAPTIVE_GEOMETRY.md` — raport etapu.

Pliki `def_layout.json`, telemetry precompute, chart renderer, NVDEC/NVENC, workers i `MAX_IN_FLIGHT` nie zostały zmienione.

## Konkluzja

Najlepszy wynik dała kombinacja **MAX4 + GRID16**. Nowy atlas ma **69.821%** i **5.523 MB/frame**. Przesunięcia wskaźników wyniosły maksymalnie **7.49 px**. HUD pozostaje wizualnie równoważny, bez clippingu i z zachowaną treścią/skalami. Nowy rzeczywisty medianowy `FRAME_PIPELINE` na `GX030120` wynosi **181.96 FPS**. Dalsze zwiększanie liczby regionów nie ma obecnie sensu.

