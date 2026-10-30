# SportCamHUD — CPU P0: poprawność rotacji, Main10 HLG i audio

## Status: CZĘŚCIOWO — akceptacja niezaliczona

Wprowadzono poprawki CPU i wykonano krótkie testy na Ryzen 7 7730U. Wyniki wskazują poprawę trzech błędów, ale nie wykonano pełnej akceptacji na kanonicznym harnessie eksportu CPU, porównania Golden HUD i oceny na monitorze/odtwarzaczu HDR. Nie deklarujemy PASS ani baseline wydajności. Nie uruchamiano benchmarków po niepełnej akceptacji. Istniejące niezacommitowane zmiany zachowano. Backendów AMD AMF, Intel QSV i NVIDIA Native nie zmieniano; shared-memory zmieniono przez opcjonalny offset równy 0 dla pozostałych ścieżek, jednak brak ich pełnych smoke testów.

## Materiał i metoda

`D:\GoPro\GX010370.MP4` + `D:\GoPro\2026-10-13_15-02-49.fit`, para jawnie wskazana przez użytkownika. Źródło 3840×2160, 30000/1001, HEVC Main 10, `yuv420p10le`, BT.2020 / HLG / BT.2020nc, range pc, displaymatrix -180°, AAC. Wyjściowy stan HEAD 1601497, gałąź intel-60fps-preview, istniejące liczne zmiany w drzewie, w tym w edytowanych plikach.

Użyto adaptacji istniejącego `tools/nvidia_short_real_export.py`, wywołującej ten sam kontroler i ścieżkę eksportu GUI z `encoder=cpu`, 15 workerami, pełnym aktywnym HUD i bitrate 40M. Adapter i logi znajdują się w `Raporty/CPU_4K_DIAGNOSTICS_20261029/`. Ten adapter nie stanowi osobnego kanonicznego harnessu CPU; skrypty `--test-amd-export` i `--test-intel-export` wybierają na sztywno swoje backendy. Dlatego wymóg uruchomienia kanonicznego harnessu CPU: NIE POTWIERDZONO. Powtórzenia prowadzono sekwencyjnie. Aktywny layout kontrolera nie został dowiedziony jako Golden CPU.

## 1. Rotacja

Przed: wejście `-noautorotate`, filtr `vflip,hflip` fizycznie odwracał wideo, ale FFmpeg zachowywał źródłową macierz -180°. Powstawał drugi obrót w odtwarzaczu.

Po: dla CPU ze źródłową macierzą 180° baza pozostaje w orientacji surowych pikseli; istniejący renderer obraca HUD o 180° w pełnym canvas, zaś gotowy MP4 otrzymuje zweryfikowaną macierz 180° przez istniejący in-place writer tkhd. Bez fizycznego odwracania pełnej klatki 4K. Inne obroty nie były przedmiotem akceptacji tej zmiany.

Dla pierwszej klatki 180° korelacja wynik/źródło surowe 0,9352, z odwróconym źródłem 0,1835. Po autorotacji FFmpeg obraz koreluje 0,9352 z obróconym źródłem. Wizualnie na `p0_smoke/display.png` HUD, mapa i wykresy mają właściwą orientację. Nie jest to porównanie pixel-perfect z Golden HUD ani test osobnego odtwarzacza.

Kontrola 0°: wykonano 6-sekundową kopię testową tego samego źródła z macierzą 0° (plik testowy, poza eksportem aplikacji) i eksport 45 klatek. Wejście i wyjście bez niezerowej macierzy; surowa i wyświetlana klatka korelują ze źródłem 0,9686. Eksport do tego fixture nie potwierdza pełnej telemetrii oryginalnego źródła.

## 2. Main10 HLG

Przed: CPU wymuszał `yuv420p` mimo HLG, ffprobe wykazywał `yuvj420p` 8-bit przy tagach HLG.

Po: `probe_video_color` wykrywa HLG, sprawdza głębię i BT.2020, a dla sekwencji zgodność HLG/range. FFmpeg `overlay` ustawiono na `format=yuv420p10`; x265 dostaje `-profile:v main10 -pix_fmt yuv420p10le` i BT.2020 / `arib-std-b67` / BT.2020nc oraz zakres wejściowy. Syntetyczna próba negocjacji FFmpeg na rzeczywistym źródle (`p0_filter_probe.log`) pokazuje bazę `yuv420p10le`, konwersję samego RGBA HUD na `yuva420p10le`, wynik `showinfo` `yuv420p10le`, range pc i BT.2020 HLG. Na dekodowanym obszarze wyniku 150 klatek stwierdzono 891 różnych wartości luminancji i obecność wszystkich dwóch najmłodszych bitów (liczności 16307, 16174, 16607, 16448). To dowód 10-bitowej reprezentacji i braku oczywistego 8-bitowego kwantowania w tym obszarze, nie dowód poprawnej luminancji HDR na całym obrazie. Monitor HDR, kolory HUD względem Golden i pomiar HLG w całym torze: NIE TESTOWANO.

`ffprobe` wyniku 150 klatek: HEVC Main 10, `yuv420p10le`, pc, BT.2020nc / BT.2020 / arib-std-b67, 3840×2160, 150 klatek, 5,005 s, displaymatrix -180°.

## 3. Audio, start i walidacja

Przyczyna: `-frames:v` ograniczał wyłącznie wideo, podczas gdy audio kopiowane było dalej do końca wejścia. Poprzedni walidator sprawdzał długość kontenera i obecność wideo, nie czas każdego strumienia.

CPU z limitem klatek otrzymuje również wyjściowe `-t` wyliczone z liczby klatek i FPS. Audio jest mapowane z wejścia i kopiowane w tym samym procesie live mux; brak cache i wtórnego remuxu eksportu. Dla `start_frame` dodano obsługę CPU pojedynczego źródła bez cięć przy Full HUD: input seek, rekord HUD z właściwego indeksu oraz kolejność lokalnych klatek; pozostałe kombinacje zgłaszają błąd zamiast cichej desynchronizacji. Synchronizacja GPMF zakresu jest przekazywana do istniejącego planu, lecz nie testowano zachowania GPMF w wyjściu.

Walidator CPU porównuje początek i koniec audio/wideo z tolerancją minimum 50 ms (lub 2 pakiety AAC przy niższej częstotliwości). Brak wymaganych czasów oznacza niepowodzenie walidacji. Inne backendy nie korzystają z nowej kontroli.

| Próba | Wideo | Audio | Wynik |
|---|---:|---:|---|
| Przed, 45 klatek | 1,501500 s | 172,693333 s | błędne |
| Po, 45 klatek od początku | 1,501500 s | 1,493333 s | różnica 8,17 ms |
| Po, 150 klatek od początku | 5,005000 s | 4,992000 s | różnica 13 ms |
| Po, klatka 900, 45 klatek | 1,501500 s | 1,500667 s | różnica 0,83 ms |
| Cały 6-sekundowy fixture 0°, bez limitu klatek | 6,006000 s / 180 klatek | 6,016000 s | różnica 10 ms |

Próba od klatki 900: korelacja surowej klatki ze źródłem od 30,03 s 0,9607; porównanie pierwszej sekundy zdekodowanego audio wskazało korelację 1,0 i przesunięcie 0 ms. Nie sprawdzono synchronizacji w dalszych punktach ani całego oryginalnego 182-sekundowego filmu. Kontrolny cały fixture nie zastępuje testu pełnego oryginalnego pliku.

## Testy i ograniczenia

`tests/test_cpu_p0_correctness.py` + `tests/test_nvidia_displaymatrix_fast.py`: 9 passed. W szerszym `tests/test_video_helpers.py` + `tests/test_nvidia_displaymatrix_fast.py`: 36 passed, 2 failed: mock wykrywania GPU wybiera nv zamiast oczekiwanego amd oraz test oczekuje nv12 w ścieżce Intel, która zwraca p010le. Nie ustalono ich przyczyny i nie uznano ich za przejście regresji.

Brak: kanoniczny harness CPU, Golden HUD i pixel parity, osobny odtwarzacz metadanych, display HDR, pomiar precyzji po wszystkich etapach produkcyjnego filtra, test 90°/270°, pełne sprawdzenie warstw FIT/GPX/GPMF, smoke AMD/Intel/NVIDIA, niezależne rozbicie Pillow/transport/overlay/x265/finalizacja. Wynik 150 klatek z adaptera to 38,95 s wall, ale zgodnie z wymaganiem nie stanowi on baseline wydajności przed pełną akceptacją. Odrębny FPS, steady state i time-to-first-frame nie zostały ustalone. Finalizacja po zamknięciu wejścia FFmpeg trwała 5,292 s i obejmuje opróżnianie x265 oraz mux.

## Pliki zmienione w tym etapie

- `src/ffmpeg/command_builder.py`: CPU 180° w metadanych, overlay Main10, encoder Main10 i limit czasu CPU.
- `src/ffmpeg/streaming.py`: wykrycie HLG, orientacja HUD, weryfikacja macierzy, limit czasu i pojedynczy start CPU.
- `src/ffmpeg/shared_memory.py`: opcjonalny offset indeksu źródła z zachowaniem kolejności wynikowej.
- `src/ffmpeg/render_errors.py`: opcjonalna kontrola długości i początków strumieni.
- `src/gui/qt/_mixins/render_mixin.py`: włączenie walidacji tylko CPU i przekazanie zakresu CPU.
- `tests/test_cpu_p0_correctness.py`; niniejszy raport; logi, adaptery i krótkie próbki w `Raporty/CPU_4K_DIAGNOSTICS_20261029/`.

Te pliki produkcyjne zawierały także istniejące zmiany użytkownika; statystyka pełnego `git diff` nie jest statystyką wyłącznie tej pracy.

Powiadomienie ntfy: wysyłka zostanie odnotowana poniżej.

Powiadomienie ntfy MalcerzPOP: wysłane, identyfikator 1O1E3nD5Avtl (status CZĘŚCIOWO).
