# SportCamHUD CPU P1.2 — Ryzen 7 7730U, długi eksport i lookahead

## Status: CZĘŚCIOWO

Długi eksport i dziewięć par A/B zakończyły się sukcesem. `lookahead-threads=4` dał wzrost wall FPS w każdej parze (3,84–6,55%), a pliki każdej pary były identyczne bitowo. Nie wdrożono ustawienia produkcyjnego: brak dostępnego pomiaru temperatury, niezależnego potwierdzenia Golden P0.4 oraz długiego eksportu z wariantem B. Wyniki uzasadniają dalszą weryfikację, ale nie deklarujemy pełnej akceptacji P1.2.

## Git i środowisko

Windows 11, Ryzen 7 7730U 8C/16T, ok. 30 GB RAM. Gałąź `cpu-optimization`, HEAD przed zadaniem `bcafc5ebd4d1f6d03eae92450957428133d046a3` = odczyt `origin/cpu-optimization` (`git ls-remote`); P1.1 był opublikowany. Zastano 885 zmodyfikowanych/usuniętych śledzonych plików oraz inne nieśledzone pliki, w tym elementy AMD, Intel, NVIDIA i telemetrii; zachowano je. Przeanalizowano raporty P1.1, P0.6 i P1.0. Nie zmieniono kodu backendów ani ustawień produkcyjnych.

Wejście `D:\GoPro\GX010370.MP4` + `D:\GoPro\2026-10-13_15-02-49.fit`, para wskazana przez użytkownika i używana w P0.6; nie podmieniano FIT. Layout `def_layout.json`. Źródło 3840×2160 HEVC Main10, `yuv420p10le`, BT.2020 HLG, full range, 30000/1001 fps, macierz −180°, AAC, 182,716 s. Para była używana w wcześniejszych testach, ale niezależna pełna walidacja synchronizacji FIT nie była w tym etapie wykonywana.

## Długi eksport

Kanoniczny `--test-cpu-export`, start 0, 5400 klatek (180,18 s), Szybki/ultrafast, ABR 16000 kb/s, automatyczne workery, live mux AAC z wejścia w tym samym FFmpeg, bez audio cache i remuxu. Adapter monitorowania P1.1 dostosowany wyłącznie do ścieżek materiału; pomiary 5 s, nie równolegle z innymi eksportami. Dane pozostają lokalnie w `Raporty/CPU_P12_AMD_LONG_EXPORT_LOOKAHEAD/`, nie są częścią commitu.

| Metryka | Wynik |
|---|---:|
| Klatki MP4 / unikalne zadania HUD / duplikaty | 5400 / 5400 / 0 |
| Wall FPS od Start | 9,44 (572,08 s) |
| Okno pipe 541–4860 | 9,44 FPS; to tempo pipe, nie niezależne tempo enkodera |
| x265 | 9,47 FPS, 5400 w 570,28 s, ABR-16000 |
| Pierwsza klatka pipe | 1,11 s od początku streamingu |
| Opróżnienie i finalizacja | 2,61 s, macierz 0,0022 s |
| Workery HUD | 2 podczas renderu; po zakończeniu procesy zamknięte |
| CPU systemowe (mediana wszystkich próbek) | 95,7%; obejmuje inne procesy |
| Szacowane taktowanie WMI min/med/max | 2840 / 3000 / 3940 MHz; pomiary systemowe, nie zegar każdego rdzenia |
| Temperatura | NOT AVAILABLE w odczycie WMI |
| RAM systemowa min/med/max | 20,09 / 25,17 / 25,51 GiB |
| FFmpeg RSS szczyt | 3428,7 MiB |
| Sumaryczny RSS workerów szczyt | 1030,7 MiB, z możliwością podwójnego liczenia stron współdzielonych |
| Wolne miejsce min | 26,93 GiB na monitorowanym dysku |

Pamięć workerów ustabilizowała się w okolicy 1 GiB sumarycznego RSS, bez widocznego wzrostu w późniejszym fragmencie; pojedynczy przebieg nie dowodzi braku wycieku we wszystkich warunkach. MP4 poprawnie sfinalizowane, 5400 klatek, HEVC Main10 yuv420p10le, BT.2020 HLG full, −180°. Audio AAC 180,160 s, wideo 180,180 s (różnica 20 ms, w granicy pakietu AAC). Licznik HUD wykazał brak duplikatów indeksów; nie przeprowadzono niezależnej analizy wszystkich dekodowanych klatek na brak/powtórzenia. Korelacje surowych źródło/wynik i wyświetlanego względem obróconego źródła: 0 s 0,9510, 90 s 0,9496, 179 s 0,9719; w trzech punktach nie zaobserwowano podwójnego obrotu. Nie oceniano na fizycznym monitorze HDR.

## Lookahead — A/B w pełnym eksporcie

A = domyślne x265, B = wyłącznie diagnostyczne `TELEM_CPU_X265_PARAMS=lookahead-threads=4`; każde po 300 klatek, 3 pary na fragment, uruchamiane sekwencyjnie A następnie B, te same wejście, layout, 2 workery, ultrafast i ABR 16M. `wall` obejmuje finalizację; `steady` to okno zapisów HUD do pipe. Warunki między próbami mogły się zmieniać; kolejność nie była zbalansowana jako BA. Wszystkie 18 eksportów przeszły walidator, każda para dała identyczny SHA-256 całego pliku MP4, co obejmuje kodowany obraz i audio danej pary.

| Start klatka | Para | A wall | B wall | Zmiana | A steady pipe | B steady pipe | SHA-256 A=B |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | 1 | 9,80 | 10,25 | +4,59% | 10,43 | 10,92 | tak |
| 0 | 2 | 9,83 | 10,42 | +6,00% | 10,57 | 11,12 | tak |
| 0 | 3 | 9,86 | 10,42 | +5,68% | 10,55 | 11,35 | tak |
| 900 | 1 | 9,93 | 10,58 | +6,55% | 10,73 | 11,77 | tak |
| 900 | 2 | 10,12 | 10,72 | +5,93% | 11,08 | 11,74 | tak |
| 900 | 3 | 10,42 | 10,82 | +3,84% | 11,61 | 11,80 | tak |
| 3900 | 1 | 8,89 | 9,34 | +5,06% | 9,69 | 10,25 | tak |
| 3900 | 2 | 8,95 | 9,41 | +5,14% | 9,67 | 10,25 | tak |
| 3900 | 3 | 8,86 | 9,23 | +4,18% | 9,69 | 10,09 | tak |

Monitor zbierał wykorzystanie CPU, szacowany zegar i RAM w osobnych lokalnych CSV. Temperatury nie udało się odczytać. Żadne inne parametry x265 nie były świadomie zmieniane. Krótkie próby nie dowodzą braku regresji stabilności B przy wielominutowym eksporcie; nie wykonywano drugiego długiego eksportu.

## Golden HUD i ponowny eksport

Ten sam materiał/layout, start 900, 30 klatek: przechwycono klatki 0, 15 i 29 w edytorze, algorytmie eksportu i w potoku przed kompresją po odwróceniu do orientacji wyświetlanej. Dla wszystkich trzech: **0 różnych pikseli, max_diff 0, MAE 0**, edytor vs algorytm oraz edytor vs pipe. To porównanie bieżących ścieżek w identycznych warunkach, nie porównanie z zamrożonym historycznym plikiem Golden P0.4; ten ostatni NOT TESTED. Wygląd wzorca nie był modyfikowany.

Po długim eksporcie wykonano `--reexport` w jednym procesie, dwa zadania po 60 klatek od 900: obydwa success, każde 60 unikalnych indeksów i 0 duplikatów. Monitor widział po dwa workery z różnymi PID; po zakończeniu procesy zniknęły. Sprzętowych testów AMD AMF/Intel/NVIDIA nie wykonywano i backendów nie modyfikowano.

## Decyzja i ograniczenia

Warunkowy wynik jest powtarzalny w tej serii i obrazy par są identyczne, ale brak niezależnego pomiaru temperatury, kolejność zawsze A→B, brak długiego testu B oraz brak porównania do zamrożonego Golden. Nie włączono parametru globalnie ani lokalnie dla modelu; opcja pozostaje diagnostyczna. Rekomendowane jest zbalansowane BA/AB oraz test temperatury i Golden przed decyzją produkcyjną. Nie wykonywano fizycznego HDR i pełnej analizy wszystkich klatek wyjścia. Nie dodano plików wideo, zrzutów RGBA ani pełnych logów do commitu.

Zmieniony plik commitowany: wyłącznie niniejszy raport. Artefakty monitorowania i pliki prób pozostają lokalne, nie są częścią commitu. Stan push i powiadomienia podany w odpowiedzi końcowej.
