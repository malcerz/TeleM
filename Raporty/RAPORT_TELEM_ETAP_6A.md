# TeleM — ETAP 6A — RESULT

## Status

**READ-ONLY AUDIT — zakończony.** Nie zmodyfikowano kodu, testów, cache ani konfiguracji.

Audyt wykonano na:

```text
Video/GX030120.MP4
Video/GX030120.json
Video/Poranna_jazda_na_rowerze.fit
```

W repozytorium nie znaleziono fixture GPX. Parser GPX został przeanalizowany statycznie, ale nie wykonywano sztucznego GPX.

## A. Raw source inventory

### GPMF

| raw field / stream | canonical / użycie | count | first | last |
|---|---|---:|---|---|
| `GPSLatitude` | `gps_lat` / track | 1802 | 04:46:25.700 | 04:49:25.800 |
| `GPSLongitude` | `gps_lon` / track | 1802 | 04:46:25.700 | 04:49:25.800 |
| `GPSAltitude` | `alt` | 1802 | 04:46:25.700 | 04:49:25.800 |
| `GPSSpeed` + `GPSSpeed3D` | `speed` | 1802 | 04:46:25.700 | 04:49:25.800 |
| `ISO` | `iso` | 5400 | 04:46:25.700 | 04:49:25.846525 |
| `ExposureTimes` / `SHUT` | `exposure` | 5400 | 04:46:25.700 | 04:49:25.846525 |
| `CameraTemperature` / `TMPC` | `temperature` | 180 | 04:46:25.700 | 04:49:24.878197 |
| `ACCL` | `accel_x/y/z`, magnitude | 35802 | 04:46:25.700 | 04:49:25.874667 |
| `GYRO` | `gyro_x/y/z`, magnitude | 35802 | 04:46:25.700 | 04:49:25.874668 |
| `GPSDOP` | **raw present / model missing** | 1802 | — | — |
| `GPSFix` | **raw present / model missing** | 1802 | — | — |
| `GPSDays`, `GPSSecs` | timing metadata / not model fields | 1802 | — | — |
| `GPSAltitudeSystem` | metadata `MSLV` / not model field | 180 | — | — |

Raw GPMF has 180 blocks for `ACCL`, `GYRO`, `ISO`, `SHUT` and `TMPC`. `GPSDateTime` is used as the UTC anchor/timing source, not exposed as a normal value indicator.

Additional GPMF metadata confirmed on the material:

```text
ACCL unit = m/s, ORIN = ZXY, ORIO = None
GYRO unit = rad/s, ORIN = ZXY, ORIO = None
GPS altitude system = MSLV
```

The current GPMF extractor maps raw `ZXY` component order to canonical `X/Y/Z` in one place. The IMU sample counts and timing remained monotonic.

### FIT

`Poranna_jazda_na_rowerze.fit` contains 1672 deduplicated `record` timestamps from `04:29:39` to `04:57:30 UTC`. The parser discovered these raw/numeric fields:

| FIT raw field | canonical output | count | parser unit / conversion |
|---|---|---:|---|
| `enhanced_speed` | `enhanced_speed` | 1653 | m/s → km/h ×3.6 |
| `speed` | `speed` | 1627 | m/s → km/h ×3.6 |
| `enhanced_altitude` | `enhanced_altitude`, preferred `alt` | 1672 | m → m |
| `cadence` | `cadence` | 1672 | rpm |
| `fractional_cadence` | `fractional_cadence` | 1672 | rpm |
| `heart_rate` | `heart_rate` | 1672 | bpm |
| `curVpower` | `curVpower` / alias `power` | 1672 | watts |
| `temperature` | `temperature` / alias `atemp` | 1672 | °C |
| `distance` | `distance` | 1672 | m |
| `K1`, `K2` | same names | 1672 | FIT custom float, unit `%d` from fitparse |
| `passing_speed`, `passing_speedabs` | same names | 1672 | FIT custom field, values all 0 in this file |
| `radar_current` | same name | 1672 | FIT custom field |

After `sync_fit_to_video`, the model contains 16 streams: `speed`, `track`, `alt`, the 13 additional fields above, and the derived FIT track. No FIT `battery`, `battery_pct`, `gopro_battery`, `solar`, `discharge` field was present in this file; those active layout keys are therefore unavailable for this material.

### GPX

No GPX fixture exists in the repository for this pair. The implemented parser supports:

```text
lat/lon, time, elevation
extensions: power, atemp, hr, cad
```

It derives speed from consecutive coordinates and cumulative distance from the track. It does not parse battery, GPS fix/DOP, IMU, ISO, exposure or camera temperature. The parser supports no arbitrary extension export beyond the four named extensions.

## B. Canonical field dictionary

| canonical field | display | source(s) | raw field(s) | unit | lookup | smoothing | GUI | chart |
|---|---|---|---|---|---|---|---|---|
| `speed` | Speed | GPMF/FIT/GPX | `GPSSpeed3D` preferred, FIT `enhanced_speed`/`speed`, GPX derived | km/h | linear | GPMF/FIT/GPX manager paths may moving-average speed | yes | yes |
| `alt` | Altitude | GPMF/FIT/GPX | `GPSAltitude`, FIT `enhanced_altitude`, GPX `ele` | m | linear | GPMF/FIT/GPX manager paths may moving-average altitude | yes | yes |
| `track` | Distance/map track | GPMF/FIT/GPX | GPS coordinates / derived cumulative distance | m internally, km display | linear | none | yes | yes |
| `iso` | ISO | GPMF only | `ISO` | ISO index | previous/step | none | yes | supported by builder |
| `exposure` | Shutter | GPMF only | `ExposureTimes` / `SHUT` | denominator `1/N` | previous/step | none | yes | supported by builder |
| `temperature` | Camera temperature | GPMF only as `temp_text` | `TMPC` / `CameraTemperature` | °C | previous/step | none | yes | supported by builder |
| `accel_x/y/z` | Accelerometer X/Y/Z | GPMF only | `ACCL` | m/s as emitted by GPMF | previous/step | none | dynamic | supported |
| `accel_magnitude` | Accelerometer Magnitude | GPMF only | derived from same ACCL vector | m/s | previous/step | none | dynamic | supported |
| `gyro_x/y/z` | Gyroscope X/Y/Z | GPMF only | `GYRO` | rad/s | previous/step | none | dynamic | supported |
| `gyro_magnitude` | Gyroscope Magnitude | GPMF only | derived from same GYRO vector | rad/s | previous/step | none | dynamic | supported |
| `heart_rate` | HR | FIT/GPX | FIT `heart_rate`, GPX `hr` | BPM | previous/step | none | dynamic/GUI schema | supported |
| `cadence` | Cadence | FIT/GPX | FIT `cadence`, GPX `cad` | rpm | previous/step | none | dynamic/GUI schema | supported |
| `power` | Power | FIT/GPX | FIT `curVpower`, GPX `power` | W | previous/step | none | GUI schema | supported |
| `atemp` | Ambient/device temperature | FIT/GPX | FIT `temperature`, GPX `atemp` | °C | previous/step | none | GUI schema | supported |
| `battery` | Battery | FIT/GPX contract | FIT `battery_soc`, GPX battery attribute | % | previous/step | none | GUI schema | supported |
| `K1`, `K2` | FIT dynamic fields | FIT | custom FIT fields | raw FIT unit | previous/step | none | dynamic `fit_*` | supported |
| `enhanced_speed` | Enhanced Speed | FIT | `enhanced_speed` | km/h | linear | none after parse | dynamic `fit_*` | supported |
| `enhanced_altitude` | Enhanced Altitude | FIT | `enhanced_altitude` | m | linear | none after parse | dynamic `fit_*` | supported |
| `fractional_cadence` | Fractional Cadence | FIT | same | rpm | previous/step | none | dynamic | supported |
| `radar_current`, `passing_speed`, `passing_speedabs` | dynamic FIT values | FIT | same | parser-provided/custom | previous/step | none | dynamic | supported |

`speed`/`enhanced_speed` and `alt`/`enhanced_altitude` are intentional aliases plus explicit FIT dynamic fields; they are not silently merged across sources.

## C. Source matrix

| field | GPMF | FIT | GPX | canonical unit | GUI available |
|---|---:|---:|---:|---|---:|
| speed | yes | yes | yes | km/h | yes |
| altitude | yes | yes | yes | m | yes |
| track/distance | yes | yes | yes | m/km display | yes |
| ISO | yes | no | no | ISO | yes |
| exposure/SHUT | yes | no | no | `1/N` | yes |
| camera temperature | yes | no | no | °C | yes |
| accel x/y/z/magnitude | yes | no | no | m/s | dynamic yes |
| gyro x/y/z/magnitude | yes | no | no | rad/s | dynamic yes |
| heart rate | no | yes | yes | BPM | yes |
| cadence | no | yes | yes | rpm | yes |
| power | no | yes | yes | W | yes |
| ambient temperature | no | yes | yes | °C | yes |
| battery | no | not in reference FIT | not implemented in GPX parser | % | schema only |
| GPS DOP/fix | raw yes | no model field | no | raw source units | no |

## D. Current/history parity

The normal manager and `frame_data` paths use the explicit requested source. `build_chart_data()` also resolves history from the indicator source, and existing source-switch tests pass. For GPMF-only fields, `source=FIT` returns no samples in the shared resolver.

| field family | current | history | normal-path parity |
|---|---|---|---|
| speed/alt/track | exact configured GPMF/FIT/GPX source | same source | pass |
| ISO/SHUT/TMPC | exact GPMF source | same GPMF source | pass |
| IMU | exact GPMF source | same GPMF source | pass |
| HR/cadence/power/atemp/battery | exact FIT/GPX source | same source | pass |

**Confirmed worker-path mismatch:** `src/telemetry_precompute.py:276-282` uses `gpx_* or gpmf` and `fit_* or gpmf` for speed/track/alt. Thus an explicitly requested but empty FIT/GPX source can receive GPMF values in the precomputed worker cache. This is not present in the shared resolver itself and is a real current/history/source-contract defect in that execution mode.

## E. None / zero semantics

The manager resolver preserves missing source as `None`; zero-valued FIT cadence/power/speed remains a real `0.0` sample. This is covered by `tests/test_etap1_source_resolver.py`.

However, the presentation paths collapse missing data:

```text
src/indicators/compositor.py:216-223
None → 0.0 for ISO, SHUT, temperature, power, atemp, HR, cadence, battery

src/indicators/frame_data.py:366
None → 0.0 for dynamic IMU fields

src/telemetry_precompute.py:345-351
None → 0.0 for dynamic FIT fields
```

The diagnostic proof with an empty FIT source and a real GPMF speed sample was:

```text
strict frame_data resolver: requested FIT speed = 0.0 presentation value
precomputed cache: requested FIT speed = 10.0 (GPMF fallback)
missing FIT dynamic field = (0.0, '', label)
```

Classification: **CONFIRMED semantic missing-data defect**, with a more severe **CONFIRMED silent source fallback** in PRECOMPUTED mode. It can display false zeroes or values from another source instead of `unavailable`.

## F. Units and conversions

| field | raw unit | canonical | display | conversion |
|---|---|---|---|---|
| GPMF speed | GoPro numeric km/h on this material | km/h | km/h | none; 3D preferred, 2D fallback only inside GPMF candidate selection |
| FIT speed | m/s | km/h | km/h | ×3.6 in `telemetry_fit.py` |
| GPX speed | derived m/s | km/h | km/h | ×3.6 |
| altitude/elevation | m | m | m | none |
| FIT distance/track | m | m internally | km for distance indicators | `/1000` in display indicator path |
| GPMF TMPC | °C | °C | °C | none |
| FIT temperature / GPX atemp | °C | °C | °C | none |
| FIT power/curVpower | watts | W | W | none |
| HR | bpm | BPM | BPM | none |
| cadence | rpm | rpm | RPM | none |
| ACCL | `m/s` as GPMF metadata | m/s | m/s | none |
| GYRO | rad/s | rad/s | rad/s | none |
| battery contract | % | % | % | no reference-file sample |

GPMF temperature retains full precision in the model: e.g. raw/current `30.419921875`; the overlay may display `30.4` or integer according to indicator formatting. FIT speed retains float precision after ×3.6. No model-level integer truncation was found for these paths.

## G. Smoothing and derived fields

| field | raw/derived | smoothing |
|---|---|---|
| GPMF speed | raw GPMF `GPSSpeed3D`/`GPSSpeed` | manager may apply configured moving average |
| GPMF altitude | raw GPS altitude | manager may apply configured moving average |
| FIT/GPX speed and altitude | parsed/derived source samples | manager source-load smoothing policy applies to speed/alt |
| GPX speed | derived from coordinate deltas | no sensor fusion |
| GPMF track / FIT track / GPX track | cumulative distance derived from lat/lon | no smoothing |
| ACCL/GYRO axes | raw scaled/oriented vectors | no smoothing |
| IMU magnitude | `sqrt(x²+y²+z²)` from one vector sample | no smoothing |
| average speed | distance / elapsed time ×3.6 | derived display value only |

Current speed/alt can be smoothed while chart history uses the same loaded source series in the normal path. No separate chart-only smoothing was found. The PRECOMPUTED source fallback remains a parity exception.

## H. Lookup / interpolation

| type | semantics |
|---|---|
| speed | linear, clamped at source ends |
| altitude | linear, clamped at source ends |
| distance/track | linear, clamped at source ends |
| ISO | previous/step hold |
| SHUT/exposure | previous/step hold |
| TMPC | previous/step hold |
| HR/cadence/power/temperature/battery | previous/step hold |
| FIT dynamic fields | previous/step hold |
| ACCL/GYRO | previous/step hold |
| GPX track map | source track points; no cross-source fallback in manager |

Before first source sample, normal interpolators use their existing endpoint policy; for an empty source scalar interpolators return numeric zero in some legacy presentation helpers. This is part of the None/zero defect above.

## I. Reference snapshot — `2026-08-18 04:46:40 UTC`

| field | GPMF current | FIT current | selected source in diagnostic | resolved |
|---|---:|---:|---|---:|
| speed | 18.252 km/h | 20.0196 km/h | explicit per source | source value |
| altitude | 14.274 m | 13.0 m | explicit per source | source value |
| heart_rate | — | 102 BPM | FIT | 102 |
| cadence | — | 63 rpm | FIT | 63 |
| power/curVpower | — | 141 W | FIT | 141 |
| camera temperature | 30.419921875 °C | — | GPMF | 30.419921875 |
| ambient/device temperature | — | 17 °C | FIT | 17 |
| ISO | 70 | — | GPMF | 70 |
| SHUT | 431 | — | GPMF | 431 |
| accel_x | 1.25179856 m/s | — | GPMF | 1.25179856 |
| gyro_x | 0.23642173 rad/s | — | GPMF | 0.23642173 |

`frame_data` received the same values as the manager for speed, ISO, SHUT, camera temperature, `accel_x` and `gyro_x` in this populated GPMF snapshot.

## J. Additional snapshots

| UTC | GPMF speed | FIT speed | GPMF temp | FIT HR | FIT cadence | GPMF ISO | GPMF accel_x | GPMF gyro_x |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 04:47:25 | 16.236 | 13.3704 | 30.671875 | 90 | 41 | 149 | -4.57314 | 2.99787 |
| 04:48:25 | 22.212 | 24.9912 | 30.88671875 | 108 | 72 | 84 | -0.105516 | -0.507987 |
| 04:49:20 | 21.96 | 22.4064 | 30.81640625 | 110 | 58 | 93 | 1.06475 | 0.402556 |

The values vary continuously with the expected source-specific sample rates; no timestamp reset or stale previous-file value was observed in the populated manager path.

## K. GUI availability

| classification | result |
|---|---|
| MODEL PRESENT / GUI PRESENT | speed, altitude, track, ISO, SHUT, camera temperature, FIT dynamic fields, ACCL/GYRO dynamic fields, HR, cadence, power, atemp, battery schema |
| MODEL PRESENT / GUI MISSING | GPMF `GPSDOP`, `GPSFix`; raw `GPSDays`, `GPSSecs`, `GPSAltitudeSystem` metadata |
| GUI PRESENT / MODEL MISSING on reference material | active `fit_battery_pct_text`, `fit_battery_pct_x100_text`, `fit_battery_text`, `fit_discharge_text`, `fit_gopro_battery_text`, `fit_solar_pct_text`, `fit_solar_text` have no corresponding samples in `Poranna_jazda_na_rowerze.fit`; they resolve as unavailable but are currently rendered through zero-valued presentation fallback |

Dynamic FIT registration is generated from `fit_data`, but the current layout contains stale dynamic keys from fields not present in this reference FIT. Availability is therefore not fully source-sensitive at the presentation layer.

## L. Preview / render parity

For the populated GPMF snapshot at `04:46:40 UTC`, manager and `prepare_overlay_frame_data()` matched:

| field | manager | frame_data/preview input | CPU worker path | result |
|---|---:|---:|---:|---|
| speed | 18.252 | 18.252 | same shared resolver when source exists | pass |
| ISO | 70 | 70 | same GPMF stream | pass |
| SHUT | 431 | 431 | same GPMF stream | pass |
| camera temp | 30.419921875 | 30.419921875 | same GPMF stream | pass |
| accel_x | 1.25179856 | 1.25179856 | same GPMF stream | pass |
| gyro_x | 0.23642173 | 0.23642173 | same GPMF stream | pass |
| HR | None without FIT loaded | None | source unavailable | pass for no-data contract, but presentation may become 0 |

The shared `prepare_overlay_frame_data()` is used by preview and final preparation. The precomputed worker path is not fully parity-safe because of the source fallback identified in section D.

## M. Source switching

Existing source-switch tests passed for GPMF/FIT/GPX sample ownership and chart history. Normal resolver behavior is strict:

```text
requested FIT with no FIT samples → None
requested GPX with no GPX samples → None
requested GPMF-only field with FIT → None
```

The precomputed cache diagnostic is the exception:

```text
requested FIT speed, FIT empty, GPMF populated → GPMF value in indicator_values
```

Therefore source switching is **PASS in normal manager/frame_data/chart paths, FAIL in PRECOMPUTED source-specific speed/alt/track path**.

## N. Confirmed bugs

### 1. Silent source fallback in PRECOMPUTED mode

```text
severity: high
field: speed / altitude / track
source: FIT or GPX
file: src/telemetry_precompute.py
function: build_telemetry_cache
root cause: `fit_samples or gpmf_samples` and `gpx_samples or gpmf_samples`
evidence: empty FIT request returned GPMF speed 10.0 in diagnostic cache
current effect: wrong current value
chart effect: chart source may differ from current value
preview effect: mode-dependent
final effect: wrong value in PRECOMPUTED export mode
```

### 2. Missing value collapsed to numeric zero

```text
severity: medium
field: standard auxiliary and dynamic FIT/IMU fields
files: src/indicators/compositor.py, src/indicators/frame_data.py,
       src/telemetry_precompute.py
root cause: None converted to 0.0 before presentation
evidence: empty FIT field produced 0.0 in frame_data and precompute records
current effect: NO DATA can look like REAL VALUE = 0
chart effect: empty history is usually omitted, but current display may show 0
preview effect: false zero text/bar/gauge possible
final effect: same false zero in final CPU/GPU input
```

### 3. Stale dynamic GUI keys are not fully availability-filtered

```text
severity: medium
field: dynamic FIT indicators
evidence: current layout contains battery/solar/discharge fields absent from
          the reference FIT; they remain configured and render through 0.0
effect: GUI can expose unavailable fields instead of unavailable/hidden state
```

## O. Suspected issues

- GPX battery support is suggested by `gpx_battery_samples` and resolver mapping, but the implemented GPX parser/synchronizer does not populate it; classify as **model contract incomplete**, not a confirmed real-data regression because no GPX fixture was available.
- GPMF `GPSSpeed3D` is preferred over `GPSSpeed`; this is an intentional candidate policy, but the canonical model does not retain both as separate series for later selection.
- FIT `distance` is retained in metres while the built-in distance indicator uses a cumulative `track` stream; this is likely intentional but should remain documented as distinct raw-vs-derived fields.
- `K1/K2`, `radar_current`, `passing_speed` and `passing_speedabs` are dynamically exposed without a project-level semantic/unit dictionary; their raw presence is confirmed, semantic interpretation is not.

## P. Expected / non-bugs

- GPMF camera temperature (~30 °C) and FIT ambient/device temperature (~17 °C) are different physical fields and must not be merged.
- GPMF, FIT and GPX speed values can legitimately differ because they are different sensors/derivations and sample times.
- FIT `speed` and `enhanced_speed`, and `alt` and `enhanced_altitude`, are intentional aliases plus explicit raw fields.
- Display rounding (e.g. `30.419921875` → `30.4`) does not indicate model precision loss.
- ACCL and GYRO have different stream timing and are correctly stored as separate high-frequency series.
- ISO/SHUT/TMPC/IMU step lookup is expected for sample-and-hold telemetry; it is not a smoothing operation.

## Q. Missing useful fields

Raw GPMF fields currently not canonicalized into the TeleM model:

```text
GPSDOP
GPSFix
GPSAltitudeSystem
GPSDays / GPSSecs as values (they remain timing metadata)
```

The FIT file has no missing standard field that is present in its own records beyond the dynamic/custom fields already registered. GPX support lacks implemented battery export and has no arbitrary extension inventory.

## R. Recommended next stage

The smallest useful follow-up is:

```text
ETAP 6B — targeted common fix
```

Scope should be limited to:

1. remove `fit/gpx → GPMF` fallback from `telemetry_precompute.py`;
2. preserve `None`/unavailable through frame data and precompute until the explicit presentation layer;
3. make dynamic FIT GUI availability follow the current loaded source;
4. add regression tests for empty FIT/GPX source, real zero, and preview/worker parity.

Do not add GPS DOP/fix or GPX battery fields in ETAP 6A.

```text
TELEMETRY VALUE CONTRACT NOT CLOSED
```

The normal resolver and populated GPMF/FIT paths are coherent, but the two confirmed defects above prevent declaring the global value contract closed.

## Tests

Executed without changing tests:

```text
46 passed, 17 skipped
```

Covered resolver/source policy, manager, real FIT/GPMF integration, GPMF timing/cache and IMU. `tests/test_fit_registration.py` could not be collected in this environment because it imports the unavailable `src.gui.hud_tuner_app`; no code or test was changed to work around it.

The previously established full-suite baseline remains:

```text
308 passed, 4 failed, 17 skipped
```

Known failures remain unrelated and were not modified.
