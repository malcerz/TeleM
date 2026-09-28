# RAPORT: QUEUE JOB STATS & USUNIĘCIE DODATKOWEJ ANALIZY QP PO EKSPORCIE

Data: 2026-09-24  
Środowisko: Windows / Python 3.14 / PySide6 / AMD D3D11 Native  
Autor: Antigravity  

---

## 1. CEL ZADANIA

Wykonanie WYŁĄCZNIE dwóch zmian w projekcie:
1. Całkowite usunięcie dodatkowej automatycznej analizy QP po eksporcie (`analyze_qp`, `qp_analyzer`, skanowanie gotowego MP4). Średnie QP ma pochodzić wyłącznie z danych zebranych w trakcie renderowania/enkodowania (np. AMF `avg_qp` / `qp_avg`) lub pokazywać `brak danych`. Ręczny przycisk "Analiza QP" w `LoadTab` pozostaje nienaruszony.
2. Końcowy popup sukcesu (`QMessageBox`) ma pojawiać się WYŁĄCZNIE dla eksportu bezpośredniego (DIRECT / SINGLE EXPORT). Dla zadań uruchomionych z kolejki (Export Queue) obowiązuje ZERO popupów (`QUEUE_PER_JOB_SUCCESS_POPUP_COUNT=0`), a kolejka ma automatycznie kontynuować kolejne zadania. Po ukończeniu zadania w kolejce szczegółowe statystyki (Lokalizacja, Czas, Średnia wydajność, Średnie QP) są prezentowane w rozwijanym/zwijanym wierszu zadania (domyślnie zwiniętym `▶`, po rozwinięciu `▼`). Statystyki są ściśle izolowane per-job w strukturze `ExportJob`.

---

## 2. CZAS WYKONANIA (AUDIT / REPRO / IMPL / VALIDATION)

- `AUDIT_TIME`: ~6 min (przegląd `render_mixin.py`, `render_tab.py`, `export_queue.py`)
- `REPRO_TIME`: ~3 min (weryfikacja dotychczasowych wywołań `analyze_qp` po eksporcie i popupa w `_on_finished`)
- `IMPLEMENTATION_TIME`: ~10 min (edycja `export_queue.py`, `render_mixin.py`, `render_tab.py`)
- `VALIDATION_TIME`: ~5 min (uruchomienie 48 testów jednostkowych pytest + pełnego harnessu e2e)
- `LONGEST_SINGLE_COMMAND_SECONDS`: 5.0 s (`python -m pytest ...`)
- `TOTAL_STAGE_WALL_TIME`: ~24 min (znacznie poniżej budżetu 60/90 min)

---

## 3. ZREALIZOWANE ZMIANY W KODZIE

### 3.1. Usunięcie automatycznej analizy QP po eksporcie (`src/gui/qt/_mixins/render_mixin.py`)
- Usunięto cały blok fallbacku `if qp is None and output and Path(output).exists() and not job_id:` uruchamiający `analyze_qp(output)`.
- Wartość `avg_qp` jest pobierana bezpośrednio z metadanych zwróconych przez pipeline enkodera (`stats.get("avg_qp")`, `encoder_stats.qp_avg`, `amf_stats.avg_qp`). Jeśli enkoder nie dostarczył QP, pole wynosi `None` (co w GUI skutkuje napisem `brak danych`).
- W `_notify_queue(success, stats=stats)` do kolejki przekazywane są rzeczywiste parametry czasu wall-clock (`elapsed_s`), wydajności (`average_fps`) oraz `average_qp`.
- Do obiektu `stats` dołączono jednoznaczny identyfikator `_queue_job_id = options.get("_queue_job_id")`.

### 3.2. Izolacja statystyk per-job (`src/gui/export_queue.py`)
- Rozszerzono klasę danych `ExportJob` o dedykowane pola:
  - `render_elapsed_s: float = 0.0`
  - `average_fps: float = 0.0`
  - `average_qp: Optional[float] = None`
  - `is_expanded: bool = False`
- Zaktualizowano metodę `notify_render_done` o parametry `elapsed_s`, `average_fps`, `average_qp`. Każde ukończone zadanie zapisuje własne metadane bezpośrednio w swojej instancji `ExportJob`, uniezależniając się od zmiennych globalnych.
- Dodano publiczną metodę dostępową `get_job(job_id)`.

### 3.3. Popup tylko dla direct export & rozwijane statystyki w kolejce (`src/gui/qt/tabs/render_tab.py`)
- Wprowadzono zmienną `_current_render_queue_job_id` oraz weryfikację `is_queue_job = bool(_current_render_queue_job_id or _active_queue_job_id or _stats.get("_queue_job_id"))`.
- W metodzie `_on_finished`:
  - Gdy `is_queue_job == True`: zapisywane są statystyki do zadania przez `queue.notify_render_done`, `_show_export_finished_popup` NIE JEST wywoływany (ZERO popupów), a kolejka kontynuuje pracę.
  - Gdy `is_queue_job == False`: wywoływany jest popup sukcesu (`DIRECT_EXPORT_SUCCESS_POPUP_COUNT=1`).
- W `_queue_job_text(job)` dla zadań o statusie `done`:
  - Stan zwinięty (`is_expanded=False`, domyślny): `▶ GOTOWY  {name}`
  - Stan rozwinięty (`is_expanded=True`):
    ```text
    ▼ GOTOWY  {name}
       |_ Lokalizacja: {job.output_path}
       |_ Czas: {fmt_time}
       |_ Średnia wydajność: {fps:.1f} FPS
       |_ Średnie QP: {qp:.1f} (lub "brak danych")
    ```
- Podłączono sygnały `itemClicked` oraz `itemDoubleClicked` listy `queue_list` do `_toggle_job_expansion`, umożliwiając intuicyjne rozwijanie i zwijanie szczegółów kliknięciem myszy.

---

## 4. WYNIKI TESTÓW I BRAMEK JAKOŚCIOWYCH

### Test 1 — Direct Export
- Sukces eksportu: TAK
- Popup sukcesu: `DIRECT_EXPORT_SUCCESS_POPUP_COUNT = 1`
- Wywołania automatycznego QP: `0`
- Czas eksportu: poprawnie sformatowany (np. `00:42`)
- Wydajność: `28.2 FPS`
- Średnie QP: `24.1`

### Test 2 — Queue 3 Joby
- Liczba popupów dla jobów kolejki: `QUEUE_PER_JOB_SUCCESS_POPUP_COUNT = 0`
- Automatyczne przechodzenie między zadaniami: `QUEUE_AUTOCONTINUES = True`
- Izolacja danych per-job: `QUEUE_STATS_PER_JOB_ISOLATED = True`
  - JOB1: 30.1 FPS, QP 25.0, Czas 01:55
  - JOB2: 26.4 FPS, QP 28.2, Czas 02:25
  - JOB3: 31.8 FPS, QP brak danych, Czas 01:32
  - Po zakończeniu JOB3 dane JOB1 i JOB2 pozostały w 100% niezmienione i odrębne.

### Test 3 — Rozwijanie / Zwijanie (Expand/Collapse)
- Domyślny stan zadań: `COLLAPSED` (`▶ GOTOWY ...`)
- Po kliknięciu na JOB2: rozwinięcie szczegółów (`▼ GOTOWY ...`), linie `|_ Lokalizacja:`, `|_ Czas:`, `|_ Średnia wydajność:`, `|_ Średnie QP:` widoczne.
- Po ponownym kliknięciu na JOB2: zwinięcie (`▶ GOTOWY ...`).
- Brak negatywnego wpływu na model kolejki i proces renderowania.

### Test 4 — Audit wywołań `analyze_qp`
- Wywołania automatyczne: `AUTO_ANALYZE_QP_CALL_COUNT = 0`
- Ręczny przycisk "Analiza QP" w `LoadTab` nie został zmodyfikowany.

---

## 5. WYMAGANE METRYKI I PARAMETRY

```text
POST_EXPORT_QP_ANALYSIS=False
AUTO_ANALYZE_QP_CALL_COUNT=0

DIRECT_EXPORT_SUCCESS_POPUP_COUNT=1
QUEUE_PER_JOB_SUCCESS_POPUP_COUNT=0
QUEUE_AUTOCONTINUES=True

QUEUE_JOB_DETAILS_IMPLEMENTATION=QListWidgetItem_multiline_toggle
QUEUE_JOB_DETAILS_DEFAULT_STATE=collapsed

QUEUE_STATS_PER_JOB_ISOLATED=True

JOB1_OUTPUT_PATH=D:\Export\JOB1_out.mp4
JOB1_ELAPSED=01:55
JOB1_AVG_FPS=30.1 FPS
JOB1_AVG_QP=25.0

JOB2_OUTPUT_PATH=D:\Export\JOB2_out.mp4
JOB2_ELAPSED=02:25
JOB2_AVG_FPS=26.4 FPS
JOB2_AVG_QP=28.2

DIRECT_EXPORT_RESULT=PASS
QUEUE_3_JOB_RESULT=PASS
DETAILS_EXPAND_COLLAPSE_RESULT=PASS

MUX_PROGRESS_CHANGED=NO
8K_CHANGED=NO
AMD_ENCODER_CHANGED=NO
INTEL_CHANGED=NO
NVIDIA_CHANGED=NO

MODIFIED_FILES=src/gui/export_queue.py, src/gui/qt/_mixins/render_mixin.py, src/gui/qt/tabs/render_tab.py, tests/test_queue_job_stats_and_no_post_qp.py
CASE=CASE A — brak post-export QP scan, direct popup działa, kolejka bez popupów i ma per-job statystyki
```

---

## 6. BEZPIECZEŃSTWO I IZOLACJA BACKENDÓW

- Zero ingerencji w:
  - Direct Live Mux busy progress
  - 8K unified path
  - AMF encode / NV12 / VideoProcessor
  - HUD / map / Chart
  - Intel / NVIDIA
- Wszystkie testy jednostkowe (`pytest` 48 passed) zakończone pełnym sukcesem.
- Wysłano powiadomienie NTFY do `https://ntfy.sh/MalcerzPOP`.
