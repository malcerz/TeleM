# SportCamHUD CPU P1.0 — wydajność cache lean/kompas i zamknięcie P0.9

## Status: PASS dla poprawności i pamięci; zysk FPS eksportu NOT PROVEN

Optymalizacja daje identyczne RGBA (0 niezgodności we wszystkich porównaniach), krótszy czas renderu wskaźnika (lean −6%, kompas −13% w przeplatanym A/B) i mniejszą pamięć workerów (−7…−10% szczytowego RSS). Pełny eksport jest ograniczony przez enkoder x265; zmiana FPS eksportu mieści się w szumie pomiaru — **NOT PROVEN**.

## Stan początkowy i Git

Gałąź `cpu-optimization`, HEAD `ff42586` = `origin/cpu-optimization`. Zastany brudny stan drzewa (ok. 780 usunięć w `Raporty/`, ~107 zmodyfikowanych plików, w tym `dispatcher.py`, `compositor.py`, NVIDIA/Intel) pozostawiono bez zmian; nie był stage'owany. Bez reset/clean/force push.

Commity:
1. **P0.9** `4e8aed2` — wyłącznie `src/gui/qt/application.py`, raport P0.9 i `Raporty/CPU_P09_GOLDEN_DETERMINISM/`.
2. **P1.0** — `src/indicators/lean.py`, `src/indicators/gauge.py`, `src/indicators/effects.py` (wszystkie trzy czyste przed etapem), `tests/test_cpu_p10_indicator_cache.py`, ten raport i `Raporty/CPU_P10_INDICATOR_CACHE/`.

## 1. Zabezpieczenie P0.9

Para jawnie wskazana w P0.8/P0.9 (`C:\GoPro\GX010378.MP4` + `C:\GoPro\2026-10-15_15-03-50.fit`, `def_layout.json`, 4K, Szybki, ABR 16M). Ta para nie jest kanoniczną parą z BENCHMARKS.md (pliki `Video/...` są niedostępne); nie podstawiono innego FIT.

| Kontrola P0.9 (przed P1.0) | Wynik |
|---|---|
| 30 klatek od 900, 2 workery, vs `checked_s900_w2.hashes.jsonl` | 0/30 różnych SHA-256 RGBA |
| Golden f915: edytor vs `compose_overlay`, edytor vs potok (obrót 180°) | 0 px, max_diff 0, MAE 0 |
| Kolejność w logu | mapa gen. 2, `export:cpu` 74/74 → `Golden CPU READY` → start eksportu |
| Wybrane testy (8 plików jak w P0.9) | 58 passed, 5 skipped |
| `tests/test_golden_parity_etap4.py` | 2 FAIL → **BLOCKED** (brak danych i `golden_ref_track_map_frame150.png`, para zabroniona w BENCHMARKS.md) |
| Historyczny Golden P0.4 (GX010370) | **BLOCKED** — materiał niedostępny |

Wzorców nie zmieniano. Ograniczenia opisano w treści commitu i dopisano do raportu P0.9.

## 2. Przyczyna wzrostu kosztu

Profil na rzeczywistej konfiguracji `def_layout.json` (lean: bike, size 5, cień v2; kompas: rose, size 7.8, cień, opacity 0.9; ss=1, brak supersamplingu) i rzeczywistych sekwencjach kątów 150 klatek z fragmentów 900 i 1800 (`indicator_profile.py`, `profile_before.json`):

| | lean | kompas |
|---|---|---|
| Unikalne pełne kąty / 150 | 150 | 150 |
| Unikalne kąty po zaokrągleniu 0,1° (stary, błędny klucz) | 63–71 | 116–126 |
| Trafienia cache przy pełnym kluczu | **0/150** | **0/150** |
| ms/render (HEAD) | 2,85–2,89 | 2,13–2,18 |

Wniosek: koszt nie pochodzi z samego klucza, lecz z tego, że przy pełnych kątach **każda klatka jest chybieniem**. Wcześniej ~55% klatek lean i ~20% klatek kompasu trafiało w cache (dlatego było szybciej, ale niedeterministycznie). Liczby P0.9 (1,61 → 8,47 ms lean) dotyczyły syntetycznej konfiguracji (`size_px=400`), nie layoutu produkcyjnego.

Rozbicie (cProfile, lean, 150 klatek): bicubic `transform` 71% (1,85 ms), efekt cienia 0,58 ms (w tym hash blake2b alfy i wstawienie do cache), `convert` RGBA→RGBa 0,10 ms, `alpha_composite` 0,15 ms; generowanie geometrii (narożniki, macierz) pomijalne. Kompas: `warpAffine` tarczy i alfy cienia 0,75 ms, 3× `alpha_composite` 0,45 ms, tekst kursu 0,17 ms, LUT przezroczystości budowany lambdą co klatkę (38 400 wywołań/150 klatek).

Pamięć (chybienia nigdy nietrafiane, na worker):

| Cache | wpis | limit | pełny |
|---|---:|---:|---:|
| `_LEAN_ROTATED_PATCH_CACHE` | 142 KiB | 360 | ~50 MiB |
| `_COMPASS_INDICATOR_CACHE` | 634 KiB | 64 | ~40 MiB |
| `_EFFECT_CACHE` (wpisy lean) | 235 KiB | limit 64 MiB wspólny | do 64 MiB |

Wpisy efektów lean (unikalna alfa w każdej klatce) wypierały z **wspólnego** LRU efektów wpisy innych wskaźników — koszt ukryty poza lean.

## 3. Implementacja (identyczna z konstrukcji)

1. **lean.py**: `_LeanRotationSource.padded_premul` — źródło premultiplikowane raz. `Image.transform` dla RGBA wykonuje `convert("RGBa").transform(...).convert("RGBA")`; wykonujemy te same kroki bez ponownej konwersji źródła (sprawdzone w kodzie Pillow 13.0.0 i bajtowo).
2. **lean.py**: patch cache 360 → 8 wpisów (dokładne powtórzenia: kąt przycięty do `max_angle`, ponowny render tej samej klatki). Dla kąta widzianego po raz pierwszy obraz dostaje `_effects_no_cache`.
3. **effects.py**: dla obrazu z `_effects_no_cache` (i bez `_dynamic_key`) pomijany jest hash, odczyt i zapis cache; warstwa efektu jest liczona tym samym kodem, a obraz komponowany w miejscu na świeżym rastrze. Przy powtórzeniu kąta (trafienie patcha) obowiązuje normalne cache. Inne wskaźniki bez zmian.
4. **gauge.py**: cache kompasu 64 → 8; LUT przezroczystości cachowany (ograniczony do 64 wartości), wynik `point(list)` == `point(lambda)`; dla czarnego cienia pominięta kompozycja na przezroczystym płótnie — dowód wyczerpujący wszystkich 65 536 par (wartość, alfa): kompozycja na (0,0,0,0) zwraca źródło z RGB wyzerowanym przy alfa 0, a czarna warstwa cienia ma już tę postać. Kolor cienia ≠ czarny → stara ścieżka.

Bez zmian geometrii, kolorów, antyaliasingu, filtrów i kluczy (nadal pełny kąt). Rozważone i odrzucone: przycięcie przezroczystego marginesu patcha (tylko ~6% powierzchni, zmiana początku układu zmienia arytmetykę float); ponowne użycie tekstu kursu kompasu/cienia statycznych części lean (mieszanie alfa nie jest rozdzielne bitowo).

## 4. Testy i zgodność pikselowa

| Test | Wynik |
|---|---|
| A/B w jednym procesie (HEAD vs nowa), 6 przebiegów × 150 klatek × 2 fragmenty × 2 wskaźniki | **0 niezgodności SHA-256** (3600 par) |
| `profile_before` vs `profile_after`, 600 renderów | 0/600 różnych |
| Eksport 30 klatek, 1/2/4 workery × start 900/1800, vs hashe P0.9 (sprzed P1.0) | **0/30** różnych w każdym z 6 |
| Te same: 2 i 4 vs 1 worker | 0/30 |
| Golden f915 / f1815 we wszystkich 6: edytor vs algo, edytor vs potok | 0 px, max_diff 0, MAE 0 |
| `tests/test_cpu_p10_indicator_cache.py` (bliskie kąty 20,0/20,001/20,01/20,04/20,049/20,05/20,099, clamp, losowa kolejność; efekty bez cache == z cache; limity) | 3 passed |
| Renderery i GPU bridge (21 plików: lean_gpu_bridge, lean_parity_5xl, lean_tight_rotation, compass_*, effects_*, dynamic_export_backends, …) | wszystkie PASS poza poniższymi |
| `test_etap8m5_gauge_parity::test_gauge_property_live_preview`, `test_gauge_rendering::test_gauge_schema_exposes_only_used_fields` | FAIL — **identycznie na HEAD** (schemat GUI `thickness`, lokalne zmiany `indicator_schemas.py`), niezwiązane |
| `test_nvidia_p400_native_integration.py` | zawiesza się (>150 s) — **identycznie na HEAD**; NOT TESTED |
| `test_amd_compass_selected_source.py` | 6 skipped |

Format wyjścia (ffprobe `after_s900_w2.mp4`): HEVC Main 10, yuv420p10le, bt2020 / arib-std-b67, display matrix −180, AAC 47 ramek. Audyt procesów podczas pomiarów: jedno wywołanie FFmpeg `-i GX010378.MP4 … -map 0:a? -c:a copy` + RGBA przez `pipe:0`; brak plików audio pośrednich i wtórnego remuksu. Synchronizacja: indeksy klatek 900–929/1800–1829 i hashe identyczne z P0.9.

## 5. Wydajność

Mikrobenchmark A/B przeplatany (`ab_bench.json`, średnia z 900 renderów na wersję):

| Wskaźnik | HEAD ms | P1.0 ms | zmiana |
|---|---:|---:|---:|
| lean, 900 | 3,30 | 3,10 | −6,3% |
| lean, 1800 | 3,35 | 3,16 | −5,7% |
| kompas, 900 | 3,61 | 3,12 | −13,6% |
| kompas, 1800 | 3,56 | 3,12 | −12,5% |

(Wartości bezwzględne wyższe niż w profilu, bo CPU był w innym stanie termicznym; porównanie ważne tylko w parze.)

Pamięć cache po 150 klatkach (A/B): lean patch 20,8 → 1,1 MiB, efekty lean 34,4 → 0 MiB, kompas 39,7 → 5,0 MiB. Pełne limity: ~154 → ~6,6 MiB na worker.

Harness, naprzemiennie przed/po (`ab_perf.py`, start 900):

| Przebieg | przed | po |
|---|---|---|
| HUD only (null sink), 300 kl., 2 workery — FPS | 17,7 / 20,1 | 18,1 / 22,1 |
| ↳ szczyt RSS workerów (suma) | 984,9 / 984,4 MiB | 915,7 / 911,7 MiB |
| ↳ rdzenie workerów (okno) | 2,00 / 1,82 | 2,04 / 1,70 |
| HUD only, 300 kl., 4 workery — FPS | 25,0 | 25,2 |
| ↳ szczyt RSS workerów | 2442 MiB | 2188 MiB |
| Pełny eksport 150 kl., 2 workery — FPS (steady) | 5,0 (5,71) / 4,9 (5,64) | 4,9 (5,73) / 4,4 (5,42) |
| ↳ CPU systemu / rdzenie FFmpeg | 93% / 8,7 | 92% / 8,5 |

HUD FPS: niewielki wzrost w każdej parze, ale rozrzut powtórzeń (17,7 vs 20,1) jest większy niż efekt — kierunek zgodny z mikrobenchmarkiem, wartość nieprecyzyjna. Eksport jest ograniczony przez x265 (~8,5 rdzenia FFmpeg vs ~1,3 workerów); spadek 4,4 w drugiej parze nie powtarza się (pierwsza para 5,0 vs 4,9, steady 5,71 vs 5,73) i odpowiada wcześniejszemu dryfowi z P0.8/P0.9. Wpływ na FPS eksportu: **NOT PROVEN** (ani zysk, ani regresja). RAM: wyraźny, powtarzalny spadek RSS workerów (−70 MiB przy 2, −254 MiB przy 4 workerach w 300 klatkach; przy dłuższych eksportach do ~150 MiB/worker, bo stare cache rosły do limitów).

## 6. Izolacja backendów i ryzyka

Zmiany dotyczą współdzielonych rendererów CPU wskaźników; nie zmieniono kodu AMD/Intel QSV/NVIDIA ani natywnych bibliotek. GPU bridge lean (`_skip_dynamic_graphic`) nie korzysta z nowych ścieżek. Pliki `dispatcher.py`/`compositor.py` (z lokalnymi zmianami użytkownika) nie zostały dotknięte.

- Sprzęt AMD/NVIDIA: **NOT TESTED** (na maszynie tylko Intel); test NVIDIA P400 zawiesza się także na HEAD.
- Mały cache (8) może zmniejszyć trafienia w podglądzie GUI przy przewijaniu do wielu tych samych klatek — wpływ tylko na czas, nie na obraz; NOT TESTED w GUI.
- `_effects_no_cache` jest atrybutem obiektu `Image`; kopia obrazu go traci — wtedy działa zwykłe cache (ten sam wynik).
- Inne layouty (inne kolory cienia, rozmiary, ss>1) sprawdzone tylko testami jednostkowymi.

## 7. Podsumowanie

| Kryterium | Status |
|---|---|
| P0.9 potwierdzone i zacommitowane osobno | PASS (z BLOCKED: etap4 Golden, P0.4) |
| Źródło kosztu ustalone | PASS — 0% trafień przy pełnych kątach; dominujący bicubic transform |
| Identyczne RGBA, 1/2/4 workery, 2 fragmenty, Golden | PASS |
| Brak zaokrąglania kluczy | PASS |
| Ograniczona pamięć cache | PASS |
| ms/render wskaźnika | PASS (−6% lean, −13% kompas) |
| FPS HUD | wzrost w każdej parze, mniejszy niż rozrzut — NOT PROVEN liczbowo |
| FPS eksportu | NOT PROVEN |
| AMD/NVIDIA sprzęt | NOT TESTED |
