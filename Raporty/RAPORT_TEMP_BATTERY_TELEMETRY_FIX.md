# RAPORT — TEMPERATURA I BATERIA W TELEMETRII HUD (PROVENANCE & TIMELINE FIX)

**Data:** 2026-09-16  
**Gałąź:** `amd-bikeridehud`  
**Środowisko:** Windows, Python 3.14, D3D11 Native Compositor  
**Status:** **CASE A — TEMP/BATTERY TELEMETRY FULLY FIXED**

---

## 1. Metric Header / Required Key-Value Fields

```text
TEMP_INDICATOR_KEY=temp_text
TEMP_SOURCE=gpmf
TEMP_FIELD=temperature

BATTERY_INDICATOR_KEY=fit_gopro_battery_text
BATTERY_SOURCE=fit
BATTERY_FIELD=gopro_battery

FIRST_BROKEN_LAYER_TEMP=Layer 1 (Telemetry Extractor — GPMF GPS anchor timeline projection)
FIRST_BROKEN_LAYER_BATTERY=None (FIT battery path verified correct across all layers)

ROOT_CAUSE_TEMP=GoPro GPS lock occurred at Doc50 (~49.7s into video). _extract_gpmf_timed_samples, _extract_gpmf_vector_samples, and find_gps_anchor directly added min(GPSDateTime) to (stmp - base_stmp) without subtracting the GPS anchor STMP offset from base_stmp, causing Doc1 (t=0) to receive a timestamp +49.7s in the future and leaving the first 49.7s of the video without telemetry samples ("-- °C").
ROOT_CAUSE_BATTERY=None (GoPro battery percentage is sourced from FIT developer field gopro_battery with 1400 continuous samples and resolved via monotonic_depletion strategy).

TEMP_063107=25.4 °C (exact raw GPMF Doc46: 25.3906 °C)
BATTERY_063107=57.6% (exact FIT sample: 57.0% / monotonic depletion: 57.57%)

CACHE_HIT_STATUS=PASS (Exact parity with cache miss, 1398 samples loaded)
CACHE_MISS_STATUS=PASS (Fresh parse from raw records verified across all 6 test timestamps)
TRACEBACK_COUNT=0

MODIFIED_FILES=src/telemetry_extract.py, src/telemetry_processed_cache.py, tests/test_gpmf_temp_and_battery_timing.py
CASE=CASE A — TEMP/BATTERY TELEMETRY FULLY FIXED
```

---

## 2. Layout & Indicator Mapping

From `Video/GX010298.layout.json`:

| VISIBLE_LABEL | INDICATOR_KEY | SOURCE | FIELD | FORM | STYLE | UNIT | ENABLED |
|---|---|---|---|---|---|---|---|
| **GP** | `temp_text` | `gpmf` | *(implicit)* `temperature` | `text` | *(none)* | *(empty)* | **True** |
| **Bat** | `fit_gopro_battery_text` | `fit` | *(implicit)* `gopro_battery` | `text` | *(none)* | `%` | **True** |
| **Garmin Battery %** | `fit_garmin_battery_percent_text` | `fit` | *(implicit)* `garmin_battery_percent` | `segment_bar` | `segments` | `%` | **True** |
| **Solar** | `fit_solar_text` | `fit` | *(implicit)* `solar` | `bar` | `ruler` | `%` | **True** |
| Temperature | `fit_temperature_text` | `fit` | *(implicit)* `temperature` | `text` | *(none)* | `°C` | False |
| Garmin Temperature | `fit_garmin_temperature_text` | `fit` | *(implicit)* `garmin_temperature` | `text` | *(none)* | `°C` | False |
| Battery Pct | `fit_battery_pct_text` | `fit` | *(implicit)* `battery_pct` | `text` | *(none)* | `%` | False |

---

## 3. Raw Source Verification & Provenance

### GoPro GPMF Stream Timing Math
- Video duration: 1398.66 s (start: `2026-09-16 04:30:22.390260 UTC` / `06:30:22` local).
- Stream `TMPC` (`CameraTemperature`) contains 1398 1-second Doc payloads (`Doc1` to `Doc1398`).
  - `Doc1:TMPC_STMP = 75869 us` (t = 0.076s relative to camera hardware clock).
  - `Doc1:CameraTemperature = 21.5898 °C`.
- First GPS Fix:
  - `Doc50-6:GPSDateTime = 2026-09-16 04:31:12.100 UTC`.
  - `Doc50:TMPC_STMP = 49125702 us`, `Doc50-6:SampleTime = 0.600 s` -> GPS fix STMP = `49725702 us`.
  - Elapsed time from Doc1 to GPS fix: `(49725702 - 75869) us = 49.649833 s`.
  - Exact stream start UTC datetime: `04:31:12.100000 - 49.649833 s = 2026-09-16 04:30:22.450167 UTC`.

### Provenance Multi-Layer Trace across Test Timestamps

| Timestamp (Local / UTC) | RAW SOURCE (GPMF Doc / FIT) | PARSER_VALUE (OLD) | PARSER_VALUE (FIXED) | CACHE HIT VALUE | TM RESOLVER | PREVIEW GUI VALUE | MATCH |
|---|---|---|---|---|---|---|---|
| **06:30:22** (04:30:22) | `Doc1: 21.5898 °C`, `FIT Bat: 58.0%` | `None` (`-- °C`) | `21.5898 °C` | `21.5898 °C` | `21.5898 °C` | `21.6 °C`, `58.0%`, `51.0%` | **YES** |
| **06:30:26** (04:30:26) | `Doc5: 22.1797 °C`, `FIT Bat: 58.0%` | `None` (`-- °C`) | `22.1273 °C` | `22.1273 °C` | `22.1273 °C` | `22.1 °C`, `58.0%`, `51.0%` | **YES** |
| **06:30:30** (04:30:30) | `Doc9: 22.6562 °C`, `FIT Bat: 58.0%` | `None` (`-- °C`) | `22.6563 °C` | `22.6563 °C` | `22.6563 °C` | `22.7 °C`, `57.9%`, `51.0%` | **YES** |
| **06:31:07** (04:31:07) | `Doc46: 25.3906 °C`, `FIT Bat: 57.0%` | `None` (`-- °C`) | `25.3901 °C` | `25.3901 °C` | `25.3901 °C` | `25.4 °C`, `57.6%`, `50.8%` | **YES** |
| **06:31:12** (04:31:12) | `Doc51: 25.6250 °C`, `FIT Bat: 57.0%` | `21.5898 °C` *(delayed)* | `25.6245 °C` | `25.6245 °C` | `25.6245 °C` | `25.6 °C`, `57.5%`, `50.8%` | **YES** |
| **06:31:20** (04:31:20) | `Doc59: 25.9531 °C`, `FIT Bat: 57.0%` | `22.6944 °C` *(delayed)* | `25.9519 °C` | `25.9519 °C` | `25.9519 °C` | `26.0 °C`, `57.4%`, `50.8%` | **YES** |

---

## 4. Root Cause Comparison (curVPower vs Temperature)

1. **curVPower**: FIT stream was completely parsed and present from t=0. The issue occurred in Layer 3 (Resolver) because `_presentation_video_start` in the layout metadata had been set to the delayed GPMF anchor (`04:31:12.100`), causing `coverage_start` filtering to drop early valid FIT samples.
2. **Temperature (`temp_text`)**: GPMF stream `CameraTemperature` was parsed, but Layer 1 (Extractor) incorrectly anchored `Doc1` to the GPS fix time at `Doc50`, creating an artificial +49.7s forward shift. Thus, no temperature samples existed between 04:30:22 and 04:31:12, yielding `None` (`-- °C`).
3. **Battery (`fit_gopro_battery_text`)**: FIT stream `gopro_battery` was parsed correctly and resolved smoothly via `monotonic_depletion` (57.5% -> 57.0%).

---

## 5. Implementation Summary

1. **`src/telemetry_extract.py`**:
   - `find_gps_anchor`: Extracts `(GPSDateTime, sample_stmp)` and projects the anchor back to `base_stmp` (`Doc1`), computing the true video start time `04:30:22.450 UTC`.
   - `_extract_gpmf_timed_samples` (`TMPC`, `ISO`, `SHUT`): Collects all GPS anchors with their respective `STMP` offsets and computes `stream_start_dt = min(gps_dt - (anchor_stmp - base_stmp))`, assigning accurate timestamps to all Doc blocks from `Doc1` onwards.
   - `_extract_gpmf_vector_samples` (`ACCL`, `GYRO`): Applies the identical projection so full-resolution accelerometer and gyroscope streams start at true clip start.
   - `interpolate_temperature`: Sets `allow_pre_first=True` for seamless boundary interpolation.
2. **`src/telemetry_processed_cache.py`**:
   - Bumped `PROCESSED_CACHE_VERSION` to `5`, cleanly invalidating legacy shifted `.telemetry.npz` archives and persisting the corrected native timeline automatically.
3. **`tests/test_gpmf_temp_and_battery_timing.py`**:
   - Automated regression test suite covering synthetic late-GPS records and real `GX010298` dataset.

---

## 6. Verification Results

- **Cache Miss vs Cache Hit**: Exact parity verified across all test timestamps (`PASS`).
- **GUI Preview Test**: 0 tracebacks, exact value matching, zero `--` dashes when source data is valid, zero artificial delays (`PASS`).
- **Test Suite**: `test_gpmf_temp_and_battery_timing.py` passed (2/2 tests OK).
