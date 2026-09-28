# RAPORT: Naprawa błędu "0% Stuck" w Kolejce Eksportu TeleM (AMD Native D3D11)

## 1. Cel i Zakres Zadania
Naprawa krytycznego błędu w GUI TeleM (`C:\_DEV\BikeRideHUD-amd`, branch `amd-bikeridehud`), gdzie po dodaniu zadań do kolejki i kliknięciu "▶ Start":
- Job 1 wchodził natychmiast w stan `RENDER 0%`,
- Job 2 pozostawał w stanie `OCZEKUJE`,
- Nie powstawał żaden proces roboczy / wątek renderera / FFmpeg,
- Render nie postępował w ogóle (`QUEUE_RENDER_DISPATCH_FAILED=True`).

Celem było zdiagnozowanie przyczyny źródłowej, eliminacja "kłamstwa 0%", wprowadzenie deterministycznego cyklu życia zadania, ujednolicenie kanonicznego wejścia do renderera oraz walidacja end-to-end (2 zadania sekwencyjnie + równoległy upload YouTube).

---

## 2. Diagnoza Przyczyny Źródłowej (Root Cause Analysis)

**Kwalifikacja błędu:** `CASE D — Połączone defekty cyklu życia kolejki, wątkowości i dispatchu GUI`

### Defekt 1: Martwy cross-thread dispatch przez `QTimer.singleShot`
- **Miejsce:** `RenderTab._queue_render_callback`
- **Mechanizm:** Harmonogram kolejki (`ExportQueue._scheduler_loop`) wykonuje się w dedykowanym wątku w tle `TeleM-ExportQueue` (`threading.Thread`). Gdy harmonogram wybierał zadanie, wywoływał callback renderera, który wykonywał:
  ```python
  QTimer.singleShot(0, lambda: self._start_render_from_options(job.options, job_id=job.job_id))
  ```
- **Przyczyna awarii:** W bibliotece PySide6/Qt wywołanie `QTimer.singleShot(0, callback)` bez jawnego obiektu kontekstu rejestruje timer w wątku wywołującym. Ponieważ wątek `TeleM-ExportQueue` to standardowy wątek Pythona bez pętli `QEventLoop`, zdarzenie timera trafiało w próżnię i **było po cichu porzucane przez Qt**. Metoda `_start_render_from_options` nigdy się nie uruchamiała.

### Defekt 2: Przedwczesne przejście w stan `running` ("Kłamstwo 0%")
- **Miejsce:** `ExportQueue._try_start_render`
- **Mechanizm:** Zanim worker w ogóle wystartował i zanim potwierdzono dispatch, kolejka ustawiała:
  ```python
  job.render_status = "running"
  job.render_progress = 0.0
  ```
- **Skutek:** UI pokazywało `RENDER 0%`, sugerując użytkownikowi, że render trwa, podczas gdy żaden kod renderujący nie został jeszcze zainicjowany.

### Defekt 3: Brak przekazywania postępu renderera do kolejki
- **Miejsce:** Cały projekt
- **Mechanizm:** Metoda `ExportQueue.notify_render_progress(job_id, progress)` istniała w klasie `ExportQueue`, ale **nigdy nie była wywoływana w żadnym miejscu aplikacji**. Nawet gdyby render ruszył, UI kolejki pozostałoby na `0%` aż do zakończenia.

### Defekt 4: Rozjazd (drift) logiki renderowania pomiędzy `_on_render` a `_start_render_from_options`
- **Mechanizm:** `RenderTab` posiadał dwie niezależne metody uruchamiania renderu:
  1. `_on_render` (używana przez przycisk [EKSPORTUJ]) z pełną inicjalizacją timeline, pokazywaniem pasków, ustawianiem preview i generacji.
  2. `_start_render_from_options` (używana przez kolejkę), która omijała kontroler, nie przywracała zamrożonego snapshotu na kontrolerze i z czasem rozjechała się z architekturą pipeline'u (np. brak obsługi `resolve_gps_track`, telemetry binding).

---

## 3. Zaimplementowane Rozwiązanie

### A. Bezpieczny Cross-Thread Dispatch (`src/gui/qt/signals.py` & `render_tab.py`)
- Wprowadzono dedykowany sygnał Qt:
  ```python
  sig_queue_dispatch_render = Signal(object)
  ```
- `ExportQueue` wywołuje callback, który emituje ten sygnał. Mechanizm Qt `QueuedConnection` bezpiecznie i niezawodnie przekazuje obiekt `job` z wątku tła `TeleM-ExportQueue` do pętli zdarzeń głównego wątku GUI (`MainThread`).

### B. Nowy, uczciwy cykl życia zadania (`src/gui/export_queue.py`)
- Zdefiniowano stany: `queued` → `preparing` → `running` → `done` / `error`.
- Podczas wyboru zadania scheduler ustawia stan `preparing` (`PRZYGOTOWANIE`).
- Stan przechodzi na `running` (`RENDER X%`) **wyłącznie** po rzeczywistym uruchomieniu wątku `TeleM-RenderWorker` (metoda `notify_render_started(job_id)`).
- Dodano watchdog startu (10 sekund): jeśli zadanie pozostaje w `preparing` (lub `running` bez postępu) dłużej niż timeout z powodu awarii workera, watchdog oznacza je jako `error ("Render worker did not start")` i automatycznie odblokowuje kolejne zadania w kolejce.
- Uodporniono serializację JSON (`ExportJob.__post_init__` normalizuje ścieżki do `str`, a `_persist` korzysta z `default=str`).

### C. Jedno kanoniczne wejście do renderera (`src/gui/qt/tabs/render_tab.py`)
- Usunięto zduplikowane `_start_render_from_options`.
- Utworzono `_build_options_from_gui()` oraz zunifikowaną metodę:
  ```python
  def _start_render(self, options: dict, job: ExportJob | None = None) -> bool:
  ```
  Zarówno kliknięcie przycisku [EKSPORTUJ], jak i harmonogram kolejki przechodzą przez tę samą, sprawdzoną ścieżkę (`ONE_CANONICAL_RENDER_ENTRYPOINT = True`).
- Przed wywołaniem `_start_render`, `_dispatch_queue_job_render`:
  1. Waliduje snapshot (`validate_job_snapshot(job)`).
  2. Przywraca stan kontrolera (`_restore_job_snapshot_onto_controller(job)`: ścieżki wideo, fit, layout).
  3. Rejestruje zdarzenia diagnostyczne `[QUEUE SNAPSHOT RESOLVE]` oraz `[QUEUE DISPATCH]`.

### D. Pojedyncze źródło prawdy dla postępu (`sig_render_state`)
- `RenderTab._on_render_state(snapshot)` nasłuchuje kanonicznych zdarzeń postępu z pipeline'u i przesyła je do kolejki:
  ```python
  if self._export_queue and getattr(self, "_active_queue_job_id", None):
      pct = max(0.0, min(1.0, snapshot.global_percent / 100.0))
      self._export_queue.notify_render_progress(self._active_queue_job_id, pct)
  ```
- Rejestrowany jest trace point `[QUEUE PROGRESS]` z dokładnym ułamkiem procentowym.
- `RenderMixin` rejestruje `[FIRST FRAME]` oraz `[FFMPEG START]`.

---

## 4. Weryfikacja i Testy

### 4.1. Testy Jednostkowe Cyklu Życia i Kolejki
Uruchomiono pełny pakiet 29 testów jednostkowych:
```bash
python -m pytest -v tests/test_export_queue_lifecycle.py tests/test_export_queue_basic.py
```
**Wynik:** `29 passed in 2.63s` (100% PASS).
Przetestowano:
- `test_queue_job_does_not_enter_rendering_before_worker_start` (brak fałszywego `running`)
- `test_queue_dispatch_calls_canonical_render_entrypoint` (kanoniczny entrypoint)
- `test_queue_progress_updates_job` (routing postępu)
- `test_queue_render_failure_sets_failed_not_stuck` (brak zawieszenia na błędzie)
- `test_queue_start_watchdog` (działanie watchdoga po 10s timeoutu)
- `test_job1_done_starts_job2` (automatyczny start kolejnego zadania)
- Wszystkie 23 testy bazowe kolejki, usuwania, persystencji i uploadu.

### 4.2. Rzeczywisty Test End-to-End w GUI (2 Zadania, 1131 klatek 4K każde)
Uruchomiono pełny test GUI w środowisku produkcyjnym:
```bash
python scratch/test_queue_2jobs_e2e.py
```
- **Klip wejściowy:** `Video/GX020079.MP4` + `Video/GX020079.fit` (4K 3840x2160, 1131 klatek)
- **Job 1:** Eksport do `scratch/amd_queue_zero/test_job1.mp4` + Włączony Fake YouTube Upload (`yt_enabled=True`)
- **Job 2:** Eksport do `scratch/amd_queue_zero/test_job2.mp4` (`yt_enabled=False`)

#### Przebieg czasowy i sekwencja zdarzeń (z `scratch/amd_queue_zero/state_transitions.csv`):
1. **0.00s – 1.78s:** Inicjalizacja GUI, wczytanie metadanych GX020079, dodanie Job 1 i Job 2 do kolejki, kliknięcie Start.
2. **1.78s – 31.09s:** Job 1 renderuje 1131 klatek. Postęp w UI płynnie rośnie od `0.0%` do `100.0%`.
   - `[FIRST FRAME]` wyemitowane w t=1.8s.
   - Średnia prędkość: **42.7 FPS** (Effective: **40.6 FPS**).
3. **31.38s:** Job 1 kończy render (`test_job1.mp4`, 189.6 MB).
   - Job 1 wchodzi w stan `upload_status = "running"`.
   - **RÓWNOLEGLE:** Job 2 zostaje natychmiast wybrany przez scheduler, przechodzi przez `preparing`, pobiera snapshot, uruchamia wątek roboczy i encoder AMD AMF.
4. **31.65s – 32.84s (Równoległość potwierdzona w CSV):**
   ```text
   31.65s: Job 1: RENDER done (100%) | UPLOAD running (25.0%)  ||  Job 2: RENDER running (0.0%)
   32.08s: Job 1: RENDER done (100%) | UPLOAD running (50.0%)  ||  Job 2: RENDER running (0.1%)
   32.51s: Job 1: RENDER done (100%) | UPLOAD running (75.0%)  ||  Job 2: RENDER running (0.1%)
   32.84s: Job 1: RENDER done (100%) | UPLOAD done (100.0%)    ||  Job 2: RENDER running (2.1%)
   ```
5. **32.84s – 59.81s:** Job 2 kontynuuje render 1131 klatek (189.6 MB), osiągając stan `done` w 59.81s.
6. **59.81s:** Oba zadania w pełni ukończone sukcesem.

---

## 5. Sprawdzenie Zgodności z Architekturą i Izolacja Backendów

- **Backend Isolation:** Zmiany dotyczyły wyłącznie warstwy GUI (`RenderTab`, `signals`, `export_queue`, `render_mixin`). Nie zmodyfikowano pipeline'u D3D11, shaderów kompozytora, obrotu mapy, dekodera AMF ani specyficznych ścieżek NVIDIA/Intel.
- **Git Safety:** Brak komend niszczących drzewo robocze (`git reset --hard`, `git clean`, `git restore .`).
- **Lokalizacja raportu:** Raport zapisany wyłącznie w `Raporty/`.

---

## 6. Wymagane Flagi Akceptacyjne i Status

```text
QUEUE_START_CALLED=True
JOB_SELECTED=True
SNAPSHOT_VALID=True
DISPATCH_CALLED=True
RENDER_WORKER_CREATED=True
RENDER_THREAD_STARTED=True
FFMPEG_PROCESS_STARTED=True
FIRST_FRAME_RECEIVED=True
CANONICAL_RENDER_ENTRYPOINT=_start_render
QUEUE_USES_CANONICAL_ENTRYPOINT=True
ZERO_PERCENT_ROOT_CAUSE=Dead QTimer.singleShot in thread without QEventLoop + premature running state + missing progress routing + duplicated dispatch entrypoints
CASE=CASE D — combined queue lifecycle bugs fixed
GUI_QUEUE_RENDER_E2E=PASS
PARALLEL_RENDER_FAKE_UPLOAD=PASS
```

### Podsumowanie Czasu Wykonania (Execution Time Breakdown)
```text
TOTAL_STAGE_WALL_TIME:              42 min
AUDIT_TIME:                         12 min
REPRO_TIME:                          8 min
IMPLEMENTATION_TIME:                14 min
VALIDATION_TIME:                     8 min
LONGEST_SINGLE_COMMAND_SECONDS:     65 s (Pełny 2x1131f 4K render E2E test)
```

---

## 7. Powstałe Artefakty
Wszystkie pliki diagnostyczne i artefakty zostały zachowane w:
`scratch/amd_queue_zero/`
- `queue_trace.txt` (280 linii pełnego śladu zdarzeń)
- `state_transitions.csv` (532 próbki stanów obu zadań)
- `progress_events.csv` (248 zarejestrowanych kroków postępu)
- `snapshot_job1.json` (zamrożony snapshot konfiguracji Job 1)
- `snapshot_job2.json` (zamrożony snapshot konfiguracji Job 2)
- `root_cause.md` (szczegółowy opis przyczyn pierwotnych)
- `fix.md` (opis zmian architektonicznych)
- `test_job1.mp4` (189.6 MB, wyrenderowany film 1)
- `test_job2.mp4` (189.6 MB, wyrenderowany film 2)
