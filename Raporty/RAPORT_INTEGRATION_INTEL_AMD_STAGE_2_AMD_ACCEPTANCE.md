# TeleM Intel + AMD Integration — Stage 2 AMD Acceptance

## 1. Status

**FAIL — ACCEPTANCE BLOCKED**

Stage 2 was executed on the existing local merge state on
`integration/intel-amd`. No push or commit was performed.

## 2. Starting state and frozen oracle

- HEAD: `7e4e34e`; merge remains local and uncommitted.
- Oracle: `C:\_DEV\TeleM-integration\native\d3d11_amf_pipeline\bin\telem_amd_native.dll`
- Oracle SHA256 before build attempt:
  `D309A73551E80A61DC1AD8F6EDB5E47EA0C519927D995F4C7BA7F6390E3E846E`
- Oracle size: 3,059,698 bytes.
- Hash after build attempt: unchanged.

The copied DLL was used only as a frozen reference. It was not treated as a
fresh-build result and did not satisfy the native build gate.

## 3. Failure adjudication

The AMD freeze control worktree was checked out at exactly `7e4e34e` and tested
under the same local material/dependency conditions:

| Tree | Passed | Skipped | Failed | Errors |
|---|---:|---:|---:|---:|
| AMD freeze control | 1097 | 42 | 57 | 5 |
| Integration after fixes | 1126 | 37 | 56 | 5 |

The failures common to the freeze are pre-existing, not merge regressions.
They are:

- `test_amd_above_exact_tight_bbox_etap10r` — 8 tests;
- `test_amd_native_etap2`, `test_amd_native_etap4`, `test_amd_native_etap5b`;
- `test_bar_orientation_contract` — 7 tests;
- `test_chart_seek_history` — 3 tests;
- `test_distance_bar_scale_contract`, `test_distance_optimization`;
- `test_etap10k2_acceptance` — 2 tests;
- `test_etap10k3_fit_speed` — 1 failure and 5 missing-fixture errors;
- `test_etap10k_fit_gui` — 4 tests;
- `test_etap10n2_distance_marker` — 3 tests;
- `test_etap10n3_distance_marker` — 5 tests;
- `test_etap5e1_chart_prefix` — 2 tests;
- `test_etap5e3_dynamic_prefix`;
- `test_etap8q_dirty_text_cache`, `test_etap8s_flush_batching`;
- `test_golden_parity_etap4` — 3 tests;
- `test_gui_etap4a1_indicator_interaction` — 3 tests;
- `test_pixel_indicator_style`;
- `test_solar_pct` — 5 tests.

Observed infrastructure causes include missing `Video/GX010115.json`, missing
golden crops and missing `Jazda_na_rowerze_w_porze_lunchu.fit`. Source-level
assertion failures and synthetic parity failures reproduce on the freeze.

Two remaining Intel failures are stale relative to the Intel reference:

- `tests/test_video_helpers.py::test_intel_and_cpu_pipeline_unchanged`;
- `tests/test_video_helpers.py::test_intel_rotation180_no_nv2`.

They require manual `vflip,hflip`, while the Intel reference Stage 5D/6C
contract explicitly uses autorotate and removes manual transforms to prevent
double rotation. Reintroducing those transforms would be a regression.

## 4. Actual integration fixes

The staged merge contains targeted compatibility changes only:

- explicit Intel adapter index and QSV/D3D11 device contract;
- `clear_lean_caches()` lifecycle hook while retaining AMD rendering;
- aware/naive UTC normalization in telemetry precompute;
- `lean_indicator` precompute support;
- explicit `auto_scale` gating for speed and altitude ranges.

No new AMD optimization, layout, map, GPU migration or native AMD rewrite was
performed.

## 5. Fresh native build

Existing CMake was found at:

`C:\Users\Malcerz\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\cmake\data\bin\cmake.exe`

The project was configured from the worktree
`native/d3d11_amf_pipeline/CMakeLists.txt` in an external temporary build
directory. Configuration failed before compilation because no Ninja build
program and no C++ compiler were available:

```text
CMAKE_MAKE_PROGRAM is not set
CMAKE_CXX_COMPILER not set
```

**NATIVE BUILD = BLOCKED / NOT PASS.** The oracle was copied to a separate
temporary path before this attempt and was not overwritten.

## 6. Canonical AMD acceptance

Required workload:

```text
Video/GX020079.MP4
Video/GX020079.fit
def_layout.json
3840x2160 / 1131 frames
AMD_NATIVE_D3D11 / production defaults
```

- Fresh-build export: **NOT TESTED — build blocked**
- 1131-frame integrity: **NOT TESTED**
- Exact pre-encode pixel parity: **NOT TESTED**
- `max_diff`, MAE, different pixels: **NOT TESTED**
- Map/lean/gauge/charts/BAR visual gates: **NOT TESTED**
- HDR/Main10/P010/BT.2020 HLG: **NOT TESTED**
- Audio/A-V continuity: **NOT TESTED**

## 7. Performance and lifecycle

AMD warmup plus three canonical performance runs: **NOT TESTED**.
Fresh-build multi-file, second export, cancel-then-export, project reopen,
resolution change and backend reset: **NOT TESTED**.

Focused software lifecycle, Intel, lean and precompute suite: **34 passed**.
Static review confirms Intel resolution is scoped to `encoder == "intel"` and
does not cross-fallback; AMD exporter/configuration remains from the freeze.

## 8. Final tests

```text
Final full pytest: 1126 passed, 37 skipped, 56 failed, 5 errors
Python compileall: PASS
```

The final pytest is not green, and native/hardware/parity/performance gates are
unproven.

## 9. Commit gate and verdict

The required commit conditions are not met: fresh build, AMD export, exact
parity, HDR/audio, performance and lifecycle validation are unavailable, and
the final pytest fails.

**NO COMMIT — GATE FAILED**

**FAIL — AMD ACCEPTANCE BLOCKED BY NATIVE TOOLCHAIN AND TEST GATES**

The frozen oracle remains preserved by hash. The worktree remains local and
uncommitted on `integration/intel-amd`; no AMD/Intel remote branch or tag was
modified.
