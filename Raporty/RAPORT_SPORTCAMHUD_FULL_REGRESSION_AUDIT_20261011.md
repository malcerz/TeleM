# SPORTCAMHUD — pełny audyt regresji, historii Git i wydajności AMD

**Data audytu:** 2026-10-11 (Europe/Warsaw)  
**Tryb:** AUDIT ONLY — bez zmian kodu i konfiguracji  
**Repo:** `C:\_DEV\BikeRideHUD-main-new`  
**Gałąź / HEAD:** `fix/gui-freeze-hud-composite` / `310555087e31405b25e6a288093c04ee8be7ae63`  
**Wynik:** wykryto niezgodności raportów/testów z kodem, przerwane ścieżki AutoFIT i niepodłączony framework błędów. Pełna akceptacja AMD i realnych klipów DJI pozostaje **NOT TESTED**.

## A. Stan lokalnego Git i różnice względem remote

- Przeczytano `AGENTS.md` i `BENCHMARKS.md`. Obowiązują kanoniczne VIDEO/FIT pary oraz zakaz pre-ekstrakcji audio i tworzenia cache audio.
- Gałąź to `fix/gui-freeze-hud-composite`. HEAD jest `3105550`.
- Jedyna lokalna zmiana robocza to użytkownikowskie `def_layout.json` (M); plik pozostawiono nietknięty i nie stagingowano. Nie wykryto innych nieśledzonych plików przez status.
- `origin/fix/gui-freeze-hud-composite` jest na `2460ad7`; lokalny HEAD ma **3 commity naprzód, 0 w tyle**: `fa8ba86`, `570f60e`, `3105550`.
- `origin/amd-bikeridehud` (`befff14`): relacja licznikowa `1` commit wyłącznie po stronie remote, `99` po stronie HEAD; `origin/main` (`ae57717`): `10` remote-only, `65` HEAD-only. Gałęzie są rozbieżne, więc sama liczba commitów nie oznacza równoważnego stanu.
- Lokalny `main` (`3adc9ad`) ma inne ustawienie upstream i własną historię. `git worktree list` zawiera główny checkout, `worktree_baseline` (`fa8ba86`) i odłączony worktree AMD (`9451c4c`, oznaczony jako prunable). Nie zmieniano żadnego worktree.
- Remote: `https://github.com/malcerz/TeleM.git`. Nie pobierano zmian z sieci.
- Przejrzano log i reflog. Raport wcześniejszego incydentu `RAPORT_GIT_MAIN_PORTABLE_GPMF_VERSION_AUDIT.md` opisuje odtworzenie modułów commitami `c4328f8`, `163cf63`, `d95c6fb`, `d9d079a`, `23a9518`, po utracie roboczych plików powiązanej z `git clean`. Dostępny reflog nie dowodzi samodzielnie uruchomienia `git clean`; potwierdza natomiast odzyskanie i commitowanie modułów. Aktualne główne moduły są śledzone w Git. Nie znaleziono dodatkowej kopii obiektów z wymaganą brakującą implementacją w analizowanych źródłach.
- Brak operacji reset/clean/checkout/restore/stash/pull/merge/rebase/push. Brak synchronizacji portable.

## B. Wykryte utracone lub niepotwierdzone funkcje

1. **Default export directory:** brak GUI, pola ustawień i resolvera w kodzie głównym oraz w kopii portable. Testy i raport twierdzą, że funkcja istnieje, ale nie znaleziono commita wprowadzającego symbole ani commita usuwającego je. Można odzyskać wymaganie przez implementację selektywną, lecz z dostępnej historii nie ma fragmentu implementacji do cherry-pick.
2. **DJI Action 2 helpery:** `resolve_local_fit` i `probe_dji_telemetry_capabilities` są importowane przez testy, lecz nie istnieją w modułach źródłowych ani portable. Brak wyników `git log -S` dla tych symboli. Testy nie przechodzą już podczas kolekcji.
3. **Lokalny matcher AutoFIT:** poprzedni etap matchera potrafi zwrócić status `ambiguous`, ale skaner ignoruje ten wynik i kontynuuje punktację generyczną, po czym zwraca pierwszego kandydata bez progu pewności ani okna wyboru. To ryzyko automatycznego podpięcia niewłaściwego FIT.
4. **DJI bez czasu absolutnego:** bez GPS GPMF i bez wiarygodnego MP4 `creation_time` nie powstają przedziały czasowe. Ścieżka preflight pomija lokalny matcher, a zdalny matcher również nie ma ram czasowych do oceny; brak GPS uniemożliwia awaryjny match przestrzenny. To skutkuje brakiem AutoFIT (bezpieczniej niż pobranie złej aktywności), nie zaś poprawnym dopasowaniem.
5. **Render error framework:** klasy i helpery istnieją, lecz krytyczne preflight, monitor miejsca, klasyfikacja muxera i walidacja częściowego MP4 nie są wywoływane przez główny pipeline. Worker emituje tekstowy `sig_error`; kolejka przechowuje tekst błędu. Pełny typowany IPC i obsługa według klas nie są podłączone.
6. **Efekty HUD/cache:** kod ma efektowy renderer OpenCV/NumPy i cache maksymalnie 128 wpisów, ale brak limitu bajtowego. Cache L1 kluczuje po `id(image)` i konfiguracji, nie zachowuje źródłowego obiektu ani nie weryfikuje jego treści przed zwróceniem wyniku. Ponowne użycie identyfikatora obiektu może zwrócić nieaktualny raster. Nie wykonano reproduktora obciążeniowego, więc to ryzyko kodu, nie zaobserwowana awaria.
7. **DJI Action 6:** obecne raporty integracyjne opisują metadane kamery, ale dostępny raport z próbką Action 6 nie potwierdza kanałów IMU/GPS (gyro, accel, quaternion). Realne dane ruchu **NOT PROVEN**.
8. **Bieżący kompas:** w aktualnym kodzie znajdują się oba tryby wyboru kompasu i źródłowy resolver w zmianach z `570f60e`; raport podaje testy powierzchni wspólnej, ale pełny eksport kodera z prawdziwymi próbkami ruchu nie został sprawdzony w tym audycie.

## C. Macierz funkcjonalności raportowanych 2026-10-04–2026-10-11

Statusy dotyczą obecnego kodu, nie deklaracji w raporcie. Gdy kilka raportów pokrywa ten sam podsystem, grupowanie jest jawne. „Commit wdrożenia” wskazuje commit widoczny w historii, nie gwarantuje kompletności funkcji.

| FUNKCJA | RAPORT | COMMIT WDROŻENIA | PLIK/FUNKCJA | STAN OBECNY | REGRESJA | COMMIT UTRATY | MOŻLIWOŚĆ ODZYSKANIA |
|---|---|---|---|---|---|---|---|
| Telemetria Action 2, skip-pause / parity | `RAPORT_ACTION2_TELEMETRY_AND_SKIP_PAUSES_FINAL_PARITY.md`; `RAPORT_DJI_ACTION2_FULL_REGRESSION_FIX.md` | raporty/testy do `c52248b`; implementacja helperów nieznaleziona | `src/telemetry_dji.py`, `auto_telemetry_preflight.py` | BROKEN | dwa moduły testowe nie kolekcjonują się z powodu brakujących importów | nieustalony; brak implementującego commita w dostępnej historii | wymagane selektywne odtworzenie na bazie testów i realnego klipu |
| Domyślny folder eksportu | `RAPORT_DEFAULT_EXPORT_DIR_SETTINGS.md`; GUI cleanup | `c52248b` dodał testy/raport, nie implementację | `settings_tab.py`, `render_tab.py`, kontroler | MISSING | 7 testów nie przechodzi; pole/resolver brakują | nieustalony; `git log -S` bez implementacji | można zaprojektować zgodnie z kontraktem, ale brak kodu do odzyskania |
| GPMF kamera/data nagrania, metadata-only | `RAPORT_GPMF...`/GUI load reports; v1.14 load report | `420b28f`, `b27db2b`, `216e3f8` | `src/telemetry_native_gpmf.py`, `mp4_inspector.py`, load flow | PRESENT_UNVERIFIED | symbole/ścieżka istnieją, brak realnego klipu w tym audycie | brak ustalonego | testować realnymi plikami później |
| AutoFIT single coordinator / local match / GPS distance / late attach | `RAPORT...AUTOFIT...`, `RAPORT...V114_LOAD_PERFORMANCE.md` | `1f5e8649`, `f6ada939`, `2460ad7` | `auto_telemetry_preflight.py`, `project_mixin.py`, `multifile.py` | PARTIALLY_PRESENT | remis lokalnych kandydatów może przejść do arbitralnego wyboru; brak timestampu zatrzymuje match | brak usunięcia udowodniony | zachować koordynator; naprawa selektywna po akceptacji audytu |
| Garmin Connect / Strava providers, kandydaci i wybór | raporty AutoFIT i selection popup | `1f5e8649`, `a07e51c` | `activity_provider.py`, `activity_matcher.py`, preflight | PRESENT_UNVERIFIED | logika rankingu/selection istnieje; lokalny fallback obchodzi bezpieczny próg | nieustalony dla lokalnego fallbacku | wykorzystać matcher i selection flow istniejące w repo |
| GPMF native metadata i szybki load | metadata/load reports | `b27db2b`, `216e3f8` | `telemetry_native_gpmf.py`, `project_mixin.py` | PRESENT_UNVERIFIED | wybrane wejścia można sprawdzić statycznie; realny klip nie był dostępny | brak | test na istniejącej parze po zatwierdzeniu VIDEO/FIT |
| Kamera/date metadata UI | metadata report | `420b28f`, `b27db2b`, `216e3f8` | metadata parser/UI | PRESENT_UNVERIFIED | brak realnych danych wejściowych | brak | dostępne w Git |
| Błędy zapisu / kompatybilność wyjątków | `RAPORT_GIT_MAIN_PORTABLE_GPMF_VERSION_AUDIT.md`; error reports | odzysk `c4328f8`, później `0f7af96`, `c52248b` | `render_errors.py`, `output_error.py` | PARTIALLY_PRESENT | typy/helpery są, pipeline/IPC ich nie używa w wielu krytycznych sytuacjach | brak utraty klas wykazany | odzysk klas w Git; integrację zaplanować osobno |
| Kolejka renderowania, frozen trims, pause/resume, zapis stanu | queue/AutoFIT reports | `2429ac7`, liczne zmiany queue | `export_queue.py`, render mixin | PRESENT_UNVERIFIED | podstawowe stany i pause/resume istnieją; błędy są spłaszczane do stringów; nie wykonano pełnego GUI testu | nieustalony | kod obecny, potrzebna izolowana akceptacja |
| NVIDIA FPS rational / single-pass live mux | `RAPORT_NVIDIA_NATIVE_FPS_AUDIO_LIVE_MUX_FIX.md` | `fa8ba86` | NVIDIA/export paths | PRESENT_UNVERIFIED | kod commitowany; ten audyt nie testował enkodera | brak | dostępny commit; bez nowych zmian |
| Brak audio pre-extraction/cache | `RAPORT_LEGACY_AUDIO_CACHE_PERMANENT_REMOVAL.md`; release reports | `6e9b877`, `fa8ba86` | mux pipeline | PRESENT_UNVERIFIED | źródłowo raport i commity mówią o live mux; brak render acceptance | brak | zweryfikować bez generowania cache |
| AMD map/chart/gauge GPU paths i dirty-region | liczne AMD ETAP reports, baseline w `AGENTS.md` | historia do `3105550`; GPU paths są produkcyjne wg AGENTS | AMD native D3D11 compositor | PRESENT_UNVERIFIED | raporty mają profile, ale brak bieżącego bezpiecznego canonical A/B w tym audycie | brak ustalonego | jest worktree/oracle; bez canonical assets nie wykonać A/B |
| Outline, cień z fade, efekty 0–100% | `RAPORT_SPORTCAMHUD_FIX_OUTLINE_COMPASS.md`; effects performance report | `570f60e`, `3105550` | `effects.py`, indicator renderers | PRESENT_UNVERIFIED | wspólna ścieżka raster istnieje; cache bez byte cap; natywny real export nie sprawdzony | brak — obecna funkcja w lokalnych commitach | odzysk niepotrzebny; dalsze testy po potwierdzeniu obrazu |
| Dwa warianty kompasu i selected course | compass report | `570f60e` | compass renderer / heading resolver | PRESENT_UNVERIFIED | dostępne testy statyczne/report; prawdziwy plik nie sprawdzony | brak | commit jest lokalnie 3 do przodu remote |
| Wersja/rebrand / GUI async freeze fixes | release/load reports | `037b17d`, `3adc9ad`, `2460ad7` | application/load/gui | PRESENT_UNVERIFIED | identyfikatory i zmiany w historii; smoke GUI tutaj nieuruchomiony | brak ustalonego | obecne źródła Git |
| AMD effects performance | `RAPORT_SPORTCAMHUD_EFFECTS_PERCENT_AMD_FPS_FIX.md` | `3105550` | `effects.py`, scripts/report | NOT_PROVEN | raport podaje krótkie pomiary 300 klatek; nie ma kanonicznego materiału w repo, harnessu właściwego `tests/test_amd_real.py` brak w tej ścieżce | brak ustalonego | wymagane canonical inputs i surowe profile |

Wnioski o historii raportów: od `c52248b` wprowadzono testy/raport default-export i DJI Action2, lecz reachable history nie pokazuje ich implementacji. Zatem „pierwszy commit, gdzie funkcji zabrakło” nie może być uczciwie wskazany: nie znaleziono commitów, gdzie te symbole istniały. To **NOT PROVEN**, że działająca wersja kiedykolwiek była w zatwierdzonym Git.

## D. AutoSync DJI bez GPS — przyczyna i łańcuch

Łańcuch obecny w kodzie:

1. `multifile.probe_clip_time_interval()` rozstrzyga czas na podstawie GPS GPMF (GPS9/GPSU), a w razie braku używa MP4 `creation_time` jako wartości szacowanej; osobno potrafi oznaczyć jakość `exact`, `estimated` lub `degraded`.
2. `run_auto_telemetry_preflight()` dodaje klip do `intervals` tylko, jeśli `start_dt` istnieje. Zbiorcza pusta lista nie trafia do temporalnego dopasowania.
3. Przy `intervals=[]` lokalny matcher od razu zwraca `no_intervals`; brak punktu GPS uniemożliwia dystansowy fallback. Zdalny AutoFIT nie ma wiarygodnych ram czasowych, więc nie powinien pobierać losowej aktywności.
4. Gdy czas istnieje, `scan_and_match_local_telemetry()` najpierw woła `find_best_fit_match`. Ten matcher może zgłosić remis, lecz caller ignoruje diagnostykę i uruchamia skaner zastępczy. Skaner akceptuje każdy dodatni overlap lub pobliskie dopasowania, a następnie zwraca najwyżej punktowany plik bez sprawdzenia różnicy do drugiego kandydata i bez `needs_selection`.
5. Właściwy activity matcher ma ranking i flow `Needs_selection` dla kandydatów remote, lecz nie chroni lokalnego fallbacku przed remisem.
6. `project_mixin` ma późne podpinanie telemetry i generation/cancel guardy. SmartSync/reconciliation z FIT istnieje jako oddzielne etapy; skuteczność złożona na prawdziwym wieloplikowym DJI nie została wykazana.

**Action 2:** testy oczekują `resolve_local_fit`; symbol nie istnieje. Testy Action2 capability oczekują `probe_dji_telemetry_capabilities`; symbol nie istnieje. Obie kolekcje zatrzymują się na ImportError. Zatem deklarowane fixy nie są obecnie zweryfikowane w kodzie.

**Action 6:** wcześniejszy raport z klipu potwierdzał kamerę/obiektyw, lecz nie kanały ruchu/GPS z parsera. Dla obu kamer brak prawdziwych sample videos/FIT w kanonicznym katalogu, więc przypadki z `creation_time` poprawnym, błędnym i brakującym są sprawdzone wyłącznie ścieżką kodu, nie akceptacją end-to-end.

Rekomendacja późniejszej naprawy: zachować automatyczne dopasowanie, jeśli confidence jest wiarygodne i kandydat ma jednoznaczną przewagę; każdą niejednoznaczność skierować do jawnego wyboru użytkownika. Nie pobierać zdalnie bez bezpiecznego rankingu/wyboru. Przed wdrożeniem potrzebne klipy DJI i powiązane FIT.

## E. Domyślny katalog eksportu

`tests/test_default_export_dir_settings.py` definiuje wymagany kontrakt, ale `settings_tab.py` nie ma `edit_default_export_dir`, a `render_tab.py` nie ma `resolve_default_export_dir`. Nie znaleziono odpowiedników w kontrolerze ani portable source. `git log -S` dla obu nazw zwraca brak commitów.

Niedestrukcyjny test uruchomiony z pominięciem testu trwałego zapisu do root `def_layout.json`:

```text
python -m pytest tests/test_default_export_dir_settings.py -q -k 'not persists_after_restart'
7 failed, 1 passed, 1 deselected
```

Błędy wskazują brak kontrolek i resolverów. Test persystencji pominięto celowo, bo modyfikuje plik `def_layout.json` użytkownika. Dostępne dane nie pozwalają ustalić commita utraty ani wykazać, że funkcja była wdrożona. Przywrócenie kontraktu wymaga dodania brakującego elementu GUI, trwałego zapisu w global settings, resolvera wspólnego dla bezpośredniego renderu i kolejki oraz fallbacku do folderu źródła. To osobna implementacja, nie bezpieczny cherry-pick.

## F. Obsługa błędów — API, UI, IPC

- `src/ffmpeg/render_errors.py` definiuje typy dla storage, source, decoder, GPU, encoder, mux, audio, telemetry, subprocess i resource; są też preflight checks, `RuntimeStorageMonitor`, `classify_mux_error`, `validate_partial_output` oraz serializacja `to_dict/from_dict`.
- `output_error.py` zachowuje compatibility exports, ale eksport symbolu nie jest integracją.
- W kodzie pipeline nie znaleziono wywołań `classify_mux_error`, `validate_partial_output`, `RuntimeStorageMonitor`, `check_preflight_storage` ani `check_preflight_sources`. Typy decoder/GPU/encoder nie są systematycznie mapowane w ścieżce renderu.
- `render_mixin.py` łapie ogólny wyjątek, loguje traceback i emituje `sig_error(str)`; sygnał ma typ `str`. `export_queue.py` trzyma `render_error` jako string i raportuje `success/error` do GUI. Nie znaleziono transportu typed error payload przez granicę worker/IPC ani użycia `RenderError.from_dict` w tym przepływie.
- Błąd enkodera/capability może zostać pokazany jako tekst; brak miejsca na dysku, brak uprawnień, odłączony dysk, brak źródła, błąd dekodera/GPU/muxera, child process i walidacja częściowego MP4 nie są konsekwentnie klasyfikowane przed/po eksporcie.
- Anulowanie renderu ma osobną ścieżkę terminal state; kolejka ma pause/resume. Te elementy są obecne, lecz bez testu awarii i IPC nie można uznać ich zachowania dla wszystkich wymienionych błędów za sprawdzone.
- Jeden zbiorczy run testów przerwał się podczas kolekcji z powodu brakujących symboli DJI, więc pozostałe testy w tym poleceniu nie wystartowały. Nie raportuję ich jako PASS.

## G. AMD — historyczne i bieżące FPS / GPU

- Historyczny `RAPORT_AMD_CURRENT_41FPS_BOTTLENECK_AUDIT.md`: raportowane Render FPS ~41.31, Effective FPS ~40.59, GPU Video Codec 0 ~99%, 3D ~50–60%. To punkt historyczny, inny od aktualnej konfiguracji baseline.
- `AGENTS.md` podaje inny zaakceptowany AMD baseline: 4K/1131, Render FPS 26.359, Effective FPS 22.183, `above_compose` 19.065 ms, `producer_prepare` 31.759 ms, `consumer_native_call` 2.948 ms i `pipeline_total` 5.991 ms. Te dane również są referencyjne, nie nowym pomiarem.
- Commit `3105550` i raport efektów podają porównanie krótkiego zadania 300 klatek: 29.28 FPS bez efektów oraz 29.15–29.90 FPS z wariantami efektów; dla starej ścieżki PIL deklarują 2.56 FPS i `producer_prepare` ~388 ms. Brak wejściowych filmów kanonicznych, lokalnych surowych profili A/B i wykresów utilization potwierdzających liczby w bieżącym checkout.
- `Video/GX020079.MP4` i `.fit` nie istnieją w tym checkout. Harness `tests/test_amd_real.py` również nie istnieje pod tą ścieżką. Nie znaleziono bezpiecznej możliwości wykonania wymaganego canonical A/B w tej sesji. Nie podstawiano innego VIDEO/FIT; nie uruchamiano benchmarku, który mógłby tworzyć cache audio lub usuwać katalogi.
- Zgłoszone „80% GPU” jest nierozstrzygnięte: bez wskazania engine (3D, Video Encode, Video Decode, Video Codec 0 lub total), sterownika i okresu pomiarowego nie da się porównać z historycznym 99% Video Codec.
- Flagi `AMD_ABOVE_*`, `AMD_MAP_PATH`, `AMD_CHART_PATH`, `AMD_GAUGE_PATH` są w części zarządzane przez backendowe flagi środowiskowe; nie wykonano ablation ani nie zmieniano wartości produkcyjnych. Potrzebne są zarejestrowane wartości effective config z profilu.

## H. Czy GPU jest niedokarmiany przez CPU?

**NOT PROVEN.** Dostępne dane historyczne wskazują istotne czasy CPU `producer_prepare` i `above_compose`, które mogą ograniczać tempo podawania pracy, ale inny raport pokazuje prawie pełne użycie silnika kodeka. Nie ma wspólnego, aktualnego śladu CPU/GPU/encode/mux z jednego workloadu. Aby rozstrzygnąć, potrzebny jest równoczesny profile na canonical video, obejmujący producer wait, consumer queue wait, decode wait, CPU, GPU engine, AMF submit, mux i transfery.

## I. Ryzyka cache i efektów HUD

- Cache efektów ma limit **128 wpisów**, bez budżetu bajtowego. Duże obrazy RGBA mogą zajmować istotną pamięć mimo małej liczby entries.
- Klucz L1 `(id(image), cfg_sig)` nie utrzymuje referencji do obrazu. W hipotetycznym ponownym użyciu id może oddać stary wynik bez sprawdzenia alpha. Klucz L2 oparty na `hash(alpha_bytes)` również nie stanowi bezkolizyjnego digestu. Potrzebny bezpieczny test/reproduktor i zmiana klucza w późniejszym zadaniu.
- Przy outline fade renderer wykonuje dylatacje iteracyjne do szerokości; shadow length tworzy przesunięcia maski dla kolejnych kroków. Koszt może rosnąć z rozmiarem widgetu i długością. Brak pomiaru kosztu 100% length, ROI albo wariantów NEEDLE/ROSE w porównywalnym AMD run.
- Skala 0–100% i efekty w rendererze są obecne w kodzie. Raport z 11 października informuje o wspólnym compositingu i testach surface, ale sam raport nie dowodzi kompatybilności wszystkich natywnych ścieżek kodera.
- Nie wyłączano efektów, nie modyfikowano ich konfiguracji i nie zmieniano cache.

## J. Commity do selektywnego odzyskania / sprawdzenia

Nie stwierdzono brakującego commita z implementacją export-dir ani helperów DJI. Nie cherry-pickować raportów/testów jako substytutu kodu.

Dostępne commity warte audytu/wykorzystania w osobnym zadaniu:

- `1f5e8649` / `f6ada939` — AutoFIT coordinator, local/time/GPS matching; zachować architekturę, naprawić tylko niejednoznaczny fallback.
- `a07e51cb` — UI wyboru activity; może być ponownie użyte do local ambiguous selection.
- `b27db2ba`, `216e3f86` — metadata-only GPMF i optymalizacja load; testować na DJI/GoPro real sources.
- `c4328f8`, `163cf63`, `d95c6fb`, `d9d079a` — wcześniejsze odzyskanie modułów; to nie jest commit funkcji export-dir/DJI helperów.
- `570f60e`, `3105550` — compass/effects i performance implementations, lokalnie nieobecne na origin o trzy commity; testy native render pozostały poza zakresem audytu.
- `fa8ba86` — NVIDIA rational FPS/live mux, w audycie niezmieniany.

Dokładny commit utraty i „ostatni commit z funkcją” dla default export i dwóch DJI helperów: **NOT PROVEN**, bo symboli nie ma w dostępnej osiągalnej historii. Nie odzyskiwać całych modułów z portable; ich brakujące helpery również nie są obecne w źródłach portable.

## K. Kolejność bezpiecznego przywracania — do akceptacji

1. **P0 — AutoFIT ambiguity:** zachować jednoznaczne automatyczne matchowanie z wiarygodnym timestampem; gdy remis, uruchomić wybór użytkownika i nie pobierać automatycznie aktywności. Dodać realne przypadki: Action 2/6, creation_time poprawny/brakujący/niewiarygodny, ruch wieloplikowy.
2. **P0 — DJI capability/local FIT:** odtworzyć wymagane API na podstawie aktualnego parsera i zdefiniować bezpieczny fallback. Potwierdzić realne strumienie GPMF/DJMD oraz IMU/GPS zamiast zakładać je z modelu kamery.
3. **P1 — export directory:** zaimplementować pole globalne i wspólny resolver dla direct/queue, z testami na izolowanym layout; nigdy nie używać CWD jako przypadkowego fallbacku. Zachować istniejące GUI poza brakującym elementem.
4. **P1 — error pipeline:** podłączyć klasyfikację do rzeczywistego render/child process, przekazać typed payload przez IPC/queue, sprawdzać źródła i dysk, zweryfikować plik częściowy i wyświetlić kontekstowy komunikat. Utrzymać anulowanie i pause/resume.
5. **P1 — AMD pomiar:** po dostarczeniu canonical assets odtworzyć A/B na identycznej konfiguracji i z profilami engine; rozdzielić GPU Encode/Decode/3D/total. Najpierw correctness/pixel parity, potem performance.
6. **P2 — cache effects:** test ponownego użycia id, użycie trwałego content digest / bezpiecznej tożsamości źródła, limit pamięci bajtowej i pomiar worst-case shadow/outline/ROI/compass. Nie usuwać efektów.
7. **P2 — real preview/render parity:** realne klipy + jasne tło + turning course, porównać preview, pre-encode surfaces i final export; utrzymać selekcję obu wariantów kompasu.

## L. Testy i ograniczenia

Wykonano niedestrukcyjnie:

- `tests/test_default_export_dir_settings.py`, z wyłączeniem `test_default_export_dir_persists_after_restart`: **7 FAILED, 1 PASSED, 1 DESELECTED**. Failures dotyczą brakujących pól/metod.
- Zbiorczy run zestawów output errors, AutoFIT, DJI, load, effects i compass przerwał kolekcję: dwa `ImportError` (`resolve_local_fit`, `probe_dji_telemetry_capabilities`). Testy po tych błędach nie zostały wykonane.
- Statyczne sprawdzenie źródeł, raportów i symboli; przegląd historii, refloga, branch/worktree oraz portable.
- `git status` po audycie nadal pokazuje tylko modyfikację `def_layout.json`; plik zachowany.

Nie wykonano realnego preview/render, testu DJI, canonical AMD A/B ani testów, które zapisują do `def_layout.json`. Ograniczenia: brak canonical datasetów w `Video/`, brak potwierdzonego historycznego źródła implementacji brakujących funkcji, brak surowego bieżącego profilu GPU. Nie twierdzę, że akceptacja wizualna lub wydajnościowa przeszła.

## M. Potrzebne informacje i dowody od użytkownika

- Aktualny pomiar „80%”: zrzut/CSV z nazwą GPU engine, narzędziem, sterownikiem i czasem; osobno 3D, Video Encode, Video Decode/Codec i total.
- Dostęp do canonical plików `GX020079.MP4` + `GX020079.fit` oraz, jeśli potrzebne, canonical multi-file GX010114–116; nie trzeba zmieniać pairingów.
- DJI Action 2 i Action 6 sample videos oraz ich właściwe Garmin FIT, plus informacja, które pliki są wieloczęściowe i czy kamera miała poprawny zegar.
- Przykładowe lokalne FIT-y tworzące remis i oczekiwane zachowanie wyboru.
- Surowe profile/logi dla deklaracji 41.31 FPS i 29.x FPS, ustawienia layout/audio/mapy/encoder oraz engine utilization z tego samego przebiegu.
- Czy w przyszłej implementacji brakujący `default_export_dir` ma być ustawieniem globalnym w profilu użytkownika, czy w `def_layout.json`; obecny test oczekuje zapisu także do layoutu, co koliduje z globalnym znaczeniem ustawienia.

---

**Końcowy status:** audyt zakończony; kodu, ustawień produkcyjnych i istniejących raportów nie zmieniono. Zmiana `def_layout.json` użytkownika pozostała nietknięta. Brakujące funkcje nie zostały naprawione. Następny krok to akceptacja priorytetów z sekcji K oraz dostarczenie materiałów z sekcji M.
