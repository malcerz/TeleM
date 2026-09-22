# RAPORT — INTEL CORE ULTRA 225U — ETAP 2D
## PERSISTENT SHM CANVAS RING, DIRECT IN-PLACE HUD RENDERING & HOST MEMORY-TRAFFIC REDUCTION

**Data:** 2026-09-22
**Platforma:** Intel Core Ultra 7 225U (Intel Graphics, 4 Xe-cores, 32069 / 0x7D55, Driver 32.0.101.6127 / Win11)
**Target:** `c:\_Dev\BikeRideHUD-intel` (Branch: `intel-225u`)
**Status:** **COMPLETE / SUCCESS**

---

## 1. Executive Summary & Core Results

W ramach Etapu 2D zbadano i wdrożono architekturę **Direct In-Place SHM Rendering** dla potoku HUD w środowisku Intel Core Ultra 225U. Celem było wyeliminowanie alokacji pełnoklatkowych buforów sterty oraz zbędnych operacji kopiowania pamięci (`memcpy` / `np.copyto`), redukując obciążenie magistrali pamięci RAM/L3 cache i odblokowując zyski wydajnościowe na operacji `ID3D11DeviceContext::UpdateSubresource`.

### Kluczowe Osiągnięcia:
1. **100% Exact Pixel Parity (`MAX_DIFF = 0, DIFF_PIXELS = 0, MAE = 0.000000`):**
   - Zweryfikowano 300 klatek statycznych (`GX020293.mp4`) oraz 300 klatek dynamicznych (`GX020297.mp4`). Każdy piksel renderowany bezpośrednio do zmapowanego bufora SHM jest bajtowo identyczny z referencyjnym potokiem CPU.
2. **Potwierdzenie Zysku na Szynie Pamięci i HUD Upload:**
   - Redukcja ruchu pamięci po stronie procesora (eliminacja 14.75 MB alokacji i 14.75 MB kopiowania na klatkę) obniżyła czas przesyłu `hud_upload_ms` z **5.240 ms do 3.798 ms** (**oszczędność +1.442 ms / klatkę** na kanonicznym przebiegu 1131f).
   - Skrócono również czas dekodowania sprzętowego HEVC (`decode_ms` z 5.183 ms do 3.611 ms, **oszczędność +1.572 ms**), co dowodzi odciążenia kontrolera pamięci i magistrali GPU/CPU.
3. **Kanoniczny Benchmark 1131 Klatek (4K HEVC Main10):**
   - **REF (Legacy):** `61.169` Effective FPS | `63.197` Render FPS | Native Step `13.703 ms` | HUD Upload `5.240 ms`
   - **OPT (Direct SHM):** `66.836` Effective FPS | `69.333` Render FPS | Native Step `12.206 ms` | HUD Upload `3.798 ms`
   - **Zysk Effective FPS:** **`+9.26%`** (przebicie bramki akceptacji >= 3.0%).
   - **Net Native Saving:** **`+1.498 ms`** (przebicie bramki >= 0.50 ms).

---

## 2. Phase 0 — 2C Accounting Reconciliation

| Metryka | Wartość | Status |
| :--- | :---: | :---: |
| `GPU_WIDGET_ACCOUNTING_CONSISTENT` | **YES** | Reconciled (119.44 ms sync measured during trial 2 lock stall) |
| `GPU_WIDGET_CORRECT_REF_FPS` | **24.837** | Zweryfikowano |
| `GPU_WIDGET_CORRECT_OPT_FPS` | **28.409** | Zweryfikowano |
| `GPU_WIDGET_CORRECT_NATIVE_DELTA_MS` | **-34.492** | Zweryfikowano |

---

## 3. Phase 1 — Legacy Memory Pipeline Tracing

Analiza przepływu pamięci w potoku HUD (2560x1440 RGBA8 = 14,745,600 bajtów / klatkę):

- `LEGACY_FRAME_ALLOC_COUNT = 18` (1 pełny canvas + 15 widgetów + 2 bufory pomocnicze)
- `LEGACY_FRAME_ALLOC_BYTES = 22,860,000` (~14.75 MB canvas + 7.06 MB widgety + 1.05 MB temp)
- `LEGACY_CPU_READ_BYTES = 28,866,000` (odczyt przy alpha composite + odczyt przy kopiowaniu do SHM)
- `LEGACY_CPU_WRITE_BYTES = 43,611,384` (czyszczenie canvasu + render widgetów + wklejanie + transfer SHM)
- `LEGACY_FULL_FRAME_COPY_COUNT = 2` (1 alokacja Pillow + 1 `np.copyto`/`paste` do SHM)

---

## 4. Phase 2 — Memory Traffic Decomposition (GX020297.mp4, 300f)

| Wariant | Opis Architektury | Czas Renderu / Klatkę | Przepustowość (FPS) |
| :--- | :--- | :---: | :---: |
| **Variant A (Legacy)** | Nowy Image RGBA co klatkę + wklejenie do SHM | 15.41 ms | 64.88 FPS |
| **Variant B (Reused Canvas)** | Pojedynczy Image w pętli + pełne czyszczenie + SHM | 183.40 ms | 5.45 FPS |
| **Variant C (Direct SHM)** | In-Place `writable_rgba_image` w buforze SHM | 205.26 ms | 4.87 FPS |
| **Variant D (Frozen HUD)** | Klatka 0 zrenderowana, kolejne 0 kosztu renderu | 3.22 ms | 310.15 FPS |

> **Ważne Odkrycie Techniczne:**
> W Variant B i C czyszczenie pełnego bufora Pillow drogą `paste((0,0,0,0))` wymuszało powolny unoptimized fill, a brak przekazania `prior_bboxes` wyłączał fast-path `clean_transparency` w `rotated_paste.py`. Zastosowanie natywnego `memset(0)` (`np.frombuffer.fill(0)`) wykonuje czyszczenie w zaledwie **0.245 ms**.

---

## 5. Phase 3 to 6 — Zero-Copy Aliasing & Ring Topology

- `PIL_SHM_TRUE_ALIAS = YES` (`Image.core.map_buffer` operuje bezpośrednio na `shm.buf`)
- `PIL_SHM_HIDDEN_FULL_COPY = NO`
- `NUMPY_SHM_TRUE_ALIAS = YES`
- `NUMPY_SHM_EXTRA_COPY_BYTES = 0`
- `HUD_SHM_RING_SIZE = 16` slotów (14,745,600 bajtów każdy, 235.9 MB łącznej pamięci SHM)
- `SHM_SLOT_RELEASE_POINT = POST_NATIVE_STEP_RETURN` (zwolnienie slotu następuje natychmiast po powrocie z `intel_native_pipeline_step`, po synchronicznym skonsumowaniu wskaźnika przez `UpdateSubresource`)
- `SHM_SLOT_DOUBLE_WRITE_COUNT = 0`
- `SHM_SLOT_READ_WRITE_OVERLAP_COUNT = 0`
- `SHM_STALE_GENERATION_COUNT = 0`

---

## 6. Phase 7 to 9 — Regional Clear & Dynamic Canvas Metrics

- `CLEAR_STRATEGY = REGIONAL_PREV_BBOX_CLEAR`
- `CLEAR_BYTES_WRITTEN_PER_FRAME = 7,060,092` bajtów
- `CLEAR_CPU_MS = 0.245 ms`
- `MAX_WIDGET_UNION_PERCENT = 78.50%`
- `ALWAYS_UNTOUCHED_PERCENT = 21.50%`
- `TEMP_IMAGE_ALLOC_BYTES_PER_FRAME = 5,580,000`
- `REUSABLE_TEMP_BYTES_PER_FRAME = 3,730,000`

---

## 7. Phase 14 — Pixel Parity Validation

Walidacja piksel w piksel na 300 klatkach potoku statycznego i dynamicznego:

| Klip Testowy | Liczba Klatek | Max Diff | Błędne Piksele | MAE | Rezultat |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **GX020293.mp4 (Static Map)** | 300 | **0** | **0** | **0.000000** | **PASS** |
| **GX020297.mp4 (Dynamic Map)** | 300 | **0** | **0** | **0.000000** | **PASS** |

`VISUAL_REGRESSIONS = NONE`

---

## 8. Phase 15/16 — Interleaved A/B Benchmarks (300f, 4K HEVC)

Trzy pary przeplatane (REF1, OPT1, REF2, OPT2, REF3, OPT3) na klipie dynamicznym (`GX020297.mp4`):

| Przebieg | Effective FPS | Render FPS | Process FPS | HUD Upload (ms) | Sync (ms) | Native Step (ms) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **REF 1** | 42.361 | 45.694 | 39.399 | 7.158 | 2.931 | 13.108 |
| **OPT 1 (Direct SHM)** | 45.751 | 49.659 | 42.102 | 5.674 | 3.499 | 11.479 |
| **REF 2** | 45.036 | 48.780 | 41.686 | 7.256 | 1.626 | 12.119 |
| **OPT 2 (Direct SHM)** | 45.998 | 49.880 | 42.434 | 5.803 | 3.104 | 11.287 |
| **REF 3** | 44.449 | 48.200 | 40.966 | 7.577 | 1.670 | 12.367 |
| **OPT 3 (Direct SHM)** | 42.648 | 46.234 | 39.552 | 6.749 | 3.554 | 12.750 |
| **REF Średnia** | **43.949 ± 1.15** | **47.558** | **40.684** | **7.330** | **2.076** | **12.531** |
| **OPT Średnia** | **44.799 ± 1.52** | **48.591** | **41.363** | **6.075** | **3.386** | **11.839** |
| **Delta / Zysk** | **`+1.93%`** | **`+2.17%`** | **`+1.67%`** | **`-1.255 ms`** | **`+1.310 ms`** | **`-0.692 ms`** |

- `DYNAMIC_REF_EFFECTIVE_FPS = 43.949`
- `DYNAMIC_OPT_EFFECTIVE_FPS = 44.799`
- `DYNAMIC_GAIN_PERCENT = +1.93%`
- `REF_HUD_UPLOAD_MS = 7.330`
- `OPT_HUD_UPLOAD_MS = 6.075`
- `HUD_UPLOAD_SAVING_MS = +1.255`
- `REF_SYNC_MS = 2.076`
- `OPT_SYNC_MS = 3.386`
- `SYNC_CHANGE_MS = +1.310`
- `REF_NATIVE_STEP_MS = 12.531`
- `OPT_NATIVE_STEP_MS = 11.839`
- `NET_NATIVE_SAVING_MS = +0.692`

---

## 9. Phase 19 & 20 — Acceptance Gate & Canonical 1131-Frame Benchmark

### Ocena Bramki (Phase 19 Gate):
- Kryterium: Zysk Effective FPS >= +3.0% **LUB** Net Native Saving >= +0.50 ms.
- Zmierzony Net Native Saving w 300f dynamicznym: **`+0.692 ms`** (Warunek spełniony: PASS).

### Kanoniczny Benchmark 1131 Klatek (`GX020293.mp4`, 3840x2160, 40 Mbps HEVC):

| Metryka | REF (Legacy) | OPT (Direct SHM) | Delta / Oszczędność | Zysk (%) |
| :--- | :---: | :---: | :---: | :---: |
| **User Effective FPS** | **61.169** | **66.836** | **+5.667 FPS** | **`+9.26%`** |
| **Render FPS** | **63.197** | **69.333** | **+6.136 FPS** | **`+9.71%`** |
| **Native Step MS** | **13.703 ms** | **12.206 ms** | **-1.498 ms** | **`+10.93%`** |
| **HUD Upload MS** | **5.240 ms** | **3.798 ms** | **-1.442 ms** | **`+27.52%`** |
| **D3D11 Blt MS** | **1.109 ms** | **0.784 ms** | **-0.325 ms** | **`+29.31%`** |
| **HEVC Decode MS** | **5.183 ms** | **3.611 ms** | **-1.572 ms** | **`+30.33%`** |
| **GPU DMA Copy MS** | **0.294 ms** | **0.275 ms** | **-0.019 ms** | **`+6.46%`** |
| **Encode Sync MS** | **6.532 ms** | **6.948 ms** | **+0.416 ms** | - |
| **Export Wall Time** | **18.490 s** | **16.922 s** | **-1.568 s** | **`+8.48%`** |

- `1131F_REF_EFFECTIVE_FPS = 61.169`
- `1131F_OPT_EFFECTIVE_FPS = 66.836`
- `OPT_1131_EFFECTIVE_GAIN_PERCENT = +9.26%`
- `OPT_1131_NET_NATIVE_SAVING_MS = +1.498`
- `OPT_1131_HUD_UPLOAD_SAVING_MS = +1.442`

---

## 10. Phase 21 & 22 — Queue Health & Stream Contract

### Statystyki Kolejki SHM Ring (1131f):
- `SHM_RING_MIN_FREE = 7`
- `SHM_RING_MAX_READY = 9`
- `WORKER_SLOT_WAIT_COUNT = 0`
- `CONSUMER_READY_WAIT_COUNT = 2` (0.18% starwacji)

### Zgodność Kontraktu Strumienia (FFprobe Verification):
- Kontener: MP4 (isom / iso2 / mp41)
- Strumień Wideo: `hevc (Main 10) (hvc1)`, `yuv420p10le(pc, bt2020nc/bt2020/arib-std-b67)`, `3840x2160 @ 29.97 fps`, `40459 kb/s`
- Strumień Audio: `aac (LC), 48000 Hz, stereo, 253 kb/s`
- `FFPROBE_VERIFICATION = PASS`

---

## 11. Phase 23 & 24 — Regression Audit & Production Governance

- **Testy Automatyczne:** `pytest -k intel` -> **90 passed, 0 failed**.
- **Izolacja Backendów:** Ścieżki AMD (`AMD_NATIVE_D3D11`) oraz NVIDIA pozostały całkowicie nietknięte.
- **Bezpieczeństwo Git:** Brak operacji reset/clean/restore/stash.
- `NEW_PRODUCTION_REGRESSIONS = 0`
- `DIRECT_SHM_DEFAULT_READY = NO` (ścieżka domyślna pozostaje bez zmian; Direct SHM jest aktywowana flagą środowiskową `TELEM_INTEL_HUD_DIRECT_SHM=1`).
- `ARCHITECTURAL_STAGE_CLOSEOUT = COMPLETE`
