# SportCamHUD — GUI, licencje i blokady interfejsu

Data: 2026-10-18. **Status: PARTIAL**.

Przywrócono pięć rodzin wymagań interfejsu: dokumenty licencyjne, blokadę Projektu, rzeczywiste czyszczenie projektu, ciche odtwarzanie integracji i usunięcie nieaktualnej kontrolki liczby wątków. Dodatkowo naprawiono pozostawianie przycisków integracji w stanie zajętym po nieoczekiwanym wyjątku. Nie ustalono historycznego commita utraty każdej funkcji; nie oznacza to sześciu udowodnionych historycznie regresji. Dwa przypadki mają potwierdzenie wymaganiem użytkownika i raportem, ale bez odnalezionego dawnego kodu.

## Repozytorium i zakres

- Baza: `e21d625c0f6458bf43af5d1f1c06173e797f7536`.
- Gałąź naprawcza: `fix/gui-licenses-control-locks`.
- Osobny checkout: `C:\_DEV\SportCamHUD-gui-regression`.
- Wskazany historycznie katalog BikeRideHUD-main-new nie istnieje; README transferu dopuszcza zmianę nazwy na SportCamHUD, a SHA zatwierdzonej bazy jest zgodne.
- Oryginalny `C:\_DEV\SportCamHUD` zachował niezatwierdzone zmiany. Nie wykonano merge do main, zmian Intel/AMD/NVIDIA, budowy Portable ani benchmarku.
- `git diff --name-only e21d625 -- src/ffmpeg src/native src/indicators def_layout.json` jest pusty. Nie zmieniono GPU Pitch, map streamingu, HUD, Single Live Mux ani parametrów eksportu/audio. Brak pomiaru FPS oznacza brak deklaracji równoważności wydajności.
- Nowy układ wizualny został jawnie zlecony przez użytkownika: dotychczasowe ustawienia po lewej, zwężone; licencje po prawej na białym tle. Zastępuje wcześniejszą propozycję osobnego okna z przycisku.

## Dowody historyczne

Przeczytano raporty GUI_LOGIC_DEGREE_EXPORT_SETTINGS_CLEANUP, SPORTCAMHUD_ETAP_5Y_PORTABLE_RELEASE i SPORTCAMHUD_FULL_REGRESSION_AUDIT_20261011. Wymagany `RAPORT_BRAKUJACE_FUNKCJONALNOSCI_AUDYT_20261017.md` nie występuje w dostępnych plikach ani historii wszystkich refs: **NOT VERIFIED**.

Inwentarz obejmuje 290 osiągalnych commitów, 404 historyczne bloby Qt, 2394 wystąpienia reguł i 120 początkowych reguł aktualnego kodu. Przeszukano raporty (582 pliki pasujące do szerokiego filtra), `git log --all`, `-S`, `-G`, `git show`, różnice i bundle transferowy. Liczby są inwentarzem, nie dowodem kompletności semantycznego audytu. Dodatkowy checkpoint bundle `61c95b88e88e64b32dd741bd85d38ea20c76952f` jest drzewem, nie commitem; przeanalizowano 31 plików Qt i 101 wywołań reguł.

Nie odnaleziono dawnej implementacji GUI licencji ani implementacji `_update_main_tabs_state` / `sig_project_cleared`; ślady tych ostatnich są w testach i raportach `c52248b`. Dokładny commit wprowadzający/usuwający te funkcje: **NOT VERIFIED**. Nie przypisuję winy ostatniemu commitowi pliku. Dwanaście odmiennych dawnych wywołań setterów obejmuje także przeniesienia: Garmin do `_set_garmin_busy`, render do start/end, analiza QP do inspection, pola plikowe do chooserów/kart. Nie przywracano duplikatów tych reguł.

Dowody i skrypt odtwarzający inwentarz: `gui_recovery_20261018/control_history_inventory.json`, `git_gui_history.txt`, `git_license_search.txt`, `bundle_refs.txt`, `bundle_checkpoint_controls.json`, `initial_control_calls.txt`, `report_hits.txt`; `tools/audit_gui_control_history.py`.

## Macierz przed / po

Skróty: G5 = GUI_LOGIC_DEGREE_EXPORT_SETTINGS_CLEANUP; P5Y = ETAP_5Y_PORTABLE_RELEASE; F11 = FULL_REGRESSION_AUDIT_20261011. „Zachowane” oznacza sprawdzoną obecną regułę, nie nową poprawkę. NV = NOT VERIFIED.

| Funkcja | Raport / commit źródłowy | Stan przed i przyczyna | Naprawa / stan po | Test |
|---|---|---|---|---|
| Licencje w Ustawieniach | wymaganie użytkownika; P5Y; pakowanie `f3ba1bc`; dawny GUI commit NV | brak GUI czytającego dokumenty; moment utraty NV | prawy biały panel, oryginalne dokumenty, bez zgadywania licencji | Qt + dev + istniejący Portable |
| Dwie kolumny | jawne polecenie 2026-10-18 | pojedyncza kolumna | splitter, lewy scroll, prawy panel | widgety + zrzuty |
| Projekt na starcie | G5 / `c52248b` raport i test, implementacja NV | brak reguły blokującej zakładkę | disabled do gotowego projektu | rzeczywisty MainWindow |
| Projekt podczas ładowania | G5 / źródło NV | ogólny postęp/metadane mogły sterować UI za wcześnie | osobny stan loading/ready | Qt signal / worker |
| Projekt po ready | G5 / źródło NV | brak jednolitego kontraktu | enable i wybór po końcu inicjalizacji | rzeczywisty ffprobe i przycisk Wczytaj |
| Wyczyść projekt | G5 / źródło NV | czyszczenie formularza nie czyściło kontrolera | anulowanie loadera, media, telemetry/cache, reset metadanych | Qt clear + MP4 probe |
| Projekt po wyczyszczeniu | G5 / źródło NV | brak ponownej blokady | disabled, wybór Wczytywanie | Qt queued signal |
| Błędny pierwszy plik | G5 / źródło NV | zastępcze rozmiary mogły maskować pusty stream | wymagany prawidłowy stream i wymiary | ffprobe invalid MP4 |
| Błąd nowego pliku przy gotowym starym | G5 / źródło NV | stan przepisywany przed walidacją | walidacja kandydata przed zastąpieniem ścieżek | worker exception / prior valid |
| Spóźniony callback | F11 / źródło NV | brak znacznika generacji gotowości | identyfikator generacji, anulowanie, ignorowanie starego ready | queued/cancel test |
| Zamknięcie podczas load | F11 / źródło NV | worker mógł dalej pracować | ustawienie istniejącego cancellation event | window close test |
| Wyjątek zatrzymywania preview przy clear | dodatkowy brzeg | reset mógł zostać przerwany | diagnostyka i dalsze czyszczenie | injected exception |
| Wczytaj po błędzie | `982cb226` + nowe lifecycle | ogólny progress nie daje wiarygodnego ready | typed failed przywraca przycisk | real Qt + invalid MP4 |
| Rendering i Ustawienia bez projektu | G5 | muszą pozostać dostępne | zachowane | MainWindow states |
| Liczba wątków w GUI | G5 / `c52248b` kontrakt | stara kontrolka nadal obecna | usunięta tylko kontrolka; renderer bez zmian | stary kontrakt i Qt |
| Brak integracji = -- | G5 / `c52248b` | etykieta Nic niezgodna z kontraktem | -- | Qt/stary kontrakt |
| Odtwarzanie integracji | G5 / `c52248b` | setCurrentIndex emitował zmianę użytkownika | QSignalBlocker + notify=False | QSignalSpy |
| Zmiana integracji przez użytkownika | `15d8b0b` | wymagana emisja | zachowana, aktualizuje widoczność | QSignalSpy |
| Garmin busy | `93b7292`, `15d8b0b` | grupowe blokady zachowane | bez duplikowania dawnych setterów | Qt busy/error |
| Garmin nieoczekiwany wyjątek | dodatkowy błąd w obecnej bazie; utrata NV | worker kończył się bez sygnału odblokowania | wyjątek -> istniejący status -> unlock | injected provider error |
| Strava test / OAuth wyjątek | dodatkowy błąd w obecnej bazie; utrata NV | jw.; odczyt QLineEdit w workerze | unlock przez status, wartości pobrane w GUI | dwa injected error tests |
| Render preparing/running | F11; aktualny blob `1385e0d` | start blokowany, cancel dostępny | zachowane | Qt render states |
| Render cancelling | F11; `1385e0d` | ponowne anulowanie blokowane | zachowane | Qt render states |
| Render completed/cancelled/failed | F11; `1385e0d` | powrót przycisków | zachowane | Qt + queue lifecycle |
| Kolejka start/pauza | F11; `1385e0d` | zależności od stanu kolejki | zachowane | Qt + istniejący harness |
| Cache podczas renderu | aktualny Settings `f14e45f` | blokada niebezpiecznej zmiany | zachowana | Qt render/cache |
| GPU / rozdzielczość / HDR | F11; `1a389f8`, `1385e0d` | capability gating istnieje | bez zmian backendu | istniejące GPU capability tests |
| Zależne pola właściwości | `5bacdaa`, `3105550` | dynamiczne grupy | zachowane | 16 grup: marker/label/value/range/kolory/grow/shape/auto/outline/shadow |
| Brak telemetrii | aktualne Project UI | brak fałszywych strumieni | clear emituje pustą listę | Qt clear |
| YouTube | `38a45c8` | świadomie wycofane kontrolki | nie przywracano | existing disabled UI tests |
| Global preferences / katalog eksportu | `4b52155`, `1f7f8e0`, `25eb07e` | stare testy wymagają layout/autosave API | późniejszy jawny global save zachowany | stare 2 kontrakty nadal fail; obecne persistence tests pass |
| request_preview_refresh | G5 / `c52248b` test; źródło NV | dawnego helpera brak, obecny geometry_and_hud istnieje | bez sztucznego aliasu i zmian HUD | stary test fail; timing pixel NV |
| Segmenty/battery HUD | F11, dokładny commit utraty NV | osiem błędów już na czystej bazie | poza bezpiecznym zakresem zmian GUI | identyczne 8 fail na bazie |

## Implementacja i testy

Zmodyfikowane produkcyjne pliki: `src/gui/qt/signals.py`, `controller.py`, `_mixins/project_mixin.py`, `main_window.py`, `tabs/load_tab.py`, `tabs/settings_tab.py`; nowy `license_dialog.py`. Testy: nowy `tests/test_gui_recovery_states.py`. Narzędzia: `audit_gui_control_history.py`, `probe_gui_license_recovery.py`, `probe_gui_project_recovery.py`.

Gotowość jest osobnym sygnałem z generacją; samo 100% postępu ani znalezienie strumieni nie odblokowuje Projektu. Błędny kandydat jest sprawdzany przed zastąpieniem starego projektu. Nie przebudowano architektury loadera i nie dowiedziono wszystkich wyścigów ciężkiej telemetrii. Skan licencji jest leniwy i wykonywany poza GUI; krótkie `-L` działa przez asynchroniczny QProcess. Dokumenty tekstowe są tylko do odczytu. Ścieżki są względem katalogu aplikacji, a nie CWD.

Testy korzystają z istniejących modułów pytest projektu oraz rzeczywistych PySide6 widgetów/sygnałów; nie zmieniono starych asercji. Interpreter dev Python 3.15; pytest z istniejącego `C:\_DEV\SportCamHUD\scratch\testdeps` przez PYTHONPATH, Qt offscreen.

- **80 passed, 28.19 s**: nowe testy + render_tab_controls_cleanup + settings_and_amd_export_logging + export_queue_lifecycle + youtube_upload_ui_disabled. Log `gui_recovery_20261018/qt_final_tests.log`.
- **29 passed, 7.82 s**: gpu_runtime_capabilities, settings_skip_pauses_persistence, property_editor_scroll, load_tab_layout_action2. Log `qt_additional_tests.log`.
- Stary kontrakt G5: przed **1 passed / 5 failed**, po **3 passed / 3 failed**. Pozostałe: `_ensure_disk_persistence`, zapis katalogu w layout global, helper request_preview_refresh; opis rozróżnienia powyżej. Logi `legacy_contract_before.log`, `legacy_contract_after.log`.
- Szersza seria: **100 passed / 8 failed**. Ten sam plik segmentów uruchomiony na czystym e21d625: **25 passed / identyczne 8 failed**. Logi `qt_verified_tests.log`, `baseline_segment_tests.log`. Pozostają: test_canonical_count_precedence, test_v10_battery_new_gui_fields_change_raster, test_v10_segment_count_actual_render, test_save_load_new_wins_after_reload, test_gui_schema_fields_present, test_gui_ranges_sensible, test_gui_to_renderer_integration, test_battery_pct_real_normalisation. Nie ogłaszam zielonego pełnego harnessu.
- Faktyczny mały MP4 + rzeczywisty ffprobe + przycisk Wczytaj + MainWindow: **PASS** startup -> ready -> clear -> invalid-video. `project_probe/result.json`, log i zrzuty. Wyłączono tylko prezentację dekodera/GPU, ekstrakcję telemetrii i map prefetch; nie wykonywano eksportu. Nie jest to dowód pełnego podglądu MPV ani finalizacji eksportu audio.
- `git diff --check`: PASS. Początkowa próba ponownego pytest bez PYTHONPATH zgłosiła brak pytest; następna pełna seria z właściwą istniejącą zależnością przeszła. Nie instalowano pakietów do Portable.

## Licencje: dev i Portable

Uruchomiono nowe źródła panelu przy użyciu istniejącego `C:\GoPro\SportCamHUD-Portable\python\python.exe` (3.14), `-s -E`, z CWD `C:\`. Root testu to istniejący Portable; nie przebudowano ani nie podmieniono wydania. Panel odczytuje jego dokumenty i uruchamia jego rzeczywiste ffmpeg/ffprobe `-L` (oba exit 0). Zidentyfikowano **50 pozycji**, w tym dwie informacje programów. Dowody: `portable_licenses/result.json`, teksty `-L`, hashe binariów i zrzuty `settings.png`, `licenses.png`. QTimer heartbeat potwierdza pracę pętli zdarzeń podczas skanowania; nie jest pomiarem FPS.

Dev: analogiczny odczyt z obcym CWD i rzeczywistymi narzędziami: **99 pozycji**, oba programy exit 0, heartbeat 1688. Wyniki w `dev_licenses/result.json`. Portable heartbeat: 717. Zależności dev są jawnie oznaczone jako środowisko developerskie, nie przypisane do Portable.

Nie uznano ogólnego THIRD_PARTY_NOTICES za kompletny audyt wszystkich DLL. W rzeczywistym Portable metadane pyside6 6.11.1 zawierają `licenses/LicenseRef-Qt-Commercial.txt`, którego treść odsyła posiadaczy licencji komercyjnej do umowy Qt. Sam ten plik nie dowodzi praw dystrybucyjnych całego wydania ani nie uzasadnia przypisania LGPL wszystkim binariom. Dokładne warunki dystrybucji Qt: **NOT VERIFIED**. Dokumenty LICENSE.GPL/LICENSE.LGPL pakietu python_mpv nie ustalają licencji konkretnego natywnego libmpv. Pełna zgodność notice'ów/parsera/natywnych bibliotek: **NOT VERIFIED**. GUI pokazuje znalezione oryginały zamiast tworzyć brakujące teksty.

## Nierozwiązane i zakończenie

Brak jednego obowiązkowego raportu, niedostępna historia implementacji części kontraktów, osiem bazowych błędów segmentów i trzy stare kontrakty opisane wyżej ograniczają wynik do PARTIAL. Nie testowano prawdziwego logowania Garmin/Strava, prezentacji na każdej karcie GPU, timingu HUD, długiego renderu ani eksportu MP4 z audio w tym zadaniu GUI. Nie ma nowego wydania Portable.

Commit kodu/testów/narzędzi: **`dacd0a1af8e93093114a5a2d2544a9e4a892c921`**. Brak skonfigurowanej tożsamości Git zatrzymał pierwszą próbę; użyto jednorazowo autora Codex <codex@openai.com>, bez zmiany konfiguracji użytkownika. Raport i dowody są w osobnym commicie dokumentacyjnym. Dowody testowe znajdują się w `gui_recovery_20261018/`.

Autoryzowane powiadomienie do tematu `https://ntfy.sh/MalcerzPOP`: **HTTP 200**, ID **`8ohkxYmM3Mep`**, tytuł „SportCamHUD — GUI Regression Recovery”. Zawiera PARTIAL, licznik pięciu przywróconych rodzin wymagań i dodatkowego błędu, testy wraz z błędami bazowymi, commit i nazwę raportu. Pełna odpowiedź: `gui_recovery_20261018/ntfy_result.json`.
