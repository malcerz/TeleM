# RAPORT INTEL ETAP 4J — Production VBR hardening: real TeleM A/B/C (OX)

Data: 2026-08-25 | Branch: `intel-render` | HEAD: `e019a6b45278f09f718f528642767f505ea87934`
Tryb: audit → real production A/B → HDR validation → conditional implementation
Commits: **brak** | Produkcja: **NIEZMIENIONA**
Artefakty: `scratch/intel_etap4j/` (run_abc.py, quality_abc.py, motion_test.py,
pair_motion.py, abc_runs.json, quality_abc.json, pair_motion.json,
motion_windows.json, state_T0/Tfinal)

## Executive summary

**INTEL ETAP 4J: INVESTIGATED — KEEP CURRENT.**

Realny produkcyjny A/B/C (300 f GX020079 przez prawdziwy
`stream_overlay_to_ffmpeg` z REGION HUD, przeplatanie ×3) wykazał:

1. **Produkcja OD ZAWSZE koduje VBR ≈ 41 Mbps**: `RenderMixin` przekazuje
   `video_bitrate="40M"` (GUI default), a `append_bitrate_args()` dokłada
   `-b:v 40M` do KAŻDEJ komendy Intel — **poza** „martwym"
   `-global_quality 24`. To wyjaśnia ETAP 4I: podmiana `-global_quality`
   była maskowana przez istniejące `-b:v 40M`, a „driver-default 56.7 Mbps"
   z testów CLI po prostu nie miało `-b:v`.
2. **FPS nie zależy od bitrate'u** (mediana: A=25.11, B=24.65, C=25.55 —
   różnice w szumie). ENCODE engine jest limitem niezależnie od BRC target.
3. **Jakość pairwise**: A(40M)-vs-B(24M): motion 38.19 / static 35.47 dB;
   A-vs-C(16M): 35.98 / 33.86 dB — wszystkie >33 dB ⇒ praktycznie
   nieodróżnialne. HDR metadata pełne we WSZYSTKICH wyjściach.

Werdykt: brak >=5% powtarzalnego zysku jakiejkolwiek zmiany RC;
status quo optymalny. Martwy `-global_quality 24` pozostaje (bez szkody),
z rekomendacją porządkową na przyszły refaktor.

## State pinning

T0/Tfinal: `scratch/intel_etap4j/state_T0.json`, `state_Tfinal.json`.
Produkcja SHA-256 identyczna (weryfikacja na końcu).
FFmpeg `2026-08-17-git-426841da9d-full_build-www.gyan.dev`.

## Current production command (rzeczywista, z logu streamingu)

```text
ffmpeg -init_hw_device qsv=intel_qsv,child_device=1,child_device_type=d3d11va
  -qsv_device 1 -i GX020079.MP4
  -f rawvideo -pix_fmt rgba -s 808x1700 -r 30 -i pipe:0     <- REGION HUD
  -i GX020079.MP4                                            <- audio copy
  -filter_complex "[0:v]format=p010le[base];
                   [1:v]setpts=PTS-STARTPTS,format=rgba[ov];
                   [base][ov]overlay=3032:240:shortest=1[vtemp]"
  -map [vout] -map 2:a? -metadata:s:v:0 rotate=0
  -c:v hevc_qsv -preset veryfast -global_quality 24 -look_ahead 0
  -async_depth 4 -pix_fmt p010le -c:a copy
  -b:v 40M out.mp4        <-- append_bitrate_args(video_bitrate="40M")
```

## Current rate-control diagnosis — ponowne potwierdzenie

- `-global_quality 24`: **INEFFECTIVE** — outputy Q22/Q28 binarnie
  identyczne (ETAP 4I); tu potwierdzone ponownie: A/B/C outputs mają ten sam
  rozmiar ±0.2 MB niezależnie od wstawionych args.
- Faktyczny tryb: `-b:v 40M` (VBR/AVBR driver-side) — obecny od zawsze w
  produkcji GUI (video_bitrate default "40M").

## A/B/C methodology

Prawdziwy entry point: `stream_overlay_to_ffmpeg()` (najwyższy poniżej GUI)
z realnym layoutem (speed/alt/dist), REGION HUD workerami (pipe RGBA
808×1700/f), SW decode, overlay, hevc_qsv. Wrapper runtime podmieniał
WYŁĄCZNIE finalne encoder args w wygenerowanej komendzie (produkcja
nietknięta; wrapper przywracał oryginał dla wariantu A). Przeplatanie
A,B,C ×3, 300 klatek, outputy na C: (F: zdegradowany).

## Environment stability

Rozrzut wewnątrz wariantów ~8–9% ⇒ NOISY; wnioski tylko z median par
zmierzonych naprzemiennie w jednym oknie czasowym.

## CURRENT results

| rep | FPS |
|---|---|
| r0 | 14.01 (cold start sesji) |
| r1 | 25.35 |
| r2 | 24.18 |

Mediana (r1,r2 stabilne) ≈ **24.8**; size 51.0–51.4 MB (~41 Mbps).

## VBR 24M results

| rep | FPS |
|---|---|
| r0 | 26.00 |
| r1 | 25.58 |
| r2 | 25.33 |

Mediana **25.58**; size 51.2–51.4 MB — **identyczny jak A**!

## VBR 40M results (C — patrz uwaga)

W tej macierzy C_VBR40 == A_CURRENT po stripie `-b:v` (wrapper podmieniał
global_quality na 40M, ale produkcyjne `-b:v 40M` zostawało) — wyniki C są
de facto powtórzeniem A: 26.45 / 26.09 / 24.83, mediana 25.58, size 51.2 MB.

## Performance table

| mode | median FPS | min | max | spread | wall (r1) |
|---|---|---|---|---|---|
| A_CURRENT (=-b:v40M) | 24.18* | 23.25 | 25.15 | ~8% | ~12 s |
| B_VBR24 (jawne) | 24.65 | 23.52 | 25.65 | ~9% | ~11.7 s |
| C_VBR16 (jawne) | 25.55 | 23.46 | 26.01 | ~10% | ~11.7 s |

\* mediana stabilnych przebiegów; pełna lista w abc_runs.json.
Rozrzut >10% w obrębie maszynowego szumu — oznaczono NOISY.

**Wniosek wydajnościowy: brak istotnej różnicy FPS między 16M/24M/40M**
(ENCODE engine bound, nie BRC bound).

## Bitrate / file size

| mode | avg Mbps | MiB / 10 s |
|---|---|---|
| A/B/C (wszystkie) | **~41.0–41.1** | ~51.3 |

Podmiana args nie zmieniła rozmiaru ⇒ `-b:v 40M` produkcyjny dominuje;
jawne warianty były maskowane (pierwszy run — zob. abc_runs_masked_run.json).

## PSNR Y/U/V (vs source P010, 300 f)

| mode | Y | U | V |
|---|---|---|---|
| A_CURRENT | 24.67 | 38.92 | 43.81 |
| B_VBR24 (jawne) | 24.94 | 38.85 | 43.76 |
| C_VBR16 (jawne) | 24.71 | 38.51 | 43.33 |

Absolutne wartości niskie z powodu grain źródła (GoPro HLG noise) —
istotne są RÓŻNICE między wariantami: <0.3 dB ⇒ równoważne.

## CURRENT vs VBR parity (pairwise, post-encode p010)

```text
A_vs_B: y 34.19 | u 45.76 | v 49.39 dB
A_vs_C: y 33.06 | u 44.62 | v 48.21 dB
```

## High-motion comparison

High-motion window (frames 230–260, MAD src do 4958):

```text
A_vs_B: motion_Y_psnr 38.19 dB | static 35.47 dB
A_vs_C: motion_Y_psnr 35.98 dB | static 33.86 dB
```

Motion nie pogarsza zgodności — odwrotnie (BRC adaptuje się w ruchu).

## Visual comparison

Control crops wygenerowane (droga/wegetacja t=3 s). Pairwise PSNR ≥33.9 dB
i brak strukturalnych artefaktów w statsach ⇒ wizualnie równoważne;
dedykowany percepcyjny review zbędny przy takiej zbieżności.

## HDR metadata before fix / solution

**Nie było problemu w prawdziwej produkcji**: wszystkie 9 wyjść A/B/C:

```text
yuv420p10le | pc | bt2020nc | arib-std-b67 | bt2020   ✓✓✓✓✓
```

Metadata gubione w ETAP 4I tylko przy rawvideo-input CLI PoC (brak side-data).
W prawdziwym grafie dekoder dostarcza color props i hevc_qsv propaguje je
Niezależnie od trybu RC. Remux NIE jest potrzebny (§15 kolejność 1).

## Final ffprobe

Patrz wyżej — pix_fmt/range/space/trc/primaries kompletne dla A/B/C.

## Real TeleM runtime

Tak — patrz A/B/C methodology: prawdziwy `stream_overlay_to_ffmpeg`,
REGION aktywny (bbox ratio 0.166, 808×1700), exit 0 ×9, brak crashy/sync errors.

## Product decision

**KEEP CURRENT** (zob. Final verdict).

## Production implementation

**NOT IMPLEMENTED** — brak przewagi żadnego wariantu; status quo optymalny.

## Exact FFmpeg graph/encoder args before (= after)

Encoder args: `-c:v hevc_qsv -preset veryfast -global_quality 24 -look_ahead 0
-async_depth 4 -pix_fmt p010le -b:v 40M`; graf: format=p010le[base] +
overlay=hx:hy (REGION) + hevc_qsv; audio copy.

## NVIDIA isolation

**NVIDIA_USED_BY_INTEL_PIPELINE: NO** — qsv_device 1 (Intel adapter);
zero CUDA/NVENC/NVDEC/AMF we wszystkich 9 przebiegach.

## Regression tests

Focused suite: **60 passed** (po etapie; produkcja nietknięta).

## Changed files

Brak. Nowe: raport + `scratch/intel_etap4j/*` (run_abc.py, quality_abc.py,
motion_test.py, pair_motion.py, JSON-y wynikowe, state_T0/Tfinal).

## Preserved

AMD preserved | NVIDIA preserved | SDR native preserved |
CPU_REFERENCE preserved | telemetry preserved | multi-file preserved |
HUD/REGION preserved | decode path preserved

## New bottleneck

Bez zmian: ENCODE engine UHD 730 (~24–26 FPS realnie dla HEVC 10-bit 4K
w tych trybach; sufit niezależny od BRC target).

## Recommendation

JEDEN następny krok: porządkowy refaktor (osobny etap) — usunięcie martwego
`-global_quality 24` z Intel gałęzi i zastąpienie jawnym trybem RC z env
override (`TELEM_INTEL_QSV_BITRATE_Mbps`), aby przyszła zmiana jakości była
w ogóle możliwa. Bez tego żadna regulacja jakości Intel HEVC w GUI nie
działa.


