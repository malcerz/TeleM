# TeleM — ETAP 8D: Audyt kosztu pełnego `CPU_ABOVE_MAP` canvas

## Result

**ETAP 8D zakończony.**
Klasyfikacja:
```text
FULL_CANVAS_ABOVE = NOT SIGNIFICANT
```

Przeprowadzony audyt diagnostyczny, mikrobenchmarki Pillow, testy wariantów layoutu oraz 3 pełne przebiegi produkcyjne po 900 klatek na materiale referencyjnym `GX030120.MP4` wykazały jednoznacznie, że **pełny canvas `CPU_ABOVE_MAP` NIE jest wąskim gardłem systemu TeleM**.

Dzięki mechanizmowi `reuse_canvas=True` w `_THREAD_CANVAS`, bufor 4K RGBA nie jest alokowany co klatkę (0 alokacji/klatkę w runtime), a jego czyszczenie regionalne zajmuje zaledwie **0,0073 ms (7,3 µs)**. Całkowity koszt warstwy `CPU_ABOVE_MAP` w klatce produkcyjnej wynosi około **1,04 ms** (~6,2% budżetu 60 FPS), a jej całkowite wyłączenie podnosi throughput zaledwie o **+0,207 FPS (+0,75%)**.

Prawdziwymi dominującymi kosztami serial CPU/native są:
1. Natywny `process_frame` / D3D11 VideoProcessor (~8,04 ms mediana),
2. Przygotowanie mapy na CPU `map_cpu_upload` (~3,09 ms mediana),
3. Główny kompozytor poniżej mapy `compose_overlay` (~2,28 ms mediana),
4. Serializacja i upload speed gauge (~2,25 ms mediana).

---

## A. Current ABOVE Architecture

Pełna ścieżka wykonania warstwy `CPU_ABOVE_MAP`:

```text
export_amd_native_d3d11()
   │
   ├── _ordered_map_layout_parts(layout)
   │     └── podział layoutu na compose_layout (BELOW) oraz map_above_layout (ABOVE)
   │
   ├── [Pętla renderowania per-frame]
   │     │
   │     ├── compose_overlay(compose_layout)  ───> główny HUD (BELOW_MAP)
   │     │
   │     ├── above_full = compose_overlay(map_above_layout)  ───> warstwa ABOVE
   │     │     ├── _get_reusable_canvas(3840, 2160) [reused, 0 alloc]
   │     │     ├── regional_clear(prev_bboxes, pad=40) [~0.007 ms]
   │     │     ├── render_value_indicator(...) [~0.011 ms]
   │     │     └── rotated_paste(img, res, ...) [~0.167 ms]
   │     │
   │     ├── candidate = _rendered_bbox_union(above_bboxes, 3840, 2160, pad=64) [~0.013 ms]
   │     ├── candidate_image = above_full.crop(candidate) [~0.032 ms]
   │     ├── local_alpha_bbox = candidate_image.getchannel("A").getbbox() [~0.061 ms]
   │     ├── above_map_img = candidate_image.crop(local_alpha_bbox) [~0.008 ms]
   │     │
   │     ├── above_bytes = above_map_img.tobytes("raw", "RGBA") [~0.019 ms]
   │     └── native_dll.telem_amd_update_above_map(...) [~0.020 ms]
   │
   └── Native D3D11 VideoProcessor Pipeline (d3d11_vp_pipeline.cpp)
         ├── ClearPreviousAboveMap()
         ├── BlendCharts()
         ├── BlendGauge()
         ├── ResampleAndBlendMap()
         └── BlendAboveMap()
```

---

## B. Full Canvas Creation & Resource Inventory

| Parametr | Wartość |
|---|---|
| Plik tworzenia canvasu | `src/indicators/compositor.py` |
| Funkcja | `compose_overlay()` -> `_get_reusable_canvas()` |
| Wymiary canvasu | 3840 × 2160 |
| Format | RGBA (straight alpha) |
| Rozmiar pamięci canvasu | 3840 × 2160 × 4 = **33 177 600 B (~31,64 MiB)** |
| Alokacje per frame (`reuse_canvas=True`) | **0 alokacji / frame** (tworzony raz przy starcie w `_THREAD_CANVAS.cache`) |
| Koszt alokacji zera od nowa (`Image.new`) | 7,317 ms (nie występuje w pętli produkcyjnej) |
| Koszt czyszczenia regionalnego per frame | **0,0073 ms (7,3 µs)** |

### Liczba pełnych obrazów 4K tworzonych per frame w AMD final path:
| Zasób | Wymiary | Format | Tworzony co klatkę? | Reużywany? | Rozmiar bufora |
|---|---|---|---|---|---|
| Main CPU HUD canvas | 3840 × 2160 | RGBA | Nie | Tak (`_THREAD_CANVAS`) | 31,64 MiB (0 alloc/frame) |
| Post-map ABOVE canvas | 3840 × 2160 | RGBA | Nie | Tak (współdzieli cached canvas) | 31,64 MiB (0 alloc/frame) |
| Candidate crop (`candidate_image`) | ~589 × 190 | RGBA | Tak | Nie (tymczasowy crop) | ~447,6 KiB |
| Final compact crop (`above_map_img`) | ~461 × 62 | RGBA | Tak | Nie (do uploadu) | ~114,3 KiB |
| Map working image (`map_img`) | 692 × 692 | RGBA | Tak | Nie | ~1,91 MiB |
| Gauge captured surface (`gauge_img`) | ~583 × 588 | RGBA | Tak | Nie | ~1,37 MiB |
| Native HUD texture (GPU) | 3840 × 2160 | DXGI R8G8B8A8 | Nie | Tak (tworzona w klatce 0) | 31,64 MiB VRAM |
| Native ABOVE texture (GPU) | ~461 × 62 | DXGI R8G8B8A8 | Tylko przy zmianie rozmiaru | Tak (persystentna) | ~114 KiB VRAM |

---

## C. Instrumentation — Tabela Timerów

| Nazwa Timera | Plik | Funkcja | Start | Stop | Zakres / Co zawiera |
|---|---|---|---|---|---|
| `MF ReadSample/decode availability` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed `ReadSample` | po pobraniu próbki | Czas oczekiwania na dekoder sprzętowy D3D11VA |
| `Telemetry/frame_data` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed lookupem | po interpolacji | Interpolacja telemetrii / cache |
| `compose_overlay` (BELOW) | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed `compose_overlay` | po zwróceniu | Główny HUD: czyszczenie, render i paste wskaźników przed mapą |
| `above_compose` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed `compose_overlay` | po zwróceniu | Warstwa ABOVE: czyszczenie, render i paste wskaźników po mapie |
| `above_bbox_crop` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed candidate | po final crop | Suma: candidate crop + local alpha scan + final crop |
| `above_bbox_tracking` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed union | po union | Wyznaczenie candidate bounding box union + pad=64 |
| `above_candidate_crop` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed crop | po crop | Przycięcie bufora 4K do rozmiaru candidate |
| `above_local_alpha_scan` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed scan | po scan | Skanowanie alpha wyłącznie na candidate crop |
| `above_final_crop` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed crop | po crop | Przycięcie candidate do ścisłego widocznego bbox |
| `map_cpu_upload` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed `render_map` | po uploadzie | Rysowanie mapy 692×692 na CPU + serializacja + upload GPU |
| `gauge_tobytes` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed tobytes | po tobytes | Serializacja RGBA bufora prędkościomierza |
| `gauge_upload` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed upload | po upload | Upload speed gauge do tekstury GPU |
| `HUD dirty extract` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed extract | po np.copyto | Przycinanie brudnych obszarów HUD i kopiowanie do bufora |
| `VideoProcessor CPU submit` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed `ProcessFrame` | po powrocie | Wywołanie natywnego D3D11 VideoProcessora |
| `AMF submit/backpressure` | `amd_native_exporter.py` | `export_amd_native_d3d11` | przed `SubmitInput` | po powrocie | Wstawienie ramki do kolejki enkodera AMF |

---

## D. Inclusive vs Exclusive Timer Map

```text
Całkowity czas klatki (Wall Clock ~36 ms):
├── Serial CPU Work (Frontend ~10.5 ms):
│   ├── MF ReadSample/decode availability (~0.75 ms) [EXCLUSIVE]
│   ├── Telemetry/frame_data (~0.07 ms) [EXCLUSIVE]
│   ├── compose_overlay (main/BELOW) (~2.28 ms) [EXCLUSIVE]
│   ├── above_compose (~0.78 ms) [EXCLUSIVE]
│   │   ├── regional_clear (~0.007 ms) [NESTED]
│   │   ├── indicator render (~0.011 ms) [NESTED]
│   │   └── indicator paste (~0.167 ms) [NESTED]
│   ├── above_bbox_crop (~0.25 ms) [EXCLUSIVE]
│   │   ├── above_bbox_tracking (~0.013 ms) [NESTED]
│   │   ├── above_candidate_crop (~0.125 ms) [NESTED]
│   │   ├── above_local_alpha_scan (~0.090 ms) [NESTED]
│   │   └── above_final_crop (~0.015 ms) [NESTED]
│   ├── map_cpu_upload (~3.05 ms) [EXCLUSIVE]
│   ├── gauge_tobytes + upload (~1.25 ms) [EXCLUSIVE]
│   ├── HUD dirty extract & prep (~0.40 ms) [EXCLUSIVE]
│   └── update_hud (~0.05 ms) [EXCLUSIVE]
├── Native / D3D11 Submissions (~1.0 ms):
│   ├── VideoProcessor CPU submit (~0.77 ms) [EXCLUSIVE]
│   ├── GPU gauge blend submit (~0.08 ms) [EXCLUSIVE]
│   └── telem_amd_update_above_map (~0.02 ms) [EXCLUSIVE]
└── AMF & GPU Async Drain / Wait (~24.5 ms overlapping / blocking):
    ├── AMF submit/backpressure (~0.38 ms) [EXCLUSIVE]
    ├── AMF QueryOutput (~0.21 ms) [EXCLUSIVE]
    ├── Packet write (~0.23 ms) [EXCLUSIVE]
    └── D3D11 / AMF async hardware execution & wait
```

---

## E. Real ABOVE Inventory (`def_layout.json`)

Wszystkie wskaźniki zdefiniowane po `track_map` w kanonicznym `def_layout.json`:

| Wskaźnik | Enabled | Form | Źródło | Renderowany w default? | Geometria Bbox (4K) | Powierzchnia (px) |
|---|---|---|---|---|---|---:|
| `fit_battery_pct_x100_text` | False | text | fit | Nie | None | 0 |
| `fit_fractional_cadence_text` | False | text | fit | Nie | None | 0 |
| `fit_battery_text` | **True** | text | fit | **Tak** | `(3300, 935, 431, 62)` | **26 722** |
| `fit_battery_pct_text` | False | text | fit | Nie | None | 0 |
| `fit_discharge_text` | False | text | fit | Nie | None | 0 |
| `fit_distance_text` | False | text | fit | Nie | None | 0 |
| `fit_solar_text` | False | text | fit | Nie | None | 0 |
| `fit_solar_pct_text` | False | text | fit | Nie | None | 0 |
| `fit_gopro_battery_text` | False | text | fit | Nie | None | 0 |
| `fit_passing_speed_text` | False | text | fit | Nie | None | 0 |
| `fit_passing_speedabs_text` | False | text | fit | Nie | None | 0 |
| `fit_radar_current_text` | False | text | fit | Nie | None | 0 |
| `custom_texts` | — | text | custom | Nie (`[]`) | None | 0 |

**Wskaźniki aktywne w warstwie ABOVE**: dokładnie **1 wskaźnik** (`fit_battery_text` — Garmin Battery 74%).

---

## F–H. Warianty Layoutu ABOVE — Pomiary Izolowane

Pomiary wykonane na 200–300 iteracjach w harnessie diagnostycznym:

| Scenariusz | `above_compose` (ms) | `crop_pipeline` (ms) | Total ABOVE CPU (ms) | Candidate Bbox (px) | Final Bbox (px) |
|---|---:|---:|---:|---|---|
| **Empty ABOVE** (brak wskaźników) | 2,956* / 0,109** | 0,002 | 0,111 ms | Brak | Brak |
| **One Small Text** (domyślny `fit_battery_text`) | **0,376** | **0,123** | **0,500 ms** | 589 × 190 (111 910 px) | 461 × 62 (28 582 px) |
| **One Large Text** (font_size = 8.0) | 1,015 | 0,302 | 1,330 ms | 603 × 302 (182 106 px) | 539 × 140 (75 460 px) |
| **2 Elements ABOVE** (battery + custom text) | 1,092 | 10,140 | 11,317 ms | 2203 × 938 (2 066 414 px) | 2073 × 801 (1 660 473 px) |
| **4 Elements ABOVE** (4 narożniki) | 1,540 | 35,109 | 36,782 ms | 3699 × 1903 (7 039 197 px) | 3569 × 1767 (6 306 423 px) |
| **Sparse Distant** (TL 5% & BR 95%) | 0,614 | 42,339 | 42,978 ms | 3840 × 2111 (8 106 240 px) | 3717 × 1977 (7 348 509 px) |
| **Value = None** (brak danych sensora) | 2,976* / 0,114** | 0,002 | 0,116 ms | Brak | Brak |

*\* Uwaga dot. Empty/None:* W teście izolowanym, gdy `prev_bboxes` jest puste, kod wykonuje pełny fallback `img.paste((0,0,0,0), (0,0,W,H))` zajmujący ~2,95 ms.
*\*\* W pętli produkcyjnej* `above_compose` dla pustego ABOVE wynosi **0,109 ms**.

### Stosunek powierzchni pikseli dla domyślnego layoutu:
- Cały canvas 4K: `3840 × 2160 = 8 294 400 px`
- Candidate bbox: `589 × 190 = 111 910 px` (**1,35% klatki 4K**)
- Final visible bbox: `461 × 62 = 28 582 px` (**0,34% klatki 4K**)

---

## I. Koszt alokacji i inicjalizacji canvasu

| Operacja | Mediana (ms) | P95 (ms) | Średnia (ms) | Max (ms) |
|---|---:|---:|---:|---:|
| `Image.new("RGBA", 3840x2160)` (nowa alokacja) | 7,317 | 13,252 | 8,054 | 20,077 |
| `Full 4K clear paste` (`img.paste((0,0,0,0), 4K)`) | 3,018 | 3,869 | 3,174 | 7,426 |
| **`Regional clear paste` (559×190 na canvasie 4K)** | **0,0073** | **0,0077** | **0,0076** | **0,0710** |
| `Candidate crop` (559×190 z 4K) | 0,0246 | 0,2183 | 0,0610 | 0,3840 |
| `Local alpha scan` (559×190) | 0,0609 | 0,1010 | 0,0678 | 0,1350 |
| *Stary full-frame 4K alpha scan (usunięty w 8C)* | 6,682 | 7,411 | 6,783 | 7,794 |

**Wniosek:** Reużywalny canvas eliminuje 7,3 ms alokacji. Koszt wyczyszczenia poprzedniej pozycji wskaźnika to zaledwie **7,3 mikrosekundy**.

---

## J. ABOVE Compose Breakdown (Szczegółowy rozkład 1 wskaźnika)

| Podetap operacji | Czas medianowy (ms) | % czasu ABOVE |
|---|---:|---:|
| Inicjalizacja / Regional clear | 0,007 ms | 1,0% |
| `render_value_indicator` | 0,011 ms | 1,5% |
| `rotated_paste` (0°) | 0,167 ms | 23,5% |
| Bbox tracking (`_rendered_bbox_union`) | 0,013 ms | 1,8% |
| Candidate crop | 0,032 ms | 4,5% |
| Local alpha scan | 0,061 ms | 8,6% |
| Final crop | 0,008 ms | 1,1% |
| `tobytes("raw", "RGBA")` | 0,019 ms | 2,7% |
| `native_update` (D3D11 upload) | 0,020 ms | 2,8% |
| Pozostały narzut pętli / Pythona | ~0,370 ms | 52,5% |
| **Suma całkowita ABOVE** | **~0,708–1,040 ms** | **100,0%** |

---

## K. Przepustowość pamięci (Memory Bandwidth Analysis)

- Minimalny ruch pamięci na alokację i upload 4K RGBA: `3840 × 2160 × 4 = 33,18 MB/frame`.
- Przy 60 FPS: `33,18 MB × 60 = 1,99 GB/s`.
- W obecnym rozwiązaniu `CPU_ABOVE_MAP`:
  - Alokacja 4K: **0 B/frame** (brak alokacji).
  - Czyszczenie regionalne: `559 × 190 × 4 = 424,8 KB/frame`.
  - Finalny upload: `461 × 62 × 4 = 114,3 KB/frame` (**0,109 MiB/frame**).
  - Ruch pamięci ABOVE przy 28 FPS: `114,3 KB × 27,5 = 3,14 MB/s` (pomijalny dla kontrolera pamięci DDR4/LPDDR4 ~30–40 GB/s).

---

## L. Przebiegi Produkcyjne 3 × 900 Klatek (`GX030120.MP4`)

Testy produkcyjne na pełnym pipeline D3D11VA + VideoProcessor + AMF HEVC (`AMD Ryzen 5 5500U`):

| Run Tag | Liczba klatek | Output klatek | Video Wall (s) | Mux Wall (s) | Total Wall (s) | TRUE FPS | Dropped frames |
|---|---:|---:|---:|---:|---:|---:|---:|
| `8dfull1` | 900 | 900 | 32,626 | 2,305 | 34,931 | **27,586** | 0 |
| `8dfull2` | 900 | 900 | 32,895 | 2,544 | 35,439 | **27,359** | 0 |
| `8dfull3` | 900 | 900 | 32,702 | 2,219 | 34,921 | **27,521** | 0 |
| **MEDIANA (Default)** | **900** | **900** | **32,702** | **2,305** | **34,931** | **27,521** | **0** |
| `8d_empty_above` (Empty) | 900 | 900 | 32,458 | 2,346 | 34,804 | **27,728** | 0 |
| `8d_profile_on` (Profiler ON) | 900 | 900 | 33,692 | 2,495 | 36,187 | **26,713** | 0 |

### Wnioski z pomiarów end-to-end:
1. **Różnica między aktywnym ABOVE (27,521 FPS) a całkowicie pustym ABOVE (27,728 FPS)** wynosi zaledwie **0,207 FPS (+0,75%)**. Potwierdza to, że koszt warstwy ABOVE jest na poziomie błędu pomiarowego i nie stanowi wąskiego gardła.
2. **Narzut profilera (`8d_profile_on` vs `8dfull3`)**: spadek o 2,93% (< 5%), spełnia kryterium akceptowalnego narzutu diagnostycznego.

---

## M. Poprawiony Ranking Krytyczny (Serial CPU & Native)

Rzeczywisty ranking operacji w pipeline produkcyjnym:

| Pozycja | Etap | Mediana (ms) | P95 (ms) | Udział w klatce (%) |
|---|---|---:|---:|---:|
| **#1** | **Natywny `process_frame` / VideoProcessor D3D11** | **8,043 ms** | **37,817 ms** | **31,5%** |
| **#2** | **Przygotowanie mapy na CPU (`map_cpu_upload`)** | **3,087 ms** | **8,132 ms** | **12,9%** |
| **#3** | **Główny kompozytor poniżej mapy (`compose_overlay`)** | **2,283 ms** | **8,969 ms** | **9,0%** |
| **#4** | **Przygotowanie i upload gauge (`gauge_tobytes` + upload)** | **2,249 ms** | **6,724 ms** | **8,9%** |
| **#5** | **`CPU_ABOVE_MAP` (compose + crop + upload total)** | **1,040 ms** | **5,040 ms** | **4,1%** |
| **#6** | **Dekoder D3D11VA (`MF ReadSample` / decode wait)** | **0,745 ms** | **2,966 ms** | **3,1%** |
| **#7** | **Ekstrakcja dirty rects HUD (`HUD dirty extract`)** | **0,406 ms** | **1,136 ms** | **1,6%** |

---

## N. Budżet 60 FPS (16,667 ms / Frame)

| Etap | Mediana (ms) | P95 (ms) | % Budżetu 16,667 ms | Klasyfikacja |
|---|---:|---:|---:|---|
| Natywny `process_frame` / VP | 8,043 | 37,817 | **48,26%** | **MAJOR BOTTLENECK** |
| Przygotowanie mapy na CPU (`map_cpu_upload`) | 3,087 | 8,132 | **18,52%** | **MAJOR BOTTLENECK** |
| Główny kompozytor (`compose_overlay` BELOW) | 2,283 | 8,969 | **13,70%** | **SECONDARY** |
| Speed gauge CPU prep & upload | 2,249 | 6,724 | **13,49%** | **SECONDARY** |
| **`CPU_ABOVE_MAP` total** | **1,040** | **5,040** | **6,24%** | **NOT SIGNIFICANT** |
| Dekoder D3D11VA availability | 0,745 | 2,966 | **4,47%** | MINOR |
| HUD dirty extract & copy | 0,406 | 1,136 | **2,44%** | MINOR |

---

## O. Klasyfikacja `FULL_CANVAS_ABOVE`

```text
FULL_CANVAS_ABOVE = NOT SIGNIFICANT
```

**Uzasadnienie techniczne:**
1. Canvas 4K nie jest alokowany co klatkę (0 alokacji w runtime dzięki `_THREAD_CANVAS`).
2. Czyszczenie regionalne zajmuje 7,3 mikrosekundy.
3. Całkowity czas kompozycji, przycinania, skanowania i uploadu warstwy ABOVE to **~1,04 ms** (6,2% budżetu 60 FPS).
4. Usunięcie warstwy ABOVE w całości przynosi jedynie **+0,207 FPS** zysku.

---

## P. Region-Aware Feasibility Analysis (Analiza Wykonalności)

Model teoretyczny region-aware composition dla ABOVE:
```text
Layout indicators after track_map
  ↓
Wyznaczenie obszaru lokalnego (min_x, min_y, max_x, max_y)
  ↓
Alokacja lokalnego canvasu RGBA (np. 559×190 zamiast 3840×2160)
  ↓
Przesunięcie współrzędnych renderowania wskaźników o wektor (-min_x, -min_y)
  ↓
Renderowanie i upload bezpośredni
```

### Ryzyka i ocena:
1. **Ryzyko translacji współrzędnych**: `rotated_paste`, pozycjonowanie tekstu, outline, anchor points, custom texts i adnotacje wymagają bezwzględnych współrzędnych lub relatywnej translacji. Wprowadzenie offsetu grozi regresją pikselową.
2. **Problem rzadkich, odległych wskaźników (Sparse Distant Elements)**: Jak wykazały testy w sekcji F, gdy wskaźniki ABOVE znajdują się w przeciwległych rogach (np. TL 5% i BR 95%), pojedynczy bounding box union obejmuje niemal całą klatkę 4K (`3840 × 2111` = 8,1 mln pikseli), co generuje narzut skanowania alpha rzędu **42 ms**. Obsługa tego wymagałaby multi-region compositora o dużej złożoności.
3. **Potencjalny zysk**: Maksymalnie **~0,5–0,7 ms**, czyli < +1 FPS.
4. **Wniosek**: Nieopłacalne.

---

## Q. Potwierdzone Problemy Wydajnościowe (Confirmed Issues)

1. **SEVERITY: HIGH — Natywny `process_frame` / VideoProcessor D3D11 completion**:
   - Plik: `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp` -> `ProcessFrame()`
   - Mediana = **8,043 ms**, P95 = **37,817 ms**
   - Przyczyna: Wielokrotne operacje VideoProcessora (VPBlt NV12->NV12, blend HUD, blend gauge, blend map, blend above) oraz synchronizacja D3D11 przed wysłaniem klatki do AMF.

2. **SEVERITY: HIGH — Przygotowanie mapy na CPU (`map_cpu_upload`)**:
   - Plik: `src/ffmpeg/amd_native_exporter.py` -> `render_map_working_image()`
   - Mediana = **3,087 ms**, P95 = **8,132 ms**
   - Przyczyna: Pełne rastrowanie obrazu roboczego mapy 692×692 na CPU (tło, ślad GPS, kropka pozycji) dla każdej klatki i serializacja do RGBA.

3. **SEVERITY: MEDIUM — Główny kompozytor (`compose_overlay` BELOW)**:
   - Plik: `src/indicators/compositor.py` -> `compose_overlay()`
   - Mediana = **2,283 ms**, P95 = **8,969 ms**
   - Przyczyna: Seryjne formatowanie tekstów, ładowanie fontów i operacje `rotated_paste` dla wskaźników na CPU.

4. **SEVERITY: MEDIUM — Serializacja Speed Gauge (`gauge_tobytes`)**:
   - Plik: `src/ffmpeg/amd_native_exporter.py` -> linie 1957–1965
   - Mediana = **1,026 ms**, P95 = **3,279 ms**
   - Przyczyna: `gauge_img.tobytes("raw", "RGBA")` wykonujące kopię ~1,37 MB co klatkę na CPU.

---

## R. Podejrzewane Problemy (Suspected Issues)

- Zatory w kolejce AMF (`AMF outstanding` = 10–11 klatek) wpływające na throttling wątku głównego.
- Pauzy Garbage Collectora w Pythonie (1810 wywołań GC, pauzy do 24–30 ms) podbijające P95 w frame accounting.

---

## S. Rekomendacja ETAPU 8E

Wybór dokładnie jednego kolejnego etapu:

```text
ETAP 8E — optymalizacja przygotowania mapy CPU (map_cpu_upload) i serializacji gauge
```

*(Alternatywnie, jeśli priorytetem jest ścieżka natywna D3D11: `ETAP 8E — profilowanie i optymalizacja natywnego VideoProcessor::ProcessFrame`).*

**Uzasadnienie:**
`CPU_ABOVE_MAP` jest już zoptymalizowany (1,04 ms). Kolejnym największym wąskim gardłem po stronie Pythona/CPU jest `map_cpu_upload` (3,09 ms) oraz `gauge_tobytes` (1,03 ms), które sumarycznie kosztują **~4,12 ms** serial CPU. Ich optymalizacja przyniesie bezpośredni, mierzalny wzrost FPS.

---

## Stan Testów Po ETAPIE 8D

```text
336 passed, 3 failed, 17 skipped
```
Znane, wcześniejsze failure'y:
- `tests/test_amd_native_etap4.py`
- `tests/test_qp_analyzer.py`
- `tests/test_render_tab.py`

Brak jakichkolwiek nowych regresji testowych.

**ETAP 8D — COMPLETE.**
