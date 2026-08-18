# ETAP 6E — RESULT

Data: 2026-08-18. Materiał: `GX030120.MP4` + `Poranna_jazda_na_rowerze.fit`.

## A. Root cause

`src/telemetry_extract.py` używał `bisect_left` w `interpolate_value`, `interpolate_iso`, `interpolate_exposure` i `interpolate_temperature`. Przy `target_dt == sample_timestamp` wybierana była próbka poprzednia.

## B. Implementation

Dodano wspólny `_interpolate_step` oparty o `bisect_right(timestamps, target_dt) - 1`. Semantyka to greatest timestamp `<= target_dt`. Zmieniono tylko pola STEP; speed, altitude, distance/track oraz ich interpolacja liniowa pozostały bez zmian.

Pliki:

- `src/telemetry_extract.py`
- `tests/test_etap6e_step_lookup.py`
- `tests/test_interpolation.py` — aktualizacja dwóch oczekiwań starego kontraktu before-first/empty.

## C. Synthetic boundary tests

Seria `10.000→100`, `11.000→200`, `12.000→300`:

| target | expected | actual |
|---|---:|---:|
| 09.999 | None | None |
| 10.000 | 100 | 100 |
| 10.500 | 100 | 100 |
| 11.000−epsilon | 100 | 100 |
| 11.000 | 200 | 200 |
| 11.000+epsilon | 200 | 200 |
| 12.000 | 300 | 300 |
| 12.500 | 300 | 300 |

Duplicate timestampy wybierają ostatnią próbkę w istniejącym orderze. Realne zero pozostaje `0.0`.

## D. Real FIT — 04:46:40 UTC

| field | current BEFORE | exact sample | current AFTER | chart endpoint | parity |
|---|---:|---:|---:|---:|---|
| cadence | 63 | 62 | 62 | 62 | PASS |
| heart_rate | 102 | 102 | 102 | 102 | PASS |

## E. GPMF exact samples

| field | timestamp | expected | manager | worker |
|---|---|---:|---:|---:|
| ISO | 04:46:29.036661 | 70 | 70 | 70 |
| SHUT/exposure | 04:46:29.036661 | 390 | 390 | 390 |
| TMPC | 04:46:35.709913 | 30.416015625 | 30.416015625 | 30.416015625 |
| accel_x | 04:46:30.732635 | −1.515587529976019 | −1.515587529976019 | −1.515587529976019 |
| gyro_x | 04:46:30.732636 | −0.3919062832800852 | −0.3919062832800852 | −0.3919062832800852 |

Nie zmieniono timestampów, SCAL, orientacji ani magnitude.

## F. Boundary contract

- before first sample → `None`;
- exact sample → exact value;
- between samples → previous value;
- after last sample → last value;
- empty source → `None` / empty history;
- real zero → `0.0`;
- source ownership pozostaje strict: FIT/GPMF/GPX bez fallbacku.

## G. Pipeline parity

Dla `04:46:40` cadence/HR:

| path | cadence | HR |
|---|---:|---:|
| manager | 62 | 102 |
| preview/frame_data | 62 | 102 |
| PRECOMPUTED | 62 | 102 |
| worker | 62 | 102 |
| AMD input contract | 62 | 102 |

AMD renderer, GPU_SPLIT, AMF, D3D11 i VP nie były modyfikowane. Otrzymują poprawioną wartość z istniejącej ścieżki przed GPU.

## H. Chart clipping

ETAP 6D pozostaje bez zmian: historia nadal spełnia `timestamp <= target_dt`, zachowuje start video-visible i nie mutuje bazowej serii.

## I. Performance

Lookup: `bisect_right - 1`, złożoność `O(log N)`. Nie dodano pełnej kopii serii ani nowego subsystemu.

## J. Tests

```text
42 passed — ETAP 6E + 6D + 6B + telemetry_manager
19 passed — GPMF timing/cache, source resolver, AMD chart path
322 passed, 3 failed, 17 skipped — pełna suite
```

Pozostały wyłącznie wcześniejsze failure’y: `test_amd_native_etap4.py`, `test_qp_analyzer.py`, `test_render_tab.py`.

## K. Regressions

Brak zmian w linear interpolation, smoothingu, geometrii, size/font, mapie, source resolverze, chart clippingu 6D, GPMF/IMU timingach i implementacji GPU.

## L. Remaining issues

### CONFIRMED

Exact STEP lookup, real zero, `None`, source ownership oraz parity manager/preview/PRECOMPUTED/worker/AMD są poprawne.

### SUSPECTED

Brak nowych problemów w zakresie ETAPU 6E.

### OUT OF SCOPE

ACCL/GYRO layout, GPSDOP/Fix, sensor fusion, geometria mapy i optymalizacja GPU.

**ETAP 6E zakończony.**
