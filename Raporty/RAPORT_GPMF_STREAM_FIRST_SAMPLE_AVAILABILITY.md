# GPMF stream availability — first real sample contract

**Data:** 2026-09-09  
**Gałąź:** `integration/intel-amd`  
**Zakres:** availability semantics only; the GX010246 anchor correction, Lean
mathematics, compositor/HUD and backends were not changed.

## Contract implemented

For each dynamic GPMF stream, including derived IMU lean:

```text
target < first_sample : None / unavailable
first_sample <= target <= last_sample : previous/step value
target > last_sample : existing last-value hold
```

The generic FIT/GPX interpolation behavior remains unchanged. GPMF scalar
streams use the new strict `interpolate_gpmf_step` path. ISO, SHUT/Exposure,
TMPC, ACCL-axis and GYRO-axis resolution in the GUI manager and final worker
use that path. `interpolate_roll` now also returns `None` before its first
timeline sample; the manager/worker additionally require the first ACCL/GYRO
pair when both streams are present. The pair gate reads the first timestamp
from the NumPy/LazySampleList backing array, so it does not expand all IMU
samples on every frame.

Preview and Final therefore share the same boundary behavior through the
manager resolver and `worker_cache._resolve_cache_value` respectively; no
future sample is backfilled into an earlier video frame.

## Controlled synthetic test

The added test uses a video axis beginning at 0 s and independent streams:

```text
ISO  : starts  5 s
TMPC : starts 10 s
IMU  : starts 15 s (ACCL + GYRO pair)
```

Observed contract:

| target | ISO | TMPC | Lean |
|---:|---|---|---|
| 0 s | None | None | None |
| 6 s | active | None | None |
| 11 s | active | active | None |
| 16 s | active | active | active |

The test also verifies last-value hold after the final sample and compares
the GUI manager result with the Final worker result at every checkpoint.

## Real-file regression

Fresh native telemetry was loaded for:

- `D:\GoPro\2026-09-02\GX010246.MP4`
- `D:\GoPro\2026-09-02\GX010258.MP4`
- `Video\GX010115.MP4`

For all three, querying one microsecond before each stream's first timestamp
returned `None`; querying exactly at the first timestamp returned a real
value; querying after the last timestamp preserved the last value. Lean also
returned `None` immediately before the first ACCL/GYRO pair and a real roll at
that pair. GX010246 retains its corrected 2026 anchor and its GPS9 lock delay
does not suppress ISO/SHUT/TMPC/IMU.

Representative GX010246 first values:

```text
ISO   545
SHUT  30
TMPC  22.326171875 °C
Lean -1.1341478°
```

## Preview / Final boundary parity

The synthetic parity test initializes the final worker cache with the same
sample timelines and confirms identical `None`/value transitions for ISO,
TMPC and Lean. A short Final frame-render smoke (frames at 0/6/11/16 s)
captured `(ISO, EXP, TMPC)` as:

```text
(None, None, None) -> (200, 2, None) -> (200, 2, 21) -> (200, 2, 21)
```

This confirms the final compositor input changes at the same availability
boundaries as Preview. No full production render was started.

## Changed files

- `src/telemetry_extract.py` — strict GPMF step helper and strict ISO/SHUT/TMPC helpers.
- `src/telemetry_imu.py` — no pre-first roll backfill.
- `src/gui/telemetry_manager.py` — per-stream GPMF strict resolution and ACCL/GYRO first-pair gate.
- `src/ffmpeg/worker_cache.py` — matching Final-worker strict resolution and first-pair gate.
- `tests/test_gpmf_stream_first_sample_availability.py` — controlled and Preview/Final parity tests.

No change was made to the GPMF anchor fix or any backend.

## Tests

```text
tests/test_gpmf_stream_first_sample_availability.py : 4 passed
tests/test_tmpc_native_and_cache.py + tests/test_multifile_timeline.py
  + tests/test_lean_imu_contract.py : 53 passed, 4 skipped, 1 pre-existing failure
```

The unrelated existing failure is `test_zero_offset_subtracts` in
`test_lean_imu_contract.py` (`lean_visual_angle` currently returns 14 instead
of the expected 10). This task did not modify Lean mathematics; the new
availability tests pass, including real lean first-sample gating.

## Acceptance

```text
NO FUTURE SAMPLE BACKFILL: PASS
ISO STARTS AT FIRST ISO SAMPLE: PASS
EXP STARTS AT FIRST SHUT SAMPLE: PASS
TMPC STARTS AT FIRST TMPC SAMPLE: PASS
LEAN STARTS AT FIRST VALID IMU SAMPLE: PASS
GPS LOCK DOES NOT BLOCK OTHER GPMF: PASS
PREVIEW/FINAL PARITY: PASS (resolver/worker contract)
GX010246 REGRESSION: PASS
GX010115 REGRESSION: PASS
```

**READY:** YES for the first-real-sample availability task. No commit or push
was performed.
