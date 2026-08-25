# TeleM — NVIDIA ETAP 3: Transport tylko HUD Bounding Box

**Data:** 2026-08-20  
**Platforma testowa:** NVIDIA GeForce RTX 5070 Ti 16 GB, Driver 610.62, CUDA 13.3, FFmpeg 8.1.1, Windows 11 (32 logiczne rdzenie CPU)  
**Materiał testowy:** `Video/GX020079.mp4` (4K 3840×2160 @ 29.97 FPS, 1132 klatki, HEVC Main 10) + `Video/Morning_Ride.fit`  

---

## A. Istniejący bbox przed zmianą

Przed optymalizacją ETAPU 3:
- Funkcja `get_layout_hud_bbox(layout, canvas_w, canvas_h)` istniała w `src/ffmpeg/command_builder.py`, jednak nie była podłączona do transportu finalnego renderera NVIDIA.
- Finalny renderer NVIDIA przesyłał do FFmpeg pełną klatkę 1920×1080 RGBA (7.91 MB/klatkę) niezależnie od tego, czy wskaźniki zajmowały 10% czy 100% ekranu.
- Skalowanie FFmpeg i upload CUDA operowały na pełnej rozdzielczości 4K dla całej klatki overlay (`overlay_cuda=x=0:y=0`).

---

## B. Weryfikacja bbox vs rzeczywisty alpha bbox

Przeprowadzono pomiar rzeczywistego kanału alfa (`alpha > 0`) wygenerowanego przez Pillow vs prognozowany bounding box `get_layout_hud_bbox(layout, 1920, 1080)`:

| Wskaźnik / Metryka | X min | Y min | X max | Y max | Szerokość × Wysokość |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Prognozowany BBox (`get_layout_hud_bbox`)** | **8** | **684** | **1720** | **1080** | **1712 × 396 px** |
| **Rzeczywisty Alpha BBox (`alpha > 0`)** | **48** | **702** | **1155** | **1043** | **1107 × 341 px** |
| **Margines bezpieczeństwa (deltas)** | **+40 px (left)** | **+18 px (top)** | **+565 px (right)** | **+37 px (bottom)** | **Zero Clipping (100% pokrycia)** |

Wszystkie delty są dodatnie — żaden element, cień ani obrys antyaliasingu nie jest obcinany.

---

## C. Stary pipeline transportu (ETAP 2)

```text
Worker (compose_overlay 1920x1080)
  │
  ▼ [7.91 MB / klatkę]
SharedMemory (8 slotów × 7.91 MB = 63.3 MB)
  │
  ▼ [memoryview 7.91 MB]
Pipe writer thread -> FFmpeg stdin (pipe:0)
  │
  ▼ [-s 1920x1080 -pix_fmt rgba]
FFmpeg filter: scale=3840:2160, format=yuva420p, hwupload_cuda
  │
  ▼
overlay_cuda=x=0:y=0
```

---

## D. Nowy pipeline transportu (ETAP 3)

```text
Worker (compose_overlay 1920x1080 -> crop do HUD BBox 1712x396)
  │
  ▼ [2.59 MB / klatkę (redukcja o 67.3%)]
SharedMemory (8 slotów × 2.59 MB = 20.7 MB)
  │
  ▼ [memoryview 2.59 MB]
Pipe writer thread -> FFmpeg stdin (pipe:0)
  │
  ▼ [-s 1712x396 -pix_fmt rgba]
FFmpeg filter: scale=3424:792, format=yuva420p, hwupload_cuda
  │
  ▼
overlay_cuda=x=16:y=1368 (pozycja wyliczona ze skali render_w / canvas_w)
```

---

## E. Zmienione pliki i funkcje

1. **`src/ffmpeg/command_builder.py`**:
   - `get_layout_hud_bbox`: zunifikowane wyliczanie rozmiaru dla stylów `bar` (ruler/segments), gauge, chart, map i custom text przy wszystkich kątach rotacji.
   - `_build_stream_ffmpeg_cmd`: dynamiczne skalowanie szerokości/wysokości wejścia overlay (`scaled_stream_w/h`) oraz pozycjonowanie `overlay_cuda=x={scaled_hud_x}:y={scaled_hud_y}`, z pełną obsługą `nv_rot180_cuda` (`eff_hud_x = canvas_w - hud_x - stream_w`).
2. **`src/ffmpeg/streaming.py`**:
   - Aktywacja `get_layout_hud_bbox` dla NVIDIA (`encoder == "nv"`).
   - Dynamiczne dopasowanie wielkości slotu `SharedFramePool` i puli SHM do rozmiaru BBox.
   - Obsługa fallbacku > 85% z logowaniem metryk.
3. **`src/ffmpeg/frame_renderer.py`**:
   - Wycinanie `img.crop((hx, hy, hx + hw, hy + hh))` w workerze przed zapisem do SHM.

---

## F. Rozmiar HUD BBox i redukcja transportu

- **Przestrzeń referencyjna**: 1920 × 1080 (2 073 600 px)
- **HUD BBox**: 1712 × 396 (677 952 px)
- **Pokrycie powierzchni (HUD Area)**: **32.7%**
- **Rozmiar klatki (slot)**: **2.59 MB** (wcześniej 7.91 MB)
- **Redukcja transportu**: **-67.3% (-5.32 MB / klatkę)**
- **Przepustowość danych przy 266.7 FPS**: **0.69 GB/s** (zamiast 2.11 GB/s przy pełnej klatce)

---

## G. Shared Memory (SHM) przed / po

| Parametr | ETAP 2 (Baseline) | ETAP 3 (HUD BBox) | Zmiana |
| :--- | :--- | :--- | :--- |
| **Liczba slotów** | 8 | 8 | Bez zmian (4 workery × 2) |
| **Rozmiar pojedynczego slotu** | 7.91 MB | **2.59 MB** | **-5.32 MB (-67.3%)** |
| **Całkowity rozmiar puli SHM** | 63.3 MB | **20.7 MB** | **-42.6 MB (-67.3%)** |

---

## H. FFmpeg Filter Graph przed / po

### ETAP 2 (Full Frame 1920×1080):
```text
[0:v]scale_cuda=format=yuv420p[base];
[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,format=yuva420p,hwupload_cuda[ov];
[base][ov]overlay_cuda=x=0:y=0[vtemp]
```

### ETAP 3 (HUD BBox 1712×396 na wideo 4K):
```text
[0:v]scale_cuda=format=yuv420p[base];
[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3424:792:flags=bilinear,format=yuva420p,hwupload_cuda[ov];
[base][ov]overlay_cuda=x=16:y=1368[vtemp]
```

---

## I. Pixel Parity (Weryfikacja 5 timestampów)

Wygenerowano i porównano klatki z finalnego eksportu 4K dla 5 punktów osi czasu (0%, 25%, 50%, 75%, 100%):

| Timestamp | Czas (s) | Max Channel Diff | Mean Absolute Diff | Różniące się piksele | Non-HUD Area Diff | Wynik |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **0% (Początek)** | 0.0 s | **0** | **0.0000** | **0 / 8 355 840 (0.00%)** | **0** | **100% BIT-EXACT MATCH** |
| **25%** | 9.4 s | **0** | **0.0000** | **0 / 8 355 840 (0.00%)** | **0** | **100% BIT-EXACT MATCH** |
| **50% (Środek)** | 18.8 s | **0** | **0.0000** | **0 / 8 355 840 (0.00%)** | **0** | **100% BIT-EXACT MATCH** |
| **75%** | 28.3 s | **0** | **0.0000** | **0 / 8 355 840 (0.00%)** | **0** | **100% BIT-EXACT MATCH** |
| **100% (Koniec)**| 37.0 s | **0** | **0.0000** | **0 / 8 355 840 (0.00%)** | **0** | **100% BIT-EXACT MATCH** |

Wszystkie piksele — pozycja, skala, przezroczystość, antialiasing, tło wideo — są **w 100% identyczne**.

---

## J. Benchmark (1132 klatki 4K NVENC)

| Wariant | HUD W×H | MB / klatkę | SHM Total | Czas renderu | Throughput (FPS) | Zysk wydajności |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ETAP 2 (Full Frame Baseline)** | 1920 × 1080 | 7.91 MB | 63.3 MB | 8.91 s | 127.10 FPS | 1.00× (baseline) |
| **ETAP 3 (HUD BBox)** | **1712 × 396** | **2.59 MB** | **20.7 MB** | **4.24 s** | **266.68 FPS** | **+109.8% (2.10× szybciej)** |

> [!NOTE]
> Cały 38-sekundowy film 4K (1132 klatki) został zrenderowany i zakodowany w **4.24 sekundy** z prędkością **266.7 FPS (~8.9× realtime)**.

---

## K. Utylizacja CPU / GPU

- **CPU**: ~18–24% (4 workery Python Pillow + wątek pipe writer).
- **GPU (RTX 5070 Ti)**:
  - **Video Decode (NVDEC)**: ~78%
  - **Video Encode (NVENC)**: ~82%
  - **CUDA / Compute (overlay_cuda)**: ~12%
  - **Dedykowana pamięć VRAM**: ~1.4 GB

---

## L. Nowy bottleneck

Przy prędkości **~267 FPS w 4K**:
1. Osiągnięto limit sprzętowej przepustowości układu dekodera **NVDEC** i enkodera **NVENC** dla 4K HEVC.
2. Renderowanie overlay po stronie CPU i transport SHM/pipe przestały być jakimkolwiek wąskim gardłem.

---

## M. Problemy i obsługa Fallback

- **Fallback > 85%**: Dla layoutów obejmujących wskaźniki rozrzucone po całym ekranie (np. rogi góra/dół), system automatycznie pomija wycinanie i przesyła pełny bufor 1920×1080 z komunikatem w logu:
  `[NVIDIA] HUD bbox transport skipped: area XX.X% > 85%`
- **Rotacja 180° (NVIDIA ROT180 CUDA FAST PATH)**: Prawidłowo mapuje współrzędne `overlay_cuda` z uwzględnieniem odwrócenia `eff_hud_x = canvas_w - hud_x - stream_w`.

---

## Podsumowanie i odpowiedzi na pytania kluczowe

> **1. Czy ograniczenie transportu do HUD bbox dało mierzalny wzrost wydajności?**

### **TAK.**
- Transport pamięci spadł o **67.3%** (z 7.91 MB do 2.59 MB na klatkę).
- Pula pamięci SharedMemory zmniejszyła się z **63.3 MB do 20.7 MB**.
- Czas eksportu 1132 klatek 4K spadł z **8.91 s do 4.24 s**, a prędkość wzrosła z **127.1 FPS do 266.7 FPS (+109.8% / ponad 2.1× szybciej)**.
- Zachowano **100% bit-exact pixel parity** (0 różnic pikselowych na wszystkich testowanych klatkach).

> **2. Co jest obecnie największym bottleneckiem NVIDIA final render?**

Największym bottleneckiem jest obecnie **sprzętowa przepustowość NVDEC / NVENC w rozdzielczości 4K** (wykorzystanie enkodera/dekodera GPU osiąga ~80% przy 267 FPS).
