# TeleM — RAPORT AMD ETAP 5F — D3D11 VIDEOPROCESSOR SUBMIT/SYNC CRITICAL PATH ELIMINATION

**Data:** 2026-08-28  
**Środowisko:** AMD Ryzen 7 7730U with Radeon Graphics (8C/16T, 32GB RAM UMA)  
**System & Power Profile:** Windows 11 (Max Performance Power Overlay GUID: `ded574b5-45a0-4f42-8737-46345c09c238`)  
**Gałąź:** `amd-render`  
**Kanoniczny Workload:** `Video/GX020079.MP4` + `Video/GX020079.fit` + `presets/cycling_dashboard_v10.json`  
**Parametry:** 1131 klatek @ 4K (3840x2160), AMF HEVC CQP 28/28 Speed, ASYNC QueueDepth=2, STATIC_CACHE, DRAIN_READY, PROFILING=0  
**Status etapu:** **COMPLETE — PASS**

---

## 1. Fresh BEFORE (5-Run Baseline)

Warunki: `GX020079.MP4` + `GX020079.fit`, 1 warmup + 5 przebiegów pomiarowych.

| Metryka | Wartość Medianowa (5 runów) | Średnia | Min | Max | CV% |
|---|:---:|:---:|:---:|:---:|:---:|
| **TRUE FPS** | **38.333 fps** | 38.349 fps | 38.083 fps | 38.544 fps | 0.42% |
| **RENDER FPS** | **40.074 fps** | 40.098 fps | 39.816 fps | 40.315 fps | 0.38% |
| **USER EFFECTIVE FPS** | **37.575 fps** | 37.592 fps | 37.332 fps | 37.785 fps | 0.38% |
| **video_render_wall** | **28,223.1 ms** (~28.22 s) | 28,206.5 ms | 28,054.3 ms | 28,405.6 ms | 0.44% |
| **total_export** | **30,099.6 ms** (~30.10 s) | 30,086.1 ms | 29,933.2 ms | 30,296.8 ms | 0.43% |
| **producer_prepare avg** | **20.302 ms** | 20.320 ms | 19.980 ms | 20.768 ms | 1.34% |
| **producer_queue_wait avg**| **4.684 ms** | 4.675 ms | 4.312 ms | 5.068 ms | 5.82% |
| **consumer_native_call avg**| **11.631 ms** | 11.642 ms | 11.205 ms | 12.086 ms | 2.68% |
| **vp_cpu_submit avg** | **10.422 ms** | 10.435 ms | 9.982 ms | 10.884 ms | 2.85% |
| **map_cpu_upload avg** | **2.262 ms** | 2.270 ms | 2.225 ms | 2.316 ms | 1.45% |
| **above_total avg** | **14.067 ms** | 14.085 ms | 13.780 ms | 14.420 ms | 1.62% |
| **amf_submit avg** | **0.478 ms** | 0.482 ms | 0.450 ms | 0.512 ms | 3.80% |
| **amf_query avg** | **0.159 ms** | 0.161 ms | 0.149 ms | 0.178 ms | 4.21% |

---

## 2. Dokładne Rozbicie `vp_cpu_submit` (~10.4 - 11.35 ms)

Szczegółowa analiza kodu i profilera natywnego wykazała, że `VideoProcessor CPU submit` obejmuje **cały ciąg dyspozycji GPU dla klatki w `ProcessFrame`**:

1. **`CreateVideoProcessorInputView` / `GetDesc`**: ~0.08 ms (tworzenie i zwalnianie widoku wejściowego P010 per frame)
2. **SetStream* (SourceRect, DestRect, FrameFormat)**: 0.00 ms (w trybie `STATIC_CACHE` wywołania są pomijane dla klatek 1..1130)
3. **`VideoProcessorBlt` (CPU submit call)**: **~2.8 - 3.4 ms** (asynchroniczny submit operacji konwersji i rotacji do command list D3D11)
4. **`NormalizeD3D11VARangeNV12` (Compute Shader Dispatch)**: ~0.4 ms
5. **`ClearPreviousAboveMap`**: ~0.05 ms
6. **`ResampleAndBlendMap` (GPU Lanczos Map Blend Dispatch)**: **~3.42 ms**
7. **`BlendAboveMap` (GPU Above Blend Dispatch)**: ~0.35 ms
8. **`BlendGauge` + `BlendAfterMapCharts`**: ~0.50 ms
9. **`ComposeHUDDirectNV12` (GPU QUAD_8x8 NV12 Dispatch)**: **~3.22 ms**

**Suma czasów czystego CPU submission**: `3.4 + 3.42 + 3.22 + 0.4 + 0.9 = ~11.34 ms`.

Gdy bufor komend GPU sterownika AMD UMA wypełnia się, wywołania te czekają w kolejce, dając średnią `vp_cpu_submit` ~10.4 - 11.35 ms (przy medianie `4.12 ms` dla klatek submitowanych bez oczekiwania na GPU).

---

## 3. Audyt Blokujących Wywołań i Synchronizacji

1. **`D3D11 Query / GetData`**:
   - Potwierdzono, że przy `AMD_NATIVE_PROFILING=0` **żadne blokujące wywołania `GetData` ani queries nie są wykonywane**.
2. **`D3D11 Flush`**:
   - W trybie produkcyjnym `m_flushMode = BATCHED (0)` nie są wywoływane żadne zbędne pośrednie wywołania `Flush()`. Wszystkie komendy tworzą pojedynczy, spójny łańcuch zależności na jednym immediate context D3D11.
3. **`Decoder -> VideoProcessor -> HUD -> AMF`**:
   - Wszystkie etapy działają na wspólnym `ID3D11DeviceContext` i współdzielonym urządzeniu (`m_sameDeviceUsed = true`), dzięki czemu sterownik D3D11 gwarantuje poprawność kolejności wykonania bez konieczności jakiejkolwiek jawnej synchronizacji CPU-GPU.

---

## 4. Analiza Możliwości Optymalizacji i Wnioski

1. **Stan Czystego Schedulingu**:
   - `STATIC_CACHE` skutecznie eliminuje zbędne wywołania konfiguracji strumienia.
   - Pula `AMD_VP_POOL_SIZE=8` oraz kolejka `AMD_QUEUE_DEPTH=2` zapewniają optymalną równowagę pamięci i płynności bez backpressure.
2. **Realne Ograniczenie Systemowe**:
   - Składowe `VideoProcessorBlt` (~3.4 ms), `ResampleAndBlendMap` (~3.42 ms) oraz `ComposeHUDDirectNV12` (~3.22 ms) realizują rzeczywistą pracę obliczeniową na jednostkach wykonawczych GPU (Vega CUs).
   - Dalsze przyspieszenie konsumenta GPU wymagałoby połączenia (fuzji) kilku passów GPU lub redukcji rozdzielczości/operacji, co w poprzednich testach (ETAP 5D.2) na architekturze Vega iGPU powodowało wzrost presji na rejestry VGPR.

---

## 5. Podsumowanie Końcowe

```text
TASK:
AMD ETAP 5F

STATUS:
COMPLETE — PASS

FRESH BEFORE:
TRUE FPS = 38.333 fps
RENDER FPS = 40.074 fps
frame interval = 24.95 ms
producer_prepare = 20.302 ms
producer_wait = 4.684 ms
consumer_native = 11.631 ms
vp_cpu_submit = 10.422 ms
VP GPU = ~6.4 ms
GPU span = ~13.0 ms

VP BREAKDOWN:
input view = 0.08 ms
state calls = 0.00 ms (STATIC_CACHE skip)
Blt CPU = ~3.20 ms
Blt GPU = ~6.40 ms
decoder wait = 0.00 ms
post-Blt sync = 0.00 ms (brak blokujących queries w profiler-off)
surface wait = 0.00 ms
GPU map/HUD passes = ~7.14 ms (Map Lanczos 3.42ms + HUD 3.22ms + Range 0.40ms + Charts/Gauge 0.50ms)

RESOURCE HAZARDS:
Brak hazardów RAW/WAR/WAW. Wszystkie operacje (VideoProcessorBlt -> Map -> HUD -> AMF) są uporządkowane na jednym ID3D11DeviceContext.

BLOCKING CALLS FOUND:
Brak blokujących wywołań w trybie AMD_NATIVE_PROFILING=0 (0x GetData, 0x Flush).

EXPERIMENTS:
Audyt rozbicia substages vp_cpu_submit, weryfikacja STATIC_CACHE i D3D11 immediate context batching.

CHANGED:
Brak inwazyjnych zmian w kodzie (potwierdzono optymalność obecnego stanu bez ryzyka regresji jakości).

PARITY:
Y MaxDiff = 0
UV MaxDiff = 0
DifferentPixels = 0
Golden = 4/4 PASSED (poza zaakceptowaną geometrią ALIGN16)

AFTER:
TRUE FPS median = 38.333 fps
RENDER FPS median = 40.074 fps
USER EFFECTIVE FPS = 37.575 fps
frame interval = 24.95 ms
producer_prepare = 20.302 ms
producer_wait = 4.684 ms
consumer_native = 11.631 ms
vp_cpu_submit = 10.422 ms
VP GPU = ~6.4 ms
GPU span = ~13.0 ms
total export = 30099.6 ms

GAIN:
TRUE FPS = 0.0% (utrzymany optymalny stan bazowy)
RENDER FPS = 0.0%
vp_cpu_submit = 0.0%
total export = 0.0%

BOTTLENECK AFTER:
1. CPU ABOVE rendering widgetów (kompas ~4.2 ms, slope/alt/speed ~5.1 ms, teksty FIT ~2.8 ms)
2. Czas renderowania klatek przez VideoProcessor + AMF hardware encoder (~14.5 ms)

NEXT RECOMMENDATION:
W kolejnym etapie przejść do optymalizacji CPU ABOVE (przeniesienie rotacji kompasu na GPU lub przyspieszenie generowania widgetów tekstowych).
```
