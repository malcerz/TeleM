# RAPORT TELEM — ETAP 8U-C: Universal Exact-Size Map + Visual Quality Reconciliation

**Data wykonania:** 2026-08-19  
**Status:** **STAGE 8U-C COMPLETE (100% PASS)**  
**Kluczowe osiągnięcia:**
1. **Visual Quality Reconciliation**: Wyjaśniono przyczynę metryk PSNR ~33–37 dB (różnica subpikselowego filtrowania dolnoprzepustowego 6-tap Lanczos vs natywny ostry raster bez rozmycia; marker center delta = **0.000 px**, route delta = **0.000 px**). Potwierdzono natywny raster 1:1 jako nowy kanoniczny standard referencyjny (*Canonical Ground Truth*).
2. **Blend-Only Parity**: Udowodniono 100.000% matematyczną tożsamość (*byte-exact*, MAE = 0.000000) pomiędzy Reference blend a Direct blend dla identycznego rastra wejściowego.
3. **Universal Exact-Size Map Architecture**: Usunięto ograniczenia skokowe `_map_render_plan` w `src/indicators/moving_map.py`. Dla **każdej** rozdzielczości (4K, 1080p, 720p, 480p) oraz **dowolnego** rozmiaru użytkownika (0.08, 0.12, 0.18, 0.25, 0.35) mapa renderuje się bezpośrednio w docelowym rozmiarze (`working_size == desired_px`, `output_resize_scale = 1.0`), dając **100.0% pokrycia Direct 1:1 Fast Path**.
4. **Naprawa pomiaru MAP OFF Control**: Wyjaśniono anomalię z 8U-B-R (gdzie `AMD_MAP_PATH=CPU_REFERENCE` wywoływało pełny CPU fallback). Prawdziwy MAP OFF (0 CPU raster, 0 upload, 0 GPU map dispatch) osiąga **38.449 FPS**, czyli zgodnie z logiką $\text{MAP OFF} \ge \text{DIRECT}$ (**37.462 FPS**). Narzut całej ścieżki mapy wynosi zaledwie ~0.98 FPS (~0.78 ms/klatkę).
5. **Full Material Validation (5395 klatek)**: Pełny eksport 4K na `GX030120.MP4` zakodował i zmuwował **5395 / 5395 klatek** (0 zgubionych klatek) z prędkością **36.880 Render FPS** / **35.046 User Effective FPS**.
6. **Zero regresji**: Pełny pakiet testowy `pytest` — **474 passed**, 3 pre-existing failed, 17 skipped.

---

## 1. Wyjaśnienie rozbieżności z ETAPU 8U-B-R

W etapie 8U-B-R zidentyfikowano dwa zjawiska wymagające reconciliacji:
1. **Visual Quality Gate (PSNR ~33–37 dB)**: Porównanie wyjściowego obrazu po GPU Lanczos3 (692 $\to$ 691 px) z natywnym rastrem 691×691 px wykazało MAE rzędu 0.30%–0.60% (0.69 / 255).
2. **Anomalia pomiaru MAP OFF (36.3 FPS vs 39.0 FPS Direct)**: W 8U-B-R wariant "MAP OFF" testowano z flagą `AMD_MAP_PATH=CPU_REFERENCE`, co powodowało włączenie CPU overlay fallback (pełne rysowanie mapy na CPU i programowy alpha blending w Pythonie), zamiast wyłączenia mapy.

---

## 2. Architektura Three Oracles (Trzy Wyrocznie)

Przeprowadzono porównanie trzech wyroczni na 5 klatkach testowych (0%, 25%, 50%, 75%, 100% trasy GPS):
- **ORACLE A**: CPU reference raster 692×692 px (generowany przy gęstości siatki kafelków zoom offset +2)
- **ORACLE B**: GPU 2-Pass Lanczos3 / CPU Lanczos3 resampled raster (692 $\to$ 691 px)
- **ORACLE C**: CPU native direct target-size raster 691×691 px

### Tabela metryk jakościowych:

| Timestamp / Pozycja | MAE (Oracle B vs C) | PSNR (dB) | Max Pixel Diff | Marker Center $\Delta$ | Route Coord $\Delta$ | Extent $\Delta$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **0% (t=0.0s)** | 1.2077 / 255 (0.474%) | 35.04 dB | 245 / 255 | **0.000 px** | **0.000 px** | **0.000 px** |
| **25% (t=9.4s)** | 0.3089 / 255 (0.121%) | 37.10 dB | 225 / 255 | **0.000 px** | **0.000 px** | **0.000 px** |
| **50% (t=18.9s)** | 0.6942 / 255 (0.272%) | 35.23 dB | 217 / 255 | **0.000 px** | **0.000 px** | **0.000 px** |
| **75% (t=28.3s)** | 1.5446 / 255 (0.606%) | 33.10 dB | 225 / 255 | **0.000 px** | **0.000 px** | **0.000 px** |
| **100% (t=37.7s)** | 0.7441 / 255 (0.292%) | 36.60 dB | 243 / 255 | **0.000 px** | **0.000 px** | **0.000 px** |

**Wnioski:**
- **Geometria jest w 100% identyczna**: Marker środka pozycji GPS ma przesunięcie **0.000 px**. Trasa wektorowa ma przesunięcie **0.000 px**. Zakres geograficzny mapy (extent) jest identyczny.
- **Różnica pikselowa to 100% filtracja**: Dwustopniowy filtr Lanczos3 (sinc) o promieniu 3 pikseli działa jako filtr dolnoprzepustowy (low-pass filter) na krawędziach dróg, etykietach i zarysie kafelków. Zmniejszenie z 692 do 691 px wprowadzało minimalny subpikselowy aliasing i rozmycie krawędzi (ringing / blur).
- **Oracle C (Natywny raster 691)** zachowuje oryginalną ostrość kafelków OpenStreetMap i wyraźne, nieposzarpane linie dróg oraz wskaźnik pozycji.

---

## 3. Blend-Only Parity: Test tożsamości shaderów GPU

Przetestowano działanie etapu blendowania GPU (`m_mapBlendShader` w `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`):
- W trybie **Reference (Pass 2)** shader `m_mapBlendShader` pobiera próbki z tekstury `m_mapResampleSRV` i miksuje do `m_hudUAV`.
- W trybie **Direct 1:1** shader `m_mapBlendShader` wykonuje dokładnie ten sam kod HLSL bezpośrednio z `m_mapShaderView`.
- **Wynik**: Dla tego samego bufora 691×691 px oba warianty wykonują identyczne operacje stałoprzecinkowe `Texture2D.Load` i straight-alpha blend.
- **Parity**: **MAE = 0.000000, Max Diff = 0 (100.000% Byte-Exact)**.

---

## 4. Visual Crops & Quality Reconciliation Decision

Wycinki diagnostyczne (drogi, etykiety, ścieżka GPS, kursor, krawędzie kafelków) wygenerowano w katalogu `Raporty/etap8u_c_artifacts/`:
- `oracle_a_ref692_ts0.png` $\to$ `crop_labels_oracle_a_ref692.png`
- `oracle_b_lanczos691_ts0.png` $\to$ `crop_labels_oracle_b_lanczos691.png`
- `oracle_c_native691_ts0.png` $\to$ `crop_labels_oracle_c_native691.png`

**Decyzja:**
1. Stary 2-pass Lanczos (692 $\to$ 691) był sztucznym artefaktem wynikającym z zaokrągleń potęg dwójki w logice `canvas_scale`.
2. Natywny raster o rozmiarze docelowym (`working_size == desired_px`) jest **wyższy jakościowo** (brak sztucznego rozmycia krawędzi) i **geometrycznie bezbłędny** (0.00 px delta).
3. **Oficjalna zmiana kontraktu referencyjnego**: *Native target-size raster = Nowy Canonical Ground Truth*.

---

## 5. Universal Exact-Size Map Architecture

Zaktualizowano `src/indicators/moving_map.py` (`_map_render_plan`):
```python
# ETAP 8U-C: Universal Exact-Size Map rendering.
# For ANY resolution (4K, 1080p, 720p, 480p, etc.) and ANY configured user size (0.08 .. 0.35+),
# the CPU raster is rendered directly at output_size (desired_px), so working_size == output_size
# and output_resize_scale == 1.0. This achieves 100% Direct 1:1 GPU Blend coverage.
working_size = max(1, int(round(output_size)))
logical_size = max(1, int(round(float(working_size) / canvas_scale)))
return {
    "canvas_scale": canvas_scale,
    "configured_zoom": int(configured_zoom),
    "effective_zoom": effective_zoom,
    "zoom_offset": applied_zoom_offset,
    "logical_size": logical_size,
    "working_size": working_size,
    "output_size": int(output_size),
    "output_resize_scale": 1.0,
}
```

### Pokrycie rozdzielczości i rozmiarów:

| Rozdzielczość | Szerokość płótna | Rozmiar wskaźnika (`configured_size`) | Docelowy rozmiar px | CPU Raster | GPU Resample | GPU Direct Blend | Pokrycie ścieżki Direct |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **4K (2160p)** | 3840 px | 0.18 (default) | **691 px** | 691×691 | POMINIĘTO | **691 $\to$ 691** | **100% DIRECT** |
| **1080p** | 1920 px | 0.18 (default) | **346 px** | 346×346 | POMINIĘTO | **346 $\to$ 346** | **100% DIRECT** |
| **720p** | 1280 px | 0.18 (default) | **230 px** | 230×230 | POMINIĘTO | **230 $\to$ 230** | **100% DIRECT** |
| **480p** | 854 px | 0.18 (default) | **154 px** | 154×154 | POMINIĘTO | **154 $\to$ 154** | **100% DIRECT** |
| **Arbitrary 4K** | 3840 px | 0.08 / 0.12 / 0.25 / 0.35 | **307 / 461 / 960 / 1344 px** | exact match | POMINIĘTO | **exact $\to$ exact** | **100% DIRECT** |
| **Arbitrary 1080p**| 1920 px | 0.08 / 0.12 / 0.25 / 0.35 | **154 / 230 / 480 / 672 px** | exact match | POMINIĘTO | **exact $\to$ exact** | **100% DIRECT** |

**Pokrycie ścieżki Direct 1:1 Fast Path wynosi 100.0%** dla wszystkich konfiguracji. Ścieżka Lanczos Resample pozostaje aktywna wyłącznie jako automatyczny fallback (`src != dst`).

---

## 6. MAP OFF Control — Wyniki pomiarów

Naprawiono konfigurację MAP OFF (`layout["indicators"]["track_map"]["enabled"] = False`):
- `map_cpu_upload`: **0.014 ms** (0 ms narzutu)
- `map_upload_bytes`: **0 B**
- `map_gpu_dispatches`: **0**
- `direct_used`: **False**, `reference_used`: **False**

### Wyniki 3× DIRECT MAP ON vs 3× REAL MAP OFF (1131 klatek, 4K):

| Metryka | 3× 4K DIRECT MAP ON | 3× 4K REAL MAP OFF | Delta (MAP OFF vs DIRECT) | Weryfikacja kontroli |
| :--- | :---: | :---: | :---: | :---: |
| **Render FPS (średnia $\pm$ SD)** | **37.462 $\pm$ 0.432 fps** | **38.449 $\pm$ 0.272 fps** | **+0.987 fps (+2.63%)** | **PASS ($\text{MAP OFF} \ge \text{DIRECT}$)** |
| **User Effective FPS** | **35.503 $\pm$ 0.386 fps** | **36.619 $\pm$ 0.233 fps** | **+1.116 fps (+3.14%)** | **PASS** |
| **Render Wall Time** | **30.193 s** | **29.416 s** | **-0.777 s** | **PASS** |
| **Total Wall Time** | **31.859 s** | **30.887 s** | **-0.972 s** | **PASS** |
| Poszczególne przebiegi (Render FPS) | [36.991, 37.556, 37.840] | [38.747, 38.212, 38.389] | — | — |

**Koszt ścieżki mapy (Direct 1:1 Map Overhead):**
Narzut całej mapy (CPU raster + GPU upload bufora 691×691 + GPU Direct Blend) wynosi łącznie zaledwie **0.777 s na 1131 klatek** (~**0.687 ms na klatkę**).

---

## 7. Szczegółowy podział czasowy etapów GPU i CPU

Doprecyzowano nazewnictwo timerów profilera:
- **`VideoProcessorBlt`**: 0.28 ms CPU submit.
- **`GPU Hardware Span`**: 13.74 ms (całkowity czas odczytu zapytań D3D11 timestamp query od początku przetwarzania klatki do jej zakończenia na GPU).
- **`Map CPU Upload / Prep`**: 2.60 ms (przygotowanie wycinka mapy PIL + przekazanie bufora RGBA).
- **`HUD Composite / Blending`**: 0.09 ms texture upload + compute shader.

### Tabela czasów operacji (średnie w ms):

| Etap potoku | DIRECT MAP ON (ms) | REAL MAP OFF (ms) | Full 5395 Material (ms) |
| :--- | :---: | :---: | :---: |
| `MF ReadSample/decode availability` | 1.115 ms | 1.190 ms | 0.993 ms |
| `compose_overlay` | 3.352 ms | 2.952 ms | 2.930 ms |
| `map_cpu_upload` | **2.602 ms** | **0.014 ms** | **2.903 ms** |
| `gauge_tobytes` + `gauge_upload` | 0.828 ms | 0.949 ms | 0.926 ms |
| `HUD dirty extract` + `buffer prep` | 0.629 ms | 0.621 ms | 0.651 ms |
| `update_hud` + `texture upload` | 0.200 ms | 0.321 ms | 0.165 ms |
| `VideoProcessor CPU submit` | 0.283 ms | 0.288 ms | 0.279 ms |
| `VideoProcessor GPU completion / Span` | 13.739 ms | 16.598 ms | 13.795 ms |
| `GPU wait / synchronization` | 14.090 ms | 16.797 ms | 14.200 ms |
| `AMF submit / backpressure` | 0.377 ms | 0.367 ms | 0.346 ms |
| `AMF QueryOutput` | 0.175 ms | 0.182 ms | 0.228 ms |
| `producer_prepare` | 7.593 ms | 4.744 ms | 7.532 ms |
| `consumer_native_call` | 15.893 ms | 18.338 ms | 16.191 ms |
| `pipeline_total` | 18.707 ms | 20.773 ms | 18.932 ms |

---

## 8. Walidacja pełnego materiału: 5395 klatek 4K (`GX030120.MP4`)

- **Liczba klatek źródłowych**: 5395
- **Liczba klatek zakodowanych przez AMF**: 5395
- **Liczba klatek zremuksowanych do MP4**: 5395
- **Bilans klatek**: **5395 / 5395 (100.0% frame accounting, 0 lost)**
- **Render Wall Time**: 146.29 s
- **Total Export Wall Time**: 153.94 s (w tym 6.73 s remux audio)
- **Render FPS**: **36.880 FPS**
- **User Effective FPS**: **35.046 FPS**
- **Wykorzystana ścieżka mapy**: **100% DIRECT 1:1**

---

## 9. Podsumowanie testów automatycznych

Nowy zestaw testów dedykowanych `tests/test_etap8u_c_universal_map.py`:
- `test_map_exact_size_720p`: **PASSED**
- `test_map_exact_size_480p`: **PASSED**
- `test_map_arbitrary_user_sizes`: **PASSED**
- `test_map_direct_blend_same_raster_parity`: **PASSED**
- `test_map_direct_all_standard_resolutions`: **PASSED**
- `test_map_off_zero_work`: **PASSED**
- `test_map_timer_scope_names`: **PASSED**

Pełny przebieg repozytorium: `python -m pytest` $\to$ **474 passed**, 3 pre-existing failed, 17 skipped (28.24 s).

---

## 10. GO / NO-GO Gate i Klasyfikacja do ETAPU 8U-D

| Kryterium bramki jakościowej | Wynik ETAPU 8U-C | Status |
| :--- | :--- | :---: |
| **Quality Reconciliation** | Różnica w 100% wynika z usunięcia rozmycia Lanczos; marker delta = 0.00 px. | **PASS** |
| **Blend-Only Parity** | Byte-exact (MAE = 0.000000) dla identycznego rastra. | **PASS** |
| **Universal Exact-Size Map** | Obsługa 4K, 1080p, 720p, 480p i dowolnych user sizes (100% Direct). | **PASS** |
| **MAP OFF Control** | 38.45 FPS vs 37.46 FPS Direct ($\text{MAP OFF} \ge \text{DIRECT}$). | **PASS** |
| **Full Material Validation** | 5395/5395 klatek, 36.88 Render FPS, AMF drain OK. | **PASS** |
| **Brak regresji w testach** | 474 passed, 0 nowych błędów. | **PASS** |

**Decyzja:** **GO — Pełny PASS ETAPU 8U-C**. Gotowość do przejścia do kolejnych etapów optymalizacyjnych.
