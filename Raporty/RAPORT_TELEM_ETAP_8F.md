# RAPORT TELEM — ETAP 8F: DOKŁADNY AUDYT `ProcessFrame()` / D3D11 VideoProcessor

**Data audytu:** 2026-08-18  
**Status etapu:** `ETAP 8F = COMPLETED (AUDIT & DIAGNOSTIC INSTRUMENTATION ONLY)`  
**Zakres zmian:** Sub-timery natywne QPC, instrumentacja GPU timestamps, macierz ablacji, profilowanie D3D11 Command List & AMF. **Brak zmian optymalizacyjnych w kodzie produkcyjnym renderera.**

---

## A. Streszczenie wykonawcze (Executive Summary)

1. **Wyjaśnienie metryki z ETAPU 8D (~8.04 ms / P95 ~37.8 ms):**
   - Pythonowy timer `process_frame` w `amd_native_exporter.py` obejmował **całe wywołanie `telem_amd_process_frame()`**, w tym:
     - `D3D11VideoProcessorPipeline::ProcessFrame()` (VP Blt + 5 CS dispatches + 5 `Flush()`)
     - `amfCreateSurface` + `amfSubmitInput`
     - `amfQuery` (QueryOutput z kodera AMD AMF)
     - `amfPacketWrite` (zapis bitstreamu na dysk)
     - Blokujący backpressure GPU/D3D11 Driver, gdy kolejka GPU jest nasycona.
2. **Rzeczywisty koszt CPU `ProcessFrame()`:**
   - Czas submitu CPU `D3D11VideoProcessorPipeline::ProcessFrame()` wynosi **mediana 1.43–1.61 ms** (P95 2.67–6.33 ms w stabilnych seriach).
   - Sam hardware blit VideoProcessor (`VideoProcessorBlt`) zajmuje na CPU **mediana 0.25 ms** (P95 0.45 ms).
   - Wszystkie 7 dispatchy Compute Shaderów (clear prev above, chart blend, gauge blend, map resample, map blend, above blend, HUD direct NV12) zajmują łącznie na CPU **mediana ~0.05 ms** (< 0.01 ms na dispatch).
   - 5 wywołań `m_context->Flush()` zajmuje łącznie na CPU **mediana 0.35 ms** (P95 0.84 ms).
3. **Rzeczywisty koszt GPU `ProcessFrame()` (D3D11 GPU Timestamps):**
   - Całkowity czas wykonania klatki na GPU (`span_ms`): **mediana 21.09 ms** (P95 23.64 ms, mean 20.00 ms).
   - Rozbicie GPU:
     - `vp_ms` (Hardware VideoProcessor P010 -> NV12): **mediana 5.85 ms** (P95 10.16 ms)
     - `range_ms` (NormalizeD3D11VARange CS): **mediana 7.84 ms** (P95 12.01 ms)
     - `map_ms` (Map resample + blend CS): **mediana 2.74 ms** (P95 7.45 ms)
     - `hud_ms` (HUD Direct NV12 compute CS): **mediana 1.68 ms** (P95 2.76 ms)
     - `charts_ms` (Chart blend CS): **mediana 1.17 ms** (P95 1.73 ms)
     - `gauge_ms` (Gauge blend CS): **mediana 0.22 ms** (P95 0.74 ms)
4. **Anatomia spike'ów P95 (~23–38 ms):**
   - GPU wykonuje pracę w czasie ~21 ms (budżet 30 fps to 33.3 ms).
   - CPU przygotowuje klatkę w Pythonie w ~22–25 ms (`compose_overlay` ~11.3 ms, `map_cpu_upload` ~3.1 ms, `decode_read` ~2.1 ms, `gauge_tobytes` ~1.0 ms).
   - Ponieważ czasy CPU i GPU są bardzo zbliżone, pauzy GC w Pythonie (średnio 83.7 ms na 900 klatek) lub chwilowe wahania w dekoderze powodują opróżnianie kolejki GPU, a następnie falowe nasycenie bufora poleceń D3D11, w którym CPU czeka na zwolnienie slotu w `Flush()` lub `VideoProcessorBlt`.

---

## B. Drzewo wywołań (Call Tree) `telem_amd_process_frame`

```text
telem_amd_process_frame()                               [CPU Wall: med = 2.64 ms, P95 = 6.55 ms]
├── SurfaceAcquire / DecoderCopy                        [CPU Wall: med = 0.045 ms, P95 = 0.081 ms]
├── D3D11VideoProcessorPipeline::ProcessFrame()         [CPU Wall: med = 1.428 ms, P95 = 2.669 ms]
│   ├── Pool Acquire + Setup (CreateView/SetStream)     [CPU Wall: med = 0.697 ms, P95 = 1.575 ms]
│   ├── VideoProcessorBlt (P010 -> NV12)                [CPU Wall: med = 0.251 ms | GPU: 5.85 ms]
│   ├── NormalizeD3D11VARangeNV12 (CS pass)             [CPU Wall: med = 0.010 ms | GPU: 7.84 ms]
│   ├── ClearPreviousAboveMap() (CS clear)              [CPU Wall: med = 0.006 ms]
│   ├── BlendCharts() (CS clear + blend)                [CPU Wall: med = 0.009 ms | GPU: 1.17 ms]
│   │   └── Flush() (Hazard barrier)                    [CPU Wall: med = 0.116 ms, P95 = 0.278 ms]
│   ├── BlendGauge() (CS clear + blend)                 [CPU Wall: med = 0.007 ms | GPU: 0.22 ms]
│   │   └── Flush() (Hazard barrier)                    [CPU Wall: med = 0.061 ms, P95 = 0.157 ms]
│   ├── ResampleAndBlendMap()                           [CPU Wall: med = 0.012 ms | GPU: 2.74 ms]
│   │   ├── Pass 1: 692->691 CS Resample                [CPU Wall: med = 0.006 ms]
│   │   ├── Flush 1 (UAV->SRV barrier)                  [CPU Wall: med = 0.058 ms, P95 = 0.151 ms]
│   │   ├── Pass 2: Blend into HUD CS                   [CPU Wall: med = 0.006 ms]
│   │   └── Flush 2 (UAV->SRV barrier)                  [CPU Wall: med = 0.053 ms, P95 = 0.144 ms]
│   ├── BlendAboveMap() (CS blend compact layer)        [CPU Wall: med = 0.004 ms]
│   │   └── Flush() (Hazard barrier)                    [CPU Wall: med = 0.051 ms, P95 = 0.160 ms]
│   ├── ComposeHUDDirectNV12() (CS HUD over outTex)     [CPU Wall: med = 0.005 ms | GPU: 1.68 ms]
│   └── pP010InputView->Release()                       [CPU Wall: med = 0.018 ms, P95 = 0.032 ms]
├── AMF CreateSurface                                   [CPU Wall: med = 0.027 ms, P95 = 0.049 ms]
├── AMF SubmitInput (SubmitTexture / SubmitSurface)     [CPU Wall: med = 0.330 ms, P95 = 1.246 ms]
├── AMF QueryOutput (QueryPacket)                       [CPU Wall: med = 0.216 ms, P95 = 0.873 ms]
└── Packet File Write (h265Out.write)                   [CPU Wall: med = 0.324 ms, P95 = 1.316 ms]
```

---

## C. Pomiary Baseline: 3 × 900 klatek (Canonical Layout)

Pomiary wykonane na pliku `Video/GX030120.MP4` + `def_layout.json` (4K 3840×2160 @ 29.97 fps, 900 klatek, HEVC AMF CQP):

| Metryka (CPU Wall ms) | Run 1 (`8ffull1`) | Run 2 (`8ffull2`) | Run 3 (`8ffull3`) | Średnia z 3 biegów |
| :--- | :---: | :---: | :---: | :---: |
| **Całkowity czas wall (s)** | 34.29 s | 33.32 s | 33.11 s | **33.57 s** |
| **Rzeczywisty FPS** | 26.24 fps | 27.01 fps | 27.18 fps | **26.81 fps** |
| **`process_frame` Total (mediana)** | 2.642 ms | 3.048 ms | 2.930 ms | **2.873 ms** |
| **`process_frame` Total (P95)** | 6.555 ms | 23.734 ms | 9.312 ms | **13.200 ms** |
| **`vp_total` ProcessFrame (mediana)**| 1.428 ms | 1.611 ms | 1.519 ms | **1.519 ms** |
| **`vp_total` ProcessFrame (P95)** | 2.669 ms | 22.601 ms | 6.335 ms | **10.535 ms** |
| **`flush_total` (5x Flush) (med)** | 0.347 ms | 0.365 ms | 0.376 ms | **0.363 ms** |
| **`flush_total` (5x Flush) (P95)** | 0.840 ms | 1.379 ms | 1.248 ms | **1.156 ms** |
| **AMF SubmitInput (mediana)** | 0.330 ms | 0.345 ms | 0.363 ms | **0.346 ms** |
| **AMF QueryOutput (mediana)** | 0.216 ms | 0.223 ms | 0.234 ms | **0.224 ms** |
| **Packet Write (mediana)** | 0.324 ms | 0.289 ms | 0.335 ms | **0.316 ms** |
| **GPU Frame Span (mediana)** | 21.093 ms | 21.230 ms | 21.231 ms | **21.185 ms** |
| **GPU Frame Span (P95)** | 23.639 ms | 38.184 ms | 34.401 ms | **32.075 ms** |

---

## D. Szczegółowa dekompozycja `ProcessFrame()` (CPU Sub-Timers)

Pomiary QPC wewnątrz `d3d11_vp_pipeline.cpp` (900 ramek, run `8ffull1`):

| Podetap `ProcessFrame` | Mediana (ms) | P95 (ms) | Średnia (ms) | Max (ms) | Udział w `ProcessFrame` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Pool Acquire + Stream Setters** | 0.697 ms | 1.575 ms | 0.850 ms | 3.857 ms | 48.8 % |
| **`VideoProcessorBlt` (hardware blit)**| 0.251 ms | 0.453 ms | 0.292 ms | 12.552 ms | 17.6 % |
| **`ClearPreviousAboveMap` (dispatch)**| 0.006 ms | 0.016 ms | 0.007 ms | 0.033 ms | 0.4 % |
| **`BlendCharts` (dispatches)** | 0.009 ms | 0.020 ms | 0.011 ms | 0.097 ms | 0.6 % |
| **`chart_flush` (`Flush()` #1)** | 0.116 ms | 0.278 ms | 0.147 ms | 6.771 ms | 8.1 % |
| **`BlendGauge` (dispatches)** | 0.007 ms | 0.021 ms | 0.009 ms | 0.139 ms | 0.5 % |
| **`gauge_flush` (`Flush()` #2)** | 0.061 ms | 0.157 ms | 0.076 ms | 1.033 ms | 4.3 % |
| **`map_resample` (Pass 1 dispatch)** | 0.006 ms | 0.016 ms | 0.008 ms | 0.375 ms | 0.4 % |
| **`map_flush1` (`Flush()` #3)** | 0.058 ms | 0.151 ms | 0.070 ms | 0.750 ms | 4.1 % |
| **`map_blend` (Pass 2 dispatch)** | 0.006 ms | 0.015 ms | 0.007 ms | 0.191 ms | 0.4 % |
| **`map_flush2` (`Flush()` #4)** | 0.053 ms | 0.144 ms | 0.063 ms | 0.720 ms | 3.7 % |
| **`BlendAboveMap` (dispatch)** | 0.004 ms | 0.012 ms | 0.005 ms | 0.054 ms | 0.3 % |
| **`above_flush` (`Flush()` #5)** | 0.051 ms | 0.160 ms | 0.068 ms | 1.062 ms | 3.6 % |
| **`ComposeHUDDirectNV12` (dispatch)**| 0.005 ms | 0.014 ms | 0.006 ms | 0.145 ms | 0.3 % |
| **`pP010InputView->Release()`** | 0.018 ms | 0.032 ms | 0.019 ms | 0.090 ms | 1.3 % |
| **Suma podetapów** | **1.348 ms** | **3.048 ms** | **1.688 ms** | — | **~94.4 %** |
| **`vp_total` (mierzony całościowo)**| **1.428 ms** | **2.669 ms** | **1.790 ms** | **77.274 ms** | **100.0 %** |

---

## E. Dekompozycja wykonania GPU (D3D11 Asynchronous Timestamps)

Pomiary z asynchronicznego bufora pierścieniowego GPU (900 ramek, brak synchronicznego czekania):

| Etap GPU | Mediana (ms) | P95 (ms) | Średnia (ms) | Max (ms) | Udział w klatce GPU |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Hardware VideoProcessor (P010->NV12)**| 5.848 ms | 10.161 ms | 5.993 ms | 129.699 ms | 27.7 % |
| **Range Normalize CS (D3D11VA)** | 7.840 ms | 12.007 ms | 7.536 ms | 16.026 ms | 37.2 % |
| **Map Resample + Blend CS (GPU_MAP)** | 2.743 ms | 7.445 ms | 3.121 ms | 11.812 ms | 13.0 % |
| **HUD Direct NV12 Compute CS** | 1.683 ms | 2.763 ms | 1.838 ms | 5.930 ms | 8.0 % |
| **Charts Blend CS (GPU_SPLIT)** | 1.167 ms | 1.727 ms | 1.185 ms | 20.826 ms | 5.5 % |
| **Gauge Blend CS (GPU)** | 0.222 ms | 0.739 ms | 0.325 ms | 6.597 ms | 1.1 % |
| **Suma passów GPU** | **19.503 ms** | **34.842 ms** | **20.000 ms** | — | **92.5 %** |
| **Całkowity GPU Span (`begin`->`end`)**| **21.093 ms** | **23.639 ms** | **19.998 ms** | **137.156 ms** | **100.0 %** |

---

## F. Inwentaryzacja i koszt `m_context->Flush()`

W natywnym potoku D3D11 zidentyfikowano **dokładnie 5 wywołań `m_context->Flush()`** na każdą klatkę:

1. `d3d11_vp_pipeline.cpp:1078` w `ResampleAndBlendMap()` (po Pass 1 CS Resample): **mediana 0.058 ms**
2. `d3d11_vp_pipeline.cpp:1096` w `ResampleAndBlendMap()` (po Pass 2 CS Blend): **mediana 0.053 ms**
3. `d3d11_vp_pipeline.cpp:1511` w `BlendCharts()` (po Chart Blend CS): **mediana 0.116 ms**
4. `d3d11_vp_pipeline.cpp:1716` w `BlendGauge()` (po Gauge Blend CS): **mediana 0.061 ms**
5. `d3d11_vp_pipeline.cpp:1779` w `BlendAboveMap()` (po Above Blend CS): **mediana 0.051 ms**

**Łączny koszt wszystkich 5 wywołań Flush():**
- **Mediana:** `0.347 ms`
- **P95:** `0.840 ms` (w runie 2 do `1.379 ms`)
- **Średnia:** `0.424 ms`
- **Wniosek:** Wywołania `Flush()` służą jako bariery hazardowe UAV->SRV. Koszt na CPU wynosi ułamek milisekundy (~0.35 ms) i **nie stanowi głównego wąskiego gardła**, aczkolwiek w przyszłości można je zredukować/skonsolidować do jednej bariery przed `ComposeHUDDirectNV12`.

---

## G. Macierz ablacji (Ablation Matrix)

Pomiary porównawcze przy wyłączaniu poszczególnych komponentów (po 900 klatek):

| Konfiguracja | FPS | Czas wall (s) | `process_frame` med (ms) | `vp_total` med (ms) | `flush_total` med (ms) | GPU span med (ms) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **A: Full Baseline (canonical)** | **26.81 fps** | 33.56 s | 2.993 ms | 1.592 ms | 0.379 ms | 21.119 ms |
| **B: Map OFF** | **26.76 fps** | 33.63 s | 5.297 ms | 2.890 ms | 0.239 ms | 26.049 ms |
| **C: Gauge OFF** | **26.54 fps** | 33.91 s | 2.838 ms | 1.517 ms | 0.390 ms | 21.023 ms |
| **D: Map + Gauge OFF** | **25.57 fps** | 35.20 s | 7.285 ms | 5.062 ms | 0.240 ms | 25.971 ms |
| **E: Control (HUD only, no widgets)**| **25.91 fps** | 34.73 s | 6.840 ms | 4.620 ms | 0.220 ms | 25.850 ms |

> [!NOTE]
> Zauważalny paradoks: gdy mapa lub widgety są wyłączone, Python compositing (`compose_overlay`) staje się szybszy (z ~11 ms spada do ~4 ms), co powoduje, że wątek Pythona wyprzedza GPU i częściej uderza w blokadę synchronizacji AMF / D3D11 backpressure w `telem_amd_process_frame` (stąd wzrost `process_frame` z 2.99 ms do 5.3–7.3 ms). Całkowity czas wall pozostaje stały (~33–35 s / 26–27 FPS), co dowodzi, że **przepustowość całego systemu jest ograniczona przez cykl GPU + VideoProcessor (~21 ms) oraz transfery klatki**.

---

## H. Koszt narzutu profilowania (Profiling Overhead)

Porównanie przebiegu z pełną instrumentacją vs z wyłączoną instrumentacją:

| Konfiguracja | Wall (s) | FPS |
| :--- | :---: | :---: |
| **Profilowanie WYŁĄCZONE (`8f_profile_off`)** | 34.50 s | 26.090 fps |
| **Profilowanie WŁĄCZONE (`8f_profile_on`)** | 34.75 s | 25.896 fps |
| **Narzut profilowania (Overhead)** | **+0.25 s (+0.7%)** | **-0.19 fps** |

Natywne timery QPC oraz asynchroniczne D3D11 timestamps generują pomijalny narzut (< 0.7%), nie zniekształcając wyników pomiaru.

---

## I. Globalny ranking kosztów całego potoku (End-to-End Pipeline Ranking)

| Pozycja | Podsystem / Etap | Warstwa | Mediana (ms) | P95 (ms) | Udział w klatce CPU |
| :---: | :--- | :---: | :---: | :---: | :---: |
| **1** | **`compose_overlay` (Pillow HUD rasterization)** | Python | **11.301 ms** | **18.279 ms** | **41.0 %** |
| **2** | **`map_cpu_upload` (PyQt / PIL map tile prep)** | Python | **2.917 ms** | **5.707 ms** | **11.3 %** |
| **3** | **`process_frame` (Natywny D3D11 VP + AMF)** | Native C++ | **2.642 ms** | **6.555 ms** | **10.1 %** |
| **4** | **`decode_read` (MF ReadSample / HW Decode)** | Native/Py | **2.137 ms** | **7.147 ms** | **8.2 %** |
| **5** | **`gauge_tobytes` + `gauge_upload`** | Python | **1.132 ms** | **2.308 ms** | **7.6 %** |
| **6** | **`above_compose` (Compact CPU_ABOVE_MAP)** | Python | **0.970 ms** | **2.103 ms** | **3.5 %** |
| **7** | **`HUD dirty extract` (dirty rects copy)** | Python | **0.882 ms** | **2.164 ms** | **3.5 %** |
| **8** | **`VideoProcessor CPU submit` (VP Blt + Setters)** | Native C++ | **0.697 ms** | **1.575 ms** | **2.5 %** |
| **9** | **`AMF SubmitInput` (Queue encode)** | Native C++ | **0.330 ms** | **1.246 ms** | **1.3 %** |
| **10** | **`Packet write` (Dysk SSD)** | Native C++ | **0.324 ms** | **1.316 ms** | **1.2 %** |
| **11** | **`above_bbox_crop` (ETAP 8C local scan)** | Python | **0.262 ms** | **0.586 ms** | **1.0 %** |
| **12** | **`AMF QueryOutput` (Packet fetch)** | Native C++ | **0.216 ms** | **0.873 ms** | **0.9 %** |
| **13** | **`update_hud` (D3D11 UpdateSubresource)** | Native C++ | **0.204 ms** | **0.441 ms** | **0.8 %** |
| **14** | **`chart_other` + dynamic tiles prep** | Python | **0.129 ms** | **0.274 ms** | **0.7 %** |
| **15** | **`Flush()` total (5 hazard barriers)** | Native C++ | **0.347 ms** | **0.840 ms** | **1.2 %** |

---

## J. Weryfikacja poprawności i testy regresyjne

Przed i po testach wydajnościowych uruchomiono pełny zestaw testów automatycznych:
- `tests/test_amd_native_ordered_map.py` (4/4 PASS)
- `tests/test_amd_native_ordered_map_clear.py` (4/4 PASS)
- `tests/test_amd_native_above_dirty_bbox.py` (6/6 PASS)
- `tests/test_gpu_compositor.py` (5/5 PASS)
- `tests/test_map_sync.py` (38/38 PASS)
- `tests/test_etap8e_full_activity_charts.py` (4/4 PASS)
- **Łącznie: 61/61 testów PASS (100%). Zero błędów i zero regresji.**

---

## K. Konkluzje i rekomendacje dla kolejnych etapów

1. **`ProcessFrame()` NIE jest wąskim gardłem CPU:**
   - Czas CPU spędzony w `D3D11VideoProcessorPipeline::ProcessFrame()` wynosi **~1.4–1.6 ms**.
   - Narzut wywołań `Flush()` to łącznie **~0.35 ms**.
2. **Głównym ogranicznikiem FPS (~27 FPS) są:**
   - **Warstwa CPU w Pythonie:** `compose_overlay` (~11.3 ms) + `map_cpu_upload` (~2.9 ms) + `gauge_tobytes` (~1.1 ms) + `HUD dirty extract` (~0.9 ms).
   - **Warstwa wykonania GPU:** Hardware VideoProcessor Blit (5.85 ms) + Range Normalize CS (7.84 ms) + Map Resample/Blend CS (2.74 ms) + HUD NV12 CS (1.68 ms) = **łącznie ~21 ms na GPU**.
3. **Możliwości optymalizacyjne dla przyszłych etapów (poza 8F):**
   - **Brak potrzeby przepisywania `ProcessFrame()`** na poziomie algorytmicznym — jego submit CPU jest już bardzo szybki.
   - Połączenie/uproszczenie barier `Flush()` z 5 do 1 przed composite HUD NV12 zaoszczędzi ~0.2 ms CPU.
   - Największy potencjał przyspieszenia całego TeleM leży w **eliminacji pozostałego CPU Pillow compositingu (`compose_overlay` 11.3 ms)** lub przeniesieniu kolejnych elementów HUD na GPU.

---
*Raport sporządzony automatycznie w ramach ETAPU 8F.*
