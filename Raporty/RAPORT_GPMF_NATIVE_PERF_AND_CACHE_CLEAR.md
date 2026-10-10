# GPMF native performance and cache cleanup

## Result

CASE=A — native GPMF works in the production load path, valid native channels
are accepted without a GPS requirement, processed telemetry is reused from the
central cache, and the Settings cleanup button is protected during active jobs.

NATIVE_GPMF_MODULE_FOUND=True
NATIVE_RESULT_ACCEPTANCE_CONDITION_BEFORE=`native_data.get("gps_track")`
NATIVE_RESULT_ACCEPTANCE_CONDITION_AFTER=`success` plus any non-empty native telemetry channel

WHOLE_FILE_PYTHON_FALLBACK_BEFORE=True
WHOLE_FILE_PYTHON_FALLBACK_AFTER=False for a valid native result; legacy full parsing remains only when the native module/result is unavailable
PARTIAL_FALLBACK_IMPLEMENTED=True

GPS_NATIVE=True — 378 samples on `Video/GX020079.MP4`
ACC_NATIVE=True — 7504 samples
GYRO_NATIVE=True — 7504 samples
ACC_LAZY_OR_ARRAY=True — NumPy `(7504, 4)` plus unmaterialized `LazySampleList`
GYRO_LAZY_OR_ARRAY=True — NumPy `(7504, 4)` plus unmaterialized `LazySampleList`

TIMELINE_MATCH=True — native and existing processed reference matched counts and first/last timestamps for GPS, ACC, GYRO, ISO and TEMP on GX020079
ACC_DATA_VALID=True — native extraction and array population smoke passed
GYRO_DATA_VALID=True — native extraction and array population smoke passed

## Cache

CACHE_PATH=`%LOCALAPPDATA%\\SportCamHUD\\cache\\media\\<source_key>\\`
CACHE_SCHEMA_VERSION=5 processed telemetry / 5 GPMF JSON / 1 central cache manager format
FIRST_LOAD_CACHE_HIT=False — end-to-end cold smoke on a unique hardlink source
SECOND_LOAD_CACHE_HIT=True — same end-to-end smoke
SECOND_LOAD_GPMF_PARSE=False — processed cache fast path returned before native/GPMF parsing

TOTAL_GPMF_LOAD_MS=243.18 — cold native path including native extraction, telemetry population, atomic cache write/read
ACC_LOAD_MS=NOT SEPARATELY MEASURED — ACC is extracted in the same native pass
GYRO_LOAD_MS=NOT SEPARATELY MEASURED — GYRO is extracted in the same native pass

CACHE_CLEAR_BUTTON_IMPLEMENTED=True
CACHE_CLEAR_ACTIVE_JOB_POLICY=disabled during active render states and GPMF telemetry analysis progress
CACHE_CLEAR_FILES_REMOVED=1 in focused cleanup test
CACHE_CLEAR_BYTES_REMOVED=4 in focused cleanup test
USER_FILES_PRESERVED=True
GPU_CAPABILITY_CACHE_PRESERVED=True

The central cleanup removes only entries below the managed `cache/media` root.
The cache root itself and files beside `media` are preserved; source MP4/FIT,
project/layout/settings/queue files and `gpu_capabilities.json` are not targeted.
All cache writes remain temporary-file plus `os.replace` atomic writes.

## Tests and verification

PYTEST=`python -m pytest -q tests/test_gpmf_native_perf_and_cache_clear.py` — 9 passed
PY_COMPILE=PASS for all changed Python modules
NATIVE_SMOKE=PASS — native module loadable; GPS 378, ACC 7504, GYRO 7504, ISO 1131, TEMP 38
GUI_BUTTON_SMOKE=PASS — button disabled for `running`, enabled for `completed`
DIFF_CHECK=PASS for task files

MODIFIED_FILES=
- `src/telemetry_native_gpmf.py`
- `src/gui/qt/_mixins/project_mixin.py`
- `src/telemetry_cache_manager.py`
- `src/gui/qt/tabs/settings_tab.py`
- `src/native/gpmf/gpmf_extractor.cpp`

CREATED_FILES=
- `tests/test_gpmf_native_perf_and_cache_clear.py`
- `Raporty/RAPORT_GPMF_NATIVE_PERF_AND_CACHE_CLEAR.md`
- `src/native/gpmf/telem_gpmf_native.pyd` and generated `.exp`/`.lib` linker artifacts

Backend isolation: no renderer, AMF, compute shader, capability detection,
NVIDIA, Intel, queue scheduler, map, or HUD code was changed by this task.

NOT TESTED=
- Full GUI export/render benchmark and AMD 8K→4K performance regression.
- Separate ACC/GYRO wall-clock timings; native parser uses one source pass.

RISKS=
- If the native module is absent or cannot load, the pre-existing legacy parser
  remains the fallback path.
- Cache cleanup intentionally skips entries that cannot be removed and reports
  the successfully removed files/bytes; active-job UI blocking is the primary
  race-avoidance policy.

TOTAL_STAGE_WALL_TIME=approximately 30 minutes
AUDIT_TIME=approximately 4 minutes
REPRO_TIME=approximately 3 minutes
IMPLEMENTATION_TIME=approximately 14 minutes
VALIDATION_TIME=approximately 9 minutes
LONGEST_SINGLE_COMMAND_SECONDS=17.6 — native module build

NTFY_SUCCESS=True — three attempts returned exit code 0
