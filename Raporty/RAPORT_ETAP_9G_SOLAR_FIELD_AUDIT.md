# ETAP 9G — audyt dokładnej nazwy pola Solar

## Wynik główny

**EXACT SOLAR FIELD NAME: `solar_pct`**

Wymagane wyszukiwanie case-insensitive wykazało:

```text
solar_prc: NIE ZNALEZIONO
solar_pct: ZNALEZIONO
```

FIT status:

```text
FOUND: solar_pct
```

Nie znaleziono `solar_prc` w `src`, `presets`, `tests`, opisach pól FIT, resolverze, cache ani nazwach parsed telemetry. Repozytorium zawiera wiele wcześniejszych odwołań do `solar_pct`; nie znaleziono kodu, który definiowałby alias `solar_prc`.

## Nowy FIT

Plik: `Video/Jazda_na_rowerze_w_porze_lunchu.fit`

Pole `solar_pct`:

- developer data index: `2`;
- record field number: `0`;
- base type: `uint8`;
- units: `%`;
- scale: brak dodatkowego scale w definicji FIT (`1`);
- offset: brak (`0`);
- samples: `2340`;
- wartości: `0..100`;
- pierwsze próbki: `2, 2, 3, 4, 4, 5, 5, 5, 5, 5`.

## Ważne rozróżnienie

FIT zawiera również osobne pole `solar`:

- developer data index: `3`;
- record field number: `0`;
- base type: `uint8`;
- units: `%`;
- samples: `4299`;
- wartości: `0..100`.

`solar` i `solar_pct` nie są traktowane jako to samo pole: mają różne developer data index, różną liczbę próbek i różne przebiegi. Nie wprowadzono aliasu ani automatycznej zamiany.

## Źródło prawdy w kodzie

`telemetry_fit.py` nie tworzy specjalnej nazwy Solar — zachowuje nazwy odczytane z FIT i przekazuje je do `FitDataset.available_fit_fields` oraz `field_catalog`. Wcześniejsze definicje katalogu FIT również wskazują `solar_pct`, nie `solar_prc`.

## Zakres zmian

Ten audyt nie zmieniał parsera, resolvera, cache, presetów ani semantyki Solar. Do dalszej integracji należy używać bezpośrednio `solar_pct`, jeśli celem jest procent Solar. `solar` pozostaje odrębnym polem i wymaga osobnej decyzji semantycznej.
