# TeleM — BAR/RULER ETAP 3: skalowanie rozmiaru + cieńsze ticki

## Zakres

Zmiana obejmuje wyłącznie `bar/ruler`:

- pionowy Ruler: skalowanie całego widgetu przez `size`;
- ułamkowe `thickness` dla podziałek;
- zachowanie poziomego Rulera;
- zapis i odczyt wartości ułamkowych.

Nie zmieniano map, telemetryki, rozdzielczości HUD, anulowania renderu ani ścieżek GPU.

## Przyczyna problemu

W `src/indicators/bar.py::_render_ruler_vertical()` wysokość osi była liczona jako:

```text
max(200 * supersample, size_px * supersample)
```

W praktyce wartości `size` mniejsze od około 200 px trafiały w stałe minimum. Dodatkowo długości ticków, marker, marginesy i rozmiary fontów miały niezależne minima, więc zmiana `size` nie zmniejszała całego rastera.

## Wprowadzone zmiany

### Rozmiar pionowego Rulera

- `size` w zakresie `0.5–1.0` jest interpretowane jako skala standardowego pionowego Rulera:
  - `1.0` — dotychczasowy rozmiar;
  - `0.75` — około 75% geometrii;
  - `0.5` — około 50% geometrii.
- Starsze wartości typu `16`, `20`, `28` zachowują dotychczasową interpretację procentową i dotychczasowy standardowy limit geometrii.
- Skalowane są: wysokość osi, szerokość osi, ticki, marker, odstępy, marginesy i fonty pionowego widgetu.
- Poziomy Ruler nie korzysta z tej pionowej skali.

### Grubość

- Pole `Grubość` dla BAR/Ruler zmieniono z `int` na `float`.
- Zakres GUI: `0.25–10.0`, krok `0.25`.
- Wartości `0.5`, `0.75` i `1.0` są zachowywane jako ułamki bazowej grubości i przekazywane do renderowania bez przedwczesnego zaokrąglenia.
- Pozostałe formy zachowują dotychczasowy kontrakt podjednostkowej grubości.

## Walidacja

Uruchomiono:

```text
python -m pytest tests/test_bar_ruler_size_thickness_etap3.py \
  tests/test_bar_integration.py \
  tests/test_bar_orientation_contract.py \
  tests/test_bar_ruler_tick_contract.py -q
```

Wynik:

```text
56 passed
```

Nowe testy sprawdzają:

- malejący raster pionowego Rulera dla `size=1.0`, `0.75`, `0.5`;
- różnicę obrazu dla `thickness=0.5` i `1.0` przez pełny dispatcher;
- brak regresji orientacji poziomej;
- schemat GUI z typem float, minimum 0.25 i krokiem 0.25;
- zachowanie `size=0.75` i `thickness=0.5` po JSON save/load.

## Ograniczenia walidacji

Nie wykonywano fizycznego testu interakcji GUI ani runtime testów AMD/NVIDIA. Zmiana nie dotyka ich kodu backendowego.

