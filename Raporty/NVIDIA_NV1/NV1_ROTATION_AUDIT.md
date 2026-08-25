# NVIDIA NV1 — Audyt Rotacji (GX020079 / displaymatrix -180°)

Data: 2026-08-17
Sprzęt: NVIDIA Quadro P400 2 GB
Materiał: GX020079.MP4 — 3840×2160, 29.97 FPS, HEVC Main 10, 1131 klatek

---

## ODKRYCIE

Real GUI production run z TELEM_NV_FILTER_COMPLEX_THREADS=2 ujawnił,
że faktyczna komenda dla GX020079 NIE używa CUDA pipeline.

Rzeczywisty filter_complex (potwierdzony z logu):

    [0:v]vflip,hflip[base]
    [1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear[ov]
    [base][ov]overlay=0:0:shortest=1[vtemp]

Encoder: hevc_nvenc -pix_fmt yuv420p (nie -pix_fmt cuda)

Wcześniejsze założenie "NVDEC → scale_cuda → overlay_cuda → NVENC"
jest NIEPRAWDZIWE dla tego materiału.

---

## DANE WEJŚCIOWE

ffprobe side_data_list:

    {
      "side_data_type": "Display Matrix",
      "displaymatrix": "...",
      "rotation": -180
    }

Brak tagu "rotate" w stream_tags.
Rotacja zakodowana wyłącznie w displaymatrix (side_data_list).

---

## FLOW KODU — KROK PO KROKU

### 1. get_container_rotation() — src/telemetry_extract.py:1079

    side_data_list[0].rotation = -180
    return abs(int(float("-180"))) % 360 = abs(180) % 360 = 180

Wynik: container_rotation = 180

### 2. render_mixin.py:93-99

    container_rotation = 180  # != 0
    effective_rotation = 180
    container_rotation_arg = 180
    rotation_degrees = 180  # przekazane jako effective_rotation

### 3. streaming.py:330

    needs_cpu_rotation = rotation_degrees in (90, 180, 270)
    # 180 in (90, 180, 270) = True
    needs_cpu_rotation = True

### 4. streaming.py:337

    if hwaccel == "cuda" and encoder == "nv" and not needs_cpu_rotation:
    # not True = False → NIE dodaje -hwaccel_output_format cuda

### 5. command_builder.py:308

    if encoder == "nv" and not needs_cpu_rotation:
    # not True = False → BLOKUJE CUDA PATH

Ląduje w CPU branch (elif target_res):

    base_filter = "[0:v]scale={W}:{H}:flags=lanczos,vflip,hflip[base]"

Overlay CPU branch:

    ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear[ov]"
    overlay=0:0:shortest=1  (CPU overlay, bez hwupload_cuda)

### 6. Wynik

    -hwaccel cuda jest (detect_gpu_decoder zwraca "cuda")
    -hwaccel_output_format cuda BRAK
    scale_cuda BRAK
    hwupload_cuda BRAK
    overlay_cuda BRAK
    -pix_fmt yuv420p (nie cuda)

---

## ROTATION 0 vs ROTATION 180 — PORÓWNANIE

### ROTATION 0 (brak rotacji w materiale)

Input args:
    -hwaccel cuda
    -hwaccel_output_format cuda
    -i video.mp4

filter_complex:
    [0:v]scale_cuda=3840:2160:format=yuv420p[base]
    [1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,hwupload_cuda[ov]
    [base][ov]overlay_cuda=x=0:y=0[vtemp]

Encoder:
    hevc_nvenc -pix_fmt cuda

Pipeline: NVDEC → scale_cuda → overlay_cuda → NVENC (FULL GPU)

### ROTATION 180 (GX020079 — displaymatrix -180°)

Input args:
    -hwaccel cuda              ← jest, ale bez hwaccel_output_format cuda
    -noautorotate
    -i GX020079.MP4

filter_complex:
    [0:v]vflip,hflip[base]             ← CPU
    [1:v]...scale=3840:2160:bilinear[ov] ← CPU
    [base][ov]overlay=0:0:shortest=1   ← CPU

Encoder:
    hevc_nvenc -pix_fmt yuv420p   ← yuv420p (nie cuda)

Pipeline: (hwaccel cuda bez output_format) → CPU vflip/hflip → CPU scale → CPU overlay → NVENC

---

## WHY CUDA PATH DISABLED

Jedna zmienna boolean:

    needs_cpu_rotation = rotation_degrees in (90, 180, 270)

Blokuje jednocześnie:
- -hwaccel_output_format cuda
- scale_cuda
- hwupload_cuda
- overlay_cuda
- -pix_fmt cuda

Logika zaprojektowana głównie dla 90°/270° (transpose zmienia dimensje, vflip/hflip są CPU-only).
180° WŁĄCZONE do tej samej blokady mimo że:
- nie zmienia dimensji (W=3840, H=2160 przed i po)
- technicznie można obsłużyć bez CPU vflip/hflip

---

## CPU DOWNLOAD — ANALIZA

Oficjalna odpowiedź: UNKNOWN / PARTIAL

Szczegóły:
- -hwaccel cuda jest w cmd
- verbose pokazuje: "Selecting decoder 'hevc' because of requested hwaccel method cuda"
  ale stream mapping: "hevc (native)" zamiast "hevc (hevc_cuvid)"
- Dla HEVC Main 10 (p010le) FFmpeg z -hwaccel cuda wybiera natywny dekoder,
  ale zwraca frames jako pixfmt:cuda (implicit hwupload po native decode)
- vflip i hflip są BEZWZGLĘDNIE CPU-only → decoded frame MUSI być w system memory
  → jest implicit hwdownload (CUDA→CPU) zanim wejdzie w vflip/hflip
- Potwierdzenie: -pix_fmt yuv420p w NVENC = CPU→GPU upload na końcu przez NVENC

Efektywna ścieżka:
    NVDEC (lub native+cuda hybrid) → implicit hwdownload → vflip/hflip CPU
    → scale CPU → overlay CPU → NVENC (upload)

---

## LOCAL FFmpeg CUDA FILTERS

Dostępne:
    scale_cuda       YES
    overlay_cuda     YES
    hwupload_cuda    YES
    bwdif_cuda       YES
    bilateral_cuda   YES
    colorspace_cuda  YES
    thumbnail_cuda   YES

BRAK:
    vflip_cuda       NO
    hflip_cuda       NO
    transpose_cuda   NO

Vulkan (dostępny, niezależny hw device):
    vflip_vulkan     YES
    hflip_vulkan     YES
    flip_vulkan      YES  ← robi vflip+hflip w jednym passie
    transpose_vulkan YES

scale_cuda ujemne wymiary / flip: NIE — brak takiej opcji w AVOptions.
scale_cuda RGBA input: NIE (potwierdzono wcześniej w NV0).

---

## OPCJE GPU 180° DLA TEGO FFMPEG

### Opcja 1 — Metadata Passthrough (NAJNIŻSZE RYZYKO)

Nie aplikuj vflip/hflip w filter_complex.
Przepisz metadata rotate do outputu:

    -metadata:s:v:0 rotate=180

lub pozostaw displaymatrix przez -map_metadata.

Efekt: pełna CUDA pipeline (NVDEC → scale_cuda → overlay_cuda → NVENC).
Obraz w pliku wynikowym fizycznie "odwrócony", ale metadata mówi odtwarzaczowi żeby go obrócił.

Zysk: eliminacja wszystkich CPU copy/transform w video path.

Ryzyko:
- Odtwarzacze które ignorują rotate tag pokażą obraz odwrócony.
- Eksporterzy dalszego przetwarzania mogą ignorować metadata.
- Wymaga testu na VLC, QuickTime, Windows Media Player, YouTube.

Correctness gate: 1131/1131, drops=0, audio=YES, obraz poprawny w co najmniej 2 odtwarzaczach.

### Opcja 2 — flip_vulkan (ŚREDNIE RYZYKO)

    -init_hw_device vulkan=vk -filter_hw_device vk
    [0:v]hwupload,flip_vulkan,hwdownload,hwupload_cuda[base_flipped]
    [base_flipped]scale_cuda=...[base]

Zysk: physyczny flip na GPU, CUDA pipeline downstream.
Ryzyko:
- Nowe hw device (Vulkan) — brak testów produkcyjnych na Quadro P400.
- Dodatkowe memory transfers: CUDA→Vulkan→CUDA.
- Nieznana stabilność na tym hardware.

### Opcja 3 — Ignorowanie rotacji (RYZYKO semantyczne)

-noautorotate + brak vflip/hflip + brak metadata →
obraz w outputcie odwrócony bez metadanych, nieakceptowalne.

### Opcja 4 — CPU path pozostaje (STATUS QUO)

Aktualne ~33.5 FPS dla rotation=180.
Bez zmiany — safe, ale nieoptymalne.

---

## EXPECTED ARCHITECTURAL GAIN

Szacunek dla Opcji 1 (metadata passthrough):

Aktualna ścieżka:
    (CPU decode) → vflip/hflip CPU → scale lanczos CPU 3840×2160
    → overlay CPU 3840×2160 → hwupload NVENC → NVENC

Docelowa ścieżka:
    NVDEC → scale_cuda 3840×2160 → overlay_cuda → NVENC (-pix_fmt cuda)

Eliminowane operacje CPU:
    - CPU vflip + hflip na pełnym 4K frame (≈4 ms/frame szacunkowo)
    - CPU scale lanczos 4K (obecna ścieżka to bilinear, ale skala to koszt)
    - CPU overlay 4K RGBA (najcięższy element)

Baseline no-HUD (czyste NVDEC+NVENC): ~56.1 FPS
Real GUI ROTATION=0 baseline: NIEZNANE (do pomiaru)
Real GUI ROTATION=180 baseline (CURRENT): ~33.5 FPS

Expected architectural gain: HIGH

---

## PLIKI DO MODYFIKACJI (NIE IMPLEMENTOWANO)

src/ffmpeg/streaming.py
    Linia 330: needs_cpu_rotation — oddzielić logikę 90°/270° od 180° dla encoder==nv

src/ffmpeg/command_builder.py
    Linia 308: if encoder == "nv" and not needs_cpu_rotation: — dodać wariant dla 180°
    Sekcja base_filter (linia ~338): dla nv+180° użyć CUDA path + metadata

---

## PYTANIE DO UŻYTKOWNIKA (BLOCKER)

Przed implementacją wymagana decyzja semantyczna:

Czy wynik eksportu ma:

A) Metadata passthrough — plik wynikowy ma displaymatrix/rotate=180,
   obraz fizycznie odwrócony, odtwarzacze go obracają (jak oryginał GoPro).

B) Fizyczny obrót — obraz w pliku jest już poprawnie zorientowany,
   brak rotate metadata (jak robi obecna ścieżka CPU z vflip/hflip).

Opcja A = pełna CUDA ścieżka możliwa natychmiast.
Opcja B = wymaga flip na GPU (Vulkan ryzyko) lub CPU (status quo).

---

## STATUS

AUDYT: DONE
IMPLEMENTACJA: STOP — oczekuje decyzji użytkownika.
