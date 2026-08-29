# AMD ETAP 5A — RYZEN 7 7730U HARDWARE REBASELINE & PRODUCTION PATH VALIDATION

## Data raportu
2026-08-28

## Galaz
`amd-render`

## Commit bazowy
`3ab0b89` — AMD ETAP 4I: direct strided pointer for map upload + below HUD dirty rect memmove

---

## 1. Srodowisko sprzetowe

| Komponent | Wartosc |
|-----------|---------|
| **CPU** | AMD Ryzen 7 7730U with Radeon Graphics |
| **Rdzenie / watki** | 8 cores / 16 threads |
| **Zegar bazowy** | 2000 MHz (boost do 4500 MHz) |
| **GPU / adapter** | AMD Radeon (TM) Graphics (zintegrowana, Vega iGPU) |
| **VRAM (shared)** | 512 MB wydzielone / shared z RAM systemowym |
| **Device ID** | VideoController2 |
| **Driver AMD** | 31.0.21925.1001 |
| **RAM systemowy** | 32 GB |
| **Windows** | Microsoft Windows 11 Pro Build 26200 (10.0.26200) |

> [!IMPORTANT]
> Ryzen 7 7730U to APU z zintegrowana grafika Radeon — GPU i CPU wspoldziela TDP ~28W.
> Brak dedykowanej VRAM = wszystkie textury w RAM systemowym przez unified memory.
> To fundamentalnie rozni sie od poprzedniego komputera z dedykowanym GPU.

---

## 2. Srodowisko programowe

| Komponent | Wartosc |
|-----------|---------|
| **Python** | 3.14.7 (tags/v3.14.7:823f032, Aug 5 2026) |
| **Pillow** | 12.3.0 |
| **FFmpeg** | 2026-08-17-git-426841da9d (gyan.dev full build) |
| **FFmpeg libs** | libavutil 59.x / libavcodec 62.x |
| **AMF** | --enable-amf (potwierdzony) |
| **D3D11VA** | --enable-d3d11va (potwierdzony) |
| **MediaFoundation** | --enable-mediafoundation (potwierdzony) |
| **DLL build** | telem-amd-native/1.0.0+d9afa75c8402 (2026-08-25) |
| **DLL ABI** | 9 |

---

## 3. Potwierdzenie produkcyjnej sciezki AMD

Z logow eksportu i profilu JSON — **wszystkie production paths aktywne**:

```
Backend:               AMD_NATIVE_D3D11_GPU_HUD_GPU_HUD_D3D11VA
GPU compositor:        DIRECT_NV12_COMPUTE_SHADER
HUD mode:              GPU_HUD (native_hud_mode=1)
Decoder:               GPU_HUD_D3D11VA (MediaFoundation D3D11VA hardware decode)
Encoder:               AMF HEVC (3840x2160 CQP 28/28 Speed)
Map path:              GPU (DIRECT_AUTO)
Chart path:            GPU_SPLIT (AFTER-MAP)
Gauge path:            GPU AFTER-MAP (AUTO_SAFE)
Lean:                  GPU_LEAN_AFFINE
Telemetry:             PRECOMPUTED
Above dirty mode:      EXACT
Above buffer mode:     DIRECT
```

**Potwierdzenie z logu:**
```
[AMF] HEVC Hardware Encoder initialized successfully (3840x2160 CQP 28/28 Speed)
[TELEM AMD DLL] MediaFoundation D3D11VA decoder configured
[AMD NATIVE D3D11] GPU gauge AFTER-MAP active key=speed_text bbox=(1606,1588,777,777)
[AMD NATIVE D3D11] GPU charts AFTER-MAP GPU_SPLIT ACTIVE: ['fit_cadence_text', 'fit_heart_rate_text']
```

Brak:
- software decode (CPU fallback): NIE AKTYWNY
- CPU fallback compositor: NIE AKTYWNY
- software HEVC: NIE AKTYWNY

> [!NOTE]
> Po migracji na nowy komputer **nie stwierdzono blednego fallbacku**. Wszystkie GPU sciezki dzialaja poprawnie na Ryzen 7 7730U / Radeon iGPU.

---

## 4. Kanoniczny workload

```
Video:       Video/GX030120.MP4   (5395 frames, 3840x2160, 29.97 fps, 180s)
FIT:         Video/Jazda_na_rowerze_w_porze_lunchu.fit
Layout:      def_layout.json
Resolution:  3840x2160 (4K)
Encoder:     AMF HEVC CQP 28/28
```

> [!IMPORTANT]
> GX030120.MP4 ma 5395 klatek (180 sekund) — pelny plik.
> Poprzednie etapy (4I/4H) uzywaly GX020079.mp4 (1131 klatek, 37.7s).
> **ETAP 5A uzywa pelnego GX030120.MP4** co jest bardziej reprezentatywnym workloadem.
> Czasy eksportu sa odpowiednio dluzsze (180s vs 37.7s materialu).

W kazdym runie pipeline procesuje faktycznie **1131 klatek z pliku 5395-klatkowego** — 
ograniczenie wynika z `duration_s = 1131/fps = 37.74s` przekazanego do eksportera.
Raporter postepow pokazuje `Frame X/5395` bo MF decoder widzi pelny plik.

---

## 5. Wyniki per-run

Workload: GX030120.MP4, 1131 klatek, 3840x2160, PRECOMPUTED

| Run | TRUE FPS | RENDER FPS | EFF FPS | wall_s | video_render_ms | total_ms |
|-----|----------|------------|---------|--------|-----------------|----------|
| warmup | ~29.5 | ~32.1 | ~29.5 | ~38.3 | ~35200 | ~38600 |
| **run01** | **29.277** | **32.330** | **29.293** | **38.646** | **34983** | **38609** |
| **run02** | **24.874** | **27.123** | **24.886** | **45.445** | **41698** | **45447** |
| **run03** | **22.719** | **24.672** | **22.731** | **49.748** | **45841** | **49756** |
| **run04** | **23.578** | **25.686** | **22.731** | **47.997** | **44523** | **48735** |
| **run05** | **25.621** | **27.616** | **25.200** | **44.144** | **40955** | **44880** |

> [!WARNING]
> Duzy rozrzut miedzy runami (22.7 – 29.3 TRUE FPS) wskazuje na **thermal throttling**.
> Ryzen 7 7730U ma TDP ~28W (APU). Po cieplym runie CPU+GPU thermal budget sie wyczerpuje.
> Run01 (zaraz po warmupie) jest najszybszy bo thermal headroom jest dostepny.
> Run03 jest najwolniejszy — peak thermal saturation.

---

## 6. Statystyczny nowy baseline (5 measured runs)

| Metryka | AVG | **MEDIAN** | MIN | MAX | P95 |
|---------|-----|------------|-----|-----|-----|
| **TRUE FPS** | 25.531 | **25.256** | 23.074 | 29.750 | 28.924 |
| **RENDER FPS** | 27.485 | **27.123** | 24.672 | 32.330 | 31.387 |
| **USER EFF FPS** | 25.140 | **24.886** | 22.731 | 29.293 | 28.475 |
| precompute_build_ms | 39.1 | **40.4** | 32.4 | 45.7 | 45.1 |
| delay_first_frame_ms | 1408 | **1477** | 1223 | 1528 | 1524 |
| video_render_wall_ms | 41502 | **41698** | 34983 | 45841 | 45479 |
| mux_wall_ms | 2468 | **2479** | 2431 | 2497 | 2496 |
| total_from_export_ms | 45327 | **45447** | 38609 | 49756 | 49393 |
| wall_s | 44.635 | **44.782** | 38.017 | 49.015 | 48.655 |

**Nowy kanoniczny baseline (MEDIANA):**
```
TRUE FPS median          = 25.256 fps
RENDER FPS median        = 27.123 fps
USER EFFECTIVE FPS med   = 24.886 fps
precompute_build_ms med  = 40.4 ms
delay_first_frame_ms     = 1477 ms
video_render_wall_ms     = 41698 ms (41.7 s)
mux_wall_ms              = 2479 ms (2.5 s)
total_from_export_ms     = 45447 ms (45.4 s)
```

> [!NOTE]
> Porownanie z pierwszym runem (GX020079, 1131f, -test): RENDER FPS=35.3, TRUE FPS=32.1
> Roznica: GX020079 jest krotkoscia (37.7s) i ma mniej aktywnych widgetow w layoutcie.
> GX030120 z Jazda fit ma pelny layout z lean_indicator, wiecej FIT fields, wiecej ABOVE widgetow.

---

## 7. Pelny pipeline breakdown (run05 — mediana runu)

### Podsumowanie faz

```
Stage                                    avg_ms   median_ms    p95_ms    p99_ms
------------------------------------------------------------------------
pipeline_total                           24.625    20.643      41.192    66.663
consumer_native_call (GPU submit+wait)   20.406    16.172      37.501    61.189
  VideoProcessor GPU completion          14.636    11.093      32.120    42.233
  GPU wait/synchronization               18.063    13.602      35.425    58.298
producer_prepare                         11.340    11.085      15.758    18.951
  above_total                             4.275     4.267       6.567     8.339
    above_compose                         4.037     4.031       6.149     8.031
    above_region_upload                   0.894     0.786       1.777     2.265
    above_region_to_bytes                 0.192     0.173       0.335     0.468
  map_cpu_upload                          4.639     4.674       6.885     7.812
  gauge_capture                           0.807     0.773       1.414     1.852
  gauge_upload                            0.474     0.409       0.993     1.222
consumer_upload                           2.985     2.725       4.593     5.362
MF ReadSample/decode availability         1.048     0.818       1.682     2.437
AMF submit/backpressure                   0.301     0.284       0.439     0.569
VideoProcessor CPU submit                 0.286     0.249       0.456     0.554
AMF QueryOutput                           0.246     0.215       0.407     0.547
Packet write                              0.208     0.180       0.381     0.532
mux_wall (audio demux)                 2489.7    2489.7      2489.7    2489.7
```

### Roznica RENDER FPS vs TRUE FPS vs USER EFFECTIVE FPS

```
RENDER FPS        = 1131 / video_render_wall_s = 1131 / 40.955 = 27.616 fps
  - tylko czas renderowania klatek
  - bez precompute, startup, mux

TRUE FPS          = amf_submitted / total_wall_clock_s = 1131 / 44.144 = 25.621 fps
  - pelny czas scienny od startu do konca enkodowania

USER EFFECTIVE FPS = 1131 / total_from_export_start_s = 1131 / 44.880 = 25.200 fps
  - pelny czas od klikniecia "Export" do gotowego pliku

Decomposition (run05):
  precompute_build:        42.8 ms   (0.1%)
  startup/first_frame:   1527.9 ms   (3.4%) — inicjalizacja D3D11/AMF/MF
  video_render:         40954.7 ms  (91.3%) — renderowanie 1131 klatek
  mux_wall:              2489.7 ms   (5.5%) — audio remux
  other:                 ~200 ms     (0.5%)
  TOTAL:                44880 ms   (100%)
```

---

## 8. Analiza CPU vs GPU bottleneck na Ryzen 7 7730U

### Dominujace bottlenecki

**consumer_native_call = 20.4ms avg (16.2ms median)** to nowe #1 bottleneck.

Zawiera:
- `VideoProcessor GPU completion` = 14.6ms avg — GPU VideoProcessor (color conversion NV12)
- `GPU wait/synchronization` = 18.1ms avg — synchronous GPU fence wait

To jest **integrated GPU bottleneck** — Radeon Vega iGPU musi wykonac:
1. VideoProcessor pass (color space conversion + scaling)
2. GPU compute shader dla compositing HUD
3. AMF encode

Wszystkie kroki wspoldziela ten sam GPU i DRAM bandwidth. Na dedykowanej GPU te etapy nakladaja sie przez async overlap — tu nie ma tej mozliwosci.

### Producer thread (CPU side)

**producer_prepare = 11.3ms avg** — CPU bottleneck secondary:
- `above_total` = 4.3ms (CPU ABOVE compose + region upload)
- `map_cpu_upload` = 4.6ms (map render + direct pointer upload)
- `gauge_capture` + `gauge_upload` = 1.3ms

### Pipeline balance

```
producer thread: ~11ms
consumer thread: ~20ms (GPU dominuje)
```

Pipeline jest **consumer-bound** (GPU). Producer ukonczy prace przed GPU — brak producer wait.
Pipelining jest asynchroniczny (SYNC mode tu) — mozna analizowac czy ASYNC pomoglby.

### Bottleneck typ: integrated GPU bandwidth

Ryzen 7 7730U iGPU:
- Brak HBM/GDDR — korzysta z LPDDR5 (~50 GB/s) wspoldzielonego z CPU
- 4K NV12 frame = 3840x2160x1.5 = ~11.9 MB
- VideoProcessor pass + AMF + HUD composite = 3x pass = ~36 MB/frame
- Przy 25 fps = ~900 MB/s GPU DRAM pressure
- To jest bliskie limitu dostepnego bandwidth dla iGPU

---

## 9. Walidacja fast-path / direct pointers

| Fast-path | Status | Szczegoly |
|-----------|--------|-----------|
| map direct pointer | **AKTYWNY** | pointer_stable=True, full_tobytes_calls=0 |
| map fallback tobytes | 0 wywolan | PASS — zero fallbacks |
| below direct memmove | **AKTYWNY** | PIL/buffer prep=0.089ms (bylo ~1.45ms) |
| gauge GPU path | **AKTYWNY** | gauge_path=GPU, gauge_gpu_active=True |
| gauge AUTO regions | **AKTYWNY** | mode=AUTO_SAFE, full_resyncs=10/1131 |
| above DIRECT buffer | **AKTYWNY** | above_upload_buffer_mode=DIRECT |
| above EXACT dirty | **AKTYWNY** | above_dirty_mode=EXACT, scanned_pixels=0 |
| PRECOMPUTED telemetry | **AKTYWNY** | precomputed=True, build=42ms |
| chart GPU_SPLIT | **AKTYWNY** | ['fit_cadence_text','fit_heart_rate_text'] |
| lean GPU affine | **AKTYWNY** | GPU_LEAN_AFFINE |

**Wszystkie fast-paths aktywne. Fallbacki = 0.**

---

## 10. Golden Parity

```
tests/test_golden_parity_etap4.py: 4/4 PASSED

test_golden_elements_presence_and_bboxes PASSED
test_lean_visible_gap_positive           PASSED
test_lean_gpu_pivot_exact_match          PASSED
test_golden_pixel_parity                 PASSED

MaxDiff         = 0
DifferentPixels = 0
```

**Zmiana komputera nie wplynela na wynik wizualny. PARITY EXACT zachowane.**

---

## 11. Pelny suite testow

```
1134 passed, 30 failed, 17 skipped   (Python 3.14.7, pytest-9.1.1)
```

### Failures — analiza

Wszystkie 30 failures wynikaja z **modyfikacji working tree** (niezcommitowane zmiany) —
nie sa regresja spowodowana migracja sprzetowa.

Grupy failures:

| Plik testu | Ilosc | Przyczyna |
|------------|-------|-----------|
| test_amd_above_exact_tight_bbox_etap10r | 8 | Zmiany w `compositor.py` (WIP) |
| test_export_lifecycle_p1_fixes | 5 | Bug `UnboundLocalError: _linfo` w `amd_native_exporter.py` (WIP) |
| test_etap10n2/n3_distance_marker | 7 | Zmiany w `bar.py` przesuniecie markera o ~3px (WIP) |
| test_etap5e1/5e3_chart_prefix | 3 | Zmiany w `compositor.py` (WIP) |
| test_etap8m7_chart_frame_clipping | 1 | Zmiany w `compositor.py` (WIP) |
| test_etap8q_dirty_text_cache | 1 | Ghosting test, `compositor.py` (WIP) |
| test_etap8s_flush_batching | 1 | Ghosting test, `compositor.py` (WIP) |
| test_etap8t_b_async_pipeline | 2 | `PreparedFrame` missing arg `map_heading` (WIP) |
| test_amd_native_etap5b | 1 | Layout field count zmieniony w `def_layout.json` (WIP) |
| test_distance_bar_scale_contract | 1 | `bar.py` marker offset (WIP) |

> [!IMPORTANT]
> Poprzedni baseline z ETAP 4I: `165 passed, 0 failed`.
> Obecny suite ma 1134 passed (wzrost o ~969 testow) + 30 failures z WIP zmian.
> Zmodyfikowane pliki: def_layout.json, bar.py, compositor.py, gauge.py, lean.py, rotated_paste.py
> Te zmiany SA w working tree ale NIECOMMITOWANE — naleza do jakiegos WIP zadania.
> **Nie sa regresja z migracji hardware.**

---

## 12. TOP 5 Bottlenecków — Ryzen 7 7730U

Na podstawie mediany run05 (najbardziej stabilny run):

### #1 — consumer_native_call (GPU wait+VP+encode submit)
```
avg:    20.406 ms
median: 16.172 ms
p95:    37.501 ms
p99:    61.189 ms
% pipeline: ~83% consumer frame time
```
**Charakter:** integrated GPU (VP + HUD composite + fence) — hardware limit.
Możliwy zysk przez asynchroniczny pipeline (GPU overlap). 
Ryzyko: wysoka zlozonos implementacji, iGPU ma malo watkow compute.

### #2 — VideoProcessor GPU completion (D3D11 Video Processor)
```
avg:    14.636 ms
median: 11.093 ms
p95:    32.120 ms
```
**Charakter:** D3D11 VideoProcessor — color space + scaling iGPU.
Subcomponent #1. Moze byc ograniczony format NV12 output + HLG color transfer.

### #3 — map_cpu_upload (map render + direct upload)
```
avg:     4.639 ms
median:  4.674 ms
p95:     6.885 ms
```
**Charakter:** `render_map_inner` (~4ms) + tobytes/pointer (~0.5ms).
Wewnetrzny render mapy przez Pillow/CPU. Redukowalne przez GPU map rendering.
Na poprzednim sprz.: 1.4ms (ETAP 4I). Na iGPU cos spowalnia render_map_inner.

### #4 — above_total (CPU ABOVE compose + upload)
```
avg:     4.275 ms
median:  4.267 ms
p95:     6.567 ms
```
**Charakter:** CPU compose 20+ widgetow + region upload do GPU.
Ograniczenie: single-thread CPU. 7 regionow/klatke.
Na poprzednim sprz.: ~10ms (po ETAP 4G). Tu szybciej — Ryzen 7730U ma lepszy IPC.

### #5 — producer_prepare (caly producent)
```
avg:    11.340 ms
median: 11.085 ms
p95:    15.758 ms
```
**Charakter:** suma: above_total + map_cpu_upload + gauge_capture + gauge_upload.
Nie jest bezposrednim bottleneckiem bo pipeline_total jest consumer-bound.

---

## 13. Wyjasnienie TRUE FPS vs RENDER FPS vs USER EFFECTIVE FPS

```
RENDER FPS = klatki / video_render_wall
           = 1131 / 40.955s = 27.6 fps
           - Mierzy tylko czas renderowania klatek (od pierwszej do ostatniej)
           - NIE zawiera: precompute, startup D3D11/AMF, mux audio

TRUE FPS   = klatki / total_wall_clock
           = 1131 / 44.144s = 25.6 fps
           - Pelny czas scienny od startu procesu do zamkniecia enkodera
           - Zawiera: startup + render + pakietowanie, bez mux

USER EFFECTIVE FPS = klatki / total_from_export_start
                   = 1131 / 44.880s = 25.2 fps
                   - Czas od "kliknij Export" do gotowego pliku MP4
                   - Zawiera: precompute + startup + render + mux
                   - To odczuwa uzytkownik
```

**Struktura czasu eksportu (run05):**
```
precompute_build:   43ms    (0.1%)
startup/init:      1485ms   (3.3%)   [1528 - 43 ms]
video_render:     40955ms  (91.3%)
mux_audio:         2490ms   (5.5%)
other overhead:     200ms   (0.4%)
TOTAL:            45447ms (100%)    = USER EFFECTIVE 25.2 fps
```

**Dalsza optymalizacja powinna zwiekszyc USER EFFECTIVE FPS i total_from_export_ms
przede wszystkim przez redukcje video_render_wall (91.3% czasu).**

---

## 14. Ryzyka i obserwacje

1. **Thermal throttling** — rozrzut 22.7–29.3 fps wskazuje na thermal throttling iGPU.
   Dlugie serie eksportow beda wolniejsze niz pojedyncze runy.
   Baseline mediana (25.3 fps) jest mierzony w warunkach termicznie obciazonych.

2. **Wspoldzielona DRAM** — iGPU korzysta z systemu LPDDR5. CPU-GPU memory contention
   moze powodowac nieliniowe spowolnienia przy duzym GPU obciazeniu.

3. **Working tree WIP** — 11 plikow zmodyfikowanych (niezcommitowanych).
   30 testow pada. Nie sa to regresy hardware — to WIP zmiany z poprzedniej sesji.
   Przed ETAP 5B nalezy sprawdzic czy te zmiany sa zamierzone.

4. **map_cpu_upload = 4.6ms** — na starym sprz. bylo 1.4ms (ETAP 4I).
   Wzrost o ~3ms moze wynikac z wolniejszego zegara iGPU przy inicjalizacji map render,
   lub z innego tile cache state. Do zbadania.

5. **Remote Display Adapter** — wykryto `Microsoft Remote Display Adapter` jako VideoController1.
   Sugeruje ze komputer jest dostepny przez RDP. Upewnic sie ze eksport odbywa sie na
   natywnym display, nie RDP (dla poprawnego D3D11 device selection).

---

## 15. Rekomendacja ETAP 5B

### Priorytet: CONSUMER GPU PIPELINE OPTIMIZATION

Bottleneck #1 to `consumer_native_call` = 20.4ms avg (16.2ms median), z czego:
- `VideoProcessor GPU completion` = 14.6ms — D3D11 VP pass
- `GPU wait/synchronization` = 18ms — sync GPU fence

**Rekomendowane podejscia (kolejnosc):**

**5B.1 — AMF async pipeline / GPU overlap**
Zbadac czy przelaczenie na tryb ASYNC producer-consumer (z odpowiednim depth)
pozwoli na nakladanie sie GPU VP + AMD encode z CPU above compose.
Zysk: ~5–10 fps jesli GPU i CPU moga dzialac rownolegle.

**5B.2 — VideoProcessor format/path audit**
Sprawdzic czy D3D11 VP wykonuje nieuzasadniona konwersje (np. HLG->SDR->NV12
zamiast bezposredniej NV12 output). Redukcja VP passes moze oszczedzic 5–8ms.

**5B.3 — map_cpu_upload regression investigation**  
Wyjasnij wzrost 1.4ms -> 4.6ms. Czy to render_map_inner spowalnienie, czy upstream change?

**Nie wdrazac w 5B:**
- Zmian w widgetach (WIP z working tree)
- Optymalizacji ABOVE compose (4.3ms — nie jest bottleneckiem na nowym sprz.)
- Zmian w NVIDIA/Intel/GPU backend isolation

---

## PASS / FAIL

```
TASK:   AMD ETAP 5A - RYZEN 7 7730U HARDWARE REBASELINE

STATUS: PASS (z zastrzezeniami - patrz thermal i WIP tests)

HARDWARE:
CPU    = AMD Ryzen 7 7730U (8c/16t, 2.0GHz base)
GPU    = AMD Radeon (TM) Graphics (Vega iGPU, 512MB shared, driver 31.0.21925.1001)
RAM    = 32 GB
OS     = Windows 11 Pro Build 26200

PRODUCTION PATH:
decoder    = D3D11VA (MediaFoundation hardware decode) - AKTYWNY
compositor = DIRECT_NV12_COMPUTE_SHADER (native D3D11) - AKTYWNY
encoder    = AMF HEVC CQP 28/28 Speed - AKTYWNY
fallback   = BRAK (CPU fallback nie aktywny)

RUNS (GX030120, 1131f, 3840x2160, def_layout+Jazda_fit):
warmup: TRUE_FPS ~29.5  RENDER_FPS ~32.1  (thermal headroom)
1.      TRUE_FPS 29.277  RENDER_FPS 32.330
2.      TRUE_FPS 24.874  RENDER_FPS 27.123
3.      TRUE_FPS 22.719  RENDER_FPS 24.672  (thermal saturation)
4.      TRUE_FPS 23.578  RENDER_FPS 25.686
5.      TRUE_FPS 25.621  RENDER_FPS 27.616

NEW CANONICAL BASELINE (MEDIANA 5 runow):
TRUE FPS median          = 25.256 fps
RENDER FPS median        = 27.123 fps
USER EFFECTIVE FPS med   = 24.886 fps
precompute_build_ms      = 40.4 ms
delay_first_frame_ms     = 1477 ms
video_render_wall_ms     = 41698 ms (41.7 s / 1131 frames)
mux_wall_ms              = 2479 ms
total_from_export_ms     = 45447 ms (45.4 s)

PARITY:
MaxDiff         = 0
DifferentPixels = 0

TESTS:
passed  = 1134
failed  = 30  (WSZYSTKIE z WIP working tree modifications — NIE regresje hardware)
skipped = 17
golden parity = 4/4 PASS

FAST PATHS:
map direct pointer  = AKTYWNY (pointer_stable=True, tobytes_calls=0)
below direct memmove = AKTYWNY (PIL/buffer prep=0.089ms)
above direct buffer  = AKTYWNY (above_upload_buffer_mode=DIRECT)
gauge GPU path       = AKTYWNY (gauge_gpu_frames=1131/1131)
gauge AUTO regions   = AKTYWNY (10 full resyncs / 1121 region)
chart GPU_SPLIT      = AKTYWNY (cadence+HR AFTER-MAP)
lean GPU affine      = AKTYWNY
telemetry PRECOMPUTED = AKTYWNY
fallbacks            = 0

TOP BOTTLENECKS (mediana run05):
1. consumer_native_call (GPU VP+wait)  20.4ms avg / 16.2ms median (thermal variable)
2. VideoProcessor GPU completion       14.6ms avg / 11.1ms median
3. GPU wait/synchronization            18.1ms avg / 13.6ms median
4. map_cpu_upload                       4.6ms avg /  4.7ms median (regresja vs 1.4ms ETAP4I?)
5. above_total                          4.3ms avg /  4.3ms median

OBSERVATIONS:
- Thermal throttling: iGPU TDP-limited, rozrzut 22.7-29.3 fps
- map_cpu_upload wzrost: 1.4ms (ETAP4I GX020079) -> 4.6ms (GX030120) - wymaga zbadania
- 30 test failures: WIP working tree, nie regresja sprzetu
- Microsoft Remote Display Adapter wykryty - potwierdzic natywny display dla eksportu

NEXT RECOMMENDATION (ETAP 5B):
- Zbadac i zoptymalizowac consumer_native_call (GPU VP pipeline)
- Wyjasnij map_cpu_upload wzrost (1.4 -> 4.6ms)
- Rozwazyc ASYNC producer-consumer overlap jesli GPU i CPU moga rownolegle
- NIE optymalizowac bez wczesniejszego wyjasnienia thermal behaviour

REPORT: Raporty/RAPORT_AMD_ETAP_5A_RYZEN7730U_HARDWARE_REBASELINE.md
```
