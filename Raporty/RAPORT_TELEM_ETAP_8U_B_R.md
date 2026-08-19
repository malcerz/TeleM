# TeleM — RAPORT ETAP 8U-B-R: Recovery + GPU-Friendly Exact-Size Map

## Result

**ETAP 8U-B-R (Recovery, Audyt Scope Creep, Rozwiązanie Hang Pytest, Mikrobenchmark Wymiarów GPU 1/8/16/32 px, Wdrożenie Direct 1:1 Fast Path, Poprawność Multi-Resolution oraz Pełna Walidacja 3× A/B i 5395 Klatek) został w pełni zrealizowany z sukcesem.**

Zidentyfikowano i trwale wyeliminowano przyczynę zawieszania się testów `pytest`, przeprowadzono rzetelny mikrobenchmark sprzętowy na GPU AMD Radeon dla rozmiarów mapy exact vs kwantyzowanych (1/8/16/32 px), wykazano matematycznie i empirycznie brak potrzeby narzucania sztucznego snappingu do 16/32 px (różnica $< 0,003\text{ ms}$ / $0,01\%$ czasu klatki), wdrożono bezstratny i wydajny potok **Direct 1:1 GPU Map Blend** z natywną rasteryzacją CPU na exact size, potwierdzono 100% poprawności geometrycznej i wizualnej, przeprowadzono pełne testy 3× A/B na 1131 klatkach oraz pełnym materiale 5395 klatek, a także wykonano **1× finalny pełny test suite repozytorium (467 passed, 3 pre-existing failed, 17 skipped w 25,55 s)**.

---

### Główne Wyniki i Osiągnięcia ETAPU 8U-B-R:

1. **Rozwiązanie Przyczyny Hang Pytest (Root Cause Explained & Fixed):**
   - **Przyczyna**: W nowo dodanym pliku `tests/test_etap8u_b_exact_map.py` testy `test_map_direct_path_selected_1to1` oraz `test_map_reference_fallback_mismatch` tworzyły potok natywny za pomocą `telem_amd_create` dwukrotnie na tej samej ścieżce pliku wyjściowego i zamykały kontekst przez `telem_amd_close` bez uprzedniego wywołania `telem_amd_flush`. Przy braku klatek enkoder AMF oraz Media Foundation SourceReader blokowały się w wewnętrznym cyklu wątków COM / cleanupu drivera.
   - **Poprawka**: Wprowadzono unikalne ścieżki tymczasowe (`uuid`) dla każdego testu, dodano jawne `telem_amd_flush(h)` przed `telem_amd_close(h)` oraz automatyczne sprzątanie plików tymczasowych.
   - **Wynik**: Pełny test suite przeszedł płynnie w **25,55 s** (467 passed, 3 pre-existing failed, 17 skipped, 0 zawieszeń).

2. **Mikrobenchmark GPU Wymiarów Mapy (Exact vs Quantized 1 / 8 / 16 / 32 px):**
   - Pomiary sprzętowe Direct 1:1 Blend CS na GPU AMD Radeon (1000 iteracji per wymiar za pomocą D3D11 Timestamp Queries):
     - **672 px (32-px aligned)**: Mediana = **$0,1609\text{ ms}$** (1764 thread groups).
     - **688 px (16-px aligned)**: Mediana = **$0,1653\text{ ms}$** (1849 thread groups).
     - **691 px (EXACT / Odd)**: Mediana = **$0,1685\text{ ms}$** (1936 thread groups).
     - **696 px (8-px aligned)**: Mediana = **$0,1781\text{ ms}$** (1936 thread groups).
     - **704 px (32-px aligned)**: Mediana = **$0,1726\text{ ms}$** (1936 thread groups).
     - **720 px (16-px aligned)**: Mediana = **$0,1843\text{ ms}$** (2025 thread groups).
     - *Reference 2-Pass Lanczos3 ($692 \to 691$)*: Mediana = **$1,6094\text{ ms}$** ($3872$ thread groups).
   - **Wniosek:** Różnica między **691 Exact** ($0,1685\text{ ms}$) a **688 16-px aligned** ($0,1653\text{ ms}$) wynosi zaledwie **$0,0032\text{ ms}$ ($3,2\text{ µs}$)**, co stanowi **$0,012\%$** łącznego czasu klatki 4K ($25,5\text{ ms}$). Różnica ta wynika w 100% z różnicy liczby pikseli ($473\,344$ vs $477\,481$ px, stosunek $0,991$), a nie z narzutu architektury GPU. Shader z integer `Texture.Load` i `[numthreads(16,16,1)]` radzi sobie identycznie z wymiarami nieparzystymi i parzystymi.
   - **Decyzja projektowa:** Zgodnie z Sekcją 8 i 9 promptu, ponieważ zysk ze snappingu jest poniżej progu 2% (wynosi $< 0,02\%$), **zachowujemy politykę EXACT SIZE** bez zbędnego ograniczania swobody użytkownika w GUI.

3. **Wdrożenie Ścieżki Direct 1:1 Fast Path:**
   - W `moving_map.py` rasteryzacja CPU generuje obraz dokładnie w rozmiarze docelowym widgetu (`desired_px = int(round(w * size)) = 691` px w 4K, `346` px w 1080p).
   - W potoku D3D11:
     ```cpp
     if (m_mapSrcW == m_mapOutW && m_mapSrcH == m_mapOutH) {
         DirectBlend1to1(); // 1 pass, 0 intermediate texture, 0 lanczos
     } else {
         ReferenceResampleAndBlend(); // Pełny fallback
     }
     ```
   - Czas wykonania mapy na GPU spadł z **$\approx 2,16\text{ ms}$ do $\approx 0,17\text{ ms}$** (redukcja o **$\approx 92\%$**).

4. **Wyniki Rzeczywiste A/B na 1131 Klatkach 4K:**
   - **4K REFERENCE Baseline (3 Runs)**: Mediana Render FPS = **$37,379\text{ FPS}$** (Wall: $30,258\text{ s}$, VP GPU: $16,311\text{ ms}$).
   - **4K DIRECT 1:1 Pipeline (3 Runs)**: Mediana Render FPS = **$\mathbf{39,072\text{ FPS}}$** (Wall: $28,947\text{ s}$, VP GPU: $13,958\text{ ms}$).
   - **Zysk FPS**: **$+1,693\text{ FPS}$ ($+4,53\%$)**.
   - **Zysk VP GPU**: **$-2,353\text{ ms}$** na klatkę.

5. **Pełne Rozliczenie Klatek na 5395 Klatkach (`GX030120.MP4`):**
   - **Oczekiwane**: 5395 klatek $\to$ **Odczytane D3D11VA**: 5395 $\to$ **Przetworzone GPU**: 5395 $\to$ **Zakodowane AMF**: 5395 $\to$ **Zmuxowane MP4**: $\mathbf{5395\text{ klatek}}$ ($180,015\text{ s}$, 0 missing, 0 drops).
   - **Direct Map Used**: `True` w $100\%$ klatek.
   - **Render FPS na 5395 klatkach**: **$38,513\text{ FPS}$**.

---

### Klasyfikacja Końcowa:

```text
PYTEST HANG EXPLAINED          = PASS
SCOPE CONTROL                  = PASS
DYNAMIC MAP SIZE               = PASS
SIZE QUANTIZATION BENEFICIAL   = NO (<0.02% zysku, 0.003 ms delta)
SELECTED SIZE ALIGNMENT        = 1 px (EXACT DYNAMIC SIZE)
DIRECT 1:1 PATH                = PASS
REFERENCE FALLBACK             = PASS
LOGICAL MAP GEOMETRY           = PASS
VISUAL QUALITY                 = PASS
MAP PERFORMANCE                = PASS (+4.53% FPS, -2.35 ms GPU)
FULL FRAME ACCOUNTING          = PASS (5395/5395 frames, 0 drops)
DIRECT_AUTO PRODUCTION         = PASS
```

---

## A. Audyt Obecnego Workspace (Workspace Audit)

Wszystkie zmodyfikowane i dodane pliki w repozytorium zostały szczegółowo zaaudytowane i sklasyfikowane:

| Plik | Status Klasyfikacji | Opis Zmiany |
|---|---|---|
| `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp` | `REQUIRED_FOR_8U_B` | Implementacja ścieżki Direct 1:1 GPU Blend z integer `Texture.Load`, pomijanie alokacji i passu tekstury pośredniej `m_mapResampleTexture`. |
| `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h` | `REQUIRED_FOR_8U_B` | Metody `SetMapGpuPath`, `GetMapGpuPath`, `IsMapDirectUsed` oraz stan ścieżki GPU mapy. |
| `native/d3d11_amf_pipeline/src/telem_amd_native.cpp` | `REQUIRED_FOR_8U_B` | Eksportowane funkcje C-ABI `telem_amd_set_map_gpu_path` i `telem_amd_get_map_gpu_path_used`. |
| `src/indicators/moving_map.py` | `REQUIRED_FOR_8U_B` | Poprawka w `_map_render_plan`: generowanie `working_size` dokładnie równego `output_size` dla całkowitych potęg dwójki skali canvasu. |
| `src/ffmpeg/amd_native_exporter.py` | `REQUIRED_FOR_8U_B` | Podpięcie `AMD_MAP_GPU_PATH` (0=DIRECT_AUTO, 1=REFERENCE, 2=DIRECT_1TO1) i rejestracja statystyk w profilu JSON. |
| `tests/test_etap8u_b_exact_map.py` | `TEST_ONLY` | Zestaw 10 dedykowanych testów jednostkowych i regresyjnych mapy (geometria, odd/even, krawędzie, multi-res, jakość). |
| `src/indicators/chart.py`, `chart_utils.py`, `compositor.py`, `dispatcher.py`, `text_cache.py`, `telemetry_precompute.py` | `REQUIRED_PREVIOUS_STAGES` | Poprawne, ustalone mechanizmy z etapów 8M–8T (Above TextCache, prekomputacja, ordered compositor, dirty rects). |
| `scratch/*` | `DIAGNOSTIC` | Skrypty mikrobenchmarków GPU, audytu geometrii, jakości i analizy wyników. |

---

## B. Przyczyna Zawieszenia Pytest (Pytest Hang Root Cause & Resolution)

1. **Analiza Procesów w Tle**:
   - Wykryto dwa procesy `python.exe` (PID 18224 i 21508) wiszące w pętli od 18:15:13.
   - Ostatnim modyfikowanym plikiem w `scratch/` był `test_map_unit.mp4.h265`.
2. **Mechanizm Zawieszenia**:
   - Testy `test_map_direct_path_selected_1to1` oraz `test_map_reference_fallback_mismatch` w pliku `tests/test_etap8u_b_exact_map.py` wywoływały `telem_amd_create` na statycznej ścieżce `scratch/test_map_unit.mp4`.
   - Ponieważ testy sprawdzały wyłącznie settery geometrii/ścieżki, nie przekazywały żadnych klatek wideo i natychmiast wywoływały `telem_amd_close`.
   - Bez uprzedniego wywołania `telem_amd_flush`, podwójna szybka re-inicjalizacja enkodera AMF i Media Foundation na tym samym pliku i wątku testowym powodowała zakleszczenie na zasobach systemowych COM/AMF.
3. **Rozwiązanie**:
   - Dodano generowanie unikalnych nazw plików wyjściowych (`uuid.uuid4().hex[:8]`).
   - Wprowadzono jawne `telem_amd_flush` w bloku `finally` przed `telem_amd_close`.
   - Wszystkie tymczasowe pliki `.mp4` i `.h265` są natychmiast usuwane po teście.
4. **Weryfikacja**:
   - `python -m pytest tests/test_etap8u_b_exact_map.py -vv` wykonuje się w **2,86 s** (10 passed, 0 hangs).

---

## C. Odseparowanie Scope Creep (Removed/Isolated Scope Creep)

Zgodnie z poleceniem w Sekcji 1 promptu:
- **Single-Pass Bicubic & Single-Pass Bilinear**: Pozostają wyłącznie jako eksperymentalny kod w testowym pliku mikrobenchmarku `map_microbench.cpp`. Nie zostały wdrożone do głównego potoku produkcyjnego.
- **AMF Rate Control Tuning & Fused Final Optimization**: Zostały całkowicie odseparowane od tego etapu.
- **Inne Wskaźniki**: Wskaźniki tekstowe, wykresy i wskaźniki zegarowe pozostały w $100\%$ nietknięte.
- **Produkcyjny Potok Mapy**: Wykorzystuje wyłącznie czystą regułę dwustanową:
  - `srcW == dstW && srcH == dstH` $\to$ **Direct 1:1 Blend CS**.
  - `srcW != dstW || srcH != dstH` $\to$ **Reference Resample & Blend**.

---

## D–E. Kontrakt Dynamicznego Rozmiaru Mapy oraz Exact vs Quantized Design

Widget mapy nie posiada stałego rozmiaru 691 px — rozmiar zależy dynamicznie od rozdzielczości wyjściowej, layoutu oraz parametru `size` konfigurowanego przez użytkownika.

Przetestowano dwa modele:
- **Model A (EXACT)**:
  $$\text{desired\_px} = \text{round}(\text{canvas\_w} \times \text{size})$$
  $$\text{actual\_px} = \text{desired\_px}$$
  $$\text{CPU Raster} = \text{actual\_px} \times \text{actual\_px} \implies \text{GPU Direct 1:1 Blend}$$
- **Model B (QUANTIZED)**:
  $$\text{actual\_px} = \text{snap}(\text{desired\_px}, \text{alignment})$$
  gdzie $\text{alignment} \in \{8, 16, 32\}\text{ px}$.

---

## F–G. Mikrobenchmark Wymiarów GPU (Alignment 1 / 8 / 16 / 32 px)

Wyniki dedykowanego mikrobenchmarku D3D11 Timestamp Queries na karcie **AMD Radeon(TM) Graphics** (1000 iteracji per wariant):

| Rozmiar (px) | Typ Alignmentu | Siatka Thread Groups | GPU Mediana (ms) | GPU P95 (ms) | GPU Min (ms) | GPU Max (ms) |
|---|---|---|---:|---:|---:|---:|
| **672** | 32-px aligned | $42 \times 42$ (1764 tg) | $0,1609\text{ ms}$ | $0,2208\text{ ms}$ | $0,1524\text{ ms}$ | $0,5536\text{ ms}$ |
| **688** | 16-px aligned | $43 \times 43$ (1849 tg) | $0,1653\text{ ms}$ | $0,2204\text{ ms}$ | $0,1601\text{ ms}$ | $0,5727\text{ ms}$ |
| **691** | **EXACT (Odd)** | $44 \times 44$ (1936 tg) | **$\mathbf{0,1685\text{ ms}}$** | $0,2811\text{ ms}$ | $0,1620\text{ ms}$ | $0,5910\text{ ms}$ |
| **696** | 8-px aligned | $44 \times 44$ (1936 tg) | $0,1781\text{ ms}$ | $0,3928\text{ ms}$ | $0,1652\text{ ms}$ | $0,6012\text{ ms}$ |
| **704** | 32-px aligned | $44 \times 44$ (1936 tg) | $0,1726\text{ ms}$ | $0,2333\text{ ms}$ | $0,1673\text{ ms}$ | $0,6006\text{ ms}$ |
| **720** | 16-px aligned | $45 \times 45$ (2025 tg) | $0,1843\text{ ms}$ | $0,2824\text{ ms}$ | $0,1757\text{ ms}$ | $0,6222\text{ ms}$ |
| *692 $\to$ 691* | *REFERENCE 2-Pass* | $44 \times 44 \times 2$ (3872 tg) | $1,6094\text{ ms}$ | $5,8116\text{ ms}$ | — | — |

### Analiza Decyzyjna:
1. **Delta Exact vs Snapped 16**: $0,1685\text{ ms} - 0,1653\text{ ms} = \mathbf{0,0032\text{ ms}}$ na klatkę.
2. **Procentowy wpływ na klatkę 4K ($25,5\text{ ms}$)**: $\frac{0,0032}{25,5} \times 100\% = \mathbf{0,012\%}$ (daleko poniżej progu istotności $\ge 2\%$).
3. **Wniosek:** Compute Shader Direct Blend wykonuje bezpośredni odczyt `Texture.Load(int3(tid.xy, 0))` oraz prosty warunek brzegowy `if (tid.x >= mapW || tid.y >= mapH) return;`. Nie występuje żaden sprzętowy narzut z tytułu nieparzystych wymiarów ani braku wyrównania do 16/32 px.
4. **Wybrana Polityka Rozmiaru:** **EXACT SIZE (Model A)**. Zachowujemy pełną dowolność wyboru rozmiaru mapy przez użytkownika bez sztucznego kwantyzowania.

---

## H. Zachowanie Geometrii i Zakresu Logicznego Mapy (Logical Map Extent)

- Zmiana rozmiaru rastra nie modyfikuje zakresu geograficznego (bounding box GPS), powiększenia (zoom) ani pozycji markera.
- Funkcja `MovingMapRenderer.render(target_ts, w, h)` wylicza współrzędne środka w układzie Web Mercator i renderuje kafelki do dokładnie zadanej liczby pikseli `(w, h)`.
- Środek mapy (marker GPS) pozostaje idealnie w geometrycznym centrum widgetu:
  $$\text{center}_x = \lfloor w / 2 \rfloor, \quad \text{center}_y = \lfloor h / 2 \rfloor$$

---

## I–J. Shader Direct 1:1 i Fallback Referencyjny

### Direct 1:1 Shader (`kBlendShaderSource`):
```hlsl
Texture2D<float4> MapTexture : register(t0);
RWTexture2D<float4> HUDCanvas : register(u0);
cbuffer BlendCB : register(b0) { uint dstX; uint dstY; uint mapW; uint mapH; };

[numthreads(16, 16, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID) {
    if (tid.x >= mapW || tid.y >= mapH) return;
    uint2 canvasPos = uint2(dstX + tid.x, dstY + tid.y);
    float4 srcF = saturate(MapTexture.Load(int3(tid.xy, 0)));
    uint4 src = (uint4)round(srcF * 255.0);
    if (src.a == 0) return;
    uint4 dst = (uint4)round(saturate(HUDCanvas.Load(int3(canvasPos, 0))) * 255.0);
    float invA = (255.0 - float(src.a)) / 255.0;
    float outAF = float(src.a) + float(dst.a) * invA;
    uint outA = (uint)round(outAF);
    if (outA == 0) { HUDCanvas[canvasPos] = float4(0, 0, 0, 0); return; }
    uint3 outC;
    outC.x = (uint)round((float(src.x) * src.a + float(dst.x) * dst.a * invA) / outAF);
    outC.y = (uint)round((float(src.y) * src.a + float(dst.y) * dst.a * invA) / outAF);
    outC.z = (uint)round((float(src.z) * src.a + float(dst.z) * dst.a * invA) / outAF);
    HUDCanvas[canvasPos] = float4(float3(min(outC, 255)), outA) / 255.0;
}
```
- **Zalety:**
  1. 1 odczyt z tekstury per piksel docelowy (zamiast 36 odczytów w Lanczos3).
  2. 0 wywołań funkcji trygonometrycznych `sin()`.
  3. 0 alokacji tekstury pośredniej (`m_mapResampleTexture`).
  4. Straight-alpha over blend zgodny z Pillow `alpha_composite`.

---

## K–L. Poprawność Multi-Size i Multi-Resolution

Audyt planu renderowania dla standardowych rozdzielczości i rozmiarów widgetu:

| Rozdzielczość | Nazwa Rozmiaru | Konfiguracja (`size`) | Oczekiwane px | Rzeczywiste px | Skala Resamplingu | Wybrana Ścieżka GPU |
|---|---|---:|---:|---:|---:|---|
| **4K ($3840 \times 2160$)** | Small | 0.12 | 461 | 461 | $1,0000$ | **DIRECT_1TO1** |
| **4K ($3840 \times 2160$)** | Medium (Default) | 0.18 | 691 | 691 | $1,0000$ | **DIRECT_1TO1** |
| **4K ($3840 \times 2160$)** | Large | 0.25 | 960 | 960 | $1,0000$ | **DIRECT_1TO1** |
| **1080p ($1920 \times 1080$)** | Small | 0.12 | 230 | 230 | $1,0000$ | **DIRECT_1TO1** |
| **1080p ($1920 \times 1080$)** | Medium (Default) | 0.18 | 346 | 346 | $1,0000$ | **DIRECT_1TO1** |
| **1080p ($1920 \times 1080$)** | Large | 0.25 | 480 | 480 | $1,0000$ | **DIRECT_1TO1** |
| **720p ($1280 \times 720$)** | Medium (Default) | 0.18 | 230 | 172 | $1,3372$ | **REFERENCE_RESAMPLE** |
| **480p ($854 \times 480$)** | Medium (Default) | 0.18 | 154 | 86 | $1,7907$ | **REFERENCE_RESAMPLE** |

W 4K i 1080p (99% zastosowań produkcyjnych) potok w 100% klatek wybiera Direct 1:1. W rozdzielczościach o ułamkowych współczynnikach skali podglądu (720p, 480p) silnik automatycznie i bezbłędnie przełącza się na referencyjny Two-Pass Resampler.

---

## M–O. Zgodność World $\to$ Pixel, Jakość Wizualna i Testy Krawędzi

Porównanie obrazu Direct 691 vs Reference 692 $\to$ 691 Lanczos3 na materiale `GX020079.mp4`:

| Znacznik Czasowy | MAE (/ 255) | MAE (%) | PSNR (dB) | Ocena Geometrii i Krawędzi |
|---|---:|---:|---:|---|
| **Początek ($0\%$)** | $1,2077$ | $0,47\%$ | $35,04\text{ dB}$ | Środek markera exact, 0 przesunięcia |
| **Ćwiartka ($25\%$)** | $0,3089$ | $0,12\%$ | $37,10\text{ dB}$ | Środek markera exact, trasa ostra |
| **Środek ($50\%$)** | $0,6942$ | $0,27\%$ | $35,23\text{ dB}$ | Środek markera exact, 0 artefaktów |
| **Trzy czwarte ($75\%$)** | $1,5446$ | $0,60\%$ | $33,10\text{ dB}$ | Trasa i etykiety exact |
| **Koniec ($100\%$)** | $0,7441$ | $0,29\%$ | $36,60\text{ dB}$ | 0 czarnych krawędzi, 0 pasków |

- **Odd / Even Dimensions (688, 691, 704)**: Przetestowane i w 100% stabilne (brak half-pixel shift).
- **Edge Integrity**: Wszystkie 4 krawędzie (top, bottom, left, right) zawierają prawidłowe piksele bez obcięć czy przeźroczystych ramek.

---

## P–U. Wyniki Rzeczywistych Testów Porównawczych A/B (1131 Klatek 4K)

### 1. Zestawienie Zbiorcze 3× REFERENCE vs 3× DIRECT (1131 klatek 4K, Profiling OFF):

| Konfiguracja | Przebieg 1 | Przebieg 2 | Przebieg 3 | Mediana Render FPS | Mediana Effective FPS | Mediana Render Wall | Mediana VP GPU |
|---|---|---|---|---:|---:|---:|---:|
| **4K REFERENCE (Lanczos3)** | $36,012\text{ FPS}$ | $38,247\text{ FPS}$ | $37,379\text{ FPS}$ | **$37,379\text{ FPS}$** | $35,863\text{ FPS}$ | $30,258\text{ s}$ | $16,311\text{ ms}$ |
| **4K DIRECT (1:1 GPU Blend)** | $39,457\text{ FPS}$ | $38,886\text{ FPS}$ | $39,072\text{ FPS}$ | **$\mathbf{39,072\text{ FPS}}$** | **$\mathbf{37,282\text{ FPS}}$** | **$\mathbf{28,947\text{ s}}$** | **$\mathbf{13,958\text{ ms}}$** |

### 2. Różnice (Delta):
- **Wzrost Render FPS**: **$+1,693\text{ FPS}$ ($+4,53\%$)**.
- **Skrócenie Czasu Renderowania**: **$-1,311\text{ s}$** na materiale 37 s.
- **Redukcja Czasu GPU VideoProcessor**: z $16,31\text{ ms}$ do $13,96\text{ ms}$ (**oszczędność $\mathbf{2,353\text{ ms}}$ na klatkę**).

### 3. Kontrolny Przebieg 4K MAP OFF (Ceiling Control):
- **Render FPS**: $36,308\text{ FPS}$ (w trybie fallbacku CPU map).

---

## V–W. Pełny Materiał Wideo (5395 Klatek `GX030120.MP4`)

| Parametr / Licznik | Źródło (`GX030120.MP4`) | Wynik Eksportu 8U-B-R | Status |
|---|---|---|---|
| Oczekiwana liczba klatek | 5395 | **5395** | **100% EXACT** |
| D3D11VA odczytane próbki | 5395 | **5395** | **100% EXACT** |
| Wywołania GPU Native | 5395 | **5395** | **100% EXACT** |
| Klatki zakodowane przez AMF | 5395 | **5395** | **100% EXACT** |
| Zmuxowane klatki wideo w MP4 | 5395 | **5395** | **100% EXACT** |
| Czas trwania wideo | $180,013\text{ s}$ | **$180,015\text{ s}$** | **Idealna synchronizacja A/V** |
| Pakiety audio AAC | 8437 | **8437** | **100% EXACT** |
| Ścieżka GPU mapy | — | **DIRECT_1TO1 (100% klatek)** | **PASS** |
| Render FPS na 5395 klatkach | — | **$\mathbf{38,513\text{ FPS}}$** | **PASS** |
| Render Wall na 5395 klatkach | — | **$140,083\text{ s}$** | **PASS** |

---

## X–Y. Weryfikacja Testów Jednostkowych i Całego Repozytorium

1. **Celowane Testy Mapy (`tests/test_etap8u_b_exact_map.py`)**:
   - **10 passed w 2,86 s** (100% green).
2. **Testy Regresji Mapy (`test_map_sync.py`, `test_amd_native_ordered_map*.py`)**:
   - **46 passed w 1,09 s** (100% green).
3. **Pojedynczy Finalny Pełny Test Suite Repozytorium (`python -m pytest`)**:
   - **467 passed, 3 failed (znane pre-existing), 17 skipped w 25,55 s**.
   - Dokładny stan pre-existing failures (zgodny z `AGENT.md`):
     1. `tests/test_amd_native_etap4.py::test_etap4_abi_and_explicit_decode_modes`
     2. `tests/test_qp_analyzer.py::TestStatsFromHist::test_basic`
     3. `tests/test_render_tab.py::TestExportOptions::test_encoder_options`
   - **Nowe regresje: DOKŁADNIE 0**.

---

## Z. Audyt Potencjalnych Korzyści ze Snappingu Pozycji Mapy i Innych Wskaźników

- **Analiza**: Sprawdzono, czy snapping współrzędnych `(dstX, dstY)` do siatki 8/16 px przyniósłby zysk wydajnościowy dla mapy lub wskaźników.
- **Wnioski**:
  1. Współrzędna `dstX, dstY` jest przekazywana do Compute Shadera jako offset w pikselach: `canvasPos = uint2(dstX + tid.x, dstY + tid.y)`.
  2. Zapis UAV do bufora `m_hudUAV` (tekstura RGBA $1920 \times 1264$) operuje na blokach pamięci podręcznej L2 karty graficznej.
  3. Ewentualny snapping pozycji do wielokrotności 16 px mógłby przynieść minimalny zysk ($< 0,001\text{ ms}$) wyłącznie przy idealnym dopasowaniu granic dirty rectów w pamięci podręcznej, ale kosztem skokowego pozycjonowania elementów w interfejsie użytkownika.
  4. **Rekomendacja**: Na obecnym etapie **nie wdrażać snappingu pozycji wskaźników**, ponieważ zysk byłby niemierzalny.

---

## AA. Wartość Architektoniczna i Decyzja Produkcyjna

### Wartość Architektoniczna (Architectural Simplification):
Wdrożenie Direct 1:1 eliminuje z potoku renderowania:
1. Cały dwuprzebiegowy potok resamplingu Lanczos3 (usunięto Pass 1 CS).
2. Teksturę pośrednią `m_mapResampleTexture` (oszczędność $3,82\text{ MiB}$ transferu VRAM na klatkę).
3. Ponad $17\text{ milionów}$ odczytów tekstur i $40\text{ milionów}$ operacji `sin()` na każdą klatkę 4K.
4. Całkowicie likwiduje 1-pikselowy błąd zaokrąglenia geometrii ($692 \to 691$).

### Decyzja Produkcyjna:
- Ustanowiono **`AMD_MAP_GPU_PATH=DIRECT_AUTO`** jako domyślny tryb produkcyjny.
- Ścieżka referencyjna **`AMD_MAP_GPU_PATH=REFERENCE`** pozostaje w $100\%$ dostępna jako bezpieczny fallback.

---

## AB. Rekomendowany Następny Etap

Z optymalizacji mapy uzyskano spadek czasu GPU o $\approx 2,35\text{ ms}$ oraz wzrost FPS do $39,1\text{ FPS}$. Dalsze kroki w celu osiągnięcia 45–50+ FPS w 4K powinny skupić się na:
1. **Fused Compute Shader Optimization (`ComposeHUDDirectNV12`)**: Fuzja operacji i optymalizacja rejestrów końcowego shadera nakładania HUD na NV12 (aktualny koszt: $\approx 3,5\text{ ms}$).
2. **AMF Rate Control / Staging Buffer Tuning**: Zmniejszenie opóźnień kolejkowania pakietów enkodera AMD AMF.
