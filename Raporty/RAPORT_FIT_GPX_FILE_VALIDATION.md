# RAPORT — bezpieczna walidacja FIT/GPX względem czasu wideo

## TASK

Weryfikacja wybranego FIT/GPX względem pełnego, absolutnego zakresu czasu wideo; bezpieczne odrzucenie błędnego pliku, transakcyjne ładowanie, dialog override oraz brak uruchomienia SmartSync przed akceptacją.

## INITIAL STATE

- FIT był wybierany i ładowany w `ProjectMixin._on_files_selected`, a SmartSync znajdował się wewnątrz `TelemetryDataManager.load_fit` / `load_gpx`.
- GPMF telemetry pozostaje źródłem absolutnego czasu wideo; dla multi-clip zakres jest liczony jako min(start) / max(end) wszystkich klipów.
- Stan roboczy był modyfikowany w metodach ładowania przed pełnym zakończeniem parsera/synchronizacji.

## IMPLEMENTATION

- Dodano `src/telemetry_file_validation.py` z UTC-aware normalizacją, pełnym overlap, nearest gap, start delta, klasyfikacją `VALID/WARNING/INVALID/UNKNOWN` i kompaktowym logiem diagnostycznym.
- FIT i GPX są parsowane do danych tymczasowych przed decyzją użytkownika. `fit_path`, `gpx_path`, strumienie telemetrii i map preload nie są zatwierdzane przy anulowaniu.
- `VALID` jest akceptowany automatycznie. Dla `WARNING`, `INVALID` z możliwością override oraz GPX bez `<time>` pojawia się standardowy Qt `QMessageBox` z przyciskami `Anuluj` i `Wczytaj mimo to`; `Anuluj` jest domyślny.
- Uszkodzony FIT/GPX dostaje przyjazny komunikat, a traceback parsera trafia wyłącznie do logu konsoli. Progres jest kończony także po błędzie, anulowaniu lub braku ffmpeg/ffprobe.
- Po akceptacji dane są ładowane istniejącymi metodami, więc algorytm SmartSync pozostaje niezmieniony; odrzucony kandydat nie dochodzi do `load_fit`/`load_gpx`.
- GPX bez znaczników czasu ma stan `UNKNOWN/NO_TIMESTAMPS`. Override jest dostępny, ale istniejący parser nie tworzy sztucznych timestampów, więc taki plik nie jest udawany jako zsynchronizowana telemetria.

## ACCEPTANCE MATRIX

| Kryterium | Wynik |
|---|---|
| FIT same activity / overlap | PASS |
| FIT wrong hour / wrong date | PASS — `DATE_TIME_MISMATCH` |
| GPX same activity / wrong hour / wrong date | PASS |
| GPX bez `<time>` | PASS — `UNKNOWN/NO_TIMESTAMPS`, override dostępny |
| Corrupt FIT / corrupt GPX | PASS — `INVALID`, przyjazny komunikat |
| Cancel zachowuje poprzedni FIT/GPX | PASS — test transakcyjny |
| Override akceptuje mismatch | PASS |
| Odrzucony plik nie uruchamia SmartSync | PASS |
| Multi-clip pełny zakres | PASS |
| Dialog wyłącznie w GUI thread | PASS — signal + `QMessageBox` |

## TESTS

```text
python -m pytest -q tests/test_fit_gpx_file_validation.py tests/test_activity_ux_timeline.py tests/test_gpmf_native_perf_and_cache_clear.py
50 passed in 0.72s

python -m py_compile src/telemetry_file_validation.py src/gui/qt/_mixins/project_mixin.py src/gui/qt/main_window.py src/gui/telemetry_manager.py tests/test_fit_gpx_file_validation.py
PASS

git diff --check -- <task files>
PASS
```

## NTFY

Wysłano 3/3 prób na `https://ntfy.sh/MalcerzPOP`; wszystkie zakończyły się `EXIT_CODE=0`. Pełne stdout/stderr/exit są dopisane do `ntfy_result.txt`.

## CHANGED FILES

- `src/telemetry_file_validation.py` — nowy walidator zakresów.
- `src/gui/qt/_mixins/project_mixin.py` — walidacja przed commit, pełny zakres video, deferred map preload, obsługa progresu/błędów.
- `src/gui/qt/main_window.py` — GUI prompt.
- `src/gui/qt/signals.py` — request signal.
- `src/gui/telemetry_manager.py` — commit stanu FIT/GPX dopiero po udanym przetworzeniu.
- `tests/test_fit_gpx_file_validation.py` — 15 testów akceptacyjnych.
- `ntfy_result.txt` — 3 próby powiadomienia.

## BACKEND ISOLATION / RISKS

- Nie zmieniano parsera GPMF, cache telemetrii, renderera AMD, AMF, capability system, NVIDIA, Intel, queue scheduler, map renderer ani SmartSync algorithm.
- Nie wykonywano benchmarku renderera — brak zmiany ścieżki wydajnościowej.
- Pełny GUI smoke z realnym kliknięciem dialogu nie był uruchamiany w tej sesji; pokrycie decyzji użytkownika jest testowane przez helpery walidacji.
- Override dla bezczasowego GPX nie generuje sztucznych dat; plik pozostaje bez zsynchronizowanych danych, aby nie wprowadzać fałszywego czasu.

## TIME BREAKDOWN

```text
TOTAL_STAGE_WALL_TIME=~20 min (observed wall-clock estimate)
AUDIT_TIME=~5 min
REPRO_TIME=~1 min
IMPLEMENTATION_TIME=~10 min
VALIDATION_TIME=~4 min
LONGEST_SINGLE_COMMAND_SECONDS=1.5
```

## FINAL

PASS — zakresy FIT/GPX są walidowane bezpiecznie przed commit i przed SmartSync; testy jednostkowe/regresyjne oraz kompilacja przeszły.
