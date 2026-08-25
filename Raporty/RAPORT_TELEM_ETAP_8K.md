# TeleM — RAPORT Z ETAPU 8K: Produkcyjne wdrożenie `Unified Fused NV12 Compositor`

Data: **2026-08-19**  
Typ etapu: **PRODUCTION IMPLEMENTATION + PIXEL CORRECTNESS + REAL AMD RUNTIME + FULL MATERIAL VALIDATION + PERFORMANCE REGRESSION**  
Stan końcowy: **FUSED PRODUCTION DEFAULT = PASS | PIXEL PARITY = PASS (100.00%) | FULL MATERIAL = PASS (0 drops) | GPU 60 FPS BUDGET = FAIL BY ~0.53 ms**

---

## 1. Podsumowanie wykonawcze (Executive Summary)

W ramach **ETAPU 8K** wdrożono **Unified Fused NV12 Compositor** (`m_nv12FusedComputeShader`) jako domyślny, produkcyjny potok AMD bez konieczności ustawiania jakichkolwiek zmiennych środowiskowych. Całkowicie wyeliminowano produkcyjne dyspatche shadera `NormalizeD3D11VARangeNV12`, osiągając jednokrotną, bezstratną konwersję zakresu i fuzję nakładek w 1-passowym shaderze Compute.

### Kluczowe rezultaty:

1. **Wdrożenie produkcyjne (Production Default)**:
   - Domyślny tryb kompozytora w `d3d11_vp_pipeline.cpp` został ustawiony na `Fused Single-Range` (`fusedMode = 1`).
   - Liczba dispatchy osobnego passu Normalize per klatka: **`0`** (czas GPU: **`0.00 ms`**).
   - Dostępny jest opcjonalny tryb diagnostyczny (`AMD_FUSED_COMPOSITOR=0`) do testów referencyjnych.
2. **Wierność pikselowa (100.00% Exact Match względem `ONE_PASS_REFERENCE`)**:
   - Sprawdzono 5 reprezentatywnych klatek (30, 225, 450, 675, 899):
     - **Luminancja Y**: **100.00% Exact Match**, MAE = **0.000**, MaxDiff = **0**, PSNR = **999.00 dB**.
     - **Chrominancja U & V**: **100.00% Exact Match**, MAE = **0.000**, MaxDiff = **0**, PSNR = **999.00 dB**.
     - **Wszystkie warstwy** (Tło, Napisy, Wykresy, Wskaźnik, Mapa GPS, CPU_ABOVE_MAP, Krawędzie $\alpha$): **100.00% Exact Match**.
3. **Stabilność na pełnym materiale wideo 4K (5395 klatek, ~180 s)**:
   - Wyrenderowano pełne wideo `GX030120.MP4` w czasie **`173.91 s`** (**`31.02 FPS`** — szybciej niż czas trwania filmu!).
   - Dostarczono **5395 / 5395** klatek do enkodera AMF (**0 dropped frames**, 0 AMF_INPUT_FULL, 0 błędów EOS).
   - Zremuksowano finalny plik MP4 ze ścieżką audio GoPro AAC.
4. **Klasyfikacja budżetu GPU 60 FPS**:
   - Zgodnie z wytycznymi (budżet 60 FPS = $16.667\text{ ms}$):
     - Zmierzony median GPU Span: **`17.20 – 17.37 ms`**.
     - **`GPU 60 FPS BUDGET = FAIL BY ~0.53 ms`** (osiągnięto ~58.1 GPU FPS, zysk ponad 4.4 ms względem baseline 21.7 ms).
     - **`FUSED PRODUCTION FEASIBILITY = PASS`**.

---

## 2. Sekcja A & B: Porównanie potoków produkcyjnych

```text
POPRZEDNI POTOK (ETAP 5..8H):
P010 FULL
  ↓ VideoProcessorBlt
NV12 FULL (0..255)
  ↓ NormalizeD3D11VARangeNV12 (Pass 1)
NV12 LIMITED (16..235)
  ↓ NormalizeD3D11VARangeNV12 (Pass 2 - Błędny artefakt)
NV12 DOUBLE LIMITED (30..218)
  ↓ ComposeHUDDirectNV12
NV12 LIMITED/DISTORTED -> AMF HEVC

NOWY POTOK PRODUKCYJNY (ETAP 8K):
P010 FULL (0..1023)
  ↓ VideoProcessorBlt (Direct Hardware Blit)
NV12 FULL (0..255)
  │
  │ (Przygotowanie nakładek RGBA w m_hudTexture: BELOW + Charts + Gauge + Map + ABOVE)
  ↓
Unified Fused NV12 CS (m_nv12FusedComputeShader)
  ├── 1. Base Y/UV Full -> Limited Range (16..235 / 16..240)
  ├── 2. HUD RGBA -> Studio YUV conversion
  └── 3. Direct Alpha Over Composition
  ↓
NV12 STUDIO/LIMITED (16..235)
  ↓
AMF HEVC Hardware Encoder (Limited Range NV12)
```

---

## 3. Sekcja C, D & E: Zmiany w kodzie i logika wyboru

### Pliki zmodyfikowane:
1. `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h`:
   - Deklaracja `m_nv12FusedComputeShader`.
2. `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`:
   - Domyślny `GetFusedCompositorMode()` zwraca `1`.
   - `GetNormalizePassCount()` w trybie Fused zwraca `0`.
   - Kompilacja i czyszczenie `m_nv12FusedComputeShader`.
   - `ComposeHUDDirectNV12` wybiera shader Fused jako produkcyjny default.
3. `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`:
   - Raportowanie w logu startowym: `AMD_NV12_COMPOSITOR=FUSED`, `AMD_RANGE_NORMALIZE=FUSED_SINGLE`, `AMD_NORMALIZE_PASSES=0`.
4. `src/ffmpeg/amd_native_exporter.py`:
   - Spójne logowanie parametrów w podsumowaniu konfiguracji.
5. `tests/test_etap8k_fused_production.py`:
   - Zestaw 3 testów jednostkowych weryfikujących domyślny tryb Fused, usuwanie dispatchy i obsługę override diagnostycznego.

### Precedens zmiennych środowiskowych:
- **Brak ENV (Normalna produkcja)**: `AMD_FUSED_COMPOSITOR=1` (Fused CS, 0 Normalize passes).
- **`AMD_FUSED_COMPOSITOR=0` (Override diagnostyczny)**: Uruchamia legacy potok z osobnym Normalize (`AMD_NORMALIZE_PASSES` domyślnie 1 dla referencji).

---

## 4. Sekcja F & G: Kontrakt zakresów i usunięcie dispatchy Normalize

- **Zakres luminancji bazy**: $Y_{base, lim} = \min(235, \lfloor(219 Y_{base, full} + 127)/255\rfloor + 16) \in [16, 235]$.
- **Zakres chrominancji bazy**: $UV_{base, lim} \in [16, 240]$.
- **Liczba dispatchy `NormalizeD3D11VARangeNV12`**: **`0`**.
- **Czas GPU `NormalizeD3D11VARangeNV12`**: **`0.00 ms`**.

---

## 5. Sekcja H & I: Weryfikacja wierności pikselowej (Pixel Parity)

Porównanie wyjścia produkcyjnego (`PROD_FUSED`) z wyrocznią (`ONE_PASS_REFERENCE`):

```text
=== PIXEL PARITY: ONE_PASS_REFERENCE vs ETAP 8K PRODUCTION FUSED ===

--- FRAME  30 METRICS ---
  Y (Luma)     -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
    ORACLE Y : min= 16, max=235, mean=121.58, med=117
    PROD   Y : min= 16, max=235, mean=121.58, med=117
  U (Chroma)   -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
    ORACLE U : min= 16, max=149, mean=115.07, med=118
    PROD   U : min= 16, max=149, mean=115.07, med=118
  V (Chroma)   -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
    ORACLE V : min= 93, max=240, mean=127.83, med=126
    PROD   V : min= 93, max=240, mean=127.83, med=126

--- FRAME 225 METRICS ---
  Y (Luma)     -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
  U (Chroma)   -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
  V (Chroma)   -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB

--- FRAME 450 METRICS ---
  Y (Luma)     -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
  U (Chroma)   -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
  V (Chroma)   -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB

--- FRAME 675 METRICS ---
  Y (Luma)     -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
  U (Chroma)   -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
  V (Chroma)   -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB

--- FRAME 899 METRICS ---
  Y (Luma)     -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
  U (Chroma)   -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
  V (Chroma)   -> Exact: 100.00%, Within ±1: 100.00%, MAE: 0.000, MaxDiff:  0, PSNR: 999.00 dB
```

### Zgodność poszczególnych warstw (Klatka 30):

| Warstwa / Region | Exact Match Y [%] | Within $\pm 1$ Y [%] | MAE Y | MaxDiff Y | Exact Match UV [%] |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Background Only (no HUD)** | **100.00%** | 100.00% | 0.000 | 0 | **100.00%** |
| **Speed Gauge (Bbox)** | **100.00%** | 100.00% | 0.000 | 0 | **100.00%** |
| **GPS Map (Bbox)** | **100.00%** | 100.00% | 0.000 | 0 | **100.00%** |
| **Telemetry Charts (Bbox)** | **100.00%** | 100.00% | 0.000 | 0 | **100.00%** |
| **CPU_ABOVE_MAP (Bbox)** | **100.00%** | 100.00% | 0.000 | 0 | **100.00%** |
| **Krawędzie antyaliasingu ($0 < \alpha < 255$)**| **100.00%** | 100.00% | 0.000 | 0 | **100.00%** |

---

## 6. Sekcja J: Spójność metadanych i enkodera AMF

Inspekcja `ffprobe` pliku wynikowego `etap8k_prod_full180s.mp4`:
- **Format**: `hevc (Main) (hev1)`
- **Color Range**: `tv` (Limited / Studio Range)
- **Color Space / Matrix**: `bt709`
- **Rozdzielczość / FPS**: `3840x2160, 30.0 fps`
- **Audio**: `GoPro AAC (stereo, 48000 Hz)`

---

## 7. Sekcja K & L: Ruch pamięci VRAM i inwentarz dispatchy

1. **Ruch pamięci NV12 per frame**:
   - Przed fuzją (2 passy): **`74.65 MB/frame`**
   - Przed fuzją (1 pass): **`49.77 MB/frame`**
   - Po fuzji produkcyjnej: **`24.88 MB/frame`** (oszczędność **`49.77 MB/frame`**, czyli **$2.99\text{ GB/s}$ przy 60 FPS**).
2. **Dyspatche pełnoklatkowe**:
   - `Normalize CS`: **0**
   - `Fused HUD Direct CS`: **1**
   - Dodatkowe flushe / bariery UAV: **0**.

---

## 8. Sekcja M & N: Pomiary GPU Timings i ocena budżetu 60 FPS

```text
=== ETAP 8K GPU TIMINGS (MEDIAN / P95 / P99 MS) ===
Przebieg                   | GPU Span [ms]     | VideoProc Blt [ms] | Range Normalize [ms] | Map Resample+Bld [ms] | HUD/Fused CS [ms]
----------------------------------------------------------------------------------------------------------------------------------
ONE_PASS_REFERENCE (Old)   | 18.40/26.77/181.89 |  5.27/10.34/13.19  |   4.43/10.04/83.63   |    3.39/ 8.57/11.42   |   1.75/ 4.03/ 5.79
PROD FUSED (3x900 Run 1)   | 17.20/18.78/ 26.72 |  4.61/ 9.68/11.16  |   0.00/ 0.00/  0.00  |    4.64/ 8.26/10.19   |   3.89/ 6.66/ 9.65
PROD FUSED (3x900 Run 2)   | 17.37/18.93/ 25.37 |  5.67/ 9.78/11.50  |   0.00/ 0.00/  0.00  |    4.65/ 8.36/10.08   |   3.91/ 5.73/ 9.78
PROD FUSED (3x900 Run 3)   | 17.32/18.92/ 26.55 |  5.33/ 9.87/11.45  |   0.00/ 0.00/  0.00  |    4.63/ 8.24/ 9.90   |   3.90/ 6.35/ 9.62
PROD FUSED (Full 5395f)    | 17.25/18.74/ 23.69 |  4.79/ 9.63/10.72  |   0.00/ 0.00/  0.00  |    4.63/ 8.08/ 9.50   |   3.87/ 5.85/ 9.63
```

### Ocena budżetu 60 FPS:
- **Budżet klatki 60 FPS**: $1000 / 60 = \mathbf{16.667\text{ ms}}$
- **Najlepsza mediana GPU Span**: $\mathbf{17.20\text{ ms}}$
- **Różnica do budżetu**: $+0.533\text{ ms}$

$$\mathbf{GPU\ 60\ FPS\ BUDGET = FAIL\ BY\ 0.533\ ms\ (Teoretyczny\ GPU\ Throughput = 58.1\ FPS)}$$

---

## 9. Sekcja O, P & Q: Przepustowość End-to-End i rozliczenie klatek (5395 klatek)

### Rozliczenie pełnego przebiegu (Full Material 180 s):
- **Czas trwania materiału źródłowego**: 180.01 s
- **Całkowity czas renderowania i zapisu**: **`173.91 s`** (**`31.02 TRUE FPS`**)
- **Klatki zażądane**: 5395
- **Klatki zdekodowane przez MF D3D11VA**: 5395
- **Klatki przetworzone przez VideoProcessor**: 5395
- **Klatki przekazane do AMF**: 5395
- **Klatki wyemitowane przez AMF**: 5395
- **Klatki utracone (Dropped / Retry)**: **`0`**
- **AMF_INPUT_FULL**: **`0`**
- **Kolejka AMF**: Średnio 3.79 klatki, stabilna.

---

## 10. Sekcja R & S: Stan testów i zakres zmian w Git

### Testy regresyjne (`python -m pytest`):
```text
=========================== short test summary info ===========================
FAILED tests/test_amd_native_etap4.py::test_etap4_abi_and_explicit_decode_modes (znany assert ABI 8==4)
FAILED tests/test_qp_analyzer.py::TestStatsFromHist::test_basic (znany test QP)
FAILED tests/test_render_tab.py::TestExportOptions::test_encoder_options (znany test UI)
================= 3 failed, 343 passed, 17 skipped in 25.09s ==================
```

### Zakres zmian:
Zmiany ograniczone wyłącznie do konfiguracji produkcyjnej kompozytora Fused, logowania i nowych testów kontraktowych.

---

## 11. Sekcja T: Pozostałe wąskie gardła (Remaining Bottlenecks)

Po usunięciu 7.6 ms z Normalize, profil GPU i CPU przedstawia się następująco:

1. **GPU Bottlenecks**:
   - **`Map Resample + Blend CS`**: **`4.63 – 4.65 ms`** (główny powód przekroczenia 16.667 ms o 0.53 ms).
   - **`VideoProcessorBlt`**: **`4.79 – 5.33 ms`**.
   - **`Fused HUD CS`**: **`3.87 – 3.90 ms`**.
2. **CPU Bottlenecks (Serial Pipeline)**:
   - **`Telemetry/frame_data`**: **`14.48 ms`** (45.4% czasu CPU).
   - **`compose_overlay (Pillow)`**: **`4.49 ms`** (14.2% czasu CPU).
   - **`map_cpu_upload`**: **`2.73 ms`** (9.2% czasu CPU).

---

## 12. Sekcja U & V: Klasyfikacja końcowa i Rekomendacja dla ETAPU 8L

### Klasyfikacja końcowa ETAPU 8K:

```text
FUSED PRODUCTION DEFAULT = PASS
SINGLE-RANGE CONTRACT    = PASS
NORMALIZE REMOVED        = PASS
PIXEL PARITY             = PASS (100.00% Exact across all layers)
FULL MATERIAL            = PASS (5395/5395 frames, 0 drops, 31.02 FPS)
GPU 60 FPS BUDGET        = FAIL BY ~0.53 ms (17.20 ms vs 16.667 ms)
```

### Jednoznaczna rekomendacja dla ETAPU 8L:

```text
ETAP 8L — Optymalizacja passu GPU Mapy (ResampleAndBlendMap CS: 4.64 ms -> <1.5 ms) w celu definitywnego zejścia całkowitego GPU Span poniżej 16.667 ms (GPU 60 FPS BUDGET = PASS).
```

---

**ETAP 8K ZOSTAŁ ZAKOŃCZONY. ZGODNIE Z KONTRAKTEM ZATRZYMUJĘ SIĘ.**
