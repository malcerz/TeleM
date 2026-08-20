# TeleM — generyczny katalog pól FIT

## Zakres

Wprowadzono kontrakt, w którym dostępność pól FIT jest ustalana na podstawie całej aktywności, a nie pierwszego rekordu ani pojedynczej próbki.

Przepływ danych:

```text
FIT parser
  → FitRecords.available_fit_fields / field_catalog
  → sync_fit_to_video()
  → FitDataset.available_fit_fields / field_catalog
  → registry aktywnych fit_*_text
```

## Implementacja

Zmiany:

- `telemetry_fit.py`
  - dodano `FitRecords`, który skanuje wszystkie rekordy;
  - dodano `FitDataset`, który zachowuje zsynchronizowane próbki i katalog pól;
  - każde pole katalogu zawiera `name`, `source="fit"`, `samples` jako `(timestamp, value)` oraz `occurred`;
  - pola pojawiające się dopiero w dalszej części aktywności są wykrywane;
  - wartości `0` są traktowane jako wystąpienie pola;
  - brak pola przez całą aktywność nie jest rejestrowany jako dostępne.
- `src/gui/telemetry_manager.py`
  - zachowuje `FitDataset` po załadowaniu FIT;
  - udostępnia `TelemetryManager.available_fit_fields`;
  - resetuje katalog przy czyszczeniu/ponownym ładowaniu źródła.

Nie dodano specjalnej listy `battery`, `battery_pct`, `solar_pct` ani żadnych innych nazw pól. Wskaźnik `fit_*_text` jest sprawdzany względem rzeczywistych kluczy datasetu.

## Weryfikacja

Test syntetyczny zawiera pole `late_field` dopiero w drugim rekordzie oraz `developer_field` dopiero w trzecim. Oba pola są wykrywane przez parser/dataset.

```text
pytest -q tests/test_fit_available_fields_catalog.py tests/test_etap8p_b_fast_builder.py
14 passed
```

Realny FIT `Popoludniowa_jazda_na_rowerze_solar_battery.fit`:

```text
FitDataset.available_fit_fields: battery_pct, solar_pct, ...
battery_pct: 1754 próbek
solar_pct:   1754 próbek
source: fit
occurred: True
```

## Wpływ

Zachowano istniejącą kompatybilność: `FitDataset` pozostaje słownikiem `field → list[(timestamp, value)]`. Nie zmieniano semantyki source resolvera, precompute, wykresów, NVENC/NVDEC, workerów ani geometrii atlasu.

Etap zakończony.
