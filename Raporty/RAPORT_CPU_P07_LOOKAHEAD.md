# SportCamHUD — CPU P0.7: lookahead

## Status: CZĘŚCIOWO / BLOCKED

Nie wdrożono zmiany produkcyjnej. P0.6 dostarcza obiecujący wynik, którego nie należy odrzucać z powodu progu 10%, ale nie potwierdzono go na kilku fragmentach ani na tej maszynie. Nie wyciągamy wniosków dla innych procesorów z liczby wątków.

## Stan i publikacja P0.6

Gałąź `cpu-optimization`, początkowy HEAD `f809e2577908f91f7683ca6197d27c21bc521436`; `git ls-remote origin refs/heads/cpu-optimization` wskazał ten sam pełny SHA. Commit `docs(cpu): P0.6 libx265 tuning measurements, no parameter change deployed` zawiera raport P0.6 i jest opublikowany na origin. W katalogu roboczym zastano 778 usunięć, 107 modyfikacji i 338 pozycji nieśledzonych; pozostawiono je bez zmian. Indeks był pusty.

## Środowisko i próba

Dostępny CPU: Intel Core i7-1265U, 12 wątków logicznych. Maszyna z Ryzen 7 7730U nie jest dostępna. Kanoniczny wrapper `Raporty/CPU_P02_PERFORMANCE/scripts/run_harness.py` ma na sztywno `D:\GoPro\GX010370.MP4` i `D:\GoPro\2026-10-13_15-02-49.fit`; dysk D: i ta para są niedostępne. Zdefiniowanych w BENCHMARKS.md par GX020079 oraz GX030120 nie znaleziono w C:\GoPro ani w sprawdzonych katalogach projektu na C: i Z:.

Uruchomiono kanoniczny punkt wejścia `--test-cpu-export` na dostępnym `C:\GoPro\GX010378.MP4`, bez FIT, 30 klatek, profil fast, 16M, start 0, `--wait-prepared`, offscreen. Przygotowanie projektu osiągnęło READY, jednak przez ponad 40 sekund potem eksport nie rozpoczął kodowania ani nie zapisał wyniku. Próbę przerwano; brak wyniku MP4 i JSON. Bez FIT wskaźniki FIT były niedostępne, więc i tak nie byłby to porównywalny Golden HUD. Przyczynę zatrzymania nie ustalono. Nie uruchamiano długiego eksportu.

## Wyniki i ograniczenia

| Kontrola | Wynik P0.7 |
|---|---|
| FPS przed/po, domyślne i lookahead 2/3/4/5, kilka fragmentów 4K | NOT TESTED — brak ukończonego przebiegu |
| Intel i7-1265U | NOT TESTED — próba nie doszła do kodowania |
| Ryzen 7 7730U | NOT TESTED w P0.7 — niedostępny |
| Zgodność bitowa, bitrate, Main10 HLG, orientacja, audio live mux, CPU/RAM, Golden HUD | NOT TESTED w P0.7 |

Historyczny wynik P0.6, nie nowy pomiar: Ryzen 7 7730U, ultrafast, 300 klatek, trzy pary harnessu: **11,08 → 11,87 FPS (+7,2%)**. Raport P0.6 podaje bitową zgodność dla porównania sweepu, identyczny bitrate i brak regresji startu/finalizacji/pamięci w tych pomiarach. Nie należy przenosić tych wyników na Intel ani inne fragmenty. P0.6 nie dowodzi bitowej zgodności wszystkich możliwych wejść.

## Reguła i decyzja

Brak podstaw do automatycznego doboru na podstawie liczby logicznych wątków i profilu: nawet na 16 wątkach P0.6 wykazał regresję dla wartości 2 i 8, a zależność od procesora i materiału nie została potwierdzona. Hipoteza `logiczne wątki // 4` pozostaje niesprawdzona. Nie wdrożono także wyjątku dla Ryzena, ponieważ wymagane powtórzenie na różnych fragmentach nie zostało wykonane. Istniejący diagnostyczny `TELEM_CPU_X265_PARAMS=lookahead-threads=4` pozostaje eksperymentalny; nie jest automatyczną regułą i nie jest ograniczony do profilu fast. Profile Szybki, Zbalansowany i Jakość oraz mechanizmy jakości x265 pozostają bez zmian. Kod GPU i telemetrii nie był zmieniany.

Aby dokończyć etap, potrzebna jest dostępna, jawnie zatwierdzona para wideo/FIT albo kanoniczny zestaw, sprawny harness oraz pomiary na Ryzen i Intel: przeplatane przebiegi domyślne i 2/3/4/5 dla kilku fragmentów, z wynikami FPS, hashami, bitrate, walidacją HLG/orientacji/audio i Golden HUD oraz próbkowaniem zasobów. Dopiero te dane mogą uzasadnić ograniczony wyjątek lub regułę.

## Zmienione pliki i podsumowanie

Wyłącznie niniejszy raport. Testy wymagane do decyzji wdrożeniowej: BLOCKED; wdrożenie: NIE; izolacja backendów: bez zmian kodu. Wynik P0.6 opublikowany: PASS. P0.7 jako całość: NIEUKOŃCZONY.
