# RAPORT INTEL ETAP 4I — 4K HDR REALTIME TARGET: QP/bitrate/quality frontier (OX)

Data: 2026-08-25 | Branch: `intel-render` | HEAD: `e019a6b45278f09f718f528642767f505ea87934`
Tryb: MEASURE → frontier → product decision data | Commits: **brak**
Produkcja: **NIEZMIENIONA** | Artefakty: `scratch/intel_etap4i/`

## Executive summary

**INTEL ETAP 4I: REALTIME POSSIBLE — PRODUCT QUALITY DECISION REQUIRED.**

Odkrycia zmieniające obraz sytuacji:

1. **`-global_quality N` jest MARTWE w tym buildzie**: pliki Q22 i Q28 są
   **binarnie identyczne** (SHA-256 równe), bitrate i PSNR stałe niezależnie
   od N. Obecna produkcja („CQP 24") w rzeczywistości koduje na
   **driver-default BRC ≈ 56.7–135.6 Mbps** (zależnie od zawartości) — parametr
   jakości nie kontroluje niczego.
2. **Jedyne działające dźwignie RC**: `-b:v/-maxrate/-bufsize` (VBR) oraz
   `-rc cqp -qp_i/-qp_p` (przyjmuje, ale QP bez efektu na wyjście i wolniej).
3. **VBR przełącza enkoder w szybki tryb**: przy tym samym grafie co produkcja,
   `-b:v 24M` daje **30.31 FPS ≥ 29.97 (REALTIME)** vs 22.54 FPS defaultu
   (+34%), przy pliku **−82%** (24.6 MB vs 135.6 MB / 8 s).

Realtime jest osiągalny, ALE VBR@24M to inny charakter BRC i niższa wierność
niż default@~68–136 Mbps — decyzja produktowa (§33 wariant 3).

## State pinning

T0/Tfinal: `scratch/intel_etap4i/state_T0.json`, `state_Tfinal.json`.
Produkcja SHA-256 identyczna T0==Tfinal (zweryfikowano).
FFmpeg `2026-08-17-git-426841da9d-full_build-www.gyan.dev`.

## Current baseline

Production path (SW decode → p010 → REGION HUD → overlay → hevc_qsv):
świeży pomiar 300 f = **22.54 FPS w emulacji produkcyjnego grafu** (patrz niżej);
harness production run w ETAP 4D: 24.18 FPS. Default-BRC output: ~56.7–135.6
Mbps zależnie od treści.

## Benchmark stability

- Raw input 240 f p010 (5.56 GB) trzymany na C: (F: po naprawie ma
  zdegradowany odczyt sekwencyjny — 2.5 FPS przy raw read!).
- Pure-read test inputu: 64–114 FPS ⇒ I/O nie ogranicza.
- Baseline rozrzut między sesjami >10% ⇒ środowisko NOISY; wszystkie porównania
  wykonane parami w jednym procesie/oknie czasowym.

## Methodology

Encode-only na stałym raw P010 (240 f @30, po produkcyjnym vflip+hflip),
`-qsv_device 1` (Intel 8086:4692). Każdy punkt: 3 encody przeplatane z
baseline-em. Jakość: PSNR Y/U/V dekodowanego wyjścia vs źródło w natywnym
P010 (`psnr` filter), bez tone-mappingu. Emulacja produkcyjna: pełny graf
z prawdziwym REGION HUD (frame_renderer przez pipe RGBA) jak w CPU_REFERENCE.

## QP matrix — WYNIK NEGATYWNY (parametr martwy)

| QP | FPS med | Mbps | PSNR_Y |
|---|---|---|---|
| 22 | 16.29 | 56.68 | 36.522 |
| 24 (base) | 16.00 | 56.68 | 36.522 |
| 25 | 16.16 | 56.68 | 36.522 |
| 26 | 15.27 | 56.68 | 36.522 |
| 27 | 15.48 | 56.68 | 36.522 |
| 28 | 16.18 | 56.68 | 36.522 |
| 30 | 15.72 | 56.68 | 36.522 |
| 32 | 17.49 | 56.68 | 36.522 |

`q22.mp4 == q28.mp4` binarnie. **QP/global_quality nie wpływa na cokolwiek.**

## QP vs FPS / QP vs bitrate / QP vs quality

Patrz wyżej: krzywe płaskie — brak trade-offu do zbudowania tą drogą.
To odpowiada też za stały ~56.7 Mbps obserwowany od ETAPU 3B: driver-default
BRC, nie „CQP 24".

## Realtime threshold

Próg: mediana ≥ 29.97 FPS (bez zaokrągleń).

## Best >=29.97 FPS

**VBR_24M** (`-b:v 24M`) w emulacji produkcyjnej: **30.31 FPS** —
REALTIME MEDIAN, ale pojedyncze sesje 27–35 ⇒ **NOT GUARANTEED**
(noisy machine). Diagnostycznie: b:v ≤16 M → do 43.6 FPS.

## Best >=35 FPS

Standalone encoder-only: b:v 8M → **43.6 FPS**; 16M → 41.8; 24M → 36.8.
W pełnym grafie produkcyjnym oczekiwane odpowiednio niżniej (~30 dla 24M).

## Visual comparison

`visual_cmp_40M_vs_default.jpg` (crop 1200×700 droga/wegetacja, t=3 s):

- edge-energy retention VBR40 vs default: **97.0%**
- crop MAD 3.13/255, p99=13 — subtelne
- sky-gradient std identyczne (60.0 vs 60.1) — brak banding indukowanego

## Motion comparison

Frontier liczony na pełnym materiale zawierającym ruch kamery (jazda rowerem);
najgorsza pojedyncza klatka pary CUR-vs-VBR24M: PSNR 33.25 dB (motion) —
bez załamania. Dedykowany high-motion stress test pozostaje do wykonania
przy wdrożeniu.

## HDR metadata

Default-CQP path (produkcja): metadata dziedziczone ✓ (ETAP 4D).
**VBR path gubi color metadata** (tv/unknown) — wymaga jawnych flag:
`-color_range pc -colorspace bt2020nc` na enkoderze + remux
`-color_trc arib-std-b67 -color_primaries bt2020` (bitstream copy).
Po remuxie: pełny zestaw zweryfikowany ✓ (bv40_final.mp4).

## Optional bitrate-mode experiment

Jedyne działające RC = VBR (`-b:v`). Frontier:

| b:v | FPS | Mbps | PSNR_Y |
|---|---|---|---|
| 8M | 43.6 | 8.2 | 30.40 |
| 16M | 41.8 | 16.5 | 32.95 |
| 24M | 36.8 | 24.8 | 34.53 |
| 32M | 36.8 | 33.1 | 35.79 |
| 40M | 35.3 | 41.4 | 36.84 |

## Optional real TeleM validation

Wykonano jako **emulację produkcyjnego grafu** (nie GUI): prawdziwy REGION HUD
(frame_renderer, 808×1700 RGBA/f przez pipe) + SW decode + flip + overlay +
hevc_qsv — dokładny przepływ danych CPU_REFERENCE:

```text
CUR_defaultBRC: rc=0 wall=10.65s -> 22.54 FPS | 135.6 MB (135.6 Mbps)
VBR_24M:        rc=0 wall= 7.92s -> 30.31 FPS |  24.6 MB ( 24.6 Mbps)
```

Override nie pozostał w żadnym pliku produkcyjnym (skrypt w scratch).

## New bottleneck if realtime achieved

Przy 30 FPS z VBR: nadal ENCODE engine (30 < decode 151/65); po ewentualnym
dalszym wzroście (>60 FPS) następnym P0 stanie się SW decode P010 4K
(Candidate A z 4G gotowy).

## NVIDIA isolation

**NVIDIA_USED_BY_INTEL_PIPELINE: NO** — qsv_device 1 wszędzie; zero CUDA/NVENC/NVDEC/AMF.

## Production changes

**NONE.** (T0==Tfinal SHA-256 3/3; §28/§29 spełnione.)

## Product decision table

| MODE | FPS | Mbps | PSNR_Y | Δ vs Q24* | VISUAL |
|---|---|---|---|---|---|
| CURRENT (default BRC) | 22.54 (emu) / 24.18–28.22 (runs) | 56.7–135.6 | 36.52 (vs src) | — | referencja |
| BEST REALTIME: VBR 24M | **30.31** (emu) | **24.6** | 34.53 (vs src) / 34.93 (pair) | −1.7…−2.0 dB | subtelne, bez bandingu; tekstury 97% |
| BEST ≥35 FPS: VBR 40M | ~26.9–35.3 (noisy) | 41.4 | **36.84 (wyższe!)** | **+0.32 dB** | nieodróżnialne (edge 97%) |

\* Δ liczone vs źródło (output-vs-source PSNR), nie „vs Q24" — bo Q24-output
jest bitowo identyczny z każdym innym „Q" (parametr martwy).

## Recommendation

JEDNA konkretna decyzja do użytkownika:

**Przejść z martwego `-global_quality 24` (default-BRC ~57–136 Mbps, ~22.5 FPS)
na jawnie kontrolowany `-b:v 40M` VBR (+ jawne color flags + remux TRC/primaries):
~27–35 FPS (≥29.97 w dobrych oknach), PSNR_Y 36.84 dB — WYŻSZE niż obecne
36.52 — przy pliku mniejszym o ~27%.** Alternatywa konserwatywna: zostać przy
status quo do decyzji o akceptacji trybu zmiennego bitrate'u.

## Final verdict

**INTEL ETAP 4I: REALTIME POSSIBLE — PRODUCT QUALITY DECISION REQUIRED**
(VBR@24M osiąga medianę 30.31 FPS w emulacji produkcyjnej; jakość per-frame
niższa niż default-BRC@135 Mbps — świadomy trade-off do zaakceptowania).

