# TeleM — NVIDIA ETAP 5B.4: Precise Text BBox + Phantom BBox

Data: 2026-08-20  
Status: **ZAKOŃCZONY — implementacja ograniczona do planera text bbox i phantom transport geometry**

## A. Stary text bbox contract

Materiał: `Video/GX030120.MP4`, `Video/Poranna_jazda_na_rowerze.fit`, `def_layout.json`, canvas `1920×1080`.

Przed zmianą planner text indicatorów używał szerokich stałych minimów, między innymi:

```text
text_w = max(12% canvas_w, fs * 12)
text_h = max(6% canvas_h, fs * 3 + 20)
position = (px - 20, py - 20)
```

`time_block` używał osobnej heurystyki około `424×169`. Baseline:

```text
atlas = 1828×978
area  = 86.216%
slot  = 6.82 MB/frame
mode  = FULL_FRAME, ponieważ 86.216% > 70%
```

## B. Nowy precise bbox contract

Planner NVIDIA otrzymuje jednorazowy kontekst tekstowy z aktualnie wybranych źródeł. Dla każdego aktywnego `form="text"`:

1. zbierane są wartości z całego dostępnego zakresu źródłowego;
2. generowane są bezpieczne kandydaty formatted value, w tym min/max, zero i wartości ze źródła;
3. istniejący `render_value_indicator()` mierzy lokalny raster każdego kandydata;
4. wybierany jest największy rozmiar;
5. dodawany jest tylko margines `2 px` z każdej strony;
6. dla `90°/270°` wymiary są zamieniane, bez zmiany anchor semantics.

Nie powstał drugi renderer tekstu. Pomiar korzysta z istniejącego dispatchera i `_render_text_indicator`.

`time_block` jest mierzony przez istniejący `render_time_block()` dla bezpiecznych wariantów daty/czasu (`0000/8888/9999`), bez zmiany jego wyglądu.

## C. Full-timeline text sizing

Planner nie wykonuje pomiaru w hot path. Wartości są analizowane jednorazowo przed planowaniem transportu z FIT, GPMF i GPX, zgodnie z wybranym źródłem.

Dodatkowa walidacja objęła wszystkie `5400` klatek. Dla aktywnych textów odnotowano `0` naruszeń declared bbox.

## D. Source / None / zero semantics

Zachowano izolację źródeł:

```text
fit_*_text + source FIT + brak pola FIT => brak danych
GPMF/GPX nie przywraca wskaźnika FIT
```

Wartość `0.0` jest traktowana jako dostępna. Test z FIT cadence zawierającym wyłącznie zero nie klasyfikuje wskaźnika jako phantom. `None`/brak próbek jest odróżniany od poprawnego zera.

## E. Phantom bbox logic

Phantom exclusion działa wyłącznie w plannerze transport geometry. Nie zmienia layoutu i nie ustawia `enabled=False`.

Dla aktualnego eksportu bez danych FIT wykluczono:

```text
fit_battery_text
fit_battery_pct_text
fit_solar_pct_text
```

Gdy dane pojawią się w następnym eksporcie, bbox zostanie automatycznie przywrócony. `track_map` nie jest wykluczany: posiada dane GPS, a wcześniejszy brak obrazu z rendererera mapy pozostaje poza zakresem tego etapu.

## F. Per-indicator bbox przed/po

| Indicator | Stary declared bbox | Nowy declared bbox | Zmiana |
|---|---:|---:|---|
| `time_block` | `(11,14,424,169)` | `(29,32,60,61)` | precise raster |
| `fit_temperature_text` | `(1630,403,290,141)` | `(1648,421,101,19)` | precise raster |
| `iso_text` | `(13,430,364,141)` | `(31,448,60,17)` | precise raster |
| `exposure_text` | `(12,473,364,141)` | `(30,491,60,18)` | precise raster |
| `temp_text` | `(12,514,364,141)` | `(30,532,64,17)` | precise raster |
| `fit_battery_text` | `(1630,448,290,141)` | excluded | confirmed phantom |
| `fit_battery_pct_text` | `(942,124,364,141)` | excluded | confirmed phantom |
| `fit_solar_pct_text` | `(940,66,364,141)` | excluded | confirmed phantom |

Nie zmieniono declared geometry wykresów, gauge ani mapy.

## G. Alpha coverage

Checkpoints `0%, 10%, 25%, 50%, 75%, 90%, 100%` oraz pełny zakres `5400` klatek:

| Indicator | Full-timeline alpha union | Declared bbox | Violations |
|---|---:|---:|---:|
| `time_block` | `(31,34,56,57)` | `(29,32,60,61)` | 0 |
| `fit_temperature_text` | `(1650,422,97,15)` | `(1648,421,101,19)` | 0 |
| `iso_text` | `(33,450,50,13)` | `(31,448,60,17)` | 0 |
| `exposure_text` | `(32,493,56,14)` | `(30,491,60,18)` | 0 |
| `temp_text` | `(32,534,60,13)` | `(30,532,64,17)` | 0 |

## H. Rotation

Testy precise bbox i alpha coverage przechodzą dla `0°`, `90°`, `180°` i `270°`. W szczególności `180°` zachowuje bezpieczne wymiary po zamianie szerokości/wysokości. Nie zmieniono anchorów ani transformacji ROT180 CUDA.

## I. Pixel parity FULL_FRAME

Zmiana dotyczy wyłącznie planowania transportu. Pre-encode RGBA pozostaje taki sam.

| Frame | max_diff | different_pixels |
|---:|---:|---:|
| 0 | 0 | 0 |
| 1350 | 0 | 0 |
| 2700 | 0 | 0 |
| 4050 | 0 | 0 |
| 5399 | 0 | 0 |

## J. Atlas reconstruction parity

Rekonstrukcja atlasu do canvasu `1920×1080` jest pixel-identical dla `0%, 25%, 50%, 75%, 100%`:

```text
max_diff = 0
different_pixels = 0
```

## K. Atlas geometry przed/po

| Wariant | Atlas | Area | Regions |
|---|---:|---:|---:|
| PRZED | `1828×978` | `86.216%` | 3 |
| PO | `1828×854` | `75.285%` | 3 |

Nowe regiony:

```text
R0: source=(44,748,1824×332), atlas=(0,0)
R1: source=(1466,118,448×322), atlas=(0,336)
R2: source=(28,32,66×518), atlas=(452,336)
```

## L. Transport przed/po

```text
PRZED: atlas slot = 1828×978×4 = 6.82 MB/frame
PO:    atlas slot = 1828×854×4 = 5.96 MB/frame
SHM PO ≈ 47.6 MB dla 8 slotów
redukcja względem pełnego 7.91 MB = 24.7%
```

Ponieważ `75.285% > 70%`, produkcyjny wybór nadal pozostaje `FULL_FRAME`. Nie zmieniono progu `70%` ani `MAX_HUD_REGIONS=3`.

## M. Benchmark 3×

Nie wykonano trzech pełnych eksportów produkcyjnych. Specyfikacja wymaga ich uruchomienia tylko wtedy, gdy atlas osiągnie `<=70%` i automatycznie aktywuje się atlas. Ten warunek nie został spełniony.

Nie raportuję nowych `FRAME_PIPELINE`/`PRODUCTION_TOTAL` jako pomiaru po zmianie, ponieważ aktywna ścieżka nadal jest `FULL_FRAME`.

## N. Pozostałe największe bbox waste

Po usunięciu małych text waste największym ograniczeniem pozostaje niezmieniony dolny klaster:

```text
fit_cadence_text + fit_heart_rate_text + fit_enhanced_speed_text
declared width = 1824 px
```

To nadal wymusza szerokość atlasu. Następne źródła kosztu to declared geometry chart/gauge/map oraz limit 3 regionów, ale ich zmiana jest poza ETAPEM 5B.4.

## O. Rekomendacja następnego etapu

Precise text bbox dał:

```text
86.216% → 75.285%
redukcja powierzchni: 10.931 punktu procentowego
redukcja atlas area: 12.7%
```

Atlas nadal przekracza `70%`. Następny pojedynczy etap powinien zdecydować, czy audytować kolejną kategorię declared geometry, czy przejść do osobnego etapu `MAX_HUD_REGIONS=4/5/6`. Nie wdrażam tej rekomendacji tutaj.

## Zmienione pliki

- `src/ffmpeg/command_builder.py` — one-shot text geometry context, precise text/time bbox, phantom transport exclusion hook.
- `src/ffmpeg/streaming.py` — NVIDIA-only przekazanie kontekstu planera.
- `tests/test_nvidia_etap5b4_precise_text_bbox.py` — regresje text geometry, rotation, source isolation, zero i phantom.

Artefakt walidacyjny: `scratch/etap5b4_validation.json`.

Nie zmieniono layoutu użytkownika, chart/gauge/map rendererów, telemetry precompute, clustering, shelf packera, `MAX_HUD_REGIONS`, progu `70%`, CUDA graph ani NVENC/NVDEC.
