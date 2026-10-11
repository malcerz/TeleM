# SportCamHUD — Etap 1: AutoFIT / DJI bez GPS

**Data:** 2026-10-11
**Repozytorium:** `C:\_DEV\BikeRideHUD-main-new`
**Gałąź:** `fix/gui-freeze-hud-composite`
**Commit implementacji i testów:** `982cb2268ea4ccb0c790e5856286f079e9a6935a`

## 1. Stan Git przed rozpoczęciem

- HEAD: `310555087e31405b25e6a288093c04ee8be7ae63`.
- Gałąź: `fix/gui-freeze-hud-composite`, trzy commity lokalnie przed `origin`.
- Istniała niezacommitowana zmiana użytkownika w `def_layout.json`.
- Istniał nieśledzony raport audytu `Raporty/RAPORT_SPORTCAMHUD_FULL_REGRESSION_AUDIT_20261011.md`.
- Nie nadpisano ani nie dodano do commita `def_layout.json` ani istniejącego raportu audytu. Backup Etapu 0 nie był modyfikowany.

## 2. Przyczyna braku AutoFIT bez GPS

Preflight tworzył przedziały tylko wtedy, gdy resolver zwrócił absolutny czas rozpoczęcia. Wcześniejszy resolver korzystał przede wszystkim z GPMF i pojedynczego formatu `creation_time`; nie rozpoznawał szeregu tagów daty w streamach/kamerach i nie oferował czasu systemowego jako jawnie niskiej jakości wskazówki. Przy DJI bez GPMF GPS i bez rozpoznanego tagu lista przedziałów pozostawała pusta, a ścieżki wyszukiwania Garmin/Strava wymagały niepustych przedziałów.

Teraz preflight używa GPMF, tagów formatu i streamów MP4, rozpoznanych metadanych czasu kamery, a na końcu mtime wyłącznie jako wskazówki. Bez żadnego wiarygodnego lub pomocniczego czasu nie dobiera aktywności automatycznie i informuje o ręcznym wyborze.

## 3. Przyczyna błędnego lokalnego fallbacku

- Wynik pojedynczego `find_best_fit_match()` mógł kończyć skan przed rozstrzygnięciem niejednoznaczności.
- Sam basename mógł dopuścić FIT oddalony nawet o 24 godziny.
- Wynik z pierwszego przeszukanego katalogu kończył skan; kandydaci z kolejnych katalogów nie brali udziału we wspólnym rankingu.
- Strava pobierała pierwszy wynik nawet wtedy, gdy matcher zwrócił `NEEDS_SELECTION`.

Lokalne FIT/GPX są teraz oceniane wspólnym matcherem `rank_and_evaluate_candidates`. Basename nie może sam zatwierdzić dopasowania. Kandydaci z katalogu filmu, ustawionej lokalizacji, katalogów Garmin i cache pobranych aktywności są deduplikowani i oceniani razem. Kilka bliskich wyników albo niska pewność czasu wymaga potwierdzenia przez istniejące okno wyboru.

## 4. Sposób ustalania czasu DJI/GoPro

Kolejność resolvera:

1. Wiarygodny absolutny GPS timestamp GPMF, jeżeli jest poprawny i plausybilny.
2. MP4 format/stream date tags, w tym `creation_time` oraz znane warianty QuickTime i daty nagrania.
3. Inne rozpoznane tagi metadanych kamery.
4. Czas modyfikacji pliku jako `fallback` / `degraded`, tylko do zaproponowania dopasowań wymagających potwierdzenia.

Znaczniki ze strefą/offsetem są normalizowane do UTC. Znaczniki naiwne są interpretowane w lokalnej strefie hosta, oznaczane jako niskiej pewności i wymagają potwierdzenia. Daty przed 2000 r. i dalej niż dzień w przyszłość są odrzucane. Rozbieżność czasu tagu i mtime większa niż 48 godzin obniża pewność; szczegół i pochodzenie zapisywane są w rozwiązaniu/cache. Nie wprowadzono stałego przesunięcia strefy.

Cache rozwiązań czasu ma nową wersję i klucz uwzględniający rozmiar oraz mtime źródła, dzięki czemu zmieniony plik nie korzysta ze starej decyzji. Jakość czasu przenoszona jest do przedziału AutoFIT jako `exact`, `estimated` lub `degraded`.

## 5. Brakujące helpery DJI i API lokalnego FIT

- Dodano `resolve_local_fit()`, który korzysta z istniejącego skanera i rankingu; domyślnie skanuje wyłącznie katalog źródłowego MP4, a koordynator podaje zatwierdzone katalogi.
- Dodano `probe_dji_telemetry_capabilities()`. Używa lekkiego ffprobe i ograniczonego odczytu nagłówka MP4, by rozpoznać DJI oraz protokół `dvtm_ac103` bez pełnego parsera.
- `_write_capability_cache()` zapisuje tylko potwierdzony, znany przypadek bez kanałów IMU. Nieznane schematy pozostają nieznane i nadal przechodzą pełną ścieżkę parsera.
- Cache przechowuje schemat, dostępne kanały i informację, czy parser znalazł użyteczną telemetrię. FIT pozostaje osobnym źródłem GPS/speed/HR/cadence/power itd.
- Worker DJI używa fallbacku do zgodnego ABI parsera w `runtime/telemetry_parser`, gdy skonfigurowana ścieżka wspólna nie zawiera rozszerzenia.

Na rzeczywistym `DJI_0010.MP4` Action 2 protokół `dvtm_ac103` daje pusty wynik IMU; niezależna wcześniejsza próba parsera tego pliku zwróciła `normalized_imu=0`. Pomiar zimnego capability probe w odizolowanym cache wyniósł **50,6 ms**.

## 6. Ranking i confidence

- Jedyny silny wynik może zostać zaakceptowany automatycznie przez istniejące progi `activity_matcher`.
- Bliskie wyniki trafiają do `Needs_selection`.
- Czas `degraded` (mtime, naiwny tag albo rozbieżny czas) wymusza wybór nawet dla pojedynczego kandydata.
- Brak przedziału czasu nie uruchamia wyszukiwania w arbitralnym okresie i nie dopasowuje po nazwie pliku.
- Współrzędne GPS filmu są używane wyłącznie po walidacji zakresów i wartości skończonych. Fallback GPS dla FIT wymaga także rozsądnej długości aktywności.
- Wyniki z wielu katalogów są rozstrzygane razem; katalog wcześniejszy na liście nie wygrywa automatycznie.

## 7. Needs_selection oraz GUI

Istniejący dialog wyboru został uogólniony z Garmin Connect na aktywności zdalne i lokalne FIT/GPX. Zamiast `QMetaObject.invokeMethod` z niezarejestrowanym typem `object`, worker wysyła kandydatów istniejącym obiektem Pythona przez Qt `Signal`; wątek GUI pokazuje dialog, a worker czeka na wybór. Generacja i anulowanie są sprawdzane przed zwróceniem wyboru, a ręcznie wskazana telemetria nadal blokuje nadpisanie.

## 8. Garmin Connect, Strava i cache

- Brak GPS nie blokuje dostawców, jeśli resolver uzyskał czas filmu.
- Garmin i Strava wyszukują w przedziale czasu i stosują matcher oraz confidence.
- Strava nie pobiera już pierwszego wyniku przy `NEEDS_SELECTION`/`NO_MATCH`.
- Garmin/Strava pobierają FIT/GPX dopiero po jednoznacznym dopasowaniu albo potwierdzeniu kandydata; zwrócony obiekt musi należeć do bieżącej listy wyników.
- Katalogi cache obu providerów są przeszukiwane czasowo również wtedy, gdy aktywność nie ma wcześniejszego powiązania z tym filmem. Nadal zachowano szybki hit z indeksu video→activity.
- Nie wykonywano połączenia z realnym kontem Garmin ani Strava; sieć i autoryzacja zostały sprawdzone przez istniejące testy/mocki.

## 9. Sekwencje multi-file i late attach

Globalna oś czasu, zakresy cięć, pauzy, SmartSync i mechanizm late attach nie zostały przebudowane. Resolver przekazuje wszystkie przedziały klipów do wspólnego matchera. Realny test sześciu klipów Action 2 zachował sześć odrębnych przedziałów i dopasował aktywność obejmującą całą sekwencję. Testy timeline przeszły. Dokładny SmartSync bez niezależnych kanałów kamery pozostaje odrębnym zagadnieniem; odnalezienie FIT nie jest deklarowane jako precyzyjna synchronizacja.

## 10. Testy kanoniczne i syntetyczne

Interpreter: Python 3.14.7. Testy uruchamiano z `LOCALAPPDATA` oraz cache wskazującymi dedykowane katalogi `C:\_DEV\_SportCamHUD_ETAP1_*`; nie modyfikowano produkcyjnego layoutu ani cache użytkownika.

- `py_compile` wszystkich zmienionych modułów i testów: **PASS**.
- Pakiet AutoFIT, GUI, multifile i DJI (w tym `test_auto_telemetry_preflight_suite.py`, `test_autofit_pre_load.py`, testy resolvera/timeline, capability probe oraz worker DJI): **92 passed**.
- `test_dji_telemetry.py` + `test_telemetry_manager.py`: **34 passed, 2 skipped**.
- Pełny `test_dji_action2_none_fix.py`: **2 passed, 7 failed** — plik zawiera asercje do metod/properties kontrolera (`ensure_telemetry_manager`, `clear_project`, `is_dji` i in.), których nie ma w aktualnej architekturze, oraz niekompletny fixture `start_dt_utc`. Te niepowiązane API kontrolera nie zostały dodane w Etapie 1.
- `test_auto_telemetry_source_order.py`: test nie zbiera się, ponieważ importuje nieistniejący `TelemetryOrchestrator`; implementacja w tym repozytorium korzysta z `run_auto_telemetry_preflight` i odrębnego coordinatora. Nie utworzono konkurencyjnego systemu.
- `tests/test_dji_smartsync.py`: plik nie istnieje w repozytorium.
- Nie uruchamiano pełnego renderingu, benchmarku GPU ani testu audio.

## 11. Rzeczywisty test DJI bez GPS i FIT

Zestaw z dokumentowanego raportu Action 2:

- `F:\GoPro\2026-10-05\DJI_0010.MP4` … `DJI_0015.MP4` — sześć rzeczywistych klipów.
- Znany, wcześniej powiązany FIT: `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24614281884.fit`.
- Wszystkie klipy rozwiązały się z tagu MP4 `creation_time`, bez GPMF timestamp; quality `estimated`.
- Rzeczywisty koordynator zwrócił dokładnie ten FIT, status `matched`, score **0.992884**.
- Cały preflight sześciu klipów: **1,03 s** na tej maszynie. Nie ma porównywalnego pomiaru sprzed zmiany, więc nie wyciągam wniosku o przyspieszeniu.
- FIT parser wykazał pola: altitude, battery, cadence, power, distance, speed, heart rate, temperature oraz latitude/longitude. Kanały FIT nie zależą od tego, czy kamera ma GPS/IMU.

## 12. Nietestowane przypadki na rzeczywistych plikach

- GoPro z GPMF GPS w realnym AutoFIT — **NOT TESTED** w tym etapie.
- DJI Action 6 oraz nieznane warianty protokołu DJMD — **NOT TESTED** na rzeczywistych nagraniach. Nieznane schematy nie są klasyfikowane jako puste.
- Żywe logowanie, wyszukiwanie i pobranie z Garmin Connect/Strava — **NOT TESTED**; ścieżki niejednoznaczności i pobierania pokrywają testy syntetyczne.
- Ręczne przesunięcie SmartSync oraz dokładność synchronizacji filmu z FIT — **NOT TESTED** na próbce wzorcowej. Sam dobór aktywności nie potwierdza dokładnego offsetu.
- Pełny render końcowy i podgląd aplikacji z człowiekiem dokonującym wyboru — **NOT TESTED**. Nie uruchamiano renderowania zgodnie z ograniczeniem zadania; automatyczny cross-thread round-trip Qt sprawdzono testem.

## 13. Porównanie wydajności

Nie było porównywalnego pomiaru „przed”. Realny pomiar bieżący to 1,03 s dla sześciu klipów DJI i jednego FIT; zimny capability probe Action 2 to 50,6 ms. Nie odpalano benchmarku renderera i nie deklaruję poprawy FPS ani czasu przygotowania HUD.

## 14. Zmienione pliki

- `src/multifile.py`
- `src/integrations/auto_telemetry_preflight.py`
- `src/gui/qt/tabs/load_tab.py`
- `src/telemetry_dji.py`
- `tests/test_autofit_no_gps_recovery.py` (nowy)
- `tests/test_auto_telemetry_preflight_suite.py`
- `tests/test_autofit_pre_load.py`
- `tests/test_multifile_etap3_clip_time.py`
- `tests/test_dji_telemetry.py`

## 15. Izolacja zakresu i stan Git

Nie zmieniano rendererów AMD/Intel/NVIDIA, Live Mux, audio, QP/bitrate, HDR, geometrii wskaźników, cache efektów, katalogu eksportu ani frameworku błędów. Nie wykonywano ekstrakcji audio, remuxu, renderingu, synchronizacji portable ani push.

`def_layout.json` pozostał poza stagingiem i commitem. Po commicie kodu/testów gałąź ma cztery commity lokalnie przed origin; pozostały wyłącznie istniejąca zmiana `def_layout.json` i istniejący nieśledzony raport pełnego audytu.

## 16. Commit

Commit kodu i testów Etapu 1: **`982cb2268ea4ccb0c790e5856286f079e9a6935a`** (`Recover AutoFIT and DJI no-GPS matching`). Raport jest dodawany osobno, aby mógł zawierać pełny hash commita implementacyjnego.

## 17. Podsumowanie i ograniczenia

**Kod Etapu 1: PASS** dla lokalnego AutoFIT DJI bez GPS na rzeczywistej sekwencji sześciu klipów i znanym FIT, przy zachowaniu ranking/confidence, wyboru użytkownika i obsługi multi-file. **Pełna akceptacja produkcyjna: PARTIAL / NOT PROVEN** z powodu braku realnego testu GoPro GPS, Action 6, aktywnych providerów oraz dokładnego SmartSync. Dodatkowo wskazane starsze testy/API w repozytorium są niespójne z aktualnym kontrolerem i wymagają osobnego audytu.
