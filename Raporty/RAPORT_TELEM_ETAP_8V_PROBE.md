# RAPORT_TELEM_ETAP_8V_PROBE: D3D11 VideoProcessor Multi-Stream Capability Check

**Data:** 2026-08-19  
**Faza:** ETAP 8V-PROBE (Hardware VideoProcessor Capability Probe)  
**Cel:** Ustalić na fizycznym adapterze AMD GPU, czy silnik D3D11 VideoProcessor może wykonać scalenie strumienia Video (P010/NV12) oraz strumienia HUD (RGBA/BGRA z per-pixel alpha) do wyjściowego formatu NV12 w pojedynczym wywołaniu `ID3D11VideoContext::VideoProcessorBlt`.

---

## 1. WYNIKI PROBE INTERFEJSÓW I SPRZĘTOWYCH FLAG CAPS

Probe uruchomiono na fizycznym adapterze GPU AMD Radeon:

```text
[1. VIDEO PROCESSOR CAPS]
  DeviceCaps:            0x19
  FeatureCaps:           0x8e6
    - ALPHA_FILL:        NO
    - CONST_METADATA:    YES
    - ALPHA_PALETTE:     NO
    - LEGACY:            NO
  InputFormatCaps:       0x0
    - RGB_INTERLACED:    NO
    - RGB_PROCAMP:       NO
    - RGB_LUMA_KEY:      NO
    - PALETTE_INTERLACED:NO
  MaxInputStreams:       52
  MaxStreamStates:       52

[2. FORMAT SUPPORT (CheckVideoProcessorFormat)]
  DXGI_FORMAT_P010               : INPUT=YES | OUTPUT=YES (raw=0x3)
  DXGI_FORMAT_NV12               : INPUT=YES | OUTPUT=YES (raw=0x3)
  DXGI_FORMAT_R8G8B8A8_UNORM     : INPUT=YES | OUTPUT=YES (raw=0x3)
  DXGI_FORMAT_B8G8R8A8_UNORM     : INPUT=YES | OUTPUT=YES (raw=0x3)
  DXGI_FORMAT_AYUV               : INPUT=NO  | OUTPUT=NO  (raw=0x0)
  DXGI_FORMAT_YUY2               : INPUT=YES | OUTPUT=NO  (raw=0x1)
  DXGI_FORMAT_R16G16B16A16_FLOAT : INPUT=YES | OUTPUT=YES (raw=0x3)

[3. FORMAT CONVERSIONS (CheckVideoProcessorFormatConversion)]
  P010 (Rec.709) -> NV12 (Rec.709) Conversion:          YES
  R8G8B8A8_UNORM (sRGB) -> NV12 (Rec.709) Conversion:  YES
  B8G8R8A8_UNORM (sRGB) -> NV12 (Rec.709) Conversion:  YES
```

---

## 2. TESTY WYWOŁANIA `VideoProcessorBlt` I ZACHOWANIA KANAŁU ALPHA

Wykonano precyzyjne testy 1-ramkowe z bezpośrednim odczytem pamięci (staging readback):

1. **Test 1 (Stream 0 alone: NV12 $\to$ NV12):** `S_OK`
2. **Test 2 (Stream 0 alone: BGRA $\to$ NV12):** `S_OK`
3. **Test 3 (2 Streams: Stream 0 Video NV12 + Stream 1 HUD BGRA):** `S_OK`
4. **Test 4 (`VideoProcessorSetStreamAlpha` Enable=TRUE lub alpha < 1.0):** `FAILED (0x80004005, E_FAIL)`
5. **Test 5 (`VideoProcessorSetStreamColorSpace1` na Stream 1):** `FAILED (0x80004005, E_FAIL)`

### Wynik inspekcji pikseli po 2-Stream Blt (Readback Test):
- Przygotowano powierzchnię wideo z $Y = 128$ (szary).
- Przygotowano powierzchnię HUD z lewą połową w pełni przezroczystą ($\alpha = 0$, $RGB=0,0,0$) oraz prawą połową białą ($\alpha = 255$, $RGB=255,255,255$).
- **Odczyt lewej połowy (gdzie $\alpha = 0$):**
  - Oczekiwana wartość przy blendingu per-pixel alpha: $Y = 128$ (tło zachowane).
  - **Faktyczna wartość wyjściowa:** $Y = 0$ (pełne, nieprzezroczyste nadpisanie czernią z konwersji RGB$\to$NV12!).

---

## 3. ANALIZA I WNIOSKI ARCHITEKTONICZNE

1. **Brak sprzętowego wsparcia dla Per-Pixel Alpha Blending w D3D11 VideoProcessor na AMD:**
   - Sterownik AMD traktuje strumienie podrzędne (Stream 1..N) jako nieprzezroczyste okna Picture-in-Picture (PiP).
   - Wartości kanału Alpha ($\alpha$) w teksturach RGBA/BGRA są ignorowane podczas konwersji sprzętowej Video Processor $\to$ NV12, a włączenie `VideoProcessorSetStreamAlpha` zwraca błąd `E_FAIL`.

2. **Dyskwalifikacja ścieżki VideoProcessor dla nakładania HUD:**
   - Silnik VideoProcessor nie nadaje się do kompozycji interfejsu telemetrycznego z przezroczystościami (napisy, wykresy z antialiasingiem, przezroczysta mapa, wskaźniki).

3. **Jednoznaczny kierunek produkcyjny:**
   - Prawidłową i najszybszą ścieżką kompozycji pozostaje **Direct Compute Shader** w zoptymalizowanej architekturze **`TILE_MASK_FUSED_32X8`** wykazanej w ETAP 8V-A.

---

## 4. FINAL CLASSIFICATION GATE — ETAP 8V-PROBE

```text
================================================================================
FINAL CLASSIFICATION GATE — ETAP 8V-PROBE
================================================================================
MAX_INPUT_STREAMS                   = 52
RGBA INPUT                          = YES
NV12 OUTPUT                         = YES
ALPHA STREAM                        = NO  (E_FAIL 0x80004005 on driver)
FORMAT CONVERSION                   = YES (RGB/P010 -> NV12 confirmed)
2-STREAM BLT S_OK                   = YES (Opaque Picture-in-Picture only)
PIXEL PARITY                        = FAIL (Alpha ignored, solid overwrite Y=0)
GPU TIME                            = NOT TESTED (disqualified on alpha)
VIDEO_PROCESSOR_COMPOSITOR_FEASIBLE = NO
================================================================================
```
