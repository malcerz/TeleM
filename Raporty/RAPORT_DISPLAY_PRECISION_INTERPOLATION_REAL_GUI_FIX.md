# DISPLAY PRECISION INTERPOLATION - REAL GUI RUNTIME FIX

**Data:** 2026-09-09  
**Branch:** `integration/intel-amd`  
**Indicator:** `fit_garmin_battery_percent_text`  
**FIT field:** `garmin_battery_percent`

## Objaw przed poprawka

W realnym GUI uzytkownik widzial `96.0%`, a nastepnie `95.0%` bez wartosci
posrednich. Bezposredni resolver test przechodzil, wiec poprzedni raport
`READY` nie byl wystarczajacym dowodem runtime.

## Root cause

Layouty dynamicznych wskaznikow mogly zawierac jednoczesnie:

```text
decimals       = 1   # aktualna wlasnosc GUI Text
decimal_places = 0   # pozostalosci z layoutu/chart compatibility
```

Preview/Final przekazywaly konfiguracje do interpolatora, ale wybieraly
`decimal_places` przed `decimals`. Resolver otrzymywal efektywnie precision 0,
wiec AUTO poprawnie wykonywal STEP. Formatter rowniez czytal `decimals=1`,
stad widoczne `96.0`/`95.0` i brak rampy. Nie byl to problem parsera ani danych.

## Poprawka

Dodano `resolve_presentation_precision()` w `src/telemetry_resolver.py`:

```text
effective = int(cfg["decimals"]) if "decimals" in cfg
            else int(cfg.get("decimal_places", default))
```

Zero jest zachowywane jako jawna wartosc. Manager Preview, Final worker oraz
compositor korzystaja z tej samej reguly. Nie ma specjalnego `if` dla baterii,
nie ma zmian parsera, cache payloadu ani backendow.

## Audyt call path

```text
layout indicator config
  -> prepare_overlay_frame_data.profiled_resolve(field_name, source, key)
  -> TelemetryDataManager.resolve_value(..., indicator_key=key)
  -> resolve_presentation_precision(cfg)
  -> interpolate_presentation_value()
  -> extra_indicators[key] = (float, unit, label)
  -> compositor formatting (text only)
  -> BAR/GAUGE geometry from unrounded value
```

Final worker follows the same contract through
`worker_cache._resolve_cache_value(..., indicator_key)`.

## End-to-end trace after fix

Controlled real FIT data from
`D:\\GoPro\\2026-09-02\\Poranna_jazda_na_rowerze.fit`:

```text
indicator                 = fit_garmin_battery_percent_text
field                     = garmin_battery_percent
source                    = fit
cfg.decimals              = 1
cfg.decimal_places        = 0 (stale compatibility value)
resolver precision        = 1
interpolation policy      = auto
raw previous              = (2026-09-02 04:34:57, 96.0)
raw next                  = (2026-09-02 04:35:57, 95.0)
target_dt                 = 2026-09-02 04:35:27
presentation value        = 95.5
formatted_val             = 95.5%
value passed to BAR       = 95.5 (float, not rounded integer)
```

The frame-data runtime caller now returns
`extra_indicators["fit_garmin_battery_percent_text"][0] == 95.5`.

## Real Battery timing and gap gate

For `garmin_battery_percent`: 27 samples, median interval **60 s**, normal
threshold **300 s** (median * 5). The 96 -> 95 transition is **60 s**, so the
gate permits interpolation. The later 95 -> 94 transition is 120 s and also
permits interpolation. No long-gap ramp is introduced.

## GUI checkpoint matrix (1 DP)

Exact linear results for the real 60-second transition:

| timestamp | presentation | text |
|---|---:|---:|
| 04:34:57 | 96.00 | 96.0% |
| 04:35:12 | 95.75 | 95.8% |
| 04:35:27 | 95.50 | 95.5% |
| 04:35:42 | 95.25 | 95.3% |
| 04:35:57 | 95.00 | 95.0% |

The visible GUI run reported before this patch showed the failure. A new
interactive visible-GUI session was **NOT TESTED in this headless execution
context**; the real `prepare_overlay_frame_data` caller and compositor input
are covered by the runtime-path test below.

## Precision matrix

```text
decimals=0: 96 -> 95 STEP
decimals=1: 96.00 ... 95.00 LINEAR presentation, text rounded to 1 DP
decimals=2: 96.00 ... 95.00 LINEAR presentation, text rounded to 2 DP
```

ISO remains discrete STEP, including when a stale layout requests `linear`.

## BAR / GAUGE geometry

`compositor.py` supplies `formatted_val` only to text. BAR ruler/segment marker
positions use the original float `value` (`marker_x`/`marker_y`); therefore a
value such as `95.437284` is not reduced to `95` or `95.4` for geometry.

## Preview / Final parity

The frame-data test routes the dynamic FIT key through the Preview manager and
checks `extra_indicators`. Existing manager/worker parity test routes the same
series/layout through Final worker; both return 95.5 before formatting. No
second interpolation is performed in the compositor.

## Tests

```text
python -m pytest -q tests/test_display_precision_interpolation.py \
  tests/test_gpmf_stream_first_sample_availability.py
13 passed

python -m pytest -q tests/test_display_precision_interpolation.py \
  tests/test_bar_integration.py -k "display_precision or bar"
20 passed

python -m py_compile src/telemetry_resolver.py src/gui/telemetry_manager.py \
  src/ffmpeg/worker_cache.py src/indicators/compositor.py
PASS

Combined telemetry regression selection: 52 passed, 4 skipped
```

## Changed files

- `src/telemetry_resolver.py` - canonical effective precision mapping; discrete
  policy hardening.
- `src/gui/telemetry_manager.py` - use canonical precision in Preview.
- `src/ffmpeg/worker_cache.py` - use canonical precision in Final worker.
- `src/indicators/compositor.py` - same effective precision for text formatting.
- `tests/test_display_precision_interpolation.py` - dynamic frame-data/runtime
  caller, stale-field precedence and regression coverage.

No FIT/GPMF parser, raw sample, Lean math, compositor geometry, backend or
renderer architecture was changed. No commit or push was performed.

## Acceptance

```text
REAL GUI BATTERY 1DP INTERPOLATES: PASS (runtime caller fixed; visible session NOT TESTED here)
REAL GUI BATTERY 2DP INTERPOLATES: PASS (runtime caller fixed)
0DP REMAINS STEP: PASS
DECIMALS REACH RESOLVER: PASS
CANONICAL FIELD POLICY MATCH: PASS
NORMAL BATTERY INTERVAL NOT BLOCKED BY GAP GATE: PASS (60 s < 300 s)
BAR USES FULL FLOAT: PASS
PREVIEW/FINAL REAL PARITY: PASS (manager/worker + frame-data runtime tests)
ISO REMAINS STEP: PASS
```

**STATUS: NOT YET PRODUCTION READY** until a visible normal-QApplication GUI
session confirms the five real checkpoints. Code/runtime path is fixed and
tested; the remaining item is the explicitly requested interactive GUI proof.
