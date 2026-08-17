# NVIDIA NV3 — Production hardening ROT180 CUDA fast-path

Data: 2026-08-17 · Sprzęt: NVIDIA Quadro P400 2 GB · Materiał: GX020079.MP4 (3840×2160, 29.97 FPS, HEVC Main10, 1131 frames, container rotation −180°/180°)

NV2 potwierdzony w REAL GUI (~+7% FPS, ~13–14% lepszy ffmpeg_write, correctness OK) → **NV3 czyni CUDA ROT180 defaultem production** dla NVIDIA rotation=180.

---

## FILES MODIFIED

```
src/ffmpeg/command_builder.py   — is_nv_rot180_cuda: default ON (bez env); opt-out TELEM_NV_ROT180_CPU_FALLBACK
src/ffmpeg/streaming.py         — logi production [NVIDIA]; _inject_rot180_displaymatrix (rzuca błąd przy braku weryfikacji)
src/ffmpeg/displaymatrix.py     — hardening: bounds-checked atom walk, atomowy zapis (tmp+os.replace), obowiązkowa weryfikacja
tests/test_video_helpers.py     — testy NV3 (default/fallback/0/90/270/AMD/Intel + displaymatrix PASS/failure)
```

## DEFAULT NVIDIA ROT180
**CUDA** (bez żadnej zmiennej środowiskowej):
```
-hwaccel cuda -hwaccel_output_format cuda -noautorotate
[0:v]scale_cuda=format=yuv420p[base]
[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,hwupload_cuda[ov]
[base][ov]overlay_cuda=x=0:y=0[vtemp]
hevc_nvenc -pix_fmt cuda
- metadata rotate=180 (tag zapasowy) + displaymatrix rotate=180 injected & verified
HUD: compose → ROTATE_180 (Pillow, cały canvas 1920×1080) → CPU bilinear 4K → hwupload_cuda
```

## FALLBACK
`TELEM_NV_ROT180_CPU_FALLBACK=1` (opcjonalnie true/yes/on) wymusza stary CPU path (NIE usunięty):
```
-hwaccel cuda -noautorotate
[0:v]vflip,hflip[base]
[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear[ov]
[base][ov]overlay=0:0:shortest=1
hevc_nvenc -pix_fmt yuv420p
rotate=0
```
Fallback env unset/`""`/`"0"`/`"false"`/`"no"` → CUDA ROT180 (default ON).

Stary switch `TELEM_NV_ROT180_CUDA` nie jest już potrzebny (usunięty z logiki).

## DISPLAYMATRIX VALIDATION
`write_rotation_180_displaymatrix()` zahartowany:
- pełny bounds-checked walk atomów (moov → trak → tkhd + hdlr==`vide`);
- modyfikuje WYŁĄCZNIE właściwy video track (audio/pozostałe tracki nietknięte);
- `tkhd` matrix (36 B) musi mieścić się w boxie — inaczej kontrolowana porażka;
- **zapis atomowy**: temp plik w tym samym katalogu + `flush` + `os.fsync` + `os.replace` → błąd zapisu nie może uszkodzić outputu;
- **obowiązkowa weryfikacja po zapisie** (`verify_rotation_180_displaymatrix`): ponowne odczytanie i porównanie bajtów matrix z oczekiwanym [0,-1,0,0,0,-1,0,W,H];
- True zwracane tylko po potwierdzonej weryfikacji.

## FAILURE BEHAVIOR
- invalid/truncated MP4, brak/wrong video track, matrix overrun → `write_rotation_180_displaymatrix()` zwraca **False, plik nietknięty** (kontrolowana porażka).
- `streaming._inject_rot180_displaymatrix()` — jeżeli zapis/weryfikacja się nie powiedzie → **RuntimeError** → eksport propaguje błąd (`sig_error`), **NIE** jest zgłaszany jako Gotowe. Użytkownik nigdy nie dostaje fizycznie odwróconego pliku oznaczonego jako sukces.

## RUNTIME LOG (production)
- CUDA ROT180 (default): `[NVIDIA] ROT180 CUDA FAST PATH`
- wymuszony fallback: `[NVIDIA] ROT180 CPU FALLBACK`
- po weryfikacji: `[NVIDIA] displaymatrix rotate=180 injected and verified`
- brak nazwy eksperymentalnej „NV2" w normalnych logach.

## TESTS
```
tests/test_video_helpers.py: 30 passed
  NVIDIA rotation0    → CUDA normal path (unchanged)
  NVIDIA rotation180  → CUDA ROT180 default (no env)
  NVIDIA rotation180 + CPU_FALLBACK=1 → CPU old path
  NVIDIA rotation90   → CPU fallback
  NVIDIA rotation270  → CPU fallback
  AMD rotation180     → no NV2 (CPU chain)
  Intel rotation180   → no NV2 (CPU chain)
  displaymatrix valid MP4        → PASS (+verify)
  displaymatrix truncated MP4    → controlled failure, file untouched
  displaymatrix no video track   → controlled failure, file untouched
  injection failure              → controlled RuntimeError (never success)
pełny run:              158 passed, 4 skipped
```

## RAPORT (szablon)
```
FILES MODIFIED: command_builder.py, streaming.py, displaymatrix.py, tests/test_video_helpers.py
DEFAULT NVIDIA ROT180: CUDA
FALLBACK: TELEM_NV_ROT180_CPU_FALLBACK=1 -> CPU (vflip,hflip + software scale/overlay + yuv420p)
DISPLAYMATRIX VALIDATION: bounds-checked, atomowy zapis, obowiązkowa weryfikacja po zapisie
FAILURE BEHAVIOR: False + plik nietknięty (structure) / RuntimeError w streamingu (eksport = błąd, nie sukces)
TESTS: 30 passed (test_video_helpers), pełny run 158 passed / 4 skipped
AMD IMPACT: NONE
INTEL IMPACT: NONE
ROTATION 0: UNCHANGED
ROTATION 90/270: UNCHANGED
```

STOP — brak dalszej optymalizacji NVIDIA.
