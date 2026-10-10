# BikeRideHUD v1.11 — final corrective acceptance

Validation date: 2026-10-10
Repository: `C:\_DEV\BikeRideHUD-main-new`
Branch: `fix/gui-freeze-hud-composite`
Initial commit: `f8c80b73b745a04c0f62d2dd3fdd8afbd7897826`
Tested code HEAD: `a515c77370575c4bf70b3cb0d889e70db118af19`

## Acceptance fields

```text
APP_VERSION=1.11
GIT_HEAD=a515c77370575c4bf70b3cb0d889e70db118af19 (tested code HEAD)
REMOTE_HEAD=PENDING_PUSH
VERSION_API_PASS=PASS (APP_VERSION, APP_BUILD_COMMIT, get_build_commit())
MAIN_START=PASS (AMD/AMF initialization and MainWindow startup; strict missing-file CLI returned expected 1)
PORTABLE_START=PASS (synced Portable AMD/AMF initialization; strict missing-file CLI returned expected 1)
TITLE_VERSION_PASS=PASS (Main and Portable titles contain v1.11 and their build commit)

SYNC_POSITIVE_CASE=NOT RUN; canonical GX020079.MP4 + GX020079.fit files are unavailable in this checkout
SYNC_NEGATIVE_CASES=PASS; GX010321 + Poranna FIT => INVALID/DATE_TIME_MISMATCH; missing MP4 and missing FIT => MISSING_FILE
SYNC_OVERRIDE_USED=FALSE
SYNC_MATCHED_POINTS=NOT AVAILABLE (positive fixture missing)
SYNC_MEDIAN_ERROR_M=NOT AVAILABLE (positive fixture missing)
SYNC_P90_ERROR_M=NOT AVAILABLE (positive fixture missing)
SYNC_OFFSET_S=NOT AVAILABLE (positive fixture missing)
SYNC_COVERAGE=NOT AVAILABLE (positive fixture missing)
SYNC_RESULT_JSON=scratch/sync_negative_final.json; scratch/sync_integrity_negative_missing_video.json; scratch/sync_integrity_negative_missing_fit.json

DIRECT_PREVIEW_ON_FPS=NOT TESTED
DIRECT_PREVIEW_OFF_FPS=NOT TESTED
QUEUE_PREVIEW_ON_FPS=NOT TESTED
QUEUE_PREVIEW_OFF_FPS=NOT TESTED
DIRECT_STEADY_FPS=NOT TESTED
QUEUE_STEADY_FPS=NOT TESTED
DIRECT_EFFECTIVE_FPS=NOT TESTED
QUEUE_EFFECTIVE_FPS=NOT TESTED
DIRECT_STARTUP_MS=NOT TESTED
QUEUE_STARTUP_MS=NOT TESTED
GPU_3D_USAGE=NOT MEASURED
GPU_VIDEO_ENCODE_USAGE=NOT MEASURED
GPU_VIDEO_DECODE_USAGE=NOT MEASURED
CPU_USAGE=NOT MEASURED

PERFORMANCE_ROOT_CAUSE=NOT PROVEN; existing profile files describe unrelated/incomplete runs and do not establish the cause
PERFORMANCE_FIX=NONE; no renderer change without comparable A/B evidence
PERFORMANCE_PARITY_PERCENT=NOT MEASURED

REAL_DIRECT_MP4=NOT RUN
REAL_QUEUE_MP4=NOT RUN
FFPROBE_PASS=NOT TESTED
HUD_PASS=NOT TESTED
MAP_PASS=NOT TESTED
CHART_PASS=NOT TESTED
AUDIO_PASS=NOT TESTED
QP_PASS=NOT TESTED

FIT_ROLLBACK_PASS=PASS (unit test)
GPX_ROLLBACK_PASS=PASS (unit test; moved GPX source assignment to commit-after-success)
CACHE_KEY_PARITY=FIT switch invalidation PASS; parent/child runtime parity NOT PROVEN

CANONICAL_HARNESS_PASS=PARTIAL (negative sync paths pass; positive real sync and 800-frame exports not run)
PORTABLE_PARITY=PASS (100% manifest match)
GIT_COMMIT_HASHES=0d7eb672f3d6f90d91ab533345e4cb72dfde0de2, a515c77370575c4bf70b3cb0d889e70db118af19
GIT_PUSH_STATUS=PENDING

FINAL_STATUS=PERFORMANCE_PARTIAL; not FULL PASS
```

## Changes

- Restored the full version API with `APP_VERSION='1.11'`; made `scripts/bump_version.py` increment decimal versions without losing trailing zeroes (`1.09 → 1.10`, `1.11 → 1.12`) and only replace the version assignment.
- Removed implicit success from `--test-sync-integrity`. Its only success route now requires explicit `VALID` preflight, the requested FIT to be loaded, a measured spatial SmartSync result, and no override. It writes structured JSON and uses nonzero exits for rejection, missing files, timeout, and internal errors.
- Reworked `scripts/test_sync_integrity.py` to require an actual positive SmartSync result with GPS overlap and measured points/coverage/errors/offset. Negative cases are labeled `EXPECTED_REJECTION` and cannot count as positive validation.
- Added FIT/GPX source rollback tests. Fixed GPX source assignment occurring before synchronization could fail.
- Prepared a serial Direct/Queue A/B runner requiring a verified VIDEO/FIT SmartSync pair, 4K HEVC, QUALITY, at least 800 frames, three alternating pairs per preview state, and FFprobe checks. It refuses the rejected `GX010321.MP4` + `Poranna_jazda_na_rowerze.fit` pairing.

## Verification

- `py_compile` passed for modified Python modules and harnesses; `git diff --check` passed.
- Targeted pytest set: **54 passed, 3 skipped**. A separate attempt to collect `tests/test_real_gui_startup_and_child_hash.py` failed at collection because this checkout's `src.startup_timeline` does not export `StartupAuditTracker`; no code in this task changed that module.
- `next_version('1.09') == '1.10'` and `next_version('1.11') == '1.12'` passed.
- Main and Portable started against the installed AMD Radeon Graphics / AMF HEVC stack. Both strict missing-file runs emitted JSON `MISSING_FILE` and exited 1.
- The rejected GX010321/FIT pair produced real validation status `INVALID`, reason `DATE_TIME_MISMATCH`, 0 overlap, and `user_override=false`; process exit was 1. The structural result is `scratch/sync_negative_final.json`.
- `scripts/sync_portable.py` completed and `scripts/check_parity.py` reported `PARITY: YES (100% manifest match)`.

## Performance and remaining evidence gap

The expected canonical positive source pair is `Video/GX020079.MP4` + `Video/GX020079.fit`; project reports document its spatial SmartSync match and 4K workload. Neither source file is present in this checkout or the inspected local source folders. The available `GX010321`/`Poranna` files are explicitly rejected by real validation. Therefore the harness correctly fails its positive gate, and no Direct/Queue export or performance fix was claimed.

The prior 17.7/27.1 FPS figures were not reproduced here. Existing profiler artifacts do not supply a comparable accepted FIT/layout workload, so they cannot prove GUI D3D11 contention or another root cause. Direct/Queue steady and effective FPS, startup phases, GPU engine use, CPU, VRAM, output quality, HUD/map/charts/audio/QP, and preview resource release remain unverified. Final status is `PERFORMANCE_PARTIAL`.
