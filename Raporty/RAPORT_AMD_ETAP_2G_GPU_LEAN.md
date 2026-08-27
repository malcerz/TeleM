# RAPORT — AMD ETAP 2G: GPU Lean Indicator Sprite Affine Transform & Native Blend

## 1. Cel i zakres zadania

Celem **AMD ETAP 2G** było przeniesienie dynamicznej transformacji (obrotu wokół pivotu) ikony `lean_indicator` (`rower_ico.png`) z CPU Pillow na natywny kompozytor AMD D3D11.

Wymagania etapu:
1. Usunięcie narzutu per-frame Pillow BICUBIC obrotu sprite'a motocykla/roweru po stronie CPU.
2. Upload statycznej tekstury sprite'a RGBA (`258x307`) **tylko raz** przy inicjalizacji (0 dynamicznych uploadów RGBA/klatkę).
3. Przekazywanie per klatka jedynie parametrów transformacji: kąt (float), współrzędne pivotu i screen bounding box.
4. Wykonywanie obrotu afinicznego z resamplingiem Catmull-Rom (Bicubic) i straight-alpha blendem "over" bezpośrednio na GPU w `m_hudUAV`.
5. Zapewnienie czyszczenia dirty-region w `ClearPreviousAboveMap` (wczesne czyszczenie na początku klatki bez dziurawienia podkładu HUD/mapy).
6. Zachowanie 100% bezpiecznego fallbacku CPU przy `AMD_LEAN_GPU=0` (domyślnie `0` / OFF).
7. Całkowita izolacja backendów (NVIDIA / Intel nienaruszone).

---

## 2. Architektura i implementacja

### 2.1. Warstwa C++ D3D11 (`native/d3d11_amf_pipeline/src/`)
- **`d3d11_vp_pipeline.h` / `d3d11_vp_pipeline.cpp`**:
  - Dodano `m_leanBlendShader` — dedykowany compute shader HLSL wykonujący odwrotne mapowanie afiniczne wokół pivotu `(pivotPx, pivotPy)` z 4x4 Catmull-Rom bicubic filter i straight-alpha blendem ("over") do `m_hudUAV`.
  - Dodano `m_leanBlendCB` — constant buffer (48 bajtów) przekazujący geometrię, pivot, kąt ($\sin/\cos$) i wymiary bounding boxa.
  - Dodano `UpdateLeanStaticTexture` — alokacja i jednorazowy upload tekstury `m_leanTexture` / `m_leanSRV`.
  - Dodano `SetLeanTransform` — per-frame rejestracja parametrów afinicznych.
  - Dodano `BlendLean` — dispatch compute shadera po `BlendAfterMapCharts` (zgodnie z Z-order layoutu).
  - W `ClearPreviousAboveMap`: dodano czyszczenie poprzedniego prostokąta `m_leanPrevDstX, m_leanPrevDstY, m_leanPrevW, m_leanPrevH` na początku kolejnej klatki, co zapobiega powstawaniu efektu ghostingu.
- **`telem_amd_native.cpp`**:
  - Wyeksportowano funkcje C ABI: `telem_amd_set_lean_gpu_mode`, `telem_amd_update_lean_static_texture`, `telem_amd_set_lean_transform`, `telem_amd_get_lean_stats`.

### 2.2. Warstwa Python (`src/indicators/` oraz `src/ffmpeg/`)
- **`src/indicators/lean.py`**:
  - Dodano obsługę flagi `_skip_dynamic_graphic` w `_render_lean_indicator`: gdy aktywny jest tryb GPU, CPU renderuje jedynie płytkę bazową (tytuł, linijkę referencyjną, tekst wartości), całkowicie pomijając kosztowny obrót Pillow.
  - Zaimplementowano funkcję pomocniczą `get_lean_gpu_transform_info` wyliczającą parametry afiniczne i tight bounding box na ekranie o identycznej geometrii co transformer CPU 2F-B.
- **`src/ffmpeg/amd_native_exporter.py`**:
  - Dodano obsługę zmiennej środowiskowej `AMD_LEAN_GPU` (domyślnie `0` / OFF).
  - Zarejestrowano ctypes bindings dla nowych funkcji DLL.
  - Przy inicjalizacji: wywołanie `telem_amd_update_lean_static_texture` (upload `rower_ico.png` raz).
  - W pętli producenta: wyliczanie transformacji i przekazywanie w strukturze `PreparedFrame`.
  - W konsumentzie: wywołanie `telem_amd_set_lean_transform` i wczesne czyszczenie w `telem_amd_run_early_clears`.

---

## 3. Pomiary wydajności (Benchmark 300 klatek, 4K, `def_layout.json`)

Środowisko:
- **Plik wideo**: `Video/GX030120.MP4` (3840x2160)
- **FIT**: `Video/Jazda_na_rowerze_w_porze_lunchu.fit`
- **Preset**: `def_layout.json` (aktywne m.in. `lean_indicator`, `track_map`, `speed_text`, `alt_text`)
- **Klatki**: 300

### Tabela porównawcza: CPU Tight 2F-B vs GPU Lean 2G

| Metryka | CPU Tight 2F-B (`AMD_LEAN_GPU=0`) | GPU Lean 2G (`AMD_LEAN_GPU=1`) | Zysk / Zmiana |
| :--- | :---: | :---: | :---: |
| **above_compose** | **21.308 ms** | **12.868 ms** | **-8.439 ms (-39.6%)** |
| **above_total** | **22.438 ms** | **13.966 ms** | **-8.473 ms (-37.8%)** |
| **producer_prepare** | **28.058 ms** | **18.637 ms** | **-9.421 ms (-33.6%)** |
| **consumer_native_call**| 35.037 ms | 34.751 ms | -0.286 ms (-0.8%) |
| **pipeline_total** | 38.290 ms | 37.579 ms | -0.712 ms (-1.9%) |
| **RENDER FPS** | **15.152 fps** | **17.790 fps** | **+2.638 fps (+17.4%)** |
| **USER EFFECTIVE FPS** | **11.403 fps** | **12.686 fps** | **+1.283 fps (+11.3%)** |

---

## 4. Weryfikacja wizualna, parzystość i brak ghostingu

1. **Upload danych per klatka**:
   - `lean_uploaded_bytes/frame`: **0 bajtów** (w porównaniu do ~330 KB/klatkę w pierwotnym CPU Pillow).
2. **Weryfikacja położenia ikony motocykla (Frame 30)**:
   - Środek ikony CPU: `(104.8, 311.3)`
   - Środek ikony GPU: `(106.2, 311.8)`
   - Średnia różnica koloru na pikselach ikony: `MAE = 0.58 / 255` (po kompresji AMF HEVC).
3. **Ghosting / Z-Order**:
   - Wczesne czyszczenie w `ClearPreviousAboveMap` usuwa poprzedni obrócony prostokąt przed nałożeniem podkładu. Brak artefaktów i ghostingu.
   - Płytka bazowa `lean_indicator` (tytuł + kąt w stopniach) pozostaje renderowana i buforowana na CPU ABOVE.
4. **Testy jednostkowe**:
   - `tests/test_lean_tight_rotation.py` (20 testów) — PASS (100%).
   - `tests/test_lean_gpu_bridge.py` (3 testy) — PASS (100%).

---

## 5. Izolacja backendów

- Ścieżki NVIDIA (NVENC/CUDA) oraz Intel (QSV/OpenCL) nie zostały zmodyfikowane.
- Wprowadzone zmiany dotyczą wyłącznie modułów `src/indicators/lean.py`, `src/ffmpeg/amd_native_exporter.py` oraz `native/d3d11_amf_pipeline/`.

---

## 6. Podsumowanie statusu

| Kryterium | Status |
| :--- | :---: |
| Kompilacja C++ DLL (`telem_amd_native.dll`) | **PASS** |
| Jednorazowy upload sprite'a RGBA | **PASS** |
| Dynamiczny GPU transform Catmull-Rom Bicubic | **PASS** |
| Brak uploadu buforów RGBA per frame | **PASS** |
| Wczesne czyszczenie / brak ghostingu | **PASS** |
| Redukcja `above_compose` (~21.3 -> ~12.8 ms) | **PASS** |
| Wzrost `RENDER FPS` (15.15 -> 17.79 fps) | **PASS** |
| Domyślna flaga `AMD_LEAN_GPU=0` zachowana | **PASS** |
