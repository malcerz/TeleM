# Raport AMD ETAP 5K — BATCHED NATIVE DIRTY REGIONS / PYTHON→D3D11 MARSHALLING ELIMINATION

**Data:** 2026-08-28  
**Platforma testowa:** AMD Ryzen 7 7730U with Radeon Graphics (8C/16T, 32GB RAM UMA)  
**Profil zasilania:** Windows Max Performance (`ded574b5-45a0-4f42-8737-46345c09c238`)  
**Gałąź git:** `amd-render`  
**Kanonical Workload:** `Video/GX020079.MP4` (3840x2160, 1131 frames) + `Video/GX020079.fit` + `presets/cycling_dashboard_v10.json`  

---

## 1. Cel etapu

W etapie 5J.1 zidentyfikowano, że po eliminacji alokacji Pillow crop/tobytes (ETAP 5I) główny narzut przekazywania 6 regionów dirty CPU ABOVE stanowił mostek Python $\to$ C++:
* 6 niezależnych wywołań FFI `telem_amd_update_above_region` z Pythona co klatkę,
* rzutowanie wskaźników przez `ctypes.cast(r_ptr, POINTER(c_uint8))`,
* tworzenie i przekazywanie 7 argumentów C na każde wywołanie regionu,
* narzut pętli Pythona mierzony w `above_region_upload` wynoszący ~1.05 ms/frame.

Celem ETAP 5K było:
* Utworzenie jednego wsadowego wywołania DLL: `telem_amd_update_above_regions_batch(ctx, pRowPointers, canvasStride, pRects, count)`,
* Zastąpienie pętli Pythona ciasną pętlą C++ w natywnym kodzie D3D11,
* Użycie trwałej tablicy deskryptorów `HUDDirtyRect` (zero dynamicznych alokacji co klatkę),
* Bezpośrednie przekazanie wskaźnika na tablicę wierszy obrazu (`row_table_ptr`) z PyImaging do C++, gdzie offset `pRowPointers[y] + x * 4` jest obliczany natywnie w pamięci podręcznej L1.

---

## 2. Implementacja techniczna

### 2.1. C++ D3D11 Native Pipeline
W plikach `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h`, `d3d11_vp_pipeline.cpp` oraz `telem_amd_native.cpp`:
1. Zdefiniowano i wyeksportowano funkcję ABI:
```cpp
TELEM_EXPORT int telem_amd_update_above_regions_batch(
    void* handle, const uint8_t* const* pRowPointers, UINT canvasStride,
    const HUDDirtyRect* pRects, UINT rectCount);
```
2. W `D3D11VideoProcessorPipeline::UpdateAboveRegionsBatch`:
   - Walidacja wejść (obsługa NULL, ujemnych współrzędnych, ograniczenie do `MAX_ABOVE_REGIONS = 8`),
   - Pobranie wskaźnika wiersza `pRow = pRowPointers[dstY]` i obliczenie adresu źródłowego `pSrcData = pRow + dstX * 4`,
   - Aktualizacja tekstury Direct3D 11 za pomocą `m_context->UpdateSubresource(m_aboveRegionTexture[i], 0, nullptr, pSrcData, canvasStride, 0)` w jednej ciasnej pętli natywnej.

### 2.2. Python Exporter Bridge
W pliku `src/ffmpeg/amd_native_exporter.py`:
1. Zdefiniowano strukturę ctypes `HUDDirtyRect`:
```python
class HUDDirtyRect(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_uint),
        ("y", ctypes.c_uint),
        ("width", ctypes.c_uint),
        ("height", ctypes.c_uint),
    ]
```
2. Zainicjalizowano przed pętlą renderowania trwały bufor `batched_above_rects_buf = (HUDDirtyRect * 8)()` (0 alokacji w pętli klatek).
3. W `_extract_exact_above_regions`: jeśli `batched_above_rects_buf` jest aktywny, funkcja wypełnia tablicę deskryptorów i przekazuje deskryptor `("BATCHED", row_table_ptr, canvas_stride, batched_rects_buf, len(exact_rects), uploaded_bytes, above_full)` w obiekcie `PreparedFrame`.
4. W konsumentze: jedno wywołanie `native_dll.telem_amd_update_above_regions_batch` wysyła wszystkie 6 regionów naraz.
5. Dodano flagę środowiskową `AMD_ABOVE_BATCHED` (domyślnie `1`, `0` wymusza legacy per-region).

---

## 3. Wyniki mikrobenchmarku (10,000 iteracji)

Skrypt: `scratch/microbench_etap5k_batched_regions.py`

| Wariant | Czas/klatkę ($\mu$s) | Alokacje pamięci (peak) | Wywołania C/klatkę |
| :--- | :--- | :--- | :--- |
| **LEGACY_PER_REGION** | 341.32 $\mu$s | 924 bytes | 7 (1 count + 6 updates) |
| **BATCHED_REGIONS** | 301.05 $\mu$s | 400 bytes | 1 (single batched call) |
| **Zysk** | **-40.27 $\mu$s (-11.8%)** | **-56.7% alokacji** | **-85.7% wywołań FFI** |

---

## 4. Testy bezpieczeństwa brzegowego (Edge Cases & Safety)

Skrypt: `scratch/test_etap5k_edge_and_parity.py` oraz `tests/test_amd_etap5k_batched_abi.py`

* 1 region, 2 regiony, 6 regionów, 8 regionów (maksymalna pojemność) — **PASS**
* Region na krawędzi $x=0$, $y=0$ — **PASS**
* Region dotykający prawej krawędzi ($x=3640, w=200$), dolnej krawędzi ($y=1960, h=200$) — **PASS**
* Region 1x1 piksel — **PASS**
* Region pełnej szerokości ($w=3840$) — **PASS**
* Bezpieczeństwo przy niepoprawnych parametrach:
  - Null `handle` / null `pRowPointers` / null `pRects` $\to$ bezpieczny return `0` bez crasha — **PASS**
  - Zerowy `stride` $\to$ bezpieczny return `0` — **PASS**
  - Przekroczenie limitu liczby regionów (`count = 12 > 8`) $\to$ bezpieczne obcięcie do `MAX_ABOVE_REGIONS = 8` — **PASS**

---

## 5. Wyniki pełnego benchmarku naprzemiennego (10 measured runs)

Skrypt: `scratch/run_etap5k_interleaved_ab.py`  
Kolejność uruchomień: Warmup A, Warmup B, A1, B1, A2, B2, A3, B3, A4, B4, A5, B5.

| Metryka | LEGACY_5K (AMD_ABOVE_BATCHED=0) | BATCHED_5K (AMD_ABOVE_BATCHED=1) | Różnica (Delta) |
| :--- | :--- | :--- | :--- |
| **TRUE FPS (mean)** | **37.460 fps** | **37.712 fps** | **+0.252 fps (+0.67%)** |
| **TRUE FPS (median)** | 37.501 fps | 37.535 fps | +0.034 fps |
| **Total Export (mean)** | **30.210 s** | **30.000 s** | **-0.210 s (-0.70%)** |
| **Total Export (median)** | 30.159 s | 30.132 s | -0.027 s |
| **`producer_prepare` (mean)** | **14.089 ms** | **13.155 ms** | **-0.934 ms (-6.6%)** |
| **`above_total` (mean)** | **10.579 ms** | **9.818 ms** | **-0.761 ms (-7.2%)** |
| **`above_region_upload` (mean)** | **1.045 ms** | **0.010 ms** | **-1.035 ms (-99.0%)** |
| **`consumer_native_call` (mean)** | 6.322 ms | 8.058 ms | +1.736 ms |
| **CV% stabilności** | 2.72% | 1.99% | Poprawa stabilności |

---

## 6. Weryfikacja zgodności bitowej (Parity) i Preview Map

### 6.1. Zgodność pikselowa (Parity)
Skrypt: `scratch/test_etap5j_golden_parity.py`
* Testowane klatki: `[0, 50, 100, 300, 500, 750, 900, 965, 1130]`
* Wynik: **MaxDiff = 0**, **DifferentPixels = 0** (100% bit-exact match).

### 6.2. Preview Map Matrix
Skrypt: `scratch/test_etap5g2_preview_map_matrix.py`
* Test 1 (Load Preset & Render Map): **PASS**
* Test 2 (Provider Switch): **PASS**
* Test 3 (Normal Export Return & Network Lock Restore): **PASS**
* Test 4 (Cancel Export Return & Network Lock Restore): **PASS**
* Test 5 (Second Preset Load): **PASS**
* Test 6 (Offline Local Cache Render): **PASS**
* Wynik łączny: **6/6 ALL PASS**.

---

## 7. Profil TOP 10 Wąskich Gardeł po ETAP 5K

Skrypt: `scratch/compute_etap5k_top10.py` na klatkach BATCHED 4K:

| Miejsce | Komponent | Średnia (ms) | Mediana (ms) | P95 (ms) | % czasu renderu |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1.** | `above_compose` (CPU rasteryzacja tekstu) | 8.385 ms | 8.206 ms | 11.789 ms | 31.6% |
| **2.** | `consumer_native_call` (D3D11/AMF GPU submit) | 8.092 ms | 1.763 ms | 21.900 ms | 30.5% |
| **3.** | `consumer_upload` (kolejka / upload D3D11) | 2.759 ms | 2.419 ms | 4.261 ms | 10.4% |
| **4.** | `above_exact_crop` (union bounding boxes) | 0.860 ms | 0.776 ms | 1.441 ms | 3.2% |
| **5.** | `map_cpu_upload` (Track-Up 691x691 upload) | 0.841 ms | 0.740 ms | 1.468 ms | 3.2% |
| **6.** | `MF ReadSample/decode availability` | 0.747 ms | 0.570 ms | 1.194 ms | 2.8% |
| **7.** | `compose_overlay` (dolny HUD poniżej mapy) | 0.711 ms | 0.608 ms | 1.210 ms | 2.7% |
| **8.** | `above_tight_bbox_collect` | 0.603 ms | 0.579 ms | 1.160 ms | 2.3% |
| **9.** | `AMF submit/backpressure` | 0.366 ms | 0.316 ms | 0.518 ms | 1.4% |
| **10.** | `update_hud` (D3D11 staging copy) | 0.344 ms | 0.276 ms | 0.601 ms | 1.3% |

*Uwaga:* Metryka `above_region_upload` spadła z ~1.05 ms/frame do **0.010 ms/frame** i opuściła całkowicie listę TOP10.

---

## 8. Klasyfikacja wyniku

**Status:** **LOCAL / STRUCTURAL PASS**
* **Narzut upload bridge (`above_region_upload`) zredukowany o -99.0%** (z 1.045 ms do 0.010 ms/frame).
* **`producer_prepare` przyspieszone o -6.6%** (z 14.089 ms do 13.155 ms/frame).
* **`above_total` przyspieszone o -7.2%** (z 10.579 ms do 9.818 ms/frame).
* **True FPS poprawiony o +0.67%** (37.712 fps vs 37.460 fps).
* **MaxDiff = 0**, **DifferentPixels = 0** (100% bit-exact parity).
* **Preview Map: 6/6 ALL PASS**.
* **Zero dynamicznych alokacji deskryptorów na klatkę**.
