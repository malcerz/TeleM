# TeleM — ETAP 6B — RESULT

## Status

**IMPLEMENTATION + REGRESSION TESTS — zakończony.** Zakres ograniczono do trzech problemów potwierdzonych w ETAPIE 6A:

1. silent `FIT/GPX → GPMF` fallback w PRECOMPUTED;
2. przedwczesne `None → 0.0`;
3. stale dynamic FIT availability.

Nie dodano GPS DOP/Fix, GPX battery, nowych pól telemetrycznych ani zmian interpolation/smoothing/speed policy.

## A. Root causes

### PRECOMPUTED fallback

`src/telemetry_precompute.py` używał `fit_samples or gpmf_samples` i `gpx_samples or gpmf_samples` dla speed/alt/track. Przy pustym żądanym źródle PRECOMPUTED zwracał wartość z GPMF.

### `None → 0`

`compositor.py`, `frame_data.py` i `telemetry_precompute.py` zamieniały brak danych na `0.0`, przez co brak pomiaru był nieodróżnialny od prawdziwego zera.

### Dynamic FIT availability

Plan aktywnych FIT fields traktował każdy włączony `fit_*_text` z layoutu jako dostępny, niezależnie od bieżącego `fit_data`. Layout zachowuje konfigurację użytkownika, ale runtime availability musi być wyliczana z aktualnego pliku.

## B. Implementation

Zmodyfikowane pliki:

- `src/telemetry_precompute.py`
  - strict source selection dla speed/alt/track;
  - puste źródło daje `None`;
  - dynamic FIT missing pozostaje `None`;
  - source-aware wybór `speed_text/dist_text/alt_text` również wtedy, gdy brak wariantu `_visual`.
- `src/indicators/frame_data.py`
  - brak próbek nie jest interpolowany do zera;
  - dynamic FIT active fields są filtrowane przez `discovered_fit_fields`;
  - configured-but-missing fields pozostają w runtime jako `(None, unit, label)`;
  - `None` jest zachowane dla dynamicznych pól i IMU.
- `src/indicators/compositor.py`
  - standardowe pola nie konwertują `None` na `0.0`;
  - wskaźnik z wartością `None` jest pomijany jako unavailable/hidden;
  - prawdziwe `0.0` nadal jest renderowane.
- `src/gui/telemetry_manager.py`
  - nowe FIT ładowanie czyści poprzednie `fit_data`, track i dynamic fields przed parse/alignment.
- `src/gui/qt/_mixins/project_mixin.py`
  - `fit_ext_fields` jest czyszczone przy zmianie pliku przed ponowną rejestracją.
- `src/gui/qt/_mixins/preset_mixin.py`
  - analogiczne czyszczenie dynamicznej listy przy reloadzie presetu.
- `tests/test_etap6b_contract.py`
  - nowe regresje source/None/zero/precompute/worker/chart/availability.
- `tests/test_amd_native_etap5b.py`
  - aktualizacja oczekiwanego kontraktu missing dynamic FIT: `None`, nie `0.0`.

Nie usuwano wpisów z layoutu użytkownika.

## C. Source contract

| requested source | używane dane | brak danych |
|---|---|---|
| GPMF | wyłącznie GPMF | `None` / empty history |
| FIT | wyłącznie FIT | `None` / empty history |
| GPX | wyłącznie GPX | `None` / empty history |
| unsupported | brak resolvera | `None` / empty history |

Shared resolver, manager, chart builder, frame data, worker resolver i PRECOMPUTED używają teraz tej samej semantyki source ownership.

## D. Missing-data contract

```text
missing sample = None
real sensor/FIT zero = 0.0
presentation None = unavailable/hidden
presentation 0.0 = real displayed zero
```

Renderer nie otrzymuje już syntetycznego zera dla niedostępnych standardowych, dynamicznych FIT ani IMU fields. Zamiast tego pomija skonfigurowany wskaźnik; konfiguracja pozostaje w layoucie.

## E. PRECOMPUTED fix — BEFORE / AFTER

Diagnostyczny przypadek:

```text
GPMF speed = 10.0
FIT speed = empty
indicator source = FIT
```

| path | BEFORE | AFTER |
|---|---:|---:|
| manager resolver | `None` | `None` |
| frame_data | `0.0` presentation fallback | `None` |
| chart | empty | empty |
| precompute | `10.0` from GPMF | `None` |
| worker resolver | `None` | `None` |
| presentation | `0` possible | unavailable/hidden |

Analogiczny test dla pustego GPX również zwraca `None`, nigdy GPMF.

## F. Frame-data fix — BEFORE / AFTER

| field | missing BEFORE | missing AFTER | real zero AFTER |
|---|---:|---:|---:|
| ISO | `0.0` | `None` | `0` |
| SHUT | `0.0` | `None` | `0` |
| camera temperature | `0.0` | `None` | `0.0` |
| HR | `0.0` | `None` | `0.0` |
| cadence | `0.0` | `None` | `0.0` |
| power | `0.0` | `None` | `0.0` |
| battery | `0.0` | `None` | `0.0` |
| dynamic FIT | `0.0` | `None` | source value |
| ACCL/GYRO | `0.0` | `None` | source value |

## G. Dynamic FIT availability

Availability wynika teraz z bieżącego zbioru `fit_data`:

| state | `fit_K1_text` configured | current FIT | runtime available | value |
|---|---:|---:|---:|---:|
| field present | yes | `K1` present | yes | sample value |
| field absent | yes | `K1` absent | no | `None`, hidden |
| A → B | yes | A has K1, B lacks K1 | no after B | `None` |
| B → A | yes | next file has K1 | yes after reload | sample value |

`build_active_fit_field_plan()` keeps `fit_K1_text` in the layout but includes it in active runtime fields only when `K1` exists in current FIT data. No preset entry is deleted.

## H. Current/history parity

| field family | current source | history source | precompute | worker | result |
|---|---|---|---|---|---|
| speed | configured GPMF/FIT/GPX | same | same | same | PASS |
| altitude | configured GPMF/FIT/GPX | same | same | same | PASS |
| track | configured GPMF/FIT/GPX | same | same | same | PASS |
| HR/cadence/power | configured FIT/GPX | same | same | same | PASS |
| dynamic FIT | current FIT only | same/empty | same/empty | same resolver | PASS |
| accel_x | GPMF only | GPMF/empty | no fallback | GPMF/empty | PASS |

For empty requested sources, both current and history are unavailable/empty. There is no current `None` + history GPMF combination in the tested paths.

## I. Preview / worker / final parity

| case | manager | preview frame data | PRECOMPUTED | worker/final |
|---|---|---|---|---|
| populated GPMF speed | source value | same | same | same |
| FIT speed selected, FIT populated | FIT value | FIT value | FIT value | FIT value |
| FIT selected, FIT empty | `None` | `None` | `None` | `None` |
| GPX selected, GPX empty | `None` | `None` | `None` | `None` |
| dynamic FIT missing | unavailable | `(None, unit, label)` | unavailable | unavailable |
| real zero | `0.0` | `0.0` | `0.0` | `0.0` |

The production compositor hides `None`; it does not display it as textual or numeric zero.

## J. Real-zero regressions

Added/verified cases:

```text
FIT cadence = 0.0 → resolver/current remains 0.0
FIT speed = 0.0 → precompute remains 0.0
FIT power = 0.0 → source value remains 0.0
missing sample → None
```

`0.0` is checked explicitly with `is None`-safe logic; no falsey-value fallback is used for telemetry values in the changed source contract.

## K. Source switching

Round-trip:

```text
GPMF → FIT → GPX → GPMF
```

was verified for manager, chart history, PRECOMPUTED and worker resolver:

```text
GPMF = 10.0
FIT  = 20.0
GPX  = 30.0
GPMF = 10.0
```

Each path returned the value from the currently selected source. Empty FIT/GPX tests returned `None`.

## L. Tests

New ETAP 6B tests:

```text
tests/test_etap6b_contract.py — 7 passed
```

Related targeted suite:

```text
76 passed
```

Included source resolver, manager, chart, gauge, GPMF timing/cache, IMU and dynamic FIT/precompute regressions.

Full suite after ETAP 6B:

```text
316 passed, 3 failed, 17 skipped
```

The three failures are pre-existing and unrelated:

```text
tests/test_amd_native_etap4.py
tests/test_qp_analyzer.py
tests/test_render_tab.py
```

No new ETAP 6B-related failure was introduced.

## M. Remaining issues

### CONFIRMED

```text
PRECOMPUTED source fallback removed.
None is preserved until presentation.
Unavailable dynamic FIT fields no longer become zero-valued indicators.
FIT availability is rebuilt from current fit_data without deleting layout config.
```

### SUSPECTED

No new issue within the ETAP 6B scope.

### OUT OF SCOPE

```text
GPSDOP/GPSFix/GPSAltitudeSystem/GPSDays/GPSSecs
GPX battery
K1/K2/radar semantic interpretation
GPSSpeed2D vs GPSSpeed3D policy
interpolation changes
smoothing changes
new telemetry fields
unrelated full-suite failures
```

## Final result

```text
SOURCE CONTRACT STRICT = PASS
NONE / ZERO SEMANTICS = PASS
DYNAMIC FIT AVAILABILITY = PASS
PREVIEW / PRECOMPUTE / WORKER PARITY = PASS for tested source cases
```

ETAP 6B zakończony. Zatrzymuję się zgodnie z zakresem.
