# Raport AMD 8K CPU-x265 — bramki interoperacyjności D3D11

Data: 2026-09-22  
Cel: pełny eksport 8K CPU-x265, bez zmiany celu na 4K  
Środowisko: AMD Cezanne, D3D11VA, wejście 7680x4320 P010  
Kontrakt: `TRUE_8K_REQUIRED=True`, `FINAL_OUTPUT=7680x4320`, `4K_DOWNSCALE_AS_8K_SOLUTION=False`

## Stan początkowy

Istniejący kod dla wymiarów >4K nadal przechodził przez topologię VP, z
`OutputWidth/OutputHeight=3840x2160`, a ścieżka x265 otrzymywała wynik z puli
powiązanej z VP. Istniał też bezpośredni wariant SRV na powierzchni dekodera.
Celem etapu było odseparowanie CPU-x265 8K od VideoProcessorBlt i sprawdzenie
wariantu decoder-surface → zwykła tekstura SRV-only.

## Zmienione pliki

- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h`
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
- przebudowany `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`

Raport zapisano wyłącznie w `Raporty/`. Repozytorium miało wcześniejsze,
niezwiązane modyfikacje i usunięcia; nie zostały czyszczone ani nadpisane.

## Implementacja

1. Tryb `CPU_X265` dla 8K jest rozpoznawany przed inicjalizacją pipeline'u.
2. Dla tego trybu `SetupVideoProcessor` używa compute-only topology:
   - output pool ma `7680x4320`;
   - `VideoProcessorOutputView` nie jest tworzony;
   - `OutputWidth=3840` nie jest używany;
   - `VideoProcessorBlt` nie jest wywoływany.
3. Decoder surface jest kopiowany przez `CopySubresourceRegion` do zwykłej
   tekstury `ArraySize=1`, `BIND_SHADER_RESOURCE`.
4. SRV Y/UV jest tworzony wyłącznie na tej kopii.
5. Compute shader zapisuje 1:1 do 8K NV12 output texture.
6. Istniejący staging ring wykonuje GPU→CPU readback, a dane trafiają do
   `libx265` 10-bit.

Bezpośredni SRV na decoder array nie był tworzony w tej ścieżce.

## Wyniki bramek

### Gate A — copy only

```text
COPY_8K_TO_SRV_TEXTURE=PASS
DEVICE_REASON_AFTER_COPY=0x0
```

Kopia 8K do zwykłej tekstury SRV-only przeszła bez device removal/TDR.

### Gate B — SRV na skopiowanej teksturze

```text
SRV_ON_COPIED_8K_TEXTURE=PASS
DEVICE_REASON_AFTER_SRV=0x0
```

Oba plane SRV (`Y` i `UV`) zostały utworzone na kopii.

### Gate C — shader 1:1

```text
8K_SHADER_1TO1=PASS
DEVICE_REASON_AFTER_DISPATCH=0x0
```

Jedna klatka 7680x4320 P010 → 7680x4320 output texture przeszła.

### Gate D — readback

```text
8K_READBACK=PASS
READBACK_FORMAT=NV12
READBACK_BYTES=49766400
READBACK_MS=23.0324
```

### x265 — 1 frame

```text
GATE 1: 8K CPU X265 1 FRAME = PASS
ffprobe: codec_name=hevc, width=7680, height=4320, pix_fmt=yuv420p10le
```

Finalny plik miał rozdzielczość `7680x4320`; nie wykonano downscale'u do 4K.

## Test 10 klatek

Test pełnego 8K copy → shader → readback → x265 nie zakończył się w limicie
120 s i został przerwany. Nie klasyfikuję go jako PASS.

Dodatkowa próba 10 klatek bez readbacku/x265, tylko copy + shader, zakończyła
się access violation w kolejnym wywołaniu `telem_amd_process_frame`. To jest
obecny hard blocker dla stabilności wieloklatkowej i wymaga osobnej analizy
życia zasobów/puli lub device state. Testów nie powtarzano po tym hard failure.

```text
GATE_A_COPY=PASS
GATE_B_SRV_ON_COPY=PASS
GATE_C_SHADER_1TO1_1FRAME=PASS
GATE_D_READBACK_1FRAME=PASS
X265_1FRAME_8K=PASS
X265_10FRAME=BLOCKED
MULTIFRAME_COPY_SHADER=FAIL (access violation)
FINAL_OUTPUT=7680x4320 (1 frame proven)
```

## Testy i budowanie

- `ninja -C native/d3d11_amf_pipeline/build telem_amd_native` — PASS.
- Pełny target CMake — NOT TESTED jako PASS: niezwiązany target
  `d3d11_etap2c_poc` zatrzymuje build przez istniejący brak
  `CreateHUDTexture`.
- Gate A, B, C i D — wyniki powyżej.
- x265 1 frame — PASS.
- x265 10 frames — BLOCKED po braku postępu >120 s.
- 4K/NVIDIA/Intel regresja — NOT TESTED w tym etapie.

## Ryzyka / regresje

- Wieloklatkowa ścieżka 8K nie jest jeszcze stabilna; nie wolno jej oznaczyć
  jako produkcyjnie zakończonej.
- Access violation może dotyczyć reuse output pool, synchronizacji GPU albo
  lifetime decoder copy/staging; przyczyna nie została jeszcze udowodniona.
- `VideoProcessorBlt` pozostaje bez zmian dla ścieżek innych niż 8K CPU-x265.

## Backend isolation

Zmiana jest warunkowana `AMD_NATIVE_ENCODER_MODE=x265` oraz wymiarem >4K.
Nie zmienia zachowania NVIDIA/NVENC/CUDA, Intel/QSV ani AMD AMF 4K.

## Time breakdown

```text
TOTAL_STAGE_WALL_TIME: ~35 min
AUDIT_TIME: ~8 min
REPRO_TIME: ~17 min
IMPLEMENTATION_TIME: ~7 min
VALIDATION_TIME: ~3 min
LONGEST_SINGLE_COMMAND_SECONDS: ~120 s (przerwany test 10 klatek)
```

## Podsumowanie

```text
TASK: FULL TRUE 8K D3D11VA -> GPU COMPUTE -> READBACK -> CPU x265 PATH
STATUS: PARTIAL / BLOCKED — gates A-D and 1-frame export PASS; multiframe stability FAIL
FINAL PASS/FAIL: PASS for 1 frame, FAIL/BLOCKED for 10-frame stability
```
