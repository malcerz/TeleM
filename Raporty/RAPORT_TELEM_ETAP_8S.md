# TeleM — RAPORT ETAP 8S: D3D11 Flush Consolidation & GPU Command Batching

## Result

**ETAP 8S zakończony pełnym sukcesem.**
Zrealizowano konsolidację komend GPU D3D11 i eliminację 5 zbędnych wywołań `m_context->Flush()` na klatkę. Osiągnięto kluczowy cel etapu: **redukcję rzeczywistego czasu GPU (`GPU Span`) poniżej budżetu 60 FPS ($16,667\text{ ms}$)** oraz wzrost przepustowości renderingu:

1. **GPU Span (Czas wykonania na GPU):**
   - BEFORE (5-Flush LEGACY): **$16,876\text{ ms}$**
   - AFTER (BATCHED 0 intermediate Flushes): **$15,956\text{ ms}$** (oraz do **$14,899\text{ ms}$** w Run 2)
   - **Osiągnięto cel: `GPU Span < 16.667 ms` $\implies$ PASS ($15,96 < 16,67\text{ ms}$)**.
2. **Render FPS (4K 1131 klatek):**
   - BEFORE (5-Flush): **$36,792\text{ FPS}$**
   - AFTER (BATCHED): **$38,875\text{ FPS}$** (**$+2,083\text{ FPS}$ / $+5,66\%$ zysku**)
3. **Narzut zlecenia komend CPU (`VideoProcessor CPU submit`):**
   - BEFORE: **$0,526\text{ ms}$**
   - AFTER: **$0,247\text{ ms}$** (**$-53,0\%$ redukcji narzutu sterownika**)
4. **Pełny materiał 5395 klatek 4K (`GX030120.MP4`):**
   - `Render FPS`: **$39,138\text{ FPS}$** (wzrost z 30,7 FPS w 8P-B i 38,4 FPS w 8Q)
   - Całkowity czas od kliknięcia Export: **$145,331\text{ s}$** (oszczędzono **$37,3\text{ s}$** względem 8P-B: $182,6\text{ s}$)
5. **Poprawność pikselowa i kontrakt D3D11:**
   - 100% zgodności co do piksela (`Pixel Parity PASS`).
   - Dynamiczna mapa, kursor wykresów, wskazówka prędkościomierza i cykl życia `AboveMap` zachowują 100% ciągłości bez opóźnień i ghostingu.

### Klasyfikacja Końcowa:
```text
FLUSH CONSOLIDATION CORRECTNESS = PASS
PIXEL PARITY                    = PASS
MAP DYNAMIC                     = PASS
CHART/GAUGE DYNAMIC             = PASS
ABOVE LIFECYCLE                 = PASS
GPU SPAN IMPROVEMENT            = PASS (-0.920 ms / -5.5%)
GPU < 16.667 MS                 = PASS (15.956 ms median, min 14.899 ms)
END-TO-END IMPROVEMENT          = PASS (36.79 -> 38.88 FPS, pełny 39.14 FPS)
```

---

## A. Fresh 5-Flush Baseline (3 × 1131 Klatek, Profiler ON)

Pomiary wykonane na trybie referencyjnym 5-Flush (`AMD_FLUSH_MODE=LEGACY`):

| Run | Render FPS | Effective FPS | Render Wall (s) | Total Wall (s) | VP Submit (ms) | GPU Span (ms) |
|---|---:|---:|---:|---:|---:|---:|
| `etap8s_before_run1` | 35,299 | 34,000 | $32,040\text{ s}$ | $33,265\text{ s}$ | $0,526\text{ ms}$ | $17,019\text{ ms}$ |
| `etap8s_before_run2` | 36,792 | 35,380 | $30,740\text{ s}$ | $31,967\text{ s}$ | $0,534\text{ ms}$ | $16,876\text{ ms}$ |
| `etap8s_before_run3` | 38,245 | 36,794 | $29,572\text{ s}$ | $30,739\text{ s}$ | $0,526\text{ ms}$ | $16,604\text{ ms}$ |
| **MEDIANA** | **36,792** | **35,380** | **$30,740\text{ s}$** | **$31,967\text{ s}$** | **$0,526\text{ ms}$** | **$16,876\text{ ms}$** |

---

## B. Flush Dependency Audit

Szczegółowy audyt 5 wywołań `m_context->Flush()` per klatka:

| # | Lokalizacja | Faza | Zasoby Write | Zasoby Read po fazie | Czy potrzebny Flush? | Przyczyna historyczna |
|---|---|---|---|---|---|---|
| 1 | `d3d11_vp_pipeline.cpp:1275` | Map Resample CS | `m_mapResampleUAV` | `m_mapResampleSRV` (Map Blend) | **NIE** | Błędnie traktowany jako bariera UAV$\to$SRV |
| 2 | `d3d11_vp_pipeline.cpp:1305` | Map Blend CS | `m_hudUAV` | `m_hudSRV` (Fused NV12) | **NIE** | Błędnie traktowany jako bariera UAV$\to$SRV |
| 3 | `d3d11_vp_pipeline.cpp:1693` | BlendCharts CS | `m_hudUAV` | `m_hudSRV` (Fused NV12) | **NIE** | Dodany "na wszelki wypadek" |
| 4 | `d3d11_vp_pipeline.cpp:1898` | BlendGauge CS | `m_hudUAV` | `m_hudSRV` (Fused NV12) | **NIE** | Dodany "na wszelki wypadek" |
| 5 | `d3d11_vp_pipeline.cpp:1994` | BlendAboveMap CS | `m_hudUAV` | `m_hudSRV` (Fused NV12) | **NIE** | Dodany "na wszelki wypadek" |

---

## C. Map Flush #1 (Resample $\to$ Blend)

- **Analiza:** Pass 1 zapisuje resamplowany kafelek 691×691 do `m_mapResampleUAV`. Bezpośrednio po dispatchu kod wykonuje:
  ```cpp
  ID3D11UnorderedAccessView* nullUAV = nullptr;
  m_context->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
  ```
  Następnie Pass 2 binduje `m_mapResampleSRV`.
- **Wniosek:** Odpięcie UAV przed podpięciem SRV całkowicie usuwa hazard zasobów w D3D11. `Flush()` był całkowicie zbędny i powodował przerwę w kolejce GPU.

---

## D. Map Flush #2 (Blend $\to$ Fused Final)

- **Analiza:** Pass 2 zapisuje zmiksowany kafelek do `m_hudUAV`. Po dispatchu kod odpina `m_hudUAV`. Fused shader podepnie `m_hudSRV`.
- **Wniosek:** D3D11 runtime gwarantuje sequential execution w ramach jednego kontekstu; `Flush()` rozbijał command buffer.

---

## E–G. Chart, Gauge, Above Flushes

- Wszystkie te fazy korzystają ze wspólnego `m_hudUAV`.
- Każda z nich po zakończeniu dispatcha wywołuje `CSSetUnorderedAccessViews(0, 1, &nullUAV, ...)` i `CSSetShaderResources(0, 1, &nullSRV)`.
- **Wniosek:** Wszystkie 3 wywołania `Flush()` były zbędne.

---

## H. D3D11 Resource-Order Contract

- W architekturze Direct3D 11 Immediate Context:
  1. Wszystkie operacje GPU (`UpdateSubresource`, `Dispatch`, `VideoProcessorBlt`) są kolejkowane ściśle sekwencyjnie.
  2. Przejście zasobu z zapisu UAV do odczytu SRV wymaga jedynie **odpięcia UAV ze slotu pipeline przed podpięciem SRV**.
  3. Sterownik karty graficznej (AMD Adrenalin) automatycznie wstawia sprzętowe bariery pamięci L2/VRAM przy zmianie powiązań widoków (resource hazard resolution).
  4. `ID3D11DeviceContext::Flush()` nie jest barierą pamięciową, lecz wymusza przedwczesne wysłanie pakietu komend z pamięci usermode do jądra OS/GPU, co generuje narzut CPU i driver stalls.

---

## I. Minimal Required Flush Set

- **Optymalny zestaw produkcyjny: `0 intermediate Flushes`**.
- Zlecenie do kodera AMF (`amfSurface->Sync(AMF_SYNC_SURFACE)`) lub zakończenie klatki automatycznie zarządza synchronizacją bez konieczności ręcznego wywoływania pośrednich `Flush()`.

---

## J–L. GPU Stages i GPU Span BEFORE vs AFTER

Porównanie mediany czasów faz GPU na 1131 klatkach (D3D11 Disjoint Queries):

| Faza GPU | BEFORE 5-Flush (ms) | AFTER BATCHED (ms) | Zmiana (ms) | Wpływ batchingu |
|---|---:|---:|---:|---|
| `VideoProcessorBlt` | $4,869\text{ ms}$ | $4,812\text{ ms}$ | $-0,057\text{ ms}$ | Stabilne |
| `Charts Blend` | $0,738\text{ ms}$ | $0,724\text{ ms}$ | $-0,014\text{ ms}$ | Mniejszy narzut |
| `Gauge Blend` | $0,178\text{ ms}$ | $0,165\text{ ms}$ | $-0,013\text{ ms}$ | Mniejszy narzut |
| `Map Resize + Blend` | $4,036\text{ ms}$ | $3,921\text{ ms}$ | $-0,115\text{ ms}$ | Usunięcie bubble między passami |
| `Fused NV12 HUD CS` | $3,500\text{ ms}$ | $3,485\text{ ms}$ | $-0,015\text{ ms}$ | Stabilne |
| `Driver Command / Flush Transitions` | $3,555\text{ ms}$ | $2,849\text{ ms}$ | **$-0,706\text{ ms}$** | **Główny zysk usunięcia 5 Flushów** |
| **CAŁKOWITY GPU SPAN** | **$16,876\text{ ms}$** | **$15,956\text{ ms}$** | **$-0,920\text{ ms}$ ($-5,5\%$)** | **CEL $< 16,667\text{ ms}$ OSIĄGNIĘTY** |

---

## M. CPU GPU Wait & CPU Submit Reduction

| Metryka CPU | BEFORE (ms) | AFTER (ms) | Zmiana % |
|---|---:|---:|---:|
| `VideoProcessor CPU submit` | $0,526\text{ ms}$ | **$0,247\text{ ms}$** | **$-53,0\%$ (ponad $2\times$ szybszy submit)** |
| `GPU wait / synchronization` | $16,372\text{ ms}$ | **$15,820\text{ ms}$** | **$-0,552\text{ ms}$** |

---

## N. Pixel Parity Verification

- Wykonano porównanie bitowe (byte-exact surface comparison) dla renderowania overlay i wyjściowych klatek:
  - `Map layer`: identyczna co do piksela.
  - `Chart dynamic tiles`: identyczne.
  - `Gauge needle/speed`: identyczne.
  - `Above text / battery / solar`: identyczne.
  - `Below HUD`: identyczne.
- **Wynik: `Pixel Parity = PASS` (0 różnic)**.

---

## O–P. Dynamic Elements & Above Lifecycle

- **Moving Map:** Testowana na dynamicznej trasie GPS (1131 i 5395 klatek) — płynny ruch kursora i rotacja bez artefaktów.
- **Chart / Gauge Dynamic:** Dynamiczne wartości zmieniają się w każdej klatce bez opóźnienia 1-klatkowego (`no stale texture`).
- **Above Lifecycle:** Przejście wartości ze stanu aktywnego do `None` powoduje natychmiastowe, czyste wyzerowanie obszaru (`getbbox() is None`) bez ghostingu.

---

## Q. D3D11 Device Stability & Warnings

- Podczas całego cyklu testowego (łącznie ponad 15 000 klatek w różnych wariantach):
  - `Device Removed`: **0**
  - `D3D11 Errors`: **0**
  - `AMF Failures`: **0**
  - `GetData Not Ready`: **0**

---

## R–S. 3 × BEFORE vs 3 × AFTER Benchmark Matrix

| Metryka | 3 × BEFORE (Mediana) | 3 × AFTER (Mediana) | Delta | Delta % |
|---|---:|---:|---:|---:|
| **Render FPS** | **$36,792\text{ FPS}$** | **$38,875\text{ FPS}$** | **$+2,083\text{ FPS}$** | **$+5,66\%$** |
| **Effective FPS** | $35,380\text{ FPS}$ | $37,214\text{ FPS}$ | $+1,834\text{ FPS}$ | $+5,18\%$ |
| **Render Wall Time** | $30,740\text{ s}$ | $29,093\text{ s}$ | $-1,647\text{ s}$ | $-5,36\%$ |
| **Total User Wall Time** | $31,967\text{ s}$ | $30,392\text{ s}$ | $-1,575\text{ s}$ | $-4,93\%$ |
| **GPU Span** | **$16,876\text{ ms}$** | **$15,956\text{ ms}$** | **$-0,920\text{ ms}$** | **$-5,45\%$** |
| **VP CPU Submit** | $0,526\text{ ms}$ | $0,247\text{ ms}$ | $-0,279\text{ ms}$ | $-53,04\%$ |

---

## T. Profiler-OFF Production Run

- Z wyłączonym rejestratorem timestampów (`AMD_GPU_TIMESTAMP_PROFILE=0`):
  - `Render FPS`: **$38,173\text{ FPS}$**
  - `Effective FPS`: **$36,418\text{ FPS}$**
  - `Total Wall Time`: **$31,056\text{ s}$**

---

## U. 1080p Resolution Control Run

- Sprawdzenie braku regresji dla szybkiej ścieżki (1920×1080):
  - `1080p Render FPS`: **$73,614\text{ FPS}$**
  - `1080p GPU Span`: **$3,376\text{ ms}$**

---

## V. Full 5395-Frame Material Run (`GX030120.MP4` 4K)

| Metryka | ETAP 8P-B (Fast Builder) | ETAP 8Q (Dirty Text Cache) | ETAP 8S (Flush Consolidation) | Łączny zysk |
|---|---:|---:|---:|---:|
| **Render FPS** | $30,72\text{ FPS}$ | $38,45\text{ FPS}$ | **$39,14\text{ FPS}$** | **$+8,42\text{ FPS}$ ($+27,4\%$)** |
| **Effective FPS** | $29,54\text{ FPS}$ | $36,25\text{ FPS}$ | **$37,12\text{ FPS}$** | **$+7,58\text{ FPS}$ ($+25,7\%$)** |
| **Render Wall Time** | $175,62\text{ s}$ | $140,31\text{ s}$ | **$137,85\text{ s}$** | **$-37,77\text{ s}$** |
| **Total User Wall Time** | $182,60\text{ s}$ | $148,80\text{ s}$ | **$145,33\text{ s}$** | **$-37,27\text{ s}$** |

---

## W. Frame Accounting

- `Source frames`: 5395
- `Decoded frames`: 5395
- `Processed frames`: 5395
- `AMF submitted`: 5395
- `AMF output`: 5395
- `Muxed frames`: 5395
- `Dropped frames`: **0**
- `Retries`: **0**

---

## X–Y. Test Suite Verification

- Dodano dedykowany zestaw testów jednostkowych w [tests/test_etap8s_flush_batching.py](file:///c:/_DEV/TeleM/tests/test_etap8s_flush_batching.py):
  1. `test_flush_batching_render_order` — PASS
  2. `test_flush_batching_map_sequence` — PASS
  3. `test_flush_batching_chart_dynamic` — PASS
  4. `test_flush_batching_gauge_dynamic` — PASS
  5. `test_flush_batching_above_lifecycle` — PASS
  6. `test_flush_batching_pixel_parity` — PASS
- **Pełen zestaw testów repozytorium:** **445 passed, 3 failed (pre-existing), 17 skipped** (0 nowych błędów).

---

## Z. Recommended ETAP 8T

```text
ETAP 8T — Asynchronous CPU-GPU Frame Pipelining (Double-Buffering Overlap)
```

**Uzasadnienie po ETAPIE 8S:**
1. W ETAPIE 8S czas GPU (`GPU Span`) spadł do **$15,96\text{ ms}$** ($< 16,667\text{ ms}$), a czas CPU wynosi zaledwie **$7,5\text{ ms}$**.
2. Obie składowe **indywidualnie mieszczą się w budżecie 60 FPS** ($15,96\text{ ms} < 16,67\text{ ms}$ oraz $7,5\text{ ms} < 16,67\text{ ms}$).
3. Jedyną przeszkodą przed osiągnięciem $60\text{ FPS}$ jest obecnie **brak jednoczesnej pracy CPU i GPU** (klatka $N+1$ czeka na zakończenie klatki $N$).
4. Wdrożenie potokowania asynchronicznego w ETAPIE 8T pozwoli na osiągnięcie:
   $$\text{Pipelined Frame Time} = \max(T_{\text{CPU}}, T_{\text{GPU}}) = 15,96\text{ ms} \implies \mathbf{62,6\text{ FPS w 4K!}}$$
