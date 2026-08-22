# TeleM — ETAP 8G: Bike Lean — offline IMU prototype

Data: 2026-08-22  
Status: eksperyment offline; brak podłączenia do normalnego pipeline'u TeleM.

## Zakres i źródło

Eksperyment używa istniejącego `Video/GX030120.json` oraz istniejących ekstraktorów ACCL/GYRO/GPS. Nie zmieniano resolvera telemetrycznego, `frame_data`, precompute, presetów, GUI, wskaźnika Lean ani rendererów GPU/CPU.

## Osie i jednostki

Metadata GPMF deklaruje kolejność `ZXY`. Obecny ekstraktor wystawia kanoniczne XYZ:

| Kanoniczna oś | Surowa składowa | Rola w eksperymencie |
|---|---|---|
| X | `raw[1]` | najlepszy kandydat osi roll |
| Y | `raw[2]` | składowa grawitacyjna dla roll |
| Z | `raw[0]` | składowa grawitacyjna; spoczynkowo około `-g` |

Dokładna orientacja względem fizycznego roweru/kamery nie wynika z repozytorium i wymaga kalibracji montażu. GYRO ma jednostkę `rad/s` i jest przeliczany na stopnie wyłącznie w diagnostyce. ACCL ma metadata `m/s`, ale normy są zgodne z przyspieszeniem fizycznym w `m/s²`: mediana normy `10.415 m/s²`, przy `g=9.80665 m/s²`. To niespójność metadata, którą trzeba wyjaśnić przed produkcyjnym użyciem.

## Timing IMU

- ACCL: `35 802` próbek.
- GYRO: `35 802` próbek.
- Czas: `180.175 s`.
- Mediana kroku: `0.005033 s`.
- Częstotliwość: około `198.69 Hz` dla obu strumieni.
- GPS użyty wyłącznie jako kontekst: `1 802` próbek.

## Gyro-only

Całkowanie wykonano trapezami na wszystkich trzech osiach, bez sztucznego zerowania biasu. Wyniki końcowe/range:

| Oś | Range [deg] | 30 s | 60 s | koniec |
|---|---:|---:|---:|---:|
| X | `-2.28 … 163.78` | `28.34` | `72.92` | `162.72` |
| Y | `-23.67 … 15.67` | `-1.28` | `-1.13` | `2.28` |
| Z | `-68.81 … 59.54` | `-24.65` | `51.20` | `17.45` |

Wniosek: gyro-only nie jest wystarczający; szczególnie X wykazuje silny dryf całki. Stabilność pozostałych osi nie dowodzi poprawnej orientacji.

## Accelerometer-only i kandydat roll

Sprawdzono trzy proste kandydatury kąta grawitacyjnego na próbkach z `|norm(a)-g|<1 m/s²`:

- X: `atan2(Y, -Z)`, korelacja pochodnej z GYRO X: `+0.514`;
- Y: `atan2(X, -Z)`: `-0.157`;
- Z: `atan2(X, Y)`: `-0.011`.

Najlepszym kandydatem jest więc kanoniczna oś X. Accelerometer-only jest jednak bardzo podatny na przyspieszenia dynamiczne: w prostym oknie `125–140 s` zakres wyniósł około `-67.8 … +117.9°`, więc nie może być bezpośrednim sygnałem Lean.

## Mount offset i filtr

Offset oszacowany eksperymentalnie z fragmentów szybkiej jazdy, małego `|gyro X|` i normy bliskiej `g`: `+0.415°`. Jest to offset obserwacyjny, nie certyfikowana kalibracja fizycznego montażu.

Zastosowano przyczynowy complementary filter:

```text
prediction = previous + gyro_x * dt
angle = prediction + (1 - alpha) * wrapped(accel_angle - mount_offset - prediction)
```

Przetestowane wartości:

| Filtr | Średnie alpha | Dryf w prostym oknie [deg/s] |
|---|---:|---:|
| CF `.95` | `.950` | `-0.0614` |
| CF `.98` | `.980` | `-0.0562` |
| CF `.995` | `.995` | `-0.0322` |
| adaptive CF `.98` | `.9927` | `-0.2176` |

Jako reprezentatywny wybrano stały `alpha=.98` — rozsądny kompromis między tłumieniem dynamicznego ACCL a korekcją dryfu gyro. Odpowiada to w przybliżeniu stałej czasowej `0.25 s` przy kroku `198.69 Hz` (interpretacja dyskretna, nie osobny parametr produkcyjny).

Adaptive norm gate używa confidence `exp(-(abs(norm-g)/1.25)^2)` i zwiększa alpha przy dynamicznym przyspieszeniu. W tym materiale podnosi średnie alpha do `.9927`, ma RMSE `4.08°` względem stałego CF `.98` i gorszy dryf prostego fragmentu. Nie ma podstaw, by wybrać go jako domyślny.

## Sanity check: prosta jazda, zakręty, mała prędkość

Wartości Lean poniżej pochodzą z fixed CF `.98`; GPS heading jest tylko kontekstem i nie wchodzi do fuzji.

| Fragment | Prędkość med. | GPS heading | Peak fused lean |
|---|---:|---:|---:|
| Prosty `125–140 s` | `19.71 km/h` | kontekst nieużywany | `5.81°` abs.; dryf `-0.056°/s` |
| Zakręt 1 `64–72 s` | `20.65 km/h` | `13.84° → 337.46°`, delta `-36.38°` | `-22.74°` |
| Zakręt 2 `145–155 s` | `22.03 km/h` | `351.51° → 14.15°`, delta `+22.64°` | `-13.60°` |
| Low-speed `38–48 s` | `0.50 km/h` | kontekst nieużywany | `12.06°` abs.; dryf `-0.276°/s` |

Zakręty mają przeciwne zmiany headingu i wyraźne zdarzenia IMU, ale brak ground truth Lean. Same dane nie pozwalają jeszcze stwierdzić, czy znak fused angle odpowiada „lewy” lub „prawy” przechył.

## Konwencja znaku

W prototypie dodatni kąt oznacza dodatnią wartość `Y` względem `-Z` w formule `atan2(Y,-Z)`, a dodatnia prędkość gyro X jest zgodna z prawoskrętną konwencją osi. Fizyczne mapowanie tego znaku na lewy/prawy przechył pozostaje **NIEPOTWIERDZONE** do czasu kalibracji montażu lub porównania z referencją wizualną.

## Downsampling i koszt

Rekonstrukcja z 20 Hz względem pełnego przebiegu około 199 Hz dała RMSE `1.18°`, maksymalny błąd `15.91°`. Dla 10 Hz: RMSE `1.47°`, maksimum `18.83°`. Do dalszego prototypowania preferowane jest 20 Hz; 10 Hz traci więcej krótkich transientów.

Pomiar lokalny na tej próbce:

- odczyt JSON i istniejąca ekstrakcja próbek: `~1480 ms`;
- obliczenie kandydatów, całkowania i filtrów: `~340 ms`;
- obliczenie metryk downsample 20/10 Hz: `~1 ms`.

To koszt jednorazowego eksperymentu offline, nie benchmark normalnego renderowania.

## Testy

Uruchomiono:

```text
python -m py_compile scratch/etap8g_lean_imu.py
python -m pytest -q tests/test_etap4d_imu.py tests/test_gpmf_timing.py tests/test_etap8p_b_fast_builder.py::test_fast_builder_imu
9 passed
```

Nie uruchamiano pełnego suite 600+ testów. NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## Zmienione artefakty

- `scratch/etap8g_lean_imu.py` — izolowany skrypt offline, nieimportowany przez runtime;
- `Raporty/ETAP8G_LEAN_IMU_DIAGNOSTIC.png` — wykres diagnostyczny gyro-only / ACCL-only / CF `.98`;
- ten raport.

## Decyzja

**LEAN PROTOTYPE: PROMISING BUT NEEDS CALIBRATION.**

Warto kontynuować eksperyment jako osobny prototyp: oś X i causal CF `.98` dają sensowną bazę, a prosta jazda jest względnie stabilna. Nie wdrażać jeszcze do normalnego pipeline'u ani nie budować widgetu Lean. Przed kolejnym etapem potrzebne są: potwierdzenie jednostki ACCL, kalibracja osi/offsetu i znaku montażu oraz niezależny ground truth kąta przechyłu.

Raport nie wprowadza żadnego production hooka.
