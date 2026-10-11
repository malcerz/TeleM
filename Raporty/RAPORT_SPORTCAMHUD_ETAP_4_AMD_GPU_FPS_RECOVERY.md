# SPORTCAMHUD — Etap 4: diagnoza AMD FPS

**Data:** 2026-10-11 | **Repozytorium:** `C:\_DEV\BikeRideHUD-main-new` | **Gałąź:** `fix/gui-freeze-hud-composite`
**Status:** **PARTIAL / BLOCKED — FPS root cause NOT PROVEN**

## 1. Stan Git przed rozpoczęciem

- HEAD przed zmianami: `bf6f28636b9816eac99602fbb7b8983cb9992a4e` (`docs: report render error pipeline`).
- Gałąź była 11 commitów przed `origin/fix/gui-freeze-hud-composite`, bez zmian za origin.
- Zastane zmiany użytkownika: `def_layout.json` zmodyfikowany oraz `Raporty/RAPORT_SPORTCAMHUD_FULL_REGRESSION_AUDIT_20261011.md` nieśledzony. Żaden z nich nie został edytowany ani dodany do commita. Backup `C:\_DEV\_SportCamHUD_BACKUP_20261011_175842` nie był dotykany.
- Po weryfikacji cache’u utworzono commit implementacji `70b3a6e19a32c4df0b1eccee4ce958e00afab215`. Nie wykonano push.

## 2. Materiały i harness

Sprawdzono dokładną kanoniczną parę `Video/GX020079.MP4` + `Video/GX020079.fit`, wymaganą rozdzielczość i bieżący checkout. Plików wejściowych nie ma w `Video/`. Przeszukano pod kątem nazw kanonicznych także wskazane źródło `F:\GoPro`; żadna z wymaganych par nie została tam znaleziona. Wymagany layout `C:\_DEV\TeleM\def_layout.json` również nie jest dostępny.

`BENCHMARKS.md` wskazuje `tools/amd_performance_gate.py` jako runner production acceptance z `--production-defaults`; tego pliku nie ma w checkout. Jest obecny `scripts/test_amd_real.py`, ale nie jest to runner wskazany przez bieżącą politykę benchmarków. Nie uruchamiałem żadnego eksportu na innym materiale ani testu, który mógłby wytworzyć cache audio lub naruszyć cache użytkownika.

**Wynik:** kanoniczny A/B i realny eksport są **BLOCKED** przez brak źródeł, layoutu oraz wymaganego runnera. Nie zastąpiono danych innym VIDEO/FIT.

## 3. Warunki A/B i historia

Wymagane porównanie A (historyczny known-good), B (efekty OFF), C (efekty ON z layoutem użytkownika) i diagnostyczne D nie mogło zostać wykonane w jednakowych warunkach. Brakuje kanonicznego VIDEO/FIT i bieżącego `def_layout.json` jako jawnie wskazanego materiału testowego; nie ma też runnera production acceptance.

Historyczne raporty nie tworzą porównywalnego A/B dla obecnego kodu:

- `RAPORT_AMD_CURRENT_41FPS_BOTTLENECK_AUDIT.md` raportuje 41.311 render FPS i 40.589 effective FPS dla 17 760 klatek oraz `Video Codec 0` około 99%. To inny checkout/commit (`c80ba07` na `integration/intel-amd`), historyczny preset i workload na Ryzen 7 7730U. Raport wymienia `GX010115.MP4` i `GX010114_116.fit`; nie traktuję tego jako pomiaru aktualnego checkoutu.
- `RAPORT_AMD_CPU_ABOVE_REGRESSION_OPTIMIZATION.md` podaje 41.364 FPS dla historycznego `0ef407e`, 34.950 FPS dla `24948bf` oraz 36.616 FPS po `eeb4a4b`. To pomiary z wcześniejszej gałęzi i odmiennych stanów aplikacji/layoutu; nie wskazują commita regresji w tej gałęzi.
- `RAPORT_SPORTCAMHUD_EFFECTS_PERCENT_AMD_FPS_FIX.md` deklaruje 29.15–29.90 direct native FPS dla 300 klatek. Wartości nie zostały tu niezależnie powtórzone; nie ma lokalnych surowych profili ani dostępnego źródła. Nie dowodzą wydajności eksportu 47 183 klatek.

Zatem ostatni porównywalny known-good, pierwszy wadliwy commit i konkretna zmiana odpowiedzialna za zgłaszany spadek 41 → 23.8 FPS: **NOT PROVEN**. Nie utożsamiam liczby „GPU Total” z użyciem silnika kodera.

## 4. Potwierdzony błąd cache efektów — osobny od FPS

W `src/indicators/effects.py` klucz L1 opierał się na `id(image)` i nie sprawdzał, czy obiekt PIL został zmieniony lub ponownie użyty. Klucz L2 bazował wyłącznie na hash’u kanału alfa, a cache przechowywał końcowy raster zawierający także RGB wejścia. Dwa rastry o tej samej alfie i różnych kolorach mogły więc zwrócić stary kolor; ponowne użycie zmodyfikowanego obiektu mogło zwrócić poprzednią klatkę.

Błąd odtworzono lokalnie na syntetycznych obrazach czerwonym i zielonym o identycznym alfa: przed poprawką drugie wywołanie zwróciło ten sam obiekt i czerwony piksel zamiast zielonego. Nie był to test eksportu.

Naprawa: klucz efektu waliduje treść kanału alfa przez BLAKE2b-128, a cache przechowuje wyłącznie alfa-zależne warstwy outline/shadow. Każde wywołanie nakłada na nie aktualny raster wejściowy, więc bieżące RGB pozostaje aktualne. Usunięto szybki lookup po `id(image)`. Dodano test regresji obejmujący różne RGB przy tej samej alfie oraz zmianę zawartości tego samego obiektu PIL.

Jest to potwierdzona naprawa poprawności rastra; **nie** potwierdza, że cache był przyczyną regresji FPS. Ponieważ szybki lookup po ID zniknął, koszt weryfikacji alfa i ponownego złożenia obrazu może być wyższy. Zmiana nie wyłącza ani nie ogranicza efektów.

## 5. Profil syntetyczny efektów

Wykonano wyłącznie mały, lokalny mikrobenchmark in-process na sztucznym obrazie RGBA 320×180 z outline 3%, shadow distance 2%, length 1%. To nie jest benchmark AMD Native, nie zawiera wideo/FIT, mapy, layoutu produkcyjnego, AMF, muxu ani pomiaru GPU.

| Ścieżka syntetyczna po poprawce | Mediana | P90 |
|---|---:|---:|
| Nowy raster / zimny cache (50 próbek) | 1.879 ms | 2.128 ms |
| Cache hit, ten sam obraz źródłowy (300 próbek) | 0.390 ms | 0.399 ms |
| Cache hit, zmieniające się RGB przy tej samej alfie (300 próbek) | 0.460 ms | 0.511 ms |

Wyniki opisują tylko pojedynczy sztuczny raster w tej sesji. Nie są podstawą do ekstrapolacji FPS ani potwierdzenia, że efekt jest lub nie jest bottleneckiem na pełnym HUD.

Cache nadal ogranicza się do 128 wpisów bez budżetu bajtowego. Nie zmieniałem tego limitu bez profilu produkcyjnego i pomiaru zużycia pamięci.

## 6. Analiza ścieżek AMD i profilu pipeline

Odczyt źródeł potwierdza, że bieżący resolver production deklaruje domyślne `AMD_CPU_GPU_PIPELINE=SYNC`, `AMD_QUEUE_DEPTH=0`, VP `REFERENCE`, pool 8 i AMF query `REFERENCE`; mapa `GPU`, wykresy `GPU_SPLIT`, gauge `GPU`, lean GPU włączony, `AMD_ABOVE_BATCHED=0`, `AMD_ABOVE_MULTI_RECT=1`, dirty mode `EXACT`, sparse/fine dirty off. Eksporter raportuje wartości effective po inicjalizacji.

To jest inspekcja domyślnej konfiguracji i kodu, nie dowód wartości środowiska podczas rzeczywistego renderu ani dowód, że wszystkie GPU path’y zostały wywołane w tym zadaniu. Bez harnessu i materiałów nie uzyskano profilu producer/consumer, czasu upload/compose, AMF, mux, frame pacing, effective FPS ani direct native FPS. Nie zmieniano flag ani kolejek.

Profil etapów:

| Obszar | Wynik Etapu 4 |
|---|---|
| Producer: widgety, mapa, gauge/compass, efekty, telemetry/cache, ABOVE/BELOW | **NOT MEASURED** na rzeczywistym eksporcie |
| Transfer CPU→GPU, ROI/dirty, RGBA i synchronizacja D3D11 | **NOT MEASURED** |
| Consumer: producer wait, GPU compose, AMF submit/encode, Video Processor, kolejka | **NOT MEASURED** |
| Live Mux / zapis / blokowanie potoku | **NOT MEASURED**; kod nietknięty |
| Walidacja końcowego pliku z Etapu 3 | brak eksportu; koszt steady-state niezmieniony w źródłowym diffie |

## 7. GPU, CPU i RAM

Bieżący przebieg eksportu nie odbył się, więc nie zmierzono GPU Total, 3D, Video Encode, Video Decode, Copy ani Compute; brak średniej, min/max, P50/P90 i przebiegu w czasie. Nie zmierzono też CPU, RAM, temperatury ani limitu mocy.

Nazwy `engtype_3D`, `engtype_Video Codec 0` i `engtype_Video Decode 1` oraz około 99% `Video Codec 0` pochodzą z historycznego raportu dla Ryzen 7 7730U/VCN. Nie są odczytem z bieżącego testu. Wskaźnik „GPU około 80%” zgłoszony przez użytkownika pozostaje nierozstrzygnięty, bo nie wskazuje engine ani okresu pomiaru.

## 8. Testy i parity

- `uv run --no-project --with pytest --with PySide6 pytest -q tests/test_effects_percent_amd_parity.py`: **7 passed** (w tym nowy test cache).
- `py_compile` dla `src/indicators/effects.py` i `tests/test_effects_percent_amd_parity.py`: **PASS**.
- `git diff --check`: **PASS**.
- Syntetyczny test potwierdza świeże RGB i aktualizację obrazu po mutacji źródła. Nie jest porównaniem pełnego obrazu referencyjnego; `max_diff`, MAE i different-pixel count dla preview/render: **NOT TESTED**.
- Preview, final render, jasne tło, kompas NEEDLE/ROSE, mapa, Z-order, ghosting, pełny pixel parity, kolejka producer-consumer, normalne zakończenie i anulowanie: **NOT TESTED** w Etapie 4 z powodu braku canonical harness/assets.
- Raport Etapu 3 dokumentuje historycznie 91 passed dla testów obsługi błędów; tego zestawu nie uruchamiano ponownie w Etapie 4.

## 9. Zakres zmian i izolacja

Zmieniono:

- `src/indicators/effects.py` — bezpieczne kluczowanie alfa-zależnych warstw i świeże nałożenie bieżącego rastra.
- `tests/test_effects_percent_amd_parity.py` — test regresji dla koloru oraz mutowanego obrazu.
- Ten raport.

Nie zmieniano AMD renderer flags, mapy, AMF, dekoderów, QP, kodeków, HDR, audio, Live Mux, AutoFIT, Intel, NVIDIA, export directory ani frameworku błędów. Diff implementacyjny nie dotyka ścieżki audio/Live Mux. Nie wykonano pre-ekstrakcji audio ani nie utworzono cache audio. `def_layout.json` i zastany raport audytu użytkownika pozostały poza commitem.

## 10. Ograniczenia i werdykt

Potwierdzono i naprawiono błąd poprawności cache’u efektów. Nie zidentyfikowano jednak rzeczywistego ograniczenia FPS eksportu, pierwszego commita regresji ani wpływu tej korekty na produkcyjny AMD pipeline. Brak porównywalnych pomiarów A/B, GPU trace, surowych profili i kanonicznego harnessu uniemożliwia stwierdzenie performance pass.

**ETAP 4: PARTIAL / BLOCKED — FPS ROOT CAUSE NOT PROVEN; PERFORMANCE ACCEPTANCE NOT TESTED.** Do zamknięcia diagnozy potrzeba kanonicznego `GX020079.MP4` + `GX020079.fit`, layoutu używanego dla baseline, wymaganego runnera (lub przywrócenia go w repo), oraz known-good profilu/konfiguracji z tym samym sprzętem i workloadem. Wtedy należy zebrać serię liczników GPU Engine i profile BEFORE/AFTER przy ustawieniach `--production-defaults`.

**Pełny hash zweryfikowanego commita kodu/testu:** `70b3a6e19a32c4df0b1eccee4ce958e00afab215`

