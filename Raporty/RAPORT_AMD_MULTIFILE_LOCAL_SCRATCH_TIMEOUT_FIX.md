# RAPORT: AMD MULTIFILE LOCAL SCRATCH + TIMEOUT FIX

**Data:** 2026-09-06  
**Gałąź:** `integration/intel-amd`  
**Status:** IMPLEMENTED; REAL PROOF PASS dla testu granicy 90.09 s; test 50-minutowy NOT TESTED

## 1. Zadanie

Naprawa AMD multi-file dla wyjścia na wolny dysk USB:

- Stage A zapis video-only MP4 na lokalnym scratch, a nie obok outputu;
- usunięcie fałszywego hard timeoutu live muxera;
- pomiar `stdin_closed -> actual FFmpeg exit`;
- zachowanie Stage A po błędzie Stage C;
- diagnostyka FPS i kosztów per klip.

## 2. Stan początkowy

Kod tworzył dla outputu `F:\...mp4` plik:

```text
F:\...mp4.part.temp_video.mp4
```

Stage A zapisywał cały plik video-only na USB. Live mux miał limit
`max(60 s, duration * 0.25)`, a pompa miała osobny limit 60 s. Przy długim
zapisie USB mogło to zakończyć się `terminate()` mimo dalszego wzrostu pliku.
`stdin_closed` był raportowany przed potwierdzeniem zakończenia pompy.

## 3. Zmienione pliki

- `src/ffmpeg/amd_native_exporter.py`
- `src/ffmpeg/finalization_tracker.py`
- `tests/test_amd_direct_mp4_mux.py`
- `Raporty/RAPORT_AMD_MULTIFILE_LOCAL_SCRATCH_TIMEOUT_FIX.md`

## 4. Implementacja

1. Dodano `_create_amd_local_scratch_dir()`:
   - `AMD_LOCAL_SCRATCH_DIR` jest opcjonalnym override dla lokalnego M.2;
   - domyślnie używany jest `LOCALAPPDATA\TeleM\amd_scratch`, następnie OS temp;
   - każda sesja otrzymuje unikalny katalog;
   - Stage A multi-file trafia do `*.temp_video.mp4` w tym katalogu;
   - katalog i plik są usuwane dopiero po poprawnym Stage C i atomowym rename;
   - po błędzie Stage A/Stage C plik Stage A pozostaje ścieżką recovery.
2. `stdout` live FFmpeg ustawiono na `DEVNULL`, a `stderr` nadal jest stale
   odczytywany przez dedykowany wątek.
3. Dodano `_wait_for_process_exit()` bez limitu czasu. Proces live mux jest
   kończony tylko po `cancel_event`; postęp pliku jest monitorowany przez
   `FinalizationTracker`, ale stagnacja nie wywołuje kill.
4. `stdin_closed` jest oznaczane po zakończeniu pompy i zamknięciu stdin.
   Dopiero potem startuje `ffmpeg_wait`, więc `ffmpeg_exit_wait_ms` mierzy
   faktyczne oczekiwanie od zamknięcia stdin do wyjścia procesu.
5. Dla AMD tracker ma jawny próg ostrzeżenia stagnacji 30 s.
6. Profil AMD otrzymuje `finalization`, `benchmark.stage_a` i `benchmark.stage_c`.
7. Log zawiera jednoznaczny routing `[AMD Scratch]` z `output_path`,
   `output_drive`, `scratch_dir`, `scratch_drive` i `stage_a_path`.
8. Profil i log zawierają per-clip: elapsed, FPS, producer/GPU/AMF/packet
   write avg oraz p90, a także średni `stage_a_file_growth_MBps`.
9. Finalization loguje epoch timestamps dla `stdin_closed` i oczekiwania FFmpeg,
   stan procesu oraz rzeczywisty `ffmpeg_exit_wait_ms`. Stage C loguje lokalny
   rozmiar wejścia, rozmiar wyjścia USB, wzrost MB/s, elapsed i koniec.

## 5. Testy

```text
python -m pytest tests/test_amd_direct_mp4_mux.py tests/test_finalization_tracker.py tests/test_multifile_avg_speed.py -q
18 passed in 7.92s
```

Dodatkowo:

- `py_compile` dla eksportera, trackera i testów: PASS;
- `git diff --check` dla zmienionych plików: brak błędów w tych plikach;
- test local scratch: PASS;
- test braku elapsed-time timeoutu: PASS;
- test lifecycle multi-file i zachowania outputu przy błędzie: PASS.

## 6. REAL PROOF

### 6.1 Startup gate

Krótki smoke z pełnym logiem od inicjalizacji AMD do pierwszej klatki:

```text
AMD Native DLL: telem_amd_native.dll, ABI 9
[AMF] InitDX11 SUCCESS
[TELEM AMD DLL] telem_amd_create SUCCESS
[AMD NATIVE D3D11] Frame 3/300
```

Startup gate: **PASS**. Nie wystąpił przypadek „brak first frame”, więc nie
uruchamiano benchmarku FPS przed naprawą startupu.

### 6.2 Real multi-file boundary render

Użyto rzeczywistych plików projektu i kanonicznego FIT:

```text
Video/GX010114.MP4 -> Video/GX010115.MP4
FIT: Video/GX010114_116.fit
clip 1: 900 frames (30.03 s, końcówka GX010114)
clip 2: 1800 frames (60.06 s, początek GX010115)
total: 2700 frames / 90.09 s
output: F:\TeleM-real-proof-boundary\real_boundary_2700f.mp4
```

Dokładny log routingu:

```text
[AMD Scratch] output_path=F:\TeleM-real-proof-boundary\real_boundary_2700f.mp4 output_drive=F: scratch_dir=C:\TeleM-amd-proof-scratch-long\telem-amd-stage-6276-80cbguc8 scratch_drive=C: stage_a_path=C:\TeleM-amd-proof-scratch-long\telem-amd-stage-6276-80cbguc8\real_boundary_2700f.temp_video.mp4
```

Stage A był na `C:`, a duży finalny zapis na `F:`. Po zakończeniu katalog
scratch został opróżniony; na `F:` pozostał finalny MP4 i profil.

### 6.3 Measured per-clip diagnostics

Wartości pochodzą z profilu AMD z tego samego renderu; `ratio` oznacza
`clip 2 / clip 1`.

| metric | clip 1 | clip 2 | ratio |
|---|---:|---:|---:|
| frames | 900 | 1800 | 2.000x |
| elapsed | 23.954 s | 41.588 s | 1.736x |
| render FPS | 37.572 | 43.282 | 1.152x |
| producer avg / p90 | 0.026 / 0.034 ms | 0.027 / 0.034 ms | avg 1.031x |
| GPU completion avg / p90 | 21.949 / 31.719 ms | 18.313 / 31.550 ms | avg 0.834x |
| AMF submit avg / p90 | 0.157 / 0.201 ms | 0.156 / 0.204 ms | avg 0.995x |
| AMF query avg / p90 | 2.857 / 7.476 ms | 2.988 / 7.980 ms | avg 1.046x |
| packet write avg / p90 | 0.037 / 0.075 ms | 0.045 / 0.081 ms | avg 1.204x |

Stage A: `630,966,514 B`, average growth `9.163 MB/s`. Stage C read the
local Stage A file and produced `633,869,960 B` on `F:` in `9,829.00 ms`,
measured average USB growth `61.502 MB/s`.

### 6.4 Finalization and output proof

```text
[Finalize] stdin_closed ts_epoch=1788690447.062568
[Finalize] ffmpeg_wait_start ...
[Finalize] ffmpeg_wait_done: wait_ms=9829.23
[AMD Stage C] end ... usb_output_size_bytes=633869960 usb_growth_MBps=61.502 elapsed_ms=9829.00
Direct MP4 Mux complete ... frames=2700, audio=True
```

The long render had no hard-timeout/kill message. `ffprobe` verified:

```text
duration: 90.090 s
video: HEVC, nb_frames=2700
audio: AAC
```

W krótkim rerun po zmianie trackera Stage C zgłosił
`ffmpeg_wait_start ... ffmpeg_alive=True`; jego `ffmpeg_exit_wait_ms` wyniósł
`802.49 ms`.

Recovery/cleanup unit tests and the real successful cleanup path are PASS.
Failure recovery was not exercised against a real USB fault: **NOT TESTED**.
The full 50-minute proof remains **NOT TESTED**.

## 7. Ryzyka / regresje

- Jeśli nie da się utworzyć lokalnego scratch, multi-file kończy się
  kontrolowanym błędem zamiast wracać do zapisu dużego Stage A na USB.
- Brak hard timeoutu oznacza, że nieskończenie zawieszony FFmpeg wymaga
  anulowania przez użytkownika; tracker pokaże ostrzeżenie stagnacji.
- Ostrzeżenie o PTS/DTS dla raw HEVC pozostaje poza zakresem.
- Istniejące modyfikacje working tree nie były cofane.

## 8. Izolacja backendu

Zmiany eksportera dotyczą wyłącznie ścieżki AMD Native D3D11/AMF oraz jej
finalizacji. Nie zmieniano QSV/Intel, NVENC/CUDA ani rendererów NVIDIA.

## 9. Podsumowanie

```text
LOCAL STAGE A SCRATCH:       PASS (unit + real boundary render)
USB ONLY FINAL LARGE WRITE:  PASS (real 633,869,960 B Stage C output on F:)
FALSE HARD TIMEOUT REMOVED:  PASS
FINALIZATION TIMING:         PASS (real stdin/FFmpeg wait timestamps)
STAGE A RECOVERY:            PASS by implementation/tests; real USB fault NOT TESTED
CLIP FPS DIAGNOSTICS:        PASS (real 2700-frame boundary render)
REAL AMD USB STABILITY:      PASS for 90.09 s proof; 50-min NOT TESTED
FINAL STATUS:                PASS for requested short REAL PROOF; full-duration proof NOT TESTED
```
