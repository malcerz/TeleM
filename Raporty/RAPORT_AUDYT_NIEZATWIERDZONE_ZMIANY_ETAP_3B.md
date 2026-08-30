# TeleM — AUDYT niezatwierdzonych zmian na gałęzi `intel-render` (kontekst INTEL ETAP 3B)

Data audytu: 2026-08-25. Tryb: AUDIT ONLY — w ramach audytu nie wprowadzono żadnych zmian produkcyjnych.

## Zakres audytu

Stan roboczy (`git status`):

- `M src/ffmpeg/command_builder.py` (+15)
- `M src/ffmpeg/streaming.py` (+14 / −1)
- `M tests/test_video_helpers.py` (+2)
- `?? Raporty/RAPORT_INTEL_ETAP_3B_AB_PARITY_PERF.md`
- `?? scratch/intel_etap3b/`

HEAD: `019a6b6` (branch `intel-render`, równy `origin/intel-render`, `main`, `backup/intel-przed-synchronizacja`).

## Wnioski szczegółowe

### 1. `src/ffmpeg/command_builder.py` — POPRAWNE

Nowa gałąź `elif encoder == "intel":` w `_build_stream_ffmpeg_cmd` dodaje jawny transfer
QSV → pamięć systemową dla ścieżki CPU_REFERENCE:

```text
[0:v]hwdownload,format=nv12[,scale=lanczos|vflip,hflip|transpose=1|transpose=2][base]
```

Weryfikacja:

- **Kolejność gałęzi**: `nv` → `amd` → `intel && intel_gpu_resident` → `intel` → generic.
  Nowa gałąź jest PO gałęzi natywnej (`command_builder.py:714`), więc nie przejmuje ścieżki
  GPU-resident i nie dotyka NVIDIA/AMD/CPU. Potwierdzone testem: native nadal bez `hwdownload`,
  CPU_REFERENCE z `hwdownload`.
- **Parzystość semantyki z CPU reference (AGENTS §9)**: rotacje lustrzanie odwzorowują gałąź
  generic (`transpose=1` dla 90°, `transpose=2` dla 270°, `vflip,hflip` dla 180°), skalowanie
  `flags=lanczos` jak w generic. Geometria/orientacja zachowane.
- **Konieczność `hwdownload`**: `streaming.py` dla `encoder == "intel"` zawsze ustawia
  `hwaccel = "qsv"`, a `intel_ffmpeg_device_args()` (`src/ffmpeg/intel_backend.py:360–371`)
  wymusza `-hwaccel qsv -hwaccel_output_format qsv`. Klatki `[0:v]` są zatem zawsze sprzętowe,
  a bez `hwdownload` negocjacja filtrów scale/overlay odrzuca graf (root cause z ETAP 3B).
- **Ryzyko cichego fallbacku SW-decode** (które złamałoby `hwdownload` na klatkach soft):
  wykluczone — `-hwaccel_output_format qsv` powoduje jawny błąd FFmpeg zamiast cichego
  przejścia na software.

### 2. `src/ffmpeg/streaming.py` — POPRAWNE

- `writer_failed: threading.Event | None = None` jako ostatni, opcjonalny parametr
  `_pipe_writer_thread` — zmiana wstecznie kompatybilna; funkcja ma dokładnie jeden call-site
  (potwierdzone wyszukiwaniem po repozytorium), więc brak wpływu na inne pipeline'y.
  Event ustawiany w obu ścieżkach wyjątku (`BrokenPipeError, OSError`: ścieżka shm-pool i standardowa).
- Pętla producenta sprawdza `writer_failed.is_set()` przed `queue.put` i przerywa produkcję
  z logiem `[STREAM] FFmpeg stdin writer failed; stopping frame producer` — eliminacja
  blokowania producenta przy śmierci procesu FFmpeg. Log jednorazowy, ASCII-safe (AGENTS §16/§17).
- Diagnostyka `[INTEL] HUD upload bytes/frame` tylko przy `encoder == "intel"`, jednorazowa
  (nie per-frame), zgodna z deklaracją raportu ETAP 3B.

### 3. `tests/test_video_helpers.py` — POPRAWNE

Dwie asercje w istniejącym `test_intel_and_cpu_pipeline_unchanged` chronią rozdział:
CPU Intel (`hwdownload,format=nv12` obecne, `overlay_qsv` nieobecne) vs native Intel
(`overlay_qsv` obecne, `hwdownload` nieobecne). Zgodne z deklaracją raportu.

## Weryfikacja deklaracji raportu RAPORT_INTEL_ETAP_3B_AB_PARITY_PERF.md

| Deklaracja raportu | Status w audycie |
|---|---|
| Focused suite `51 passed` | POTWIERDZONE — ponownie uruchomiono: `51 passed in 1.24s` |
| Jawny transfer QSV→CPU w CPU_REFERENCE | POTWIERDZONE w kodzie (`command_builder.py`) |
| Propagacja błędu writer stdin | POTWIERDZONA (`streaming.py`, `writer_failed`) |
| Jednorazowa diagnostyka rozmiaru HUD upload | POTWIERDZONA |
| Brak zmian AMD/NVIDIA/CPU | POTWIERDZONE statycznie — diff dotyka wyłącznie gałęzi `encoder=="intel"` oraz wspólnego writer-thread (zmiana opcjonalna/None-default) |

Liczby parity/perf z raportu 3B (mean abs diff ~1.24–1.36, wall time ~4.16 s vs ~4.40 s)
są pomiarem bieżącego środowiska wg raportu; audyt ich nie powtarza (poza testami jednostkowymi).

## Artefakty scratch

`scratch/intel_etap3b/` zawiera m.in.: `cpu.log` — **89 MB**, `CPU_REFERENCE.mp4` ~27 MB,
`GPU_RESIDENT.mp4` ~28 MB, `canonical_sdr_720p.mp4` ~13 MB, PNG-e ~1.2 MB/szt., `run_ab.py`.

`.gitignore` ignoruje globalnie `*.mp4` i `*.png`, ale **NIE** ignoruje `*.log` ani `scratch/` —
przy `git add .` plik 89 MB oraz logi/`run_ab.py` zostałyby dodane do repozytorium.

**Rekomendacja**: dodać `scratch/` do `.gitignore` (lub usunąć `cpu.log`) przed commitem (AGENTS §69).

## Preserved

- Ścieżki AMD, NVIDIA, CPU fallback: statycznie nienaruszone (przegląd diff + testy regresyjne gałęzi nv/amd/cpu przeszły).
- Eligibility ścieżki natywnej Intela, ustawienia QSV, polityka INTEL_FORCE (brak cross-GPU fallback): nienaruszone.
- Z-order/geometria HUD: nienaruszone (filtry bazowe zgodne z generic; overlay bez zmian).

## Tested

- `python -m pytest tests/test_intel_backend.py tests/test_video_helpers.py tests/test_gpu_compositor.py tests/test_amd_native_overlay_handoff.py -q` → **51 passed in 1.24s**.
- Statyczny przegląd pełnych diffów (`git diff`) — brak zmian niezamierzonych, brak debug-artefaktów w `src/`.

## Hardware tested

- Intel runtime: render A/B wykonany wcześniej w ramach ETAP 3B (raport źródłowy); w ramach niniejszego audytu nowych renderów runtime nie wykonywano.
- AMD runtime: niedostępne; path preserved statically.
- NVIDIA runtime: niedostępne; path preserved statically.

## Not tested

- Pełny export 4K i multi-file dla Intela (poza zakresem audytu).
- Rzeczywista interakcja GUI (nie dotyczy zmian).

## Risks / Remaining issues

1. `scratch/intel_etap3b/cpu.log` (89 MB) — ryzyko przypadkowego commitu; obsłużyć przez `.gitignore`.
2. `writer_failed` zatrzymuje producenta, ale jawnie nie kończy procesu FFmpeg — proces i tak
   jest już martwy (BrokenPipe); zachowanie akceptowalne, odnotowane.
3. Różnice parity CPU vs GPU overlay (~28% changed pixels przy progu >2) wymagają takiej samej
   interpretacji jak w raporcie 3B: różnica implementacji overlay + reenkod QSV, nie bit-to-bit;
   ewentualne wizualne skutki zweryfikować osobno, jeśli pojawią się zgłoszenia.
4. Optymalizacja uploadu regionowego HUD — celowy następny etap (rekomendacja raportu 3B), nie część tej zmiany.

## Verdict

Zmiany są spójne, minimalne zakresowo (Intel/streaming only), zgodne z deklaracjami raportu
ETAP 3B oraz z AGENTS.md (zachowanie vendorów, parzystość z CPU reference, logowanie ASCII).
**Gotowe do commitu po obsłużeniu artefaktów `scratch/` (rekomendacja: `.gitignore`).**

