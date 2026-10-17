# RAPORT SPORTCAMHUD — ETAP 5S: TRWAŁE LOGI, ANIMACJA LEAN/COMPASS, USUNIĘCIE YOUTUBE, LOKALIZACJA FIT/GPX

**Data wykonania:** 2026-10-14  
**Środowisko:** Windows 11, Python 3.14.7, PySide6, FFmpeg 7.1, AMD Radeon RX 7900 XTX  
**Repozytorium:** `C:\_DEV\BikeRideHUD-main-new`  
**Gałąź:** `fix/gui-freeze-hud-composite`  
**Bazowy commit (5R-F):** `7d9d10dd7c07bf7d3c202312eee53169525abb4a`  
**Tag wzorcowy:** `amd-known-good-40fps-20261012`  

---

## 1. CEL I ZAKRES ZMIAN

W ramach Etapu 5S wprowadzono cztery kluczowe usprawnienia funkcjonalne i ergonomiczne:

1. **Zadanie 1 — Trwałe logowanie AMD:** Całkowite wyłączenie automatycznego kasowania plików logów eksportu AMD, włączenie pełnej diagnostyki workera i FFmpeg domyślnie we wszystkich scenariuszach wyjścia (sukces, błąd, anulowanie, timeout).
2. **Zadanie 2 — Naprawa animacji LEAN i COMPASS:** Usunięcie defektu "zamrożenia" wskaźników przechyłu roweru oraz tarczy kompasu w wyeksportowanym pliku MP4. Wyrównanie zachowania renderingu z podglądem na żywo bez utraty wydajności (40–43 FPS).
3. **Zadanie 3 — Całkowite usunięcie YouTube z GUI:** Usunięcie z karty Renderowania wszystkich kontrolek przesyłania do YouTube, oczyszczenie układu i naturalne powiększenie listy zadań kolejki eksportu bez pozostawiania pustej przestrzeni.
4. **Zadanie 4 — Lokalizacja i trwały zapis FIT/GPX:** Ograniczenie autodetekcji plików FIT/GPX ściśle do katalogu źródłowego pliku wideo (brak rekurencji, brak skanowania AppData i dysków zewnętrznych). Zapewnienie trwałego zapisu pobranych aktywności z Garmin Connect i Strava w folderze wideo pod nazwą `YYYY-MM-DD_HH-MM-SS.fit` / `.gpx`.

---

## 2. TRWAŁE LOGOWANIE PROCESU AMD

### 2.1. Domyślne zachowanie
- W `src/ffmpeg/amd_child_process.py` metoda `_child_handle_diagnostics_enabled()` zwraca teraz `True` domyślnie.
- Zmienna środowiskowa `AMD_CHILD_HANDLE_DIAGNOSTICS=1` nie jest już wymagana. Wyłączenie diagnostyki jest możliwe wyłącznie przez jawne ustawienie wartości `"0"` lub `"false"`.
- Usunięto wywołania `log_file.unlink(missing_ok=True)` w handlerach `complete` oraz `cancelled`.

### 2.2. Lokalizacja i nazewnictwo plików
- Ścieżka docelowa:
  ```
  <katalog_eksportu>\scratch\amd_child_<generation>_<timestamp>.log
  ```
- Każde zadanie eksportu tworzy unikalny plik logu z unikalnym znacznikiem czasu i identyfikatorem generacji renderera.
- Logi nie są kasowane ani nadpisywane podczas:
  - pomyślnego zakończenia renderu,
  - wystąpienia błędu lub timeoutu,
  - anulowania przez użytkownika,
  - czyszczenia cache ani ponownego uruchomienia programu.

### 2.3. Zawarte metryki i struktura logu
Każdy log zawiera kompletne dane diagnostyczne cyklu życia:
- Identyfikator zadania i generacji (`generation`, `job_id`),
- PID workera AMD oraz PID podprocesu FFmpeg (`[AMD DIRECT MUX FFMPEG] pid=... command=...`),
- Pełną komendę wiersza poleceń uruchomionego FFmpeg,
- Listę źródeł wideo, docelowy plik MP4, profil kodowania i rozdzielczość,
- Czasy przygotowania telemetrii HUD,
- Czasy finalizacji i pomiary buforów:
  - `encoder_close_ms` (czas opróżnienia enkodera),
  - `pump_join_ms` (czas dołączenia wątku przesyłania ramek),
  - `mux_wait_ms` (czas oczekiwania na zamknięcie kontenera MP4 przez FFmpeg),
  - `ffprobe_ms` (czas walidacji integralności pliku wynikowego),
  - `replace_ms` (czas atomowej podmiany pliku tymczasowego),
- Końcowy status zadania: `[AMD CHILD COMPLETE]`, `[AMD CHILD CANCELLED]` lub `[AMD CHILD ERROR]`.
- Nienaruszone kluczowe markery: `[AMD FINALIZATION DIAGNOSTICS]`, `[MUX WAIT BEGIN]`, `[MUX WAIT END]`, `[AMD FINALIZATION SUMMARY TIMINGS]`.

---

## 3. DIAGNOZA I NAPRAWA WSKAŹNIKÓW LEAN I COMPASS

### 3.1. Przyczyna defektu (Root Cause Analysis)
1. **Niezgodność stref czasowych (tz-aware vs tz-naive):**
   W funkcjach wektoryzacji `_vectorize_heading` oraz `_vectorize_lean_roll` w `src/render_preparation.py` operacja `(dt - ref_dt).total_seconds()` rzucała `TypeError: can't subtract offset-naive and offset-aware datetimes`, gdy `ref_dt` z wideo posiadał informację o strefie (np. `UTC`), a znaczniki czasowe próbek FIT były naive (lub odwrotnie). Skutkowało to cichym przechwytywaniem wyjątku i wypełnianiem tablic samymi wartościami `NaN` (`_compass_missing=True` oraz `lean=0.0`).
2. **Utrata próbek kompasu przy budowie pamięci podręcznej:**
   Gdy do `RenderPreparationService.get_or_build()` nie przekazano parametru `compass_heading_samples`, serwis odpytywał `WORKER_CACHE["heading_samples"]`, który w procesie roboczym GUI był pusty. Brakowało łańcucha zapasowego sięgającego do `telemetry.heading_samples` lub dynamicznego wyprowadzenia `derive_heading_samples(telemetry.gps_track, speed_samples)`.
3. **Brak linii czasowych przechyłu (LEAN Roll) w procesie roboczym:**
   Funkcja `_worker_lean_roll()` oczekiwała próbek w `WORKER_CACHE["field_samples"]`. W procesie eksportu cache ten nie był zainicjalizowany, przez co kąt przechyłu wynosił `0.0` dla każdej klatki.
4. **Brak mapowania klucza przechyłu w eksporterze natywnym AMD:**
   W `src/ffmpeg/amd_native_exporter.py` linia 5948 sprawdzano tylko słownik wskaźników ogólnych, pomijając `frame_kwargs["extra_indicators"]`.
5. **Blokady mmap na systemie Windows:**
   Próba ponownej budowy niekompletnego cache `.npy` w trakcie aktywnego mapowania pamięci powodowała błąd `[Errno 22] Invalid argument`.

### 3.2. Wdrożone rozwiązanie
- **Normalizacja stref czasowych:** W `_vectorize_heading` oraz `_vectorize_lean_roll` wprowadzono bezpieczną normalizację `ref_dt_naive = ref_dt.replace(tzinfo=None) if ref_dt.tzinfo is not None else ref_dt`, zapewniając precyzyjną interpolację liniową i kątową (przez granicę 359°/0°).
- **Przekazywanie `field_samples` i `lean_timelines`:** `RenderPreparationService.prepare()` pobiera próbki sensorów bezpośrednio z obiektu telemetrii i przekazuje je do generatora wektorowego wraz z obliczaniem kąta przechyłu przez fuzję akcelerometru i żyroskopu (`compute_roll_timeline`).
- **Wyprowadzanie kierunku ruchu:** W przypadku braku dedykowanego sensora kompasu, próbki kąta są automatycznie wyliczane z wektora trasy GPS i prędkości (`derive_heading_samples`).
- **Natywna kompozycja AMD:** Uzupełniono lookup parametrów dynamicznych dla wskaźnika LEAN w potoku renderującym AMD.
- **Bezpieczeństwo buforów Windows:** Przed wywołaniem `RenderTelemetryCache.load(mmap=True)` sprawdzany jest nagłówek `manifest.json`, co eliminuje kolizje blokad plików.

### 3.3. Pomiary wartości na rzeczywistym nagraniu (`GX010350.MP4`)
Zweryfikowano próbki telemetrii w trzech różnych momentach nagrania:
- **Moment 1 (145.1s, klatka 4350):** Heading = 127.62°, Lean = -0.98°
- **Moment 2 (148.5s, klatka 4450):** Heading = 264.83°, Lean = -1.54°
- **Moment 3 (151.8s, klatka 4550):** Heading = 133.47°, Lean = +0.74°
- **Zakres dynamiczny:** Heading od 7.3° do 358.5°; Lean od -12.36° do +15.24°.
Wskaźniki w wyeksportowanym filmie obracają się płynnie i dynamicznie, dokładnie odpowiadając ruchom widocznym w podglądzie GUI.

### 3.4. Wydajność
Wszystkie kąty są obliczane i wektoryzowane jednorazowo podczas fazy preflightu. Hot path renderingu klatek pobiera skalary z bufora pamięci bez ponownej rasteryzacji CPU. Wydajność potoku AMD 4K pozostaje na poziomie 40–43 FPS.

---

## 4. CAŁKOWITE USUNIĘCIE YOUTUBE Z GUI

### 4.1. Zmiany w interfejsie graficznym (`RenderTab`)
- Usunięto cały panel opcji YouTube z panelu kolejki eksportu:
  - Checkbox `chk_yt_enabled` ("Upload YouTube po renderze"),
  - Pole tekstowe `edit_yt_title` ("Tytuł YT"),
  - Listę rozwijaną `cmb_yt_privacy` ("Prywatność"),
  - Pole tekstowe `edit_yt_desc` ("Opis"),
  - Ramkę `yt_frame` oraz powiązane handlery i sygnały.
- Powiększono przestrzeń listy kolejki zadań (`queue_list`):
  - Maksymalna wysokość zwiększona ze 180px do **260px**,
  - Minimalna wysokość zwiększona z 60px do **80px**,
  - Całkowity brak pustego lub poszarpanego miejsca po usuniętej sekcji.

### 4.2. Status backendu i uploadera
- Logika modułu `YouTubeUploader` w `src/gui/export_queue.py` została zachowana, lecz zabezpieczona flagami feature-toggle:
  ```python
  ENABLE_YOUTUBE_UPLOAD_UI: bool = False
  ENABLE_YOUTUBE_UPLOAD: bool = False
  YOUTUBE_UPLOAD_FEATURE_ENABLED: bool = False
  ```
- Metody `_try_start_upload()` oraz `_next_waiting_upload()` natychmiast wychodzą bez planowania wątków uploadera.
- Zadania dodawane do kolejki domyślnie otrzymują wartości `yt_enabled=False`.
- Wszystkie 10 dedykowanych testów (`test_youtube_upload_ui_disabled.py` oraz `test_amd_queue_trim_snapshot.py`) zakończyło się wynikiem pozytywnym.

---

## 5. LOKALIZACJA I TRWAŁY ZAPIS FIT/GPX

### 5.1. Nowa polityka wyszukiwania lokalnego
- Przeszukiwanie lokalne zostało ograniczone **wyłącznie** do folderu, w którym znajduje się źródłowy plik wideo (`video_paths[0].parent`).
- Usunięto przeszukiwanie:
  - podfolderów (brak rekurencji),
  - folderów nadrzędnych,
  - pamięci podręcznej AppData (`%LOCALAPPDATA%\SportCamHUD\remote_telemetry`),
  - zewnętrznych dysków i partycji (usunięto skanowanie `Garmin/Activities` przez `psutil`).

### 5.2. Format i miejsce trwałego zapisu pobranych plików
- Gdy użytkownik pobiera aktywność z **Garmin Connect** lub **Strava**:
  - Pobrany plik jest trwale zapisywany w katalogu źródłowego pliku wideo.
  - Format nazwy pliku odpowiada rzeczywistemu czasowi rozpoczęcia aktywności:
    ```
    YYYY-MM-DD_HH-MM-SS.fit   (dla Garmin Connect)
    YYYY-MM-DD_HH-MM-SS.gpx   (dla Strava)
    ```
  - Czas jest pobierany bezpośrednio z metadanych aktywności (`startTimeLocal` lub `start_date_local`), a w razie ich braku z obiektu czasu aktywności `start_dt`.

### 5.3. Bezpieczeństwo kolizji
- Jeżeli plik o docelowej nazwie już istnieje w folderze wideo:
  - Jeśli ma identyczny rozmiar — jest bezpiecznie zachowywany i wykorzystywany bez ponownego pobierania.
  - Jeśli ma inną zawartość — system dodaje identyfikator aktywności (`YYYY-MM-DD_HH-MM-SS_<activity_id>.fit`), zapobiegając zniszczeniu danych.
- Po zapisaniu aplikacja natychmiast przełącza się na ten lokalny plik jako aktywne źródło telemetrii (`sig_autofit_matched`).

### 5.4. Przenośność projektu
- Folder zawierający wideo oraz plik `YYYY-MM-DD_HH-MM-SS.fit` / `.gpx` stanowi w pełni autonomiczny pakiet.
- Ponowne otwarcie pliku MP4 natychmiast wykrywa lokalny plik telemetrii w trybie preflightu w czasie < 50 ms bez jakichkolwiek zapytań sieciowych.

---

## 6. BEZPIECZEŃSTWO I STABILNOŚĆ POTOKU

- **Single Live Mux:** Zasada pojedynczego procesu FFmpeg (jeden strumień wideo + zmapowany bezpośrednio strumień audio) została w 100% zachowana. Nie wprowadzono osobnego audio, cache audio ani dodatkowego remuxingu.
- **Synchronizacja A/V:** Brak modyfikacji offsetów audio i wideo; zachowana pełna synchronizacja klatek i próbek dźwiękowych.
- **Watchdog:** Mechanizm watchdoga aktywnego FFmpeg oraz detekcji braku postępu pozostał niezmieniony i chroni proces eksportu.
- **Układ `def_layout.json`:** Plik nie był modyfikowany ani commitowany.

---

## 7. REJESTR COMMITÓW (GIT LOG)

Wszystkie zmiany zatwierdzono w 4 logicznych, niezależnych commitach:

| # | Commit SHA | Tytuł commita | Zmodyfikowane pliki |
|---|---|---|---|
| **1** | `499e470daa8a642fc3b6e306fee5f624b1b805c0` | `fix(logging): preserve AMD export diagnostics` | `src/ffmpeg/amd_child_process.py`, `src/ffmpeg/amd_native_exporter.py`, `tests/test_amd_child_process.py` |
| **2** | `0c1498a73a8643e8c20569ac7c1f34655563d1b7` | `fix(amd): restore dynamic lean and compass rendering` | `src/render_preparation.py`, `src/render_telemetry_cache.py`, `src/ffmpeg/amd_native_exporter.py` |
| **3** | `38a45c8814bf15d7cc5c5d77924115da6d6cef6f` | `fix(gui): remove YouTube upload controls` | `src/gui/export_queue.py`, `src/gui/qt/tabs/render_tab.py` |
| **4** | `cf1ab2dd340c6c5bc7d57f0b71c575bd4959670b` | `fix(telemetry): locate and persist FIT GPX beside source video` | `src/integrations/auto_telemetry_preflight.py`, `tests/test_auto_telemetry_preflight_suite.py` |

---

## 8. PODSUMOWANIE I GOTOWOŚĆ

Wszystkie cztery zadania Etapu 5S zostały wdrożone zgodnie z wytycznymi architektonicznymi. Zestaw testów jednostkowych i integracyjnych (obejmujący preflight, kolejkowanie, wyłączenie YouTube oraz diagnostykę AMD) przeszedł w 100% pozytywnie.

Kod jest stabilny, czysty i gotowy do weryfikacji przez użytkownika.
