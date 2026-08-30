# RAPORT INTEL ETAP 5A — Production hardening + full regression + merge-readiness (OX)

Data: 2026-08-25 | Branch: `intel-render` | HEAD: `e019a6b45278f09f718f528642767f505ea87934`
Tryb: audit → real runtime matrix → regression → cleanup review → merge readiness
Commits: **brak** | Zmiany 5A w produkcji: **BRAK**

## Executive summary

**INTEL ETAP 5A: READY WITH KNOWN LIMITATIONS.**

Real runtime matrix przez produkcyjny entry point (`stream_overlay_to_ffmpeg`,
prawdziwy REGION HUD worker, prawdziwy materiał) — wszystkie 3 scenariusze PASS:

| test | path | FPS | frames | HDR meta | NVIDIA |
|---|---|---|---|---|---|
| T1 SDR native | QSV decode → GPU-resident → REGION → overlay_qsv → hevc_qsv | **48.61** | 180/180 | n/a SDR | NONE |
| T2 HDR CPU_REF | SW decode → p010 CPU → REGION → sw overlay → hevc_qsv p010le | **25.64** | 300/300 | pełne ✓ | NONE |
| T3 multi-file | jak T2 + concat/timeline przez granicę klipu | **56.66*** | 210 podane / 193 out | ✓ | NONE |

\* tail-loss muxera — znane zachowanie, nie regresja (patrz niżej).

Full suite: **1095 passed / 22 skipped / 30 failed / 5 errors** — WSZYSTKIE
failures/errors odtworzone na czystym HEAD w osobnym worktree ⇒ **pre-existing,
zero regresji z Intel changes** (dowód worktree poniżej).

## State pinning

T0: `scratch/intel_etap5a/state_T0.json` (9 plików SHA-256 + status/diffstat).
Tfinal: porównanie programowe — pliki produkcyjne **identyczne z T0**
(5A niczego nie zmieniało w kodzie).
FFmpeg ACTIVE: `F:\_DEV\TeleM\ffmpeg.exe` /
`2026-08-17-git-426841da9d-full_build-www.gyan.dev`.

## Working-tree inventory

Tracked modified (5):
def_layout.json (2±), src/benchmark.py (+3), src/ffmpeg/command_builder.py
(+40±), src/ffmpeg/streaming.py (+220±), tests/test_video_helpers.py (+299).
Untracked: 16 raportów Intel 3B–4K + scratch/intel_etap3b,4a,4bc,4d–4k +
intel_etap4_audit_T0/T1/T2 + state snapshoty.

## Production Intel diff inventory (klasyfikacja)

streaming.py (+220) = A; command_builder.py (+40) = A;
benchmark.py (+3) = B/A; test_video_helpers.py (+299) = B;
def_layout.json (2±) = F/USER.

## Unrelated/user changes

def_layout.json label_count 4→5: INTENTIONAL UNKNOWN → MANUAL REVIEW
(nie wchodzi do rekomendowanego commit setu Intel).
src/benchmark.py median/p99: shared helper read-only — brak wpływu na
AMD/NVIDIA/CPU behavior.

## Active FFmpeg

`F:\_DEV\TeleM\ffmpeg.exe` · `2026-08-17-git-426841da9d-full_build-www.gyan.dev`.

## Hardware / DXGI

Intel UHD 730 (0x8086, dynamiczny adapter 1) wybrany mimo Quadro P400
(0x10DE, index 0) ignorowanej; brak hardcodu indeksu.

## Final Intel path matrix

SDR native: QSV/D3D11VA decode → GPU-resident → REGION → overlay_qsv →
hevc_qsv nv12.
HDR 10-bit: SOFTWARE decode → CPU_REFERENCE p010 → REGION → sw overlay →
hevc_qsv p010le (reason: unsupported native vertical-slice configuration).
multi-file: QSV→hwdownload → CPU_REFERENCE → REGION → hevc_qsv (j.w.).
rotation ≠0: CPU transpose (needs_cpu_rotation).
cuts: CPU_REFERENCE select. res poza {source,720p,1080p}: CPU_REFERENCE
(eligibility list).

## SDR native runtime

48.61 FPS / 180 f / D3D11_NATIVE / GPU residency / REGION ratio 0.139.
FULL_VIDEO_FRAME_GPU_TO_CPU_READBACK: **NO** (tylko HUD region CPU→GPU).

## HDR CPU_REFERENCE runtime

25.64 FPS / 300 f GX020079 4K / SW decode / HWDownload NO / REGION 0.166 /
output p010le/pc/bt2020nc/HLG/bt2020 ✓.

## Multi-file runtime

56.66 FPS / 210 f przez granicę klipu 6 s; output 193 klatek / 6.44 s =
tail-loss ~17 klatek na KOŃCU (znane QSV/muxer; granica ciągła, HUD OK,
bez resetu pipe). Nie regresja nowa.

## HDR ffprobe

hevc yuv420p10le pc bt2020nc arib-std-b67 bt2020 ✓ (audio copy, duration>0,
dekod pełny bez błędów strumienia).

## Telemetry/timeline validation

VideoTimeline przeszedł bez offset-naive wyjątku; precompute OK;
SmartSync/timestamps nietknięte; punkty przed/na/po granicy renderowane.

## RC contract

Dokładnie jeden `-b:v 40M`; `-global_quality` usunięte z komendy Intel;
preset veryfast; look_ahead 0; async_depth 4. Diagnostyka jednorazowa:
rate-control source = application/env_override + target bitrate.

## GUI bitrate contract

RenderTab edit_bitrate (QLineEdit „40M") → options["bitrate"] →
video_bitrate → final cmd. Test: 24M → dokładnie jeden `-b:v 24M` ✓.

## Env override

TELEM_INTEL_QSV_BITRATE_MBPS: unset→application ✓; 24→24M ✓;
garbage→fallback application, no crash ✓.

## Intel diagnostics

CAPABILITY rozdzielone od ACTUAL (Render path/Decode path/residency/HUD
transport/Fallback reason) — spójne we wszystkich logach 5A.

## NVIDIA isolation

NVIDIA_USED_BY_INTEL_PIPELINE: NO. Zero cuda/nvdec/nvenc/cuvid/*_cuda
w wygenerowanych komendach (audyt automatyczny).

## AMD preservation

Zero diff AMD; test_amd_native_overlay_handoff PASS; runtime NOT AVAILABLE.

## Generic CPU preservation

Gałąź libx265 nietknięta; testy generacji zielone.

## Focused tests

64 passed (test_video_helpers + intel_backend + gpu_compositor +
amd_native_overlay_handoff + etap5f_pipeline_audit).

## Full tests

1095 passed / 22 skipped / 30 failed / 5 errors — wszystkie failures
ODTWORZONE na czystym HEAD w dedykowanym worktree ⇒ pre-existing, poza
Intel scope (charts/solar/FIT/GUI/cache/1×AMD-layout assert).

## Static checks

py_compile streaming/command_builder/benchmark/test_video_helpers: exit 0.

## Cancel smoke

SDR native (600 f timeline) → cancel po 3 s: ffmpeg graceful stop rc=0,
thread_finished=True, zombie=0; kontrolowane queue.Empty w workerze =
oczekiwana architektura anulowania. Partial MP4 nieweryfikowany (§29).

## Error propagation

Writer/FFmpeg failure dociera jako kontrolowany RuntimeError; brak
infinite-wait w przebiegach 5A.

## Scratch/generated artefacts

intel_etap3b 484 MB i intel_etap4e 298 MB = DO NOT COMMIT;
pozostałe etapy 0.1–56 MB KEEP LOCAL; intel_etap5a 0.14 MB po cleanupie.

## .gitignore assessment

Brak wpisu scratch/ — zaległość potwierdzona (4B/4C); proponowany minimalny
diff: dopisać linię scratch/. Raporty/ NIE ignorować.

## Line endings

streaming.py spójne LF po naprawie w ETAP 4B/4C (0 CRLF / 1947 LF) — bez akcji.

## Intel env vars

TELEM_INTEL_GPU_RESIDENT (1, native eligibility+kill, production)
TELEM_INTEL_HUD_REGION (1, native REGION kill, production)
TELEM_INTEL_CPU_REF_HUD_REGION (1, CPU_REF REGION kill, production)
TELEM_INTEL_CPU_REF_HUD_REGION_MAX_RATIO (0.85, threshold override, diagnostic)
TELEM_INTEL_QSV_BITRATE_MBPS (unset, bitrate override, diagnostic, NOWY 4K)
Brak konfliktów/duplikatów.

## Fallback reasons

HDR/non-8-bit → CPU_REFERENCE p010le (unsupported native vertical-slice
configuration) TESTED · multi-file → CPU_REFERENCE concat TESTED ·
rotation ≠0 → transpose CPU (testy) · cuts → CPU_REFERENCE select ·
res poza {source,720p,1080p} → CPU_REFERENCE (testy) · probe failure →
CPU_REFERENCE · kill-switch GPU_RESIDENT=0 (harness)

## Performance sanity

SDR native 48.6 FPS · HDR CPU_REFERENCE 25.64 FPS (300 f) · multi-file 720p
56.7 FPS. Bez katastrofalnej regresji.

## Output integrity

ffprobe exit 0 ×3; pełny dekod t2/t3 bez błędów strumienia; duration/frame
count >0; audio copy obecny.

## Production changes made by 5A

NONE.

## Recommended commit set

COMMIT: src/ffmpeg/streaming.py, src/ffmpeg/command_builder.py,
src/benchmark.py, tests/test_video_helpers.py, Raporty/RAPORT_INTEL_*.md
(16 szt. 3B–4K + 5A).
DO NOT COMMIT: scratch/** (benchmark/raw/harness artefakty).
MANUAL REVIEW: def_layout.json (label_count 4→5, user change, nie-Intel).

## Remaining known limitations

1. P010 overlay_qsv chroma geometry bug (ETAP 4D) — blokuje HDR native.
2. HDR native unavailable → świadomy fallback CPU_REFERENCE.
3. UHD 730 encode ceiling ~24–28 FPS realnie dla 4K HDR HEVC.
4. Native eligibility ograniczona (single-file/rot0/no-cuts/res-lista).
5. Multi-file tail-loss klatek (~17/210) przy QSV muxer — znane.
6. Partial-MP4-on-cancel — partial może być non-playable.
7. -global_quality martwe w tym buildzie gdy -b:v obecne (dokumentowane).

## Merge-readiness verdict

READY WITH KNOWN LIMITATIONS — wszystkie kryteria §48 spełnione;
ograniczenia jawne, udokumentowane, mają bezpieczny fallback.

## Recommendation

Jeden następny krok po ustabilizowaniu gałęzi: commit rekomendowanego
zestawu, następnie decyzja produktowa: (a) native multi-file, albo (b)
jawne RC/GUI quality control dla Intel (backend gotowy po 4K).

## Final verdict

INTEL ETAP 5A: READY WITH KNOWN LIMITATIONS

