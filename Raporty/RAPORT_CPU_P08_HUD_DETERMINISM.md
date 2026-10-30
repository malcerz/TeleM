# SportCamHUD CPU P0.8 — deterministyczność HUD

## Wynik: poprawka zastosowana; ograniczenia walidacji

Przyczyną zależności HUD od poprzednich klatek były dwa procesowe cache: kompas i grafika przechyłu używały klucza kąta zaokrąglonego do 0,1°, choć obraz obliczany był z pełnej wartości. Pierwsza klatka obsłużona w danym przedziale wypełniała cache i decydowała o obrazie kolejnych klatek. Kolejność i przypisanie klatek do workerów zmieniały zatem wynik. Test dla wartości 20,01 i 20,04 stopnia odtworzył błąd niezależnie w obu wskaźnikach; przed poprawką oba testy zawiodły, po poprawce przechodzą. To nie było zaokrąglenie wartości renderowanej.

Klucze cache zawierają teraz pełny kąt, używany rzeczywiście przez renderer. Nie zmieniono geometrii, wzoru renderowania, danych FIT/GPX/GPMF, liczby workerów, x265, profili ani rate control. Zmienione pliki: `src/indicators/gauge.py`, `src/indicators/lean.py`, `tests/test_cpu_p08_hud_determinism.py`, ten raport i diagnostyka w `Raporty/CPU_P08_HUD_DETERMINISM/`. Dwa pliki rendererów były czyste przed etapem. Są to współdzielone renderery wskaźników; kod backendów AMD, Intel QSV i NVIDIA nie był zmieniany. Testy GPU bridge wykonano, pełne eksporty GPU NOT TESTED.

## Stan początkowy

`cpu-optimization`, HEAD i `origin/cpu-optimization` `db6431bfad1a6c688447f156c13c0ad26122f4b1`. Pusty indeks; zastano 778 usunięć, 107 modyfikacji, 338 pozycji nieśledzonych. Zachowano je. Layout `def_layout.json` był już lokalnie zmieniony i używano go bez modyfikacji. Raport P0.7a i jego diagnostyka zostały przeanalizowane.

## Lokalizacja i przyczyna

Kanoniczny harness `--test-cpu-export`, 4K, start 900, 150 klatek, `C:\GoPro\GX010378.MP4` + `C:\GoPro\2026-10-15_15-03-50.fit`, layout `def_layout.json`, Szybki, 16M, Intel i7-1265U. Diagnostic launcher zapisuje SHA-256 każdego RGBA na wyjściu writer, wybrane zrzuty i rekordy telemetryczne; lokalnie jednoprocesowa ścieżka haszuje wynik renderera bez IPC. Nie zapisano wszystkich pełnych klatek.

Przed poprawką: dwa eksporty z dwoma workerami różniły się w **48/150** hashy, pierwsza różna klatka 9; rekordy identyczne. Dwa z jednym workerem: **0/150**, a jeden vs dwa workery: **62/150**, pierwsza różna klatka 13. Dla tej pierwszej różnej klatki w porównaniu 1/2 workerów zapisano [obraz różnicy](CPU_P08_HUD_DETERMINISM/difference_frame13_1v2.png): 6408 pikseli, kanały R/G/B/A 3493/3493/3493/4862, bbox w orientacji zapisu x=134–300, y=944–1141, max różnica 255. Kształt i położenie wskazują grafikę roweru `lean_indicator`; rekord klatki absolutnej 913 zawiera lean 0,5584833276668945 i compass 101,2624282836914; te same rekordy przekazano workerom w powtórzeniach dwóch workerów. Dokładnych wcześniejszych wpisów cache konkretnego workera nie rejestrowano. W próbce P0.7a klatki 299 [obraz różnicy](CPU_P08_HUD_DETERMINISM/difference_p07a_frame299.png) obejmuje również tarczę `compass`; 19914 pikseli, kanały 9709/9627/9465/16193. Niezależny test kolejności dowodzi konfliktu cache dla obu renderów.

Multiprocessing numeruje zadania i buforuje je do kolejności przed zapisem; po poprawce hashe 1/2 workerów potwierdzają ten sam wynik dla 150 klatek. Rekordy dwuworkerowe w trzech przebiegach były identyczne i ciągłe 900–1049 oraz 1800–1949. W tej próbce mapa i wykresy były włączone i pełne hashe klatek są równe po poprawce. Nie wykazano wpływu czasu systemowego, losowości, wyścigu kafelków czy wykresów; nie dowodzi to ich braku we wszystkich konfiguracjach. Worker Pillow ma procesowy cache; wykazana była właśnie jego zależność od historii. Pozostałe konfiguracje i wszystkie możliwe wskaźniki nie zostały wyczerpane.

## Akceptacja po poprawce

| Fragment | Liczba identycznych eksportów | Różne RGBA między powtórzeniami | Walidacja |
|---|---:|---:|---|
| klatki 900–1049, 2 workery | 3 | 0/150 | wszystkie 150/150, MP4 valid, kolor i audio PASS |
| klatki 1800–1949, 2 workery | 3 | 0/150 | wszystkie 150/150, MP4 valid, kolor i audio PASS |
| 900–1049, 1 vs 2 workery | 1 + 3 | 0/150 | PASS dla próbki |

Wynik bitowy HEVC nie jest warunkiem poprawności HUD. Hashy RGBA, wyniki harnessu i launcher diagnostyczny zapisano w `CPU_P08_HUD_DETERMINISM/`; pełne logi i wybrane surowe klatki są lokalnie `C:\GoPro\TO\p08`. Telemetrii z lokalizacją nie dołączono do repozytorium.

Golden: oryginalny rerun P0.4 na GX010370 NOT TESTED, bo ten materiał i jego FIT nie są dostępne. Test integralności zamrożonego obrazu P0.4 PASS. Dla aktualnego materiału wykonano niezależną kontrolę P0.4: edytor, referencyjny `compose_overlay` i rzeczywisty RGBA z potoku przy klatce 913 są **0 różnych pikseli, max_diff=0, MAE=0** po wyzerowaniu RGB pod zerową alfą; dla 180° zrzut obrócono do orientacji wyświetlania. Dla 0° użyto kopii MP4 remuxowanej z wyzerowaną display matrix, zachowującej wideo/audio/GPMF oraz oryginalny FIT; identyczność edytor/potok również 0 pikseli. `ffprobe` potwierdził 0° bez rotacyjnej matrix oraz 180° z matrix −180°, Main10 yuv420p10le, BT.2020 HLG, AAC. Wideo dla 0° jest kopią testową, nie niezależnym materiałem.

Uwaga o harnessie: zwykły `--golden-dir` robi zrzut edytora w trakcie przełączania eksportu Intel→CPU, przed zakończeniem drugiego przygotowania mapy. Na tym materiale daje 93497 różnych pikseli w mapie zarówno przed, jak i po poprawce, z identycznym polem różnic; inne obszary 0. Diagnostyczny `golden_after_ready.py` odracza zrzut do gotowości CPU, co daje powyższe 0. Nie zmieniono produkcyjnego harnessu. Pełny historyczny Golden oraz wpływ na niezbadane layouty pozostają ryzykiem.

Audio: przechwycone argumenty FFmpeg P0.7a dla tej samej ścieżki `-map 0:a? -c:a copy`, wejście to oryginalny MP4; bez pliku pośredniego. Wyniki po poprawce mają audio i prawidłowy timing. `python -m pytest -q tests/test_cpu_p08_hud_determinism.py tests/test_cpu_golden_p04.py tests/test_cpu_p0_correctness.py tests/test_cpu_p03_presets.py tests/test_lean_parity_5xl.py tests/test_lean_gpu_bridge.py tests/test_compass_and_shadow_outline.py`: **41 passed, 3 skipped**; pominięto m.in. oryginalny rerun Golden.

## Wydajność

W bezpośrednio sąsiadujących próbach 150 klatek, po tym samym lekkim haszowaniu HUD, dawne klucze cache 4,53 / 4,61 FPS eksportu (steady 5,15 / 5,37), nowe klucze 4,57 / 4,54 FPS (steady 5,26 / 5,16). Średnie 4,57 → 4,56 FPS; brak zauważalnego spadku w tej parze. Wcześniejsze po poprawce wyniki 3,09 / 3,12 / 3,11 FPS przy niższym CPU, zanim kontrola osiągnęła 4,53–4,61, pokazują bardzo duży dryf i nie pozwalają wykluczyć regresji w innych warunkach. Kolejność kontroli: dwie stare, potem dwie nowe, bez kontrolowanej temperatury. Krótkie testy i ograniczony cache nie gwarantują braku spadku w innych materiałach/profilach; pełne klucze mogą zmniejszać trafienia cache. Nie zmieniano ustawień zasilania.

## Podsumowanie

Pierwsza przyczyna różnic została odtworzona i poprawiona bez tolerancji pikselowej; powtórzenia na dwóch fragmentach i 1/2 workerów PASS. Aktualny Golden po gotowości 0°/180° PASS. Oryginalny Golden P0.4, inne CPU/backendy i pełna stabilność wydajności NOT TESTED/NOT PROVEN. Ograniczenia należy uwzględnić przy ocenie wdrożenia.
