# RAPORT AMD: State, Queue & Layout Persistence Cleanup

## 1. TASK
Uporządkowanie zarządzania stanem aplikacji TeleM / SportCamHUD:
1. Kolejka eksportu automatycznie zapisywana i odczytywana przy starcie aplikacji (`QUEUE_AUTOLOAD_ON_START = True`).
2. Przywrócenie widocznego i funkcjonalnego przycisku `STOP` w kolejce eksportu (`btn_queue_stop`).
3. Naprawa `Resetuj układ` (`_on_reset_layout`): zerowanie wskaźników (`INDICATOR_COUNT = 0`), czyszczenie selekcji/properties/cache, czysty podgląd, bez odtwarzania/nadpisywania sidecara.
4. Całkowite wyeliminowanie automatycznego tworzenia plików `*.layout.json` obok filmów w katalogu materiałów (`NEW_LAYOUT_SIDECAR_FILES_CREATED = 0`). Przeniesienie sesji aktywnego układu do `%LOCALAPPDATA%\SportCamHUD\session\active_layout.json`.
5. Ręczny eksport i import kolejki eksportu (`.telemqueue.json`) z niezmiennym snapshotem layoutu i bez tokenów/danych poufnych (`TOKENS_EXPORTED = False`).
6. Architektoniczne uniezależnienie render queue: każdy job posiada w pełni odizolowany snapshot layoutu (`ACTIVE_JOB_DECOUPLED_FROM_GUI_STATE = True`).

---

## 2. STATUS & CASE
- **STATUS:** PASS
- **CASE:** CASE A — full state/persistence cleanup complete

---

## 3. AUDIT (Pkt 1)

### 3.1. SIDECAR_CREATE_CALLS
Zidentyfikowano miejsca tworzenia i zapisu plików `*.layout.json` obok materiałów wideo:
- `src/gui/qt/_mixins/preset_mixin.py`: metoda `_save_project_layout()` tworzyła plik `Path(self.video_paths[0]).with_suffix(".layout.json")` i zapisywała layout na dysku przy każdym:
  - `on_property_changed` (zmiana dowolnej właściwości wskaźnika)
  - `on_indicator_dropped` (dodanie wskaźnika)
  - `_on_render_clicked` (rozpoczęcie renderu)
  - `_on_reset_layout` (reset układu nadpisywał sidecar pustym stanem lub go tworzył)

### 3.2. SIDECAR_AUTOLOAD_CALLS
- `src/gui/qt/_mixins/project_mixin.py`: w metodzie `open_project()` sprawdzano `Path(self.video_paths[0]).with_suffix(".layout.json")`. Jeśli plik istniał, layout był wczytywany. Plik ten był jednak traktowany jako domyślny plik roboczy, do którego potem `_save_project_layout` stale zapisywał.

### 3.3. RESET_LAYOUT_CALL_CHAIN
- Sygnał `sig_reset_layout` z paska `DataStreamBar` (`reset_btn`) -> `AppController._on_reset_layout()` -> `IndicatorMixin._on_reset_layout()`.
- Wcześniej: `_on_reset_layout()` czyścił `self.layout['indicators']`, ale wywoływał `self._save_project_layout()`, co powodowało zapis pustego sidecara na dysku obok wideo lub konflikty przy ponownym otwarciu. Ponadto, jeśli wideo miało stary sidecar, ponowne otwarcie lub przeładowanie przywracało wskaźniki z dysku, uniemożliwiając rzeczywiste zresetowanie stanu w pamięci.

---

## 4. CHANGED FILES
1. `src/gui/export_queue.py`:
   - Wersjonowanie schematu kolejki: `QUEUE_FORMAT_NAME = "SportCamHUD Export Queue"`, `QUEUE_FORMAT_VERSION = 1`.
   - Klasa `ExportJob`: obsługa statusu `interrupted` dla `render_status` i `upload_status`, aktualizacja `is_done()`.
   - `ExportQueue.__init__`: opcjonalny parametr `appdata_dir` dla elastycznego testowania i izolacji.
   - `_persist()`: atomowy zapis (plik tymczasowy `.tmp` + `os.replace`) do `%LOCALAPPDATA%\SportCamHUD\export_queue.json` w formacie słownika ze schematem `version: 1`.
   - `_load_persisted()`: migracja formatu v0 (lista) do v1 (słownik z metadanymi), obsługa awarii/restartu aplikacji (stan `running`/`preparing` -> `interrupted` z błędem `"Przerwano (restart aplikacji)"`).
   - `export_to_file(filepath)`: eksport zadań do pliku `.telemqueue.json` z wyczyszczeniem tokenów (`TOKENS_EXPORTED = False`).
   - `import_from_file(filepath, mode="append")`: walidacja schematu, regeneracja kolidujących ID, weryfikacja istnienia plików wideo (brak crasha, status `error`), wybudzenie schedulera.
   - Nowe metody pomocnicze: `get_active_render_id()`, `cancel_active_render(reason)`, `reorder_jobs(job_ids)`.

2. `src/gui/qt/_mixins/preset_mixin.py`:
   - Dodano `get_session_layout_path()` -> `%LOCALAPPDATA%\SportCamHUD\session\active_layout.json`.
   - Dodano `_save_session_layout()`: atomowy zapis aktywnej sesji layoutu do AppData.
   - Przekierowano `_save_project_layout()` oraz `get_project_layout_path()` do sesji w AppData, całkowicie eliminując tworzenie plików `*.layout.json` w katalogu wideo (`NEW_LAYOUT_SIDECAR_FILES_CREATED = 0`).

3. `src/gui/qt/_mixins/indicator_mixin.py`:
   - `_on_reset_layout()`: zeruje `self.layout['indicators'] = {}`, `INDICATOR_COUNT = 0`, czyści zaznaczenie, bboxy, właściwości w panelu, cache podglądu, odświeża scenę i zapisuje pusty stan wyłącznie do sesji w AppData. Nie dotyka katalogu materiałów wideo.

4. `src/gui/qt/_mixins/project_mixin.py`:
   - Legacy sidecar (`video.layout.json`) jest traktowany jako read-only import do pamięci RAM. Żadne późniejsze edycje ani reset nie modyfikują tego pliku ani nie wiążą z nim stanu aplikacji.

5. `src/gui/qt/_mixins/render_mixin.py`:
   - Całkowite odizolowanie aktywnego renderu: renderer korzysta z `effective_layout = options.get("layout") or self.layout`, deep-kopiowanego wraz z wyciętymi regionami. Render worker jest niezależny od późniejszych manipulacji layoutem w GUI.
   - Zapis layoutu przy renderze odbywa się do sesji AppData, a nie obok wideo.

6. `src/gui/qt/tabs/render_tab.py`:
   - Rozszerzenie paska narzędzi kolejki o przyciski: `Dodaj`, `Usuń`, `Importuj`, `Eksportuj`, `Start`, `Pauza`, oraz wyrazisty czerwony przycisk `⏹ STOP` (`btn_queue_stop`).
   - Implementacja obsługi: `_on_queue_stop()`, `_on_queue_export()`, `_on_queue_import()`.
   - Inicjalizacja kolejki przy starcie (`set_controller` -> `_init_export_queue`).
   - Formatowanie statusu `PRZERWANO` w liście zadań.

7. `tests/test_state_queue_layout_persistence.py`:
   - Kompleksowy zestaw 17 testów jednostkowych i integracyjnych pokrywających wszystkie wymagania specyfikacji.

8. `tests/test_export_queue_basic.py`:
   - Aktualizacja testów do uwzględnienia parametru `appdata_dir` i statusu `interrupted`.

---

## 5. EXACT IMPLEMENTATION & BEHAVIOR

| Cecha | Przed zmianą | Po zmianie |
| :--- | :--- | :--- |
| **Kolejka: Autoload** | Ręczny lub brak gwarancji | `QUEUE_AUTOLOAD_ON_START = True` automatycznie przy starcie kontrolera/RenderTab |
| **Kolejka: Format zapisu** | Płaska lista w `%APPDATA%\SportCamHUD\export_queue.json` | Schemat v1 ze strukturą `{"format": "...", "version": 1, "jobs": [...]}` |
| **Kolejka: Zapis na dysk** | Standardowy `open()` | Atomowy `os.replace` przez plik tymczasowy `.tmp` |
| **Kolejka: Crash recovery** | Zadanie wisiało w `running`/`preparing` | Automatyczna tranzycja do `interrupted` z błędem `"Przerwano (restart aplikacji)"` |
| **Kolejka: Kontrolki** | Brak przycisku `STOP` | Dostępne: `Start`, `Pauza`, `⏹ STOP`, `Importuj`, `Eksportuj` |
| **Przycisk STOP** | Nieobecny | Anuluje aktywny proces renderu, pauzuje scheduler, zachowuje resztę kolejki |
| **Resetuj układ** | Zostawiał śmieci / nadpisywał sidecar | Zeruje `INDICATOR_COUNT = 0`, czyści podgląd i właściwości, nie dotyka wideo |
| **Pliki obok wideo** | Tworzone automatycznie `*.layout.json` | `NEW_LAYOUT_SIDECAR_FILES_CREATED = 0` (katalog wideo pozostaje czysty) |
| **Lokalizacja sesji** | Katalog wideo | `%LOCALAPPDATA%\SportCamHUD\session\active_layout.json` |
| **Legacy sidecar** | Źródło prawdy i cel zapisu | Read-only import do pamięci RAM przy otwarciu wideo |
| **Eksport/Import kolejki** | Brak | Pełne wsparcie dla `.telemqueue.json` (wersja 1, sanityzacja tokenów) |
| **Decoupling layoutu** | Render modyfikował/czytał wspólny layout | Render job posiada niezmienny snapshot w pamięci RAM |

---

## 6. TESTS & VERIFICATION

### 6.1. Pytest Test Suites
Uruchomiono pełen zestaw powiązanych testów regresji:
```bash
python -m pytest tests/test_state_queue_layout_persistence.py tests/test_export_queue_basic.py tests/test_export_queue_lifecycle.py tests/test_icon_rendering_regression.py tests/test_render_tab_controls_cleanup.py -v
```
Wynik:
```text
============================= 59 passed in 4.57s ==============================
```
Wszystkie 59 testów zakończone statusem **PASSED**:
- `tests/test_state_queue_layout_persistence.py`: 17 passed
- `tests/test_export_queue_basic.py`: 23 passed
- `tests/test_export_queue_lifecycle.py`: 6 passed
- `tests/test_icon_rendering_regression.py`: 5 passed
- `tests/test_render_tab_controls_cleanup.py`: 8 passed

### 6.2. Real GUI Smoke Check
Uruchomiono `scratch/gui_state_smoke_check.py` weryfikujący działanie w środowisku PySide6 z rzeczywistym `AppController`, `MainWindow` i `RenderTab`:
- `QUEUE_AUTOLOAD_ON_START = PASS`
- `STOP_BUTTON_VISIBLE = PASS`
- `RESET_LAYOUT_CLEARS_IN_MEMORY = PASS`
- `NEW_LAYOUT_SIDECAR_FILES_CREATED = 0`
- `RESET_LAYOUT_WITH_LEGACY_SIDECAR = PASS`
- `QUEUE_EXPORT_IMPORT = PASS`
- Zrzut wizualny wygenerowany i zweryfikowany: `render_tab_queue_smoke_proof.png`.

---

## 7. BACKEND ISOLATION & REGRESSIONS
- **AMD GPU Native D3D11 Pipeline:** Nienaruszony. Wszystkie shadery, bufory i architektura renderera pozostały bez zmian.
- **Wskaźniki / Lean / Mapy / Homografia:** Nienaruszone.
- **NVIDIA / Intel Backends:** Nienaruszone.
- **Bezpieczeństwo Git:** Brak operacji destrukcyjnych (`git reset`, `git clean`, itp.).

---

## 8. TIME BREAKDOWN
- `TOTAL_STAGE_WALL_TIME`: ~45 min (limit: TARGET <= 75 min, HARD STOP = 100 min)
- `AUDIT_TIME`: ~10 min
- `REPRO_TIME`: ~5 min
- `IMPLEMENTATION_TIME`: ~20 min
- `VALIDATION_TIME`: ~10 min
- `LONGEST_SINGLE_COMMAND_SECONDS`: 4.57 s (uruchomienie 59 testów pytest)

---

## 9. FINAL SUMMARY
Wszystkie 5 punktów zadania zostały w pełni zaimplementowane i przetestowane:
1. Kolejka eksportu posiada wersjonowaną, atomową persystencję i automatyczny autoload.
2. Przycisk `STOP` został przywrócony i prawidłowo obsługuje zatrzymanie aktywnego renderu z zachowaniem kolejki.
3. `Resetuj układ` działa wyłącznie w pamięci RAM, zeruje liczbę wskaźników do 0 i nie tworzy ani nie psuje plików sidecar.
4. Zaśmiecanie katalogów wideo plikami `*.layout.json` zostało w 100% wyeliminowane.
5. Eksport/Import kolejki `.telemqueue.json` działa poprawnie i bezpiecznie (bez tokenów).
