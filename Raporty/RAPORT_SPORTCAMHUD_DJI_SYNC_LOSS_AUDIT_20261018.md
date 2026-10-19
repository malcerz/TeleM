# SportCamHUD — audyt utraconej synchronizacji DJI

Data: 2026-10-18. **Status: PARTIAL — potwierdzone braki bieżącej implementacji; dawna kompletna synchronizacja DJI i commity jej usunięcia NOT FOUND / NOT PROVEN.**

## 1. Zakres i stan repozytorium

Zbadano rzeczywisty working tree `C:\_DEV\SportCamHUD`, gałąź `main`, HEAD `e21d625c0f6458bf43af5d1f1c06173e797f7536`. Kod roboczy ma pierwszeństwo przed HEAD i raportami. Na początku istniały zmiany Intel/NVIDIA, wspólnego eksportu, application/render GUI, prywatnego def_layout i narzędzi. Pozostawiono je bez zmian. **Nie zmodyfikowano żadnego pliku produkcyjnego, testu, layoutu ani konfiguracji. Nie wykonano commita, checkoutu, merge, buildu Portable ani eksportu.** Dodano wyłącznie ten raport i dowody w `Raporty/dji_sync_audit_20261018/`.

Przeszukano wszystkie osiągalne lokalnie refs, także remote-tracking i tagi, bez pobierania z sieci: 292 commity. Lokalne gałęzie: main, backup/amd-release-checkpoint-20261017, backup/main-before-amd-release-20261017, fix/gui-freeze-hud-composite, fix/gui-licenses-control-locks. Pełne refs i SHA zapisano w `refs.txt`. Nie utożsamiano odrębnego checkoutu `SportCamHUD-gui-regression` z bieżącym main; jego poprawki nie są tutaj scalone.

Wykonano `git log --all`, wyszukiwania `-S` i `-G`, odczyty `git show` oraz analizę treści historycznych blobów: 502 wersje plików GUI/DJI, a następnie 1863 wersje plików Python i kopii .bak/.old z całej historii, również archiwum. Inwentarz nie obejmuje niedostępnych wcześniejszych repozytoriów, nieosiągalnych obiektów ani niepodłączonych paczek źródeł. Brak znalezionej wersji nie oznacza dowodu, że użytkownik nigdy jej nie miał.

## 2. Najważniejsze ustalenia

1. **GUI:** brak ręcznego ustawiania przesunięcia FIT/GPX i przycisków regulacji; brak przycisku uruchamiającego korelację SmartSync DJI. Projekt buduje podgląd, DataStreamBar i PropertyEditor. Nie znaleziono powiązanych sygnałów/handlerów synchronizacji aktywności. Kontrolki `lean_sync_ms` są inną funkcją i nie stanowią synchronizacji FIT/GPX.
2. **Algorytm DJI:** parser potrafi dostarczać żyroskop, akcelerometr i kwaterniony. Nie znaleziono kodu korelującego te sygnały z FIT/GPX ani ścieżki zamieniającej wynik takiej korelacji w korektę czasu aktywności.
3. **Istniejący SmartSync:** `_align_offset_by_track()` dopasowuje GPS GPMF GoPro do GPS FIT/GPX. To działający mechanizm przestawiania znaczników czasu danych zewnętrznych, a nie SmartSync IMU DJI. Przy braku śladów GPS pozostają fallbacki czasowe. AutoFIT bez GPS wybiera kandydatów aktywności na podstawie informacji czasowych i confidence; nie mierzy przesunięcia przez korelację IMU.
4. **Offset ręczny:** `telemetry_sync_offset_s` jest odczytywany i przesyłany jako `sync_offset_s`, ale w badanych ścieżkach wpływa na klucz cache, nie na oś próbkowania. Zmiana klucza nie dowodzi zastosowania korekty.
5. **Zapis:** ogólna serializacja layoutu zachowuje istniejący klucz. Nie ma kompletnego kontraktu „korekta tego projektu -> zapisz -> otwórz -> podgląd/eksport”. Zapis sesji i ponowne wczytanie korzystają z różnych ścieżek, a normalizacja layoutu usuwa nieznany klucz główny.

## 3. Tabela zachowanych i brakujących funkcji

| Funkcja | Working tree | Dowód implementacji / ograniczenie |
|---|---|---|
| Ręczny offset FIT/GPX w Projekcie | BRAK GUI | `src/gui/qt/tabs/project_tab.py`, widgets/data_stream_bar.py, sygnały i kontroler; brak całego łańcucha akcji |
| Przyciski +/- i reset przesunięcia | BRAK | brak konstrukcji kontrolek, sygnałów i handlerów, także w odnalezionej historii |
| SmartSync DJI z GUI | BRAK | brak akcji połączonej z algorytmem DJI |
| Korelacja IMU DJI z FIT/GPX | BRAK znalezionej implementacji | `src/telemetry_dji.py` parsuje, TelemetryDataManager ładuje kanały; brak obliczenia korekty na podstawie obu źródeł |
| Odczyt DJI IMU | ZACHOWANY zależnie od pliku/runtime | `_parse`, load_dji_telemetry, worker; nie każdy DJI zawiera użyteczne IMU; brak realnego pliku w tym teście |
| Zakotwiczenie próbek DJI w UTC | ZACHOWANE | próbki: `clip_start_utc + row[0]`; to przypisanie czasu klipu, nie korelacja z aktywnością |
| GPS GoPro <-> FIT/GPX | ZACHOWANY algorytm | telemetry_manager.py:110 `_align_offset_by_track`, wywołany z `_compute_smart_time_offset`; offset dodawany do FIT/GPX przed sync_*_to_video |
| Fallback UTC / strefa / początek aktywności | ZACHOWANY | telemetry_manager.py:300; nie ma pomiaru IMU i nie daje dowodu poprawnego dopasowania DJI |
| AutoFIT DJI bez GPS | ZACHOWANY mechanizm wyboru | integrations/auto_telemetry_preflight.py, multifile.py, telemetry_dji.py; odróżnić dobór pliku od synchronizacji sygnałów |
| telemetry_sync_offset_s w RAM | CZĘŚCIOWO | klucz może istnieć w surowym JSON layoutu; brak GUI nadającego mu wartość |
| Offset w sygnaturze cache | ZACHOWANY | render_preparation.py:334/366/1280; osobny test sprawdza wyłącznie zmianę klucza |
| Offset w próbkowaniu aktywności | BRAK w zbadanych ścieżkach | rzeczywisty cold build daje identyczne wartości dla 0 i +2 s |
| Zapis offsetu do active_layout.json | ZACHOWANY dla już istniejącego klucza | rzeczywiste `_save_session_layout()` zachowało +2,5 s w izolowanej ścieżce |
| Odtworzenie korekty tego samego projektu | NIESPÓJNE / niepełne | zapis do AppData/session; load sprawdza sidecar pierwszego filmu, preset, następnie def_layout; brak pełnej ścieżki odczytu tej korekty sesji |
| Offset przez normalize_layout | UTRATA WARTOŚCI | normalize_layout przywraca wybrane klucze, pomija telemetry_sync_offset_s; próba potwierdziła brak klucza po odczycie |
| Offset w surowym preset/sidecar load | WARTOŚĆ MOŻE PRZETRWAĆ | json.load zachowuje klucz, ale samo jego istnienie nie uruchamia przesunięcia czasu |
| Wieloplikowa oś UTC i przerwy | ZACHOWANE mapowanie | VideoTimeline global/local/absolute oraz precompute; brak dodatkowej ręcznej korekty |
| Synchronizacja przechyłu | OSOBNA, NIENARUSZONA | lean_sync_ms / telemetry_imu; nie traktować jej jako zamiennika offsetu FIT |

## 4. Historia: wersje źródłowe i usunięcia

**Nie odnaleziono ostatniej wersji kompletnej ręcznej synchronizacji DJI ani korelacji IMU DJI–FIT/GPX w dostępnych refs. Nie można wskazać commita usunięcia elementu bez poprzedniej implementacji i diffu usuwającego. Poniższe commity nie są automatycznie winowajcami regresji.**

| Commit | Potwierdzona zmiana | Znaczenie dla audytu |
|---|---|---|
| `4df3dad` (2026-07-25) | najstarszy dostępny snapshot; sync_fit_to_video / sync_gpx_to_video w starym kodzie | potwierdza wcześniejszą synchronizację timestampów; brak odnalezionych kontrolek i korelacji DJI |
| `7d09b095f41c48a448d612a6dfec27c7d055da1f` (2026-08-07) | dodaje `_compute_smart_time_offset` oraz zastosowanie przesunięcia timestampów FIT/GPX | mechanizm automatycznego dopasowania czasu, nie IMU DJI |
| `ee85231eacb5a8d996dd7b896a2e9962d2c70cb8` (2026-08-11) | dodaje `_align_offset_by_track` | GPS GPMF GoPro–FIT/GPX; nie DJI |
| `e019a6b45278f09f718f528642767f505ea87934` (2026-08-25) | zmienia dopasowanie przestrzenne/UTC | wcześniejsza postać aktualnego GPS SmartSync; nie usunięcie mechanizmu DJI |
| `47ee0b40d261817225b4f7c8a6909854ed13a808` (2026-09-03) | GUI/persistence, zapis sesji zamiast tworzenia sidecarów | istotny dla obecnego rozjazdu zapisu i load; nie dowodzi usunięcia działającej persystencji offsetu |
| `6f2045d` (2026-09-25) | odtworzenie interfejsu na bazie AMD | nie znaleziono wcześniejszych kontrolek DJI, więc brak podstaw do przypisania temu commitowi ich usunięcia |
| `353df3d6cfb1ab877ef57f14da64170ced6aa6b5` (2026-09-29) | DJI Action 6 metadata foundation, nowe kanały kamery | pierwsza odnaleziona dedykowana infrastruktura parsera DJI, bez korelacji IMU–FIT |
| `a2bb11f` (2026-10-03) | izoluje ciężkie parsowanie DJI w procesie | lifecycle parsera, nie algorytm synchronizacji |
| `02f4117362e9a45df50af780641feaf6015c259b` (2026-10-08) | wprowadza RenderPreparationService i offset w cache key | już w dodawanym pliku offset jest sygnaturą; nie znaleziono usunięcia wcześniejszego zastosowania do target_ts |
| `c52248b` | dodaje m.in. testy kontraktów DJI wymagające ensure_telemetry_manager / is_dji / clear_project | obecne źródła main nie spełniają części tych testów; sama nazwa testu/raport nie dowodzi istnienia historycznej implementacji |
| `b1e6507` (2026-10-10) | poprawki FIT/cache contract | zachowuje offset w kluczu; brak dowodu zmiany osi czasu |
| `a515c77` (2026-10-10) | wymaga mierzalnego wyniku GPS SmartSync w harnessie | chroni przed fałszywym PASS fallbacku czasowego |
| `982cb2268ea4ccb0c790e5856286f079e9a6935a` (2026-10-11) | AutoFIT i DJI no-GPS | nie przywraca ręcznego offsetu ani korelacji IMU |
| `98a58df`, później `4eab62a` | szybkie stany telemetrii NVIDIA / poprawki | aktualny osobny generator czasu NVIDIA wymaga uwzględnienia w przyszłym kontrakcie |
| `e21d625` + working tree | obecny stan | opisane braki nadal występują |

Usunięcie GUI ręcznego: **NOT FOUND**. Usunięcie przycisków: **NOT FOUND**. Usunięcie SmartSync DJI IMU: **NOT FOUND**. Usunięcie zastosowania telemetry_sync_offset_s do osi czasu: **NOT FOUND**; odnaleziona historia tego klucza zaczyna się od obsługi cache, nie potwierdzonej wcześniejszej funkcji czasu. Ostatnia działająca pełna wersja DJI: **NOT VERIFIED**. Źródła innej paczki mogły nie trafić do tych refs; potrzebne byłyby do wskazania dokładnej utraty.

## 5. Podgląd i backendy — prześledzone wejścia czasu

| Ścieżka | Faktyczne wyznaczanie czasu | Offset aktywności |
|---|---|---|
| Podgląd | preview_mixin.py:43 `_resolve_preview_time`: global -> clip/local -> absolute; fallback start_dt_utc + global. `_render_preview_sync` używa target_dt | nie odczytuje telemetry_sync_offset_s; rzeczywisty resolver dał ten sam wynik dla 0/+2 |
| AMD native D3D11 | render_mixin.py:1271 -> streaming.py:1342/1440 -> amd_native_exporter.py:2196/4723 -> RenderPreparationService.get_or_build. target_ts z UTC timeline lub i/fps | parametr dociera do klucza; nie dociera jako przesunięcie do buildera próbek |
| Intel native D3D11/QSV | intel_native_exporter.py:1503 -> telemetry_precompute.build_telemetry_cache; target_dts z frame_to_absolute lub base+i/fps | brak korekty z layoutu w tej ścieżce; wspólny parent cache key nie gwarantuje użycia tego samego cache |
| NVIDIA native D3D11/NVENC | nvidia_native_exporter.py:1196 -> telemetry_states_fast.compute_fast_telemetry_states; sekundy z clip absolute_start/local_start/global_start | generator nie otrzymuje layoutu ani parametru ręcznego offsetu; korzysta z aktualnych próbek managera |
| Streaming / fallback FFmpeg | streaming.py:2317 -> telemetry_precompute.build_telemetry_cache | ten sam brak aplikacji telemetry_sync_offset_s w builderze |
| Wieloplikowy eksport | VideoTimeline odwzorowuje skompresowany czas eksportu na prawdziwe czasy klipów, z zachowaniem przerw UTC | to zachowane mapowanie nie realizuje ręcznej korekty FIT/GPX |

Nie jest to wynik uruchomionych enkoderów. Analiza potwierdza brak połączenia parametru z osią czasu w kodzie, lecz **nie wykonano rzeczywistych eksportów Intel/AMD/NVIDIA ani porównania ich pikseli**. Istniejący GPS SmartSync modyfikuje timestampy zewnętrznych próbek wcześniej, dlatego może działać niezależnie od nieczynnego ręcznego parametru. Nie należy ogłaszać, że cała synchronizacja FIT z każdym filmem jest zepsuta.

## 6. Zapis korekty — szczegóły

`normalize_layout_for_save()` kopiuje layout i zachowuje telemetry_sync_offset_s. `_save_session_layout()` zapisuje go do `%LOCALAPPDATA%\SportCamHUD\session\active_layout.json`; `_save_project_layout()` jest aliasem tego zapisu. Próba wywołania oryginalnej metody z izolowaną ścieżką dała +2,5 s po odczycie JSON.

Przy otwieraniu filmu project_mixin.py:653 sprawdza `<pierwszy film>.layout.json`, potem preset, potem normalize_layout(def_layout). Surowy sidecar/preset zachowuje klucz, ale nie nadaje mu skutku. normalize_layout w layout_manager.py:298 wybiera jawne klucze, pomijając offset; rzeczywisty odczyt +2,5 s przez tę funkcję usunął klucz. Nie odtwarza się tu zapisanej korekty sesji jako trwałej korekty konkretnego zestawu filmów. Przywrócenie wyłącznie przycisków GUI byłoby niewystarczające.

## 7. Testy i harness

Uruchomiono istniejące pliki: test_telemetry_manager, test_dji_telemetry, test_dji_gui_worker, test_dji_action2_none_fix, test_dji_action2_capability_probe, test_common_render_preparation, test_fit_gpx_file_validation. Bez zmian asercji, `-p no:cacheprovider`, Qt offscreen; pytest z istniejącego scratch/testdeps przez PYTHONPATH.

- Python 3.15 dev: **59 passed, 8 failed, 7 skipped**, 5,08 s; `existing_tests.log`. Jeden dodatkowy fail to test oczekujący dosłownie „Python 3.14” w komunikacie ABI na interpreterze 3.15.
- Python 3.14 istniejącego Portable, bez jego przebudowy: **60 passed, 7 failed, 7 skipped**, 14,98 s; `existing_tests_python314.log`.
- Siedem pozostałych fail: `test_dji_manager_exists_before_load`, `test_clear_then_reload_reinitializes_dji_correctly`, `test_dji_single_file_load_does_not_call_none`, `test_dji_multifile_load_does_not_call_none`, `test_dji_and_fit_can_coexist`, `test_late_fit_attach_preserves_dji`, `test_stale_dji_worker_result_is_ignored`. Błędy: brak ensure_telemetry_manager, clear_project, is_dji oraz brak start_dt_utc w danych podstawionych przez test. To niespełnione kontrakty testów obecnego main; nie każdy fail dowodzi awarii prawdziwego pliku DJI. Nie maskowano ich zmianą fixture'ów.
- Pomijane przypadki obejmują opt-in real DJI/worker oraz brak realnych fixture'ów SmartSync. Nie uznano ich za PASS.

**Kanoniczny harness synchronizacji:** `scripts/test_sync_integrity.py`, uruchamia `SportCamHUD.py --test-sync-integrity --video ... --fit ... --result-json ...`. Pozytywna para według BENCHMARKS.md: `Video/GX020079.MP4` + `Video/GX020079.fit`. Negatywna domyślna: `F:\GoPro\2026-09-25\GX010321.MP4` + `Poranna_jazda_na_rowerze.fit`; są też przypadki missing-file. Harness wymaga GPS overlap, punktów dopasowania, coverage, median/p90 i offsetu, a nie tylko etykiety VALID. **NOT RUN / BLOCKED przez brak wymaganych plików pod zdefiniowanymi ścieżkami.** Nie zastąpiono pary innym materiałem. To harness przestrzennego GPS SmartSync, nie kanoniczny test korelacji DJI IMU. Harnessu dla kompletnej ręcznej synchronizacji DJI / IMU nie odnaleziono.

`test_cache_key_changes_on_sync_offset` sprawdza tylko różnicę hashy. Nie sprawdza przesunięcia wartości, podglądu ani eksportu. Testy GPS w test_telemetry_manager sprawdzają realne wywołania algorytmu na syntetycznych trajektoriach; nie dowodzą działania DJI bez GPS.

Dodatkowe próby diagnostyczne (nie zastępują harnessu):

1. Oryginalny get_or_build, oddzielne cold buildy, próbki prędkości 0/10/20/30, offset 0/+2 s: **inne klucze, identyczne wartości**. `offset_probe.json`; w tym samym badaniu potwierdzono serializację +2,5 s.
2. Rzeczywisty VideoTimeline z dwoma syntetycznymi klipami: 2 s od t0 i 2 s od t0+10 s (8 s przerwy). Podgląd global 2 s -> UTC t0+10 s zarówno dla offsetu 0, jak +2. Oba rzeczywiste buildery (wektorowy i scalar używany przez Intel/streaming) dały `[0,10,100,110]` dla obu offsetów. `multifile_and_reload_probe.json`. Nie były to pliki wideo ani test enkodera.
3. Rzeczywisty normalize_layout: offset pominięty. Nie zapisano nic do prywatnego def_layout ani przy materiałach.

## 8. Czy można naprawić bez przebudowy renderera?

**Ręczną korektę można zaprojektować w warstwie czasu/telemetrii i GUI, bez zmiany natywnych kompozytorów, D3D11, QSV, VBR, audio czy HUD.** To ocena na podstawie istniejących wejść timestampów, nie zweryfikowana implementacja. Nie wystarczy poprawić samego cache key lub tylko gałęzi AMD. Trzeba obsłużyć podgląd, common vectorized, scalar precompute i NVIDIA fast states, ewentualnie podając im już skorygowane kanały aktywności.

Automat DJI wymaga najpierw odnalezienia rzeczywistego dawnego algorytmu albo osobnego projektu i walidacji. Nie można obiecać jego „przywrócenia” przez cherry-pick odnalezionego parsera. Nie każdy model/plik DJI ma IMU; przykłady metadanych bez użytecznych kanałów muszą kończyć się jasnym brakiem możliwości automatycznej korelacji.

### Pliki do przyszłego odtworzenia / uzupełnienia

Nie jest to lista plików z potwierdzonym starym działającym mechanizmem; takiej wersji nie odnaleziono.

- GUI: `src/gui/qt/tabs/project_tab.py`, `signals.py`, controller.py oraz odpowiedni mixin projektu — kontrolki, aktualizacja stanu, wynik auto/manual i anulowanie. Nie przywracać całych historycznych plików GUI.
- Stan projektu: `_mixins/preset_mixin.py`, `_mixins/project_mixin.py`, `src/gui/layout_manager.py` — jednoznaczny zapis/odczyt korekty dla konkretnego projektu, nie przypadkowego globalnego presetu.
- Telemetria: `src/gui/telemetry_manager.py` lub wydzielona niewielka warstwa korekty aktywności — oryginalne kanały i korekta stosowana dokładnie raz.
- Konsumenci czasu do weryfikacji: `_mixins/preview_mixin.py`, `src/render_preparation.py`, `src/telemetry_precompute.py`, `src/telemetry_states_fast.py`.
- Przekazanie stanu/snapshotów i invalidacja cache: `_mixins/render_mixin.py`, `src/ffmpeg/streaming.py`; eksportery Intel/AMD/NVIDIA sprawdzić kontraktowo. Nie zakładać konieczności edycji DLL ani całego eksportera.
- Algorytm DJI: nowy/odzyskany moduł nad danymi z `src/telemetry_dji.py`, bez przebudowy parsera i bez ingerencji w `telemetry_imu` / lean_sync_ms.
- Testy: rozszerzenie istniejącego harnessu z odrębnym scenariuszem DJI; testy znaku, ±offset, resetu, reloadu, cache hit/miss, klipów/przerw/cutów, GUI i parity backendów. Obecny harness GPS zachować.

### Zalecana kolejność naprawy — niczego z tej listy teraz nie wdrożono

1. Zabezpieczyć bieżące zmiany i ustalić bazę. Uzupełnić brakujące rzeczywiste źródła wcześniejszej synchronizacji, jeżeli są dostępne poza refs.
2. Uzgodnić i przetestować znak korekty: istniejący GPS SmartSync dodaje offset do timestampów FIT; przesunięcie query musi mieć znak odwrotny. Wybrać jeden punkt zastosowania i zabezpieczyć przed podwójną korektą auto+manual. Nie przesuwać UTC filmu ani IMU kamery.
3. Naprawić per-project persistence i bezpieczne zerowanie przy zmianie projektu, zanim GUI zacznie zapisywać korekty.
4. Zapewnić wspólne znaczenie korekty aktywności w podglądzie i wszystkich generatorach telemetrii, w tym wieloplikowych przerwach i eksportowanych zakresach. Zachować kamerę, czas ekranowy, lean i audio na ich obecnych osiach.
5. Dodać ręczne kontrolki, reset, zakres i czytelny opis znaku; immediate preview oraz invalidację cache. Najpierw testy sztucznego sygnału z oczekiwanymi wartościami.
6. Dopiero potem odzyskany/nowy SmartSync DJI: walidacja dostępności IMU, pewności dopasowania, sytuacji niejednoznacznych i odmowy wyniku. Nie używać align-start fallbacku jako dowodu pomiaru.
7. Kanoniczny harness GPS bez regresji, nowy scenariusz DJI i rzeczywiste krótkie eksporty Intel/AMD/NVIDIA single/multifile z tym samym zatwierdzonym materiałem. Następnie kontrola FPS/GPU; bez automatycznego długiego benchmarku.

## 9. Ryzyka regresji

| Obszar | Ryzyko przy nieostrożnej naprawie | Zabezpieczenie wymagane przed wdrożeniem |
|---|---|---|
| Intel | parent przygotowuje common cache, native korzysta też z scalar buildera; poprawienie tylko jednego daje inną telemetrię w preview/export | wspólny kontrakt wartości i czasu; rzeczywisty QSV/native smoke, bez zmian powierzchni/DLL |
| AMD | offset już wpływa na key; zmiana danych bez aktualizacji sygnatury lub podwójne przesunięcie psuje HIT/MISS, mapę i chart cursor | test key i zawartości cache, czysty cold/warm, zgodność map/charts oraz krótki native smoke |
| NVIDIA | odrębne fast states nie otrzymują layoutowego offsetu | sprawdzić jego wejściowe próbki i parity z common/scalar, nie ograniczać się do render_preparation |
| Wieloplikowy | użycie czasu skompresowanego zamiast absolute UTC gubi przerwy; cięcia i start_frame mogą dodać offset drugi raz | testy granic klipów, przerw, zakresów i ciągłości aktywności |
| Kamera / przechył | globalne przestawienie start_dt_utc przesuwa także IMU, lean, czas filmu i kanały kamery | korekta wyłącznie odpowiednich źródeł FIT/GPX, osobno od lean_sync_ms |
| Audio | przesuwanie wejściowych timestampów FFmpeg zamiast telemetrii narusza mux/A-V sync | brak zmian audio/ffmpeg timing; nadal oryginalny MP4 jako źródło audio |
| Wydajność | per-frame kopiowanie/listy, ponowne parsowanie lub odtworzenie mapy | korekta na etapie przygotowania/warstwy query, bez dodatkowego worker/render loop |
| GUI async | spóźniony automat stosuje korektę do innego projektu | generacja projektu, anulowanie, zatwierdzenie wyniku tylko dla bieżących źródeł |

## 10. Granice wyniku

Audyt kodu i testy potwierdzają brak GUI, brak znalezionego algorytmu DJI oraz nieczynny ręczny parametr w badanych generatorach czasu. Część zapisu zachowuje samą wartość, lecz nie ma działającego end-to-end kontraktu. Zachowany GPS SmartSync jest odrębną funkcją i rzeczywiście zmienia dane FIT/GPX.

**NOT TESTED:** rzeczywista korelacja DJI, enkodery Intel/AMD/NVIDIA, eksport MP4/audio, finalizacja wieloplikowa na mediach, FPS i piksele HUD. **NOT PROVEN:** ostatnia kompletna wersja dawnego mechanizmu i commity jej usunięcia. **BLOCKED:** realny kanoniczny harness bez wymaganej pary plików. Żadnych zmian D3D11/QSV/VBR/HUD/audio/przechyłu nie wykonano.

Dowody: `dji_sync_audit_20261018/` — refs, status początkowy/końcowy, historia offsetu i DJI, historia ProjectTab, wyniki dwóch serii pytest, inwentarze blobów i JSON prób. Dawne raporty wykorzystano pomocniczo (DJI metadata/freeze/no-GPS i V111 sync integrity); rozstrzygają odczytane źródła oraz rzeczywiste wyniki, nie etykiety PASS w raportach.
