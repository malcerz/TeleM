# TeleM — ETAP 5C — RESULT

## Status

**READ-ONLY VALIDATION / DIAGNOSTIC — zakończony.**

W ETAPIE 5C nie zmodyfikowano kodu, testów, konfiguracji ani `def_layout.json`. Audyt wykonano na rzeczywistym layoutcie, realnym `PropertyEditor`, produkcyjnej ścieżce `compose_overlay()` i rendererach wskaźników. Istniejące zmiany w working tree pochodzą z wcześniejszych etapów.

## A. TEXT — regresja `size/font_size`

Rzeczywisty aktywny `temp_text`:

```text
stored size       = 10.0
stored font_size  = 2.5
GUI Rozmiar       = 2.5
effective source  = font_size
```

Wczytanie nie zmienia geometrii. Sekwencja wykonana przez realny formularz:

| GUI | cfg.size | cfg.font_size | font_px | surface | bbox | x/y |
|---:|---:|---:|---:|---|---|---|
| 2.5 | 2.5 | 2.5 | 14 | 91×14 | 91×14 | 16/267 |
| 2.6 | 2.6 | 2.6 | 14 | 91×14 | 91×14 | 16/267 |
| 2.7 | 2.7 | 2.7 | 15 | 94×15 | 94×15 | 16/267 |
| 2.8 | 2.8 | 2.8 | 15 | 94×15 | 94×15 | 16/267 |
| 2.9 | 2.9 | 2.9 | 16 | 100×16 | 100×16 | 16/267 |
| 3.0 | 3.0 | 3.0 | 16 | 100×16 | 100×16 | 16/267 |

Zmiany są monotoniczne i wynikają wyłącznie z naturalnego zaokrąglania `font_px` do integera.

**LEGACY JUMP FIX VERIFIED.** Stara sekwencja `10.0 → 10.1` nie powoduje już `font_size 2.5 → 10.1`. Legacy event `field=size` nie zmienia canonicalnego fontu.

Pozostałe sprawdzone pola legacy:

| indicator | size | font_size | effective GUI | font_px |
|---|---:|---:|---:|---:|
| temp_text | 10.0 | 2.5 | 2.5 | 14 |
| iso_text | 10.0 | 2.5 | 2.5 | 14 |
| exposure_text | 10.0 | 2.5 | 2.5 | 14 |
| fit_K1_text | 10.0 | 1.8 | 1.8 | 10 |
| fit_K2_text | 10.0 | 1.8 | 1.8 | 10 |
| fit_curVpower_text | 10.0 | 1.8 | 1.8 | 10 |
| fit_enhanced_altitude_text | 10.0 | 1.8 | 1.8 | 10 |
| fit_temperature_text | 2.5 | 2.5 | 2.5 | 14 |
| fit_battery_text | 2.5 | 2.5 | 2.5 | 14 |

## B. GUI / locale / zdarzenia

Realny `PropertyEditor` działał w `pl_PL`:

```text
decimal separator = ,
decimals           = 4
step               = 0.1
keyboardTracking   = True
```

Wpis `2,6000` daje wartość `2.6`. Wpis `10,1000` dla zwykłego kontrolera size z zakresem obejmującym 10.1 daje `10.1`; dla canonicalnego text `font_size` jest prawidłowo odrzucony, bo kontrolka ma zakres `0.5–10.0`.

Każdy programowy krok kontrolki wygenerował dokładnie jedno `valueChanged` i jeden event modelu:

```text
text   → font_size
gauge  → size
chart  → size
bar    → size
map    → size
```

## C. GAUGE

Rzeczywisty aktywny wskaźnik: `fit_enhanced_speed_text`.

```text
form = gauge
size = 12.5
x/y  = 48.65 / 90.56
supersample = 1 (ścieżka preview/diagnostic)
canvas = 960×540
```

| size | surface/bbox | bbox center |
|---:|---|---|
| 5.0 | 64×64 | (467,489) |
| 7.5 | 96×96 | (467,489) |
| 10.0 | 129×129 | (467,489) |
| 10.1 | 132×132 | (467,489) |
| 10.2 | 132×132 | (467,489) |
| 11.0 | 141×141 | (467,489) |
| 12.0 | 156×156 | (467,489) |
| 15.0 | 194×194 | (467,489) |

Kotwica pozostaje stała, a rozmiar rośnie bez skoków regresyjnych.

## D. CHART

Rzeczywisty aktywny wskaźnik: `fit_cadence_text`, `size=30.0`, `x/y=19.93/85.36`.

| size | bbox | center |
|---:|---|---|
| 5.0 | 56×62 | (191,461) |
| 7.5 | 80×62 | (191,461) |
| 10.0 | 104×62 | (191,461) |
| 10.1 | 105×62 | (191,461) |
| 10.2 | 106×62 | (191,461) |
| 11.0 | 114×64 | (191,461) |
| 12.0 | 123×68 | (191,461) |
| 15.0 | 152×79 | (191,461) |

Wzrost szerokości/wysokości jest schodkowy z powodu rasteryzacji tekstu i wykresu, bez wartości ujemnych ani outlierów.

## E. BAR

W bieżącym `def_layout.json` nie ma aktywnego wskaźnika `form=bar`. Dla kontraktu produkcyjnego użyto istniejącego `dist_visual` z `default_layout(3840,2160)`; nie aktywowano go w projekcie.

```text
size = 20.0
x/y = 50.0 / 92.5
thickness = 0.4
```

| size | bbox |
|---:|---|
| 5.0 | 88×54 |
| 7.5 | 112×54 |
| 10.0 | 136×54 |
| 10.1 | 137×54 |
| 10.2 | 138×54 |
| 12.0 | 155×54 |
| 15.0 | 184×54 |

Bar rośnie poziomo, wysokość pozostaje stała zgodnie z rendererem.

## F. MAP / `track_map`

Rzeczywisty aktywny `track_map` ma `size=18.0`, `x/y=88.02/22.31`, `zoom=14`, `map_style=satellite`. Do geometrii użyto realnego tracku z `GX030120.MP4` — 1802 punkty — oraz stałego targetu/markera. Nie zmieniono źródła ani layoutu.

| size | bbox / working size | center | effective zoom |
|---:|---|---|---:|
| 5.0 | 48×48 | (845,120) | 14 |
| 7.5 | 72×72 | (845,120) | 14 |
| 10.0 | 96×96 | (845,120) | 14 |
| 10.1 | 97×97 | (845,120) | 14 |
| 10.2 | 98×98 | (845,120) | 14 |
| 11.0 | 106×106 | (845,120) | 14 |
| 12.0 | 115×115 | (845,120) | 14 |
| 15.0 | 144×144 | (845,120) | 14 |

Center, marker target i geograficzny target pozostają stałe. Zmiana `effective_zoom` przy większym canvasie jest zamierzonym kompensowaniem skali canvasu, a nie zmianą `size`.

## G. Fine sweep / outliers

Sweep `5.0…20.0`, krok `0.1`:

| form | zakres geometry | median Δw/Δh | max Δw/Δh | ujemne Δ | outliers |
|---|---|---|---|---:|---:|
| gauge | 64×64 → 259×259 | 2/2 | 3/3 | 0 | 0 |
| chart | 56×62 → 200×98 | 1/0 | 1/1 | 0 | 0 |
| bar | 88×54 → 232×54 | 1/0 | 1/0 | 0 | 0 |

Text `2.5…3.0` wykazał wyłącznie naturalne przejścia integer `font_px`. Map został sprawdzony punktowo zgodnie z zakresem diagnostycznym etapu.

## H. Powrót do wartości bazowej

Dla wszystkich czterech form geometrycznych oraz `temp_text` wykonano sekwencję zwiększenia rozmiaru i powrotu do wartości początkowej. Bbox, pozycja, anchor/center oraz konfiguracja po powrocie były identyczne z pomiarem początkowym.

```text
return_to_origin = PASS
```

## I. Repeated redraw

Wielokrotny redraw przy niezmienionym `size`, target value/history i track target dawał identyczną geometrię. Nie zaobserwowano kumulatywnego przesunięcia ani wzrostu bbox.

```text
20 repeated redraws = PASS
```

## J. Save/reload

Kopie runtime layoutu zapisane i ponownie odczytane zachowały `size`, `font_size`, pozycje i geometrię dla text, gauge, chart i map.

```text
save/reload geometry parity = True
original def_layout.json modified = False
```

## K. Preview / CPU final / GPU

Preview oraz CPU final korzystają z tego samego `compose_overlay()` i tego samego runtime layoutu. Porównanie bbox po przeskalowaniu do wspólnego układu współrzędnych nie wykazało rozbieżności poza zwykłym błędem zaokrąglenia jednego piksela. Dla mapy różnica zoomu między canvasem preview i final jest zamierzonym mechanizmem utrzymania viewportu geograficznego.

Nie uruchamiano natywnego backendu GPU w tym read-only środowisku; nie ma więc podstaw do twierdzenia o wykonaniu GPU renderu. Nie stwierdzono jednak osobnego kontraktu `size` w ścieżce GPU — layout jest współdzielony.

## L. Potwierdzone problemy

```text
CONFIRMED: SIZE → FONT_SIZE semantic jump dla text — naprawiony w ETAPIE 5B.
CONFIRMED: brak aktywnego bara w bieżącym def_layout.json — nie jest to błąd geometrii.
```

Nie znaleziono nowego problemu `size` dla gauge, chart, bar ani map.

## M. Expected / non-bugs

- schodkowe zmiany bbox wynikające z rasteryzacji są oczekiwane;
- `font_px` jest integerem, więc kilka kolejnych wartości GUI może mieć ten sam bbox;
- `10,1000` jest poza zakresem canonicalnego text `font_size`;
- `effective_zoom` mapy może zależeć od rozmiaru canvasu, aby zachować viewport;
- brak aktywnego baru nie był zmieniany ani uzupełniany w tym etapie.

## N. Testy i rekomendacja

Powiązane testy po audycie:

```text
67 passed
```

Obejmowały m.in. text size compatibility, controller properties, chart, gauge i map sync. Stan pełnej suite po ETAPIE 5B pozostaje:

```text
308 passed, 4 failed, 17 skipped
```

Znane wcześniejsze failure’y: `test_amd_native_etap4.py`, `test_amd_native_etap5b.py`, `test_qp_analyzer.py`, `test_render_tab.py`. Nie były modyfikowane.

### Wynik końcowy

```text
SIZE/GEOMETRY ISSUE CLOSED
LEGACY JUMP FIX VERIFIED
NO NEW SIZE REGRESSION FOUND
```

Rekomendacja: zakończyć ETAP 5C. Centralny refaktor geometrii, migracja presetów i optymalizacja GPU pozostają poza zakresem.
