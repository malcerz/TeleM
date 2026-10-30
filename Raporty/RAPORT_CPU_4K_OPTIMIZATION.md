# SportCamHUD — diagnostyka CPU 4K (29.10.2026)

## Stan: NIEUKOŃCZONE

Nie wdrożono zmian produkcyjnych. Poniższy pomiar ujawnił problemy poprawności; brak danych uzasadniających dobór konfiguracji lub ocenę jakości. Nie uznawać krótkiego eksportu za poprawny wynik końcowy ani za benchmark akceptacyjny.

## Warunki i materiał

Ryzen 7 7730U, 8 rdzeni / 16 wątków logicznych, 29 957 386 240 B RAM. Repozytorium `C:\_DEV\SportCamHUD`, HEAD `1601497`, gałąź `intel-60fps-preview`; istniejące zmiany użytkownika zachowano. `streaming.py` i `command_builder.py` były już zmodyfikowane. Zgodnie z późniejszym wskazaniem użytkownika: `D:\GoPro\GX010370.MP4` + `D:\GoPro\2026-10-13_15-02-49.fit`. Jest to para wskazana przez użytkownika, inna niż podstawowa para w BENCHMARKS.md. Źródło: 3840×2160 HEVC Main10, BT.2020 HLG, displaymatrix -180°, audio AAC.

Adapter istniejącego `tools/nvidia_short_real_export.py` uruchamia kontroler GUI z `encoder=cpu`, 45 klatek od początku, rozdzielczość źródła, 40M, 15 workerów; adapter w katalogu diagnostycznym. Użyto aktywnego layoutu kontrolera; nie potwierdzono identyczności z `def_layout.json`, co ogranicza porównywalność. Log, JSON i plik MP4 zachowano w `Raporty/CPU_4K_DIAGNOSTICS_20261029/user_baseline/` i `user_baseline.log`.

## Pomiary przed / po

45 klatek, 11,42 s od żądania renderu do sygnału zakończenia: **3,94 FPS**, w tym finalizacja, bez przygotowania projektu. GUI pokazuje 15,0 FPS przy podaniu ostatniej klatki; to nie jest FPS całego eksportu. Wideo trwa 1,5015 s, audio 172,6933 s. Plik ma błąd długości audio w tym ograniczonym klatkami teście, mimo że walidator oznaczył go jako valid. Nie ustalono, czy błąd występuje również w normalnym eksporcie całego zakresu. FPS po: **NIE ZMIERZONO**, brak zmian. Nie jest to w pełni poprawny eksport akceptacyjny.

Osobne czasy etapów dekodowania, Pillow, skalowania/obrotu, transportu RGBA, overlay, kodowania, live mux i finalizacji: **NIE ZMIERZONO** w reprezentatywnym izolowanym pomiarze. Log podaje `ffmpeg_write` średnio 54,28 ms i p95 153,96 ms (45 zapisów), lecz obejmuje oczekiwanie na odbiorcę i nie rozdziela kosztu transportu od pozostałych etapów. Oczekiwanie na wyjście FFmpeg po zamknięciu wejścia wyniosło 4,55 s, co obejmuje opróżnianie enkodera i mux, a nie wyłącznie zapis metadanych. Pomiary `stage_*.log` wykonywano równolegle z innym eksportem; nie nadają się do rozbicia kosztów.

## Rotacja P0 — potwierdzona, nienaprawiona

Wejście ma macierz -180°, wyjście również -180°. CPU używa `-noautorotate` dla niezerowej rotacji kontenera, następnie `vflip,hflip`, a `rotate=0`/`-map_metadata -1` nie usuwa w tym wykonaniu macierzy wyjściowej. Porównanie pierwszych klatek w skali szarości 320×180: surowy wynik koreluje 0,9507 z obróconym surowym wejściem oraz 0,1900 z nieobróconym; wynik dekodowany z autorotacją koreluje 0,9507 z nieobróconym surowym wejściem. To potwierdza fizyczny obrót plus drugi obrót przy wyświetlaniu. Test odtwarzacza GUI, osobny materiał 0°, pozycja HUD i poprawka: **NIE WYKONANO**. Docelowa optymalizacja z zachowaniem surowych pikseli wymaga obrócenia i umieszczenia HUD w przestrzeni surowego obrazu oraz sprawdzenia macierzy MP4 i wszystkich wariantów geometrii; sama zmiana flagi metadanych nie wystarczy.

## x265, jakość i HDR

Oddzielny diagnostyczny test syntetyczny `c:\tools\ffmpeg.exe`, 4K `testsrc2`, 12 klatek, CRF 24 i `-b:v 20M`, bez HUD i audio: log x265 4.3+66 podaje `Rate Control: CRF-24.0`, pulę 16 wątków, 4 frame threads, WPP 34 wiersze, SIMD MMX2, SSE2Fast, LZCNT, SSSE3, SSE4.2, AVX, FMA3, BMI2, AVX2. Wyniki wyłącznie enkodera: medium 11,66 FPS/28,99 Mb/s; fast 13,27/30,54; faster 14,25/30,35; veryfast 14,93/30,41. Próby za krótkie, bez normalizacji bitrate i bez pomiaru jakości; nie uzasadniają wyboru presetu ani wydajności aplikacji. Logi `synthetic_*.log`. FFmpeg dostarczony z aplikacją deklaruje obsługę `yuv420p10le`; rzeczywista konfiguracja x265 aplikacji i użycie rdzeni podczas enkodowania wymagają osobnego pomiaru.

Źródło HLG Main10; wynik CPU `yuvj420p` 8-bit, ale nadal ma tagi BT.2020 HLG. Ustawienie `preserve_hlg` nie zapewnia zachowania 10-bit. Ścieżka CPU wymusza `yuv420p`, a wykrycie 10-bit w `streaming.py` ograniczone jest do NVIDIA. Bezpieczny Main10 wymaga co najmniej 10-bitowej ścieżki filtrowania i overlay (bez pośredniego 8-bit YUV), `yuv420p10le`, profilu Main10, zachowania parametrów transferu/primaries/matrix/range oraz weryfikacji renderowania HUD i odtwarzania HLG na referencyjnym materiale. Nie uznano, że oznaczenia same w sobie dowodzą poprawnej luminancji lub zgodności HDR. 8-bit i 10-bit nie porównano jakościowo.

## Procesy, SHM i RAM

Kod domyślnie przy braku wartości korzysta z `cpu_count()-1` dla CPU i alokuje po dwa sloty SHM na worker, o rozmiarze `stream_w × stream_h × 4` każdy; aktywna wartość przekazywana przez GUI może to nadpisać. Przy 15 workerach teoretycznie do 30 slotów, czyli do 949 MiB przy pełnym 3840×2160 RGBA albo 422 MiB przy 2560×1440; rzeczywista wielkość zależy od stream/ROI, nie została zmierzona. Podczas jednego eksportu obserwowano proces FFmpeg ~1,26 GiB working set oraz wiele procesów Python ~165–325 MiB każdy; jest to pojedynczy odczyt, a suma working set może podwójnie liczyć współdzielone strony. Nie jest to peak private memory ani rzeczywisty rozmiar SHM.

Próba z 2 workerami dla wcześniejszej pary kanonicznej zakończyła się przekroczeniem limitu 10 s zamknięcia FFmpeg i wymuszonym zakończeniem, przy jednoczesnym dodatkowym obciążeniu testami; wydajność i optimum workerów/slotów **NIE USTALONO**. Testy 4 i 8 workerów nie zostały wykonane. Statyczne buforowanie, aktualizacje części HUD, ROI, kopie i zgodność Golden HUD wymagają profilowania i porównania pikseli. Nie dodano DLL.

## Zmienione pliki i dalsza walidacja

Zmian produkcyjnych brak; dodano niniejszy raport i artefakty diagnostyczne w `Raporty/CPU_4K_DIAGNOSTICS_20261029/`. Nie zmieniano backendów AMD, Intel ani NVIDIA. Nie wykonano porównania Golden HUD, prób 0°, weryfikacji FIT/GPX/GPMF ani regresji backendów. Aby zakończyć zadanie, należy kolejno uzyskać poprawne krótkie eksporty z wyrównanym audio, wykonać izolowane powtórzenia z kontrolą zasobów i jakości, wdrożyć oraz sprawdzić poprawkę rotacji i Main10, a następnie porównać FPS przed/po na tej samej parze i układzie.
