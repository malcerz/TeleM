# RAPORT INTEL ETAP 4K — QSV rate-control contract cleanup + real bitrate override + production parity (OX)

Data: 2026-08-25 | Branch: `intel-render` | HEAD: `e019a6b45278f09f718f528642767f505ea87934`
Tryb: audit → small refactor → production parity → real runtime validation
Commits: **brak** | Zmiany produkcyjne: **2 pliki** (command_builder.py,
streaming.py) — wyłącznie Intel scope

## Executive summary

**INTEL ETAP 4K: PASS — RC CONTRACT CLEANED.**

1. Audyt call chain potwierdził pełny łańcuch bitrate'u:
   GUI `QLineEdit("40M")` → `options["bitrate"]` → `RenderMixin`
   `video_bitrate` → `stream_overlay_to_ffmpeg(video_bitrate)` →
   `append_bitrate_args()` → dokładnie JEDEN `-b:v 40M`.
   `-global_quality 24` (Intel-only, jedyna występująca instancja w builderze)
   był dodawany OPRÓCZ `-b:v` i jest **inert**.
2. Production-shape proof (§7): `40M + gq22/24/28` → **identyczne SHA-256**
   wszystkich trzech outputów (21 259 628 B każdy).
3. Refaktor: usunięto `-global_quality 24` z Intel HEVC gałęzi;
   dodano `resolve_intel_qsv_bitrate()` z env override
   `TELEM_INTEL_QSV_BITRATE_MBPS` + jednorazową diagnostykę kontraktu RC.
4. Real TeleM parity BEFORE/AFTER (300 f GX020079): metadata HDR kompletne,
   rozmiar 51.2 vs 51.5 MB, FPS bez regresji; różnice plików = szum
   niedeterminizmu QSV (median Y PSNR między BEFORE/AFTER = 99 dB).

## State pinning

T0/Tfinal: `scratch/intel_etap4k/state_T0.json`, `state_Tfinal.json`.
FFmpeg `2026-08-17-git-426841da9d-full_build-www.gyan.dev`.

## Root cause

`hevc_qsv` w tym buildzie: gdy obecne jest `-b:v`, tryb BRC = VBR/AVBR
driver-side i `-global_quality` jest ignorowane (ETAP 4I/4J + proof §7:
identyczne SHA-256 dla gq 22/24/28). Produkcja GUI zawsze dokłada `-b:v 40M`
(`append_bitrate_args`), więc Intel „quality setting" był martwy od momentu
wprowadzenia, a komenda deklarowała fałszywy kontrakt jakościowy.

## Call chain (audyt §4)

```text
RenderTab.edit_bitrate (QLineEdit, default "40M")     [GUI — EDYTOWALNE]
  → render_mixin.py:84 options.get("bitrate","40M")
  → stream_overlay_to_ffmpeg(video_bitrate="40M")    [streaming.py:694]
  → _build_stream_ffmpeg_cmd(video_bitrate)
      intel branch: -c:v hevc_qsv -preset veryfast
                    [-global_quality 24 -- MARTWY, USUNIĘTY w 4K]
                    -look_ahead 0 -async_depth 4 -pix_fmt p010le|nv12
  → append_bitrate_args(): -b:v {video_bitrate}       [JEDEN, ostatni wygrywa]
```

Odpowiedzi: (1) default "40M" = render_tab QLineEdit default;
(2) TAK — użytkownik ma UI (`Bitrate:` pole tekstowe); (3) append_bitrate_args
wspólne dla nv/amd/intel/generic; (4) Intel dodawał tylko martwe
global_quality; (5) `-b:v` trafia raz; (6) przy duplikatach FFmpeg bierze
ostatni; (7) global_quality było Intel-only.

## Source-of-truth policy

Hierarchia (§5 zachowana):

```text
video_bitrate z aplikacji (GUI/CLI)
        ↓ nadpisany TYLKO gdy ustawiony
TELEM_INTEL_QSV_BITRATE_MBPS (Intel-only, diagnostyczny)
        ↓ inaczej
application value (default "40M")
```

Brak nowych twardych defaultów; istniejący `video_bitrate="40M"` pozostaje
source of truth.

## Env override policy

`resolve_intel_qsv_bitrate(video_bitrate)` (streaming.py):
- unset/niepoprawny → `(video_bitrate, "application")`
- poprawny numer → `("{N}M", "env_override")`
Intel-only (wywoływane wyłącznie w bloku encoder=="intel").

## Duplicate bitrate prevention

Wrapper-test dowiódł maskowanie; po refaktorze komenda ma **dokładnie jedno**
`-b:v`. Test regresyjny: `test_intel_hevc_vbr_contract_cleanup`,
`test_intel_hevc_env_override_reaches_final_command`
(assert `cmd.count("-b:v") == 1`).

## Diagnostics

Raz per render (blok Intel):

```text
[INTEL] QSV encoder: HEVC
[INTEL] QSV preset: veryfast
[INTEL] QSV rate-control source: application | env_override
[INTEL] QSV target bitrate: 40M | 24M | ...
[INTEL] QSV look_ahead: 0 | async_depth: 4
```

RC mode NIE jest logowany nazwanie (§16) — build nie eksponuje wiarygodnego
odczytu mode; logowana jest wyłącznie dźwignia (target bitrate).

## Before command

```text
-c:v hevc_qsv -preset veryfast -global_quality 24 -look_ahead 0
-async_depth 4 -pix_fmt p010le ... -b:v 40M
```

## After command

```text
-c:v hevc_qsv -preset veryfast -look_ahead 0
-async_depth 4 -pix_fmt p010le ... -b:v {video_bitrate}
```

(global_quality usunięte; override=24 → `-b:v 24M`; brak duplikatów)

## Default production parity (BEFORE/AFTER, 300 f GX020079)

Real TeleM path, ten sam layout/REGION/frames:

| metric | BEFORE (stary kontrakt) | AFTER (refactor) | delta |
|---|---|---|---|
| FPS | 13.96 (cold) | 22.60 | bez regresji |
| wall | 21.5 s | 13.27 s | — |
| size | 51.2 MB | 51.5 MB | +0.6% |
| bitrate | ~41 Mbps | ~41 Mbps | = |
| pix_fmt | yuv420p10le | yuv420p10le | = |
| range/space/trc/primaries | pc/bt2020nc/HLG/bt2020 | identycznie | = |
| nb_frames | 287* | 289* | tail muxer |
| `-global_quality` w cmd | tak (martwe) | **nie** | cleanup |

\* nb_frames 287/289 = tail bufora muxera (obserwowane też w 4J);
FPS r0 cold-start sesji QSV — nieporównywalne wprost, brak regresji
(wcześniejsze stabilne przebiegi 24–26 FPS).

**Output SHA-256 różni się** — wyjaśnienie: hevc_qsv nie jest bitowo
deterministyczny między sesjami; para BEFORE/AFTER (oba z -b:v 40M,
jedna z dodatkowym martwym gq24): median Y PSNR między nimi = **99 dB**
(praktyczna identyczność; 285/287 klatek ≥40 dB, 2 klatki <40 dB =
niedeterminizm silnika, nie semantyka — patrz ba.psnr).

## Override validation

`TELEM_INTEL_QSV_BITRATE_MBPS=24`, real path, 300 f:

```text
final cmd: -b:v 24M (exactly one; no 40M remnant) ✓
output size: 30.4 MB -> 24.3 Mbps  (< 41 Mbps baseline) ✓
render PASS, HDR metadata preserved ✓
```

## HDR ffprobe

AFTER i OVERRIDE24: `yuv420p10le / pc / bt2020nc / arib-std-b67 / bt2020` ✓
(bez remuxu — prawdziwy graf propaguje metadata z dekodowanego źródła,
potwierdza przewidywanie §15/§17).

## SDR preservation

Test `test_intel_sdr_nv12_unchanged_by_rc_cleanup`: SDR 720p nadal
nv12, jeden `-b:v`, bez global_quality ✓.

## NVIDIA isolation

Runtime Intel: **NVIDIA_USED_BY_INTEL_PIPELINE: NO** (qsv_device 1).
Env override dotyczy wyłącznie gałęzi `encoder=="intel"`.

## Regression tests

Nowe (test_video_helpers.py, ETAP 4K sekcja):

1. `test_intel_hevc_vbr_contract_cleanup` — no global_quality, exactly one
   `-b:v 40M`, p010le, bez nv12-hwdownload w HDR
2. `test_intel_qsv_bitrate_env_override` — unset/24/40/garbage semantics
3. `test_intel_hevc_env_override_reaches_final_command` — resolve→builder
   chain: exactly one `-b:v 24M`, zero remnantów 40M/global_quality
4. `test_intel_sdr_nv12_unchanged_by_rc_cleanup` — SDR nv12 + kontrakt

Focused suite: **64 passed** (60 + 4 nowe).

## Changed files

- `src/ffmpeg/command_builder.py` — usunięty martwy `-global_quality 24`
  (Intel HEVC branch only) + komentarz kontraktu
- `src/ffmpeg/streaming.py` — `resolve_intel_qsv_bitrate()` +
  jednorazowa diagnostyka RC (preset/source/target/la/ad)
- `tests/test_video_helpers.py` — 4 nowe testy

AMD/NVIDIA/generic CPU/GUI/telemetry/HUD/decode: **zero diff**.

## Preserved

Default bitrate 40M | preset veryfast | look_ahead 0 | async_depth 4 |
p010le/nv12 polityka | AMD/NVIDIA/CPU commands | GUI Bitrate field (działa
już poprawnie z backendem) | decode path

## Performance conclusion

**NO PERFORMANCE CLAIM — CONTRACT CLEANUP.** FPS AFTER (22.6 cold) w granicach
szumu vs BEFORE (13.96 cold) i wcześniejszych stabilnych przebiegów (24–26).

## Recommendation

JEDEN następny krok: podłączyć `options["bitrate"]` (istniejące GUI pole)
jako widoczną kontrolkę jakości eksportu dla Intel — backend jest teraz
truthful i gotowy; ewentualnie dodać profile (24M „small" / 40M „standard").

