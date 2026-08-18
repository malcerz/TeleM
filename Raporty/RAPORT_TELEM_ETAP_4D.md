# TeleM — ETAP 4D — RESULT

Materiał: `Video/GX030120.MP4`  
Cache: `Video/GX030120.json` / `Video/GX030120.json.meta.json`  
Status: **zakończony**

## A. Raw ACCL architecture

| pole | wynik |
|---|---|
| FourCC | `ACCL` |
| STNM | `Accelerometer` |
| TYPE / size | signed short / 6 B |
| SCAL | `417` |
| SIUN / UNIT | `m/s` / brak osobnego `UNIT` |
| ORIN / ORIO | `ZXY` / brak |
| blocks | 180 |
| samples per block | 199, z 18 blokami po 198 |
| last block samples | 198 |
| total vectors | 35 802 |
| components | 3 signed-short components/vector |
| STMP | `1006092290 … 1185270487` |
| TSMP | `200101 … 235704` |

Przykład pierwszego payloadu po skalowaniu, w surowej kolejności `Z,X,Y`:
`[-19.158273, 2.244604, 7.510791]`.

## B. Raw GYRO architecture

| pole | wynik |
|---|---|
| FourCC | `GYRO` |
| STNM | `Gyroscope` |
| TYPE / size | signed short / 6 B |
| SCAL | `939` |
| SIUN / UNIT | `rad/s` / brak osobnego `UNIT` |
| ORIN / ORIO | `ZXY` / brak |
| blocks | 180 |
| samples per block | 199, z 18 blokami po 198 |
| last block samples | 198 |
| total vectors | 35 802 |
| components | 3 signed-short components/vector |
| STMP | `1006094068 … 1185272265` |
| TSMP | `200102 … 235705` |

Przykład pierwszego payloadu po skalowaniu, w surowej kolejności `Z,X,Y`:
`[0.068158, -0.539936, 0.280085]`.

## C. Axis interpretation

`CONFIRMED X/Y/Z`.

GPMF podaje `ORIN=ZXY`; implementacja wykonuje jedno przemapowanie w extractorze:

```text
raw [Z, X, Y] → TeleM (x, y, z) = [raw[1], raw[2], raw[0]]
```

Jest to zgodne z dokumentacją GPMF dla trzyosiowych kanałów HERO5, która opisuje kolejność danych ZXY ([GoPro GPMF Parser](https://gopro.github.io/gpmf-parser/)). `ORIO` nie występuje i nie jest sztucznie uzupełniane.

## D. Units

| stream | RAW GPMF UNIT | TeleM canonical unit | conversion |
|---|---|---|---|
| ACCL | `m/s` | `m/s` | `raw / SCAL`; bez dalszej konwersji |
| GYRO | `rad/s` | `rad/s` | `raw / SCAL`; bez dalszej konwersji |

Wartości pozostają typu `float`; nie ma usuwania grawitacji, filtracji, bias compensation ani sensor fusion.

## E. Timing

Timing jest odtwarzany z `STMP/TSMP` bloków GPMF. Dla przejścia między blokami czas bloku jest rozłożony na rzeczywistą liczbę jego wektorów, więc blok 198-próbkowy nie powoduje duplikatu ani sztucznej przerwy. `TSMP` służy jako walidacja progresji, a nie jako zegar zastępczy.

Absolutny anchor UTC: pierwszy `GPSDateTime`; GPS nie jest używany jako per-sample clock.

| stream | count | first | last | effective Hz |
|---|---:|---|---|---:|
| ACCL | 35 802 | 2026-08-18 04:46:25.700000 UTC | 2026-08-18 04:49:25.874667 UTC | 198.701630 |
| GYRO | 35 802 | 2026-08-18 04:46:25.700000 UTC | 2026-08-18 04:49:25.874668 UTC | 198.701629 |

## F. Implementation

- `src/telemetry_gpmf_new.py`: zapis pełnych ACCL/GYRO payloadów, `SCAL`, jednostek, orientacji, `STMP`, `TSMP`, liczby komponentów i liczby próbek do cache.
- `src/telemetry_extract.py`: `extract_accelerometer_samples()` i `extract_gyroscope_samples()`; timing blokowy, mapowanie ZXY i walidacja monotoniczności.
- `src/gui/telemetry_manager.py`: pełne serie wektorowe, osie skalarne i magnitude.
- `src/telemetry_resolver.py`: jawne pola GPMF bez fallbacku do FIT/GPX.
- `src/indicators/frame_data.py`, `src/indicators/chart_builder.py`, `src/ffmpeg/worker_cache.py`: current value, historia i produkcyjny worker korzystają z tych samych serii.
- `src/gui/qt/_mixins/indicator_mixin.py`, controller i render mixin: dynamiczna dostępność GUI i przekazanie serii do renderera.
- cache schema: `4 → 5`; zachowano fingerprint źródła, generator, metadata sidecar i atomic write.

## G. Data model

```text
accel_x, accel_y, accel_z, accel_magnitude
gyro_x, gyro_y, gyro_z, gyro_magnitude
```

Magnitude jest obliczana z tego samego wektora czasowego: `sqrt(x²+y²+z²)`.

## H. Counts

| stream | raw | cache | pipeline |
|---|---:|---:|---:|
| ACCL | 35 802 | 35 802 | 35 802 |
| GYRO | 35 802 | 35 802 | 35 802 |

Regresja istniejących kanałów: ISO `5400/5400/5400`, SHUT `5400/5400/5400`, TMPC `180/180/180`.

## I. Timing statistics

| stream | min delta | median | p90 | max | duplicates | backward jumps |
|---|---:|---:|---:|---:|---:|---:|
| ACCL | 5.032 ms | 5.033 ms | 5.033 ms | 5.033 ms | 0 | 0 |
| GYRO | 5.032 ms | 5.033 ms | 5.033 ms | 5.033 ms | 0 | 0 |

Granice bloków `0→1`, `14→15`, `89→90`, `178→179` zachowują progresję; żaden test nie wykazał cofnięcia, duplikatu ani sztucznego dużego gapu.

## J. Multi-point validation

Lookup używa poprzedniej próbki dla high-frequency sensor data, bez wygładzania bazowej serii.

| video s | ACCL index / delta ms | ACCL (x,y,z) | GYRO index / delta ms | GYRO (x,y,z) |
|---:|---:|---|---:|---|
| 0 | 0 / 0.000 | (2.244604, 7.510791, -19.158273) | 0 / 0.000 | (-0.539936, 0.280085, 0.068158) |
| 10 | 1987 / 0.152 | (1.683453, -4.594724, -10.779376) | 1987 / 0.154 | (-0.218317, 0.141640, -0.082002) |
| 30 | 5961 / 0.440 | (-1.911271, 1.489209, -9.139089) | 5961 / 0.439 | (0.011715, 0.142705, -0.343983) |
| 60 | 11922 / 0.794 | (0.513189, 5.894484, -1.232614) | 11922 / 0.795 | (-0.092652, 0.010650, -0.137380) |
| 90 | 17883 / 1.007 | (-1.323741, -16.352518, -14.402878) | 17883 / 1.008 | (-0.128860, -0.104366, 0.382322) |
| 120 | 23844 / 1.156 | (1.630695, -4.652278, -13.985612) | 23844 / 1.157 | (0.191693, -0.357827, -0.595314) |
| 150 | 29805 / 1.312 | (1.071942, -3.836930, -10.961631) | 29805 / 1.313 | (0.324814, 0.146965, 0.017039) |
| 175 | 34772 / 3.964 | (2.251799, -1.908873, -19.302158) | 34772 / 3.964 | (-0.211928, -0.103301, -0.101171) |

## K. Cache parity

Fresh parse vs cache reload: `parity = True` for sample count, timestamps, component values, `ORIN/ORIO` and units. Cache load time was approximately `0.165 s`; fresh GPMF parse approximately `0.368 s` on this run.

## L. Resolver/source behavior

- `source=GPMF`: ACCL/GYRO fields resolve correctly.
- `source=FIT` or `GPX`: these GPMF-only fields return `None`/empty, with no silent fallback.
- Missing ACCL or GYRO: the two extractors and series are independent; absent stream produces unavailable data, not zeros or stale values.

## M. GUI availability

Dynamic availability exposes, when present:

```text
Accelerometer X/Y/Z, Accelerometer Magnitude
Gyroscope X/Y/Z, Gyroscope Magnitude
```

They use the existing chart/text indicator mechanism and the confirmed units.

## N. Preview/render parity

For the same `target_dt` at sample index 10 000:

```text
manager accel_x = -0.26618705035971224
worker/render accel_x = -0.26618705035971224
FIT source = None
```

## O. Performance

| metric | result |
|---|---:|
| ACCL vectors | 35 802 |
| GYRO vectors | 35 802 |
| fresh parse | ~0.368 s |
| cache before | previous v4 size was not recorded in the workspace |
| cache after | 8 736 813 B |
| cache load | ~0.165 s |

The cache remains JSON and includes full high-frequency vectors/timing. A later performance follow-up may consider compact encoding, but no correctness trade-off was made here.

## P. Regression

Confirmed unchanged by targeted validation: GPS9, ISOE, SHUT, TMPC, SmartSync and track/map paths. No implementation changes were made to those domains in ETAP 4D.

## Q. Tests

- New: `tests/test_etap4d_imu.py` — orientation, short final block, magnitude and source contract: **2 passed**.
- Related targeted suite: **44 passed**.
- Full suite: **303 passed, 4 failed, 17 skipped**.
- The four failures are the same pre-existing unrelated failures listed after ETAP 4C: `test_amd_native_etap4.py`, `test_amd_native_etap5b.py`, `test_qp_analyzer.py`, `test_render_tab.py`.

## R. Remaining issues

### CONFIRMED

ACCL/GYRO are fully parsed, scaled, timed, cached, resolved, exposed to GUI/chart/frame data and available in preview/render paths.

### SUSPECTED

The v5 JSON cache is large because it retains all 71 604 high-frequency vectors. Compact cache encoding can be evaluated separately.

### OUT OF SCOPE

Sensor fusion, pitch/roll/yaw, orientation estimation, gravity removal, filtering, gyro integration, GPU optimization and indicator scaling.

