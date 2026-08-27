# RAPORT INTEL ETAP 5C — Final commit-set audit + clean staging plan (OX)

Data: 2026-08-26 · Tryb: FINAL AUDIT → COMMIT-SET CLASSIFICATION → DIFF HYGIENE → PRE-COMMIT VALIDATION → STOP BEFORE COMMIT
Zakres: przygotowanie `intel-render` do JEDNEGO kontrolowanego commita produkcyjnego. Żadnego `git add/commit/push` nie wykonano.

---

## Current branch / HEAD

- Branch: `intel-render` (= origin/intel-render; main i backup/intel-przed-synchronizacja na tym samym SHA)
- HEAD: `e019a6b45278f09f718f528642767f505ea87934` ("Poprawki i korety")
- Seria 3B–5B istnieje WYŁĄCZNIE w working tree.

## Working-tree inventory

Tracked modified: **7** plików. Untracked: 16 raportów Intel + 1 notatka procesowa + `NUL-bad` + `scratch/**` (~250 plików; po dodaniu wpisu `.gitignore` niewidoczne dla statusu).

## Tracked modified files

| file | reason | class | action |
|------|--------|-------|--------|
| src/ffmpeg/streaming.py | REGION+CPU_REF gate+diag (4A/4B/4E), RC resolve (4K), writer EOF contract+finalize+cancel flag (5B) | production, Intel YES | COMMIT |
| src/ffmpeg/command_builder.py | Intel CPU_REF hwdownload/format + SW-decode branchy (4B–4E), RC cleanup+p010 (4K), `_fps_rational_arg()`+racjonalne `-r` (5B) | production, Intel YES | COMMIT |
| src/benchmark.py | median/p99 w BenchmarkTracker (instrumentacja A/B z 4A, używana przez raporty/testy diagnostyczne) | test-infra, Intel YES | COMMIT |
| tests/test_video_helpers.py | +299 linii: REGION gate, RC resolve/env override, diag contract (4B/4K) | test, Intel YES | COMMIT |
| tests/test_etap5h_writer_queue.py | +5 testów: writer lifecycle, rational FPS, command construction (5B) | test, Intel YES | COMMIT |
| tests/test_render_cancel_process_lifecycle.py | kontrakt done→write / explicit-cancel→discard (5B; stary test kodował BUG#1) | test, Intel YES | COMMIT |
| def_layout.json | label_count 4→5 — zmiana użytkownika, niezwiązana z Intelem | user | MANUAL REVIEW / EXCLUDE |

## Untracked inventory

- `Raporty/RAPORT_INTEL_ETAP_*.md` + `RAPORT_INTEL_HOTFIX_*.md` — 16 plików dowodowych 3B→5B (2.9–22.1 KB, markdown)
- `Raporty/RAPORT_AUDYT_NIEZATWIERDZONE_ZMIANY_ETAP_3B.md` — notatka procesowa 3B
- `scratch/intel_etap3b…5b/**`, `scratch/intel_etap4*_T*.json` — ~250 evidence files → DO NOT COMMIT
- `NUL-bad` (root, 4.4 KB) — debug-log z 5A; DO NOT COMMIT (do ręcznego usunięcia przez użytkownika)

## Production diff classification

Streaming: 19 hunkow - wszystkie przypisalne do etapow (device/path+diag 3B/4K; REGION gate 4A/4B; CPU_REF download format 4D/4E; SW-decode 4D; writer EOF 5B; audit hooks env-gated juz w HEAD). Command-builder: 6 hunkow (Fraction helper, intel_cpu_* params, CPU_REF/SW base_filter, -r rational, RC cleanup, p010 output). Benchmark: 1 hunk.

Anty-wzorce w dodanych liniach: local paths 0 realnych (7 trafien = falszywe _DEV podciag _device_args), sleep 0, TODO/FIXME/HACK 0, hardcoded adapter index 0, vendor-tokeny 1 (komentarz kontekstowy NVIDIA rot180 CUDA - bez uzycia), scratch-ref 1 (docstring-dowod breakeven - dokumentacja, brak zaleznosci).

Werdykt higieny: NO CHANGE wymagane.

## Streaming diff audit

Hunk-mapa: L72+ (_probe_intel_cpu_download_format, _flag_on_env, resolve_intel_qsv_bitrate, _intel_hud_region_gate, REGION geometry) = 4A/4B/4K. L239-525 writer (5B). L763+ wybor sciezki (3C/4A). L837-880 [INTEL] diag + RC one-shot print (4K). L1135-1351 worker/SHM wiring + audit marks (env-gated, 5F-era). L1739-1800 cancel/finalize (5B). Brak tymczasowego debugu, martwych licznikow, benchmark-only kodu w produkcji.

## Command-builder diff audit

_fps_rational_arg() zwalidowana:

| input | output |
|---|---|
| 30 | 30 |
| 29.97002997002997 | 30000/1001 |
| 59.94005994005994 | 60000/1001 |
| 23.976023976023978 | 24000/1001 |
| 25 / 50 / 60 / 24 / 120 / 15 | int |
| 29.97 (dokladnie podany) | 2997/100 |
| 59.94 (dokladnie podany) | 2997/50 |

Zero absurdalnych ulamkow z FP noise.

## Writer lifecycle final contract

Potwierdzone: normal EOF = zapis wszystkich zakolejkowanych (sentinel FIFO / Empty+done); explicit cancel/error = discard_pending => release-drain; done_event = no-more-input; stdin.close() dopiero po join(). FFmpeg-death: writer BrokenPipe/OSError => writer_failed.set() => producer _put_frame przerywa; join(60 s) nie wisi na martwym FFmpeg. Timeout 60 s nietkniety.

## Cancel contract

Cancel ustawia writer_discard_pending PRZED pipe_done i joinuje 1.0 s - cancel NIE renderuje backlogu. Potwierdzone testem discard-only-when-pending oraz runtime R5 (5B): thread exit, zombie=0.

## Frame-accounting instrumentation decision

PipelineAuditRecorder: TRACKED, niezmieniony wzgledem HEAD (istnial przed 5B) => decyzja A: produkcyjny debug-contract, env-gated (TELEM_PIPELINE_AUDIT), inert domyslnie. 5B nie dodalo instrumentacji produkcyjnej. Decyzja: KEEP.

## Rational-FPS validation

PASS (tabela wyzej).

## Hardcoded-device audit

Dynamiczny Intel 0x8086 (log: Selected adapter index pochodzi z detekcji). W dodanych liniach brak qsv_device 1 / child_device=1 / adapter_index=1 jako selekcji (tylko komentarz do-not-hardcode). Runtime diag potwierdza pinning INTEL. PASS.

## Vendor-leak audit

Zero uzyc cuda/nvenc/nvdec/cuvid/amf w Intel changes (1 trafienie = komentarz kontekstowy). AMD/NVIDIA paths nietkniete. PASS.

## Machine-specific-path audit

Brak F:\ , C:\ , username, kluczy/tokenow w commit secie. Testy przenosne (Quadro P400 = mock-fixture nazwa w tescie izolacji vendorowej). PASS.

## Large-file audit

Najwiekszy plik commit-setu: streaming.py 91.2 KB tekst; raporty <=22.1 KB md. Zero P010/MP4/PNG/dumpow. PASS.

## .gitignore decision

git ls-files scratch = 4 tracked stare logi scratch/intel_etap3a/*.log (pozostaja sledzone - ignore nie odlacza tracked). Dodano minimalnie:

    # Intel/AMD etap working artifacts (evidence, not source)
    scratch/

Efekt: status czysty z ~250 untracked artefaktow. Raporty/ NIE ignorowane. .gitignore wchodzi do COMMIT SET.

## Focused tests

tests/test_video_helpers.py, test_intel_backend.py, test_gpu_compositor.py, test_amd_native_overlay_handoff.py, test_etap5f_pipeline_audit.py, test_etap5h_writer_queue.py, test_render_cancel_process_lifecycle.py => 74 passed (12.30 s). Zgodne z minimum 5B.

## Full tests

1100 passed / 22 skipped / 30 failed / 5 errors - IDENTYCZNE z baseline 5B. Zero nowych regresji.

## Runtime smoke

- SDR native: canonical_sdr_720p, 180 f, Intel: probe yuv420p/bt709 = 180/180 exact; diag D3D11_NATIVE / GPU residency. PASS.
- HDR: GX020079, 300 f, 4K: probe yuv420p10le / arib-std-b67 = 300/300; diag CPU_REFERENCE + Decode SOFTWARE + HWDownload NO. PASS.
(Uwaga procesowa: pierwszy przebieg smoke pokzal CPU_REFERENCE dla SDR z powodu bledu WLASNEGO harnessu - plaski layout bez klucza indicators => is_no_hud=True; po poprawce harnessu native dziala. Produkcja nietknieta.)

## Static checks

python -m py_compile na wszystkich zmienionych .py => exit 0.

## FINAL COMMIT SET

1. src/ffmpeg/streaming.py
2. src/ffmpeg/command_builder.py
3. src/benchmark.py
4. tests/test_video_helpers.py
5. tests/test_etap5h_writer_queue.py
6. tests/test_render_cancel_process_lifecycle.py
7. .gitignore
8. Raporty/RAPORT_INTEL_ETAP_*.md (16 plikow: ETAP_3B_AB_PARITY_PERF, 3C_HUD_REGION, 4_PIPELINE_BOTTLENECK_AUDIT_OX, 4A..4K OX-series, HOTFIX_10BIT_CPU_REFERENCE, HOTFIX_2_QSV_HWDOWNLOAD_SYNC, 5A_PRODUCTION_HARDENING_OX, 5B_QSV_TAIL_LOSS_OX) + RAPORT_INTEL_ETAP_5C_FINAL_COMMIT_AUDIT_OX.md

Uzasadnienia odchyleń od listy wstepnej (par. 5): dolaczono .gitignore (porzadek untracked scratch), Raporty/RAPORT_INTEL_*.md (dowody serii); benchmark.py potwierdzony jako Intel instrumentation helper (INCLUDE).

## DO NOT COMMIT

- scratch/** (calle evidence)
- NUL-bad (debug-log artefakt)
- def_layout.json (user change)
- Raporty/RAPORT_AUDYT_NIEZATWIERDZONE_ZMIANY_ETAP_3B.md (notatka procesowa - opcjonalnie user decyduje)

## MANUAL REVIEW

- def_layout.json (label_count 4->5; niezwiazane z Intelem; nie cofac, nie edytowac)

## Recommended staging command

    git add -- src/ffmpeg/streaming.py src/ffmpeg/command_builder.py src/benchmark.py .gitignore tests/test_video_helpers.py tests/test_etap5h_writer_queue.py tests/test_render_cancel_process_lifecycle.py Raporty/RAPORT_INTEL_ETAP_3B_AB_PARITY_PERF.md Raporty/RAPORT_INTEL_ETAP_3C_HUD_REGION.md Raporty/RAPORT_INTEL_HOTFIX_10BIT_CPU_REFERENCE.md Raporty/RAPORT_INTEL_HOTFIX_2_QSV_HWDOWNLOAD_SYNC.md Raporty/RAPORT_INTEL_ETAP_4_PIPELINE_BOTTLENECK_AUDIT_OX.md Raporty/RAPORT_INTEL_ETAP_4A_CPU_REFERENCE_HUD_REGION.md Raporty/RAPORT_INTEL_ETAP_4B_4C_PRODUCTION_OPTIMIZATION_OX.md Raporty/RAPORT_INTEL_ETAP_4D_HDR_P010_NATIVE_OX.md Raporty/RAPORT_INTEL_ETAP_4E_P010_CPU_OVERLAY_OX.md Raporty/RAPORT_INTEL_ETAP_4F_10BIT_REGION_COMPOSITOR_OX.md Raporty/RAPORT_INTEL_ETAP_4G_P0_VIDEO_PATH_OX.md Raporty/RAPORT_INTEL_ETAP_4H_HEVC_QSV_QUALITY_PERF_OX.md Raporty/RAPORT_INTEL_ETAP_4I_QP_REALTIME_FRONTIER_OX.md Raporty/RAPORT_INTEL_ETAP_4J_VBR_PRODUCTION_OX.md Raporty/RAPORT_INTEL_ETAP_4K_QSV_RC_CONTRACT_OX.md Raporty/RAPORT_INTEL_ETAP_5A_PRODUCTION_HARDENING_OX.md Raporty/RAPORT_INTEL_ETAP_5B_QSV_TAIL_LOSS_OX.md Raporty/RAPORT_INTEL_ETAP_5C_FINAL_COMMIT_AUDIT_OX.md

(NIE wykonano. Jawna lista zamiast patternu - zero ryzyka zlapania obcych plikow.)

## Suggested commit message

    Intel: stabilize QSV render pipeline and frame lifecycle

    - Dynamic Intel adapter selection (vendor 0x8086), QSV/D3D11 decode pinning,
      no NVIDIA fallback, no hardcoded adapter index
    - SDR native path: GPU-resident video base + bounded REGION HUD upload
      (ratio gate 0.85, env-overridable), overlay_qsv + hevc_qsv without
      full-frame readback
    - HDR 10-bit: software decode P010 CPU_REFERENCE with REGION HUD,
      explicit hwdownload boundary, hevc_qsv p010 output
    - RC contract: removed inert -global_quality; single -b:v source of truth
      (GUI bitrate / TELEM_INTEL_QSV_BITRATE_MBPS override) + one-shot diag
    - Writer lifecycle: normal EOF writes the full queued backlog; discard is
      an explicit cancel/error flag; stdin closes only after writer drain
      (fixes variable multi-file tail loss of ~9-21 frames)
    - HUD rawvideo input rate declared as exact rational (30000/1001 etc.),
      fixing single-frame shortest=1 tail drop
    - Tests: writer/cancel contract, rational FPS command construction,
      REGION gate, RC resolve/env override; benchmark summary median/p99
    - Reports: full 3B..5C Intel evidence series under Raporty/

## Post-commit verification commands

    git status --short                 # oczekiwane: tylko def_layout.json + NUL-bad + AUDYT_3B.md
    git show --stat HEAD               # oczekiwane: 24 files changed, zero scratch/**
    python -m pytest tests/test_etap5h_writer_queue.py tests/test_render_cancel_process_lifecycle.py tests/test_intel_backend.py -q   # zielone
    git ls-files --others --exclude-standard | Select-String scratch   # brak (po ignore)

## Merge readiness

READY TO COMMIT

## Blockers

NONE

## FINAL VERDICT

INTEL ETAP 5C: READY TO COMMIT
