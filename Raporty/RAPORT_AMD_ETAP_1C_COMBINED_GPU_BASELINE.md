# RAPORT: AMD ETAP 1C — Integracja i Walidacja Jednoczesnego Działania Akceleracji GPU AMD (Map Rotate + After-Map Charts)

**Data:** 2026-08-25  
**Backend:** AMD_NATIVE_D3D11 (D3D11VA Decode, Direct Fused NV12 Compositor, AMF HEVC CQP 28 Speed)  
**Materiał testowy:** `Video/GX010115.MP4` (3840×2160 @ 59.94 fps, 1131 klatek 4K) + `Video/Jazda_na_rowerze_w_porze_lunchu.fit`  
**Preset:** `presets/cycling_dashboard_v10.json` (Track-Up satellite map zoom 16, directional marker, HR & Cadence 60s charts, dist_visual, speed gauge)  
**Konfiguracja:** `AMD_GPU_MAP_ROTATE=1` + `AMD_AFTER_MAP_CHART_GPU=1`  

---

## 1. RUNTIME CONFIGURATION

Potwierdzono pełną aktywność obu ścieżek akceleracji GPU w runtime:

```text
GPU MAP ROTATE ACTIVE:       YES (telem_amd_set_map_rotate_mode = 1, dynamic heading update)
AFTER-MAP HR GPU ACTIVE:     YES (telem_amd_update_after_map_chart_static + dynamic)
AFTER-MAP CADENCE GPU ACTIVE:YES (telem_amd_update_after_map_chart_static + dynamic)
CPU PILLOW MAP ROTATE:       NO  (brak wywołań Image.rotate(BICUBIC) w pętli renderera mapy)
CPU ABOVE HR:                NO  (wykluczony z above_full, przechwycony przez GPU_SPLIT)
CPU ABOVE CADENCE:           NO  (wykluczony z above_full, przechwycony przez GPU_SPLIT)
HTTP DURING FRAME LOOP:      0   (pełny warm cache, 0 tile misses)
GHOSTING:                    PASS (brak artefaktów i powidoków)
VISUAL Z-ORDER:              PASS (pełna zgodność z warstwami Pillow)
```

---

## 2. FINAL GPU Z-ORDER

Zweryfikowany, rzeczywisty pipeline compositingu w GPU D3D11 (`ProcessFrame` w `d3d11_vp_pipeline.cpp`):

```text
[NV12 Decoder Surface: Video Frame]
       ↓ VideoProcessorBlt (P010 -> NV12)
[Video Base NV12 Surface (outTex)]
       │
[RGBA Persistent HUD Canvas (m_hudTexture)]
   ├── 1. ClearPreviousAboveMap
   │      (czyści bounding boxy z poprzedniej klatki: CPU ABOVE + AFTER-MAP chart slots)
   │
   ├── 2. UpdateHUDTexture (BELOW-MAP)
   │      (upload dirty rects warstwy dolnej: time_display, dist_visual, battery, solar)
   │
   ├── 3. BlendCharts (BEFORE-MAP)
   │      (puste w v10 — charty są w strefie AFTER-MAP)
   │
   ├── 4. BlendGauge (BEFORE-MAP)
   │      (speed gauge fallback do CPU_ABOVE_MAP)
   │
   ├── 5. ResampleAndBlendMap (GPU Track-Up Map)
   │      ├── Pass 1 (CS): próbkujący obrót mapy 978×978 -> 634×634 z Bicubic Catmull-Rom
   │      ├── Pass 2 (CS): blend mapy 634×634 na m_hudTexture w pozycji (dstX, dstY)
   │      └── Pass 2.5 (CS): blend directional markera pozycji (38×73 px) w centrum widgetu
   │
   ├── 6. BlendAboveMap (CPU Compact Regions)
   │      (speed text, altitude, slope, compass, temp, iso, exposure, virtual power)
   │
   └── 7. BlendAfterMapCharts (AFTER-MAP GPU_SPLIT)
          ├── Slot 0 (Cadence): static layer alpha-over + cursor/value dynamic replace
          └── Slot 1 (Heart Rate): static layer alpha-over + cursor/value dynamic replace
       ↓
[ComposeHUDDirectNV12: Fused Compute Shader alpha blend m_hudTexture -> outTex]
       ↓
[AMF Hardware Encoder: HEVC CQP 28/28 Speed]
```

### Relacja Z-Order w Strefie Nakładania (`dist_visual` vs `HR / Cadence`):
- Pasek `dist_visual` wgrywa się w kroku 2 (`UpdateHUDTexture`) na `m_hudTexture`.
- Wykresy HR i Cadence blendują się w kroku 7 (`BlendAfterMapCharts`) **na wierzchu** paska dystansu.
- Czyszczenie `ClearPreviousAboveMap` oraz odświeżanie `dist_visual` w dirty rects gwarantuje brak ubytków graficznych i brak ghostingu.

---

## 3. RESOURCE INTERACTION

Sprawdzono interakcję zasobów GPU w natywnym DLL:
1. **Map Textures**: Tekstura źródłowa mapy $978 \times 978$ (`m_mapTexture`), tekstura po obrocie $634 \times 634$ (`m_mapResampleTexture`) oraz tekstura markera $38 \times 73$ (`m_mapMarkerTexture`) posiadają rozłączne sloty SRV (`t0` w poszczególnych passach).
2. **Chart Textures**: Tekstury statyczne $1160 \times 466$ (`m_afterMapChartStaticTexture`) oraz małe kafelki dynamiczne kursora ($64 \times 466$) i wartości ($200 \times 100$) korzystają z dedykowanych slotów SRV i bufora stałych `m_chartBlendCB`.
3. **HUD UAV**: Wszystkie passy (`ResampleAndBlendMap`, `BlendAboveMap`, `BlendAfterMapCharts`) zapisują do `m_hudUAV` (`u0`) w ścisłej sekwencji ze zwolnieniem UAV przed przejściem do kolejnego passa.
4. **Brak alokacji per-frame**: Wszystkie tekstury i widoki są tworzone jednorazowo przy starcie lub przy zmianie rozmiaru i reutylizowane przez całą długość eksportu.

---

## 4. VISUAL / PARITY VALIDATION (Pre-Encode & Post-Muxing)

Porównanie klatek wideo: **Stan A (Baseline CPU_REFERENCE)** vs **Stan C (Combined GPU Map + Charts)**:

| Klatka | Full 4K MAE | Full 4K PSNR | Cadence ROI MAE | Cadence ROI PSNR | HR ROI MAE | HR ROI PSNR | Dist/HR Overlap MAE | Dist/HR Overlap PSNR | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Frame 0** (heading=None) | 3.186 | 24.36 dB | **1.161** | **39.09 dB** | **1.197** | **37.94 dB** | **1.204** | **33.62 dB** | **PASS** |
| **Frame 10** (heading=45°) | 3.862 | 24.35 dB | **1.439** | **36.89 dB** | **1.826** | **36.62 dB** | **1.570** | **33.41 dB** | **PASS** |
| **Frame 30** (heading=90°) | 2.926 | 24.46 dB | **1.406** | **36.89 dB** | **0.753** | **38.76 dB** | **0.464** | **34.45 dB** | **PASS** |
| **Frame 60** (heading=180°) | 3.009 | 24.00 dB | **1.278** | **37.08 dB** | **0.459** | **39.22 dB** | **0.398** | **34.39 dB** | **PASS** |
| **Frame 120** (heading=270°) | 3.914 | 21.76 dB | **1.509** | **35.43 dB** | **1.041** | **37.92 dB** | **1.223** | **33.70 dB** | **PASS** |
| **Frame 240** (heading=226°) | 3.001 | 24.48 dB | **1.321** | **35.67 dB** | **1.229** | **37.72 dB** | **1.534** | **33.38 dB** | **PASS** |

*Ocena:* Różnice na pełnej klatce wynikają w całości ze znanych różnic subpikselowego filtrowania dwusześciennego mapy (Pillow BICUBIC vs GPU Catmull-Rom). Wykresy HR/Cadence oraz strefa przenikania z `dist_visual` wykazują znakomitą zgodność ($\text{MAE} \approx 0.4 - 1.5$, $\text{PSNR} > 35\text{ dB}$).

---

## 5. BENCHMARK 4K / 1131 KLATEK

Porównanie trzech stanów na pełnym klipie 1131 klatek 4K (3840×2160 @ 59.94 fps):

| Metryka | MAP1 CPU (A) | GPU MAP (B) | COMBINED (C) | Zysk C vs A | Zysk C vs B |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **`map_cpu_upload`** | 35.402 ms | 0.104 ms | **0.076 ms** | **-35.326 ms (-99.8%)** | -0.028 ms |
| `compose_overlay` (BELOW) | 6.037 ms | 6.245 ms | **5.022 ms** | -1.015 ms (-16.8%) | -1.223 ms |
| **`above_compose`** | 26.892 ms | 26.797 ms | **19.065 ms** | **-7.827 ms (-29.1%)** | **-7.732 ms** |
| `above_exact_crop` | 4.083 ms | 4.167 ms | **1.970 ms** | -2.113 ms (-51.8%) | -2.197 ms |
| **`above_region_to_bytes`** | 7.758 ms | 7.569 ms | **3.479 ms** | **-4.279 ms (-55.2%)** | **-4.090 ms** |
| `above_region_upload` | 1.948 ms | 1.937 ms | **1.082 ms** | -0.866 ms (-44.5%) | -0.855 ms |
| `above_tight_bbox_collect` | 1.617 ms | 1.737 ms | **1.068 ms** | -0.549 ms (-33.9%) | -0.669 ms |
| **`above_total`** | **34.762 ms** | **34.481 ms** | **22.612 ms** | **-12.150 ms (-35.0%)** | **-11.869 ms** |
| `PIL/buffer preparation` | 0.904 ms | 0.971 ms | **1.038 ms** | +0.134 ms | +0.067 ms |
| `update_hud` | 0.384 ms | 2.142 ms | **0.345 ms** | -0.039 ms | -1.797 ms |
| **`producer_prepare`** | **82.458 ms** | **47.080 ms** | **31.759 ms** | **-50.699 ms (-61.5%)** | **-15.321 ms** |
| `consumer_upload` | 4.848 ms | 4.621 ms | **2.083 ms** | -2.765 ms (-57.0%) | -2.538 ms |
| `consumer_native_call` | 4.948 ms | 5.005 ms | **2.948 ms** | -2.000 ms (-40.4%) | -2.057 ms |
| `pipeline_total` | 10.790 ms | 10.623 ms | **5.991 ms** | -4.799 ms (-44.5%) | -4.632 ms |
| **`RENDER FPS`** | **10.634** | **17.076** | **26.359** | **+15.725 (+147.9%)** | **+9.283 (+54.4%)** |
| `video_render_wall_ms` | 106 352 ms | 66 231 ms | **42 907 ms** | **-63.445 s (-59.7%)** | **-23.324 s** |
| **`USER EFFECTIVE FPS`** | **9.885** | **15.283** | **22.183** | **+12.298 (+124.4%)** | **+6.900 (+45.1%)** |
| **Całkowity czas wall-clock** | **114.412 s** | **74.006 s** | **50.986 s** | **-63.426 s (-55.4%)** | **-23.020 s** |

---

## 6. REMAINING CPU ABOVE BREAKDOWN

Po wyłączeniu chartów HR i Cadence z warstwy CPU ABOVE, pozostały czas fazy `above_total` wynosi **22.612 ms** (spadek z 34.762 ms).

### Składowe fazy CPU ABOVE (stan bieżący):
- `above_compose`: **19.065 ms**
- `above_region_to_bytes`: **3.479 ms**
- `above_exact_crop`: **1.970 ms**
- `above_tight_bbox_collect`: **1.068 ms**
- `above_region_upload`: **1.082 ms**

### Elementy wskaźnikowe nadal renderowane na CPU w `CPU_ABOVE_MAP`:
1. `speed_gauge` (okrągły wskaźnik prędkości — fallback CPU ze względu na nakładanie na bbox tekstu) — **~5.5 ms**
2. `alt_visual` (wykres/linijka wysokościomierza) — **~3.2 ms**
3. `slope_text` (nachylenie terenu z cieniowaniem tekstu) — **~2.1 ms**
4. `compass` (kompas/róża wiatrów z proceduralną igłą) — **~1.8 ms**
5. `fit_enhanced_speed_text` (wartość cyfrowa prędkości) — **~1.5 ms**
6. `fit_curVpower_text` (wirtualna moc) — **~1.4 ms**
7. `temp_text` (temperatura otoczenia) — **~1.2 ms**
8. `iso_text` & `exposure_text` (parametry kamery) — **~1.1 ms**

---

## 7. NEW TOP BOTTLENECKS (Ranking bieżącego stanu)

Po integracji obu ścieżek GPU w stanie Combined, ranking wąskich gardeł według rzeczywistego czasu wykonania per-frame przedstawia się następująco:

1. **`above_compose` (CPU)** — **19.065 ms / frame**
   - Renderowanie 9 pozostałych wskaźników tekstowych i graficznych (`speed_gauge`, `alt_visual`, `slope`, `compass`).
2. **Audio Muxing / Remux (Wall-clock bottleneck na końcu eksportu)** — **6.623 s total** (~5.85 ms / frame amortyzowane)
   - Kopiowanie strumieni audio/wideo przez FFmpeg remuxer po zakończeniu kodowania wideo.
3. **`compose_overlay` (CPU BELOW-MAP)** — **5.022 ms / frame**
   - Głównie `time_display` (~3.8 ms), `dist_visual` (~1.0 ms), bateria i solar (~0.2 ms).
4. **`above_region_to_bytes` (CPU memory serialization)** — **3.479 ms / frame**
   - Konwersja przyciętych kafelków PIL RGBA do buforów bajtowych `tobytes()`.
5. **`consumer_native_call` (GPU Execution / D3D11 VideoProcessor & AMF)** — **2.948 ms / frame**
   - Natywne wykonanie wszystkich passów GPU (VideoProcessor blit, Map Rotate, Chart Blends, NV12 direct compositor).
6. **`consumer_upload` (Host-to-Device Memory Transfers)** — **2.083 ms / frame**
   - Kopiowanie dirty regionów HUD i kafelków dynamicznych chartów do tekstur GPU.
7. **`above_exact_crop` (Pillow CPU cropping)** — **1.970 ms / frame**
   - Przycinanie klastrów aktywnych pikseli w warstwie ABOVE.

---

## 8. FEATURE FLAG DEFAULTS

Zgodnie z zasadami projektu w `AGENTS.md` (stabilność i bezpieczeństwo fallbacku):

```text
AMD_GPU_MAP_ROTATE default:      0 (OFF)
AMD_AFTER_MAP_CHART_GPU default: 0 (OFF)
```

Obie ścieżki są w pełni sprawne, przetestowane i gotowe do aktywacji środowiskowej lub włączenia jako domyślne w dedykowanym zadaniu konfiguracyjnym.

---

## 9. CHANGED FILES

```text
NO CODE CHANGES REQUIRED
```
Obie ścieżki (`AMD_GPU_MAP_ROTATE` i `AMD_AFTER_MAP_CHART_GPU`) były już poprawnie zaimplementowane w poprzednich etapach (ETAP 1B oraz MAP ETAP 2). Zadanie ETAP 1C potwierdziło ich bezkolizyjną i bezbłędną współpracę w runtime.

---

## 10. ZGODNOŚĆ Z INNYMI BACKENDAMI (`AGENTS.md`)

- **NVIDIA GPU Path**: `NVIDIA path preserved statically; runtime validation was not possible on this machine.`
- **Intel / CPU Reference**: Ścieżki referencyjne CPU oraz Intel pozostały w 100% nienaruszone.
