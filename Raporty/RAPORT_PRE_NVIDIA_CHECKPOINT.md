# TeleM — Pre-NVIDIA checkpoint on `main`

## Scope

Checkpoint only. No functional code, backend, renderer, parser, or layout changes were made in this checkpoint operation. The working tree was audited on branch `main` at starting HEAD `c9c791b`.

## Starting state

- Branch: `main` (verified; no branch switch performed)
- Starting HEAD: `c9c791b`
- Existing safety tag `amd-final-2026-09-09`: preserved and not moved
- Working tree contained the telemetry presentation/startup/formatting work from the preceding approved tasks plus pre-existing scratch/build artifacts.

## Files to commit

### Production changes (A)

- `src/ffmpeg/worker_cache.py`
- `src/gui/layout_manager.py`
- `src/gui/qt/_mixins/indicator_mixin.py`
- `src/gui/qt/_mixins/preset_mixin.py`
- `src/gui/qt/_mixins/preview_mixin.py`
- `src/gui/qt/_mixins/project_mixin.py`
- `src/gui/qt/models.py`
- `src/gui/telemetry_manager.py`
- `src/indicators/bar.py`
- `src/indicators/compositor.py`
- `src/telemetry_resolver.py`

These are the previously implemented generic startup availability, decimal-property, canonical default, and range-label fixes. No new code was added for the checkpoint.

### Tests (B)

- `tests/test_gopro_battery_startup.py`
- `tests/test_gopro_battery_iso_decimal_ui.py`

### Reports (C)

- `Raporty/RAPORT_GOPRO_BATTERY_STARTUP_AVAILABILITY_FIX.md`
- `Raporty/RAPORT_GOPRO_BATTERY_ISO_DECIMAL_UI_FIX.md`
- `Raporty/RAPORT_GARMIN_BATTERY_STARTUP_RANGE_FORMAT_FIX.md`
- `Raporty/RAPORT_PRE_NVIDIA_CHECKPOINT.md`

## Explicitly excluded

- All tracked `scratch/**` deletions and files.
- `Video/scratch/`, telemetry `.npz`, render outputs, screenshots, logs, and caches.
- Native/build artifacts: `*.obj`, `*.pyd`, `*.exp`.
- Manual/local harnesses under `tests/manual_*.py`.
- Any unrelated or suspect file outside the lists above.

The excluded files remain untouched in the dirty working tree for the user to handle separately.

## Debug / hardcoded-path audit

Changed production files contain only existing normal application logging and default-off diagnostic gates (for example `TELEM_MULTIFILE_DEBUG`, `TELEM_PREVIEW_DEBUG`, `TELEM_LEAN_DEBUG`, and `AMD_AUDIT_ABOVE_COMPose`). No active production debug mode, filename-specific workaround, or hardcoded `D:`/USB path was found. Manual D:-path harnesses are excluded.

## Tests

Command:

```text
python -m pytest -q tests/test_gopro_battery_startup.py tests/test_gopro_battery_iso_decimal_ui.py tests/test_display_precision_interpolation.py tests/test_presentation_architecture.py tests/test_gpmf_stream_first_sample_availability.py tests/test_distance_bar_scale_contract.py tests/test_altitude_bar_rotation.py tests/test_battery_solar_optimization.py tests/test_fit_device_status.py
```

Result: **98 passed, 1 skipped**.

AMD quick smoke (import only; no render):

```text
AMD_IMPORT_PASS src.ffmpeg.amd_native_exporter
```

No long render, full benchmark, NVIDIA, or Intel run was performed.

## Commit/tag/push

- Commit message: `TeleM: checkpoint telemetry presentation fixes before NVIDIA work`
- Commit hash: recorded by the final `git log`/handoff after this single checkpoint commit (the report itself is included in that commit).
- Annotated tag: `pre-nvidia-2026-09-09`
- Push: verified after commit/tag creation

## Final parity and risks

The checkpoint records the approved telemetry fixes without changing backend behavior. The repository intentionally remains dirty because pre-existing scratch/build/local artifacts were not deleted or staged. The next task is NVIDIA rendering repair.

## Verdict

- PRE-NVIDIA CHECKPOINT: PASS
- ACTIVE DEVELOPMENT BRANCH: `main`
- SAFETY TAG: `pre-nvidia-2026-09-09`
- NEXT TASK: NVIDIA RENDERING REPAIR
