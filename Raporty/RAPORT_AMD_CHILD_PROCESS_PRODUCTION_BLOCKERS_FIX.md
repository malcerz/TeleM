# AMD CHILD PROCESS — PRODUCTION BLOCKERS FIX

## Zadanie

Naprawa wyłącznie trzech blockerów produkcyjnej ścieżki AMD:

1. bounded zakończenie parent IPC/render session,
2. respektowanie normalnego GUI `IN/OUT` / `cut_regions` przez AMD native,
3. usuwanie `.part.temp_video.mp4` po anulowaniu przez użytkownika.

Branch: `integration/intel-amd`  
HEAD początkowy: `59277b4`  
Working tree był i pozostał dirty; istniejące zmiany użytkownika zostały zachowane.

## Stan początkowy

- Child containment, osobne PID-y i odzyskiwanie pamięci natywnej były już wdrożone.
- Poprzednia macierz 5 × 1000f spełniała kryterium plateau.
- Normalne GUI tworzyło `cut_regions`, ale AMD native otrzymywał pełny `VideoTimeline`.
- Cancel w pętli klatek zachowywał Stage A jako recovery artifact, pozostawiając produkcyjny plik `.part.temp_video.mp4`.
- Poprzedni harness nie zapisywał rekordu po 10000f i został zinterpretowany jako brak terminalnego `completed`.

## Root cause „terminal hang”

Rekonstrukcja logów wykazała, że parent `TeleM-RenderWorker` nie był miejscem obserwowanego zawieszenia:

- `[EXPORT PREVIEW GPU TAP STOP] reason=render_end` może wystąpić dopiero po odebraniu `RenderProgressState.completed` i wykonaniu `RenderTab._end_render()`;
- dotychczasowy harness wykonywał następnie synchronicznie, na wątku GUI, `ffprobe -count_frames` dla pliku 10000f o rozmiarze około 1.86 GB;
- rekord JSON był zapisywany dopiero po zakończeniu tego pełnego skanu, więc brak rekordu błędnie wyglądał jak brak terminalu parent.

Dokładny blokowany wait znajdował się zatem w pomocniczym `subprocess.run(ffprobe -count_frames)` w `after_cleanup()`, nie w produkcyjnym workerze. Harness używa teraz bounded, 30-sekundowego odczytu indeksowanej metadanej `nb_frames`, bez pełnego skanowania ramek.

Jednocześnie stara pętla parent miała realną podatność: po `Connection.poll()` wykonywała `recv()` w tym samym wątku, bez niezależnego deadline dla EOF/terminal/process death. Została zastąpiona bounded state machine:

- daemon reader wykonuje blokujące `recv()` poza workerem i przekazuje kompletne wiadomości do ograniczonej kolejki;
- osobno rejestrowane są `terminal_received`, `ipc_eof` i `process_exit`;
- terminal + żywy child ma limit 10 s do zakończenia procesu;
- exit child bez EOF ma limit 5 s na drain;
- cancel ma istniejący limit 15 s;
- exit/EOF bez terminalu kończy się jawnym `RuntimeError`, nigdy domniemanym sukcesem;
- success wymaga równocześnie terminalu `complete`, exit code 0 i istniejącego niepustego outputu;
- holder child jest czyszczony w `finally`.

W realnej próbie kolejność końcowa była deterministyczna:

```text
terminal_received(kind=complete)
ipc_eof
process_exit(exitcode=0)
RenderProgressState.completed
render_end / Preview release
rendering=False / worker stopped
```

## GUI IN/OUT — canonical range contract

Dodano `VideoTimeline.subset_excluding(cut_regions)`. Metoda:

- normalizuje, przycina, sortuje i scala wykluczone zakresy na skompresowanej osi projektu GUI;
- wylicza ich dopełnienie;
- dzieli retained intervals na granicach klipów;
- konwertuje je do source-local `(clip_index, local_start, local_end)`;
- deleguje tworzenie planu do istniejącego `VideoTimeline.subset()`.

`stream_overlay_to_ffmpeg()` rozwiązuje ten plan tylko przy dispatchu AMD native. Do AMD przekazywane są ten sam effective timeline, wynikający z niego duration i layout z już skonsumowanym `cut_regions=[]`. Fallback software zachowuje oryginalny timeline i oryginalne `cut_regions`, więc zakres nie jest stosowany podwójnie. Ścieżki Intel/NVIDIA nie zostały zmienione.

Testy kontraktowe przy 30 fps:

| Przypadek | Retained source-local ranges | GUI / AMD / decoded / native / muxed |
|---|---|---:|
| A: 1 clip, środek 5–12 s | clip1 5–12 s | 210 / 210 / 210 / 210 / 210 |
| B: 2 clips, tylko clip1 2–8 s | clip1 2–8 s | 180 / 180 / 180 / 180 / 180 |
| C: przecięcie granicy 8–14 s | clip1 8–10 s + clip2 0–4 s | 180 / 180 / 180 / 180 / 180 |
| D: tylko clip2 12–18 s | clip2 2–8 s | 180 / 180 / 180 / 180 / 180 |
| E: cały timeline 10+20 s | oba pełne klipy | 900 / 900 / 900 / 900 / 900 |

Pełne wycięcie timeline jest jawnie odrzucane przez `ValueError`.

Realny GUI range 10000f przeciął granicę `GX010244 → GX010245`:

```text
GUI planned:       10000
AMD requested:     10000
decoded:           10000
native processed:  10000
AMF output:        10000
muxed:             10000
per clip:          5000 + 5000
output duration:   333.666667 s
```

Nie uruchomiono pełnego renderu 85574f.

## Cancel cleanup

`_abort_direct_mux()` rozróżnia teraz:

- błąd/finalization failure: zachowanie Stage A według istniejącej polityki recovery;
- jawny cancel: usunięcie tylko incomplete artifacts (`.part`, `.part.temp_video.mp4`, audio concat), bez możliwości przekazania do helpera ścieżki finalnego MP4.

Ta sama polityka cancel obowiązuje w pętli renderującej i podczas Stage C remux.

Test katalogu:

```text
przed: final MP4 + .part + .part.temp_video.mp4 + .audio.concat.txt
po:    final MP4
```

Realny cancel przy klatce 300:

```text
terminal=cancelled
child exitcode=0
child exited=True
output-specific residue=[]
Preview restored=True
rendering=False
next render completed=True
```

Kontrolowany błąd child przekazał pełny traceback przez IPC, child zakończył się, holder został wyczyszczony, a kolejny rzeczywisty render rozpoczął się i zakończył poprawnie. Zgodnie ze scope logiczny błąd nadal może mieć OS exit code 0.

## Realna macierz GUI / sprzętowa

Harness: `scratch/run_amd_child_final_gui_acceptance.py`  
Wyniki: `D:\GoPro\2026-09-01\TeleM_child_final_acceptance_20260908_111923\acceptance_results.json`

| Run | Terminal | PID | Parent terminal po child | Muxed | Preview frames | Residue |
|---|---|---:|---:|---:|---:|---|
| 1 | completed | 22092 | 0.238 s | 1000 | 67 | none |
| 2 | completed | 12612 | 0.232 s | 1000 | 67 | none |
| 3 | completed | 4100 | 0.221 s | 1000 | 67 | none |
| 4 | completed | 11364 | 0.227 s | 1000 | 67 | none |
| 5 | completed | 12648 | 0.220 s | 1000 | 67 | none |
| cancel@300 | cancelled | 23868 | 0.224 s | n/a | 20 | none |
| post-cancel | completed | 24240 | 0.230 s | 1000 | 67 | none |
| controlled error | failed | 7052 | n/a | n/a | 0 | none |
| 10000 | completed | 19236 | 0.400 s | 10000 | 667 | none |
| post-10000 | completed | 3032 | 0.232 s | 1000 | 67 | none |

Dla każdego zakończonego/cancelled run: child nie pozostał aktywny, `rendering=False`, worker nie żył, przycisk render był aktywny i Edit Preview był widoczny.

10000f:

- final MP4: 1,863,728,432 bytes;
- native render FPS: 41.698;
- effective FPS: 40.194;
- video render wall: 239.820 s;
- final mux: 3.920 s;
- total native export: 248.796 s;
- parent end-to-end (łącznie z pickle/GUI cleanup): 287.119 s.

## Pamięć, uchwyty i wątki

Pięć kolejnych 1000f zostało ocenionych przez istniejące kryterium harness jako `plateau_ok=True`.

```text
parent private bytes:
3,017,256,960
3,122,757,632
3,206,787,072
3,265,802,240
3,320,524,800

handles: 1215, 1209, 1209, 1209, 1209
threads: 68, 66, 66, 66, 67
```

Nie jest to zerowy wzrost pamięci: private wzrosło o około 303 MiB między run 1 i 5, ale kolejne przyrosty malały, tail pozostawał w progu 500 MiB, a handles/threads ustabilizowały się. Po 10000f parent private wynosiło 3,477,925,888 B, a po następnym renderze 3,499,589,632 B. Child peak private dla 10000f wyniósł 2,930,655,232 B i został odzyskany wraz z wyjściem procesu.

Koszt pickle pozostawiono bez zmian: około 106.16 MB oraz 12.35–13.86 s; startup child około 14–15 s.

## Testy

```text
python -m py_compile ...
PASS

pytest (range, child IPC, direct mux/cancel,
multifile, progress, Preview restore, GPU tap, spawn)
44 passed, 2 skipped
```

Pominięte zostały wyłącznie opt-in testy wymagające `TELEM_AMD_CHILD_CLIP_1` oraz `TELEM_AMD_CHILD_REAL_RENDER=1`; ich pokrycie funkcjonalne zapewnił pełny rzeczywisty GUI harness powyżej.

`git diff --check`: PASS (tylko istniejące ostrzeżenia Git LF→CRLF).

Windows Event Log od startu macierzy:

```text
Event 2004: none
DWM crash: none
D3D11/TDR/display reset: none
```

## Zmienione pliki

- `src/multifile.py` — canonical complement/subset timeline.
- `src/ffmpeg/streaming.py` — AMD effective range plan przy dispatchu.
- `src/ffmpeg/amd_child_process.py` — bounded parent IPC lifecycle state machine.
- `src/ffmpeg/amd_native_exporter.py` — jawne cancel cleanup bez kasowania finalnego MP4.
- `scratch/run_amd_child_final_gui_acceptance.py` — bounded ffprobe, realne GUI IN/OUT, timeout terminalu, residue/readiness/inventory assertions, post-10000 render.
- `tests/test_amd_gui_range_contract.py` — przypadki A–E i full-cut rejection.
- `tests/test_amd_child_process.py` — terminal+EOF oraz EOF bez terminalu.
- `tests/test_amd_direct_mp4_mux.py` — directory cleanup i zachowanie finalnego outputu.

## Izolacja backendów i ryzyka

- Nie zmieniono kodu Intel/QSV ani NVIDIA/NVENC/CUDA.
- Wspólna metoda `VideoTimeline` jest addytywna; jej użycie produkcyjne w tej zmianie ogranicza się do dispatchu AMD.
- Nie zmieniono wizualnego HUD ani kolejności warstw.
- Nie optymalizowano `LazySampleList`/pickle.
- Recovery Stage A przy rzeczywistym błędzie pozostało zachowane; tylko jawny cancel usuwa incomplete artifact.
- Bounded IPC celowo zwraca error przy braku terminalu zamiast zgadywać sukces.

## Finalna ocena

```text
PARENT TERMINAL HANG: FIXED
10000 CHILD EXIT → PARENT COMPLETED: PASS (0.400 s)
EDIT PREVIEW RESTORE AFTER 10000: PASS
NEXT RENDER AFTER 10000: PASS
GUI IN/OUT AMD RANGE: PASS
CROSS-CLIP RANGE: PASS
NO FULL-TIMELINE OVERRUN: PASS
CANCEL TEMP CLEANUP: PASS
NO ORPHAN CHILD: PASS
5 SEQUENTIAL RENDERS: PASS
MEMORY PLATEAU: PASS (existing bounded criterion; non-zero growth disclosed)
NO NEW EVENT 2004/DWM/D3D11: PASS

STATUS: READY
```
