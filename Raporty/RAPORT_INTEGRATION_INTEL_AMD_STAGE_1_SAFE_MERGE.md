# TeleM Intel + AMD Integration — Stage 1

## 1. Starting state

- Branch: `integration/intel-amd`
- Starting HEAD / AMD freeze: `7e4e34e`
- `origin/amd-render`: `7e4e34ecae13eae947c0386443e6a7317b42256f`
- `origin/intel-render`: `8882d81c87a884459ec9a75d4d7f29b2137b4edc`
- Merge base: `0ca4d547d055a6e5b9f4628a90a1f7abceaef83c`
- Ahead/behind versus Intel: `39 10` (`integration/intel-amd...origin/intel-render`)
- Working tree before merge: clean
- AMD and Intel remote refs were not modified.

## 2. Source-of-truth documents

Read before merge: `AGENTS.md`, `BENCHMARKS.md`,
`AGENTS_BENCHMARK_SECTION.md`, AMD reports 5R.2, 5T and 5Z, and the latest
Intel production report `RAPORT_INTEL_ETAP_6C3_FINAL_LEAN_PERFORMANCE_ADJUDICATION.md`.

The canonical AMD workload remains `Video/GX020079.MP4` +
`Video/GX020079.fit`, `def_layout.json`, 3840x2160, 1131 frames.

## 3. Pre-merge diff summary

The Intel branch contains the Intel QSV/native pipeline and GUI policy changes,
large changes to shared orchestration and indicators, and a substantial cleanup
of reports, scratch data and generated native build directories. The generated
build directories and scratch logs were excluded from the integration result.
AMD governance documents, AMD configuration, AMD native exporter, native AMD
sources, canonical layout and AMD regression tests were retained from the
freeze.

## 4. Conflict list and resolution

| File/group | AMD intent | Intel intent | Resolution |
|---|---|---|---|
| `native/d3d11_amf_pipeline/src/*` | Preserve frozen AMF/D3D11 implementation | Older conflicting native snapshot | AMD freeze retained |
| `src/ffmpeg/amd_native_exporter.py` | Preserve AMD GPU map/charts/gauge/HUD and production defaults | Older conflicting exporter snapshot | AMD freeze retained |
| `src/ffmpeg/amd_config.py`, AMD governance tests | Production-default governance | Deleted by Intel cleanup | Restored from AMD freeze |
| `def_layout.json`, `presets/cycling_dashboard_v10.json` | Preserve canonical appearance and geometry | Intel-side layout changes | AMD canonical versions retained |
| `src/ffmpeg/streaming.py` | Existing AMD/NVIDIA/CPU orchestration | Intel QSV selection, residency, HDR and lifecycle policy | Intel orchestration retained; AMD native path remains separately selected |
| `src/ffmpeg/command_builder.py` | Existing non-Intel paths | Intel QSV/P010/GPU-resident command branches | Intel version retained; Intel rotation follows its autorotate contract |
| `src/gui/qt/*`, `src/gui/telemetry_manager.py` | Existing GUI integration | Intel backend and Auto HUD policy | Intel changes retained |
| `src/indicators/*` | AMD pixel/Z-order and GPU transfer contracts | Older common indicator changes | AMD indicator implementations retained |
| `src/telemetry_precompute.py` | Existing cache semantics | Intel aware/naive datetime and lean precompute fixes | Semantically merged: UTC normalization and `lean_indicator` support added |
| `src/ffmpeg/intel_backend.py` | Existing Intel selection contract | QSV device-pinning adapter contract | Added `IntelDeviceSelection`, FFmpeg device args and adapter index |
| `src/indicators/lean.py` | AMD exact lean/GPU transform behavior | Explicit cache lifecycle | Added `clear_lean_caches()` without replacing renderer |
| generated build/scratch artifacts | Not production inputs | Present on Intel branch | Excluded from result |

## 5. Architecture after merge

- Common orchestration selects one backend per export.
- AMD uses `AMD_NATIVE_D3D11`, native D3D11 composition and AMF through the
  retained AMD exporter/native sources.
- Intel uses the Intel QSV/device-pinning path from the Intel branch, including
  GPU-resident and CPU-reference/P010 decisions.
- NVIDIA and CPU/reference paths were not intentionally changed by this stage.
- Intel state is resolved into an explicit per-export device selection; no
  AMD configuration is used to select Intel hardware.

## 6. Backend selection proof

Static proof: `intel_backend.py` resolves vendor `0x8086`, validates D3D11/QSV,
and fails with `IntelBackendError` instead of cross-GPU fallback when Intel is
explicitly requested. `streaming.py` calls that resolution only for
`encoder == "intel"`; other encoders use their existing detection paths.

Software unit coverage for Intel resolution and Auto HUD policy: PASS.
Real AMD/NVIDIA hardware selection and second-export cross-contamination:
NOT TESTED.

## 7. AMD production config proof

AMD governance/configuration files and AMD native exporter were retained from
`7e4e34e`. The documented production contract remains SYNC/Q0,
VP REFERENCE/pool 8, AMF REFERENCE, GPU map, GPU_SPLIT charts, GPU gauge/lean,
GPU HUD, DIRTY/EXACT/DIRECT and FUSED NV12. The governance defaults
`AMD_ABOVE_BATCHED=0`, `AMD_ABOVE_FINE_DIRTY=0`,
`AMD_HUD_BUFFER_MODE=REFERENCE`, `AMD_BASE_CONVERT_MODE=VP_REFERENCE` and
`AMD_ABOVE_COMMON_TEXT_FAST=0` were not replaced.

## 8. Intel production config proof

Intel QSV device selection, CPU-reference P010 handling, GPU-resident policy,
Auto HUD resolution policy and QSV bitrate contract were retained from
`origin/intel-render` and covered by focused tests. Production Intel hardware
validation is pending.

## 9. Visual parity

AMD map, lean, speed gauge, charts, BAR geometry, labels, fonts, opacity and
preview/render layout were protected by retaining the AMD freeze implementations
and canonical layout. Full post-merge pixel comparison is **NOT TESTED**.
Intel visual/HDR/audio parity is **NOT TESTED on hardware**.

## 10. Test results

Focused integration suite after semantic fixes: **34 passed** for Intel,
lean, lifecycle, precompute and preview/export policy tests.

Full `python -m pytest -q`: **1115 passed, 42 skipped, 62 failed, 5 errors**.
The failures include missing non-canonical local fixtures/golden assets and
legacy assertions inconsistent with current contracts; they are not accepted
as a passing merge gate. Seven BAR failures were reproduced in code retained
from the AMD starting tree and were not changed.

`python -m compileall -q src tests`: PASS.
Native CMake build: **NOT TESTED / BLOCKED** because `cmake` is not available
in PATH.

## 11. AMD canonical result

- Export: NOT TESTED after merge
- 1131-frame accounting: NOT TESTED after merge
- Pre-encode parity: NOT TESTED
- HDR: NOT TESTED after merge
- Audio: NOT TESTED after merge
- Map/lean/gauge/charts/BAR visual checks: NOT TESTED after merge

## 12. AMD performance delta vs freeze

NOT TESTED. No canonical warmup plus three-run AMD benchmark was executed.
No performance claim is made.

## 13. Intel validation

**PASS SOFTWARE / INTEL HARDWARE VALIDATION PENDING.** Focused software tests
pass. Hardware export, HDR/P010, audio, visual parity and performance versus
`origin/intel-render` remain pending.

## 14. Multi-file / lifecycle

Focused cancel/writer lifecycle tests pass. Canonical multi-file, second export,
cancel-then-export, project reopen and backend reset hardware workflows:
NOT TESTED.

## 15. Remaining differences vs AMD freeze

Shared Intel orchestration and GUI policy are newer than the AMD freeze.
`telemetry_precompute.py`, `compositor.py`, `intel_backend.py`, selected GUI
files, `streaming.py` and `command_builder.py` contain the integration changes.
AMD native/exporter/indicator implementations and canonical layout remain the
freeze versions. Each remaining shared difference requires the pending full
regression gates before acceptance.

## 16. Remaining differences vs Intel branch

AMD-specific exporter/native/indicator/governance files intentionally differ
from Intel's older snapshot. AMD benchmark governance and canonical layout were
restored. Generated build and scratch artifacts were excluded. These are
intentional backend-isolation differences, not attempted unification.

## 17. Files changed

The merge stages Intel reports, Intel tests and Intel orchestration/GUI changes;
retains AMD production files; and adds small compatibility changes to
`intel_backend.py`, `lean.py`, `telemetry_precompute.py`, `compositor.py` and
the lifecycle/render-tab test contracts. See `git diff --cached --name-status`
for the complete staged inventory.

## 18. Risks

- Full suite is not green.
- AMD canonical parity and performance are not proven after merge.
- Intel hardware validation is pending.
- Native build could not run because CMake is unavailable.
- The Intel autorotate contract intentionally differs from legacy test
  expectations for manual `vflip,hflip`; this requires hardware/output proof.
- Incoming Intel branch contains historical reports with non-canonical dataset
  pairings; they were retained as historical evidence, not used as benchmarks.

## 18A. Stage 2 AMD reference binary contract

The current `telem_amd_native.dll` was manually copied into this worktree from
`C:\_DEV\TeleM\native\d3d11_amf_pipeline\bin\`. It is recorded as a frozen
AMD oracle/reference binary only:

- Path: `C:\_DEV\TeleM-integration\native\d3d11_amf_pipeline\bin\telem_amd_native.dll`
- SHA256: `D309A73551E80A61DC1AD8F6EDB5E47EA0C519927D995F4C7BA7F6390E3E846E`
- Size at verification: 3,059,698 bytes
- Verified before any fresh-build attempt: PASS

AMD rendering was reported functional with this copied binary, but this does
not satisfy the native build gate. Stage 2 must build the DLL from the native
sources in this worktree, record the fresh DLL hash, prove AMD export on that
fresh build, and repeat correctness/parity gates. The frozen oracle must not be
overwritten before its path and hash are recorded; the oracle hash must remain
available for comparison.

## 19. Commit SHA

**NO COMMIT — GATE FAILED**

## 20. Final verdict

**FAIL — TEST REGRESSION / VALIDATION INCOMPLETE**

The merge is left locally uncommitted on `integration/intel-amd` for inspection.
No push, reset, rebase, force operation or modification of AMD/Intel remote
branches was performed.
