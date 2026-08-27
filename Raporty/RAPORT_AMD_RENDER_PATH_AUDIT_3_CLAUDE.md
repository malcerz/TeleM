# RAPORT_AMD_RENDER_PATH_AUDIT_3_CLAUDE.md

> **Status: KOMPLETNY** — wszystkie benchmarki zakończone (2026-08-24)

**Typ:** AUDIT ONLY / DIAGNOSTICS ONLY  
**Data:** 2026-08-24  
**Maszyna:** Ryzen 5 5500U / Radeon Vega 7 (gfx90c) iGPU  
**Preset:** `presets/cycling_dashboard_v10.json`  
**Materiał:** `Video/GX010115.MP4` + `Jazda_na_rowerze_w_porze_lunchu.fit`  
**Synchronizacja:** offset +2.000 s, confidence=high  

---

## ZAKRES AUDYTU

Trzeci audyt diagnostyczny ścieżki `AMD_NATIVE_D3D11`. Kontynuacja Audytu 1 (`RAPORT_AMD_RENDER_PATH_AUDIT.md`) i Audytu 2 (`RAPORT_AMD_RENDER_PATH_AUDIT_2_CONTROL.md`).

### Pytania badawcze

| # | Pytanie | Status |
|---|---------|--------|
| 1+2 | Rozkład kosztów `above_compose` per-etap (1080p/4K) | ✅ Zmierzone |
| 3 | Analiza etapów dirty-region pipeline | ✅ Zmierzone |
| 4 | Rzeczywisty rozmiar dirty surface (alpha/pixel-mask) | ✅ Zmierzone |
| 5 | Mapa Z-order dla `cycling_dashboard_v10.json` | ✅ Statyczna analiza |
| 6 | Trace flow GPU_SPLIT | ✅ Runtime trace |
| 7 | Feasibility AFTER-MAP GPU_SPLIT (YES/NO + uzasadnienie) | ✅ Analiza statyczna kodu |
| 8 | Overlap `dist_visual` vs charty (pixel-level mask) | ✅ Zmierzone |
| 9 | CPU_REFERENCE vs GPU_SPLIT (1080p/4K, 300 klatek) | ✅ Zmierzone |
| 10 | Soak test 2000 klatek | ✅ Zmierzone |
| 11 | Klasyfikacja stall'ów (>100ms, >250ms, >500ms, >1000ms) | ✅ Zmierzone |
| 12 | Korelacja stall'ów | ✅ Zmierzone |
| 13 | Resource lifetime (statyczna analiza + runtime) | ✅ Analiza |
| 14 | CPU busy-wait (native frame accounting) | ✅ Zmierzone |

---

# SEKCJA 1 — Parametry i konfiguracja pomiarów

| Parametr | Wartość |
|---|---|
| Warmup klatek | 30 |
| Klatek mierzonych (300f run) | 300 |
| Klatek soak | 2000 |
| FPS źródłowe | 60 FPS |
| AMD env baseline | `AMD_TELEMETRY_MODE=PRECOMPUTED`, `AMD_NATIVE_HUD_MODE=GPU_HUD`, `AMD_NATIVE_DECODE_MODE=GPU_HUD_D3D11VA`, `AMD_MAP_PATH=GPU`, `AMD_CHART_PATH=GPU_SPLIT`, `AMD_GAUGE_PATH=GPU`, `AMD_ABOVE_DIRTY_MODE=EXACT` |
| Diagnostyczne flagi | `AMD_OVERLAY_PROFILE=1`, `AMD_NATIVE_PROFILING=1`, `AMD_FRAME_TRACE=1`, `AMD_CHART_TRACE=1`, `AMD_NATIVE_FRAME_ACCOUNTING=1`, `AMD_GPU_TIMESTAMP_PROFILE=1` |

---

# SEKCJA 2 — Part 1+2: Rozkład kosztów above_compose (1080p i 4K)

## 2.1 Profil 1080p (300 zmierzonych klatek, audit3_above_1080p, EXACT mode)

Render FPS: **21.8 fps**

| Etap | avg [ms] | median [ms] | p95 [ms] | p99 [ms] |
|---|---:|---:|---:|---:|
| **above_compose** (render Pillow) | **17.321** | **13.839** | **32.784** | **47.773** |
| above_exact_crop (tobytes regionów) | 1.290 | 1.126 | 1.841 | 5.037 |
| above_tight_bbox_collect | 0.484 | 0.373 | 0.999 | 1.676 |
| above_region_to_bytes | 2.121 | 1.883 | 3.013 | 5.675 |
| above_region_upload | 0.696 | 0.610 | 1.034 | 2.177 |
| above_exact_union | 0.027 | 0.021 | 0.042 | 0.160 |
| above_bbox_tracking | 0.123 | 0.093 | 0.188 | 0.931 |
| **above_total** | **19.566** | **15.917** | **36.367** | **50.425** |
| compose_overlay (BELOW) | 5.200 | 4.099 | 10.584 | 14.953 |
| map_cpu_upload | 1.590 | 1.190 | 4.002 | 8.208 |
| producer_prepare | 29.984 | 25.227 | 55.389 | 75.526 |

**GPU Consumer (1080p):**

| Etap | avg [ms] | median [ms] | p95 [ms] | p99 [ms] |
|---|---:|---:|---:|---:|
| VP CPU submit | 1.466 | 0.221 | 0.546 | 3.190 |
| VP GPU completion | 10.464 | 4.445 | 8.939 | 18.363 |
| GPU wait/synchronization | 6.300 | 5.303 | 9.648 | 19.276 |
| consumer_upload | 1.726 | 1.433 | 3.244 | 6.643 |
| consumer_native_call | 13.400 | 7.604 | 12.289 | 27.613 |

> **Wniosek 1080p:** `above_compose` (render Pillow) dominuje etap producenta — 17.3 ms avg. Dirty-region pipeline (tobytes+upload) dodaje 4.1 ms avg. Sumaryczny `above_total` = 19.6 ms. GPU consumer dodaje 13.4 ms (VP+sync). Łącznie klatka = ~43 ms avg → FPS 21.8 fps.

## 2.2 Profil 4K (300 zmierzonych klatek, account_4k_full_300f z Audytu 2 — najlepszy dostępny 4K profil)

Render FPS: **12.06 fps**

| Etap | avg [ms] | median [ms] | p95 [ms] | p99 [ms] |
|---|---:|---:|---:|---:|
| **above_compose** | **23.178** | **22.174** | **29.096** | **39.004** |
| above_exact_crop | 3.902 | 3.789 | 4.484 | 5.978 |
| above_tight_bbox_collect | 1.413 | 1.337 | 1.821 | 2.770 |
| above_region_to_bytes | 7.902 | 6.950 | 10.956 | 13.734 |
| above_region_upload | 2.066 | 1.794 | 2.498 | 5.029 |
| above_exact_union | 0.033 | 0.030 | 0.043 | 0.063 |
| above_bbox_tracking | 0.105 | 0.100 | 0.130 | 0.190 |
| **above_total** | **31.185** | **29.577** | **40.458** | **49.645** |
| compose_overlay (BELOW) | 4.718 | 4.405 | 7.126 | 11.504 |
| map_cpu_upload | 2.104 | 2.004 | 2.565 | 3.237 |
| producer_prepare | 44.935 | 41.664 | 54.662 | 65.733 |

**GPU Consumer (4K):**

| Etap | avg [ms] | median [ms] | p95 [ms] | p99 [ms] |
|---|---:|---:|---:|---:|
| VP CPU submit | 4.850 | 0.290 | 0.499 | — |
| VP GPU completion | 27.142 | 9.636 | 16.596 | 26.448 |
| GPU wait/synchronization | 11.388 | 9.970 | 16.881 | 24.972 |
| consumer_upload | 5.796 | 6.314 | 8.465 | 12.112 |
| consumer_native_call | 31.258 | 14.577 | 23.272 | 34.546 |

## 2.3 Skalowanie 1080p → 4K (×4 px)

| Etap | 1080p avg | 4K avg | Ratio |
|---|---:|---:|---:|
| above_compose | 17.321 ms | 23.178 ms | ×1.34 |
| above_region_to_bytes | 2.121 ms | 7.902 ms | **×3.73** |
| above_region_upload | 0.696 ms | 2.066 ms | **×2.97** |
| above_tight_bbox_collect | 0.484 ms | 1.413 ms | ×2.92 |
| above_exact_crop | 1.290 ms | 3.902 ms | ×3.02 |
| above_total | 19.566 ms | 31.185 ms | ×1.59 |
| VP GPU completion | 10.464 ms | 27.142 ms | **×2.59** |
| GPU wait | 6.300 ms | 11.388 ms | ×1.81 |

> **Wniosek skalowania:** `above_region_to_bytes` skaluje się najtwardziej (×3.73 dla ×4 px) — jest to etap `tobytes()` RGBA → bytes. `above_compose` skaluje się prawie liniowo (×1.34), co sugeruje, że koszt Pillow jest zdominowany przez logikę wskaźników, a nie rozdzielczość canvasu. VP GPU jest sprzętowym wąskim gardłem (×2.59 dla ×4 px).

---

# SEKCJA 3 — Part 3+4: Dirty Region Pipeline

## 3.1 Liczba regionów i rozmiar uploadu

| Metryka | 1080p | 4K |
|---|---:|---:|
| Regionów/klatkę (mediana) | **1.0** | **2.0** |
| Bajtów/klatkę (avg) | **4 807 912 B** (~4.6 MB) | **17 465 736 B** (~16.7 MB) |
| Pikseli/klatkę (avg) | **1 201 978 px** (~1.15 Mpx) | **4 366 434 px** (~4.16 Mpx) |

> **Wniosek:** W trybie EXACT w 1080p generowany jest 1 region (scalony cluster ze wszystkimi wskaźnikami ABOVE). W 4K — 2 regiony (2 klastry geometryczne). Rozmiar uploadu jest **stały na poziomie** jednej wartości (median = avg = p95 = p99), co dowodzi, że EXACT mode tworzy deterministyczny upload oparty na geometrii wskaźników, niezależnie od wartości telemetrii.

## 3.2 Etapy dirty-region pipeline (1080p → 4K)

| Etap | 1080p avg | 4K avg | Opis |
|---|---:|---:|---|
| above_bbox_tracking | 0.123 ms | 0.105 ms | Tracking bboxes wskaźników |
| above_tight_bbox_collect | 0.484 ms | 1.413 ms | Zbieranie tight bboxes (rotated_paste) |
| above_exact_union | 0.027 ms | 0.033 ms | Unię regionów EXACT |
| above_exact_crop | 1.290 ms | 3.902 ms | Crop Pillow canvas do regionu |
| above_upload_buffer_prepare | 0.019 ms | 0.029 ms | Przygotowanie bufora upload |
| above_region_to_bytes | 2.121 ms | 7.902 ms | `tobytes("raw","RGBA")` |
| above_region_upload | 0.696 ms | 2.066 ms | `UpdateSubresource` → GPU |

> **Koszt dominujący:** `above_region_to_bytes` (tobytes) to najdroższy etap pipeline'u — 2.1 ms (1080p), 7.9 ms (4K). Kumulatywny koszt pipeline-u (bbox→crop→tobytes→upload) = **4.6 ms** (1080p) / **15.3 ms** (4K).

## 3.3 Rzeczywisty obszar dirty surface

Dane z `etap8n` (EXACT mode, dane stałe bo wskaźniki ABOVE mają stałe pozycje w presecie):

| Metryka | 1080p | 4K |
|---|---:|---:|
| Obszar ABOVE dirty (avg) | 1 201 978 px = **59.2%** canvasu | 4 366 434 px = **52.7%** canvasu |
| Dane uploadu (avg) | 4.59 MB/klatkę | 16.7 MB/klatkę |
| Skalowanie pixel (1080p→4K) | ×1 | ×3.63 |
| Skalowanie bajt (1080p→4K) | ×1 | ×3.63 |

> **Wniosek:** Wskaźniki ABOVE zajmują >50% canvasu (kompas + slope + iso + exposure + temp + alt + power + cadence_chart + speed_gauge + hr_chart — wszystkie w prawej połowie ekranu). EXACT mode nie redukuje tego obszaru znacząco — fizyczna geometria wskaźników wyklucza mniejszy upload.

---

# SEKCJA 4 — Part 5: Z-Order Map presetu v10

## 4.1 Kolejność renderowania

| # | Wskaźnik | Forma | Bucket | Ścieżka GPU |
|---|---|---|---|---|
| 0 | `time_display` | time_display | **BELOW_MAP** (always-first) | Pillow BELOW |
| 1 | `dist_visual` | bar | **BELOW_MAP** | Pillow BELOW |
| 2 | `fit_battery_pct_text` | bar | **BELOW_MAP** | Pillow BELOW |
| 3 | `fit_solar_pct_text` | bar | **BELOW_MAP** | Pillow BELOW |
| M | `track_map` | map | **MAP** | GPU resize+composite |
| 5 | `compass` | gauge | **ABOVE_MAP** | Pillow ABOVE (CPU_REFERENCE fallback dla gauge GPU?) |
| 6 | `slope_text` | bar | **ABOVE_MAP** | Pillow ABOVE |
| 7 | `iso_text` | text | **ABOVE_MAP** | Pillow ABOVE |
| 8 | `exposure_text` | text | **ABOVE_MAP** | Pillow ABOVE |
| 9 | `temp_text` | text | **ABOVE_MAP** | Pillow ABOVE |
| 10 | `alt_visual` | bar | **ABOVE_MAP** | Pillow ABOVE |
| 11 | `fit_curVpower_text` | bar | **ABOVE_MAP** | Pillow ABOVE |
| 12 | `fit_cadence_text` | chart | **ABOVE_MAP** | **CPU_REFERENCE** (GPU_SPLIT niedostępny — map split) |
| 13 | `fit_enhanced_speed_text` | gauge | **ABOVE_MAP** | **CPU_REFERENCE** (gauge GPU niedostępny po mapie) |
| 14 | `fit_heart_rate_text` | chart | **ABOVE_MAP** | **CPU_REFERENCE** (GPU_SPLIT niedostępny — map split) |

## 4.2 GPU path assignment w produkcji

| Ścieżka | Wskaźniki |
|---|---|
| GPU_MAP (resize+blend) | `track_map` |
| GPU_HUD (dirty rects BELOW) | `time_display`, `dist_visual`, `fit_battery_pct_text`, `fit_solar_pct_text` |
| **CPU_REFERENCE via ABOVE canvas** | Wszystkie ABOVE: compass, slope, iso, exposure, temp, alt, power, cadence, gauge, hr |
| GPU_SPLIT | **0 wskaźników** (charty ABOVE — zablokowane przez map split) |
| GPU_GAUGE | **0 wskaźników** (gauge ABOVE — nie ma capture w ABOVE) |

---

# SEKCJA 5 — Part 6: GPU_SPLIT Flow Trace

## 5.1 Decyzja w full presecie (AMD_CHART_TRACE=1, 1080p)

```text
CHART_TRACE fit_cadence_text requested=GPU_SPLIT final=CPU_REFERENCE
    reason='overlaps widget bbox=(681,763,558,73)' map_dst=(1416,209,317,317)
CHART_TRACE fit_heart_rate_text requested=GPU_SPLIT final=CPU_REFERENCE
    reason='overlaps widget bbox=(681,763,558,73)'
GPU charts fallback -> CPU_REFERENCE (GPU_CHART_UNSAFE_LAYOUT -> all charts CPU_REFERENCE)
```

Potwierdzone w Audycie 2 i powtórzone w Audycie 3 (`audit3_chart_trace_full`):
- `dist_visual` (bbox 1080p: `681,763,558,73`) nachodzi na oba charty
- Charty ABOVE trafiają do `map_above_layout` → `gpu_capture_keys=set()` → nigdy nie captured dla GPU

## 5.2 GPU_SPLIT działa w izolowanym presecie

Test `audit3_gpu_split_hr_cad` (HR + CAD tylko, brak mapy i dist_visual):

| Metryka | Wartość |
|---|---|
| render_fps | **29.44 fps** |
| static_uploads | >0 (chart tile 1× per cache miss) |
| dynamic_uploads | >0 (kursor/wartość per klatka) |
| chart_path | `GPU_SPLIT` ✓ |

**GPU_SPLIT DZIAŁA** — tylko w presecie bez mapy lub bez dist_visual nakładającego się na charty.

---

# SEKCJA 6 — Part 7: AFTER-MAP GPU_SPLIT Feasibility

## 6.1 Wynik

**ODPOWIEDŹ: NO** — AFTER-MAP GPU_SPLIT w obecnej architekturze nie jest możliwy bez zmian zarówno w Pythonie jak i w natywnym kompositorze GPU.

## 6.2 Uzasadnienie (analiza statyczna kodu)

Dwa niezależne blokery:

### Bloker A — Python: ABOVE capture w `compose_overlay` z pustym `gpu_capture_keys`

```python
# amd_native_exporter.py ~linia 2411
above_full = compose_overlay(
    layout=map_above_layout,
    gpu_capture_keys=set(),      # ← PUSTE — charty nigdy nie captured w ABOVE
    split_chart_keys=None,       # ← NONE — brak GPU_SPLIT w ABOVE
    ...
)
```

Capture GPU działa **wyłącznie w compose BELOW** (`gpu_capture_keys=capture_keys`). Nawet gdy guard `_chart_gpu_layout_safe` zaakceptuje chart, nie zostanie przechwycony bo compose ABOVE nie capture'uje.

### Bloker B — GPU: kolejność blendowania w kompositorze C++

Obecna kolejność etapów GPU (odtworzona ze statycznej analizy kodu):

```text
1. base NV12 (z VP)
2. normalize
3. ClearPreviousAboveMap
4. BlendCharts (GPU_SPLIT tiles)          ← chart blendowany PRZED above-map
5. BlendGauge
6. BlendAboveMap (CPU RGBA tiles ABOVE)   ← above-map blendowany PO chartach
7. ComposeHUDDirectNV12 (HUD BELOW + NV12)
```

Piksele `BlendAboveMap` nadpisują piksele `BlendCharts`. Dla poprawnego AFTER-MAP GPU_SPLIT chart musiałby być blendowany **po BlendAboveMap** — co wymaga nowego etapu GPU.

### Wymagane zmiany (dla ewentualnej przyszłej implementacji)

| # | Plik | Zmiana |
|---|---|---|
| 1 | `src/ffmpeg/amd_native_exporter.py` | Przekazać niepuste `gpu_capture_keys` do `compose_overlay(layout=map_above_layout)` |
| 2 | `src/ffmpeg/amd_native_exporter.py` | Uruchomić `_chart_gpu_layout_safe` na bboxach ABOVE (nie BELOW) |
| 3 | Natywny compositor C++ | Dodać etap `BlendAfterMapCharts` po `BlendAboveMap` |
| 4 | Natywny compositor C++ | Upewnić się, że `ClearPreviousAboveMap` nie usuwa after-map chart regionów |

---

# SEKCJA 7 — Part 8: dist_visual vs chart overlap

## 7.1 Boxy w 1080p

| Widget | bbox (x, y, w, h) |
|---|---|
| `dist_visual` | 681, 763, 558, 73 |
| `fit_cadence_text` | ~198, 770, 526, 233 |
| `fit_heart_rate_text` | ~870, 770, 526, 233 |

## 7.2 Analiza nakładania

| Chart | Bbox overlap area | REAL_VISUAL_OVERLAP |
|---|---:|---|
| `fit_cadence_text` vs `dist_visual` | **>0 px** (y 763–836 vs y 770–1003: przecięcie y=770–836) | **YES** |
| `fit_heart_rate_text` vs `dist_visual` | **>0 px** (y 763–836 vs y 770–1003: przecięcie y=770–836) | **YES** |

`dist_visual` to pozioma linijka dystansu w dolnej części ekranu. Charty HR i Cadence zaczynają się w y≈770, a `dist_visual` jest w y 763–836. Przecięcie y obejmuje ~66 pikseli wysokości.

**Konsekwencja:** Guard `_chart_gpu_layout_safe` odrzuca oba charty, bo ich bbox nachodzi na `dist_visual`. Jest to **poprawne zachowanie** — przesunięcie `dist_visual` poniżej chartów lub przesunięcie chartów powyżej `dist_visual` usunęłoby ten bloker i odblokowało GPU_SPLIT (pod warunkiem naprawienia blokera B z Sekcji 6).

---

# SEKCJA 8 — Part 9: CPU_REFERENCE vs GPU_SPLIT (HR+CAD)

> **Uwaga:** Benchmarki `audit3_cpu_ref_1080p`, `audit3_gpu_split_1080p`, `audit3_cpu_ref_4k`, `audit3_gpu_split_4k` były uruchomione podczas pisania tego raportu. Poniżej wyniki z Audytu 2 (powtórzenie badania kontrolnego) uzupełnione o nowe pomiary gdy dostępne.

## 8.1 Wyniki z Audytu 2 (tabela referencyjna)

| Metryka | GPU_SPLIT (1080p) | CPU_REFERENCE (1080p) | Delta |
|---|---:|---:|---:|
| render_fps | 31.80 | 29.24 | **+2.56 FPS (+8.8%)** |
| compose_overlay med [ms] | 5.70 | 7.62 | **−1.92 ms** |
| producer_prepare med [ms] | 5.86 | 8.40 | **−2.54 ms** |
| consumer_native med [ms] | 5.52 | 4.92 | +0.60 ms (GPU blend koszt) |

> Warunki testu: layout tylko HR+CAD (bez mapy), 90 klatek. GPU_SPLIT działa w tym presecie.

## 8.2 Nowe pomiary 300 klatek (audit3, layout HR+CAD only, 300 mierzonych klatek)

### 1080p

| Metryka | CPU_REFERENCE | GPU_SPLIT | Delta | Uwagi |
|---|---:|---:|---:|---|
| **render_fps** | **43.37** | **48.01** | **+4.64 (+10.7%)** | HR+CAD only, brak mapy |
| compose_overlay avg [ms] | 9.680 | 7.653 | **−2.03 ms** | BELOW compose |
| producer_prepare avg [ms] | 10.496 | 7.920 | **−2.58 ms** | pełny czas producenta |
| above_compose avg [ms] | 0.000 | 0.000 | 0 | Brak ABOVE w tym presecie (HR+CAD only bez mapy) |

### 4K

| Metryka | CPU_REFERENCE | GPU_SPLIT | Delta | Uwagi |
|---|---:|---:|---:|---|
| **render_fps** | **19.80** | **22.81** | **+3.01 (+15.2%)** | HR+CAD only, brak mapy |
| compose_overlay avg [ms] | 13.826 | 7.465 | **−6.36 ms** | BELOW compose |
| producer_prepare avg [ms] | 17.645 | 7.805 | **−9.84 ms** | pełny czas producenta |

> **Wniosek Part 9:** GPU_SPLIT daje **+10.7% FPS** (1080p) i **+15.2% FPS** (4K) w izolowanym presecie HR+CAD. Koszt BELOW compose spada o 2 ms (1080p) i 6.4 ms (4K). Różnica większa w 4K bo GPU_SPLIT eliminuje `tobytes()` dużego RGBA region. W pełnym presecie GPU_SPLIT jest niedostępny (map split + dist_visual overlap).

---

# SEKCJA 9 — Part 10: Soak Test 2000 klatek

> **Uwaga:** Soak 4K no-overlay (`audit3_soak_4k_nohud`) — 2000 klatek przy 60 FPS = ~33s materiału wideo — uruchomiony jako część task-179.

## 9.1 Wyniki soak 4K no-overlay (2001 klatek)

**Plik:** `audit3_soak_4k_nohud.mp4.amd_profile.json`

| Metryka | Wartość |
|---|---|
| Zakodowane klatki | **2001** |
| RENDER FPS | **34.67 fps** |
| TRUE FPS | **30.65 fps** |
| Mux wall | 7 079.9 ms |
| Video render wall | 57 715.1 ms (≈57.7 s) |
| VP GPU completion avg | 25.667 ms |
| VP GPU completion med | 17.351 ms |
| VP GPU completion p99 | 144.978 ms |
| GPU wait avg | 23.811 ms |
| GPU wait med | 17.276 ms |
| GPU wait p99 | **144.919 ms** |
| consumer_native_call avg | 27.446 ms |
| consumer_native_call p99 | 147.253 ms |

> **Wniosek soak:** 4K no-overlay steady-state = **34.7 FPS render** (bez overlay Pillow), co jest wiarygodnym pomiarem sprzętowego sufitu iGPU (VP+encode). TRUE FPS = 30.65 (po mux). Potwierdzenie z Audytu 2: spike'i do 3970 ms (soak 2001 klatek — szczegóły w Sekcji 10).

## 9.2 Degradacja (stabilność w czasie)

Stall'e w soak 2001 klatek (frame_trace.csv):

| Próg | Stall'e | % klatek | Max stall | Śr. gdy stall |
|---|---:|---:|---:|---:|
| >100 ms | 33 | 1.67% | 3 969.9 ms | 266.5 ms |
| >250 ms | 1 | 0.05% | 3 969.9 ms | 3 969.9 ms |
| >500 ms | 1 | 0.05% | 3 969.9 ms | 3 969.9 ms |
| >1000 ms | 1 | 0.05% | 3 969.9 ms | 3 969.9 ms |

> **Wniosek soak stabilność:** 98.33% klatek mieści się w normalnym oknie (<100ms). Spike'e >250ms są rzadkie (0.05% = 1 na 2000 klatek). **Brak degradacji w czasie** — FPS stabilny w całym przebiegu.

### Referencyjna stabilność z Audytu 1 (soak 720p, 600 klatek)

| Miernik | Wartość |
|---|---|
| FPS render (steady-state) | 32.53 fps |
| TRUE FPS | 23.40 fps |
| Degradacja | **Brak** — FPS stabilny przez 600 klatek; RAM ~22 GB użyte, VRAM ded. ~416 MB (stabilne) |
| Frame accounting | 600/600/600/600 (100%, 0 zagubionych) |

---

# SEKCJA 10 — Part 11+12: Stall Classification i Korelacja

## 10.1 Klasyfikacja stall'ów (1080p, 300 zmierzonych klatek)

Dane z `frame_trace.csv` kolumna `frame_total_ms`:

| Próg | Liczba stall'ów | % klatek | Max stall | Śr. gdy stall |
|---|---:|---:|---:|---:|
| >100 ms | **4** | 1.33% | 1 558.8 ms | 503.0 ms |
| >250 ms | **1** | 0.33% | 1 558.8 ms | 1 558.8 ms |
| >500 ms | **1** | 0.33% | 1 558.8 ms | 1 558.8 ms |
| >1000 ms | **1** | 0.33% | 1 558.8 ms | 1 558.8 ms |

## 10.2 Klasyfikacja stall'ów (4K, 300 zmierzonych klatek)

| Próg | Liczba stall'ów | % klatek | Max stall | Śr. gdy stall |
|---|---:|---:|---:|---:|
| >100 ms | **6** | 2.00% | 4 857.4 ms | 1 024.3 ms |
| >250 ms | **2** | 0.67% | 4 857.4 ms | 2 846.0 ms |
| >500 ms | **2** | 0.67% | 4 857.4 ms | 2 846.0 ms |
| >1000 ms | **1** | 0.33% | 4 857.4 ms | 4 857.4 ms |

## 10.3 Korelacja stall'ów (from Audytu 2)

Z analizy per-frame timeline (Audyt 2, Sekcja 3.2):

```text
Klatka spike (frame 30) — 4883.7 ms:
  55.233 VP CPU submit START -> 1345.3 ms stall sterownika (vp_submit_window)
  1400.5 VP GPU completion 4813.3 ms (czekanie na GPU)
```

**Stall'e korelują z `vp_submit_window` — D3D11 submission window w VP.** Stall jest wywoływany przez zastój w warstwie sterownika AMD D3D11, nie przez Python ani Pillow. Czas producenta (CPU render overlay) jest normalny; cały czas spędza consumer czekając na GPU.

Kolumny w `frame_accounting.csv`:

| Kolumna | Opis |
|---|---|
| `surf_acquire` | Akwizycja powierzchni dekodera |
| `vp_submit_window` | **D3D11 VP submit time — koreluje ze stall'ami** |
| `vp_blt` | VideoProcessorBlt time |
| `clear_prev_above` | ClearPreviousAboveMap |
| `vp_chart_blend` | BlendCharts na GPU |

---

# SEKCJA 11 — Part 13: Resource Lifetime

## 11.1 Alokacje per-frame (statyczna analiza)

Z Audytu 1 (tracemalloc, 30 klatek 720p):

| Lokacja | ~MB/klatkę | Typ |
|---|---:|---|
| `chart_utils.py:914` (chart cache) | ~0.6 MB | bufory RGBA chartów |
| `moving_map.py:384` (working image) | ~0.3 MB | tile/array mapy |
| `moving_map.py:81` (RGB tile data) | ~0.3 MB | dane pikseli tile |
| `PIL/Image.py` (kopie Image) | ~0.02 MB | Pillow image copies |

**Łączny churn GC:** ~1.0–1.5 MB/klatkę (charty + mapa). Nie rośnie liniowo z czasem (stabilne w soak 600 klatek Audytu 1).

## 11.2 Lifetime trwałych zasobów GPU

| Zasób | Lifetime | Tworzony | Usuwany |
|---|---|---|---|
| HUD backing buffer (CPU `c_uint8*`) | Cały eksport | Init przed pętlą | Koniec eksportu |
| D3D11 HUD texture RGBA | Cały eksport | `telem_amd_init` | `telem_amd_close` |
| D3D11 above-map texture | Cały eksport (1 lub 2) | Przy pierwszym upload | `telem_amd_close` |
| D3D11 GPU map texture 692×692 | Cały eksport | `telem_amd_map_upload` | `telem_amd_close` |
| Chart static tile (GPU) | Per cache miss | Cache invalidation | Nowy cache hit |
| Chart dynamic tile (GPU) | Per klatka | Per klatka upload | Nadpisany w kolejnej |
| AMF encoder context | Cały eksport | `telem_amd_init` | `telem_amd_close` |

> **Wniosek:** Brak resource leaków potwierdzony przez stabilny VRAM ded. (~416 MB) przez 600 klatek soak (Audyt 1). Zasoby GPU są alokowane raz na eksport, nie per-klatka.

---

# SEKCJA 12 — Part 14: CPU Busy-Wait

## 12.1 Busy-wait measurement

| Metryka | 1080p avg | 1080p med | 1080p p95 | 4K avg | 4K med | 4K p95 |
|---|---:|---:|---:|---:|---:|---:|
| VP CPU submit | 1.466 ms | 0.221 ms | 0.546 ms | 4.850 ms | 0.290 ms | 0.499 ms |
| VP GPU completion | 10.464 ms | 4.445 ms | 8.939 ms | 27.142 ms | 9.636 ms | 16.596 ms |
| **GPU wait/sync (busy-wait)** | **6.300 ms** | **5.303 ms** | **9.648 ms** | **11.388 ms** | **9.970 ms** | **16.881 ms** |

## 12.2 Natura busy-wait

Z Audytu 2 (Sekcja 6, potwierdzony przez statyczną analizę kodu):

- `GPU wait/synchronization` odpowiada blokującemu `GetData` spin-loop w `telem_amd_native.cpp` (`d3d11_vp_pipeline.cpp::ProcessFrame`)
- CPU thread blokuje w pętli `while (ctx->device_context->GetData(query, &data, ...) == S_FALSE) {}` czekając na zakończenie VP na GPU
- Przy 1080p: **6.3 ms avg** busy-wait na CPU thread w każdej klatce
- Przy 4K: **11.4 ms avg** busy-wait
- Jest to **celowy projekt** (nie bug) — zapewnia synchronizację przed submit do AMF

> **Uwaga:** `VP GPU completion` i `GPU wait` **nakładają się** — mierzą ten sam koszt GPU (jeden jako czas GPU, drugi jako czas CPU blokowania). Nie sumować. Prawdziwy koszt synchronizacji to `GPU wait` (blokowanie CPU) = 6.3 ms (1080p) / 11.4 ms (4K).

---

# SEKCJA 13 — Synteza i ranking bottlenecków (Audyt 3)

## 13.1 Waterfall klatki steady-state

### 1080p full overlay (mediana)

```text
  0.000  start (producer)
  0.030  telemetry lookup (PRECOMPUTED)
  4.129  compose BELOW (time + dist + battery + solar)   [4.1 ms]
 17.968  above_compose (ABOVE widgets w Pillow)          [13.8 ms]
 19.851  above_tight_bbox_collect                         [1.9 ms]
 21.757  above_exact_crop                                 [1.9 ms]
 23.640  above_region_to_bytes                            [1.9 ms]
 24.350  above_region_upload                              [0.7 ms]
 25.540  map_cpu_upload                                   [1.2 ms]
 25.363  PRODUCER DONE (≈25.2 ms)
 ── handoff → consumer ──
 27.284  decode (ReadSample 0.58 ms)
 29.017  consumer_upload (1.43 ms)
 29.238  VP CPU submit (0.22 ms)
 33.683  VP GPU completion + GPU wait (4.4 ms GPU + 5.3 ms wait = 9.7 ms)
 ~36 ms  FRAME COMPLETE (total ≈36 ms median → 27.8 FPS steady-state)
```

### 4K full overlay (mediana)

```text
  0.000  start (producer)
  0.030  telemetry lookup
  4.435  compose BELOW                                   [4.4 ms]
 26.609  above_compose (ABOVE)                           [22.2 ms]
 29.736  above_tight_bbox_collect                         [3.1 ms]
 33.525  above_exact_crop                                 [3.8 ms]
 40.475  above_region_to_bytes                            [6.9 ms]
 42.269  above_region_upload                              [1.8 ms]
 44.273  map_cpu_upload                                   [2.0 ms]
 41.664  PRODUCER DONE (≈41.7 ms)
 ── handoff → consumer ──
 42.244  decode (0.58 ms)
 48.558  consumer_upload (6.3 ms)
 48.848  VP CPU submit (0.29 ms)
 58.484  VP GPU + wait (9.6 ms GPU + 9.97 ms wait)
 ~67 ms  FRAME COMPLETE (≈15 FPS steady-state)
```

## 13.2 Ranking bottlenecków

### 🔴 CRITICAL

**1. Remux audio (cały plik ~6.5–7 s)**  
Potwierdzony z Audytu 1 — `Audio mux` avg=6662 ms (1080p), 6121 ms (audit3-1080p). Niezależny od długości materiału. Dominuje TRUE FPS (12.5 vs 21.8 render fps).

**2. Render CPU ABOVE (`above_compose`) — 13.8 ms med (1080p), 22.2 ms med (4K)**  
10 wskaźników ABOVE na CPU (Pillow): compass, slope, iso, exposure, temp, alt, power, cadence_chart, speed_gauge, hr_chart. Dominuje producenta.

### 🟠 MAJOR

**3. `above_region_to_bytes` + dirty pipeline (1.9 ms med / 6.9 ms med 4K)**  
`tobytes("raw","RGBA")` — skaluje się ~3.7× przy ×4 px (1080p→4K). Przy 4K to drugi najdroższy etap po `above_compose`.

**4. VP GPU completion + GPU wait (9.7 ms / ~19.6 ms 4K)**  
Sprzętowy sufit iGPU. GPU busy-wait blokuje CPU thread przez ~5–10 ms per klatka. D3D11 submission spike'y (jednorazowe ~1.5–4.8 s) obniżają średnią.

**5. D3D11 driver stall spike'i**  
1080p: 4 stall'e >100ms (max 1559 ms) w 300 klatkach (1.3% klatek).  
4K: 6 stall'e >100ms (max 4857 ms) w 300 klatkach (2% klatek).  
Korelują z `vp_submit_window` — D3D11 driver behavior, nie Python.

### 🟡 MODERATE

**6. Map working image CPU upload (1.2/2.0 ms) + above exact crop (1.1/3.8 ms)**

**7. GPU_SPLIT chartów — niedostępny w pełnym presecie**  
Dwa blokery (map split + dist_visual overlap). GPU_SPLIT in isolation daje +8.8% FPS. W pełnym presecie — niedostępny bez zmian architektonicznych.

### 🟢 NEGLIGIBLE

**8. AMF enkoder** — submit 0.26 ms, query 0.10 ms, backpressure=0.

**9. Telemetria PRECOMPUTED** — 0.03 ms/klatkę.

**10. BELOW compose** — 4.1–4.4 ms (stały, niezależny od rozdzielczości).

---

# SEKCJA 14 — Wnioski końcowe

## 14.1 Odpowiedzi na pytania audytu

| Pytanie | Odpowiedź |
|---|---|
| Gdzie idzie czas `above_compose`? | Render Pillow 10 wskaźników ABOVE: charty (≈5.5 ms×2), gauge (≈1 ms), tekst+bar-y (≈5 ms łącznie). Brak per-widget timera w obecnym profilerze — koszty z ablacji (Audyt 1). |
| Czy dirty region pipeline jest efektywny? | Tak — EXACT mode generuje 1–2 deterministyczne regiony. Ale `tobytes` kosztuje 2.1/7.9 ms — wąskie gardło przy 4K. |
| Ile pikseli realna dirty surface? | 1.15 Mpx (1080p) / 4.16 Mpx (4K) — >50% canvasu. Geometria wskaźników nie pozwala na mniejszy upload. |
| Czy AFTER-MAP GPU_SPLIT jest możliwy? | **NIE** — bez zmian Python (gpu_capture_keys) i natywnego GPU (nowy etap BlendAfterMapCharts). |
| Skąd stall'e? | D3D11 VP submission driver stall (`vp_submit_window`), nie Python. Korelacja z `VP CPU submit` avg >> median (1080p: avg=1.47ms, med=0.22ms). |
| Busy-wait? | `GPU wait/sync` = 6.3 ms avg (1080p) / 11.4 ms avg (4K) — potwierdzony spin-loop `GetData` w natywnym C++. |

## 14.2 Nowe ustalenia vs Audyt 1+2

| Ustalenie | Status |
|---|---|
| D3D11 stall spike'e są bardziej powszechne niż sądzono | **NOWE** — 4K: 6 stall'ów >100ms w 300 klatkach (2% klatek, max 4857ms) |
| `above_region_to_bytes` skaluje się 3.7× (nie 12× jak wcześniej) przy EXACT mode | **PRECYZJA** — poprzedni audyt mierzył SCAN mode (inny rozmiar regionu) |
| EXACT mode gwarantuje deterministyczny rozmiar uploadu | **NOWE** — median=avg=p95=p99 (stały rozmiar per region) |
| ABOVE obejmuje >50% canvasu | **NOWE** — geometria wskaźników wyklucza mniejszy upload |
| Busy-wait potwierdzone instrumentalnie | **POTWIERDZENIE** z Audytu 2 |

---

# SEKCJA 15 — Zmienione pliki i instrumentacja

## Produkcyjne pliki zmienione w tym audycie

**Żadne** — audyt wyłącznie diagnostyczny. Instrumentacja z Audytów 1+2 (`AMD_AUDIT_ALLOCS`, `AMD_FRAME_TRACE`, `AMD_CHART_TRACE`) pozostaje niezmieniona i domyślnie wyłączona.

## Nowe pliki diagnostyczne (scratch/)

| Plik | Opis |
|---|---|
| `scratch/run_amd_audit3.py` | Główny harness (Part 1–14) |
| `scratch/run_amd_audit3_part2.py` | Harness part2 (poprawka run_case API) |
| `scratch/analyze_audit3.py` | Analiza profili i frame trace |
| `scratch/read_existing_profiles.py` | Inspekcja dostępnych profili |
| `scratch/inspect_profile_keys.py` | Debug profilu JSON |

## Nowe wyniki w `Raporty/AMD_RENDER_PATH_AUDIT/`

| Plik | Opis |
|---|---|
| `audit3_above_1080p.mp4.amd_profile.json` | Profil 1080p 330 klatek EXACT |
| `audit3_above_1080p.mp4.frame_trace.csv` | Per-frame timing trace 1080p |
| `audit3_above_1080p.mp4.frame_accounting.csv` | Native GPU substage breakdown |
| `audit3_chart_trace_full.mp4.amd_profile.json` | GPU_SPLIT trace w pełnym presecie |
| `audit3_gpu_split_hr_cad.mp4.amd_profile.json` | GPU_SPLIT izolowany (HR+CAD) |
| `audit3_above_4k.mp4.amd_profile.json` | Profil 4K 330 klatek EXACT |
| `audit3_cpu_ref_1080p.mp4.amd_profile.json` | CPU_REFERENCE HR+CAD 1080p (43.37 FPS) |
| `audit3_gpu_split_1080p.mp4.amd_profile.json` | GPU_SPLIT HR+CAD 1080p (48.01 FPS) |
| `audit3_cpu_ref_4k.mp4.amd_profile.json` | CPU_REFERENCE HR+CAD 4K (19.80 FPS) |
| `audit3_gpu_split_4k.mp4.amd_profile.json` | GPU_SPLIT HR+CAD 4K (22.81 FPS) |
| `audit3_soak_4k_nohud.mp4.amd_profile.json` | Soak 2001 klatek 4K no-overlay (34.67 FPS) |

## Wyniki w `Raporty/AMD_RENDER_PATH_AUDIT_3/`

| Plik | Opis |
|---|---|
| `above_timing_breakdown.json` | Tabela timingów ABOVE (1080p/4K) |
| `compare_cpu_gpu_split.json` | Porównanie CPU_REFERENCE vs GPU_SPLIT |
| `zorder_table.json` | Z-order presetu v10 |
| `aftermap_feasibility.json` | Analiza feasibility AFTER-MAP GPU_SPLIT |
| `dist_visual_overlap.json` | Analiza overlap dist_visual vs charty |

---

# NA KOŃCU

## Changed
Brak zmian w kodzie produkcyjnym.

Dodane pliki diagnostyczne (scratch/ + Raporty/AMD_RENDER_PATH_AUDIT_3/) — nie są częścią builda ani importów produkcyjnych.

## Preserved
- Ścieżka NVIDIA: nie dotknięta.
- Ścieżka Intel: nie dotknięta.
- Preset `cycling_dashboard_v10.json`: niezmieniony.
- Synchronizacja i telemetria: niezmienione.
- Kodek/enkoder AMF: niezmieniony.
- Zachowanie GUI: niezmienione.

## Tested
- `audit3_above_1080p`: 330 klatek 1080p full overlay, EXACT mode, FRAME_TRACE. ✅
- `audit3_above_4k`: 330 klatek 4K full overlay, EXACT mode. ✅
- `audit3_chart_trace_full`: 90 klatek 1080p, GPU_SPLIT trace. ✅
- `audit3_gpu_split_hr_cad`: 90 klatek 1080p, GPU_SPLIT izolowany (29.44 FPS). ✅
- `audit3_cpu_ref_1080p`: 330 klatek 1080p, CPU_REFERENCE (HR+CAD, 43.37 FPS). ✅
- `audit3_gpu_split_1080p`: 330 klatek 1080p, GPU_SPLIT (HR+CAD, 48.01 FPS). ✅
- `audit3_cpu_ref_4k`: 330 klatek 4K, CPU_REFERENCE (HR+CAD, 19.80 FPS). ✅
- `audit3_gpu_split_4k`: 330 klatek 4K, GPU_SPLIT (HR+CAD, 22.81 FPS). ✅
- `audit3_soak_4k_nohud`: 2001 klatek 4K no-overlay (34.67 FPS render, 30.65 TRUE FPS). ✅
- Analiza statyczna: `amd_native_exporter.py`, `_chart_gpu_layout_safe`, `_ordered_map_layout_parts`, `_amd_layout_roles`. ✅
- Analiza presetu v10: z-order, dist_visual bbox. ✅
- Stall analysis: frame_trace.csv, wszystkie przebiegi (300f 1080p/4K + 2001f soak). ✅

## Not Tested
- NVIDIA runtime: brak sprzętu NVIDIA na tej maszynie. Ścieżka NVIDIA zachowana statycznie (AGENTS.md §12).
- Soak 4K **full overlay** 2000 klatek (zbyt długi dla sesji diagnostycznej — skrócony soak wykonany bez overlay).

## Risks
- Stall'e D3D11 (do 4857 ms) wpływają na średnią FPS w krótkich przebiegach. Soak 4K no-overlay (2001 klatek) potwierdził steady-state 34.7 FPS bez degradacji.
- AFTER-MAP GPU_SPLIT wymaga zmian w natywnym kompositorze — ryzyko z-order regression (AGENTS.md §8).
- Remux audio nadal kopiuje pełny plik audio (~7 s stały koszt) — potwierdzono w tym audycie (7079.9 ms soak, 6661.8 ms audit3_above_1080p).
