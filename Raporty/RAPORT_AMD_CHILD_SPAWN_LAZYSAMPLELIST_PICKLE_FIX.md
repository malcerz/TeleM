# AMD CHILD PROCESS — LazySampleList pickle/spawn fix

## TASK

Naprawa rzeczywistego crashu eksportu AMD z GUI podczas Windows
`multiprocessing.get_context("spawn")`, bez wyłączania child-process containment,
GPU frame tap ani produkcyjnych ścieżek GPU HUD.

## INITIAL STATE

- branch: `integration/intel-amd`
- HEAD: `59277b4`
- Python: `3.14.7`, 64-bit, Windows spawn
- working tree był i pozostał dirty; istniejących zmian użytkownika nie
  odrzucano ani nie resetowano
- crash odtworzono lokalnie przed poprawką przez `pickle.dumps` / `loads`:

```text
File "src/telemetry_processed_cache.py", line 98, in extend
    not self._materialized
AttributeError: 'LazySampleList' object has no attribute '_materialized'
```

Sam `pickle.dumps` materializował przy tym listę w parent.

## ROOT CAUSE — PYTHON 3.14 RECONSTRUCTION ORDER

Domyślny pickle dla subclass `list` używa osobno bazowej zawartości listy i
instance/slot state. Empiryczny disassembly protokołu 5 na Pythonie 3.14.7
pokazał kolejność:

```text
NEWOBJ
APPEND / APPENDS
... slot state ...
BUILD
```

Obiekt powstaje więc bez wykonania `LazySampleList.__init__`; elementy bazowej
listy są dodawane przed `BUILD`, który dopiero odtwarza sloty. Override
`extend()` został wywołany zanim istniały `_arr`, `_is_vector`, `_tz_aware` i
`_materialized`. GPU frame tap nie uczestniczył w błędzie.

## PICKLE CONTRACT

Wybrano jawny kontrakt descriptor/data zależny od rzeczywistego stanu:

- lazy/unmaterialized: pickle zapisuje tablicę NumPy, `is_vector` i `tz_aware`;
  nie iteruje listy i nie tworzy obiektów `datetime`/tuple;
- materialized lub po mutacji: pickle zapisuje autorytatywne tuple listy, bez
  dublowania starej `_arr`;
- top-level factory `_rebuild_lazy_sample_list` zawsze wywołuje normalny
  konstruktor, a więc inicjalizuje wszystkie sloty przed ewentualnym
  `list.extend`;
- `__reduce_ex__` i `__reduce__` prowadzą do tego samego kontraktu;
- `__getstate__`/`__setstate__` nie są potrzebne: cały legalny stan jest w
  argumentach factory, bez późnego `BUILD`;
- nie są serializowane Qt objects, locki, wątki, file handles, ctypes/D3D11 ani
  callbacki GUI.

Nie zastosowano jednopunktowego `hasattr/getattr` hacku.

## LAZYSAMPLELIST STATE AND MUTATOR AUDIT

Jawnie obsłużono:

```text
append, extend, insert, __setitem__, __delitem__, clear,
pop, remove, __iadd__, __imul__, sort, reverse
```

Każda mutacja pracuje na logicznej zawartości. `extend` nadal zachowuje szybkie
łączenie dwóch kompatybilnych lazy tablic. `sort(key=...)` materializuje dane,
ponieważ dowolnego callbacka `key` nie wolno zastąpić sortowaniem samego
timestampu. `__new__` pozostaje bezpiecznym wbudowanym `list.__new__`, ponieważ
pickle nie korzysta już z domyślnego list-subclass restore; `__init__`
inicjalizuje komplet slotów.

Przetestowano:

- empty lazy array;
- lazy/unmaterialized;
- materialized;
- cache-backed z normalnego processed-cache load;
- po `append`, `extend` i pozostałych mutatorach;
- timezone-aware i naive timestamps;
- zachowanie tuple/list values;
- brak materializacji parent podczas pickle;
- brak `AttributeError`.

Osobny stan „partially materialized” nie istnieje w kontrakcie klasy:
`_materialized` przełącza się atomowo przed zapełnieniem bazowej listy.

## REAL RENDERJOB

Test opt-in użył dokładnie produkcyjnych builderów:

```text
ProjectMixin._load_single_clip_telemetry
ProjectMixin._merge_clip_telemetry
TelemetryDataManager.load_fit
RenderMixin._render_pipeline
```

Dane:

```text
D:\GoPro\2026-09-01\GX010244.MP4
D:\GoPro\2026-09-01\GX010245.MP4
D:\GoPro\2026-09-01\12_naprawiony.fit
D:\GoPro\2026-09-01\GX010244.layout.json
```

Wynik preflight `pickle.dumps(render_job)`:

```text
pickle size:                         48,967,053 B (46.70 MiB)
pickle time:                         1,647.337 ms
parent private peak delta:           112,660,480 B (107.44 MiB)
parent private retained delta/GC:      3,690,496 B (3.52 MiB)
```

Top-level job zawierał wyłącznie dane, m.in. `str`, `list`, `dict`,
`pathlib.WindowsPath`, `datetime`, `numpy.float64`, `VideoTimeline` i
`FitDataset`.

Znalezione lazy pola:

```text
field_samples.accel_x_samples
field_samples.accel_y_samples
field_samples.accel_z_samples
field_samples.accel_magnitude_samples
field_samples.gyro_x_samples
field_samples.gyro_y_samples
field_samples.gyro_z_samples
field_samples.gyro_magnitude_samples
```

Każde miało 274,920 próbek i 4,398,720 B array storage. Wszystkie osiem
pozostało w stanie `lazy`; łączny backing array payload to 35,189,760 B.

Nie wdrożono nowej warstwy cache-path transport. Realny payload jest
ograniczony i nie materializuje milionów obiektów Python; descriptor transport
byłby osobną przebudową provenance/merge cache, niewymaganą do poprawnego i
zmierzonego kontraktu w tym etapie.

## CHILD DIAGNOSTICS

Dodano jednorazowe, nie-per-frame znaczniki:

```text
[AMD CHILD SPAWN] parent_pid=... generation=...
[AMD CHILD START] child_pid=...
[AMD CHILD JOB RESTORED] generation=...
[AMD CHILD NATIVE INIT] telem_amd_create
[AMD CHILD RENDER START] generation=...
```

Parent otrzymuje ponadto niezawodny komunikat `job_restored`; zmierzony czas od
`Process.start()` do odtworzenia joba wyniósł:

```text
Preview ON:  1,730.605 ms
Preview OFF: 1,824.983 ms
Cancel run:  1,736.819 ms
```

Zamknięcie pipe po kontrolowanym błędzie zostało utwardzone: końcowy Windows
`poll()` traktuje `EOFError/OSError/BrokenPipeError` jako zamknięty kanał,
zamiast wywracać parent.

## REAL 300-FRAME AMD RENDERS

Test obejmował 150 końcowych klatek `GX010244` i 150 początkowych klatek
`GX010245`, 3840x2160, 30000/1001, aktualny layout i FIT.

```text
Preview ON:
  backend:     AMD_NATIVE_D3D11_GPU_HUD_GPU_HUD_D3D11VA
  output:      HEVC 3840x2160 + AAC
  frames:      300/300
  duration:    10.010 s
  size:        41,147,056 B
  true_fps:    25.640
  render_fps:  39.409
  effective:   23.968
  preview:     external GPU frame callbacks received at 960x540

Preview OFF:
  backend:     AMD_NATIVE_D3D11_GPU_HUD_GPU_HUD_D3D11VA
  output:      HEVC 3840x2160 + AAC
  frames:      300/300
  duration:    10.010 s
  size:        41,147,056 B
  true_fps:    26.082
  render_fps:  40.399
  effective:   24.388
```

Identyczny rozmiar obu finalnych plików jest dodatkowym sygnałem, że GPU
Preview nie zmienia strumienia finalnego. Nie jest to formalny pixel-reference
A/B.

## CANCEL / ERROR / PREVIEW RESTORE

- real cancel ustawiono po progress `completed >= 120`; zachowany Stage A miał
  121 poprawnych klatek HEVC;
- child zakończył się, holder parent został wyczyszczony;
- read-only `Win32_Process` check nie znalazł orphan `spawn_main` / AMD child;
- kontrolowany błąd nieznanego argumentu został poprawnie przekazany do parent;
- bez restartu aplikacji uruchomiono drugi child z kontrolowanym błędem;
- oba zostały zakończone, bez orphanów;
- istniejące testy Edit/Export Preview restore po complete/fail/cancel przeszły.

## CHANGED FILES

- `src/telemetry_processed_cache.py` — jawny pickle contract i pełny mutator audit;
- `src/ffmpeg/amd_child_process.py` — preflight diagnostyka, startup IPC/logi,
  bezpieczny closed-pipe poll;
- `src/ffmpeg/amd_native_exporter.py` — tylko marker rzeczywistego native init
  aktywny w AMD child;
- `tests/test_telemetry_processed_cache.py` — stany, mutatory i real Windows spawn;
- `tests/test_amd_child_process.py` — diagnostyka oraz error containment/restart;
- `tests/test_amd_child_spawn_real.py` — opt-in real GUI job i 300f ON/OFF/cancel;
- `Raporty/RAPORT_AMD_CHILD_SPAWN_LAZYSAMPLELIST_PICKLE_FIX.md`.

Pliki te częściowo zawierały wcześniejsze niecommitowane zmiany; raport opisuje
wyłącznie zakres bieżącej poprawki.

## TESTS

PASS:

```text
targeted LazySampleList/cache/child:                 18 passed
AMD preview + restore + Intel/NVIDIA isolation:      56 passed
real GUI RenderJob serialization:                     1 passed
real AMD Preview ON/OFF + cancel:                      1 passed
py_compile changed Python modules/tests:              PASS
git diff --check task files:                          PASS
```

`git diff --check` pokazał wyłącznie informacyjne ostrzeżenia o przyszłej
konwersji LF/CRLF w już modyfikowanych plikach.

## NOT TESTED / NOT PROVEN

- pełny 85,574-frame render: NOT TESTED zgodnie z poleceniem;
- formalne surface-before-HEVC pixel parity: NOT PROVEN; kod HUD/compositingu
  nie został zmieniony;
- pięć kolejnych długich eksportów i długookresowy plateau parent private
  memory: NOT TESTED;
- pełny dirty repository suite: NOT TESTED.

## BACKEND ISOLATION

- Intel/QSV i NVIDIA/NVENC/CUDA nie zostały zmienione;
- marker native init jest warunkowy na `TELEM_AMD_CHILD_PROCESS=1` i znajduje
  się wyłącznie w AMD native exporter;
- GPU Preview pozostał `gpu_frame_tap`; nie włączono HEVC sidecar;
- `AMD_RENDER_CHILD_PROCESS=0` pozostał wyłącznie diagnostycznym override;
- AMD child-process containment pozostaje produkcyjnie włączony;
- HUD i Preview nie zostały wizualnie zmienione.

## REGRESSIONS / RISKS

- Jawny preflight `pickle.dumps` dodaje około 1.65–1.75 s i chwilowy peak około
  107 MiB przed każdym child start. Po zwolnieniu payload zmierzony retained
  delta wyniósł 3.52 MiB. Jest to wymagana diagnostyka i nie materializuje lazy
  telemetryki, ale można ją w przyszłości ograniczyć flagą po zakończeniu
  okresu produkcyjnego audytu.
- Cancel zachowuje częściowy Stage A zgodnie z istniejącą polityką recovery;
  testowy artefakt miał 121 klatek.
- Descriptor/cache-path transport pozostaje możliwą późniejszą optymalizacją,
  ale nie jest potrzebny dla poprawności ani obecnego ograniczonego payloadu.

## FINAL SUMMARY

```text
LAZYSAMPLELIST PICKLE:                    PASS
WINDOWS SPAWN ROUNDTRIP:                  PASS
REAL RENDERJOB SERIALIZATION:             PASS
NO ATTRIBUTEERROR:                        PASS
GPU PREVIEW ON:                           PASS
GPU PREVIEW OFF:                          PASS
REAL AMD CHILD START:                     PASS
SHORT REAL RENDER:                        PASS (300/300 ON, 300/300 OFF)
CANCEL:                                   PASS (requested >=120, stopped at 121)
PARENT SURVIVES CHILD ERROR:               PASS (two sequential errors)
NO ORPHAN CHILD:                          PASS
NO EXCESSIVE TELEMETRY MATERIALIZATION:    PASS
INTEL/NVIDIA ISOLATION:                   PASS

STATUS: READY
```
