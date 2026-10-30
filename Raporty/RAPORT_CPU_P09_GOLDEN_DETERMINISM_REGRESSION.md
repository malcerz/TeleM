# SportCamHUD CPU P0.9 — Golden Harness i regresje

## Status: CZĘŚCIOWO — poprawka harnessu zacommitowana w P1.0 z ograniczeniami poniżej

> **Aktualizacja P1.0 (2026-10-30):** poprawkę ponownie zweryfikowano przed commitem na tej samej, jawnie wskazanej parze `C:\GoPro\GX010378.MP4` + `C:\GoPro\2026-10-15_15-03-50.fit`: 30 klatek od 900, 2 workery, Golden frame 15 — 0/30 różnych SHA-256 RGBA względem `checked_s900_w2.hashes.jsonl`, edytor vs `compose_overlay` i edytor vs potok 0 różnych pikseli (max_diff 0, MAE 0); log: mapa generacja 2, `export:cpu` 74/74, `Golden CPU READY` przed startem eksportu. Zestaw testów jak niżej ponownie 58 passed / 5 skipped. Ograniczenia bez zmian: `tests/test_golden_parity_etap4.py` 2 FAIL = **BLOCKED** (brak danych i wzorca, para zabroniona przez BENCHMARKS.md), historyczny Golden P0.4 na GX010370 **BLOCKED** (materiał niedostępny), sprzęt AMD/NVIDIA **NOT TESTED**, brak regresji FPS eksportu **NOT PROVEN**. Wzorców nie zmieniano. Commit obejmuje wyłącznie `src/gui/qt/application.py` (ścieżka `--golden-dir` harnessu), ten raport i `CPU_P09_GOLDEN_DETERMINISM/`.

Kanoniczny CPU Golden Harness został poprawiony i dla dostępnego materiału porównania dają 0 różnic pikselowych. Nie ogłaszamy pełnego PASS: dwa testy starszego zestawu Golden nie przechodzą z powodu niedostępnych danych i wzorców; sprzętowe AMD/NVIDIA oraz historyczny rerun P0.4 nie zostały sprawdzone. Zgodnie z warunkiem użytkownika nie opublikowano nie w pełni zweryfikowanej poprawki jako zakończonej. `src/gui/qt/application.py` oraz niniejszy raport i diagnostyka pozostają lokalnymi, niezacommitowanymi zmianami P0.9.

## Git i wejścia

Przed etapem `cpu-optimization`, HEAD `ff4258612273fdf108e5dd4d31e9fd07290df1ec`, `git branch -vv` wskazał tracking origin, a `git ls-remote` zwrócił ten sam SHA. P0.8 było więc zacommitowane i opublikowane. Zastano 778 usunięć, 107 modyfikacji i 338 nieśledzonych pozycji; indeks pusty. Pozostawiono je, w szczególności NVIDIA/AMD/Intel QSV i telemetrię. Jedynym zmodyfikowanym śledzonym plikiem P0.9 jest wcześniej czysty `src/gui/qt/application.py`; kod wspólnych rendererów P0.8 bez zmian. Nie wykonano resetu, clean ani force push.

## Przyczyna i poprawka gotowości

`_configure_export()` przełącza backend na CPU, wyzwalając nowe przygotowanie mapy, ale wcześniej wywoływał `capture_editor_hud()` natychmiast po ustawieniu opcji. Zrzut mógł więc użyć poprzedniego stanu mapy Intel. W P0.8 ta kolejność dała 93497 różnych pikseli mapy; po przygotowaniu docelowej mapy było 0.

Dla `--test-cpu-export --golden-dir` zrzut przeniesiono bezpośrednio przed start eksportu, po konfigurowaniu CPU i po `export_readiness_state() == ready`, które weryfikuje właściwą sygnaturę mapy/kafelki, gotową telemetrię, kompas i lean. Oczekiwanie wykorzystuje sygnały gotowości projektu, HUD, mapy i kompasu, bez okresowego odpytywania; jednorazowe zero-ms QTimer służy wyłącznie do przekazania uruchomienia ładowania pętli zdarzeń. Stan jest sprawdzany ponownie przed zrzutem. Watchdog `--golden-ready-timeout` (domyślnie 120 s) dotyczy ładowania i przygotowania; failure, nie-CPU lub błąd zrzutu zapisują wynik `success=false`, czytelny powód i kod 1. Niedozwolony indeks Golden odrzuca parser. Nie zmieniono wyglądu mapy/HUD. Bez `--golden-dir` dotychczasowa ścieżka pozostaje bez zmian.

Test rzeczywisty: timeout 0,01 s => exit 1, `Golden CPU readiness: timeout przygotowania docelowego backendu`; wstrzyknięty stan mapy `failed` => exit 1, `syntetyczna awaria mapy P09`. W próbach sukcesu log pokazuje generację mapy 2, `export:cpu`, ready 74/74, następnie Golden CPU READY i start eksportu. Nie zmieniano źródła ani wzorca P0.4.

## Golden i deterministyczność

Materiał `C:\GoPro\GX010378.MP4` + jawnie wskazany `C:\GoPro\2026-10-15_15-03-50.fit`, lokalny `def_layout.json`, 4K, Szybki, ABR 16M, HEVC Main10 HLG. Ostateczna wersja harnessu: 30 klatek na fragmentach od 900 i 1800, po jednym eksporcie dla 1/2/4 workerów na każdy fragment; porównano wszystkie 30 hashy RGBA. Dodatkowa wcześniejsza seria 60 klatek na fragment dla każdego wariantu także dała 0 różnic.

| Kontrola | Wynik |
|---|---|
| 900: 1 vs 2 oraz 1 vs 4 | 0/30 różniących się klatek SHA-256 |
| 1800: 1 vs 2 oraz 1 vs 4 | 0/30 różniących się klatek SHA-256 |
| 180°: każda z klatek 0, 15, 29, w obu fragmentach, edytor/compose_overlay/potok | 0 różnych pikseli w każdym porównaniu |
| 0°: klatki 0, 15, 29 przy starcie 900, edytor/compose_overlay/potok | 0 różnych pikseli w każdym porównaniu |
| Przed P0.8 (raport P0.8), dwie próby 2-worker | 48/150 różnych klatek |

Przed porównaniem obu obrazów jednakowo wyzerowano RGB tam, gdzie alfa = 0; dla źródła 180° zrzut potoku obrócono raz do orientacji edytora. W badanych obrazach mapa/ślad, kompas, lean, wykresy, BAR-y, teksty i bateria wchodzą w porównanie całej klatki; nie jest to dowód dla innych wartości i layoutów. 0° sprawdzono na istniejącej kopii testowej `C:\GoPro\TO\p08\source0b.mp4`, sporządzonej w P0.8 ze zmienioną display matrix i zachowanymi strumieniami wideo/audio/GPMF. W P0.9 nie przeprowadzano wtórnego remuxingu eksportu. Liczby i hashe w `CPU_P09_GOLDEN_DETERMINISM/checked_comparison.json` i `*.hashes.jsonl`. Rekordy i obrazy z lokalizacją pozostają lokalnie w `C:\GoPro\TO\p09`.

Wszystkie 9 końcowych eksportów 30/30 zakończyły się sukcesem, `valid=True`, zgodnością koloru i obecnością audio. ffprobe wybranych wyników: HEVC Main 10 yuv420p10le, BT.2020/arib-std-b67, AAC; 180° matrix −180, 0° bez matrix. W audycie procesów CPU FFmpeg jedyny proces eksportowy mapował `-map 0:a? -c:a copy` z oryginalnego MP4 i wejście RGBA przez pipe; bez wyodrębniania i audio cache. Kod finalizacji zmienia matrix in-place, nie wykonuje wtórnego remuxu; eksport poprawnie ukończony. Porównanie rekordów 2/4-worker z tym samym startem i P0.8 potwierdza indeksowanie 900–929 oraz 1800–1829; dane FIT/GPMF są użyte w tym konkretnym projekcie. GPX i inne przypadki synchronizacji NOT TESTED. Hash HEVC nie był warunkiem poprawności.

## Testy rendererów i GPU

Wybrany zestaw `test_cpu_p08_hud_determinism.py`, `test_cpu_golden_p04.py`, `test_cpu_p0_correctness.py`, `test_cpu_p03_presets.py`, `test_lean_parity_5xl.py`, `test_lean_gpu_bridge.py`, `test_compass_and_shadow_outline.py`, `test_dynamic_export_backends.py`: **58 passed, 5 skipped**. Testy P0.8 weryfikują wynik dla tego samego pełnego kąta przy różnej historii cache; pikselowa zgodność całych obrazów powyżej obejmuje pozycję, grubość i antyaliasing w badanych klatkach. Testy kontraktowe obejmują wybór backendów AMD i NVIDIA oraz lean GPU bridge; nie zastępują sprzętowych prób.

Dodatkowo `tests/test_golden_parity_etap4.py`: **2 passed, 2 FAILED**. `test_golden_elements_presence_and_bboxes` nie ma mapy w wyniku przy braku danych wejściowych, `test_golden_pixel_parity` nie znajduje `tests/golden_parity/golden_ref_track_map_frame150.png`. Test wskazuje `Video/GX030120.MP4` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit`, parę wprost zabronioną przez BENCHMARKS.md; te pliki również nie są dostępne. Nie podstawiono innego FIT i nie zmieniono wzorców. Rerun historycznego CPU Golden P0.4 wymaga niedostępnych `D:\GoPro\GX010370.MP4` i FIT, więc NOT TESTED; integralność zamrożonego obrazu PASS.

Intel Iris Xe, kanoniczny `--test-intel-export`, 60 klatek, sprzętowy Intel native/QSV: **PASS**, 60/60, 17,17 FPS, MP4 video+audio valid, flush 60/60, rc=0. AMD i NVIDIA: kontrakty jak wyżej, **sprzęt NOT TESTED** (na tej maszynie tylko Intel). Nie modyfikowano ich backendów.

## Wydajność i pamięć

600 różnych kątów w izolowanym procesie z typową konfiguracją 4K, pomiar orientacyjny, jeden przebieg na wersję, bez renderowania całej klatki; `cache_before.json` to historyczna zaokrąglona wersja błędna, `cache_exact.json` aktualne pełne klucze:

| Wskaźnik | ms/klatkę stare → pełne | wpisy przy 600 stare → pełne | przyrost RSS MiB stare → pełne |
|---|---:|---:|---:|
| lean | 1,61 → 8,47 | 79 → 360 | 79,8 → 249,5 |
| kompas | 0,41 → 2,87 | 64 → 64 | 88,1 → 87,0 |

Pamięć procesu obejmuje również biblioteki i inne cache, nie jest wyłącznie wielkością danego cache. Ograniczone LRU mają odpowiednio maks. 360 i 64 wpisy: brak nieograniczonego wzrostu liczby wpisów w 600 klatkach, lecz wysoki RSS lean i limit liczby zamiast bajtów pozostają ryzykiem, szczególnie przy wielu workerach/większych widgetach. Bez kwantyzacji i bez spekulacyjnego zmniejszania cache.

Pełny HUD 300 klatek, 2 workery, diagnostyczny `TELEM_CPU_DIAG_NULL_SINK=1`: stare → pełne klucze **19,8 → 18,4 FPS** na liczniku 300 klatek, odpowiednio szczyt sum RSS workerów 986,4 → 977,5 MiB. Jedna para, bez enkodera; ~7% różnicy nie jest oszacowaniem pełnego eksportu ani dowodem powtarzalnej regresji. Null sink nie tworzy MP4 i oczekiwanie displaymatrix kończy się błędem; służył tylko do pomiaru producer HUD.

P0.9, pełne eksporty 150 klatek bez hashów diagnostycznych, naprzemiennie plik harnessu przed/po zmianie: FPS przed **5,58 / 5,63**, po **5,59 / 4,35**; steady przed 6,31 / 6,56, po 6,52 / 4,97. Szczyt system RAM przed 13,80 / 13,41 GiB, po 13,43 / 13,39 GiB; FFmpeg RSS ok. 3,0 GiB. Ten spadek pojedynczego przebiegu jest niewyjaśniony; konfiguracja eksportu bez Golden nie zmieniła się, a warunki CPU dryfują. FPS bez regresji NOT PROVEN. Pełnych wielominutowych eksportów nie wykonywano.

## Decyzja i ograniczenia

Lokalna poprawka harnessu działa dla badanych warunków, ale dwa starsze testy Golden FAIL, oryginalny materiał P0.4 i sprzęt AMD/NVIDIA niedostępne, a brak regresji FPS nieudowodniony. Nie commitowano ani nie wysłano P0.9. Trzeba zapewnić poprawną kanoniczną parę i oryginalne wzorce, powtórzyć brakujące porównania i bardziej stabilne próby wydajności przed publikacją. Powiadomienie MalcerzPOP: wysłane przez curl.exe, id `18rGJeyuiIG3`.
