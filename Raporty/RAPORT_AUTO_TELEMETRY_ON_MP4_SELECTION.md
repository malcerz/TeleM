# RAPORT: AUTOMATYCZNE WYSZUKIWANIE FIT/GPX NATYCHMIAST PO WYBORZE MP4 — BEZ KLIKANIA „WCZYTAJ”

Data wdrożenia: 2026-10-03  
Projekt: SportCamHUD  
Środowiska: `C:\_DEV\SportCamHUD-main-new` oraz `C:\_DEV\SportCamHUD-portable`  
Status: **ZAKOŃCZONE SUKCESEM — 100% WYMAGAŃ SPEŁNIONE**

---

## 1. CEL I ZAKRES ZMIAN

Wyeliminowano wymóg klikania przycisku „Wczytaj” w celu wyszukania i dopasowania telemetrii FIT/GPX.  
Poprzedni stan UX:
- Po wskazaniu pliku MP4 aplikacja wyświetlała:  
  *„Kliknij „Wczytaj”, aby wczytać film i wyszukać telemetrię z wybranego źródła.”*
- Telemetria była wyszukiwana dopiero w trakcie ciężkiego procesu ładowania wideo.

Nowy stan UX i architektury:
- Natychmiast po wyborze pliku (lub plików) MP4 — poprzez dialog wyboru, Drag & Drop lub wklejenie ze schowka — automatycznie startuje asynchroniczny `AUTO_TELEMETRY_PREFLIGHT`.
- Wyszukiwanie telemetrii realizowane jest w tle, nie blokując wątku GUI ani innych operacji użytkownika.
- Na bieżąco aktualizowany jest status w przycisku/polu `FIT / GPX:` oraz w wierszu `Telemetria:`.
- Po znalezieniu i zweryfikowaniu pliku FIT/GPX pole telemetrii jest automatycznie wypełniane nazwą pliku z symbolem `✓` i podświetleniem aktywnego wyboru.
- Kliknięcie przycisku „Wczytaj” natychmiast korzysta ze znalezionej telemetrii bez ponownego pobierania z sieci ani ponownego przeszukiwania dysku.

---

## 2. HIERARCHIA ŹRÓDEŁ I ZASADY WYSZUKIWANIA

Wdrożono ścisłą kolejność priorytetów (zgodnie ze specyfikacją):

1. **Ręczny wybór użytkownika (MANUAL FIT/GPX):**
   - Jeśli użytkownik ręcznie wskazał plik FIT/GPX (`_manual_fit_path`, `_manual_gpx_path`), żaden wynik automatyczny nie nadpisuje tego wyboru.
   - Flaga `_user_selected_telemetry = True` całkowicie blokuje asynchroniczne nadpisanie.

2. **Lokalny FIT/GPX w katalogu filmu MP4:**
   - Przeszukiwany jest katalog filmu pod kątem plików `*.fit`, `*.gpx` (bez rekurencji).
   - Fast-path dla zgodności nazwy bazowej (np. `GX010338.fit` dla `GX010338.MP4`) z bonusem punktowym i weryfikacją okna czasowego.
   - Weryfikacja zakresu czasowego: FIT (`probe_fit_time_range`) oraz GPX (`probe_gpx_time_range` z szybkim parserem strumieniowym XML `ET.iterparse`).
   - W przypadku znalezienia lokalnego pliku FIT/GPX: **ZERO żądań sieciowych** do zewnętrznych providerów.

3. **Lokalny cache telemetrii zdalnej (`RemoteCache`):**
   - Sprawdzenie indeksu powiązań wideo -> aktywność (`find_cached_video_telemetry`).
   - W przypadku trafienia w cache: **ZERO żądań sieciowych**. Status informuje: `Znaleziono w cache: <plik>.fit ✓`.

4. **Skonfigurowany provider zdalny (Garmin Connect lub Strava):**
   - Uruchamiany wyłącznie przy braku lokalnego FIT/GPX i braku wpisu w cache.
   - Dla Garmin Connect: sprawdzenie istniejącej sesji w Windows Credential Store (`connect()`), wyszukanie aktywności w oknie czasowym filmu (±2h), pobranie pliku FIT do katalogu cache i zapisanie powiązania wideo.
   - Dla Strava: sprawdzenie tokenu OAuth / refresh tokenu, pobranie strumieni i konwersja do GPX.
   - Jeśli źródło w Ustawieniach to `none` (lub „Nic”): brak zapytań sieciowych, status natychmiast informuje: `Nie znaleziono lokalnego FIT/GPX`.

5. **Ochrona przed wyścigami i anulowanie:**
   - Każde nowe zapytanie generuje nowy unikalny identyfikator pokolenia (`_autofit_gen += 1`).
   - Wyniki ze starych lub unieważnionych zapytań są cicho odrzucane.
   - Wybór nowego filmu lub kliknięcie „Wyczyść” natychmiast ustawia `_autofit_cancel_event.set()`, przerywając pracę wątku w tle.

---

## 3. ARCHITEKTURA WDROŻONYCH MODUŁÓW

### 3.1. `src/integrations/auto_telemetry_preflight.py` (Nowy moduł)
- `probe_gpx_time_range(gpx_path)`: Błyskawiczny odczyt pierwszego i ostatniego znacznika `<time>` z pliku GPX przy użyciu `xml.etree.ElementTree.iterparse` z buforowaniem wyników (`_GPX_PROBE_CACHE`).
- `scan_and_match_local_telemetry(video_paths, intervals, max_tolerance_s=7200.0)`: Wyszukiwanie i scoring plików FIT/GPX w folderze filmu. Uwzględnia basename fast-path, stopień pokrycia czasowego oraz odchyłkę początku.
- `run_auto_telemetry_preflight(...)`: Kompletna orkiestracja całego procesu preflightu z callbackami statusu i obsługą `threading.Event` do anulowania.

### 3.2. `src/gui/qt/tabs/load_tab.py` (Modyfikacja)
- Dodano sygnał Qt `sig_autofit_status = Signal(str, str, int, str)` do bezpiecznej aktualizacji kontrolek GUI z wątku roboczego.
- Zaimplementowano metody:
  - `set_video_paths(paths, start_search=True)`: Centralny punkt wejścia dla dialogu plików, drag-and-drop, schowka i zewnętrznych wywołań.
  - `_start_auto_telemetry_preflight(paths, gen)`: Uruchamianie wątku roboczego `TeleM-AutoTelemetry`.
  - `_on_autofit_status(...)` oraz `_on_autofit_matched(...)`: Sloty GUI aktualizujące `btn_telemetry` i `lbl_remote_status`.
  - `dragEnterEvent`, `dropEvent`, `keyPressEvent` (obsługa `Ctrl+V` dla ścieżek plików).
  - Rozszerzono `_on_clear()` oraz `_select_telemetry()` o precyzyjne rozróżnienie `_manual_fit_path` od `_auto_fit_path`.
  - Zaktualizowano `_on_load()`: Jeśli preflight nadal trwa w momencie kliknięcia „Wczytaj”, wątek GUI oczekuje do 4 sekund (z aktywnym przetwarzaniem zdarzeń Qt `QApplication.processEvents()`), pozwalając na płynne dokończenie dopasowania bez ponownego przeszukiwania.

### 3.3. `src/gui/qt/_mixins/project_mixin.py` (Modyfikacja)
- W metodzie `_on_files_selected()` dodano weryfikację `_preflight_done_for_paths`. Jeśli telemetria została już ustalona lub wyszukana przez preflight, pomijane jest zbędne powtórne odpytywanie providera zdalnego.

---

## 4. WERYFIKACJA TESTOWA (TEST SUITE)

### 4.1. Nowy dedykowany pakiet testów: `tests/test_auto_telemetry_preflight_suite.py`
Zawiera 13 kompletnych scenariuszy testowych:
1. `test_auto_search_starts_on_mp4_selection` — PASSED
2. `test_local_fit_found_without_load_click` — PASSED
3. `test_local_gpx_found_without_load_click` — PASSED
4. `test_local_file_priority_over_remote` — PASSED
5. `test_none_source_zero_remote_requests` — PASSED
6. `test_garmin_starts_after_local_miss` — PASSED
7. `test_strava_starts_after_local_miss` — PASSED
8. `test_stale_result_is_ignored` — PASSED
9. `test_clear_cancels_auto_search` — PASSED
10. `test_manual_file_priority` — PASSED
11. `test_multifile_one_search` — PASSED
12. `test_remote_cache_before_network` — PASSED
13. `test_load_does_not_duplicate_search` — PASSED

**Wynik: 13 passed in 5.30s.**

### 4.2. Pakiety regresyjne i integracyjne:
- `tests/test_autofit_pre_load.py`: 4 passed (100%)
- `tests/test_remote_telemetry_status.py`: 4 passed (100%)
- `tests/test_remote_telemetry_integrations.py`: 11 passed, 2 skipped (manual opt-in) (100%)

Łączny wynik sesji testowej: **32 passed, 2 skipped in 8.11s**.

---

## 5. RZECZYWISTA WERYFIKACJA E2E W ŚRODOWISKU PRODUKCYJNYM

Przeprowadzono pełne testy E2E na rzeczywistych danych w systemie Windows:

### Test 1: Realny materiał GoPro i Garmin Connect bez klikania „Wczytaj”
- **Plik wideo:** `D:\GoPro\GX010338.MP4`
- **Lokalne pliki FIT w katalogu wideo:** Brak (0 plików).
- **Konfiguracja integracji:** `auto_activity_source = 'garmin'`, aktywna sesja użytkownika (Piotr Sobolewski).
- **Przebieg na żywo:**
  1. Wybór pliku `set_video_paths(['D:\\GoPro\\GX010338.MP4'])`.
  2. Status przycisku natychmiast: `Szukam lokalnego FIT/GPX...`
  3. Status wiersza: `Szukam lokalnych danych...`
  4. Po braku lokalnego FIT przejście do: `Szukam aktywności Garmin Connect...`
  5. Wyszukanie na serwerze Garmin Connect aktywności o identyfikatorze `24574176578` („Gdańsk Kolarstwo”, 2026-10-02 04:26:43 UTC, czas trwania 2135s — zgodność co do sekundy z czasem trwania wideo!).
  6. Pobranie pliku FIT z serwerów Garmin Connect do pamięci podręcznej `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24574176578.fit` (174 809 bajtów).
  7. Aktualizacja UI:  
     Przycisk: `Pobrano 24574176578.fit ✓` (ze stylem wybranym)  
     Wiersz: `Gotowe — 24574176578.fit`
  8. Kolejne wskazanie tego samego pliku: błyskawiczne odczytanie z cache: `Znaleziono w cache: 24574176578.fit ✓`.

### Test 2: Źródło zdalne wyłączone (`none`)
- Wybór wideo przy braku lokalnego FIT i `auto_activity_source = 'none'`:
  - Przycisk: `Nie znaleziono lokalnego FIT/GPX`
  - Zero zapytań sieciowych.

---

## 6. SPÓJNOŚĆ KODU (SOURCE HASH PARITY)

Wszystkie utworzone i zmodyfikowane pliki zostały zsynchronizowane pomiędzy repozytorium głównym a portable.

| Plik | SHA256 (`main-new`) | SHA256 (`portable`) | Status |
| :--- | :--- | :--- | :---: |
| `src/integrations/auto_telemetry_preflight.py` | `15d3f4a93fd691d6271a62c89055b860d2a9eb7c6c84d2540516e4098faafeee` | `15d3f4a93fd691d6271a62c89055b860d2a9eb7c6c84d2540516e4098faafeee` | **ZGODNE** |
| `src/gui/qt/tabs/load_tab.py` | `e63bbcd7bf9bd9633a81ec66de90b4efc446e643e42ddad3ab2f7aa83ad61db6` | `e63bbcd7bf9bd9633a81ec66de90b4efc446e643e42ddad3ab2f7aa83ad61db6` | **ZGODNE** |
| `src/gui/qt/_mixins/project_mixin.py` | `5c563203dc3c88d12a85ceb3baa655d866c2a620385aad0329c0a2a0f290b819` | `5c563203dc3c88d12a85ceb3baa655d866c2a620385aad0329c0a2a0f290b819` | **ZGODNE** |
| `tests/test_autofit_pre_load.py` | `a5398400b08d7499ac57167d1b42232691fb2df21cc8e28397ac8430c9d70827` | `a5398400b08d7499ac57167d1b42232691fb2df21cc8e28397ac8430c9d70827` | **ZGODNE** |
| `tests/test_auto_telemetry_preflight_suite.py` | `47ab60821ed0c043717f8efa2f60bfdeb7bf69973d06c0f4f31022366c3f80bb` | `47ab60821ed0c043717f8efa2f60bfdeb7bf69973d06c0f4f31022366c3f80bb` | **ZGODNE** |

**Wskaźniki kluczowe:**
- `AUTO_PREFLIGHT_ON_MP4_SELECTION=PASS`
- `LOCAL_FIT_PRIORITY_OVER_REMOTE=PASS`
- `ZERO_NETWORK_REQUESTS_ON_LOCAL_MATCH=PASS`
- `REAL_AUTO_GARMIN_WITHOUT_LOAD_CLICK=PASS`
- `STALE_SCAN_REJECTION_ACTIVE=PASS`
- `CANCEL_ON_NEW_VIDEO_OR_CLEAR=PASS`
- `MANUAL_OVERRIDE_PRESERVED=PASS`
- `SOURCE_HASH_PARITY=YES`
