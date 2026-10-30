# SportCamHUD — CPU P0.7: lookahead

## Decyzja: nie wdrażać automatycznego doboru; etap częściowo wykonany

P0.6 dał na Ryzen 7 7730U 11,08 → 11,87 FPS (+7,2%) i zgodność bitową w badanej próbce; nie odrzucamy go z powodu progu 10%. W P0.7 Ryzen nie był dostępny. Na dostępnym Intel Core i7-1265U (12 wątków logicznych) krótkie testy nie wykazały stabilnego zysku `lookahead-threads=4`; ponadto powtórzenie bazy dało inny zakodowany strumień. Automatyczna reguła na podstawie liczby wątków i profilu jest nieuzasadniona. Również wyjątek dla Ryzena wymaga potwierdzenia na kilku fragmentach na tej maszynie. `TELEM_CPU_X265_PARAMS` pozostaje jawnym eksperymentalnym ustawieniem, stosowanym do wszystkich profili; żadna zmiana produkcyjna nie została wykonana.

## Git i stan początkowy

Początkowy HEAD gałęzi `cpu-optimization` to `f809e2577908f91f7683ca6197d27c21bc521436`, potwierdzony przez `git ls-remote origin`: raport i commit P0.6 zostały opublikowane. Zastano 778 usunięć, 107 modyfikacji i 338 pozycji nieśledzonych; indeks był pusty. Zmiany pozostawiono. Pierwszy commit P0.7 `edacb266a89e3a4e5b0b1457bb8d5238764a4371` udokumentował brak pary; po wskazaniu przez użytkownika poniższej pary wykonano pomiary. W P0.7 zmieniono wyłącznie ten raport i dane pomiarowe w `Raporty/CPU_P07_LOOKAHEAD/`. Nie zmieniono kodu GPU ani telemetrii.

## Metoda

Użytkownik wskazał parę `C:\GoPro\GX010378.MP4` + `C:\GoPro\2026-10-15_15-03-50.fit`. Harness `--test-cpu-export`, przez wrapper P0.2 z podmienionymi tylko ścieżkami wejścia, `def_layout.json`, 3840×2160, fast/ultrafast, ABR 16M, 60 klatek, start 0, 900 i 1800. Przy 0 i 900 testowano domyślne i 2/3/4/5; przy 1800 domyślne i 4; dodatkowo powtórzono domyślne i 4 na 0. Kolejność 0: baza, 2, 3, 4, 5, później powtórzenia; 900: 5, 4, 3, 2, baza. Krótkie testy pojedyncze, bez kontrolowanego schładzania; start/finalizacja są znaczną częścią czasu. Nie jest to miarodajny szacunek długiego eksportu ani dowód powtarzalności. Żadnego długiego eksportu ani pełnego sweepu nie wykonywano. `summaries.json` zawiera próbki zagregowane przez wrapper; pliki MP4 i pełne logi pozostają lokalnie w `C:\GoPro\TO\p07`.

## Wyniki Intel

| start | parametr | FPS eksportu | bitrate x265 kb/s | CPU systemu % | szczyt RAM systemu GB | peak RSS ffmpeg MB |
|---:|---|---:|---:|---:|---:|---:|
| 0 | default | 6,21 | 14994,43 | 54,6 | 14,57 | 2964,5 |
| 0 | 2 | 4,83 | 14996,12 | 66,1 | 13,96 | 2968,0 |
| 0 | 3 | 5,07 | 14988,59 | 62,8 | 13,98 | 2967,5 |
| 0 | 4 | 4,95 | 14993,74 | 60,9 | 14,00 | 2959,2 |
| 0 | 5 | 4,99 | 14993,92 | 60,0 | 13,99 | 2950,2 |
| 900 | default | 4,28 | 17836,36 | 67,0 | 14,11 | 2991,3 |
| 900 | 2 | 4,37 | 17813,43 | 67,7 | 14,00 | 2952,5 |
| 900 | 3 | 4,35 | 17825,59 | 68,4 | 14,02 | 2970,0 |
| 900 | 4 | 4,24 | 17848,40 | 67,0 | 14,10 | 2960,9 |
| 900 | 5 | 4,14 | 17798,01 | 65,5 | 14,08 | 3136,2 |
| 1800 | default | 4,27 | 18069,68 | 69,3 | 14,03 | — |
| 1800 | 4 | 4,30 | 18068,10 | 67,1 | 13,69 | — |
| 0 | default powtórzenie | 4,41 | 14990,40 | 67,0 | 13,95 | — |
| 0 | 4 powtórzenie | 4,83 | 14992,44 | 62,0 | 13,96 | — |

CPU to średnia systemowa w oknie 25–90% całego procesu, obejmującym również przygotowanie; nie jest to precyzyjny pomiar steady-state. Dane RSS pozostałych przebiegów są w JSON. Duża różnica 6,21 vs 4,41 FPS powtórzonej bazy wskazuje na silny dryf warunków; nie należy obliczać wiarygodnego zysku z tych pojedynczych par. Przed/po dla trzech fragmentów: 6,21→4,95 (powtórzenie 4,41→4,83), 4,28→4,24, 4,27→4,30 FPS.

## Poprawność

- Wszystkie 14 przebiegów zgłosiły success, 60/60 klatek, poprawny MP4, audio i kolor w walidatorze. ffprobe na `s0_lat4` potwierdził HEVC Main 10, yuv420p10le, BT.2020, arib-std-b67 oraz AAC. Wejście i wynik mają display matrix −180°. Wizualna kontrola orientacji i wariant 0°: NOT TESTED.
- Hashe SHA-256 skopiowanego strumienia wideo są różne: baza 0 `d20e5cc10e4a30301bb3dbb729ddaddb1cd0714bad203a89468fcbdf4938c362`, jej powtórzenie `6eddffb9bd2cc6940ae2e2a6db7d387aef5910ffffed98c479a73b4602e81702`, lat4 `fb1c7170af491e57b636825681e4987b027af88b0c058f5d1df345b73e372e8a`. Pozostałe warianty także różne od bazy. Zgodność bitowa NOT PROVEN; ponieważ powtórzenia bazy też różne, przyczyny nie ustalono. Nie twierdzimy, że sam lookahead powoduje różnicę.
- Audio w wyniku obecne i timing walidatora prawidłowy. Brak niezależnego potwierdzenia całego procesu live mux i niewystępowania wyodrębnienia: NOT PROVEN; kod nie był zmieniany.
- `python -m pytest -q tests/test_cpu_golden_p04.py tests/test_cpu_p0_correctness.py tests/test_cpu_p03_presets.py`: 23 passed, 1 skipped. Integralność zamrożonego Golden HUD i jego obrót PASS; rzeczywisty rerun Golden pominięty z powodu niedostępnego oryginalnego źródła GX010370, więc porównanie HUD eksportu P0.7 z golden NOT TESTED.
- Profile Szybki, Zbalansowany, Jakość i mechanizmy jakości x265 bez zmian. Pozostałe profile w P0.7 NOT TESTED. Ryzen P0.7 NOT TESTED, Intel i7-1265U przetestowany tylko w opisanym zakresie; inne procesory NOT TESTED.

## Dalsze kroki

Na Ryzen powtórzyć przeplatane krótkie pary na kilku fragmentach i ustalić źródło niedeterministyczności przed porównaniem bitowym. Na Intel powtórzyć pary w stabilnych warunkach, zebrać bezpośredni dowód ścieżki audio i wizualną orientację oraz prawdziwy rerun Golden HUD. Dopiero wtedy rozważyć ograniczoną regułę. P0.7 pozostaje CZĘŚCIOWO / brak wdrożenia.
