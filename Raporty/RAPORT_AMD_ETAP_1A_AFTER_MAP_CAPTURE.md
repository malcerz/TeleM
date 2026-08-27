# RAPORT_AMD_ETAP_1A_AFTER_MAP_CAPTURE.md

**Etap:** AMD ETAP 1A — Przygotowanie infrastruktury Python/capture dla AFTER-MAP GPU_SPLIT chartów  
**Data:** 2026-08-25  
**Autor:** Gemini 3.7 Flash  
**Status:** ZAKOŃCZONY POMYŚLNIE (ALL PASS)  

---

## 1. Co zmieniono

Wszystkie zmiany zostały ograniczone wyłącznie do jednego pliku w ścieżce AMD exportera:

### `src/ffmpeg/amd_native_exporter.py`

1. **`AfterMapChartTile` (nowa struktura danych / kontrakt):**
   - Zdefiniowano dataclass `AfterMapChartTile` reprezentujący kompletną definicję kafelka statycznego (tło/osie) oraz kafelków dynamicznych (kursor + wartość liczbowa) wraz z pozycjami docelowymi i formatem RGBA/DXGI dla chartów umieszczonych po mapie.
2. **`PreparedFrame` (rozszerzenie):**
   - Dodano pole `after_map_chart_captures: list[AfterMapChartTile] = field(default_factory=list)` przekazujące metadane i bufory kafelków AFTER-MAP od producenta CPU do konsumenta GPU.
3. **`export_amd_native_d3d11` (klasyfikacja BEFORE/AFTER oraz Feature Flag):**
   - Wprowadzono flagę diagnostyczną `AMD_AFTER_MAP_CHART_CAPTURE_DIAG` (domyślnie `False`/`OFF`).
   - Wprowadzono jednoznaczną klasyfikację wskaźników wykresów z layoutu na `before_map_chart_keys` oraz `after_map_chart_keys` na podstawie obecności mapy (`track_map`) i podziału na `compose_layout` / `map_above_layout`.
4. **`_prepare_frame_cpu` (separacja GPU slotów i diagnostyczny capture):**
   - Podczas ramki 0 (probe frame) guard `_chart_gpu_layout_safe` wyznacza `gpu_chart_keys_before_map` i `gpu_chart_keys_after_map`.
   - Istniejący natywny pass `BlendCharts` (wykonywany w C++ przed `BlendAboveMap`) otrzymuje wyłącznie `gpu_chart_keys_before_map`, co gwarantuje brak naruszenia Z-orderu.
   - Gdy flaga `AMD_AFTER_MAP_CHART_CAPTURE_DIAG=1` jest włączona, producent wykonuje diagnostyczny capture kafelków `ChartSplit` z `map_above_layout`, generuje obiekty `AfterMapChartTile` i umieszcza je w `PreparedFrame`, podczas gdy główny bufor `above_full` nadal renderuje wykres na CPU (brak zmian w obrazie wyjściowym).
5. **`_build_amd_profile` (metryki profilowania ETAP 1A):**
   - Dodano sekcję `"etap1a"` w profilu JSON raportującą stan klasyfikacji, liczbę wykonanych przechwyceń oraz status native blend (`native_after_map_blend_active: False`).

---

## 2. BEFORE/AFTER classification

Rzeczywisty przepływ klasyfikacji w runtime:

```text
               User Layout / Preset (np. cycling_dashboard_v10.json)
                                       │
                                       ▼
                     _ordered_map_layout_parts(layout)
                     ┌─────────────────┴─────────────────┐
                     ▼                                   ▼
        compose_layout (BELOW)               map_above_layout (ABOVE)
                     │                                   │
                     ▼                                   ▼
          before_map_chart_keys                after_map_chart_keys
       (np. [] w pełnym presecie)         (np. ['fit_cadence_text',
                                                'fit_heart_rate_text'])
                     │                                   │
                     ▼                                   ▼
          _chart_gpu_layout_safe              _chart_gpu_layout_safe
                     │                                   │
                     ▼                                   ▼
         gpu_chart_keys_before_map           gpu_chart_keys_after_map
                     │                                   │
                     ▼                                   ▼
        Istniejący pass BlendCharts          Gotowość dla przyszłego passu
            (Natywny GPU C++)                  BlendAfterMapCharts (ETAP 1B)
```

---

## 3. AFTER-MAP capture

Szczegółowe parametry przechwytywania dla wykresów `fit_heart_rate_text` i `fit_cadence_text` w trybie diagnostycznym:

### Wykres: `fit_heart_rate_text`
- **Classification:** `AFTER_MAP`
- **Slot:** 1
- **Static tile:** generowany jednorazowo (`format: DXGI_FORMAT_R8G8B8A8_UNORM`, `stride: width * 4`, raw RGBA bytes)
- **Dynamic tile (cursor):** generowany per klatka (`cursor_local: (lx, ly)`, `stride: width * 4`)
- **Dynamic tile (value):** generowany per klatka (`value_local: (lx, ly)`, `stride: width * 4`)
- **Destination:** `(870, 770, 526, 233)`
- **Capture success:** `YES`
- **Native blend:** `NO` (nieaktywny w ETAPIE 1A)
- **Final production path:** `CPU_REFERENCE via CPU ABOVE (above_full)`

### Wykres: `fit_cadence_text`
- **Classification:** `AFTER_MAP`
- **Slot:** 0
- **Static tile:** generowany jednorazowo (`format: DXGI_FORMAT_R8G8B8A8_UNORM`, `stride: width * 4`, raw RGBA bytes)
- **Dynamic tile (cursor):** generowany per klatka (`cursor_local: (lx, ly)`, `stride: width * 4`)
- **Dynamic tile (value):** generowany per klatka (`value_local: (lx, ly)`, `stride: width * 4`)
- **Destination:** `(198, 770, 526, 233)`
- **Capture success:** `YES`
- **Native blend:** `NO` (nieaktywny w ETAPIE 1A)
- **Final production path:** `CPU_REFERENCE via CPU ABOVE (above_full)`

---

## 4. Testy

| Test | Opis | Wynik |
|---|---|:---:|
| **TEST A — Existing GPU_SPLIT** | Layout: HR + Cadence (bez mapy). Weryfikacja działania dotychczasowej ścieżki GPU_SPLIT (`static_uploads >= 2`, `dynamic_uploads > 0`). | **PASS** |
| **TEST B — BEFORE-MAP** | Layout: HR + Cadence + track_map (wykresy przed mapą). Weryfikacja klasyfikacji `BEFORE_MAP` i poprawnego renderowania GPU przed mapą. | **PASS** |
| **TEST C — AFTER-MAP** | Layout: track_map + HR + Cadence (wykresy po mapie) z `AMD_AFTER_MAP_CHART_CAPTURE_DIAG=1`. Weryfikacja klasyfikacji `AFTER_MAP`, braku wywołania native blend i poprawnego wygenerowania kafelków capture. | **PASS** |
| **TEST D — Full preset v10** | Layout: `presets/cycling_dashboard_v10.json` z `AMD_AFTER_MAP_CHART_CAPTURE_DIAG=1`. Weryfikacja stabilności pełnego presetu, poprawnej detekcji AFTER-MAP i zachowania renderu CPU ABOVE. | **PASS** |
| **PIXEL PARITY (Flag OFF)** | Porównanie bit-w-bit klatek (5, 15, 25) wyrenderowanych z kodem ETAPU 1A (flaga domyślnie OFF) względem baseline z pre-edit. `max_diff = 0, mae = 0.0000`. | **PASS** |

---

## 5. Co pozostaje do ETAPU 1B

W ramach ETAPU 1A przygotowano kompletną infrastrukturę Python/capture. Do ETAPU 1B (wymagającego prac w C++ / D3D11) pozostaje:

1. **Natywne API D3D11:**
   - Dodanie w bibliotece DLL `telem_amd_native` funkcji aktualizacji kafelków after-map:
     - `telem_amd_update_after_map_chart_static(...)`
     - `telem_amd_update_after_map_chart_dynamic(...)`
2. **Kolejność compositingu w shaderze/pipeline GPU:**
   - Wprowadzenie etapu `BlendAfterMapCharts` umieszczonego **PO** `BlendAboveMap` i **PRZED** `ComposeHUDDirectNV12`.
3. **Obsługa czyszczenia tekstur (Clear):**
   - Dostosowanie `ClearPreviousAboveMap` tak, aby nie usuwał obszarów połączonych z kafelkami chartów AFTER-MAP.

---

## 6. Changed files

- `src/ffmpeg/amd_native_exporter.py`

---

## 7. Potwierdzenia

`AMD ETAP 1A COMPLETE`

`NO NATIVE COMPOSITOR CHANGES`

`PRODUCTION Z-ORDER UNCHANGED`

`PIXEL PARITY: PASS`

`NVIDIA UNCHANGED`

`INTEL UNCHANGED`
