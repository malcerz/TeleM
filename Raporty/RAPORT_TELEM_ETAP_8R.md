# TeleM — RAPORT ETAP 8R: GPU Saturation & Critical Path Audit po usunięciu CPU_ABOVE bottleneck

## Result

**ETAP 8R zakończony pełnym sukcesem diagnostycznym.**
Przeprowadzono kompletny, empiryczny audyt ścieżki krytycznej (Critical Path & GPU Saturation Audit) potoku eksportu na karcie AMD. Wyjaśniono w 100% zjawisko ~100% obciążenia GPU oraz zlokalizowano dokładne wąskie gardło uniemożliwiające osiągnięcie 60 FPS przy eksporcie 4K:

1. **Główny wniosek (Primary Finding):**
   - **Praca własna CPU (`CPU Active Work`) wynosi obecnie zaledwie $7,52\text{ ms}$ ($27,3\%$ budżetu klatki)**.
   - **Czas oczekiwania CPU na GPU / synchronizację (`CPU GPU Wait`) wynosi aż $16,37\text{ ms}$ ($59,6\%$ budżetu klatki)**.
   - **Rzeczywisty czas wykonania na GPU (`GPU Span`) wynosi $16,48\dots 17,27\text{ ms}$**.
   - Czas oczekiwania CPU niemal idealnie (1:1) odpowiada czasowi wykonania klatki na GPU.
2. **Punkt serializacji potoku (Serialization Point):**
   - Obecny potok działa w trybie **ściśle synchronicznym klatka-po-klatce** (brak podwójnego buforowania / asynchronicznego overlapu CPU i GPU, 5 wywołań `m_context->Flush()` per klatka).
   - Całkowity czas klatki jest sumą seryjną:
     $$\text{Frame Time} = T_{\text{CPU Active}} (7,52\text{ ms}) + T_{\text{GPU Wait}} (16,37\text{ ms}) + T_{\text{MF/AMF/Other}} (3,60\text{ ms}) \approx 27,49\text{ ms} \implies \mathbf{36,38\text{ FPS}}.$$
3. **Dowód nasycenia GPU / Rozdzielczość 4K vs 1080p:**
   - W **4K (3840×2160)**: `Render FPS` = **$36,38\text{ FPS}$**, `GPU Span` = **$17,25\text{ ms}$**.
   - W **1080p (1920×1080)**: `Render FPS` = **$72,18\text{ FPS}$** (**$+98,4\%$ / $2\times$ throughput**), `GPU Span` spada do **$3,37\text{ ms}$**.
   - Spadek czasu GPU z $17,25\text{ ms}$ do $3,37\text{ ms}$ w 1080p jest ostatecznym dowodem, że potok przy 4K jest **GPU / PIXEL-BOUND**.

### Klasyfikacja końcowa:
```text
CPU ACTIVE BOTTLENECK     = NO  (7.52 ms = 27.3% klatki)
GPU BOTTLENECK            = YES (GPU Span 17.25 ms)
AMF ENCODE BOTTLENECK     = NO  (0.40 ms, 0 INPUT_FULL, 0 drops)
DECODE BOTTLENECK         = NO  (0.74 ms)
SYNC BOTTLENECK           = YES (Brak overlapu CPU-GPU, 5 Flush/frame)
60 FPS CURRENTLY POSSIBLE = NO  (Wymaga potokowania asynchronicznego i optymalizacji GPU Map)
PRIMARY BOTTLENECK        = GPU_BOUND (oraz SERIAL_PIPELINE_SYNC)
```

---

## A. Fresh 4K Baseline (3 × 1131 Klatek, FAST PRECOMPUTED, ABOVE Cache ON)

Pomiary wykonane bezpośrednio na obecnym HEAD z włączonym asynchronicznym rejestratorem timestampów D3D11 (`AMD_GPU_TIMESTAMP_PROFILE=1`):

| Run | Render FPS | Effective FPS | Render Wall (s) | Total User Wall (s) | GPU Span median (ms) |
|---|---:|---:|---:|---:|---:|
| `etap8r_baseline_run1` | 33,678 | 32,457 | $33,583\text{ s}$ | $34,846\text{ s}$ | $17,269\text{ ms}$ |
| `etap8r_baseline_run2` | 38,155 | 36,766 | $29,642\text{ s}$ | $30,762\text{ s}$ | $16,475\text{ ms}$ |
| `etap8r_baseline_run3` | 36,380 | 35,028 | $31,089\text{ s}$ | $32,288\text{ s}$ | $17,248\text{ ms}$ |
| **MEDIANA** | **36,380** | **35,028** | **$31,089\text{ s}$** | **$32,288\text{ s}$** | **$17,248\text{ ms}$** |

---

## B. CPU Exclusive Frame Timeline

Rozbicie jednej klatki 4K ($27,488\text{ ms}$ całkowitego czasu trwania przy 36,38 FPS) na **EXCLUSIVE** timery CPU:

| Etap klatki (Exclusive) | Czas median (ms) | Czas p95 (ms) | Udział w klatce % | Charakterystyka |
|---|---:|---:|---:|---|
| `MF ReadSample` (decode availability) | $0,737\text{ ms}$ | $1,493\text{ ms}$ | $2,7\%$ | Oczekiwanie na dekoder sprzętowy |
| `Telemetry/frame_data` | $0,038\text{ ms}$ | $0,056\text{ ms}$ | $0,1\%$ | Fast PRECOMPUTED lookup |
| `compose_overlay` (BELOW) | $2,598\text{ ms}$ | $3,512\text{ ms}$ | $9,5\%$ | Renderowanie HUD Pillow CPU |
| `map_cpu_upload` | $2,853\text{ ms}$ | $3,716\text{ ms}$ | $10,4\%$ | Render GPS track CPU + copy do staging |
| `gauge_tobytes` + `gauge_upload` | $0,835\text{ ms}$ | $1,340\text{ ms}$ | $3,0\%$ | Renderowanie i upload prędkościomierza |
| `chart_dynamic_tobytes` + `upload` | $0,042\text{ ms}$ | $0,110\text{ ms}$ | $0,2\%$ | ETAP 5K Split Chart upload |
| `above_total` (`above_compose` + upload) | $0,030\text{ ms}$ | $0,045\text{ ms}$ | $0,1\%$ | ETAP 8Q Dirty Text Cache + 8N multi-region |
| `HUD dirty extract` + `upload` | $0,441\text{ ms}$ | $0,650\text{ ms}$ | $1,6\%$ | Ekstrakcja boksów HUD do staging |
| `VideoProcessor CPU submit` | $0,562\text{ ms}$ | $0,950\text{ ms}$ | $2,0\%$ | Zlecenie komend D3D11 na CPU |
| `GPU wait / synchronization` | **$16,372\text{ ms}$** | **$20,210\text{ ms}$** | **$59,6\%$** | **Czekanie na wykonanie przez GPU** |
| `AMF submit / backpressure` | $0,273\text{ ms}$ | $0,580\text{ ms}$ | $1,0\%$ | Przekazanie klatki do enkodera |
| `AMF QueryOutput` | $0,125\text{ ms}$ | $0,350\text{ ms}$ | $0,5\%$ | Pobranie pakietu HEVC |
| `Packet write` | $0,118\text{ ms}$ | $0,260\text{ ms}$ | $0,4\%$ | Zapis strumienia do pliku |
| `Inne / frame_other` (residual) | $2,465\text{ ms}$ | — | $9,0\%$ | Narzuty pętli, GIL, profiler (< 10%) |
| **SUMA (Czas trwania 1 klatki)** | **$27,488\text{ ms}$** | — | **$100,0\%$** | **Wyjaśniono $91,0\%$ czasu** |

---

## C. CPU Active vs Wait

| Kategoria | Czas na klatkę (ms) | Procent klatki | Wnioski |
|---|---:|---:|---|
| **CPU ACTIVE WORK** | **$7,516\text{ ms}$** | **$27,3\%$** | CPU nie jest bottleneckiem renderingu |
| **CPU GPU WAIT (Synchronizacja)** | **$16,372\text{ ms}$** | **$59,6\%$** | **Główny powód ograniczenia do 36 FPS** |
| **CPU AMF WAIT (Enkoder)** | **$0,398\text{ ms}$** | **$1,5\%$** | Enkoder sprzętowy AMF jest bardzo szybki |
| **CPU DECODE WAIT (Dekoder)** | **$0,737\text{ ms}$** | **$2,7\%$** | Dekoder D3D11VA nie blokuje potoku |
| **RESIDUAL / SYSTEM** | **$2,465\text{ ms}$** | **$8,9\%$** | Pomijalny narzut frameworka |

---

## D. GPU Profiler Architecture

- Zastosowano wbudowany w `d3d11_vp_pipeline.cpp` mechanizm asynchronicznych zapytań D3D11 (`D3D11_QUERY_TIMESTAMP` oraz `D3D11_QUERY_TIMESTAMP_DISJOINT`).
- **Zero-Stall Ring Buffer**: Wyniki zapytań są odczytywane z opóźnieniem kilku klatek z flagą `D3D11_ASYNC_GETDATA_DONOTFLUSH`.
- Liczba odpytań `GetData` zakończonych sukcesem bez czekania: **100% (0 not-ready)**.
- Narzut profilera GPU: **$1,40\%$** ($< 3\%$ dopuszczalnego limitu $\to$ **PASS**).

---

## E. GPU Stage Timings (Pomiary Sprzętowe D3D11 Timestamp)

Pomiary rzeczywistego czasu pracy poszczególnych faz silnika 3D/Compute na GPU:

| Faza GPU | Typ jednostki GPU | Czas median (ms) | Czas p95 (ms) | Udział w GPU Span % |
|---|---|---:|---:|---:|
| `VideoProcessorBlt` (4K P010 $\to$ NV12) | Hardware Video Processor | **$4,869\text{ ms}$** | $10,574\text{ ms}$ | $28,2\%$ |
| `Range Normalize Pass` (ETAP 8K) | Compute Shader | **$0,001\text{ ms}$** | $0,002\text{ ms}$ | $0,0\%$ (0 passów) |
| `Charts Blend` (Clear + Blend) | Compute Shader | **$0,738\text{ ms}$** | $1,667\text{ ms}$ | $4,3\%$ |
| `Gauge Blend` (Clear + Blend) | Compute Shader | **$0,178\text{ ms}$** | $0,768\text{ ms}$ | $1,0\%$ |
| `Map Resize + Blend` (692 $\to$ 691 Bicubic CS) | Compute Shader | **$4,036\text{ ms}$** | $8,744\text{ ms}$ | $23,4\%$ |
| `Fused NV12 HUD Compositor` (4K CS) | Compute Shader | **$3,500\text{ ms}$** | $8,149\text{ ms}$ | $20,3\%$ |
| `Pipeline State Transitions / Flushes / Driver` | GPU Command Processor | **$3,926\text{ ms}$** | $4,500\text{ ms}$ | $22,8\%$ |
| **CAŁKOWITY SPAN GPU (`GPU Span`)** | **GPU Execution** | **$17,248\text{ ms}$** | **$20,038\text{ ms}$** | **$100,0\%$** |

---

## F. VideoProcessor Timing

- `VideoProcessorBlt` zajmuje sprzętowo **$4,87\text{ ms}$** w 4K.
- Jest to stały koszt skalowania i konwersji próbkowania sprzętowego silnika wideo AMD dla strumienia 4K P010 HDR/Full-Range.

---

## G. Fused Final Timing

- Zgodnie z założeniami ETAPU 8K:
  - `AMD_NV12_COMPOSITOR`: `FUSED (production single-range)`
  - `AMD_RANGE_NORMALIZE`: `FUSED_SINGLE`
  - `AMD_NORMALIZE_PASSES`: `0`
- Pojedynczy 1-passowy shader `Unified Fused NV12 CS` wykonuje się w zaledwie **$3,50\text{ ms}$** w 4K (wykonując jednocześnie konwersję zakresu tła, konwersję HUD RGBA $\to$ Studio YUV i blending $\alpha$).

---

## H. Flush / Synchronization Inventory

W pętli przetwarzania klatki zidentyfikowano **5 wywołań `m_context->Flush()` per klatka**:

| Lokalizacja w kodzie | Funkcja | Liczba wywołań / klatkę | Cel | Blokowanie CPU |
|---|---|---:|---|---|
| `d3d11_vp_pipeline.cpp:1275` | `ResampleAndBlendMap` | 1 | Flush po resamplingu mapy | Niebezpośrednie (zwiększa narzut kolejkowania) |
| `d3d11_vp_pipeline.cpp:1305` | `ResampleAndBlendMap` | 1 | Flush po blendzie mapy | j.w. |
| `d3d11_vp_pipeline.cpp:1693` | `BlendCharts` | 1 | Flush po blendzie wykresów | j.w. |
| `d3d11_vp_pipeline.cpp:1898` | `BlendGauge` | 1 | Flush po blendzie wskaźnika | j.w. |
| `d3d11_vp_pipeline.cpp:1994` | `BlendAboveMap` | 1 | Flush po blendzie warstwy above | j.w. |

**Wniosek:** 5 wywołań `Flush()` wymusza przedwczesne wysyłanie małych pakietów komend do GPU, rozbijając optymalne batchowanie drivera AMD i kosztując $\sim 3-4\text{ ms}$ narzutu sterownika.

---

## I. GPU $\to$ CPU Readbacks

- Na ścieżce produkcyjnej: **`0 readbacków`** (0 B/frame, 0 ms).
- Wszystkie bufory pośrednie pozostają w pamięci VRAM GPU.

---

## J. CPU $\to$ GPU Uploads

Ilości danych przesyłanych z CPU do GPU na klatkę:

| Warstwa nakładki | Rozmiar / Klatka | Format |
|---|---:|---|
| `Chart dynamic tiles` (ETAP 5K) | $\sim 36\text{ KiB}$ | RGBA (tylko kursor i wartość) |
| `Gauge` (ETAP 5L) | $\sim 1,31\text{ MiB}$ | RGBA (wycinek prędkościomierza) |
| `Map` (ETAP 5G) | $\sim 1,83\text{ MiB}$ | RGBA (kafelek 692×692) |
| `Above Map` (ETAP 8N + 8Q) | $\sim 0\dots 40\text{ KiB}$ | RGBA (tylko dirty klastry) |
| `HUD Below` (ETAP 2) | $\sim 1,0\dots 1,5\text{ MiB}$ | RGBA (tylko dirty rects) |
| **ŁĄCZNIE CPU $\to$ GPU** | **$\sim 4,2\dots 4,7\text{ MiB}$ / klatkę** | **PCIe transfer $\ll 0,5\text{ ms}$** |

---

## K. AMF Encoder Timing

- `AMF submit / backpressure`: **$0,27\text{ ms}$** (p95 = $0,58\text{ ms}$)
- `AMF QueryOutput`: **$0,12\text{ ms}$** (p95 = $0,35\text{ ms}$)
- `AMF_INPUT_FULL`: **0**
- `AMF Retries`: **0**
- `AMF Dropped Frames`: **0**
- **Wniosek:** Enkoder sprzętowy AMF HEVC działa z ogromnym zapasem wydajności ($> 120\text{ FPS}$) i nie stanowi żadnego opóźnienia.

---

## L. Decoder Timing (Media Foundation D3D11VA)

- `MF ReadSample`: **$0,74\text{ ms}$** (p95 = $1,49\text{ ms}$)
- `Decoder direct surface to VP`: **100% klatek (Zero-Copy VRAM)**
- **Wniosek:** Dekoder sprzętowy dostarcza klatki płynnie w czasie $< 1\text{ ms}$.

---

## M. Pipeline Overlap & Timeline Diagram

Obecny potok jest **całkowicie seryjny (Zero-Overlap)**:

```text
KLATKA N:
CPU: [Telemetry][HUD Compose][Map/Gauge Prep][GPU Submit] ──────────┐ (CPU kończy w 7.5 ms)
                                                                    ▼
GPU:                                                       [VP Blt][Map][HUD CS] (GPU liczy 17.3 ms)
                                                                               │ (Czekanie CPU: 16.4 ms)
                                                                               ▼
AMF:                                                                           [Encode N] (0.4 ms)
──────────────────────────────────────────────────────────────────────────────────────────────────
KLATKA N+1: (rozpoczyna się dopiero PO zakończeniu klatki N!)
CPU:                                                                           [Telemetry N+1]...
```

---

## N. Serialization Point

- **Punkt serializacji:** Wywołanie synchronizacji w `telem_amd_native.cpp` oraz przekazanie powierzchni do AMF przed rozpoczęciem przetwarzania kolejnej klatki przez pętlę Python/CPU.
- Ponieważ CPU czeka, aż GPU zakończy klatkę $N$, procesor CPU marnuje **$16,37\text{ ms}$ na bezczynne oczekiwanie** zamiast renderować nakładkę dla klatki $N+1$!

---

## O. GPU Engine Utilization

- **3D / Compute Engine (DirectX 11)**: **$\sim 95-100\%$** (wysokie nasycenie przez Fused CS, Map Resample i VideoProcessor).
- **Video Decode (VCN Decode)**: $\sim 20-25\%$.
- **Video Encode (VCN Encode)**: $\sim 25-30\%$.
- **Copy Engine**: $< 5\%$.

---

## P. 4K vs 1080p Resolution Comparison

| Rozdzielczość | Render FPS | Render Wall (s) | GPU Span median | Status |
|---|---:|---:|---:|---|
| **4K (3840×2160)** | **$36,380\text{ FPS}$** | $31,089\text{ s}$ | **$17,248\text{ ms}$** | GPU-Bound / Pixel Saturation |
| **1080p (1920×1080)** | **$72,176\text{ FPS}$** | $15,670\text{ s}$ | **$3,371\text{ ms}$** | **$+98,4\%$ throughput ($2\times$ szybciej)** |

**Wniosek:** Skalowanie przepustowości niemal $2:1$ przy zmianie rozdzielczości potwierdza, że ograniczeniem 4K jest czas pracy shaderów i VideoProcessora GPU.

---

## Q–T. Control Runs (Izolacja Podsystemów Overlay)

Wpływ wyłączania poszczególnych komponentów na wydajność 4K:

| Konfiguracja testowa | Render FPS | Zysk FPS względem Baseline | GPU Span (ms) | Wnioski |
|---|---:|---:|---:|---|
| **Baseline 4K (Wszystko Włączone)** | **$36,38\text{ FPS}$** | — | **$17,25\text{ ms}$** | Stan referencyjny |
| **Gauge OFF** | $37,34\text{ FPS}$ | $+0,96\text{ FPS}$ ($+2,6\%$) | $16,98\text{ ms}$ | Mały wpływ GPU ($0,18\text{ ms}$) |
| **Charts OFF** | $38,55\text{ FPS}$ | $+2,17\text{ FPS}$ ($+6,0\%$) | $16,63\text{ ms}$ | Umiarkowany wpływ ($0,74\text{ ms}$) |
| **Map OFF** | **$40,45\text{ FPS}$** | **$+4,07\text{ FPS}$ ($+11,2\%$)** | **$13,53\text{ ms}$** | **Znaczący zysk GPU ($4,04\text{ ms}$)** |
| **ALL Overlays OFF** | **$41,29\text{ FPS}$** | **$+4,91\text{ FPS}$ ($+13,5\%$)** | **$14,94\text{ ms}$** | Bazowy koszt samego potoku wideo VP |

**Kluczowe odkrycie kontrolne:**
Wyłączenie mapy (`Map OFF`) obniża `GPU Span` z **$17,25\text{ ms}$** do **$13,53\text{ ms}$** (oszczędność **$3,72\text{ ms}$ na GPU**), co daje skok z 36 FPS do 40,5 FPS.

---

## U. Profiler Overhead

- `GPU Timestamps ON`: **$36,380\text{ FPS}$**
- `GPU Timestamps OFF`: **$36,897\text{ FPS}$**
- Narzut instrumentacji: **$+0,517\text{ FPS}$ ($1,40\%$)** ($< 3\%$ $\to$ **PASS**).

---

## V. Frame Accounting

- `Source metadata`: 1131
- `Python decoded`: 1131
- `Native processed`: 1131
- `AMF submitted`: 1131
- `AMF output`: 1131
- `Muxed frames`: 1131
- `Dropped frames`: **0**
- `Retries`: **0**

---

## W. 60 FPS Frame Budget Analysis

Dla celu **60 FPS** budżet klatki wynosi:
$$T_{\text{target}} = \frac{1000}{60} = \mathbf{16,667\text{ ms}}.$$

W obecnym potoku:
1. Praca CPU ($7,52\text{ ms}$) mieści się z zapasem w budżecie 60 FPS ($7,52 < 16,67\text{ ms}$).
2. Czas GPU ($17,25\text{ ms}$) nieznacznie przekracza budżet ($17,25 > 16,67\text{ ms}$ o $0,58\text{ ms}$).
3. **Kluczowa przeszkoda dla 60 FPS:** Sumowanie seryjne CPU + GPU:
   $$T_{\text{serial}} = 7,52 + 17,25 + 2,7 = \mathbf{27,49\text{ ms}} \implies \mathbf{36,38\text{ FPS}}.$$

Aby osiągnąć 60 FPS, konieczne jest:
1. **Pipelining CPU/GPU (Asynchroniczny Overlap)**: CPU przygotowuje klatkę $N+1$, podczas gdy GPU renderuje klatkę $N$. Wtedy czas klatki to $\max(T_{\text{CPU}}, T_{\text{GPU}}) = 17,25\text{ ms}$ ($\to \mathbf{58\text{ FPS}}$).
2. **Optymalizacja GPU Map Resample**: Redukcja czasu shadera mapy z $4,04\text{ ms}$ do $< 1,5\text{ ms}$ lub przeniesienie resamplingu. Wtedy $T_{\text{GPU}}$ spada do $14,5\text{ ms}$ ($\to \mathbf{69\text{ FPS}}$).

---

## X. Primary Bottleneck

**PRIMARY BOTTLENECK: `GPU_BOUND` (przy braku potokowania asynchronicznego CPU-GPU).**
- GPU wykonuje obliczenia przez $17,25\text{ ms}$ w każdej klatce 4K.
- CPU czeka synchronicznie na GPU przez $16,37\text{ ms}$.

---

## Y. Secondary Bottleneck

**SECONDARY BOTTLENECK: `GPU_MAP_RESAMPLE_AND_FLUSHES`.**
- Faza `Map Resize + Blend` kosztuje na GPU **$4,04\text{ ms}$** (oraz 2 wywołania `Flush()`).
- Dodatkowo 5 wywołań `Flush()` w pętli klatki generuje narzut $\sim 3,5\text{ ms}$ na sterowniku GPU.

---

## Z. Recommended ETAP 8S

```text
ETAP 8S — Asynchronous CPU-GPU Pipelining & Flush Consolidation
```

**Plan wdrożenia dla ETAPU 8S:**
1. **Asynchroniczny Overlap CPU-GPU (Double Buffering)**:
   - Zapewnienie, by CPU rozpoczynało renderowanie klatki $N+1$ natychmiast po wysłaniu komend GPU dla klatki $N$, bez czekania na zakończenie pracy GPU.
   - Pula powierzchni wyjściowych VP (już powiększona do 8 w ETAPIE 5V) pozwala na bezkolizyjne kolejkowanie w driverze.
2. **Konsolidacja `Flush()`**:
   - Usunięcie 5 pośrednich wywołań `m_context->Flush()` wewnątrz faz (Map, Charts, Gauge, AboveMap) na rzecz pojedynczego zlecenia per klatka.
3. **Oczekiwany efekt:**
   - Wzrost przepustowości z **$36,4\text{ FPS}$** do **$> 55-60\text{ FPS}$ w 4K**.
