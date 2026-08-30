# TeleM Intel + AMD Integration — Stage 3A HDR Adjudication

## 1. Scope

This stage adjudicates the INT-3 HDR/frame-integrity finding only. No benchmark or pixel-parity gate was rerun. The INT-3 report was not modified.

## 2. Clean AMD freeze worktree

- Worktree: C:\Temp\TeleM-baseline-int2
- Exact HEAD: 7e4e34ecae13eae947c0386443e6a7317b42256f
- Worktree status: clean
- Runtime binary was temporarily supplied from the frozen oracle because the clean freeze commit does not track native binaries.
- Oracle SHA256: D309A73551E80A61DC1AD8F6EDB5E47EA0C519927D995F4C7BA7F6390E3E846E

The temporary binary was not a source or commit change.

## 3. Canonical workload

The same canonical workload was used:

- Source video: C:\_DEV\TeleM\Video\GX020079.MP4
- FIT: C:\_DEV\TeleM\Video\GX020079.fit
- Layout: def_layout.json from the clean AMD freeze worktree
- Resolution: 3840x2160
- Frames: 1131
- Backend: AMD_NATIVE_D3D11
- Configuration: production defaults with PRECOMPUTED telemetry

Clean AMD freeze export result: PASS. The exporter reported 1131 encoded and 1131 muxed frames, with audio present.

## 4. ffprobe metadata comparison

| field | source | clean AMD freeze output | fresh integration output |
|---|---|---|---|
| profile | HEVC Main 10 | HEVC Main | HEVC Main |
| pix_fmt | yuv420p10le | yuv420p | yuv420p |
| color_space | bt2020nc | unset | unset |
| color_transfer | arib-std-b67 (HLG) | bt709 | bt709 |
| color_primaries | bt2020 | reserved | reserved |

Additional matching fields:

- clean freeze output: 1131 video frames, 37.738077 s; AAC LC audio, 1768 frames, 37.717333 s
- fresh integration output: 1131 video frames, 37.738077 s; AAC LC audio, 1768 frames, 37.717333 s

The output file byte hashes differ, as expected for separate hardware encoder runs, but the requested metadata fields and frame/audio counts match exactly.

## 5. Adjudication

Both the clean AMD freeze and fresh integration output convert the Main10/BT.2020/HLG source to Main/yuv420p/bt709. Therefore:

- PRE-EXISTING AMD BASELINE LIMITATION = YES
- NEW HDR REGRESSION = 0
- Integration HDR gate = PASS by freeze parity adjudication
- HDR was not fixed in this stage

The fresh integration pre-encode pixel parity remains the INT-3 result: all required checkpoints had MaxDiff 0, MAE 0, and DifferentPixels 0.

## 6. Earlier INT-3 gates

The existing INT-3 evidence remains valid:

- native Release x64 build = PASS
- fresh AMD runtime and export = PASS
- canonical 1131-frame export = PASS
- exact pre-encode parity = PASS
- performance regression = PASS (mean -1.525%, paired median -1.314%)
- lifecycle/second export/cancel/resolution changes = PASS
- Intel software validation = PASS
- NEW MERGE REGRESSIONS = 0
- final software failures remain INT-2-adjudicated baseline/fixture/stale-test failures

## 7. Final verdict

# PASS — SAFE INTEGRATION / PRE-EXISTING AMD HDR LIMITATION / INTEL HARDWARE PENDING

The clean AMD freeze reproduces the same HDR metadata limitation as the fresh integration output. HDR therefore does not block the integration acceptance under the defined freeze-parity rule.

## 8. Commit

Commit gate satisfied. Local commit is permitted and must not be pushed.
