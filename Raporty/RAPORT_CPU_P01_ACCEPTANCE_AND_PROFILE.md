# SportCamHUD — CPU P0.1: walidacja i przygotowanie benchmarku

## Status: CZĘŚCIOWO — pełna akceptacja NIEZALICZONA

Harness CPU istnieje i przeprowadził krótkie eksporty z automatycznym sprawdzeniem strumieni. Rotacja pikseli 0°/180°, 10-bitowe formaty w rzeczywistym filtergraph oraz krótkie audio są potwierdzone w zakresie opisanym poniżej. Pełna zgodność Golden HUD, wszystkich wskaźników i kolorów HUD w HLG nie została wykazana; nie przeprowadzono testu na fizycznym monitorze HDR. Zgodnie z warunkiem użytkownika nie rozpoczęto benchmarku etapów ani nie uznano krótkich prób poprawności za wiarygodny baseline wydajności.

Repozytorium `C:\_DEV\SportCamHUD`, HEAD 1601497, gałąź `intel-60fps-preview`; istniały liczne niezacommitowane zmiany, również w plikach edytowanych w tym etapie. Zachowano je. Materiał wskazany przez użytkownika: `D:\GoPro\GX010370.MP4` i `D:\GoPro\2026-10-13_15-02-49.fit`. Rozdzielczość 3840×2160, 30000/1001; wspólny jawny layout `C:\_DEV\SportCamHUD\def_layout.json`, pełny HUD. Przebiegi były sekwencyjne.

## Harness CPU

Rozszerzono istniejący harness GUI `SportCamHUD.py --test-intel-export` o wejście `--test-cpu-export`, z tym samym mechanizmem ładowania projektu, przygotowania, kliknięcia Start, sygnałów i walidacji wyniku. Tryb CPU wymaga `--frames > 0`, `--start-frame >= 0` i trybu direct; liczba klatek jest podawana zarówno w opcjach żądania renderu, jak i przez istniejący limit harnessu. Gotowy MP4 jest sprawdzany względem dokładnej liczby klatek, obecności audio, poprawności czasów A/V oraz zgodności formatu i zakresu HLG wejścia i wyjścia. Result JSON zawiera czas od rozpoczęcia ładowania do kliknięcia, wall-clock FPS od kliknięcia, czas do pierwszego przekazania HUD do pipe, FPS środkowego okna 10–90% zapisów do pipe, czas opróżnienia enkodera/finalizacji i ślad negocjacji FFmpeg. FPS pipe nie jest FPS enkodera ani samodzielnym dowodem steady state enkodowania. Trzeba uwzględnić przygotowanie przed kliknięciem. Domyślnych workerów i presetu nie zmieniano.

Przykład: `python SportCamHUD.py --test-cpu-export --mode direct --video D:\GoPro\GX010370.MP4 --fit D:\GoPro\2026-10-13_15-02-49.fit --layout C:\_DEV\SportCamHUD\def_layout.json --start-frame 900 --frames 45 --wait-prepared --output <nowy-plik.mp4> --result-json <nowy-plik.json>`.

| Kontrola | Status | Dowód i granica |
|---|---|---|
| Harness, start 0 / max 45 | PASS | `start/result.json`: success, 45 klatek, wideo 1,501500 s, audio 1,493333 s. |
| Harness, start 900 / max 45 | PASS | `middle/result.json`: success, 45 klatek, wideo 1,501500 s, audio 1,500667 s. |
| Harness po dodaniu weryfikacji koloru i śladu | PASS | `final_check/result.json`: 30/30 klatek, A/V i kolor zaakceptowane; dokładny limit wyklucza pełny eksport w tych próbach. |
| Oddzielne źródło 0° | PASS CZĘŚCIOWY | `rotation0/result.json`: 45 klatek; źródło to wcześniej przygotowany 6-sekundowy fixture bez GPMF, więc nie jest to test pełnej telemetrii. |
| Golden HUD / wszystkie pozycje i kolory | NIEUDOWODNIONE | `tests/golden_hud` zawiera wzorzec i telemetrię z innego snapshotu; nie porównano ich jako identycznego stanu z obecną parą. `tests/test_golden_parity_etap4.py` wskazuje inną, w BENCHMARKS.md oznaczoną jako niepoprawna, parę VIDEO/FIT i nie użyto jej jako dowodu. |
| Mapa / wykresy | CZĘŚCIOWO | Na kontrolnej klatce widoczne mapa, trasa oraz wykresy kadencji i tętna; poprawność wartości i wszystkich stanów nie jest potwierdzona. |
| Fizyczny monitor HDR / odtwarzacz HDR | NIE TESTOWANO | Przygotowano PNG kontrolne z jawnym tone mappingiem HLG do SDR; nie są oceną wyglądu na monitorze HDR. |
| FIT / GPX / GPMF, wszystkie warstwy | NIEUDOWODNIONE | Wskazany FIT i źródło załadowano, lecz brak kompletnej weryfikacji wskaźników oraz odczytu dołączonego GPMF; GPX nie był częścią wejścia. |
| Profil etapów i CPU/RAM | NIE WYKONANO | Nie osiągnięto pełnej walidacji wizualnej. Nie ma pomiaru Pillow, transportu, overlay, x265 i oczekiwań, który pozwalałby wskazać dominujące wąskie gardło. |

## Orientacja 0° / 180°

Porównano pierwszą klatkę wyjścia z odpowiadającą jej klatką źródła, zmniejszając obraz do 320×180 i używając korelacji luminancji; nakładka i kompresja ograniczają zgodność. Pełne dane: `controls/orientation.json`.

| Test | Surowe: korelacja z surowym źródłem | Wyświetlane z autorotacją: korelacja z obróconym źródłem | Wniosek |
|---|---:|---:|---|
| 180°, początek | 0,9510 | 0,9510 | surowe piksele zachowane, macierz obraca obraz raz |
| 180°, od klatki 900 | 0,96073 | 0,96065 | właściwy fragment i orientacja |
| 0°, początek | 0,96860 | nie dotyczy | surowe i wyświetlane mają tę samą orientację; wynik bez obrotu |

Kontrola korzysta z autorotacji FFmpeg, nie z osobnego fizycznego odtwarzacza. Widoczny HUD w `controls/start_display_tonemapped.png`, `middle_display_tonemapped.png`, `rotation0_display_tonemapped.png` jest czytelny i obrócony prawidłowo; nie stanowi to dokładnego porównania wszystkich bbox względem Golden.

## Main10, HLG i audio

Na rzeczywistym torze CPU (`final_check/result.json`, `cpu_stream_metrics.ffmpeg_trace`) dekoder podał `yuv420p10le`, BT.2020nc, range pc. Jedyny widoczny autoscale przekształca RGBA HUD do `yuva420p10le`; overlay otrzymuje 10-bitową bazę i 10-bitowy HUD. x265 potwierdził build 10bit, Main 10 oraz 16-wątkową pulę, a ffprobe wyniku: `yuv420p10le`, BT.2020, `arib-std-b67`, BT.2020nc, pc i 180°. Test P0 wykazał także 891 różnych 10-bitowych wartości luminancji w kontrolnym obszarze zdekodowanej klatki. To istotny dowód precyzji, lecz nie dowód prawidłowego odwzorowania barw 8-bitowego HUD w przestrzeni HLG. Obraz PNG przekształcono Hable do BT.709 wyłącznie dla kontroli, nie w ścieżce eksportu.

Krótki eksport nie tworzy cache audio ani drugiego remuxu: używa oryginalnego audio AAC i jednego procesu FFmpeg z `-c:a copy`; różnice długości 8,17 ms od początku oraz 0,83 ms od środka mieszczą się w granicach pakietów AAC. W etapie P0 korelacja pierwszej sekundy zdekodowanego audio środkowego fragmentu wyniosła 1,0 przy przesunięciu 0 ms; tutaj nie przeprowadzono niezależnej analizy całej długości środkowego fragmentu. Pełny oryginalny 182-sekundowy eksport nie był uruchamiany zgodnie z zakazem długiego eksportu.

## Regresje testów

Obie porażki z P0 były przestarzałymi oczekiwaniami testów:

1. `detect_best_encoder()` deleguje do `resolve_auto_backend()` i `query_backend_capabilities()`. Wcześniejszy mock dotyczył wyłącznie dawnej ścieżki `_test_encoder`, a nie aktualnego źródła danych, więc test nie izolował dostępnych GPU. Zaktualizowany test wymusza snapshot dostępności i sprawdza zarówno AMD bez NVIDIA, jak i priorytet NVIDIA przy obu dostępnych.
2. Domyślny kodek Intel `hevc` ma kontrakt Main10 / P010LE; `hevc_sdr` i H.264 korzystają z NV12. Oczekiwanie NV12 dla domyślnego HEVC było nieaktualne. Produkcyjnych backendów nie zmieniano.

`python -m pytest -q tests/test_video_helpers.py tests/test_cpu_p0_correctness.py tests/test_nvidia_displaymatrix_fast.py`: **40 passed**. Nie wykonywano sprzętowych smoke testów AMD, Intel ani NVIDIA.

## Obserwacje diagnostyczne, nie baseline

Finalna próba poprawności 30 klatek: 9,94 s od kliknięcia do zakończenia, 3,02 FPS; 7,05 s od początku obsługi projektu do kliknięcia; 2,01 s od początku streamingu do pierwszego zapisu klatki do pipe; centralne okno zapisów do pipe 23,25 FPS (klatki 4–27); opróżnienie writer/FFmpeg i finalizacja 6,93 s, w tym oczekiwanie na writer i enkoder; zapis macierzy 0,0028 s. Log x265: 4,33 FPS dla tych 30 klatek. Te wartości są z krótkiej próby poprawności o dużym udziale rozruchu i nie rozdzielają nakładających się etapów. Nie należy traktować ich jako porównywalnego benchmarku ani dodawać ich do siebie. Ślad pokazuje 16 wątków x265, ale nie mierzy wykorzystania CPU ani private/peak RAM.

Po zamknięciu zgodności Golden i HLG: uruchomić ten sam harness na dłuższym krótkim fragmencie oraz wykorzystać kontrolowany audyt per-frame Pillow/writer i niezależne ablac­­je FFmpeg dla overlay/decode/x265; monitorować CPU oraz private/working-set procesu i SHM. Najpierw rozdzielić czas renderowania HUD, oczekiwanie na pipe i enkoder, następnie dopiero wybierać optymalizacje. Bez takich danych kolejność konkretnych optymalizacji nie jest udowodniona.

## Zmienione pliki

- `src/gui/qt/application.py`: tryb istniejącego harnessu CPU, ograniczenia zakresu, walidacja i JSON.
- `src/ffmpeg/streaming.py`: ograniczona do CPU/harnessu instrumentacja czasów i śladu FFmpeg; bez zmian algorytmu P0.
- `tests/test_video_helpers.py`: aktualny mock kontraktu AUTO i oczekiwanie P010LE.
- `Raporty/RAPORT_CPU_P01_ACCEPTANCE_AND_PROFILE.md` oraz `Raporty/CPU_P01_ACCEPTANCE/` z logami, wynikami i klatkami.

Status powiadomienia ntfy zostanie dopisany po próbie wysłania.

Powiadomienie ntfy MalcerzPOP wysłane: TbzSs8jE3QcP, status CZĘŚCIOWO.
