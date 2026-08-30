# RAPORT INTEL ETAP 4E — P010 CPU overlay fidelity + conversion audit (OX)

Data: 2026-08-25 | Branch: `intel-render` | HEAD: `e019a6b45278f09f718f528642767f505ea87934`
Tryb: audit → PoC → conditional implementation | Commits: **brak**
Artefakty: `scratch/intel_etap4e/` (state_T0.json, raw dowody PoC)

## Executive summary

**INTEL ETAP 4E: INVESTIGATED — NOT IMPLEMENTED.**

Root cause modyfikacji bazy poza HUD został ustalony faktograficznie (log
negocjacji FFmpeg): filter `overlay` przy alfa-blendingu wymusza przejście
**całej ramki** przez 8-bit `yuva420p`:

```text
auto_scale_1: p010le        -> yuva420p   (full-frame, 10→8 bit)
auto_scale_2: bgra          -> yuva420p   (overlay input)
[overlay blend in yuva420p]
auto_scale_3: yuva420p      -> p010le     (full-frame, 8→10 bit)
```

Fidelity-fix przez formaty jest **technicznie niemożliwy w tym buildzie**:
`overlay` obsługuje alfę wyłącznie w 8-bit — jawne `yuva420p10le` na wejściu
overlaya zostało i tak skonwertowane do `yuva420p` (zweryfikowane logiem).
Usunięcie defektu wymagałoby customowego 10-bit alpha compositora → §29 STOP.

Pomiar kosztu (§28): cały software overlay + konwersje = **1.7% wall**
(24.19 vs 24.60 FPS base-only @300f/4K) — overlay **nie jest istotnym P0**;
dominantą pozostaje SW decode P010 4K + hevc_qsv (slot_lifetime ~668 ms).

Zmiany produkcyjne: **brak** (8/8 plików identycznych z T0). Fallback
CPU_REFERENCE nietknięty i ponownie zweryfikowany.

## State pinning

T0: `scratch/intel_etap4e/state_T0.json` — branch `intel-render`,
HEAD `e019a6b…`, SHA-256 streaming.py/command_builder.py/test_video_helpers.py.
Working tree stabilny w trakcie audytu; brak obcych zmian.
FFmpeg: `2026-08-17-git-426841da9d-full_build-www.gyan.dev` (bez aktualizacji).

## Current production baseline

Realny materiał `Video/GX020079.MP4` (4K HEVC Main10 HLG BT.2020 pc,
container rotation=-180), CPU_REFERENCE + REGION:

```text
300 frames: wall 12.41 s -> 24.18 FPS | HUD REGION 3 400 992 B/f (ratio 0.103)
SW decode p010le | HWDownload NO | hevc_qsv p010le | metadata HDR zachowane
```

(pomiar z ETAPU 4D; niezależny pomiar CLI poniżej dał 24.19 FPS — spójne)

## Root cause audit

Patrz Executive summary + sekcja negocjacji. Dodatkowe fakty:

- `overlay` query-formats akceptuje main `yuv420p10le`, ale **alpha formats
  ograniczone do 8-bit YUVA** (`ffmpeg -pix_fmts` ma `yuva420p10le`, lecz
  filtr go nie negocjuje jako alpha input).
- Konwersje `p010le ↔ yuv420p10le` (shift 6 bitów) są bezstratne przy zerowych
  low-bits dekodera — problemem NIE są; problemem jest `→ yuva420p`.

## Actual FFmpeg format negotiation

Pełny ślad (`-loglevel verbose`) dla produkcyjnego kształtu grafu:

```text
graph input #0: yuv420p10le bt2020nc pc   (SW decode, 3840x2160)
graph input #1: bgra gbr pc               (HUD 800x600)
auto_scale_0: yuv420p10le -> p010le                 (alias/shift)
auto_scale_1: p010le      -> yuva420p               (FULL-FRAME 10->8)
auto_scale_2: bgra        -> yuva420p               (HUD)
overlay: blend w yuva420p (8-bit)
auto_scale_3: yuva420p    -> p010le                 (FULL-FRAME 8->10)
```

Kandydat B/C z jawnym `format=yuv420p10le[base]` + `format=yuva420p10le[ov]`:

```text
auto_scale_1: p010le       -> yuv420p10le           (shift, ok)
auto_scale_3: yuv420p10le  -> yuva420p              (NADAL full-frame 10->8!)
auto_scale_4: yuva420p10le -> yuva420p              (HUD też sprowadzony do 8-bit)
auto_scale_5: yuva420p     -> p010le                (full-frame 8->10)
```

## Candidate matrix

| Kand. | Working formats | Outside Y MAD (lvl10) | Outside UV MAD / max (lvl10) | HUD correctness | HDR meta | wall 300f | FPS | Verdict |
|---|---|---|---|---|---|---|---|---|
| A — current (RGBA→overlay) | p010→yuva420p→p010 | 1.25 (max 3) | U 3.53 / **120**, V **13.71 / 282**; 16.8% >2 lvl10 | OK (hue/alpha poprawne) | OK | 12.40 s CLI | 24.19 | baseline |
| B — explicit yuv420p10le base | +2 shift passes, dalej yuva420p 8-bit | jak A | jak A | OK | OK | (+1 pass → wolniej) | — | odrzucony (zero korzyści) |
| C — preconverted HUD yuva420p10le | HUD i tak → yuva420p 8-bit | jak A | jak A | OK | OK | — | — | odrzucony (filtr nie negocjuje 10-bit alfy) |
| D — explicit output format=p010le | końcowe p010le obecne; intermediate bez zmian | jak A | jak A | OK | OK | — | — | odrzucony (nic nie usuwa) |
| E — alternate blend path | brak filtra P010-alpha-aware w buildzie (overlay_qsv zdyskwalifikowany w 4D) | — | — | — | — | — | — | brak bezpiecznego kandydata |

Metryki outside-HUD dla A (klatka 0, region 800×600 @ (100,100)):

```text
Y OUTSIDE: MAD=80.08/64k (1.25 lvl10), max=192 (3 lvl10), nonzero 75.1%
U OUTSIDE: MAD=225.9 (3.53 lvl10), max=7680 (120 lvl10), >2 lvl10: 16.80%
V OUTSIDE: MAD=877.1 (13.71 lvl10), max=18048 (282 lvl10), >2 lvl10: 16.83%
```

Rozróżnienie §9: to NIE jest chroma-cell edge effect (dotyczy całej ramki,
nie krawędzi bboxa) — to **conversion-induced modification** (roundtrip
10→8→10 + swscale chroma path na pełnej ramce).

## Selected candidate

**NONE.**

## PoC commands

```text
REF:  ffmpeg -noautorotate -i GX -vf format=p010le,vflip,hflip -frames:v 2 -f rawvideo ref.raw
A:    ffmpeg -noautorotate -i GX -f lavfi -i "color=c=red@0.5:s=800x600:r=30000/1001:d=1,format=bgra"
      -filter_complex "[0:v]format=p010le,vflip,hflip[base];[base][1:v]overlay=100:100[v]"
      -frames:v 2 -pix_fmt p010le -f rawvideo a_pre.raw
NEG:  j.w. z -loglevel verbose (dowód negocjacji powyżej)
PERF: full-overlay vs base-only, 300 frames, hevc_qsv veryfast/global_quality 24
```

## Pre-encode parity

Wszystkie porównania fidelity wykonane **pre-encode** (rawvideo p010le),
żeby wyeliminować wpływ osobnych encodów (§22).

## HDR metadata

Na każdym etapie PoC zachowane: `pc / bt2020nc / arib-std-b67 / bt2020`
(log graph input oraz ffprobe outputów). Zero tone-mappingu (§11).

## Real TeleM HUD parity

REGION TeleM działa na obecnym grafie bez zmian — produkcja nietknięta
(baseline runtime z ETAPU 4D + potwierdzenie ścieżki w tym etapie).
Prosty pattern PoC potwierdził poprawne hue/alpha wewnątrz overlay (U↓/V↑ ku
czerwieni zgodnie z `red@0.5`).

## Production implementation

**NOT IMPLEMENTED.** Warunek §16 niespełniony z obu stron:
- fidelity clearly better — **niemożliwe** bez custom 10-bit compositora (§29 STOP),
- performance +5% — overlay to 1.7% wall; nie ma czego zbierać.

## Graph before / after

Before (= after — zero diff): patrz „Actual FFmpeg format negotiation".

## Performance before/after

| metric | CURRENT_BASELINE | SELECTED_CANDIDATE |
|---|---|---|
| effective FPS | 24.18–24.19 | n/a (brak kandydata) |
| wall time (300f) | 12.40–12.41 s | n/a |
| overlay cost share | **1.7%** wall | — |

## NVIDIA isolation

**NVIDIA_USED_BY_INTEL_PIPELINE: NO** — wszystkie testy CLI/harness pinują
Intel adapter (qsv_device 1); zero CUDA/NVENC/NVDEC.

## Regression tests

Focused suite: **60 passed** (test_video_helpers + intel_backend +
gpu_compositor + amd_native_overlay_handoff + etap5f_pipeline_audit).
Produkcja nietknięta — brak nowych testów wymaganych (§26 dotyczy wdrożeń).

## Changed files

Brak (produkcja 8/8 SHA-256 == T0; zweryfikowano programowo).
Nowe: raport + `scratch/intel_etap4e/*`.

## Preserved

AMD preserved | NVIDIA preserved | SDR native preserved |
CPU_REFERENCE preserved | telemetry preserved | multi-file preserved |
REGION preserved

## Remaining bottleneck

P0 pozostaje tor wideo CPU_REFERENCE: SW decode P010 4K + full-frame konwersje
+ hevc_qsv (slot_lifetime ~668 ms @4K HDR). Overlay = 1.7% — odnotowany jako
defekt jakościowy (V poza HUD do 282 lvl10), nie wydajnościowy.

## Recommendation

JEDEN następny krok: **etap badawczy 10-bit HUD compositing** — PoC
region-replace w 10-bit (crop base do bboxa → CPU blend z HUD w 10-bit →
wklejenie z powrotem) po stronie workera TeleM, cel:
`OUTSIDE_HUD_BASE_MODIFICATION = 0`. Wymaga decyzji architektury renderera
(§29) — nie nadaje się do autonomicznego wdrożenia w ramach optymalizacji.

## Final verdict

**INTEL ETAP 4E: INVESTIGATED — NOT IMPLEMENTED**
Powód: software `overlay` blenduje alfę wyłącznie przez 8-bit `yuva420p`
(negocjacja udokumentowana logiem); naprawa fidelity wymagałaby customowego
10-bit compositora (§29 STOP), a potencjalny zysk wydajnościowy jest pomijalny
(overlay = 1.7% wall).

