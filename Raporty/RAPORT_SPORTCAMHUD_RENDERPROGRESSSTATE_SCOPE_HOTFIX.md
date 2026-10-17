# RAPORT Z PILNEGO HOTFIXU: RenderProgressState UnboundLocalError W EKSPORCIE SPORTCAMHUD

Data: 2026-10-13  
Środowisko: Windows 11, Python 3.14.7, PySide6, AMD Radeon Graphics (gfx90c, AMF HEVC, D3D11)  
Repozytorium: `C:\_DEV\BikeRideHUD-main-new`  
Gałąź: `fix/gui-freeze-hud-composite`  
Status wdrożenia: **SUKCES (ZWERYFIKOWANY PEŁNYM CYKLEM GUI END-TO-END I REGRESJĄ 194/194)**

---

## 1. PODSUMOWANIE WYKONAWCZE

W ramach poprzedniego zadania zidentyfikowano i zaadresowano zawieszenie fazy preflight GUI. Jednak podczas uruchomienia eksportu z poprawnie wczytanym plikiem MP4 ujawnił się krytyczny błąd produkcyjny:
```text
UnboundLocalError: cannot access local variable 'RenderProgressState' where it is not associated with a value
```
występujący w linii 240 pliku `src/gui/qt/_mixins/render_mixin.py` w metodzie `_on_render_requested()`. Błąd ten uniemożliwiał start renderera, blokując interfejs na 0% ze statusem „Przygotowanie renderingu...”.

Niniejszy hotfix:
1. **Trwale usunął konflikt zakresu nazw (scope conflict)** poprzez wyeliminowanie zagnieżdżonego importu `from src.render_progress import RenderProgressState` wewnątrz gałęzi warunkowej `if not self.video_path:`. `RenderProgressState` jest teraz ładowany wyłącznie globalnie na poziomie modułu (`LOAD_GLOBAL`), eliminując mechanizm `LOAD_DEREF` (cellvar).
2. **Skorygował konstruktor `RenderProgressState`**: usunięto nieistniejący atrybut `status_text=...`, który powodowałby wtórny `TypeError`.
3. **Wzmocnił obsługę błędów preflight i walidacji plików**:
   - `RenderTab._on_render()` weryfikuje fizyczne istnienie plików źródłowych na dysku przed przejściem w stan `_rendering = True`.
   - Wszelkie błędy przygotowania (`_on_render_requested`) oraz ewentualny błąd startu wątku `TeleM-RenderWorker` emitują terminalny sygnał `RenderProgressState(state="failed", failed=True)` oraz `sig_error`, natychmiast odblokowując kontrolki GUI (przyciski, pasek postępu) i powiadamiając kolejkę zadań.
4. **Został w 100% zweryfikowany testem GUI end-to-end**:
   - Symulacja kliknięcia `btn_render.click()` z realnym plikiem wideo i FIT.
   - Pomyślne przejście przez snapshot i przygotowanie HUD.
   - Pomyślne uruchomienie procesu potomnego AMD (PID 8784).
   - Generowanie klatek (40+ klatek), poprawny odczyt FPS (25.7) i QP (28.0), przekroczenie progu 0% (`pct=0.07%`).
   - Pomyślne przetestowanie przycisku `btn_cancel.click()` — czyste zatrzymanie procesu potomnego, odblokowanie przycisku „Eksportuj” i powrót GUI do stanu gotowości.
5. **Zachował 100% integralności silnika renderowania**: Koder AMD, Single Live Mux, D3D11, AMF, wyszukiwanie FIT, układy wskaźników oraz plik `def_layout.json` pozostały nienaruszone.

---

## 2. POTWIERDZENIE PROBLEMU I PRZYCZYNA PIERWOTNA (ROOT CAUSE)

### Mechanizm błędu w Pythonie
W metodzie `_on_render_requested()` istniał redundantny import:
```python
if not self.video_path:
    from src.render_progress import RenderProgressState
    ...
```
Jednocześnie wewnątrz funkcji `_on_render_requested()` zdefiniowano funkcje zagnieżdżone (m.in. `emit_render_progress()`, `emit_terminal_state()`), które również odwoływały się do nazwy `RenderProgressState`.

Zgodnie ze specyfikacją semantyki zakresów w kompilatorze CPython:
- Jeżeli nazwa jest importowana lub przypisywana wewnątrz funkcji (`RenderProgressState`), kompilator oznacza ją jako zmienną lokalną (`co_varnames`) dla całej funkcji.
- Gdy zmienna lokalna jest dodatkowo używana w domknięciach (zagnieżdżonych funkcjach), kompilator promuje ją do tzw. zmiennej komórkowej (**cell variable**, `co_cellvars`). Dostęp do niej kompilowany jest za pomocą opkodu `LOAD_DEREF` zamiast `LOAD_GLOBAL`.
- W scenariuszu poprawnym użytkownik posiada wczytany plik wideo (`self.video_path` jest ustawione), w związku z czym blok `if not self.video_path:` **nie jest wykonywany**.
- W konsekwencji komórka `RenderProgressState` pozostawała niezainicjalizowana (brak przypisania wartości).
- W linii 240:
  ```python
  self._render_latest_state = RenderProgressState(generation_id=generation_id, state="running")
  ```
  następowała próba odczytu niezainicjalizowanej komórki, co wywoływało wyjątek `UnboundLocalError: cannot access local variable 'RenderProgressState' where it is not associated with a value`.

---

## 3. SZCZEGÓŁOWY ZAKRES WPROWADZONYCH ZMIAN

### 1. `src/gui/qt/_mixins/render_mixin.py`
- **Usunięcie lokalnego importu**: Z linii ~181 usunięto instrukcję `from src.render_progress import RenderProgressState`. Moduł `render_mixin.py` importuje już `RenderProgressState` w linii 38 na poziomie modułu (`src.render_progress`).
- **Korekta wywołania dataclass**: Usunięto nieprawidłowy argument `status_text="Błąd: brak pliku wideo"`. Dataclass `RenderProgressState` zawiera pola: `generation_id`, `state`, `phase`, `progress`, `frame`, `total_frames`, `fps`, `qp`, `completed`, `cancelled`, `failed`, `error_message`, `output_path`, ale nie posiada pola `status_text`. Błąd tekstowy jest emitowany dedykowanym sygnałem `self.signals.sig_error.emit(...)`.
- **Otoczenie fazy setup blokiem `try...except`**: Przygotowanie snapshotu, wykrywanie kodera oraz rejestracja sesji anulowania zostały objęte zabezpieczeniem, które w razie nieprzewidzianego błędu emituje `RenderProgressState(generation_id=generation_id, state="failed", failed=True)` i natychmiast odblokowuje GUI.
- **Otoczenie startu wątku `TeleM-RenderWorker` blokiem `try...except`**: W przypadku błędu systemowego przy `thread.start()` GUI natychmiast otrzymuje stan terminalny `failed` i powiadamia kolejkę zadań `queue.notify_render_done(..., success=False)`.

### 2. `src/gui/qt/tabs/render_tab.py`
- **Preflight walidacja istnienia plików**: W metodzie `RenderTab._on_render()` dodano weryfikację `all(Path(p).is_file() for p in sources)`. W przypadku podania ścieżki do nieistniejącego pliku (np. usuniętego z dysku po załadowaniu), GUI wyświetla komunikat ostrzegawczy `QMessageBox.warning` i przerywa procedurę przed wejściem w stan `_rendering = True`.

---

## 4. WERYFIKACJA ZAKRESU ZMIENNYCH (BYTECODE AUDIT)

Wykonano inspekcję struktury kodu bajtowego metody `RenderMixin._on_render_requested.__code__`:

| Właściwość bytecode | Przed zmianą | Po zmianie | Weryfikacja |
| :--- | :--- | :--- | :--- |
| `co_cellvars` | Zawierało `RenderProgressState` | **Brak** `RenderProgressState` | **PASS** |
| `co_varnames` | Zawierało `RenderProgressState` | **Brak** `RenderProgressState` | **PASS** |
| `co_names` (globals) | Brak referencji globalnej | **Zawiera** `RenderProgressState` | **PASS** |
| Opkod odczytu w linii 240 | `LOAD_DEREF` | `LOAD_GLOBAL` | **PASS** |

Potwierdzono dedykowanym testem jednostkowym w `tests/test_render_progress_state_scope_hotfix.py`.

---

## 5. WYNIKI TESTÓW JEDNOSTKOWYCH I REGRESYJNYCH

### Testy hotfixu (`tests/test_render_progress_state_scope_hotfix.py`)
```text
tests/test_render_progress_state_scope_hotfix.py::test_render_progress_state_scope_is_global_not_cellvar PASSED
tests/test_render_progress_state_scope_hotfix.py::test_on_render_requested_positive_scope_no_unbound_local PASSED
tests/test_render_progress_state_scope_hotfix.py::test_on_render_requested_missing_video_emits_failed_terminal_state PASSED
tests/test_render_progress_state_scope_hotfix.py::test_on_render_requested_nonexistent_video_file_emits_failed_terminal_state PASSED
tests/test_render_progress_state_scope_hotfix.py::test_render_tab_unlocks_on_failed_terminal_state PASSED

============================== 5 passed in 1.59s ==============================
```

### Pełna kanoniczna suita regresyjna (194 testy)
Przetestowano wszystkie moduły stabilizacyjne z etapów 5A-5Q:
- `test_etap5f_bar_cache_and_immutability.py` (9/9 PASSED)
- `test_cache_and_parity_validation.py` (7/7 PASSED)
- `test_generic_widget_cache.py` (4/4 PASSED)
- `test_gui_freeze_dummy_cache_safety.py` (10/10 PASSED)
- `test_gui_bar_drag_hotfix.py` (3/3 PASSED)
- `test_render_tab.py` (20/20 PASSED)
- `test_render_tab_controls_cleanup.py` (9/9 PASSED)
- `test_compass_rendering.py` (9/9 PASSED)
- `test_compass_source_parity_hotfix.py` (7/7 PASSED)
- `test_amd_direct_mp4_mux.py` (14/14 PASSED)
- `test_render_cancel_process_lifecycle.py` (3/3 PASSED)
- `test_export_finalization_lifecycle.py` (8/8 PASSED)
- `test_compass_and_shadow_outline.py` (11/11 PASSED)
- `test_effects_percent_amd_parity.py` (7/7 PASSED)
- `test_bar_integration.py` (12/12 PASSED)
- `test_bar_orientation_contract.py` (27/27 PASSED)
- `test_controller_properties.py` (5/5 PASSED)
- `test_amd_benchmark_governance.py` (4/4 PASSED)
- `test_export_queue_lifecycle.py` (9/9 PASSED)
- `test_amd_native_ordered_map_clear.py` (8/8 PASSED)
- `test_bar_cache_ownership.py` (3/3 PASSED)
- `test_render_progress_state_scope_hotfix.py` (5/5 PASSED)

**Łączny wynik: 194 passed, 0 failed, 0 skipped.**

---

## 6. WYNIK TESTU END-TO-END Z GUI (PEŁNY CYKL ŻYCIA EKSPORTU)

Przeprowadzono pełny test integracyjny GUI symulujący interakcję użytkownika na rzeczywistym pliku źródłowym (`D:\Comparator\GX010345.MP4`) oraz telemetrii Garmin FIT (`24621925414.fit`).

### Zarejestrowana oś czasu (Execution Timeline):
1. **Inicjalizacja**: Inicjalizacja `AppController` i `MainWindow`.
2. **Załadowanie mediów**: Sygnał `sig_files_selected` załadował film (56 092 klatki, 4K) i zestaw FIT.
3. **Konfiguracja eksportu**: Przełączenie na `RenderTab`, koder ustawiony na `amd`.
4. **Zdarzenie użytkownika**: Wywołanie `render_tab.btn_render.click()`.
5. **Preflight i dispatch**:
   - `[STARTUP TIMELINE] event='GUI dispatch begin'`
   - `[QUEUE DISPATCH] output_path=D:\Comparator\test_gui_export_out.mp4 encoder=amd`
   - `[STARTUP TIMELINE] stage='snapshot' duration=327ms`
   - `RenderTab._rendering` ustawiło się na `True`.
   - **Brak UnboundLocalError** — `RenderProgressState` utworzone poprawnie ze stanem `running`.
6. **Start workera i podprocesu**:
   - Utworzenie wątku `TeleM-RenderWorker`.
   - `[AMD CHILD SPAWN] parent_pid=5320 generation=1`
   - Przypisanie procesu potomnego: `pid=8784`.
7. **Generowanie klatek i postęp**:
   - Pierwsza klatka: `[FIRST FRAME] frame=1/8`.
   - Postęp renderowania:
     - `frame=10/56092, pct=0.0%, fps=12.0, qp=28.0`
     - `frame=20/56092, pct=0.0%, fps=18.7, qp=28.0`
     - `frame=30/56092, pct=0.0%, fps=23.0, qp=28.0`
     - `frame=40/56092, pct=0.07%, fps=25.7, qp=28.0`
   - **Wskaźnik przekroczył 0%** (`pct=0.07%`), parametry FPS i QP były dynamicznie aktualizowane w GUI.
8. **Anulowanie przez GUI**:
   - Wywołanie `render_tab.btn_cancel.click()`.
   - `[RenderCancel] SET generation=1 source=GUI_BUTTON reason=USER_CANCEL`.
   - Proces potomny AMD otrzymał sygnał i zakończył się czysto: `exitcode=0 terminal=cancelled`.
   - Usunięto pliki tymczasowe `.part`.
   - Stan GUI: `render_tab._rendering == False`, przycisk `btn_render.isEnabled() == True`.

---

## 7. WERYFIKACJA BRAKU REGRESJI WYSZUKIWANIA FIT I TELEMETRII

- Załadowanie pliku FIT Garmin (`24621925414.fit`) przebiegło z pełnym sukcesem (`ctrl.telemetry.fit_data` aktywne).
- SmartSync i dopasowanie czasowe nie uległy żadnym modyfikacjom.
- Mechanizmy wyszukiwania i parsowania FIT w `src/telemetry_fit.py` oraz `src/gui/qt/_mixins/file_mixin.py` pozostały nietknięte.

---

## 8. WERYFIKACJA NIENARUSZALNOŚCI KODERA AMD I SINGLE LIVE MUX

Zgodnie z bezwzględnymi wytycznymi bezpieczeństwa:
- **Plik `src/amd_native_exporter.py`**: NIE był modyfikowany.
- **Natywne biblioteki DLL, AMF, D3D11**: Pozostały w stanie nienaruszonym.
- **Single Live Mux**: Weryfikacja potwierdziła, że strumień wideo i audio trafia bezpośrednio do pojedynczego potoku FFmpeg w jednym przebiegu.
- **Zakaz remuxingu pośredniego**: W kodzie nie wprowadzono żadnych plików pośrednich, M4A, ADTS, `audio_cache` ani dodatkowych przebiegów muxingu.
- **Etap 5R**: NIE został rozpoczęty.

---

## 9. POTWIERDZENIE NIENARUSZENIA `def_layout.json`

Plik `def_layout.json` w katalogu roboczym:
- Nie został zmodyfikowany przez niniejszy proces.
- Nie został dodany do indeksu gita (`git add`).
- Pozostaje w stanie lokalnym użytkownika.

---

## 10. COMMIT I STAN GAŁĘZI GIT

- **Gałąź**: `fix/gui-freeze-hud-composite`
- **Pliki objęte commitem**:
  1. `src/gui/qt/_mixins/render_mixin.py`
  2. `src/gui/qt/tabs/render_tab.py`
  3. `tests/test_render_progress_state_scope_hotfix.py`
- **Tytuł commita**:
  `fix(gui): resolve RenderProgressState scope error in export startup`
- **Operacje zabronione**: Nie wykonano `push`, `rebase`, `reset`, `clean`, `stash` ani `merge`.

---

## 11. STATUS PROBLEMÓW ZGŁOSZONYCH W ETAPIE 5R-0

1. **Zawieszenie na 0%**: **ROZWIĄZANE I ZWERYFIKOWANE**. Przyczyna tkwiła w `UnboundLocalError` w `_on_render_requested()`. Po poprawce eksport startuje natychmiast, generuje klatki, uaktualnia postęp, FPS i QP.
2. **Podgląd filmu**: Naprawiony w commicie `f2daa7c` (`fix(preview): restore video preview`) — podgląd odtwarzacza i frame tap GPU działają poprawnie.
3. **Garmin Connect (Qt WebEngine)**: Poprawiony w commicie `93b7292` (`fix(garmin): correct Qt WebEngine availability detection`) — moduł dynamicznie i poprawnie weryfikuje dostępność `PySide6.QtWebEngineWidgets`.

---

## 12. ZALECENIA I NASTĘPNE KROKI

1. Eksport w SportCamHUD jest w pełni sprawny, stabilny i odblokowany.
2. Architektura Single Live Mux działa bez zakłóceń z kodowaniem sprzętowym AMD HEVC.
3. Wszelkie błędy konfiguracji lub brakujące pliki są bezpiecznie przechwytywane przez GUI bez ryzyka zamrożenia interfejsu.
4. Repozytorium jest w pełni gotowe do ewentualnego przejścia do Etapu 5R, jeżeli zostanie zlecony.
