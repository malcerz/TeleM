# RAPORT INTEL ETAP 4H — hevc_qsv performance/quality frontier + conditional tuning (OX)

Data: 2026-08-25 | Branch: `intel-render` | HEAD: `e019a6b45278f09f718f528642767f505ea87934`
Tryb: audit → benchmark matrix → quality analysis → conditional implementation
Commits: **brak** | Produkcja: **nietknięta**
Artefakty: `scratch/intel_etap4h/` (bench_matrix.py, matrix.json, matrix_log.txt,
enc_help.txt, control_f90.jpg, state_T0.json)

## Executive summary

**INTEL ETAP 4H: INVESTIGATED — NOT IMPLEMENTED.**

Empiryczna mapa `hevc_qsv` na realnym materiale (GX020079, 240 f P010,
identyczne wejście dla wszystkich wariantów) pokazała:

1. **Presety QSV są odwrócone względem x265**: `veryfast`(TU 7) jest
   NAJSZYBSZY — produkcja już używa najszybszego presetu. Wolniejsze presety
   = wolniej i minimalnie lepiej (PSNR +0.8–1.0 dB kosztem −30…−63% FPS).
2. **`low_power=on` (VDEnc) nie daje zysku** na UHD 730 dla HEVC 10-bit 4K:
   17.8 vs 17.4 FPS mediany, rozmiar wyjścia identyczny bajt-w-bajt.
3. **async_depth 2/4/8** — bez >=5% (spójne z ETAP 4G).
4. Żaden kandydat nie osiąga >=30 FPS ani nie spełnia gate'ów §26/§27.

UHD 730 ma twardy sufit ~17–24 FPS dla HEVC 10-bit 4K CQP24 w tych trybach.
`>=30 FPS` wymagałoby zmian jakościowych (QP/bitrate) → **PRODUCT DECISION**,
nie automatyczny tuning. Produkcja nietknięta.

## State pinning

T0/Tfinal: `scratch/intel_etap4h/state_T0.json` (branch/head/SHA-256).
FFmpeg `2026-08-17-git-426841da9d-full_build-www.gyan.dev`.
Uwaga środowiskowa: w trakcie etapu wolumen F: przeszedł awarię
(`Full Repair Needed`) — po powrocie odczyt F: zdegradowany; **raw input
benchmarków przeniesiono na dysk systemowy C:** (`C:\etap4h_tmp\enc_input.p010`,
240 klatek, 5.56 GB), aby pomiary encoder-only były stabilne.

## Active FFmpeg / hevc_qsv capabilities

`-h encoder=hevc_qsv` (pełny dump: `enc_help.txt`, 94 linie):

- presets: veryfast(7) faster(6) fast(5) medium(4) slow(3) slower(2) veryslow(1)
- `low_power` auto/on/off; `async_depth`; `rdo`; `extbrc`; `mbbrc`;
  `look_ahead_depth` (tylko z extbrc); `scenario` ×8; `avbr_accuracy/
  convergence`; `max/min_qp_i/p/b`; `adaptive_i/b`; `p_strategy/b_strategy`;
  `idr_interval`; `tile_cols/rows`; `skip_frame`; `dual_gfx` (HyperEncode);
  `low_delay_brc`; `forced_idr`; pix_fmts: nv12/p010le/p012le/yuyv422/y210le/
  qsv/bgra/x2rgb10le/vuyx/xv30le
- `-rc/-global_quality/-look_ahead/-gop/-bf/-refs` to opcje poziomu kodeka
  (AVCodecContext), niewidoczne w prywatnym helpie — działają (produkcja je
  używa). RC mode przy `global_quality` bez jawnego `-rc`: **CQP** (warning
  z logu, ETAP 4D).

## Current encoder configuration

```text
-c:v hevc_qsv -preset veryfast -global_quality 24 -look_ahead 0
-async_depth 4 -pix_fmt p010le   (CQP QP≈24)
```

## Baseline repeatability

veryfast_q24 ×3: FPS **13.01 / 17.38 / 17.91** → mediana 17.38, rozrzut >10%
⇒ oznaczono **noisy** (maszyna współdzielona + dysk F: po naprawie).
Bitrate stabilny: 56 684.6 kbps w każdym przebiegu (CQP deterministyczny).

## Benchmark methodology

240 klatek realnego GX020079 (P010, po vflip+hflip jak produkcja), input
rawvideo z C: (stały), encode-only (bez decode w pomiarze), `-qsv_device 1`,
3 przebiegi/wariant, mediana + min/max; jakość: PSNR Y/U/V dekodowanego
wyjścia vs źródło w natywnym P010 (`psnr` filter, 10-bit, bez tone-mappingu);
bitrate z rozmiaru mp4.

## Preset matrix

| preset | TU | FPS mediana | FPS range | bitrate kbps | PSNR_Y dB |
|---|---|---|---|---|---|
| **veryfast (prod.)** | 7 | **17.38** | 13.0–17.9 | 56 685 | 36.52 |
| faster | 6 | 11.31 | 9.5–11.4 | 59 724 | 37.34 |
| fast | 5 | 7.25 | 7.1–7.3 | 59 122 | 37.48 |
| medium | 4 | 6.48 | 6.3–6.6 | 59 413 | 37.51 |

Wniosek: veryfast dominuje (najszybszy i najmniejszy plik); wolniejsze presety
dają +0.8–1.0 dB za 2–2.7× wolniej. Kierunek "szybszy preset" nie istnieje.

## Low-power analysis

`-low_power 1` @ veryfast/CQP24: **16.67–18.11 FPS** (mediana 17.81) —
statystycznie identycznie z baseline; rozmiar wyjścia **identyczny**
(56 684 630 B) ⇒ VDEnc nie zmienia ścieżki jakości/prędkości na tym
GPU/driverze dla HEVC 10-bit 4K. Tryb działa (brak fallbacku/błędu), ale nie
przyspiesza.

## Rate-control matrix

Jawne tryby RC nie są wystawione opcją `-rc` w tym buildzie; kontrola przez
`global_quality`(CQP)/`b:v`. Alternatywne BRC (ICQ/LA_ICQ/QVBR) wymagają
qsv_params/extbrc — poza minimalnym PoC. Ponieważ preset i low_power nie dają
prędkości, RC-matrix nie zmienia werdyktu prędkości (ten sam silnik encode).

## Quality methodology

PSNR Y/U/V w natywnej P010 (10-bit, BT.2020/pc): dekod wyjścia vs źródło,
HDR-aware (brak konwersji przestrzeni). SSIM pominęto (filtr bez wsparcia
p010 w tym buildzie). Control frame: `control_f90.jpg` (t=3 s).

## Quality results

PSNR_Y: veryfast 36.52 → faster 37.34 → fast 37.48 → medium 37.51 dB.
Różnice małe; koszt prędkości ogromny (szczegóły: Preset matrix).

## Bitrate / size results

veryfast 56.7 Mbps < faster 59.7 ≈ fast 59.1 ≈ medium 59.4 Mbps.
low_power = bit-to-bit ten sam rozmiar co veryfast.

## Async-depth results

ETAP 4G probe (90f raw): ad2 ~23.1, ad4 ~24.0, ad8 ~24.0 FPS — brak >=5%.
Nie ponawiano szerzej (§13).

## Hardware utilization

Bez dedykowanego monitora util (§16 dopuszcza pominięcie). Sufit ~17–24 FPS
przy niskim CPU wskazuje na engine encode jako limit (spójne z ENCODE_BOUND).

## Candidate matrix

| candidate | preset | RC | quality | async | FPS med | range | bitrate kbps | PSNR_Y | HDR | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline (prod.) | veryfast | CQP 24 | gq24 | 4 | **17.38** | 13.0–17.9 | 56 685 | 36.52 | OK | baseline |
| faster Q24 | faster | CQP 24 | gq24 | 4 | 11.31 | 9.5–11.4 | 59 724 | 37.34 | OK | wolniejszy |
| fast Q24 | fast | CQP 24 | gq24 | 4 | 7.25 | 7.1–7.3 | 59 122 | 37.48 | OK | wolniejszy |
| medium Q24 | medium | CQP 24 | gq24 | 4 | 6.48 | 6.3–6.6 | 59 413 | 37.51 | OK | wolniejszy |
| low_power on | veryfast | CQP 24 | gq24 | 4 | 17.81 | 16.7–18.1 | 56 685 | =base | OK | brak zysku |
| async 2/8 | veryfast | CQP 24 | gq24 | 2/8 | — | — | — | — | OK | brak >=5% (4G) |

## Best quality-equivalent candidate

NONE — nie istnieje szybsza konfiguracja przy porównywalnej jakości.

## Best performance candidate

Baseline (veryfast/CQP24) — już maksimum prędkości dostępnych opcji.

## Product trade-off candidates

Wolniejsze presety: +~1 dB PSNR_Y kosztem −35…−63% FPS — odwrotny trade-off
niż szukany; jako opcja „export max quality" (medium, ~6.5 FPS) do osobnej
decyzji produktowej.

## Selected production candidate

**NONE.**

## Production implementation

**NOT IMPLEMENTED.**

## Real TeleM A/B

Nietknięta produkcja; świeże production runs w ETAP 4G: mediana 27.69 FPS
(14.55–28.22, noisy). Po przyszłej decyzji produktowej wymagany pełny
runtime A/B wg §28.

## New bottleneck

Gdyby enkoder przyspieszył, limitem stanie się SW decode P010 4K
(sufit 64.8 FPS) — wtedy wraca Candidate A z ETAPU 4G (QSV→system memory,
bit-exact, 151.5 FPS).

## NVIDIA isolation

**NVIDIA_USED_BY_INTEL_PIPELINE: NO** — wszystkie testy `-qsv_device 1`
(Intel adapter); zero CUDA/NVENC/NVDEC.

## Regression tests

Focused suite: **60 passed** (produkcja nietknięta; §30 testów nowych brak).

## Changed files

Brak zmian produkcyjnych. Nowe: raport + `scratch/intel_etap4h/*`
(bench_matrix.py, matrix.json, enc_help.txt, control_f90.jpg, state_T0.json).

## Preserved

AMD preserved | NVIDIA preserved | SDR native preserved |
CPU_REFERENCE preserved | telemetry preserved | multi-file preserved |
HUD/REGION preserved

## Recommendation

JEDEN następny krok: decyzja produktowa — (a) zaakceptować sufit UHD 730
(~24–28 FPS realnie dla 4K HDR HEVC; 17 FPS przy obciążeniu), lub (b) otworzyć
etap „quality-first export" (preset medium ≈ +1 dB Y, czas ×2.7), albo (c)
zbadać nowszy driver/FFmpeg pod kątem low_power HEVC 10-bit VDEnc, który tu
działa poprawnie, ale nie przyspiesza.

## Final verdict

**INTEL ETAP 4H: INVESTIGATED — NOT IMPLEMENTED**
Powód: veryfast/CQP24 jest już najszybszą konfiguracją dostępną w tym buildzie
i na tym GPU; low_power i async_depth bez zysku; żaden kandydat nie osiąga
>=30 FPS ani gate'ów §26/§27.


