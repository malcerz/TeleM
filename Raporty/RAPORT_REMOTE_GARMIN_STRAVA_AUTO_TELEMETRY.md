# Raport: Automatyczne pobieranie telemetrii z Garmin Connect lub Strava

Data: 2026-10-03
Status: Zrealizowane pomyślnie

## 1. Kluczowe parametry techniczne

```ini
AUTO_SOURCE_OPTIONS=NONE,GARMIN,STRAVA

GARMIN_LOGIN_IMPLEMENTED=YES
GARMIN_CREDENTIAL_STORE=YES (Windows Credential Manager via advapi32.dll CredWriteW/CredReadW + mock fallback)
GARMIN_ACTIVITY_SEARCH=YES (okno +/- 2h wokół osi czasu wideo)
GARMIN_FIT_DOWNLOAD=YES (oryginalny .fit z archiwum ZIP lub raw strumienia)
GARMIN_CACHE=YES (%LOCALAPPDATA%\SportCamHUD\remote_telemetry\garmin\)

STRAVA_OAUTH_IMPLEMENTED=YES (OAuth 2.0 z lokalnym serwerem callback i przeglądarką)
STRAVA_TOKEN_REFRESH=YES (automatyczne odświeżenie tokenu przed wygaśnięciem)
STRAVA_ACTIVITY_SEARCH=YES (okno +/- 2h wokół osi czasu wideo)
STRAVA_STREAM_DOWNLOAD=YES (time, latlng, altitude, velocity_smooth, heartrate, cadence, watts, temp, moving)
STRAVA_IMPORT_MODE=GENERATED_GPX

MANUAL_FILE_PRIORITY_PASS=YES (ręczny plik FIT/GPX ma bezwzględny priorytet, brak zapytań remote)
NONE_ZERO_REQUESTS_PASS=YES (dla 'none' zero requestów sieciowych)
MULTIFILE_SINGLE_ACTIVITY_PASS=YES (timeline projektu traktowany jako całość, pojedyncza aktywność)

MATCH_ALGORITHM=MULTI_FACTOR (TIME_OVERLAP 45-55%, START_TIME_DELTA 25-30%, DURATION_DELTA 15%, GPS_DISTANCE 15%)
AUTO_MATCH_THRESHOLD=0.90 (>=90% AUTO_ACCEPT, 60-90% NEEDS_SELECTION, <60% NO_MATCH)

REMOTE_CACHE_PASS=YES (linkowanie video_fingerprint -> cache file, zero requestów na cache hit)
OFFLINE_FALLBACK_PASS=YES (błędy sieci/autoryzacji nie blokują wczytywania filmu)
GUI_RESPONSIVE_PASS=YES (wszystkie operacje I/O i sieciowe w wątkach roboczych)

SECRETS_IN_CONFIG=NO
SECRETS_IN_LOGS=NO
SECRETS_IN_REPO=NO

FILES_CHANGED=15
DEPENDENCIES_ADDED=garminconnect, requests
TESTS_PASSED=11 (11 passed, 2 skipped opt-in real tests)
TESTS_FAILED=0
COMMIT=15d8b0b4d7d703f3021f916e287380720f8eec7d

FINAL_STATUS=SUCCESS
```

## 2. Architektura i wdrożone moduły

### `src/integrations/credential_store.py`
- Bezpieczny magazyn haseł i tokenów oparty bezpośrednio o **Windows Credential Manager** (`advapi32.dll` -> `CredWriteW`, `CredReadW`, `CredDeleteW`).
- Zero zewnętrznych zależności systemowych.
- Żadne hasło, token ani secret nie trafia do `def_layout.json`, plików projektu, kolejki eksportu ani konsoli logów.
- Posiada wbudowany tryb mockowy dla testów automatycznych (`set_mock_mode(True)` / `TELEM_CREDENTIAL_STORE_MOCK=1`), chroniący środowisko użytkownika.

### `src/integrations/activity_provider.py`
- Abstrakcyjny interfejs `ActivityProvider` z ujednoliconymi metodami:
  - `connect()`
  - `test_connection()`
  - `list_activities(start_dt, end_dt)`
  - `download_telemetry(activity_id, dest_dir)`
  - `refresh_auth()`
- Klasa `ActivityCandidate` agregująca metadane aktywności, czasy UTC i koordynaty.

### `src/integrations/activity_matcher.py`
- Wielokryterialny algorytm scoringowy łączący:
  1. `TIME_OVERLAP` (pokrycie czasowe filmu przez aktywność),
  2. `START_TIME_DELTA` (różnica czasu startu),
  3. `DURATION_DELTA` (stosunek czasu trwania),
  4. `GPS_DISTANCE` (odległość geograficzna punktu startowego na podstawie wzoru Haversine).
- Reguły decyzji:
  - `AUTO_ACCEPT`: wynik $\ge 0.90$ (i brak bliskiego drugiego kandydata),
  - `NEEDS_SELECTION`: wynik w przedziale $[0.60, 0.90)$ lub wielu zbliżonych kandydatów,
  - `NO_MATCH`: brak aktywności spełniającej próg 0.60.

### `src/integrations/remote_cache.py`
- Trwały cache w `%LOCALAPPDATA%\SportCamHUD\remote_telemetry\`.
- Podkatalogi: `garmin/` (`<id>.fit`, `<id>.json`), `strava/` (`<id>.gpx`, `<id>.json`).
- Indeks `video_index.json` mapujący `video_fingerprint` (nazwy, rozmiary, czasy modyfikacji klipów) na pobraną aktywność.
- Mechanizm `REMOTE_CACHE_HIT=YES`: ponowne otwarcie filmu natychmiast korzysta z pliku lokalnego bez zapytań sieciowych.

### `src/integrations/garmin_connect.py`
- Obsługa Garmin Connect z zachowaniem tokenów sesji.
- Pobieranie oryginalnego pliku FIT (z automatyczną dekompresją kontenera ZIP).
- Zachowanie wszystkich strumieni telemetrycznych: tętno, kadencja, moc, temperatura, wysokość, GPS, dev fields.

### `src/integrations/strava.py`
- Pełna implementacja OAuth 2.0 z automatycznym odświeżaniem wygasającego `access_token` za pomocą `refresh_token`.
- Pobieranie strumieni aktywności: `time`, `latlng`, `distance`, `altitude`, `velocity_smooth`, `heartrate`, `cadence`, `watts`, `temp`, `moving`.
- Konwersja strumieni do formatu `GPX` z rozszerzeniami `TrackPointExtension` (`hr`, `cad`, `speed`, `atemp`) oraz `power`, co pozwala na natywne wczytanie przez `telemetry_gpx` i pełne zasilenie wszystkich wskaźników HUD.

### `src/integrations/coordinator.py`
- Główny koordynator `resolve_remote_activity(...)`.
- Odpowiada za:
  1. Sprawdzenie aktywnego providera (dla `none` natychmiastowe wyjście bez sieci),
  2. Sprawdzenie cache lokalnego,
  3. Wyszukanie kandydatów w oknie $\pm 2\,\text{h}$,
  4. Wyliczenie score i decyzję,
  5. Pobranie pliku, zapisanie cache i powiązanie z filmem,
  6. Obsługę błędów sieci (offline mode).

### GUI: `src/gui/qt/tabs/settings_tab.py`
- Nowa sekcja: **Integracje / Dane aktywności**.
- Wybór źródła: `[ Nic ]`, `[ Garmin Connect ]`, `[ Strava ]`.
- Panele logowania i testowania połączenia w tle (wątki daemon, pełna responsywność GUI bez zawieszania).
- Maskowanie haseł i sekretów (`QLineEdit.Password`).
- Przechowywanie loginów i ID w konfiguracji, a haseł/tokenów wyłącznie w bezpiecznym magazynie systemowym.

### GUI: `src/gui/qt/main_window.py` & `project_mixin.py`
- Okno dialogowe wyboru przy niejednoznacznym dopasowaniu aktywności (`NEEDS_SELECTION`).
- Integracja wczytywania telemetrii: jeśli brak ręcznego pliku, automatycznie importowany FIT/GPX trafia wprost do `telemetry.load_fit` / `telemetry.load_gpx` i zasila cały system wskaźników.

---

## 3. Wyniki testów

Wykonano pełny pakiet testów w `tests/test_remote_telemetry_integrations.py`:
- `test_a_none_source_zero_requests`: **PASSED**
- `test_b_garmin_flow`: **PASSED**
- `test_c_strava_streams_to_gpx`: **PASSED**
- `test_d_cache_hit_zero_remote_download`: **PASSED**
- `test_e_manual_fit_priority`: **PASSED**
- `test_f_no_internet_graceful_fallback`: **PASSED**
- `test_g_strava_token_expired_refresh`: **PASSED**
- `test_h_multiple_candidates_selection`: **PASSED**
- `test_i_strong_single_match_auto_accept`: **PASSED**
- `test_j_multifile_single_activity`: **PASSED**
- `test_k_settings_tab_ui_toggle`: **PASSED**
- `test_real_garmin_connection_opt_in`: **SKIPPED** (opt-in)
- `test_real_strava_connection_opt_in`: **SKIPPED** (opt-in)

Podsumowanie: **11 passed, 2 skipped in 0.65s**. Zero błędów i zero regresji w istniejących testach aplikacji.
