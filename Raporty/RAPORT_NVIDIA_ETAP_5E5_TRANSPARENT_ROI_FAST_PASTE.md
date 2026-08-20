# TeleM — NVIDIA ETAP 5E.5: Pixel-Exact Transparent ROI Fast Paste

Status: audyt zakończony, fast path nie został zaakceptowany dla rzeczywistych rasterów cadence/HR.

## A. Zakres

Zbadano wyłącznie końcowy transfer gotowego lokalnego RGBA chartu do atlasu. Nie zmieniano rendererów wykresów, semantyki prefixu, `None`/`0`, rozcinania luk, gauge, Direct-Region jako architektury ani ustawień NVIDIA.

## B. Baseline

Referencyjny stan ETAPU 5E.4:

- `FRAME_PIPELINE`: 228.1 FPS mediany
- `REAL_EXPORT`: 213.9 FPS mediany
- lokalny render: cadence około 0.752 ms, HR około 0.878 ms
- pełny koszt render + transfer: cadence około 1.923 ms, HR około 2.014 ms

Nie wykonano nowych eksportów produkcyjnych, ponieważ test pixel-parity odrzucił plain paste dla realnych chartów.

## C. Call graph i aktualna decyzja compositora

Aktualna ścieżka NVIDIA jest następująca:

`fresh atlas RGBA → compose_overlay(target_image) → render_value_indicator → rotated_paste → composite_final`

Rzeczywisty chart ma `584×264`. `composite_final()` widzi alpha-bbox mniejszy od pełnego prostokąta, ale obejmujący około 85.4–85.7% powierzchni. Ponieważ alpha zawiera również zera, obecna bezpieczna decyzja kończy się na `alpha_composite()`.

Nie użyto `paste(source, xy, source)`, ponieważ maskowane paste zmienia semantykę pikseli półprzezroczystych.

## D. Geometria ROI

Dla aktualnego layoutu planner wyznacza rozłączne prostokąty:

- cadence: `x=92..676`, `y=796..1060`
- speed gauge: `x=766..1090`, `y=814..1138`
- heart rate: `x=1244..1828`, `y=796..1060`

Cadence, gauge i HR nie nachodzą prostokątami. Fast path otrzymał jawny sygnał `destination_proven_empty` tylko dla świeżo zaalokowanego atlasu i tylko dla wskaźników `form="chart"`. Geometria poprzednich widgetów jest przeliczana do lokalnego układu atlasu; przy jakimkolwiek przecięciu następuje konserwatywny fallback.

## E. Pixel parity

Porównano dla 96 rzeczywistych rasterów każdego chartu:

- A: transparentny ROI + `alpha_composite(source)`
- B: transparentny ROI + plain `paste(source)`

Wynik dla cadence i HR, dla rotacji 0°, 90°, 180° i 270°:

- cadence: `max_diff=9`, `different_pixels=54`
- HR: `max_diff=9`, `different_pixels=53`

Źródłem różnicy jest RGB pod pikselami `alpha=0`:

- cadence: 54 piksele z niezerowym RGB, maksimum 9
- HR: 53 piksele z niezerowym RGB, maksimum 9

To nie jest różnica wizualna po kompozycji na typowym tle, ale jest to rzeczywista różnica RGBA i nie spełnia wymaganego `max_diff=0`, `different_pixels=0`.

Test kontrolny z czystym transparentnym rasterem przechodzi pixel-exact. Nie jest jednak dowodem dla aktualnych chartów produkcyjnych.

## F. Minimalna poprawka

Dodano wyłącznie bezpieczny mechanizm warunkowy:

- `destination_proven_empty` przekazywany przez świeży Direct-Region atlas;
- szybki plain paste wymaga braku przecięcia prostokątów, pełnego zamknięcia ROI w atlasie oraz cache’owanego dowodu czystej transparentności źródła;
- dowód transparentności jest sprawdzany najwyżej raz dla `(cache_key, width, height)`, nie per frame;
- realne rastry cadence/HR nie przechodzą dowodu i pozostają na `alpha_composite`;
- gauge nie został objęty fast path;
- nie zmieniono rendererów chartów ani ich danych.

W efekcie poprawka jest bezpieczna, ale dla aktualnego materiału nie aktywuje plain paste. Nie wdrożono obejścia polegającego na czyszczeniu RGB pod alpha=0, ponieważ wymagałoby to dodatkowego przetwarzania gotowego rastra i osobnej walidacji kolejnego etapu.

## G. Testy regresyjne

Dodano `tests/test_etap5e5_transparent_roi.py`, obejmujący:

- pusty transparentny ROI i semitransparent source;
- wymuszenie fallbacku przy overlapie prostokątów;
- overlap prostokąta mimo braku widocznych pikseli poprzedniego widgetu;
- dirty RGB pod `alpha=0`;
- rotacje 0°, 90°, 180°, 270°.

Wynik testów zakresu chart/ROI: `21 passed`.

Pełny lokalny suite: `547 passed, 23 skipped, 3 failed`. Trzy błędy są niezwiązane z tym etapem: brak DLL `native/…/telem_amd_native.dll` w testach AMD smoke oraz test fallbacku encodera wykrywający środowisko NVIDIA zamiast AMD.

## H. Benchmark transferu — 2000 powtórzeń

Wartości w ms; każdy test używał rzeczywistych rasterów chartu.

| Chart | A current `rotated_paste` avg/med/p95 | guarded path avg/med/p95 | B full plain paste avg/med/p95 | C cropped plain paste avg/med/p95 | D alpha reference avg/med/p95 |
|---|---:|---:|---:|---:|---:|
| cadence | 0.363 / 0.358 / 0.455 | 0.344 / 0.332 / 0.445 | 0.053 / 0.038 / 0.097 | 0.093 / 0.068 / 0.161 | 0.326 / 0.321 / 0.423 |
| HR | 0.297 / 0.288 / 0.366 | 0.274 / 0.258 / 0.353 | 0.045 / 0.032 / 0.081 | 0.094 / 0.071 / 0.163 | 0.260 / 0.245 / 0.339 |

Wartości `B` są wyłącznie teoretycznym kosztem niedopuszczonej ścieżki. `guarded path` dla realnych chartów odrzuca plain paste i wraca do bezpiecznego compositingu, dlatego nie jest zaakceptowaną optymalizacją produkcyjną.

## I. Profil workera po zmianie

Dla 300 klatek rzeczywistego materiału, bez eksportu FFmpeg:

- compose z chartami: średnio 7.125 ms, mediana 7.088 ms, p95 8.219 ms
- cadence total: średnio 1.566 ms, mediana 1.578 ms, p95 1.900 ms
- HR total: średnio 1.850 ms, mediana 1.828 ms, p95 2.112 ms
- cadence graph background/chart composite: średnio 0.606 ms
- HR graph background/chart composite: średnio 0.589 ms

Największym hotspotem pozostaje render chartów, nie bezpieczny transfer ROI. W szczególności większy koszt całkowity ma HR chart.

## J. Benchmark produkcyjny

Nie wykonano 3 nowych eksportów. Zgodnie z kontraktem benchmark produkcyjny uruchamia się po zaakceptowaniu wdrożenia; tutaj warunek pixel-parity nie został spełniony.

Ostatni porównywalny baseline pozostaje:

- `FRAME_PIPELINE`: 228.1 FPS
- `REAL_EXPORT`: 213.9 FPS
- HUD producer: Direct-Region / Multi-Region Atlas

## K. Ocena kryteriów wdrożenia

- pixel parity realnych chartów: niezaliczony;
- `max_diff=0`: nie;
- `different_pixels=0`: nie;
- transfer gain plain paste: uzyskany tylko dla sztucznie czystego źródła, nie dla aktualnego rastra;
- transfer ≤0.4 ms/chart: osiągalny tylko przez niedopuszczony plain paste; realny fallback pozostaje na alpha compositing;
- regresja chartów: brak w zakresie tego etapu;
- Direct-Region: pozostaje aktywny.

## L. Zmienione pliki

Zmiany tego etapu dotyczą:

- `src/indicators/rotated_paste.py`
- `src/indicators/compositor.py`
- `src/ffmpeg/frame_renderer.py`
- `tests/test_etap5e5_transparent_roi.py`

Audyt i walidacja:

- `scratch/audit_etap5e5_transparent_roi.py`
- `scratch/validate_etap5e5_atlas_fast.py`

## M. Odpowiedzi końcowe

1. Fast path został zrealizowany jako warunkowy plain paste na świeży, transparentny ROI z geometrycznym sprawdzeniem overlapu i cache’owanym sprawdzeniem czystości źródła.
2. Dla aktualnych chartów przyszła ścieżka plain paste nie jest aktywowana, ponieważ źródło nie spełnia pixel-parity. Nie zaakceptowano żadnego wariantu mogącego zmienić RGBA.
3. `cadence=0` pozostało bez zmian; ten etap nie dotyka danych chartu.
4. Rozcinanie luk FIT pozostało bez zmian.
5. Nie ma zaakceptowanego kosztu „po” dla produkcyjnego fast path. Teoretyczny plain paste to około 0.053 ms cadence i 0.045 ms HR, ale jest odrzucony dla realnych rasterów. Bezpieczny fallback pozostaje w zakresie około 0.3 ms transferu w tym mikrobenchmarku.
6. Nowego `FRAME_PIPELINE` FPS nie raportuję, ponieważ nie wdrożono zmiany produkcyjnej i nie wykonano eksportów. Obowiązuje baseline 228.1 FPS.
7. Największym hotspotem pozostaje render chartów: HR około 1.850 ms/frame, cadence około 1.566 ms/frame; transfer ROI nie jest obecnie głównym ograniczeniem.
8. ETAP 5E.5 zostaje zatrzymany. Nie przechodzę do kolejnej optymalizacji.
