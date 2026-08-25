# NVIDIA NV2 — ROTATION 180 CUDA FAST PATH — PoC / ETAP EKSPERYMENTALNY

Data: 2026-08-17 · Sprzęt: **NVIDIA Quadro P400 2 GB** (driver 577.12)
Materiał: **GX020079.MP4** — 3840×2160, 29.97 FPS, HEVC Main10, **1131 frames**, container displaymatrix **−180° (180°)**.

**STATUS: PARTIAL** (PoC + implementacja DONE; REAL GUI A/B wykonuje użytkownik ręcznie — patrz `NV2_REAL_GUI_AB.md`).

---

## BRAMKA 1 — AUDYT KODU

```
HUD FINALIZATION POINT:
  src/ffmpeg/frame_renderer.py::render_overlay_frame() -> compose_overlay()
  zwraca finalny HUD Image 1920x1080 RGBA (else branch, brak atlas dla nv);
  dalej render_frame_bytes_job / render_frame_shm_job -> .tobytes() -> SHM/pipe.
  Najlepsze miejsce opcjonalnego rotate180 = koniec render_overlay_frame()
  (przed .tobytes()). Zaimplementowano dokładnie tam (WORKER_CACHE["hud_rotate_180"]).

ROTATION DECISION:
  src/ffmpeg/streaming.py (linia ~330):
      needs_cpu_rotation = rotation_degrees in (90, 180, 270)
  src/ffmpeg/command_builder.py (linia ~281): identyczne wyrażenie.
  effective_rotation = container_rotation if container_rotation != 0 else rotation_degrees.
  Dla GX020079: container_rotation=180 -> effective_rotation=180.

CUDA BRANCH:
  command_builder.py: if encoder=="nv" and not needs_cpu_rotation: ->
      scale_cuda / hwupload_cuda / overlay_cuda / -pix_fmt cuda
  streaming.py: dodaje -hwaccel_output_format cuda tylko gdy not needs_cpu_rotation.
  needs_cpu_rotation=True (obecnie 180) BLOKUJE cały CUDA branch.

OUTPUT ROTATION METADATA:
  command_builder.py pisał: -map_metadata -1 -metadata:s:v:0 rotate=0.
  USTALENIE BRAMKI 2: ten FFmpeg (2023-06-26) NIE zapisuje rotate tag ani
  displaymatrix z -metadata; overlay_cuda GUBI source displaymatrix.

FILES NEEDED:
  src/ffmpeg/command_builder.py, streaming.py, worker_cache.py,
  frame_renderer.py, NOWY src/ffmpeg/displaymatrix.py, tests/test_video_helpers.py
```

## BRAMKA 2 — METADATA POC

Metoda zweryfikowana lokalnym FFmpeg (2023-06-26, gyan.dev):

- `-metadata:s:v:0 rotate=180` → **NIE tworzy** displaymatrix (movenc porzuca tag; brak `side_data_list`, brak tagu).
- `-display_rotation` → w tej wersji jest **tylko input-side**; jako output option rzuca błąd, jako input nie zapisuje matrix w output.
- Source displaymatrix **przeżywa** transcode bez filtrów (NVDEC→NVENC) oraz `scale_cuda` (pojedynczy `-vf`), ale jest **gubiony przez `overlay_cuda`** (filter_complex multi-input).
- **Rozwiązanie:** wstrzyknięcie displaymatrix bezpośrednio do pola matrix wideo tracka `tkhd` (36 bajtów, in-place, bez re-encode). Bajty dokładnie takie, jakie pisze sam movenc dla rotation 180 (potwierdzone vs `-display_rotation` transcode i source GoPro):
  `[0, -1.0, 0, 0, 0, -1.0, 0, W, H]` (16.16 fixed point).
- Nowy moduł: **`src/ffmpeg/displaymatrix.py`** (`write_rotation_180_displaymatrix`).

### ffprobe (output PoC po wstrzyknięciu)
```
side_data_list: [ { "side_data_type": "Display Matrix", "rotation": -180 } ]
```
→ prawdziwy **Display Matrix / rotation 180**, nie tekstowy tag.

### Playery
- **MPV (TeleM, libmpv-2.dll):** `video-params/rotate = 180`; screenshot renderuje poprawnie (wideo + HUD prawidłowo zorientowane). **PASS**
- **Drugi player (Windows Media Player):** extension `Microsoft.HEVCVideoExtension` zainstalowany, ale `wmplayer.exe` to deprecated stub — headless nie da się zweryfikować renderowania. Probe Media Foundation wykazał, że NV2 output jest **nieodróżnialny od source GoPro** (ten sam brak `MF_MT_VIDEO_ROTATION` na media type; source gra wszędzie poprawnie). **NIEZWERYFIKOWANY headlessly → użytkownik sprawdza w VLC / Films&TV wg `NV2_REAL_GUI_AB.md`.**

## BRAMKA 3 — HUD ROTATE COST

Metoda: `Image.Transpose.ROTATE_180` na **realnych** klatkach HUD 1920×1080 RGBA z production `render_overlay_frame` (realne GPMF + FIT, layout `def_layout.json`, 500 klatek).

| metryka | wartość |
|---|---|
| resolution | 1920×1080 RGBA |
| median | **3.743 ms** |
| P95 | **4.950 ms** |
| P99 | **5.498 ms** |
| min / max | 3.131 / 6.850 ms |
| pixel-exact permutation (ROTATE_180 ×2 == id) | **YES** |

Koszt ~3.7–5.5 ms/klatkę — niewielki vs budżet klatki 29.97 FPS (~33 ms) i vs eliminowane CPU vflip/hflip + CPU scale + CPU overlay 4K.

## BRAMKA 4 — IMPLEMENTACJA (`TELEM_NV_ROT180_CUDA`)

> **BUGFIX (2026-08-17, po REAL GUI):** switch zahartowany — OFF jest bezwarunkowym
> defaultem. Env unset / `""` / `"0"` / `"false"` / `"no"` → **OFF**; tylko `"1"`
> (opcjonalnie `"true"/"yes"/"on"`, case/whitespace-insensitive) → **ON**.
> W OFF nie ma logu `[NV2]` ani injection. Log przy ON: `[NV2] ROT180 CUDA FAST PATH: ON`.
> Zaobserwowane wcześniejsze aktywowanie NV2 bez świeżo ustawionej zmiennej wynikało
> z utrzymywania się `$env:TELEM_NV_ROT180_CUDA="1"` w terminalu GUI (efekt poprzedniego
> eksperymentu) — patrz ostrzeżenie w `NV2_REAL_GUI_AB.md`.

NVIDIA-only eksperymentalny override, **default OFF**. OFF = production bez zmian (potwierdzone testami). ON działa wyłącznie dla `encoder=="nv"` i `effective_rotation==180`; 0° bez zmian; 90°/270° pozostają CPU fallback.

Zmiany:
- `src/ffmpeg/command_builder.py` — helper `is_nv_rot180_cuda()`; w NV2 `needs_cpu_rotation=False`; output `-metadata:s:v:0 rotate=180` (tag zapasowy; właściwa rotacja z injection).
- `src/ffmpeg/streaming.py` — `nv_rot180_cuda`; `-hwaccel_output_format cuda` przywrócone; `hud_rotate_180` do workerów (SHM init_args + init_worker); log `[NV2] ...`; po zakończeniu eksportu **injection** displaymatrix (in-place).
- `src/ffmpeg/worker_cache.py` — nowy parametr `hud_rotate_180`.
- `src/ffmpeg/frame_renderer.py` — w `render_overlay_frame` (ścieżka streaming) opcjonalny `ROTATE_180` całego HUD canvas przed `.tobytes()`.
- `src/ffmpeg/displaymatrix.py` — **NOWY** moduł wstrzykiwania displaymatrix rotate=180.
- `tests/test_video_helpers.py` — 5 nowych testów NV2 + test displaymatrix. **14/14 przejść.**

### Realny command NV2 (production builder, potwierdzony)
```
-hwaccel cuda -hwaccel_output_format cuda -noautorotate -i GX020079.MP4
[0:v]scale_cuda=format=yuv420p[base]
[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,hwupload_cuda[ov]
[base][ov]overlay_cuda=x=0:y=0[vtemp]
hevc_nvenc -pix_fmt cuda
+ displaymatrix rotate=180 (injection post-step)
```
Base video: **NIE** fizycznie obracany (scale_cuda). HUD: logical 1920×1080 → ROTATE_180 w Pythonie → CPU bilinear do 4K → `hwupload_cuda` → `overlay_cuda`. Player obraca cały composite o 180° → wideo i HUD poprawne.

---

## RAPORT (wg szablonu)

```
STATUS: PARTIAL (PoC + kod PASS; REAL GUI TRUE FPS czeka na użytkownika)

REFERENCE PIPELINE (OFF):
  (hwaccel cuda bez output_format) -> CPU vflip,hflip 4K -> CPU scale lanczos
  -> CPU overlay 4K RGBA -> hevc_nvenc -pix_fmt yuv420p -> rotate=0
NV2 PIPELINE (ON):
  NVDEC -> CUDA -> scale_cuda (base, bez obrotu) -> HUD 1920x1080 ROTATE_180
  (CPU, Pillow) -> CPU bilinear 4K -> hwupload_cuda -> overlay_cuda
  -> hevc_nvenc -pix_fmt cuda -> displaymatrix rotate=180 (injected)

METADATA:
  method: in-place tkhd displaymatrix injection (src.ffmpeg.displaymatrix)
  ffprobe: side_data_list rotation=-180 (Display Matrix) PASS
  MPV:     PASS (video-params/rotate=180, rendering poprawny)
  second player: WMP headlessly NIEZWERYFIKOWANY (deprecated stub; MF traktuje
  output identycznie jak source GoPro) -> user verifies (VLC/Films&TV)

HUD ROTATE:
  method: Image.Transpose.ROTATE_180 (Pillow)
  resolution: 1920x1080
  median: 3.743 ms
  P95:    4.950 ms
  P99:    5.498 ms
  pixel-exact permutation: YES

CUDA:
  hwaccel_output_format cuda: YES
  scale_cuda base:            YES
  base hwdownload:            NO
  hwupload_cuda HUD:          YES
  overlay_cuda:               YES
  NVENC pix_fmt cuda:         YES

CORRECTNESS (PoC-level):
  frames: 120/120 (PoC 4s) — pełne 1131/1131 czeka na REAL GUI
  drops: 0 (PoC)
  audio: YES (kopiowany)
  video orientation: PASS (po display rotation; nv2_phys==rotate180(nv2_auto) MAE=0.0)
  HUD orientation:   PASS (screenshot MPV: HUD ustawiony logicznie)
  HUD positions:     PASS (PoC synthetic HUD; pełny layout -> REAL GUI)
  map/charts/gauge:  n/d (PoC) -> REAL GUI

PIXEL A/B (PoC):
  nv2_phys == rotate180(nv2_auto): MAE=0.0000 MAX=2.00 (czysta permutacja 180)
  src+logicalHUD vs nv2_auto: MAE=4.84 (różnica = timing klatki + skalowanie HUD PoC)
  pełny A/B klatki 30/300/900: użytkownik wg NV2_REAL_GUI_AB.md

PERFORMANCE:
  REFERENCE: ~33.5 FPS (baseline użytkownika)
  NV2 (PoC encode 4s, image2 loop input — NIE TRUE FPS): ~36 FPS indicative
  REAL GUI TRUE FPS: CZEKA NA UŻYTKOWNIKA
  gain: n/d do czasu REAL GUI
  ffmpeg_write avg/P95: n/d (Real GUI log)

MEMORY:
  VRAM: brak dodatkowych surfaces vs rotation=0 (brak wzrostu liczby GPU surfaces)
  RAM:  bez zmian
  SHM:  8 slotow × 8.29 MB (1920x1080x4) = ~66 MB — identycznie jak rotation=0
  OOM:  nie przewidziano; do potwierdzenia w REAL GUI (nvidia-smi)
```

---

## ODPOWIEDZI WPROST (stan po PoC + implementacji)

1. **Czy rotation=180 udało się utrzymać poza CPU base-video path?** — Tak, w trybie NV2: base przechodzi `scale_cuda` bez vflip/hflip; jedyna fizyczna rotacja CPU to HUD canvas 1920×1080.
2. **Czy base video pozostaje na CUDA od decode do NVENC?** — Tak: NVDEC → CUDA → scale_cuda → overlay_cuda → NVENC `-pix_fmt cuda`; brak hwdownload base.
3. **Czy jedyną fizyczną rotacją CPU jest mały HUD canvas?** — Tak (1920×1080, ~3.7 ms median).
4. **Czy metadata rotation działa w realnym MP4?** — Tak, przez wstrzyknięcie displaymatrix do `tkhd` (ffprobe `rotation=-180`); `-metadata:s:v:0` NIE działa w tym FFmpeg. MPV honoruje; WMP headlessly niezweryfikowany.
5. **Czy HUD po odtworzeniu jest prawidłowy?** — Tak (screenshot MPV PoC: wideo i HUD poprawne po display rotation).
6. **Czy layout jest identyczny?** — Tak przez konstrukcję (cały canvas 1920×1080 obracany, bez ręcznego przeliczania pozycji); pełne potwierdzenie w REAL GUI A/B.
7. **Jaki jest koszt rotate180 HUD?** — median 3.743 ms, P95 4.950 ms, P99 5.498 ms (pixel-exact).
8. **Jaki jest REAL GUI TRUE FPS?** — **CZEKA NA UŻYTKOWNIKA** (ręczny A/B).
9. **Jaki jest gain względem 33.5 FPS?** — **n/d** do czasu REAL GUI.
10. **Czy rozwiązanie nadaje się na production default?** — **NIE (jeszcze).** PoC + kod gotowe, ale TRUE FPS / correctness / metadata-in-all-players muszą zostać potwierdzone w REAL GUI A/B.
11. **Jeśli NIE — dlaczego?** — brak REAL GUI measurements; WMP/metadata w drugim playerze niezweryfikowane headlessly; eksperyment zgodnie ze spec (nie ustawiać default bez correctness gates).

---

## ZAKRES / OCHRONA

- AMD: **FROZEN** — nie dotknięto (`amd` branch bez zmian; test `test_nv_rot180_cuda_does_not_affect_amd`).
- Intel: **FROZEN** — bez zmian.
- 90°/270°: bez zmian (test potwierdza CPU fallback).
- Brak nowego FFmpeg, brak scale_npp, brak custom CUDA, brak Vulkan, brak filter_complex_threads sweep.
- Production default: **NIE ustawiony**.
