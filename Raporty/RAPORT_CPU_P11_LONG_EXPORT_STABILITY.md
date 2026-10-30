# SportCamHUD CPU P1.1 — stabilność długiego eksportu 4K

## Status: SUKCES dla stabilności i poprawności; długość materiału poniżej celu 3–5 min

Dwa pełne eksporty całego nagrania (4394 klatki, 146,6 s) i jeden podwójny eksport 300 klatek w jednym procesie zakończyły się poprawnie: 0 brakujących i 0 powtórzonych klatek, MP4 kompletne, Main10 HLG, −180° bez podwójnego obrotu, audio identyczne bitowo z oryginałem. Nie wykryto wycieku pamięci ani zawieszenia workerów. Etap walidacyjny: **kod aplikacji nie był zmieniany**.

Ograniczenie: dostępna para ma tylko **2 min 26,6 s** materiału (cel 3–5 min). Nie podstawiono innego FIT ani innego nagrania.

## Konfiguracja i Git

| | |
|---|---|
| Komputer | Surface Laptop 5, Intel Core i7-1265U (10 rdzeni / 12 wątków), 15,8 GiB RAM, Windows 11 Pro |
| Commit testowany | `42dcb54` (P1.0) na `cpu-optimization` |
| Status Git przed etapem | P0.9 `4e8aed2` i P1.0 `42dcb54` zacommitowane; `git ls-remote` = `42dcb549006fb76ab2cb13475eab4eef8ac6d0d2` = lokalny HEAD; indeks pusty; pliki P1.0 czyste |
| Wejście | `C:\GoPro\GX010378.MP4` (4394 kl., 30000/1001, HEVC Main10 HLG, matrix −180, AAC 6871 pakietów) + `C:\GoPro\2026-10-15_15-03-50.fit`, `def_layout.json` |
| Eksport | 3840×2160, libx265 ultrafast (Szybki), ABR 16M, Main10, BT.2020/arib-std-b67, `--test-cpu-export --mode direct --wait-prepared` |
| Workery | automatyczne: reguła `max(2, min(8, cpu_count // 8))` → 12 wątków → **2**; `TELEM_CPU_WORKERS` usunięty ze środowiska |

`render_threads`: w kodzie jedynym źródłem jest `_on_settings_changed("threads")`, ale żaden element GUI ani zapis projektu nie emituje tego ustawienia; wartość domyślna `None` → reguła automatyczna. Potwierdzone w działaniu: przez cały eksport dokładnie 2 procesy workerów.

Wolne miejsce przed testem 45 GB; szacowany wynik ~300–400 MB; rzeczywisty 317,5 MB; minimum wolnego miejsca w trakcie 44,16 GB.

## Narzędzia pomiarowe

`Raporty/CPU_P11_LONG_EXPORT_STABILITY/`:
- `p11_monitor.py` — uruchamia kanoniczny harness i co 5 s zapisuje CSV/JSON: FPS bieżący i średni, CPU systemu, taktowanie (WMI `% Processor Performance` × częstotliwość bazowa), strefy termiczne ACPI, `PercentPassiveLimit`/`ThrottleReasons`, RAM systemu, RSS FFmpeg/workerów/procesu głównego, rdzenie per rola, CPU innych procesów, rozmiar MP4, wolne miejsce, zajętość dysku.
- `p11_launcher.py` — tylko callback na futures `_RenderExecutor` (liczba ukończonych klatek, indeksy, duplikaty).
- `sitecustomize.py` (przez `PYTHONPATH`, wyłącznie w procesach `--multiprocessing-fork`) — co 5 s RSS i rozmiary cache lean/kompas/efekty/static w każdym workerze.

Bez instalowania dodatkowego oprogramowania. Pierwszy przebieg (`long_full`) ujawnił błąd **narzędzia** (blokada pliku przy `os.replace` w wątku diagnostycznym po ~550 s; eksport niezakłócony) — licznik klatek w CSV zamarł. Poprawiono narzędzie i powtórzono pełny przebieg (`long_full2`), który jest przebiegiem głównym; `long_full` służy jako powtórzenie.

## Wyniki długiego eksportu

| | long_full2 (główny) | long_full (powtórzenie) |
|---|---:|---:|
| Klatki ukończone / zapisane / w MP4 | 4394 / 4394 / 4394 | 4394 / 4394 / 4394 |
| Unikalne indeksy / duplikaty / błędy zadań | 4394 / 0 / 0 | 4394 / 0 / 0 |
| Przygotowanie projektu do kliknięcia Start | 5,03 s | 4,88 s |
| Przygotowanie HUD (worker init + mapa) | 0,07 s | — |
| Czas do pierwszej klatki w potoku | 1,22 s | 1,35 s |
| Steady FPS (klatki 440–3955) | **4,38** | 4,44 |
| Wall FPS harnessu | **4,39** (1000,3 s) | 4,48 (981,2 s) |
| Finalizacja FFmpeg / metadanych | 3,46 s / 0,004 s | 2,89 s / 0,003 s |
| Rozmiar MP4 | 317 527 113 B | 317 527 113 B |

### FPS i zasoby w czasie (long_full2, okna ~60 s)

| t [s] | klatki | FPS | śr. FPS | CPU % | MHz | ACPI °C | RAM sys GB | FFmpeg MB | workery MB | główny MB | inne CPU % | lean/kompas | efekty MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 15–61 | 254 | 4,18¹ | 5,23 | 76 | 1584 | 49,6 | 14,05 | 3013 | 792 | 460 | 7,7 | 8/8 | 30,7 |
| 66–122 | 543 | 4,72 | 4,92 | 85 | 1270 | 50,2 | 14,23 | 3034 | 967 | 460 | 8,0 | 8/8 | 63,9 |
| 127–183 | 837 | 4,81 | 4,88 | 85 | 1248 | 50,5 | 14,27 | 3041 | 1003 | 460 | 8,8 | 8/8 | 63,9 |
| 188–244 | 1112 | 4,50 | 4,78 | 86 | 1260 | 50,5 | 14,19 | 3052 | 1008 | 460 | 8,0 | 8/8 | 63,9 |
| 249–305 | 1414 | 4,93 | 4,81 | 85 | 1256 | 50,6 | 14,15 | 3054 | 951 | 461 | 8,7 | 8/8 | 63,9 |
| 310–366 | 1716 | 4,95 | 4,84 | 85 | 1258 | 50,7 | 14,41 | 3056 | 981 | 461 | 10,2 | 8/8 | 63,5 |
| 372–428 | 1987 | 4,42 | 4,77 | 86 | 1264 | 50,7 | 14,22 | 3057 | 988 | 461 | 7,4 | 8/8 | 63,5 |
| 433–489 | 2243 | 4,20 | 4,70 | 86 | 1284 | 50,8 | 14,19 | 3068 | 958 | 461 | 6,9 | 8/8 | 63,5 |
| 494–550 | 2490 | 4,04 | 4,62 | 86 | 1244 | 50,7 | 14,22 | 3082 | 992 | 461 | 7,7 | 8/8 | 63,5 |
| 555–611 | 2731 | 3,94 | 4,55 | 86 | 1286 | 50,8 | 14,42 | 3087 | 1008 | 461 | 9,2 | 8/8 | 63,7 |
| 616–672 | 2993 | 4,29 | 4,53 | 85 | 1280 | 50,8 | 14,41 | 3089 | 1025 | 461 | 8,0 | 8/8 | 63,9 |
| 677–733 | 3257 | 4,32 | 4,51 | 85 | 1260 | 50,8 | 14,33 | 3090 | 985 | 461 | 9,0 | 8/8 | 63,9 |
| 738–794 | 3526 | 4,40 | 4,50 | 85 | 1260 | 50,8 | 14,41 | 3090 | 978 | 461 | 9,5 | 8/8 | 64,0 |
| 799–856 | 3767 | 3,93 | 4,46 | 83 | 1270 | 50,9 | 14,33 | 3090 | 943 | 461 | 12,4 | 8/8 | 63,7 |
| 861–917 | 4014 | 4,04 | 4,43 | 79 | 1252 | 50,8 | 14,10 | 3078 | 956 | 436 | 8,4 | 8/8 | 63,5 |
| 922–978 | 4251 | 3,87 | 4,40 | 79 | 1258 | 50,8 | 14,11 | 3048 | 961 | 436 | 8,4 | 8/8 | 64,0 |
| 983–1008 | 4381 | 4,26 | 4,39 | 80 | 1260 | 50,8 | 14,18 | 3051 | 976 | 436 | 9,7 | 8/8 | 63,9 |

¹ okno obejmuje start (0 klatek do ~15 s). Pełne próbki 5 s: `long_full2.metrics.csv`; zestawienie: `summary.json`.

Szczyt RAM systemu: **14,42 GiB** z 15,83 GiB (w tym ok. 10 GiB zajętych przed startem przez system i inne aplikacje). Szczyt RSS: FFmpeg 3090 MB, suma workerów 1025 MB, proces główny 461 MB.

### Spadek FPS w czasie

Średnie tercji: 4,79 → 4,25 → 4,13 FPS. Korelacje:
- **Taktowanie**: po pierwszej minucie stałe ~1250–1290 MHz (z ~1580 MHz w pierwszej minucie — krótkotrwały boost); w drugiej i trzeciej tercji praktycznie identyczne (1270 vs 1260 MHz) — nie tłumaczy spadku 4,25 → 4,13.
- **Temperatura**: strefy ACPI 49,6 → 50,9 °C, `PercentPassiveLimit` = 100% i `ThrottleReasons` = 0 przez cały czas. To strefy ACPI płyty, **nie** temperatura rdzeni; temperatura pakietu CPU i limit mocy PL1/PL2: **NOT TESTED** (brak dostępu bez uprawnień administratora).
- **RAM**: płaski (14,05–14,42 GB), brak swapowania widocznego w danych.
- **Dysk**: 0,2–2% zajętości, zapis ~0,3 MB/s — bez wpływu.
- **Inne procesy**: 7–12% CPU w całym teście, bez trendu.
- **Treść**: FPS w tych samych zakresach klatek jest prawie identyczny w obu długich przebiegach (np. 2000–2499: 4,05 / 4,09). Rozstrzygające: osobny, „zimny” eksport klatek 3900–4199 dał steady **4,00 / 4,00 FPS**, tyle samo co długi przebieg w tym zakresie (3,93–4,04). Spadek wynika więc z treści końcowej części nagrania (koszt x265 zależny od sceny), a nie z czasu działania. Wyjaśnienia nie przypisujemy throttlingowi.

## Stabilność workerów i pamięci

- Dokładnie 2 workery (PID 15540, 18984) od pierwszej do ostatniej próbki; żadnego restartu ani zawieszenia; każda próbka 5 s po starcie miała przyrost klatek (jedyne próbki 0 FPS: przed startem i po zakończeniu).
- Liczniki workerów: kompas renderowany 2197 i 2194 razy (suma 4391 przy ostatniej próbce 5 s przed końcem) — równomierny podział.
- RSS na worker (z wnętrza procesu): start ~292 MB → ¼ ~475 MB → ½ ~478 MB → ¾ ~475 MB → koniec ~491 MB. Wzrost w pierwszej ćwierci to jednorazowe zapełnienie cache: `_EFFECT_CACHE` dochodzi do limitu 64 MiB, `_STATIC_CACHE` do 128 wpisów. Od ¼ do końca RSS waha się w granicach ±15 MB bez trendu — **brak wycieku** w tym teście.
- Limity cache przez cały eksport: lean 8/8, kompas 8/8, efekty ≤ 64,0 MiB.
- Proces główny 460–461 MB, FFmpeg 2,95–3,09 GB, bez trendu wzrostowego.

## Wideo, audio, HUD

| Kontrola (long_full2; long_full identycznie) | Wynik |
|---|---|
| Liczba klatek | 4394 = zakres 0–4393 = źródło |
| PTS wideo | 4394 unikalne, stały krok 1001 (30000/1001), start 0 |
| Pełne dekodowanie `ffmpeg -f null` | bez błędów |
| Czas wideo / audio | 146,613133 s / 146,581333 s — jak w źródle |
| Audio | 6871 pakietów; `framemd5` (PTS, czas trwania, rozmiar, MD5) **identyczne** z oryginałem |
| Proces audio | jedno FFmpeg: `-i GX010378.MP4 … -map 0:a? -c:a copy` + RGBA z `pipe:0` (audyt P1.0, ten sam kod); brak plików pośrednich, brak wtórnego remuksu |
| Format | HEVC Main 10, yuv420p10le, bt2020 / arib-std-b67 / bt2020nc, pc |
| Orientacja | display matrix −180 (jak źródło); klatki z autorotacją t=5/73/141 s: obraz i HUD w pionie — brak podwójnego obrotu |
| Zakończenie MP4 | walidacja harnessu `valid=True`, `color_valid`, poprawny moov (ffprobe/dekodowanie) |

HUD (podgląd t=5/73/141 s): czas 00:03 → 01:14 → 02:22, dystans 0,0 → 0,3 → 0,7 km, kompas, lean (+0,8° / −7,3° / +0,2°), mapa ze śladem, BAR-y i wykresy obecne i zmieniają się w czasie.

Golden Harness (2 workery, 30 klatek, klatka kontrolna 15):

| Fragment | edytor vs `compose_overlay` | edytor vs potok |
|---|---|---|
| początek, klatka 15 | 0 px, max_diff 0, MAE 0 | 0 px, max_diff 0, MAE 0 |
| środek, klatka 2205 | 0 px | 0 px |
| koniec, klatka 4365 | 0 px | 0 px |

Kontrole Golden są osobnymi krótkimi eksportami tych zakresów (nie RGBA z długiego eksportu, który nie był zapisywany). Determinizm długich eksportów potwierdza identyczny rozmiar i liczba klatek obu MP4; bitowej identyczności HEVC nie wymagano.

## Test końcowy (dwa zadania w jednym procesie)

`--reexport`, klatki 3900–4199, 300 klatek, ten sam projekt:

| | zadanie 1 | zadanie 2 |
|---|---:|---:|
| Klatki / duplikaty / valid | 300 / 0 / True | 300 / 0 / True |
| Pierwsza klatka | 1,28 s | 1,36 s |
| Steady / wall FPS | 4,00 / 3,87 | 4,00 / 3,83 |
| Finalizacja | 4,57 s | 5,06 s |
| PID workerów | 6120, 12928 | 19464, 19996 |
| Proces główny w trakcie / po | 462,0 / 334,2 MB | 462,3 / 334,6 MB |

Workery pierwszego zadania zostały zamknięte (0 procesów między zadaniami) i uruchomiono nowe. Oba MP4: 300 klatek, Main10 HLG, −180, audio 10,009 s. Pamięć procesu głównego nie narasta między zadaniami (+0,3–0,4 MB).

## Wykryte błędy

- Aplikacja: **brak** potwierdzonych błędów poprawności ani stabilności; brak zmian kodu.
- Narzędzie diagnostyczne P1.1: `PermissionError` przy `os.replace` w wątku licznika (Windows) — poprawione ponawianiem; dotyczyło wyłącznie zbierania metryk.
- Znane z P1.0, bez zmian: `test_nvidia_p400_native_integration.py` zawiesza się, 2 testy schematu gauge FAIL — także na HEAD sprzed P1.0; poza zakresem.

## Ograniczenia

- Materiał 146,6 s zamiast 3–5 min (najdłuższa dostępna para; całe nagranie wyeksportowane, bo krótszy fragment byłby jeszcze dalej od celu).
- Para nie jest kanoniczną parą `Video/...` z BENCHMARKS.md (niedostępna); używana zgodnie z poleceniem.
- Temperatura pakietu CPU, moc i PL1/PL2: **NOT TESTED**; dostępne tylko strefy ACPI.
- Taktowanie szacowane z `% Processor Performance` × częstotliwość bazowa (WMI), średnia dla wszystkich rdzeni.
- Licznik klatek pochodzi z ukończonych zadań HUD (różni się od zapisanych do FFmpeg o ≤ okno MAX_IN_FLIGHT).
- Tylko CPU/Intel; AMD/NVIDIA nie dotyczy tego etapu i nie były testowane.
- Wyniki Intela nie są porównywane z Ryzenem.

## Podsumowanie

| Kryterium | Status |
|---|---|
| Git P0.9/P1.0 zacommitowane i wypchnięte | PASS |
| 2 workery automatycznie, brak wymuszonego `render_threads` | PASS |
| Wszystkie klatki, brak duplikatów, brak zawieszeń | PASS (2 × 4394, 2 × 300) |
| Brak wycieku pamięci, limity cache | PASS (w zakresie testu) |
| Main10 HLG, rotacja −180, brak podwójnego obrotu | PASS |
| Audio live copy, bitowo zgodne, synchronizacja | PASS |
| Golden HUD początek/środek/koniec | PASS (0 px) |
| Ponowny eksport w tym samym procesie | PASS |
| Długość 3–5 min | NIESPEŁNIONE — materiał 2:26,6 |
| Throttling / temperatura CPU | NOT TESTED (ACPI: brak ograniczenia pasywnego) |
