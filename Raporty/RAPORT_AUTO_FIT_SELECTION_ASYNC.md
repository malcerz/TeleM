# RAPORT: UPROSZCZENIE I NAPRAWA AUTOMATYCZNEGO DOBORU TELEMETRII (ASYNC & SOURCE ORDER)

## 1. Kontekst i cel zadania

Dotychczasowy mechanizm automatycznego doboru telemetrii zawierał powielone ścieżki i synchroniczne wywołania sieciowe:
- Preflight po wyborze MP4,
- Ponowne lokalne wyszukiwanie podczas ładowania projektu (`bg_load()`),
- Synchroniczne wywołania remote import z `req.completed.wait(timeout=45.0)` blokujące ładowanie projektu,
- Ryzyko zawieszenia procesu ładowania przy problemach sieciowych lub braku autoryzacji.

**Cel:**
Uproszczenie i bezwzględne wyegzekwowanie jednoznacznej hierarchii źródeł telemetrii:
1. **PRIORYTET 1**: Ręcznie wskazany FIT / GPX (wybór użytkownika zawsze wygrywa),
2. **PRIORYTET 2**: Pasujący plik `.fit` znajdujący się **dokładnie w folderze źródłowego MP4** (niedozwolone skanowanie podfolderów, folderów nadrzędnych ani innych ścieżek; brak automatycznego dobierania `.gpx` lokalnie),
3. **PRIORYTET 3**: Aktualnie wybrana integracja zdalna (**Garmin** LUB **Strava**) uruchamiana **wyłącznie asynchronicznie** w tle z mechanizmem *late attach* (`attach_late_telemetry`).

**Twardy niezmiennik architektoniczny (Hard Invariant):**
Ładowanie projektu **nigdy nie czeka na sieć** (`BLOCKING_REMOTE_WAIT = 0`).

---

## 2. Zakres wprowadzonych zmian

### A. Lokalne wyszukiwanie FIT (`src/integrations/auto_telemetry_preflight.py`)
- `scan_and_match_local_telemetry`:
  - Usunięto automatyczne dopasowywanie plików `.gpx` lokalnie – wyszukiwane są wyłącznie kandydaty `.fit`.
  - Wprowadzono twarde ograniczenie `cand.parent.resolve() == dir_path.resolve()`, co uniemożliwia wchodzenie do podkatalogów (np. `MP4/FIT/`).
- `resolve_local_fit`:
  - Dedykowana, szybka funkcja skanująca wyłącznie katalog `Path(video_paths[0]).parent`.
  - Logowanie `[AUTO TELEMETRY] scanning local directory: ...`, `[AUTO TELEMETRY] local FIT matched: ...` lub `[AUTO TELEMETRY] no local FIT match`.

### B. Pojedynczy koordynator decyzji (`TelemetryOrchestrator`)
- Dodano singleton `TelemetryOrchestrator`:
  - Zarządza generacją żądań (`generation_id`), zdarzeniami anulowania (`_active_cancel_event`) oraz aktywnym kluczem wyszukiwania (`_active_lookup_key`).
  - **Deduplikacja**: maksymalnie 1 zapytanie remote dla danego zestawu wideo (pomija zduplikowane wywołania z LoadTab i ProjectMixin).
  - **Odrzucanie przestarzałych wyników**: zmiana filmu lub wyczyszczenie projektu natychmiast anuluje aktywne zapytanie i ignoruje spóźnione odpowiedzi.
  - **Priorytet wyboru ręcznego**: kliknięcie/wybór ręcznego FIT/GPX natychmiast anuluje trwające zapytanie remote i nadpisuje stan.
  - **Izolacja dostawców**: brak jakiegokolwiek przełączania pomiędzy Garmin a Strava (0 wywołań alternatywnego providera w razie błędu).
  - **Obsługa braku logowania**: brak sesji/tokenów nie otwiera żadnych okien modalnych ani przeglądarki podczas ładowania filmu – remote search jest natychmiast pomijany ze statusem informacyjnym.

### C. Usunięcie blokowania z procesu ładowania (`src/gui/qt/_mixins/project_mixin.py`)
- W `bg_load()`:
  - Zastąpiono powielony preflight wywołaniem `resolve_local_fit(candidate_video_paths)`.
  - W razie braku lokalnego FIT: uruchamiany jest asynchroniczny daemon `start_remote_activity_lookup_async`, a ładowanie projektu natychmiast kontynuuje pracę (`BLOCKING_REMOTE_WAIT = 0`).
  - Po pobraniu pliku w tle wywoływane jest canonical `attach_late_telemetry(p)` bez restartowania projektu i bez przerywania podglądu.
  - Usunięto zduplikowane przeszukiwanie lokalne (linie 804–818).
  - Usunięto zduplikowany fallback remote import zawierający `req.completed.wait(timeout=45.0)` (linie 912–951).

### D. Integracja z kontrolerem i zakładką ładowania (`controller.py`, `load_tab.py`)
- W `controller.py`: `clear_project()` powiadamia `TelemetryOrchestrator.on_project_cleared()`.
- W `load_tab.py`:
  - `_select_telemetry()` powiadamia `TelemetryOrchestrator.on_manual_telemetry_selected(path)`.
  - `_on_clear()` powiadamia `TelemetryOrchestrator.on_project_cleared()`.

### E. Aktualizacja reguł architektonicznych (`AGENTS.md`)
- Dodano sekcję **21. HARD INVARIANT — TELEMETRY SOURCE RESOLUTION & ZERO BLOCKING PROJECT LOAD**.

---

## 3. Zestaw testów i weryfikacja

Utworzono dedykowaną suite testową w `tests/test_auto_telemetry_source_order.py`:
1. `test_local_fit_in_exact_mp4_dir_matches` — poprawny FIT w katalogu MP4 jest dopasowywany.
2. `test_fit_in_subfolder_not_matched` — FIT w podkatalogu NIE jest dopasowywany (`LOCAL_FIT=NONE`).
3. `test_fit_in_parent_or_external_not_matched` — FIT w katalogu nadrzędnym lub zewnętrznym NIE jest dopasowywany.
4. `test_gpx_in_mp4_dir_not_matched_locally` — lokalny GPX w katalogu MP4 NIE jest automatycznie dopasowywany.
5. `test_manual_fit_from_another_directory_wins` — ręcznie wybrany FIT z dowolnego miejsca wygrywa.
6. `test_manual_gpx_wins` — ręcznie wybrany GPX wygrywa.
7. `test_local_fit_terminates_search_zero_remote_calls` — dopasowanie lokalnego FIT natychmiast kończy wyszukiwanie (`REMOTE_REQUESTS=0`).
8. `test_garmin_remote_lookup_async_with_delay` — symulowane opóźnienie sieciowe nie blokuje wywołania, wynik dołączany asynchronicznie.
9. `test_strava_remote_lookup_async` — asynchroniczne pobieranie ze Strava i late attach.
10. `test_remote_skipped_when_not_logged_in` — brak sesji nie generuje zapytań ani okien modalnych.
11. `test_zero_cross_provider_fallback_garmin_failure` — błąd Garmin wykonuje 0 zapytań do Strava.
12. `test_zero_cross_provider_fallback_strava_failure` — błąd Strava wykonuje 0 zapytań do Garmin.
13. `test_deduplication_max_one_remote_lookup` — maksymalnie 1 zapytanie remote na dany film.
14. `test_stale_request_rejected_on_video_switch` — zmiana filmu odrzuca wynik dla poprzedniego wideo.
15. `test_stale_request_rejected_on_clear` — wyczyszczenie projektu odrzuca trwające zapytanie.
16. `test_manual_override_wins_over_inflight_remote` — ręczny wybór w trakcie zapytania sieciowego anuluje i nadpisuje wynik zdalny.
17. `test_project_load_contains_no_blocking_remote_wait` — test governance sprawdzający brak `req.completed.wait` oraz brak synchronicznego `resolve_remote_activity` w `project_mixin.py`.

### Wyniki uruchomienia testów:
- `tests/test_auto_telemetry_source_order.py`: **17 passed** (1.90s)
- `tests/test_auto_telemetry_preflight_suite.py`: **13 passed** (4.94s)
- `tests/test_autofit_pre_load.py`: **4 passed**
- `tests/test_remote_telemetry_integrations.py`: **11 passed, 2 skipped**
- `tests/test_default_export_dir_settings.py`: **9 passed**
- Łącznie: **54 passed, 2 skipped in 28.54s**

---

## 4. Status

Implementacja zakończona sukcesem. Wszystkie niezmienniki architektoniczne zostały zachowane.
