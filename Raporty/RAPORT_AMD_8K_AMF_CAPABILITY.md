# Raport: Zdolności AMD AMF i D3D11 dla materiałów 8K oraz skalowania do 4K/5.3K/8K

**Data wykonania:** 2026-09-22  
**Środowisko:** Windows 10/11, AMD Cezanne (Radeon Graphics 0x15E7 / gfx90c / VCN 2.2), sterownik AMD Software Adrenalin  
**Branch:** `amd-bikeridehud`  
**Autor:** Antigravity  

---

## 1. Cel zadania i kontekst problemu

Użytkownik zgłosił błąd eksportu wideo w dwóch scenariuszach:
1. **Wyjściowa rozdzielczość 8K:** Natychmiastowy błąd inicjalizacji enkodera `[hevc_amf] encoder->Init() failed with error 5` (`AMF_OUT_OF_RANGE`).
2. **Wejściowe wideo 8K -> Wyjściowa rozdzielczość 4K:** Eksport z pliku 8K (`F:\GoPro\2026-09-22\GX020310.mp4`, 7680x4320, 10-bit HEVC) z docelową rozdzielczością 4K (3840x2160) również zakończył się niepowodzeniem.

Celem niniejszej diagnostyki było dokładne zbadanie łańcucha przetwarzania potoku `AMD_NATIVE_D3D11`, ustalenie dokładnego miejsca wystąpienia pierwszego błędu (`FIRST_FAILURE`), weryfikacja alokacji zasobów i VRAM oraz jednoznaczne rozróżnienie limitów enkodera AMF od limitów sprzętowego skalera D3D11 Video Processor.

---

## 2. Wyniki obowiązkowej macierzy testowej (1–10 klatek)

| Parametr | Test A: 4K in -> 4K out | Test B: 8K in -> 4K out | Test C: 8K in -> 5.3K out | Test D: 8K in -> 8K out |
| :--- | :--- | :--- | :--- | :--- |
| **Plik wejściowy** | `Video\GX020079.MP4` | `F:\GoPro\2026-09-22\GX020310.mp4` | `F:\GoPro\2026-09-22\GX020310.mp4` | `F:\GoPro\2026-09-22\GX020310.mp4` |
| **INPUT_W/H** | `3840x2160` | `7680x4320` | `7680x4320` | `7680x4320` |
| **DECODE_SURFACE_W/H** | `3840x2160` (Array=11) | `7680x4320` (Array=11) | `N/A` (stop przed decode) | `N/A` (stop przed decode) |
| **POST_SCALE_W/H** | `3840x2160` | `3840x2160` | `5312x2988` | `7680x4320` |
| **COMPOSITOR_W/H** | `3840x2160` | `3840x2160` | `5312x2988` | `7680x4320` |
| **ENCODER_INPUT_W/H** | `3840x2160` | `3840x2160` | `5312x2988` | `7680x4320` |
| **FINAL_OUTPUT_W/H** | `3840x2160` | `3840x2160` | `5312x2988` | `7680x4320` |
| **D3D11_DECODE_FORMAT** | `DXGI_FORMAT_P010` (104) | `DXGI_FORMAT_P010` (104) | `DXGI_FORMAT_P010` | `DXGI_FORMAT_P010` |
| **D3D11_POST_SCALE_FORMAT**| `DXGI_FORMAT_NV12` (103) | `DXGI_FORMAT_NV12` (103) | `DXGI_FORMAT_NV12` | `DXGI_FORMAT_NV12` |
| **AMF_INPUT_FORMAT** | `AMF_SURFACE_NV12` | `AMF_SURFACE_NV12` | `AMF_SURFACE_NV12` | `AMF_SURFACE_NV12` |
| **DECODER_INIT** | **PASS** | **PASS** | `NOT REACHED` | `NOT REACHED` |
| **VIDEO_PROCESSOR_INIT** | **PASS** | **PASS** | **PASS** | **PASS** |
| **SCALE_INIT** | **PASS** | **PASS** | **PASS** | **PASS** |
| **COMPOSITOR_INIT** | **PASS** | **PASS** | `NOT REACHED` | `NOT REACHED` |
| **AMF_INIT** | **PASS** | **PASS** (3840x2160) | **FAIL** (error 5) | **FAIL** (error 5) |
| **FIRST_FRAME** | **PASS** (16.9 ms) | **FAIL** (`VP Blt` 0x80004005)| `NOT REACHED` | `NOT REACHED` |
| **STATUS KOŃCOWY** | **PASS** | **FAIL** | **FAIL** | **FAIL** |

---

## 3. Kluczowe pytania i dowody diagnostyczne

### 3.1. Czy AMF dla 8K input -> 4K output otrzymuje 3840x2160 czy 7680x4320?
**Dowód logiem bezpośrednio przed wywołaniem `amfEncoder.Initialize()` w `telem_amd_native.cpp`:**
```text
[MEMORY BEFORE AMF INIT]
  process_private_mb=528.73
  system_commit_mb=36559.91
  GPU_dedicated_used_mb=0.00
  GPU_shared_used_mb=0.00
  decode_surface_count=0
  decode_surface_bytes_total=0
  postscale_surface_count=8
  postscale_surface_bytes_total=99532800
  encoder_surface_count=4
  encoder_surface_bytes_total=49766400
AMF_ENCODER_WIDTH=3840
AMF_ENCODER_HEIGHT=2160
```
**Wniosek:** AMF otrzymuje dokładnie `3840x2160`. Inicjalizacja AMF dla 8K->4K **zakończyła się pełnym sukcesem**. Enkoder AMF nie był przyczyną błędu w teście 8K->4K.

### 3.2. Weryfikacja spójności parametrów wyjściowych (UI -> Enkoder)
Prześledzono cały przepływ konfiguracji dla opcji wyjściowej 4K:
```text
OUTPUT_RESOLUTION_OPTION=3840x2160 (4k)
OUTPUT_RESOLUTION_CHILD=3840x2160 (4k)
OUTPUT_RESOLUTION_FFMPEG=3840x2160
OUTPUT_RESOLUTION_AMF=3840x2160
```
Wszystkie poziomy są w 100% zgodne i respektują żądaną rozdzielczość docelową 4K.

### 3.3. Standalone 8K Decode Test (bez HUD, bez AMF)
Przetestowano dekodowanie 8K 10-bit HEVC (`F:\GoPro\2026-09-22\GX020310.mp4`, 7680x4320, 29.97 fps) w dwóch trybach:
1. **FFmpeg D3D11VA standalone:**
   ```text
   ffmpeg -hwaccel d3d11va -i GX020310.mp4 -frames:v 10 -f null -
   -> returncode=0, elapsed=1.335s [PASS]
   ```
2. **Native Media Foundation D3D11VA Reader (telem_amd_native):**
   ```text
   telem_amd_native MF D3D11VA decode only 10 frames: decoded=10/10, format=104 (P010), size=7680x4320
   -> 8K_D3D11_DECODE=PASS
   ```
**Raport:**
```text
8K_D3D11_DECODE=PASS
```
Sprzętowy dekoder AMD VCN 2.2 bez problemu dekoduje strumień 8K 10-bit P010.

### 3.4. Standalone 8K -> 4K GPU Scale Test (8K decode -> D3D11 VideoProcessor -> no HUD, no AMF)
Wykonano test weryfikujący samo sprzętowe skalowanie D3D11 VideoProcessor (`telem_amd_process_frame` z wyłączonym HUD, wyłączoną mapą i wyłączonym enkoderem AMF):
```text
[VP DIAG] frame 0 Blt: inDesc=7680x4320 out=3840x2160 srcRect=(0,0,7680,4320) dstRect=(0,0,3840,2160)
[VP] VideoProcessorBlt FAILED: 0x80004005 frame=0
[VP] GPU compositor failed: 0x80004005
[TELEM AMD DLL] VP ProcessFrame failed on frame 0
-> 8K_TO_4K_GPU_SCALE=FAIL
```
Dodatkowo przetestowano przypadek odczytu fragmentu 1:1 (`srcRect = 3840x2160` z tekstury 8K bez skalowania). Operacja `VideoProcessorBlt` zakończyła się identycznym błędem `0x80004005`.
**Wniosek:** Sprzętowy skaler D3D11 Video Processor sterownika AMD odrzuca teksturę wejściową o szerokości 7680 px na poziomie API `VideoProcessorBlt`.

---

## 4. Pomiary pamięci i VRAM (8K input -> 4K output)

### A. Bezpośrednio przed AMF Init (przed odczytem klatek wideo):
```text
process_private_mb=528.73
system_commit_mb=36559.91
GPU_dedicated_used_mb=0.00
GPU_shared_used_mb=0.00

decode_surface_count=0
decode_surface_bytes_total=0
postscale_surface_count=8
postscale_surface_bytes_total=99532800 (94.9 MB)
encoder_surface_count=4
encoder_surface_bytes_total=49766400 (47.5 MB)
```

### B. Na klatce 0 tuż przed wykonaniem `VideoProcessorBlt` (po zaalokowaniu dekodera 8K):
```text
process_private_mb=1630.04
system_commit_mb=38731.99
GPU_dedicated_used_mb=1204.54 (~1.2 GB VRAM)
GPU_shared_used_mb=0.00

decode_surface_count=11
decode_surface_bytes_total=1094860800 (~1.02 GB VRAM)
postscale_surface_count=8
postscale_surface_bytes_total=99532800 (94.9 MB)
encoder_surface_count=4
encoder_surface_bytes_total=49766400 (47.5 MB)
```
**Wniosek dotyczący zasobów:** Pamięć VRAM i RAM **nie zostały wyczerpane**. Dekoder D3D11VA zaalokował 1.02 GB na tablicę 11 powierzchni 8K, co bez problemu zmieściło się w pamięci GPU (1204 MB VRAM użyte).

---

## 5. Test HUD OFF / MAP OFF

Dla 8K input -> 4K output przetestowano wariant z całkowitym wyłączeniem warstw HUD i Mapy:
- Wyłączona mapa (`map_enabled = False`)
- Wyłączony HUD (`hud_enabled = 0`, `enable_hud = 0`)
- Wyłączone wykresy i wskaźniki (`AMD_GPU_HUD_OFF = 1`)

Wynik: **Identyczny błąd `VideoProcessorBlt: 0x80004005` na klatce 0**.
```text
HUD_MAP_NOT_ROOT_CAUSE=True
```

---

## 6. Pierwszy błąd i hierarchia awarii

```text
FIRST_FAILURE=D3D11_VIDEO_PROCESSOR_BLT (dla 8K input -> 4K output)
FIRST_FAILURE=AMF_ENCODER_INIT (dla wyjścia 5.3K i 8K)

AMF_INIT_FAILURE_SECONDARY=False
```
Dla eksportu `8K input -> 4K output` enkoder AMF zainicjalizował się pomyślnie, a błąd wystąpił wcześniej – w D3D11 Video Processorze podczas próby przeskalowania zdekodowanej powierzchni 8K do 4K.

---

## 7. Aktualizacja klasyfikacji przyczyn (Case Analysis)

- **CASE A — Brak obsługi kodowania AMF powyżej 4096 px:** `TRUE` (potwierdzone oficjalnym zapytaniem AMF C++: `AMFIOCaps` zwraca `max_width=4096, max_height=4096`).
- **CASE F — 8K input D3D11 decode/surface allocation blocker:** `FALSE`. Dekodowanie 8K D3D11VA działa w 100% poprawnie w Media Foundation i FFmpeg.
- **CASE G — 8K->4K scaling / D3D11 VideoProcessor input dimension limit:** `TRUE`. Układ sprzętowy Video Processor w architekturze VCN 2.2 / Vega APU nie obsługuje wejściowych powierzchni 7680x4320 w funkcji `VideoProcessorBlt`.
- **CASE H — Resource/VRAM exhaustion before AMF init:** `FALSE`. Pomiary wykazały brak wyczerpania zasobów.

---

## 8. Obowiązkowe podsumowanie końcowe

```text
8K_INPUT_4K_OUTPUT=FAIL
8K_INPUT_5K_OUTPUT=FAIL
8K_INPUT_8K_OUTPUT=FAIL

8K_D3D11_DECODE=PASS
8K_TO_4K_GPU_SCALE=FAIL

AMF_WIDTH_FOR_8K_TO_4K=3840
AMF_HEIGHT_FOR_8K_TO_4K=2160

FIRST_FAILURE=D3D11_VIDEO_PROCESSOR_BLT (dla 8K->4K); AMF_ENCODER_INIT (dla wyjścia >= 5.3K)
AMF_INIT_FAILURE_SECONDARY=False

RESOURCE_PRESSURE_BEFORE_AMF_INIT=528.73 MB RAM, 0 MB GPU VRAM (BRAK PRZECIĄŻENIA ZASOBÓW)

ROOT_CAUSE=W architekturze AMD Cezanne (VCN 2.2) występują dwie niezależne bariery sprzętowe:
1. Sprzętowy enkoder HEVC AMF posiada sztywny limit maksymalnej rozdzielczości kodowania 4096 x 4096 px (dlatego wyjście 5.3K i 8K kończy się błędem AMF_OUT_OF_RANGE).
2. Sprzętowy skaler D3D11 Video Processor nie obsługuje operacji Blt na teksturach wejściowych 8K (7680x4320), zwracając błąd E_FAIL (0x80004005). Pomimo że dekodowanie sprzętowe 8K D3D11VA działa w pełni poprawnie i AMF dla wyjścia 4K inicjalizuje się bez błędu, natywny potok GPU D3D11 nie jest w stanie dokonać sprzętowego przeskalowania 8K -> 4K przez VideoProcessorBlt.
```
