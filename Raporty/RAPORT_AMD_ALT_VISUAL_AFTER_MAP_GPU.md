# RAPORT AMD: Przeniesienie alt_visual do natywnego GPU AFTER-MAP

Data: 2026-09-16
Środowisko: `C:\_DEV\BikeRideHUD`
Gałąź: `amd-bikeridehud` (HEAD bazowy: `1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98`)
Referencja Oracle: `C:\_DEV\TeleM` (READ-ONLY)

---

## 1. Wymagane Kluczowe Wskaźniki

```text
CPU_ALT_VISUAL_MS=0.325
GPU_ALT_VISUAL_MS=0.497
ABOVE_TOTAL_A=13.666
ABOVE_TOTAL_B=14.303
FPS_A=38.13
FPS_B=37.59
FPS_DELTA=-0.54
VISUAL_DIFF_PIXELS=0
CASE=CASE B — ALT_VISUAL GPU FUNCTIONAL BUT NO MATERIAL GAIN
```

---

## 2. Cel i Zakres Zadania

Celem zadania było zbadanie oraz przeniesienie **wyłącznie** widgetu linijki wysokości (`alt_visual`) z warstwy programowej CPU `ABOVE` do dedykowanego potoku natywnego D3D11 GPU `AFTER-MAP`.

Zgodnie z zasadami dyscypliny zakresu:
- Nie ruszano widgetów: `compass`, `speed gauge`, `charts`, `map`, `bars`, `layout`, parametrów encodera.
- Zachowano w 100% zwalidowane produkcyjne defaulty:
  - `AMD_QUEUE_DEPTH=2`
  - `AMD_CPU_GPU_PIPELINE=ASYNC`
  - `AMD_VP_PROCESSOR_RING_SIZE=1`
  - `AMD_ABOVE_BATCHED=0`
- Dodano kontrolowaną flagę `AMD_AFTER_MAP_ALT_VISUAL_GPU` z domyślną wartością `0` (`default=0`).

---

## 3. Audyt alt_visual (Stan początkowy)

Szczegółowy audyt został udokumentowany w [`scratch/amd_alt_visual_gpu/alt_visual_current_path.md`](../scratch/amd_alt_visual_gpu/alt_visual_current_path.md):
- **Gdzie rasteryzowany**: `src/indicators/altitude.py` w funkcji `_render_altitude_indicator()` (styl `ruler`/`visual`).
- **Dane wejściowe**: telemetryczny `value` (wysokość n.p.m. w metrach lub stopach).
- **Bounding box / Rect**: w layoucie `cycling_dashboard_v10.json`: pozycja `x=53, y=803`, rozmiar `visual_w=316, visual_h=640` (pionowa linijka z podziałką, liczbami i centralnym wskaźnikiem trójkątnym).
- **Format**: kafelek RGBA 316x640 ze straight-alpha.
- **Koszt CPU**: rasteryzacja wycinka linijki w Pillow zajmuje średnio zaledwie ~0.33 ms na klatkę.

---

## 4. Implementacja GPU AFTER-MAP

### 4.1. Natywny C++ D3D11 Pipeline
W plikach `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h`, `d3d11_vp_pipeline.cpp` oraz `telem_amd_native.cpp`:
1. Dodano zarządzanie stanem i zasobami D3D11 dla `alt_visual`:
   - Tekstura `m_pAltVisualTex` (D3D11_USAGE_DYNAMIC / WRITE_DISCARD) w formacie `DXGI_FORMAT_R8G8B8A8_UNORM`.
   - Bounding box i parametry docelowe `(m_altVisualDstX, m_altVisualDstY, m_altVisualWidth, m_altVisualHeight)`.
2. Zaimplementowano wczesne czyszczenie dirty rect (`ClearPreviousAboveMap`):
   - Poprzedni bounding box `alt_visual` jest bezpiecznie zerowany na początku kolejnej klatki (`clearPrevAltVisual`), co zapobiega zjawisku ghostingu i nie narusza warstw pod spodem.
3. Zaimplementowano funkcję blendowania:
   - `BlendAltVisual()` wykorzystuje istniejący `D3D11_BLEND_STATE_MODE_PREMUL_SRC_STRAIGHT_ALPHA` (mode 3 - straight-alpha "over") i rysuje kafelek w warstwie AFTER-MAP (po `BlendLean` i `BlendAfterMapCharts`).
4. Rozszerzono C ABI o 3 minimalne funkcje:
   - `telem_amd_set_alt_visual_after_map(ctx, enabled)`
   - `telem_amd_update_alt_visual(ctx, p_pixels, w, h, stride, dst_x, dst_y, p_uploaded, p_created)`
   - `telem_amd_get_alt_visual_stats(ctx, p_draw_count, p_draw_ms)`

### 4.2. Dowód Kompilacji i ABI DLL
- Narzędzie kompilacji: MSVC cl.exe 19.38.30324.3, Direct3D 11, Direct3D 9, AMF SDK.
- Ścieżka DLL: `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`
- SHA256: `3c0336f5dc52dc74cf2a342eb688937b062fbaaa4cbfede0bf6b9e65bf393bf7`
- Rozmiar: 3,098,508 bajtów
- Wersja ABI: 9
- Wszystkie 69 symboli C API obecne i zwalidowane w teście ctypes (`scratch/amd_alt_visual_gpu/dll_proof.txt`).

### 4.3. Integracja Python
- W `src/ffmpeg/amd_config.py`: dodano zarządzanie flagą `AMD_AFTER_MAP_ALT_VISUAL_GPU` w governance (`PRODUCTION_DEFAULTS = {"alt_visual": 0}`). Wszystkie testy governance w `tests/test_amd_benchmark_governance.py` zakończone sukcesem (`11 passed`).
- W `src/ffmpeg/amd_native_exporter.py`:
  - Pobieranie flagi `after_map_alt_visual_gpu` z konfiguracji.
  - Wykluczenie `alt_visual` z warstwy CPU ABOVE (pomijanie w dirty rects i compositingu CPU) przy włączonym GPU path.
  - Przekazywanie kafelka RGBA w `PreparedFrame` i upload do GPU przez `telem_amd_update_alt_visual()`.
  - Rejestracja metryk profilera (`alt_visual_cpu_ms`, `alt_visual_upload_ms`, `alt_visual_blend_ms`).

---

## 5. Wyniki A/B (Real GUI Path)

Oba przebiegi wykonano w pełnym procesie produkcyjnym GUI (`BikeRideHUD.py -> GUI -> RenderMixin -> AMD child process -> amd_native_exporter -> telem_amd_native.dll -> AMF`):
- Workload: `Video/GX020079.mp4` + `Video/GX020079.fit` (4K UHD 3840x2160, 300 klatek / 10.0 s @ 29.97 fps, AMF HEVC).
- RUN A (CPU baseline): `AMD_AFTER_MAP_ALT_VISUAL_GPU=0`
- RUN B (GPU AFTER-MAP): `AMD_AFTER_MAP_ALT_VISUAL_GPU=1`

### Tabela Porównawcza

| Metryka | RUN A (CPU baseline) | RUN B (GPU AFTER-MAP) | Różnica (B - A) |
|---|---|---|---|
| **Wall time** | 7.87 s | 7.98 s | +0.11 s (+1.4%) |
| **FPS** | **38.13** | **37.59** | **-0.54 FPS (-1.4%)** |
| **producer_prepare avg** | 22.52 ms | 23.72 ms | +1.20 ms |
| **above_total avg** | 13.67 ms | 14.30 ms | +0.63 ms |
| **alt_visual CPU avg** | 0.325 ms | 0.333 ms | +0.008 ms |
| **alt_visual upload avg** | 0.000 ms | 0.496 ms | +0.496 ms |
| **alt_visual blend GPU avg** | 0.000 ms | 0.001 ms | +0.001 ms |
| **above_upload avg** | 1.924 ms | 1.655 ms | -0.269 ms (-14.0%) |
| **consumer_native_call avg** | 15.81 ms | 13.78 ms | -2.03 ms (-12.8%) |
| **AMF / D3D11 errors** | 0 | 0 | 0 |
| **Dropped frames** | 0 | 0 | 0 |
| **Child exit code** | 0 | 0 | 0 |
| **Output MP4 size** | 86,105,320 B | 86,105,320 B | Identyczny co do bajta |

---

## 6. Weryfikacja Pixel Parity

Wyekstrahowano klatki `[0, 50, 150, 250, 299]` z obu plików MP4 (`runA_10s.mp4` i `runB_10s.mp4`):
- Porównanie Full-Frame (3840x2160):
  - Klatka 0: 0 diff pixels (max=0, MAE=0.0000)
  - Klatka 50: 0 diff pixels (max=0, MAE=0.0000)
  - Klatka 150: 0 diff pixels (max=0, MAE=0.0000)
  - Klatka 250: 0 diff pixels (max=0, MAE=0.0000)
  - Klatka 299: 0 diff pixels (max=0, MAE=0.0000)
- Porównanie wycinka `alt_visual` Crop Box `[33, 783, 389, 1463]` (356x680 pikseli):
  - Wszystkie klatki: **0 różnych pikseli** (max=0, MAE=0.0000).
- Contact sheets: `runA/contact_sheet.png` i `runB/contact_sheet.png` mają identyczny rozmiar 2,809,156 bajtów.

---

## 7. Analiza i Klasyfikacja Wyniku

1. **Jakość wizualna i stabilność**:
   - Zero regresji wizualnych (dokładna zgodność pikselowa 0 różnych pikseli).
   - Zero błędów AMF / D3D11, zero zrzuconych klatek, poprawny cykl życia procesu podrzędnego (exit code 0).
2. **Dynamika wydajnościowa**:
   - Sam widget `alt_visual` kosztuje na CPU jedynie ~0.33 ms na klatkę (ruler jest prostą grafiką wektorową z tickami).
   - Wyłączenie go z CPU ABOVE przyniosło spadek `above_upload` o 0.27 ms i skrócenie czasu `consumer_native_call` o 2.03 ms.
   - Jednakże narzut uploadu kafelka dynamicznego do GPU wyniósł ~0.50 ms, a sumaryczny FPS (38.13 vs 37.59) mieści się w granicach naturalnego szumu pomiarowego platformy (±1.5%).
3. **Decyzja o wdrożeniu**:
   - Ścieżka GPU jest w pełni funkcjonalna i zwalidowana pod kątem poprawności.
   - Ponieważ zysk wydajnościowy jest w szumie pomiarowym, flaga `AMD_AFTER_MAP_ALT_VISUAL_GPU` zgodnie z wytycznymi pozostaje z wartością domyślną `0` (`default=0`).
4. **Klasyfikacja**:
   - **CASE B — ALT_VISUAL GPU FUNCTIONAL BUT NO MATERIAL GAIN**.
