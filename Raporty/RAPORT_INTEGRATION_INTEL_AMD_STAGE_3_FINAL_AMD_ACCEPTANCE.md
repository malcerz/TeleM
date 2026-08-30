# TeleM Intel + AMD Integration — Stage 3

## 1. Starting state

- Repository: `C:\_DEV\TeleM-integration`
- Branch: `integration/intel-amd`
- Starting HEAD: `7e4e34ecae13eae947c0386443e6a7317b42256f`
- AMD freeze: `7e4e34e`
- Intel reference: `8882d81c87a884459ec9a75d4d7f29b2137b4edc`
- Merge conflicts were resolved, but the merge remains uncommitted.
- No push performed.

The frozen AMD runtime binary was treated as an oracle only and was not modified.

## 2. Toolchain discovery

Existing CMake:

```
C:\Users\Malcerz\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\cmake\data\bin\cmake.exe
cmake version 4.4.2
```

No usable native C++ toolchain was found: `cl.exe`, `clang.exe`, `clang-cl.exe`, `msbuild.exe`, `ninja.exe`, `nmake.exe`, and `vswhere.exe` were absent. Standard Visual Studio 2022/2026 and Build Tools directories were also absent.

Explicit probes:

- `-G "Visual Studio 18 2026" -A x64`: `could not find any instance of Visual Studio`
- `-G "NMake Makefiles"`: no `nmake`, followed by `CMAKE_CXX_COMPILER not set`

No compiler, SDK, Ninja, MinGW, or Visual Studio component was installed.

## 3. Fresh native build

Sources:

```
C:\_DEV\TeleM-integration\native\d3d11_amf_pipeline
```

Configure commands, using external output directories:

```
cmake -S C:\_DEV\TeleM-integration\native\d3d11_amf_pipeline -B C:\Temp\TeleM-integration-native-int3-vs-20260830 -G "Visual Studio 18 2026" -A x64
cmake -S C:\_DEV\TeleM-integration\native\d3d11_amf_pipeline -B C:\Temp\TeleM-integration-native-int3-nmake-20260830 -G "NMake Makefiles"
```

Result: **BLOCKED / NOT TESTED**. Configuration did not reach compilation. No fresh `telem_amd_native.dll`, compiler version, or build SHA256 exists.

## 4. Oracle vs fresh DLL

| Artifact | Path | Size | SHA256 |
|---|---|---:|---|
| Frozen AMD oracle | `native/d3d11_amf_pipeline/bin/telem_amd_native.dll` | 3,059,698 | `D309A73551E80A61DC1AD8F6EDB5E47EA0C519927D995F4C7BA7F6390E3E846E` |
| Safety copy | `.oracle/amd-freeze/telem_amd_native.dll` | 3,059,698 | `D309A73551E80A61DC1AD8F6EDB5E47EA0C519927D995F4C7BA7F6390E3E846E` |
| Fresh integration DLL | — | — | **NOT BUILT** |

The safety copy is outside build output and ignored/uncommitted. The oracle hash remained unchanged.

## 5. AMD runtime DLL proof

The existing oracle had previously rendered `AMD_NATIVE_D3D11`, but it is not a fresh integration build. Fresh-DLL runtime proof is **NOT TESTED / NOT PROVEN**.

## 6. Effective production config

Canonical workload:

```
Video/GX020079.MP4
Video/GX020079.fit
def_layout.json
3840x2160, 1131 frames
AMD_NATIVE_D3D11, --production-defaults
```

The required effective contract remains the AMD freeze contract: synchronous processing, Q0, VP_REFERENCE, processor ring 1, output pool 8, AMF_REFERENCE, GPU map, GPU_SPLIT charts, GPU gauge, GPU lean, GPU_HUD, DIRTY, EXACT, DIRECT, FUSED NV12; `AMD_ABOVE_BATCHED=0`, `AMD_ABOVE_FINE_DIRTY=0`, `AMD_HUD_BUFFER_MODE=REFERENCE`, `AMD_BASE_CONVERT_MODE=VP_REFERENCE`, `AMD_ABOVE_COMMON_TEXT_FAST=0`.

Fresh-build effective configuration is **NOT TESTED**.

## 7. Canonical 1131f export

**NOT TESTED** on a fresh DLL. The copied oracle cannot satisfy this gate.

## 8. Exact pixel parity

**NOT TESTED** on a fresh integration DLL; no fresh pre-encode compositor checkpoints were produced. Required checkpoints are `0, 1, 15, 30, 45, 150, 300, 600, 900, 1130`, with `MaxDiff = 0` and `DifferentPixels = 0`.

| frame | MaxDiff | DifferentPixels | map | lean | gauge | charts | BAR |
|---:|---:|---:|---|---|---|---|---|
| 0, 1, 15, 30, 45, 150, 300, 600, 900, 1130 | — | — | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED | NOT TESTED |

## 9. Preview/render parity

The focused software parity suite passed (`34 passed`), covering existing integration contracts. Hardware/runtime preview-render parity on a fresh DLL is **NOT TESTED**. No layout was changed.

## 10. Frame/HDR/audio integrity

Fresh canonical export integrity is **NOT TESTED**. Frame count, dropped/duplicated frames, duration, audio, A/V sync, codec/profile, Main10/P010, BT.2020, and HLG metadata are **NOT PROVEN** for a fresh build.

## 11. Performance

The required three paired warm runs (or five if unstable) were **NOT TESTED** because no fresh DLL could be built. No performance claim is made.

| pair | REF wall | MERGE wall | delta |
|---:|---:|---:|---:|
| 1–3 | — | — | NOT TESTED |

## 12. Lifecycle

Fresh-DLL canonical export, second export, cancel, export-after-cancel, project reopen, layout reload, resolution change, return to 4K, and subsequent export are **NOT TESTED**. Native context, AMF, VP, map, gauge, lean, charts, config, and dirty-region lifecycle are **NOT PROVEN**.

## 13. Final tests

```
python -m pytest -q
python -m compileall -q src tests
```

```
TOTAL PASS  = 1126
TOTAL SKIP  = 37
TOTAL FAIL  = 56
TOTAL ERROR = 5
compileall  = PASS
```

Failure adjudication follows INT-2:

- `NEW MERGE REGRESSIONS = 0`, supported by AMD-freeze control comparison.
- Historical renderer/fixture/test failures reproduce on AMD freeze.
- Fixture/environment blocks include missing local video/FIT/golden assets and the unavailable native toolchain.
- Two Intel rotation assertions are stale against the current Intel autorotate-on contract; restoring manual `vflip,hflip` would violate the reference behavior.

## 14. Intel status

- INTEL SOFTWARE VALIDATION = PASS (focused integration validation and INT-2 adjudication).
- INTEL HARDWARE VALIDATION = PENDING.
- Intel renderer was not changed in this stage.

## 15. Files changed

No source changes were made in INT-3. The resolved/staged INT-1 integration changes and reports remain staged. This report was added:

```
Raporty/RAPORT_INTEGRATION_INTEL_AMD_STAGE_3_FINAL_AMD_ACCEPTANCE.md
```

The ignored safety copy is `.oracle/amd-freeze/telem_amd_native.dll`.

## 16. Commit SHA

**NONE.** The commit gate was not satisfied. No commit and no push were performed.

## 17. Final verdict

# FAIL — NATIVE BUILD

Acceptance is blocked because the machine has CMake but no installed MSVC/Visual Studio/Clang/MinGW compiler or build program. Therefore the fresh AMD DLL, fresh runtime export, exact pixel parity, frame/HDR/audio integrity, performance regression, and lifecycle gates remain untested. The frozen AMD oracle is preserved with its original SHA256 and was not accepted as a fresh build.

---

# INT-3 continuation after toolchain recovery

The original native-toolchain block was resolved after Visual Studio Build Tools 2022 with the C++ workload was installed. This continuation supersedes the previous blocked-build statements above.

## Toolchain and fresh DLL

- Visual Studio Build Tools: 17.14.37614.0
- MSVC compiler: 19.44.35228.0 / toolset 14.44.35207
- CMake: 4.4.2
- Generator: Visual Studio 17 2022, architecture x64
- Configure: cmake -S C:\_DEV\TeleM-integration\native\d3d11_amf_pipeline -B C:\Temp\TeleM-integration-native-int3-vs2022 -G "Visual Studio 17 2022" -A x64
- Build: cmake --build C:\Temp\TeleM-integration-native-int3-vs2022 --config Release --target telem_amd_native
- Result: PASS
- Fresh DLL: C:\Temp\telem_amd_native_INT3_fresh_integration.dll
- Fresh size: 203,776 bytes
- Fresh SHA256: 79EDE9BCAEC9EA8924813B72619AC953C1B8FB6B0EF8F288D3A4B34C3E91A72E
- ABI export inspection: PASS; 67 named exports including create/process/flush/close and all AMD feature exports.

The native source needed one minimal compile-compatibility correction: <string> was added to d3d11_vp_pipeline.cpp for existing std::to_string uses. The same omission exists in the AMD freeze source, so this was not adjudicated as a merge regression and no renderer semantics were changed.

The oracle was copied before the build and restored after every fresh/reference run. Oracle SHA256 and final runtime SHA256 both remained D309A73551E80A61DC1AD8F6EDB5E47EA0C519927D995F4C7BA7F6390E3E846E.

## Fresh AMD runtime and canonical export

Fresh runtime smoke: PASS. Log proved AMD_NATIVE_D3D11, ABI 9, AMF InitDX11 SUCCESS, GPU map, GPU_SPLIT charts, GPU gauge, GPU lean, 60/60 frames, and audio present.

Canonical pairing used exactly:

- C:\_DEV\TeleM\Video\GX020079.MP4
- C:\_DEV\TeleM\Video\GX020079.fit
- C:\_DEV\TeleM-integration\def_layout.json
- 3840x2160 / 1131 frames / AMD_NATIVE_D3D11

The media pairing is external because the integration worktree contains only the telemetry archive; no alternate pairing was substituted.

Fresh canonical export: PASS.

- Encoded/muxed frames: 1131 / 1131
- Video render wall: 28.860 s
- Render FPS: 39.189
- User effective FPS: 35.663
- Audio present: YES
- Effective production config: SYNC, Q0, VP REFERENCE, pool 8, AMF REFERENCE, GPU map, GPU_SPLIT charts, GPU gauge, GPU lean, GPU_HUD, DIRTY, EXACT, DIRECT, FUSED NV12.

## Exact pre-encode pixel parity

Fresh and oracle checkpoint PNGs were compared at frames 0, 1, 15, 30, 45, 150, 300, 600, 900, 1130.

| frame | MaxDiff | MAE | DifferentPixels | map | lean | gauge | charts | BAR |
|---:|---:|---:|---:|---|---|---|---|---|
| 0, 1, 15, 30, 45, 150, 300, 600, 900, 1130 | 0 | 0 | 0 | PASS | PASS | PASS | PASS | PASS |

Exact pre-encode parity: PASS.

## Preview/render and frame/HDR/audio integrity

Focused preview/render software parity: PASS (34 passed).

Fresh and oracle canonical container metadata matched:

- video: HEVC Main, yuv420p, 1131 frames, 37.738077 s, bt709
- audio: AAC LC, stereo 48 kHz, 1768 frames, 37.717333 s

The input is HEVC Main 10, yuv420p10le, BT.2020 with ARIB STD-B67 HLG. Both fresh and oracle outputs are 8-bit Main/bt709, so relative freeze parity is PASS but preservation of the requested HDR/Main10/BT.2020/HLG contract is FAIL. No dropped or duplicated video frames were observed; audio and duration were present and matched the oracle.

## Performance regression

Three paired full 1131-frame runs were completed:

| pair | REF wall (ms) | FRESH wall (ms) | delta |
|---:|---:|---:|---:|
| 1 | 29632.157 | 28533.542 | -3.708% |
| 2 | 28710.810 | 28858.365 | +0.514% |
| 3 | 28992.237 | 28611.265 | -1.314% |

- REF mean: 29111.735 ms
- FRESH mean: 28667.724 ms
- Mean regression: -1.525%
- Paired median delta: -1.314%

Performance gate: PASS (within the 3% limit).

## Lifecycle

On the fresh DLL in one process: first export PASS, second export PASS, 640x360 resolution change PASS, return to 4K PASS, cancel returned False as required, and export after cancel PASS. Native contexts closed cleanly and no stale-state failure was observed.

Lifecycle gate: PASS for tested operations.

## Final software gate and adjudication

- pytest: 1126 passed, 37 skipped, 56 failed, 5 errors
- compileall: PASS
- NEW MERGE REGRESSIONS = 0

The 56 failures and 5 errors remain the INT-2-adjudicated baseline/fixture/environment failures; the two Intel rotation assertions remain stale against autorotate-on. No additional merge regression was introduced by INT-3.

## Final verdict

# FAIL — AMD FRAME/HDR/AUDIO

Native build, fresh AMD runtime, canonical 1131-frame export, exact pre-encode pixel parity, performance, and lifecycle passed. Acceptance remains blocked because the canonical input’s Main10/BT.2020/HLG contract is not preserved in either fresh or oracle output (Main/yuv420p/bt709). Therefore the commit gate is not satisfied.

Commit SHA: NONE. No commit and no push were performed.
