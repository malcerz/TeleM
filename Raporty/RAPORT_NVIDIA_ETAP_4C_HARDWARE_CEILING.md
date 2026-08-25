# TeleM — RAPORT NVIDIA ETAP 4C: HARDWARE CEILING NVDEC / NVENC

**Data:** 2026-08-20  
**Środowisko:** Windows 11, NVIDIA GeForce RTX 5070 Ti 16 GB, Driver 610.62, CUDA 13.3, FFmpeg 8.1.1  
**Materiał testowy:** `Video/GX020079.mp4` (4K 3840×2160 @ 29.97 FPS, 1132 klatki, 37.74 s, HEVC Main10 48.0 Mbps) + `Video/Morning_Ride.fit`  
**Autor:** Antigravity AI  

---

## A. Aktualny pipeline TeleM (Stan wyjściowy po ETAPIE 4B)

W potoku eksportu NVIDIA obowiązuje konfiguracja:
```text
Hardware: RTX 5070 Ti (16 GB VRAM)
FFmpeg: 8.1.1
Dekoder: NVDEC (hwaccel cuda, hwaccel_output_format cuda)
Base filter: scale_cuda=format=yuv420p
Koder: hevc_nvenc (preset p1, tune hq, rc vbr, cq 24, pix_fmt cuda, gpu 0, bitrate 40M)
Workers: 4 procesy robocze (Pillow)
Kolejkowanie: MAX_IN_FLIGHT = 8 (SharedFramePool)
Transport: MULTI_REGION_ATLAS (1112×668 RGBA, 2.83 MB/slot, SHM Total ~22.7 MB)
```

Wyniki produkcyjne z Etapu 4B:
- **`FRAME_PIPELINE`:** **209.4–214.9 FPS** (5.27–5.41 s)
- **`PRODUCTION_TOTAL`:** **174.6–178.8 FPS** (6.33–6.48 s)
- **`ffmpeg_write`:** avg = **0.86 ms** | p95 = **1.62 ms**

---

## B. Dokładna komenda i parametry produkcyjnego NVENC

Odczytane z aktualnego `command_builder.py` / logu produkcyjnego:

| Parametr | Wartość | Opis / Rola |
| :--- | :--- | :--- |
| **Input HWAccel** | `-hwaccel cuda -hwaccel_output_format cuda` | Pełne dekodowanie w VRAM bez powrotu do RAM |
| **Base Filter** | `[0:v]scale_cuda=format=yuv420p[base]` | Konwersja Main10 do 8-bit YUV420P na rdzeniach CUDA |
| **Codec** | `-c:v hevc_nvenc` | Sprzętowy enkoder HEVC NVIDIA NVENC (Gen 9) |
| **Preset** | `-preset p1` | Najszybszy profil kompresji (Fastest / Lowest latency) |
| **Tune** | `-tune hq` | Strojenie jakości obrazu High Quality |
| **Rate Control** | `-rc vbr` | Zmienna przepływność bitowa sterowana jakością |
| **Quality target** | `-cq 24` | Constant Quality Factor = 24 |
| **Pixel format** | `-pix_fmt cuda` | Ramki wideo pozostają w pamięci CUDA urządzenia |
| **Bitrate / Maxrate** | `-b:v 40M -maxrate 40M` | Docelowy i maksymalny bitrate wideo = 40 Mbps |
| **Buffer size** | `-bufsize 80M` | Bufor VBV = 80 Mb (2× bitrate) |
| **GPU ID** | `-gpu 0` | Dedykowana karta NVIDIA RTX 5070 Ti |
| **Audio** | `-c:a copy` | Bezstratne kopiowanie strumienia audio AAC |

---

## C. TEST A — NVDEC ONLY (Sprzętowe dekodowanie)

**Cel:** Zmierzenie maksymalnej przepustowości samego sprzętowego dekodera NVDEC dla 4K HEVC Main10 bez kodowania, filtrów i zapisu dyskowego.

**Komenda:**
```bash
ffmpeg -y -hwaccel cuda -hwaccel_output_format cuda -i Video/GX020079.mp4 -f null -
```

**Wyniki 3 powtórzeń (1132 klatki):**
- Przebieg 1: `2.333 s` (485.1 FPS)
- Przebieg 2: `2.328 s` (486.2 FPS)
- Przebieg 3: `2.335 s` (484.7 FPS)
- **Mediana:** **2.333 s | 485.1 FPS** (Min: 484.7, Max: 486.2)
- **Telemetria GPU:** NVDEC avg: **80.0%** (max 100%), NVENC: **0.0%**, CUDA: **4.8%**, CPU: **3.8%**, VRAM: **2650 MB**.

---

## D. TEST B — BARE NVDEC → SCALE_CUDA → NVENC (Punkt odniesienia)

**Cel:** Wyznaczenie rzeczywistego sprzętowego sufitu (`BARE_TRANSCODE_FPS`) dla potoku bazowego TeleM (dekodowanie 4K Main10 → konwersja do 8-bit YUV420P na CUDA → kodowanie HEVC NVENC 40M) bez nakładania HUD i bez procesów Pythona.

**Komenda:**
```bash
ffmpeg -y -hwaccel cuda -hwaccel_output_format cuda -i Video/GX020079.mp4 \
  -filter_complex "[0:v]scale_cuda=format=yuv420p[base];[base]null[vout]" \
  -map "[vout]" -map_metadata -1 -metadata:s:v:0 rotate=0 \
  -c:v hevc_nvenc -preset p1 -tune hq -rc vbr -cq 24 -pix_fmt cuda -gpu 0 \
  -b:v 40M -maxrate 40M -bufsize 80M -f null -
```

**Wyniki 3 powtórzeń (1132 klatki):**
- Przebieg 1: `2.717 s` (416.7 FPS)
- Przebieg 2: `2.697 s` (419.7 FPS)
- Przebieg 3: `2.709 s` (417.9 FPS)
- **Mediana:** **2.709 s | 417.9 FPS** (Min: 416.7, Max: 419.7)
- **Telemetria GPU:** NVDEC avg: **67.4%** (max 99%), NVENC avg: **66.6%** (max 89%), CUDA: **11.0%**, CPU: **8.4%**, VRAM: **2890 MB**.

> [!IMPORTANT]
> **BARE_TRANSCODE_FPS = 417.9 FPS** stanowi absolutny fizyczny sufit sprzętowy karty RTX 5070 Ti dla tego klipu i konfiguracji kodera.

---

## E. TEST C — CUDA Filter Graph / overlay_cuda Overhead (NO-OP)

**Cel:** Izolacja kosztu samego filter graphu CUDA (rozpakowanie atlasu na 3 regiony: `split=3` → `crop` × 3 → `scale` do 4K × 3 → `format=yuva420p` → `hwupload_cuda` → `overlay_cuda` × 3) przy użyciu pustego, statycznego bufora 1112×668 RGBA, bez udziału workerów Pillow i bez telemetrii.

**Komenda:**
```bash
ffmpeg -y -hwaccel cuda -hwaccel_output_format cuda -i Video/GX020079.mp4 \
  -loop 1 -framerate 29.97 -t 37.74 -i scratch/blank_atlas.png \
  -filter_complex "[0:v]scale_cuda=format=yuv420p[base];[1:v]setpts=PTS-STARTPTS,format=rgba,split=3[ov_raw_0][ov_raw_1][ov_raw_2];[ov_raw_0]crop=426:170:0:0,scale=852:340:flags=bilinear,format=yuva420p,hwupload_cuda[ov_0];[ov_raw_1]crop=678:332:430:0,scale=1356:664:flags=bilinear,format=yuva420p,hwupload_cuda[ov_1];[ov_raw_2]crop=1082:332:0:336,scale=2164:664:flags=bilinear,format=yuva420p,hwupload_cuda[ov_2];[base][ov_0]overlay_cuda=x=20:y=28[v_step_0];[v_step_0][ov_1]overlay_cuda=x=2380:y=1496[v_step_1];[v_step_1][ov_2]overlay_cuda=x=88:y=1496[vout]" \
  -map "[vout]" -map_metadata -1 -metadata:s:v:0 rotate=0 \
  -c:v hevc_nvenc -preset p1 -tune hq -rc vbr -cq 24 -pix_fmt cuda -gpu 0 \
  -b:v 40M -maxrate 40M -bufsize 80M -f null -
```

**Wyniki 3 powtórzeń (1132 klatki):**
- Przebieg 1: `3.399 s` (333.1 FPS)
- Przebieg 2: `3.429 s` (330.1 FPS)
- Przebieg 3: `3.409 s` (332.0 FPS)
- **Mediana:** **3.409 s | 332.0 FPS** (Min: 330.1, Max: 333.1)
- **Telemetria GPU:** NVDEC avg: **70.7%**, NVENC avg: **58.3%**, CUDA avg: **38.9%** (max 54%), CPU: **16.3%**, VRAM: **3610 MB**.
- **Wpływ kaskady filtrów CUDA:** Spadek z 417.9 FPS do 332.0 FPS (**-85.9 FPS**, $+0.70\text{ s}$ na całym klipie).

---

## F. TEST D — Pełny produkcyjny TeleM Atlas (Stage 4B)

**Cel:** Zmierzenie rzeczywistego produkcyjnego potoku TeleM z pełnym renderowaniem wskaźników (Pillow, telemetria FIT/GPMF, 4 workery, IPC SharedMemory, pipe writing).

**Wyniki 3 powtórzeń (1132 klatki):**
- Przebieg 1: `6.807 s` (166.3 FPS) | `FRAME_PIPELINE`: 5.627 s (201.2 FPS)
- Przebieg 2: `6.472 s` (174.9 FPS) | `FRAME_PIPELINE`: 5.405 s (209.4 FPS)
- Przebieg 3: `6.485 s` (174.6 FPS) | `FRAME_PIPELINE`: 5.407 s (209.4 FPS)
- **Mediana `PRODUCTION_TOTAL`:** **6.485 s | 174.6 FPS** (Min: 166.3, Max: 174.9)
- **Mediana `FRAME_PIPELINE`:** **5.407 s | 209.4 FPS**
- **Telemetria GPU:** NVDEC avg: **36.4%**, NVENC avg: **32.1%**, CUDA avg: **24.2%**, CPU avg: **27.6%** (max 66.9%), VRAM: **3735 MB**.
- **Zapis do potoku (`ffmpeg_write`):** avg = **0.86 ms** | p95 = **1.62 ms** | range = [0.30–4.09] ms.

---

## G. Opcjonalny TEST E — NVENC ONLY (Syntetyczne klatki)

**Cel:** Zmierzenie maksymalnej przepustowości samego enkodera NVENC bez dekodowania wideo (klatki syntetyczne 4K generowane w pamięci).

**Komenda:**
```bash
ffmpeg -y -f lavfi -i nullsrc=s=3840x2160:r=29.97:d=37.74 \
  -filter_complex "[0:v]format=yuv420p,hwupload_cuda[vout]" -map "[vout]" \
  -c:v hevc_nvenc -preset p1 -tune hq -rc vbr -cq 24 -pix_fmt cuda -gpu 0 \
  -b:v 40M -maxrate 40M -bufsize 80M -f null -
```

**Wyniki 3 powtórzeń (1132 klatki):**
- Przebieg 1: `2.195 s` (515.7 FPS)
- Przebieg 2: `2.211 s` (512.1 FPS)
- Przebieg 3: `2.216 s` (510.7 FPS)
- **Mediana:** **2.211 s | 512.1 FPS** (Min: 510.7, Max: 515.7)
- **Telemetria GPU:** NVDEC: **0.0%**, NVENC avg: **60.0%** (max 90%), CUDA: **22.9%**, CPU: **8.5%**, VRAM: **2135 MB**.

> [!NOTE]
> *Status testu:* **SYNTHETIC SOURCE (BLACK FRAMES)**. Test potwierdza, że sam blok NVENC w RTX 5070 Ti przekracza 510+ FPS przy kompresji jednolitych klatek 4K HEVC.

---

## H. Zbiorcze zestawienie wyników

| Test | Pipeline / Komponent | Mediana FPS | Min FPS | Max FPS | Czas trwania | NVDEC % | NVENC % | CUDA % | CPU % |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **TEST A** | NVDEC ONLY (Hardware Decode) | **485.1** | 484.7 | 486.2 | 2.333 s | 80.0% | 0.0% | 4.8% | 3.8% |
| **TEST E** | NVENC ONLY (Synthetic 4K Encode) | **512.1** | 510.7 | 515.7 | 2.211 s | 0.0% | 60.0% | 22.9% | 8.5% |
| **TEST B** | **BARE TRANSCODE (NVDEC → NVENC)** | **417.9** | 416.7 | 419.7 | 2.709 s | 67.4% | 66.6% | 11.0% | 8.4% |
| **TEST C** | NVDEC + CUDA 3-Atlas Filters + NVENC | **332.0** | 330.1 | 333.1 | 3.409 s | 70.7% | 58.3% | 38.9% | 16.3% |
| **TEST D** | **TeleM Multi-Region Atlas (FRAME_PIPELINE)** | **209.4** | 201.2 | 209.4 | 5.405 s | 36.4% | 32.1% | 24.2% | 27.6% |
| **TEST D** | **TeleM Multi-Region Atlas (PRODUCTION_TOTAL)** | **174.6** | 166.3 | 174.9 | 6.485 s | 36.4% | 32.1% | 24.2% | 27.6% |

---

## I. TeleM Efficiency % (Wskaźnik efektywności)

Wskaźnik efektywności potoku TeleM liczony względem sufitu sprzętowego (`BARE_TRANSCODE_FPS = 417.9 FPS`):

$$\text{TELEM\_EFFICIENCY}_{\text{pipeline}} = \frac{\text{TeleM FRAME\_PIPELINE FPS}}{\text{BARE\_TRANSCODE\_FPS}} \times 100\% = \frac{209.4}{417.9} \times 100\% = \mathbf{50.1\%}$$

$$\text{TELEM\_EFFICIENCY}_{\text{total}} = \frac{\text{TeleM PRODUCTION\_TOTAL FPS}}{\text{BARE\_TRANSCODE\_FPS}} \times 100\% = \frac{174.6}{417.9} \times 100\% = \mathbf{41.8\%}$$

Wskaźnik efektywności liczony względem sufitu filtrów CUDA (`TEST C = 332.0 FPS`):

$$\text{TELEM\_EFFICIENCY}_{\text{cuda\_ceiling}} = \frac{209.4}{332.0} \times 100\% = \mathbf{63.1\%}$$

**Klasyfikacja:**  
**`< 70%` — SIGNIFICANT SOFTWARE HEADROOM (Istotny potencjał programowy do dalszego wzrostu).**

---

## J. Dekompozycja strat wydajności (Overhead Breakdown)

Całkowita różnica między sprzętowym maksimum a realnym eksportem wynosi:
$$\Delta = 417.9\text{ FPS} - 174.6\text{ FPS} = \mathbf{243.3\text{ FPS}} \quad (+3.78\text{ s w czasie eksportu})$$

Dekompozycja na poszczególne warstwy:

```text
417.9 FPS  [BARE NVDEC -> NVENC CEILING]
   │
   ├── [1] Sprzętowy koszt filtrów CUDA (split + crop + scale 4K + 3x overlay_cuda)
   │       Strata: -85.9 FPS (+0.70 s) | 35.3% całkowitej luki
   ▼
332.0 FPS  [CUDA FILTER GRAPH CEILING (z NO-OP atlasem)]
   │
   ├── [2] Renderowanie wskaźników w Pillow (4 workery CPU) + IPC SharedMemory
   │       Strata: -122.6 FPS (+2.00 s) | 50.4% całkowitej luki  <-- GŁÓWNY BOTTLENECK
   ▼
209.4 FPS  [TeleM FRAME_PIPELINE FPS]
   │
   ├── [3] Narzut startowy i końcowy (Inicjalizacja workerów + First frame latency + Drain)
   │       Strata: -34.8 FPS (+1.08 s) | 14.3% całkowitej luki
   ▼
174.6 FPS  [TeleM PRODUCTION_TOTAL REAL EXPORT FPS]
```

---

## K. Identyfikacja aktualnego bottlenecku

1. **NVDEC i NVENC nie są bottleneckiem:**
   Wykorzystanie dekodera w TeleM wynosi zaledwie **36.4%**, a enkodera **32.1%** (wobec ~67% w bare transcode). Karta GPU oczekuje na ramki z procesora.
2. **Transport IPC / pipe:0 nie jest już bottleneckiem:**
   Dzięki Multi-Region Atlas z Etapu 4B, `ffmpeg_write` wynosi zaledwie **0.86 ms** (p95: **1.62 ms**), a SharedMemory zużywa tylko 22.7 MB.
3. **Głównym wąskim gardłem jest generowanie ramek HUD w Pythonie (Pillow):**
   - 4 workery generują klatki w średnim tempie ~19 ms per klatka na pojedynczym procesie CPU.
   - 4 workery pracujące równolegle dostarczają 1 klatkę co $\approx 4.77\text{ ms}$, co odpowiada przepustowości $\approx 209.4\text{ FPS}$.
   - FFmpeg konsumuje ramki natychmiast, ale musi czekać na zakończenie renderowania przez procesy Pythona.

---

## L. Potencjalny maksymalny dalszy zysk

- **Sufit dla renderera Pillow bez zmian w CUDA:** **332.0 FPS** (maksimum, jakie przyjmie kaskada 3 filtrów `overlay_cuda` na GPU).
- **Zysk przy optymalizacji renderera CPU:** z **209.4 FPS do 332.0 FPS (+58.5% FPS)**, skracając czas renderowania 1132 klatek z **5.41 s do 3.41 s (-2.00 s)**.
- **Sufit absolutny (gdyby overlay był nanoszony w 1 operacji GPU):** **417.9 FPS**.

---

## M. Podsumowanie i odpowiedzi na 4 pytania kluczowe

### 1. Jaki jest bare NVDEC → NVENC hardware throughput dla GX020079.mp4 na RTX 5070 Ti?
> **417.9 FPS** (czas: **2.71 s** dla całego 37.7-sekundowego materiału 4K 1132 klatek).

### 2. Jaki procent tego maksimum osiąga obecny TeleM FRAME_PIPELINE (~209-215 FPS)?
> **50.1%** sufitu bare transcode (oraz **63.1%** sufitu kaskady filtrów CUDA wynoszącego 332.0 FPS).

### 3. Czy dalsza szybka optymalizacja NVIDIA ma jeszcze sens?
> **TAK.** Istnieje nadal **122.6 FPS czystego headroomu programowego** (pomiędzy 209.4 FPS TeleM a 332.0 FPS filter graphu CUDA), a utylizacja NVDEC/NVENC wynosi zaledwie ~32–36%.

### 4. Wskaż JEDEN konkretny następny bottleneck o największym potencjale:
> **Rastrowanie i kompozycja wskaźników w Pillow (CPU per-frame render w workerach).**  
> Każdy worker rysuje pełny logiczny overlay 1920×1080 od zera na każdej klatce (wykresy, teksty, obrysy, paski). Zastosowanie **dirty-rect renderingu**, **cache'owania warstw statycznych** (np. tła wykresów, skale zegarów), **renderowania wskaźników bezpośrednio do wymiarów ich sub-regionów** (bez tworzenia pełnej klatki 1080p w pamięci PIL) lub szybszego rasteryzatora pozwoli natychmiast nasycić potok CUDA i zbliżyć TeleM do poziomu **300+ FPS**.

---
*ETAP 4C został zakończony. Nie wprowadzono żadnych zmian w kodzie produkcyjnym TeleM.*
