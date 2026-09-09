# TELEM - display precision interpolation

**Data:** 2026-09-09  
**Branch:** `integration/intel-amd`  
**Zakres:** presentation-time interpolation for quantized continuous values.

## Cel i ograniczenia

Dodano wspolny, backend-neutralny kontrakt dla wartosci ciaglych. Nie zmieniano
parsera FIT/GPMF, surowych tablic probek, payloadu cache, Lean mathematics,
compositor/HUD ani backendow. Nie wykonano reset/clean/rebase, commit ani push.

## Implementacja

`src/telemetry_resolver.py` definiuje:

- `CONTINUOUS_PRESENTATION_FIELDS` (battery, battery voltage, temperature,
  speed, altitude, distance, power i analogiczne aliasy),
- `DISCRETE_PRESENTATION_FIELDS` (ISO, SHUT/exposure, status, mode, fix, ID,
  boolean, enum),
- `interpolation_policy()` z trybami `auto`, `step`, `linear`,
- `interpolate_presentation_value()`.

Lookup uzywa `bisect_right` oraz cache'u timestampow, czyli O(log N) na klatke
po jednorazowym przygotowaniu osi czasu. Funkcja zwraca `None` przed pierwsza
proba, wykonuje previous/step hold w trybie dyskretnym, zachowuje last-value
hold po ostatniej probie, a liniowa interpolacje dopuszcza tylko dla normalnej
luki (mediana interwalu * 5). Surowa lista probek nie jest modyfikowana.

W `TelemetryDataManager.resolve_value()` i
`ffmpeg.worker_cache._resolve_cache_value()` przekazywane sa ta sama wartosc
`precision`/`interpolation_policy`; Preview i Final korzystaja z identycznej
funkcji. Dotychczasowe kontrakty speed/distance/altitude pozostaja bez zmian.

## Continuous vs discrete

`AUTO` interpoluje tylko wtedy, gdy zadana liczba miejsc jest wieksza od
obserwowanej rozdzielczosci zrodla. Dla stalego 96 -> 96 wynik pozostaje 96.0;
odcinek 96 -> 95 jest liniowy dopiero na prezentacji z wieksza precyzja.
ISO/SHUT nie sa interpolowane (100 -> 200 nigdy nie daje 137.4).

## Rzeczywisty Battery FIT

Fresh `parse_fit()` wykonany dla:

`D:\\GoPro\\2026-09-02\\Poranna_jazda_na_rowerze.fit`

Pole `garmin_battery_percent`: 27 probek, first
`2026-09-02T04:22:27 = 96.0`, last
`2026-09-02T04:55:57 = 94.0`. Na odcinku
`04:34:57 = 96.0` -> `04:35:57 = 95.0`, midpoint `04:35:27` daje:

| precision | wynik |
|---:|---:|
| 0 | 96.0 (step) |
| 1 | 95.5 |
| 2 | 95.5 |

Pole `garmin_battery_voltage` ma natywne 3 miejsca (`4.225 -> 4.221`), wiec
precision 2 zachowuje step, a precision 4 wlacza interpolacje. To jest
automatyczna detekcja rozdzielczosci, a nie wyjatek dla konkretnego pliku.

## Raw vs presentation

Wejscie pozostaje np. `[(t0, 96), (t1, 95)]`; nie sa tworzone ani zapisywane
sztuczne probki FIT/GPMF. Interpolowany float istnieje tylko jako wartosc
prezentacyjna przy pobraniu current value.

## BAR / GAUGE / TEXT

Compositor przekazuje `formatted_val` tylko do tekstu. Ruler/segment marker i
gauge obliczaja pozycje z niezaokraglonego `value` (`marker_x`/`marker_y`), wiec
np. `95.437284` moze ustawic marker dokladniej niz napis `95.4%`. Test wywolania
BAR z floatem i zaokraglonym tekstem przechodzi.

## Luki i multi-file

Przerwa wieksza niz 5 medianowych interwalow nie jest rampowana: resolver
trzyma lewa, rzeczywista probe do nastepnej probki. Ten sam mechanizm blokuje
falszywa rampe przez granice klipow/wyciete fragmenty, gdy ich timeline ma
rzeczywista luke. Nie tworzy sie dodatkowa seria interpolowana.

## Preview / Final parity

Test managera i worker cache inicjalizuje identyczne probki Battery oraz ten
sam layout (`decimals=2`); oba wyniki dla midpointu sa `95.5`. Sciezki
Preview i Final wywolujace te resolvery maja wspolny interpolator. Pelny realny
render produkcyjny nie byl potrzebny do weryfikacji kontraktu i nie zostal
uruchomiony w tym zadaniu.

## Zmienione pliki

- `src/telemetry_resolver.py` - policy, detekcja rozdzielczosci, gap gate,
  binarne lookup/interpolacja.
- `src/gui/telemetry_manager.py` - precision/policy do Preview resolvera.
- `src/ffmpeg/worker_cache.py` - identyczna obsluga w Final workerze.
- `tests/test_display_precision_interpolation.py` - testy Battery, voltage,
  speed/gap, multi-file-like gap, ISO, raw immutability, BAR contract i
  Preview/Final parity.

## Testy

```text
python -m pytest -q tests/test_display_precision_interpolation.py
7 passed

python -m pytest -q tests/test_display_precision_interpolation.py \
  tests/test_gpmf_stream_first_sample_availability.py \
  tests/test_tmpc_native_and_cache.py tests/test_multifile_timeline.py \
  tests/test_telemetry_processed_cache.py \
  -k "cache or timeline or native or first_sample or display_precision or battery or interpolation"
50 passed, 4 skipped

python -m py_compile src/telemetry_resolver.py src/gui/telemetry_manager.py \
  src/ffmpeg/worker_cache.py tests/test_display_precision_interpolation.py
git diff --check
modified task files clean (repository also contains pre-existing whitespace
findings in unrelated dirty files)
```

## Acceptance

```text
RAW TELEMETRY UNCHANGED: PASS
BATTERY INTEGER SOURCE + 1DP SMOOTH: PASS
BATTERY INTEGER SOURCE + 2DP SMOOTH: PASS
BAR MARKER USES FULL FLOAT: PASS
TEXT USES SELECTED PRECISION: PASS
DISCRETE ISO REMAINS STEP: PASS
NO INTERPOLATION ACROSS GAPS: PASS
NO CROSS-CLIP FALSE RAMP: PASS (gap-gated contract)
PREVIEW/FINAL PARITY: PASS (manager/worker resolver test)
NO BACKEND REGRESSION: PASS by scope (backend-neutral Python path; no backend files changed by this task)
```

**STATUS: READY for display-precision interpolation.** Full production GUI
render and long-run performance benchmark: **NOT TESTED** (not required to
change the resolver contract).
