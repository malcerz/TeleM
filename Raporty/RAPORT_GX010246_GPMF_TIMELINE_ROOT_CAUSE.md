# GX010246 — GPMF timeline / absolute-time root-cause audit

**Data:** 2026-09-09  
**Gałąź:** `integration/intel-amd`  
**HEAD (bez commitowania):** `59277b4`  
**Status:** **READY — ROOT CAUSE PROVEN; GENERAL FIX APPLIED**

## Zakres i pliki

- `BAD_FILE`: `D:\GoPro\2026-09-02\GX010246.MP4`
- `GOOD_FILE`: `D:\GoPro\2026-09-02\GX010258.MP4` (działający sąsiedni plik; `GX010259.MP4` również ma prawidłowy wzorzec)
- regresja dodatkowa: `Video\GX010115.MP4`
- wszystkie świeże porównania GPMF wykonano bez użycia istniejącego cache; po zmianie cache otrzymał nową wersję i został wygenerowany ponownie.

## Dowód z ffprobe (container timeline)

| stream | GX010246 | GX010258 |
|---|---:|---:|
| format `start_time` | 0.000000 | 0.000000 |
| format `duration` | 2047.045000 s | 162.395567 s |
| video `duration` / `time_base` | 2046.677967 s / 1/30000 | 162.395567 s / 1/30000 |
| video avg/rate | 30000/1001 | 30000/1001 |
| video `nb_frames` | 61339 | 4867 |
| audio duration / time_base | 2046.656000 s / 1/48000 | 162.368000 s / 1/48000 |
| GPMF duration / time_base / packets | 2047.045000 s / 1/1000 / 2045 | 162.396000 s / 1/1000 / 163 |
| first video packet PTS/DTS | 0.000000 / 0.000000 | 0.000000 / 0.000000 |
| last video packet PTS/DTS | 2046.644600 / 2046.644600 | 162.362200 / 162.362200 |
| first/last audio PTS/DTS | 0.000000 / 2046.634667 | 0.000000 / 162.346667 |
| display matrix | rotation -180° | rotation -180° |
| format `creation_time` | 2026-09-02T05:48:37Z | 2026-09-02T12:53:46Z |

Both files have zero container/video start and the same time base, frame rate and rotation. ffprobe exposes no non-zero/negative start, edit-list offset, or PTS shift. `modification_time` and an `elst` record are not exposed by this ffprobe build.

`creation_time` is not the telemetry anchor for BAD: it is **5158.776 s later** than the canonical GPMF/video start. GOOD differs by only 2.234 s. Using creation time (or a timezone offset) would therefore be incorrect.

## Fresh native GPMF inventory

Absolute timestamps are UTC. “last−end” uses `canonical_start + native duration`.

| field | GX010246 count | first | last | first−video start | last−expected end | GX010258 count | first | last |
|---|---:|---|---|---:|---:|---:|---|---|
| GPS9 (valid) | 19649 | 04:24:00.099 | 04:56:44.900 | +81.874872 s | −0.369172 s | 1622 | 12:53:44.000 | 12:56:26.099 |
| ISOE | 61339 | 04:22:38.224128 | 04:56:44.869025 | 0.000000 s | −0.400147 s | 4867 | 12:53:43.766329 | 12:56:26.130034 |
| SHUT | 61339 | 04:22:38.224128 | 04:56:44.868994 | 0.000000 s | −0.400178 s | 4867 | 12:53:43.766329 | 12:56:26.130034 |
| TMPC (logical) | 2045 | 04:22:38.224128 | 04:56:44.267007 | 0.000000 s | −1.002165 s | 163 | 12:53:43.766329 | 12:56:25.929690 |
| ACCL | 406684 | 04:22:38.224128 | 04:56:44.931351 | 0.000000 s | −0.337821 s | 32268 | 12:53:43.766329 | 12:56:26.191455 |
| GYRO | 406684 | 04:22:38.224128 | 04:56:44.932293 | 0.000000 s | −0.336879 s | 32269 | 12:53:43.766329 | 12:56:26.196488 |

BAD canonical start is `2026-09-02T04:22:38.224128Z`. The first valid GPS9 block is `2026-09-02T04:24:00.099Z`, with `STMP=81174872`, `TSMP=820`, sample index 7, hence local position `81.174872 + 0.7 = 81.874872 s`. The correct anchor is therefore `GPS9_absolute − local_STMP/sample_position`, not the first GPS9 timestamp itself.

`GPSU`, `GPSDateTime`, GPS5, GPSP/GPSFix and GPSDOP standalone blocks are absent in both files. GPS9 contains the absolute days/seconds. BAD has 2045 GPS9 blocks; the initial pre-lock blocks contain `(lat,lon)=(0,0)`. The old native result accepted those numerically in-range rows: 20466 GPS points beginning in 2021. The corrected result rejects 817 invalid pre-lock rows and starts at the first real 2026 position.

## Raw STMP/TSMP block timing

Per-stream block sequences are monotonic for BAD and GOOD. For BAD, ISO/SHUT/ACCL/GYRO/GPS9 each have zero STMP decreases and zero TSMP decreases; forward gaps are approximately the expected ~1 s block cadence (largest about 1.11 s for GPS9). GOOD shows the same pattern. TMPC has two physical copies (ACCL and GYRO), so an interleaved all-TMPC sequence can appear to decrease; the canonical logical ACCL copy is monotonic and deduplicated.

Representative BAD block endpoints:

```text
GPS9: ISO/SHUT:  STMP 81174872 (first valid GPS9) ... 2046127879
ISO/SHUT:        STMP 101195 ... 2046145408
ACCL:            STMP 100290 ... 2046143169
GYRO:            STMP 100809 ... 2046144632
```

There is no STMP reset, wraparound, or multi-minute discontinuity inside the valid 2026 sensor timeline.

## Root-cause proof and endpoint hold

Before the fix, fresh native GX010246 data had this range for ISO/SHUT/TMPC/IMU:

```text
2021-03-07 00:01:19.1 ... 2021-03-07 00:35:25.744896 UTC
```

The project resolver generated targets on the real video/GPMF axis:

```text
2026-09-02 04:22:38.224128 ... 04:56:34.902095 UTC
```

Consequently every target was **AFTER LAST SAMPLE** and previous/step hold returned the final 2021 value. This exactly explains the simultaneous frozen ISO, EXP, TMPC and Lean while video seek continued to work. The first pre-lock GPS9 rows were the sole reason the global anchor became 2021; the valid GPS9/STMP sequence itself is continuous.

After the correction, ISO/SHUT/TMPC/ACCL/GYRO begin at the canonical 2026 start and the GUI targets fall inside the range. GPS9 alone is legitimately **BEFORE FIRST SAMPLE** for targets 0–81.874872 s (GPS lock was not yet available), then enters its valid range; this is a physical GPS-lock interval, not a resolver freeze.

## Real visible GUI trace (QApplication → AppController → MainWindow)

No `QT_QPA_PLATFORM=offscreen` was used. Hardware preview reported `d3d11va`; the window was visible and `GX010246.MP4` loaded as a single clip with duration 2046.677967 s.

| slider/global s | clip local s | target UTC | video position/PTS | ISO | EXP | TMPC °C | lean_roll_x |
|---:|---:|---|---:|---:|---:|---:|---:|
| 0 | 0 | 04:22:38.224 | 0.0 | 545 | 30 | 22.3262 | −1.1341 |
| 10 | 10 | 04:22:48.224 | 10.0 | 717 | 61 | 23.4160 | −2.6679 |
| 30 | 30 | 04:23:08.224 | 30.0 | 215 | 400 | 25.1875 | +4.1716 |
| 60 | 60 | 04:23:38.224 | 60.0 | 84 | 200 | 26.6836 | +3.2207 |
| 120 | 120 | 04:24:38.224 | 120.0 | 69 | 128 | 28.1191 | +1.7976 |
| 2036.678 (end−10) | 2036.678 | 04:56:34.902 | 2036.678 | 1421 | 60 | 32.7480 | −4.6812 |

Video, ISO, exposure, temperature and lean all change across the requested seeks. This is direct proof that the BAD file no longer resolves to an endpoint-held stale sample.

## Implementation (general rule, no filename exception)

Changed only the timeline/invalid-cache pieces:

1. `src/native/gpmf/gpmf_extractor.cpp`
   - reject pre-GPS-lock GPS9 `(0,0)` rows;
   - remember the first valid GPS9 absolute timestamp and its STMP/sample local position;
   - derive `anchor_ts = first_valid_gps9_abs − first_valid_gps9_local_s`;
   - retain the old fallback only when no valid GPS9 exists.
2. `src/telemetry_processed_cache.py`
   - bump `PROCESSED_CACHE_VERSION` from 3 to 4 so old 2021 archives cannot be reused.
3. Rebuilt `src/native/gpmf/telem_gpmf_native.pyd` with the repository build script.

No parser-wide fallback, Lean, compositor/HUD, backend, or filename-specific offset was added. The change was made only after the stale 2021 sample range and endpoint-hold behavior were proven.

## Regression

- Fresh native parse: `GX010246`, `GX010258`, and `GX010115` all load successfully with non-empty ISO/EXP/TMPC/ACCL/GYRO and 2026 absolute timestamps.
- `GX010115` remains variable: ISO 78→114, EXP 346→359, TMPC 29.9707→43.2148 °C, and IMU timestamps span the full clip.
- Automated regression: `39 passed, 4 skipped` from
  `tests/test_telemetry_processed_cache.py`, `tests/test_tmpc_native_and_cache.py`, and `tests/test_multifile_timeline.py` (filtered to cache/timeline/native cases).
- Native extension rebuilt successfully with MSVC x64.

## Final decision

```text
ROOT CAUSE PROVEN: PASS
GX010246 absolute GPMF/video mapping: PASS
STMP/TSMP valid-stream continuity: PASS
Endpoint-hold explanation: PASS
Real visible GUI seek trace: PASS
GOOD_FILE regression: PASS
GX010115 regression: PASS
READY: YES (for the GX010246 timeline root-cause task)
```

No full 85574-frame render, commit, push, reset, clean, rebase, or unrelated backend change was performed.
