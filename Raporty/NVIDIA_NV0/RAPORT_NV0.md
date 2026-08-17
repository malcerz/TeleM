
# NVIDIA ETAP NV0 — Pelny Raport Audytowy

**Data:** 2026-08-17  
**Sprzet:** NVIDIA Quadro P400 (GPU util ~69% avg, VRAM 2048 MiB)  
**Material referencyjny:** `GX020079.MP4` | 3840x2160 | HEVC Main10 | 29.97 FPS | **1131 klatek**

---

## 0. Weryfikacja baseline FPS

**27.15 FPS pochodzi z:** `1131 / time.perf_counter()` wall-clock (export_wall_seconds = 41.664 s)

```
exported_frames / export_wall_seconds = 1131 / 41.664258 = 27.1456 FPS
```

**NIE** pochodzi z media duration (media duration = 37.74 s -> 29.97 FPS).  
Match z stored true_fps: CONFIRMED.

> **UWAGA KRYTYCZNA:** `diagnose_nv0.py` przekazal `overlay_w=3840, overlay_h=2160`.  
> Produkcyjne GUI stosuje Smart Canvas Scaling: `max_overlay_w=1920` -> `ov_w=1920, ov_h=1080`.  
> NV0 baseline **mierzyl 4K HUD**, ktory NIE jest tym, co wykonuje produkcja.  
> Produkcja uzywa 1080p HUD + CPU scale 1080->4K w FFmpeg.  
> Mimo tej rozbieznosci 27.15 FPS pozostaje waznym punktem odniesienia dla tego testu.

---

## 1. Exact Production NVIDIA Pipeline

### Decode
- `-hwaccel cuda -hwaccel_output_format cuda` -> **NVDEC** (GPU decode)
- Wynik: frame w powierzchni CUDA (GPU memory), **0 kopii do CPU**

### Base scale
- `[0:v]scale_cuda=format=yuv420p[base]`
- **CUDA** (scale_cuda filtr GPU) — konwersja formatu na GPU, brak CPU
- resolution=source (3840x2160): scale_cuda jako format converter (bez resamplingu)

### HUD generation
- **CPU/Pillow** — `compose_overlay()` w process pool worker
- Canvas: **3840x2160** (diagnose_nv0) lub **1920x1080** (produkcja GUI)
- Wynik: PIL Image RGBA

### HUD native resolution
- **diagnose_nv0:** 3840x2160 (niepoprawne wzgledem GUI)
- **produkcja GUI:** 1920x1080 (Smart Canvas Scaling, `max_overlay_w=1920`)

### HUD transport
- **SharedMemory (SHM)** — `np.copyto(shm_arr, img_arr)` w workerze -> zero-copy
- `memoryview` z SHM przez `pipe_queue` -> writer thread -> `stdin.buffer.write()`

### HUD scaling

| Konfiguracja | stream_w | render_w | CPU scale |
|---|---|---|---|
| diagnose_nv0.py | 3840 | 3840 | **BRAK** |
| Produkcja GUI 4K | 1920 | 3840 | **TAK — FFmpeg CPU bilinear** |

**Produkcja GUI (4K output), overlay filter:**
```
[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,hwupload_cuda[ov]
```

**diagnose_nv0 (4K HUD, bez scale):**
```
[1:v]setpts=PTS-STARTPTS,format=rgba,hwupload_cuda[ov]
```

### hwupload_cuda
**YES** — `hwupload_cuda` uploaduje RGBA HUD frame na GPU (po CPU scale lub bezposrednio)

### overlay_cuda
**YES** — `[base][ov]overlay_cuda=x=0:y=0[vtemp]`  
Compositing bazowego frame (YUV420p CUDA) z HUD (RGBA CUDA) na GPU.

### Encode
`hevc_nvenc -preset p1 -tune hq -rc vbr -cq 24 -pix_fmt cuda -gpu 0 -b:v 40M`  
**NVENC** — sprzet GPU, frame pozostaje w GPU memory.

### Pelny filter_complex (diagnose_nv0)
```
[0:v]scale_cuda=format=yuv420p[base];
[1:v]setpts=PTS-STARTPTS,format=rgba,hwupload_cuda[ov];
[base][ov]overlay_cuda=x=0:y=0[vtemp];
[vtemp]null[vtemp2];
[vtemp2]null[vout]
```

### Pelny filter_complex (produkcja GUI, 4K)
```
[0:v]scale_cuda=format=yuv420p[base];
[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,hwupload_cuda[ov];
[base][ov]overlay_cuda=x=0:y=0[vtemp];
[vtemp]null[vtemp2];
[vtemp2]null[vout]
```

---

## 2. Hipoteza HUD CPU Upscale

**Odpowiedz: YES — w produkcji GUI.**

`render_mixin.py` L121-129:
```python
max_overlay_w = 1920
if w > max_overlay_w:   # w = 3840
    ov_w = max_overlay_w      # = 1920
    ov_h = int(1920 * 2160 / 3840)  # = 1080
```
-> `overlay_w=1920, overlay_h=1080` -> `stream_w=1920 != render_w=3840`  
-> command_builder wybiera **sciezke z CPU scale**

### Koszt CPU scale (zmierzony — bench_cpu_scale.py)
```
FFmpeg bilinear 1920x1080 RGBA -> 3840x2160 RGBA
Frames:       1131
Wall-clock:   60.71 s
Per-frame:    53.68 ms/frame
Ceiling FPS:  18.63 FPS
```

---

## 3. Analiza nvidia-smi

**Zrodlo:** `nvidia_samples.csv` — 38 probek @ ~1 Hz podczas FULL export (41.66 s)

| Metryka | avg | median | max |
|---|---|---|---|
| GPU util | 68.7% | 74.0% | 99% |
| VRAM used | 1838 MiB | — | 1903 MiB |
| VRAM total | 2048 MiB | — | 2048 MiB |
| VRAM % | 89.8% | — | 92.9% |
| encoder_util | UNKNOWN | — | — |
| decoder_util | UNKNOWN | — | — |
| temperature | UNKNOWN | — | — |
| clocks | UNKNOWN | — | — |

Diagnose_nv0.py odpytywal tylko `utilization.gpu,memory.total,memory.used`. Brak encoder/decoder util, temp i clockow w CSV.

**Obserwacje:**
- GPU util 68.7% avg — nierownomierne (1% do 99%) sugeruje backpressure od strony CPU
- VRAM ~90% — brak OOM, ale margines niewielki
- Wahania util zgodne z cyklem: HUD render CPU (GPU czeka) -> HUD upload+encode (GPU na 99%)

---

## 4. HUD CPU-Only Ceiling

**Test:** 1131 klatek, 3840x2160 RGBA, AppController layout (18 wskaznikow), single-threaded.

| Stage | avg | median | P95 | P99 |
|---|---|---|---|---|
| prepare_overlay_frame_data | 0.19 ms | 0.18 ms | 0.29 ms | 0.39 ms |
| compose_overlay (Pillow) | 8.81 ms | 8.56 ms | 10.84 ms | 13.34 ms |
| tobytes() 3840x2160 RGBA | 18.01 ms | 17.22 ms | 22.97 ms | 25.31 ms |
| **render_overlay_frame TOTAL** | **27.02 ms** | **26.28 ms** | **33.12 ms** | **37.77 ms** |

```
HUD-only wall: 30.56 s
HUD ceiling FPS: 37.01 FPS (single-threaded, 4K)
```

**tobytes() = 67% kosztu** HUD rendera — kopiuje 31.6 MiB RGBA per frame.  
W produkcji (SHM): tobytes zamienione na `np.copyto(shm_arr, img_arr)` — podobny koszt.

> Test przeprowadzony dla 4K HUD (diagnose_nv0 config, nie GUI).  
> Szacunek dla 1080p GUI: compose ~2.2 ms, tobytes ~4.5 ms, TOTAL ~7 ms -> ~145 FPS ceiling.

---

## 5. SHM / Pipe / Backpressure

### Konfiguracja (z kodu)

| Parametr | Wartosc |
|---|---|
| HUD dim (diagnose_nv0) | 3840x2160 |
| HUD dim (GUI prod) | 1920x1080 |
| RGBA bytes/frame (4K) | 33,177,600 = **31.6 MiB** |
| RGBA bytes/frame (1080p) | 8,294,400 = **7.9 MiB** |
| workers | max(1, cpu_count - 1) |
| SHM slots | MAX_IN_FLIGHT = max(4, workers*2) |
| pipe_queue maxsize | max(8, workers*2) |

### Pomiar (static overlay test, 4K RGBA — bench_static_overlay.py)

| Metryka | avg | median | P95 | P99 | max |
|---|---|---|---|---|---|
| stdin.write (4K RGBA, 31.6 MiB) | 25.72 ms | 24.80 ms | 29.85 ms | 34.27 ms | 553 ms |

**Przepustowosc pipe:** ~1229 MiB/s  
**Szacunek 1080p (7.9 MiB):** ~6.4 ms/write -> ~155 FPS pipe ceiling

> Pelny backpressure test (SHM acquire + queue.put instrumentacja) nie zostal uruchomiony
> (wymaga `if __name__ == '__main__':` guard — Windows multiprocessing).
> Dane ze static overlay testu wystarczaja do klasyfikacji.

### Werdykt backpressure

**Przy 4K HUD (diagnose_nv0):**
- stdin.write = 25.72 ms, HUD render = 27 ms — operacje rownoleglee
- Oba sa zblizone -> MIXED: HUD i PIPE sa oba limitujace
- GPU util 68.7% avg: GPU czeka na dane -> **A. producer (CPU) jest wolniejszy niz FFmpeg/GPU**

**Przy 1080p HUD (produkcja GUI):**
- stdin.write ~6.4 ms — szybkie
- FFmpeg CPU scale 53.68 ms/frame — **C. brak backpressure pipe, ale FFmpeg sam jest wolny**
- FFmpeg CPU scale jest wewnetrznym limitatorem FFmpeg (nie Python)

---

## 6. Base CUDA+NVENC Ceiling

**Test:** Ten sam input, 1131 frames, NVDEC + scale_cuda + NVENC, bez HUD pipe.

```
Wall-clock:  20.159 s
TRUE FPS:    56.10 FPS
vs FULL:     2.07x szybciej
```

GPU moze enkodowac 56 FPS. Pelny pipeline = 27.15 FPS -> overhead ~2x pochodzi z HUD+pipe.

---

## 7. Static Overlay

**Test:** Statyczny transparentny 3840x2160 RGBA frame pipowany 1131 razy.  
Identyczny filter_complex: scale_cuda + hwupload_cuda + overlay_cuda + NVENC.

| Metryka | Wartosc |
|---|---|
| Wall-clock | 29.374 s |
| TRUE FPS | **38.50 FPS** |
| stdin.write median | 24.80 ms/frame |

Pipe+GPU (bez CPU HUD) = 38.5 FPS. Koszt 4K RGBA pipe + hwupload + overlay_cuda + NVENC = ~26ms/frame.

---

## 8. Tabela rozliczenia

| Test | TRUE FPS | Wall-clock |
|---|---|---|
| **FULL production** (diagnose_nv0, 4K HUD) | **27.15 FPS** | **41.664 s** |
| BASE CUDA+NVENC (no HUD) | **56.10 FPS** | **20.16 s** |
| STATIC OVERLAY (GPU path, 4K) | **38.50 FPS** | **29.37 s** |
| HUD CPU-only ceiling (4K, single-thread) | **37.01 FPS** | **30.56 s** |
| HUD CPU-only (1080p, estimated) | **~145 FPS** | ~7.8 s |
| CPU RGBA UPSCALE (1080->4K bilinear) | **18.63 FPS** | **60.71 s** |

| Stage | Pomiar |
|---|---|
| CPU HUD render (4K) | **26.28 ms/frame** median |
| CPU HUD render (1080p, est.) | **~7 ms/frame** |
| tobytes / np.copyto (4K) | **17-18 ms/frame** |
| stdin.write (4K RGBA) | **24.80 ms/frame** median |
| stdin.write (1080p RGBA, est.) | **~6.4 ms/frame** |
| CPU scale 1080->4K bilinear | **53.68 ms/frame** |
| SHM acquire wait | BRAK POMIARU |

---

## 9. Bottleneck

### Werdykt: **CPU RGBA UPSCALE** (produkcja GUI) / **CPU HUD + PIPE** (diagnose_nv0)

| Czynnik | Koszt | Limit FPS |
|---|---|---|
| BASE GPU (NVDEC+scale_cuda+NVENC) | — | **56.10 FPS** |
| + 4K RGBA pipe + hwupload + overlay_cuda | +~18ms | **38.50 FPS** |
| + CPU HUD 4K render (diagn.) | +~27ms rownolegly | **27.15 FPS** |
| CPU bilinear scale 1080->4K (GUI prod) | **53.68ms** | **18.63 FPS ceiling** |

**W produkcji GUI:**
- HUD 1080p Pillow: ~7ms — OK
- stdin.write 1080p: ~6ms — OK
- **FFmpeg CPU bilinear scale 1080->4K: 53.68ms -> LIMITER** ❌
- NVDEC / scale_cuda / overlay_cuda / NVENC: GPU, szybkie

**W diagnose_nv0:**
- HUD 4K Pillow: 27ms (tobytes=18ms = 67%) — LIMITER
- stdin.write 4K: 25ms — LIMITER (rownolegly)
- Bez CPU scale
- GPU idle ~31% czasu (czeka na dane)

**Kategoria:** `CPU RGBA UPSCALE` (GUI prod) + `CPU HUD` i `PIPE` (diagnose_nv0)

**NVENC NIE jest limiterem** — baseline 56 FPS dowodzi zdolnosci GPU.

---

## 10. Kandydaci NV1

### NV1-A: GPU scale zamiast CPU bilinear (PRIMARY)

**Co:** Zmienic filter_complex dla 1080p HUD z:
```
format=rgba,scale=3840:2160:flags=bilinear,hwupload_cuda
```
na:
```
format=rgba,hwupload_cuda,scale_cuda=3840:2160
```
Wymaga weryfikacji czy `scale_cuda` akceptuje RGBA format i czy `overlay_cuda` akceptuje overlay innego rozmiaru niz base — jesli nie, overlay musi byc skalowany do 4K przed compositing.

**Expected gain:** -53ms/frame CPU scale -> +15-25 FPS  
**Risk:** SREDNI — overlay_cuda ograniczenia formatow/rozmiarow  
**Files:** `src/ffmpeg/command_builder.py` (L351-354)  
**Correctness risk:** SREDNI — wymaga visual A/B

---

### NV1-B: Usun limit max_overlay_w=1920 (prostsze, mniejszy gain)

**Co:** Ustaw `max_overlay_w = render_w` w `render_mixin.py` L123.  
HUD renderowany na 4K, bez CPU scale. Pipe przenosi 31.6 MiB/frame zamiast 7.9 MiB.

**Expected gain:** Eliminacja 54ms CPU scale, ale +20ms HUD render i +18ms pipe.  
Netto: ~+16ms = ~27->~34 FPS (szacunek)  
**Risk:** NISKI — to co robi diagnose_nv0  
**Files:** `src/gui/qt/_mixins/render_mixin.py` (L123)  
**Correctness risk:** NISKI

---

### NV1-C: overlay_cuda z mniejszym overlay (bez scale)

**Co:** Sprawdzic czy `overlay_cuda` akceptuje 1080p RGBA overlay na 4K base bez scale  
(overlay_cuda moze pozwolac na overlay mniejszy niz frame — wtedy brak CPU scale, maly pipe).

**Expected gain:** Najlepsze z obu swiatow: maly pipe (7.9 MiB), brak CPU scale, GPU overlay  
**Risk:** WYSOKI — overlay_cuda API moze wymagac matching resolution  
**Files:** `src/ffmpeg/command_builder.py`  
**Correctness risk:** WYSOKI — wymaga weryfikacji ffmpeg overlay_cuda docs + visual test

---

## Odpowiedzi koncowe

| # | Pytanie | Odpowiedz |
|---|---|---|
| 1 | FULL TRUE FPS? | **27.15 FPS** (1131 / 41.664s, time.perf_counter) |
| 2 | BASE CUDA+NVENC ceiling? | **56.10 FPS** (20.16s, bez HUD) |
| 3 | Ile kosztuje CPU HUD? | **26.28 ms/frame** median (4K); ~7 ms/frame (1080p) |
| 4 | HUD skalowany 1080p->4K na CPU? | **TAK** w produkcji GUI; NIE w diagnose_nv0 |
| 5 | Koszt CPU scale? | **53.68 ms/frame** (FFmpeg bilinear 1080->4K, ceiling 18.63 FPS) |
| 6 | Ile danych/frame Python->FFmpeg? | **31.6 MiB/frame** (4K, diagnose_nv0); **7.9 MiB/frame** (1080p, GUI) |
| 7 | Pipe/backpressure? | **TAK przy 4K** (stdin.write 25ms ~= HUD 27ms, GPU czeka 31%); przy 1080p prod: FFmpeg CPU scale jest limiterem |
| 8 | NVENC jest limiterem? | **NIE** — BASE 56 FPS dowodzi zdolnosci NVENC |
| 9 | Najwiekszy bottleneck? | **CPU RGBA UPSCALE** (54ms, prod GUI) / **CPU HUD+PIPE** (27+25ms, diagnose_nv0) |
| 10 | Pierwsza NV1? | **NV1-A: GPU scale (scale_cuda zamiast CPU bilinear w filter_complex)** |

---

## Artefakty

| Plik | Opis |
|---|---|
| `summary.json` | Wyniki FULL export |
| `ffmpeg_cmd.txt` | Komenda FFmpeg (diagnose_nv0) |
| `nvidia_samples.csv` | GPU utilization samples |
| `bench_hud_cpu.json` | HUD CPU-only benchmark (4K) |
| `bench_base_cuda_nvenc.json` | BASE CUDA+NVENC ceiling |
| `bench_static_overlay.json` | Static overlay + stdin.write timing |
| `bench_cpu_scale.json` | CPU bilinear scale cost |
| `scratch/nv0/bench_hud_cpu.py` | Skrypt HUD CPU benchmark |
| `scratch/nv0/bench_base_cuda_nvenc.py` | Skrypt BASE ceiling |
| `scratch/nv0/bench_static_overlay.py` | Skrypt static overlay |
| `scratch/nv0/bench_cpu_scale.py` | Skrypt CPU scale |

---

*Raport: Antigravity agent — ETAP NV0 COMPLETE. Nie wykonywac NV1 bez review.*
