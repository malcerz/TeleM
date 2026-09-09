# AMD SINGLE-PASS A/V MUX — ACCEPTANCE REPORT

Date: 2026-09-08  
Backend: `AMD_NATIVE_D3D11`  
Worktree: dirty, pre-existing changes preserved  

## Task

Remove the production multi-file full-size Stage A/Stage C copy.  The AMD
exporter must stream the live HEVC bitstream directly to the final `.part`
MP4 and provide the canonical audio timeline as a small concat-demuxer plan.
The final video remains `-c:v copy`; audio is copied when FFmpeg accepts it.

## Initial state

The previous production path rendered a full-size
`.part.temp_video.mp4`, then performed a second full-size Stage C remux.  The
real 85,574-frame proof reached a 26,517,705,374-byte Stage A artifact and
failed Stage C with `No space left on device`; the old path then attempted a
software fallback and raised `MemoryError`.  That proof is documented in
`RAPORT_AMD_FINAL_85574_PRODUCTION_PROOF.md`.

## Implementation

Changed production AMD files:

- `src/ffmpeg/amd_native_exporter.py`
  - Added `AMD_SINGLE_PASS_AV_MUX` (default `1`) for multi-file AMD exports.
  - Reuses the already GUI/cut-resolved `VideoTimeline` to write a tiny
    source-local audio concat plan (`file`, `inpoint`, `outpoint` per clip).
  - Launches one FFmpeg topology: live HEVC pipe + concat audio input,
    `-map 0:v -map 1:a? -c:v copy -c:a copy`, output directly to `.part`.
  - Skips Stage C on the successful single-pass path and removes the plan
    after atomic rename; successful runs leave no `.part.temp_video.mp4`.
  - Keeps the previous two-stage implementation only when the explicit
    `AMD_SINGLE_PASS_AV_MUX=0` compatibility/recovery switch is used.
  - Raises `AMDNativeFinalizationError` for live-mux, output-validation, zero-
    frame, audio-plan-write, and legacy Stage C finalization failures.
- `src/ffmpeg/streaming.py`
  - Propagates `AMDNativeFinalizationError`; finalization/storage failures do
    not silently launch the software exporter.
- `tests/test_amd_direct_mp4_mux.py`
  - Added canonical source-local audio-plan coverage and made the legacy test
    explicit with `AMD_SINGLE_PASS_AV_MUX=0`.

No Intel, NVIDIA, QSV, CUDA, HUD compositor, child containment, or renderer
optimization code was intentionally changed for this task.

## Canonical timeline coverage

The plan is derived from the effective `VideoTimeline` passed by GUI dispatch,
including local clip bounds.  This covers single clips, two clips,
cross-boundary ranges, a fragment beginning in clip 2, multiple cuts, and the
full timeline without reconstructing ranges from filenames or timestamps.

## Tests

Automated:

```text
python -m py_compile src/ffmpeg/amd_native_exporter.py src/ffmpeg/streaming.py tests/test_amd_direct_mp4_mux.py
python -m pytest -q tests/test_amd_direct_mp4_mux.py tests/test_amd_child_process.py tests/test_amd_gui_range_contract.py
24 passed in 3.30s
```

Real GUI acceptance (no 85,574-frame render):

Input project: `GX010244.MP4` + `GX010245.MP4`, `12_naprawiony.fit`,
`GX010244.layout.json`, normal GUI, AMD GPU HUD and GPU Preview enabled.

| Run | Result | Video frames | Audio | Residue |
|---|---|---:|---|---|
| 1–5 × 1000 | completed | 1000 each | AAC 48 kHz stereo | none |
| cancel @ 300 | cancelled | n/a | n/a | none |
| post-cancel × 1000 | completed | 1000 | AAC 48 kHz stereo | none |
| controlled child error | failed as expected | n/a | n/a | none |
| 10000, cross-clip | completed | 10000 | AAC 48 kHz stereo | none |
| post-10000 × 1000 | completed | 1000 | AAC 48 kHz stereo | none |

The acceptance JSON had no validation failures or run errors.  The parent GUI
remained usable after cancellation and controlled failure; subsequent renders
completed.  The optional Windows-event-log summarizer returned no events but
also reported a harness `NoneType.strip` diagnostic, so that auxiliary check is
not treated as fully proven.

The 10,000-frame output was 1,863,566,180 bytes.  FFprobe reported HEVC
3840×2160 at `30000/1001`, exactly 10,000 video frames, and AAC 48 kHz stereo;
the output directory contained only final MP4/profile files.  The profile
records `benchmark.single_pass_av_mux=true`, `stage_a.mode=N/A`, and zero
Stage C elapsed/output bytes.

## Performance

For the same real 10,000-frame cross-clip workload:

| Metric | Previous two-stage proof | Single-pass run |
|---|---:|---:|
| Render FPS | 41.698 | 41.082 |
| Effective FPS | 40.194 | 39.926 |
| Video render wall | 239.820 s | 243.413 s |
| Finalization mux | 3.920 s | 1.447 s |
| Total native export | 248.796 s | 250.464 s |

The observed render/effective FPS are within the normal run-to-run variation;
the finalization phase is materially shorter and no second full-size file is
created.  Exact OS peak-disk telemetry, CPU/GPU utilization sampling, and
packet-level PTS gap/overlap analysis were **NOT TESTED** in this bounded run.

## Risks / recovery

- `AMD_SINGLE_PASS_AV_MUX=0` remains an explicit legacy Stage A → Stage C
  path for controlled recovery; it is not selected automatically after a
  successful single-pass render.
- A single-pass finalization/storage failure is surfaced to the caller and is
  not hidden by software fallback.  Incomplete `.part` and audio-plan files
  are cleaned by the existing cancellation/error cleanup policy.
- A real single-file production GUI smoke was **NOT TESTED** in this task;
  the pre-existing single-file direct path is unchanged and unit-covered.

## Backend isolation

Only AMD dispatch/finalization code and AMD direct-mux tests were changed for
this task.  No Intel/NVIDIA encoder, decoder, filter, device-selection, or HUD
layer behavior was modified.

## Final summary

Implementation and multi-file acceptance: **PASS**.  The full-size Stage A /
Stage C copy is removed from the default AMD multi-file path, and cancellation
and controlled child failure leave the GUI ready without orphan files.

Production “READY” sign-off is **NOT PROVEN** until a single-file production
smoke, packet-level audio PTS validation, and dedicated OS disk/CPU/GPU peak
sampling are completed.  No full 85,574-frame render was run for this task.

```text
TASK: AMD single-pass A/V mux; remove full-size Stage C copy
STATUS: IMPLEMENTED; bounded multi-file acceptance PASS; final production sign-off NOT PROVEN
```
