# AMD CHILD PROCESS — FINAL GUI / MEMORY ACCEPTANCE

## Task

Final acceptance of the short-lived AMD render child in one long-lived, visible
TeleM GUI process.  The workload used the real user project:

- `D:\GoPro\2026-09-01\GX010244.MP4`
- `D:\GoPro\2026-09-01\GX010245.MP4`
- `D:\GoPro\2026-09-01\12_naprawiony.fit`
- the existing `GX010244.layout.json`
- AMD, source 3840x2160, full HUD, GPU Export Preview ON

Test date: 2026-09-08 (Europe/Warsaw).

## Final result

**NOT READY / FAIL**

The five-run child containment and parent resource behavior passed, as did
cancel recovery, controlled-error containment, event-log checks, the rendered
10,000-frame media file, and final orphan cleanup.  Production readiness is
blocked by three observed failures:

1. The normal GUI IN/OUT path stores boundary selections as `cut_regions`, but
   AMD native derives `total_frames` from the complete `VideoTimeline` and does
   not apply those cuts.  The first acceptance attempt therefore began the
   prohibited full 85,574-frame render.  It was stopped through normal GUI
   shutdown after this was proven; it was not allowed to complete.
2. Cancel at frame 300 left
   `run_cancel_1000f.mp4.part.temp_video.mp4` (11,859,896 bytes).
3. The 10,000-frame child produced a valid complete file and exited, but the
   parent `TeleM-RenderWorker` did not emit its terminal state even after several
   minutes.  The GUI window remained responsive, but the render session did not
   complete and Edit Preview/render readiness could not be restored normally.
   The application was closed with a normal `WM_CLOSE`; no orphan remained.

No production source was changed during this acceptance task.

## Initial state and safety

- Branch: `integration/intel-amd`
- Initial HEAD: `59277b4`
- The pre-existing dirty working tree was inspected and preserved.
- No reset, clean, restore, rebase, commit, push, system-setting change, or
  backend modification was performed.
- `D:\pagefile.sys`: 32,768 MB allocated.
- Commit limit observed: 64,317,124,608 bytes (59.90 GiB).
- The first invalid attempt was stopped rather than completing 85,574 frames.
  Its directory remains at
  `D:\GoPro\2026-09-01\TeleM_child_final_acceptance_20260908_090720` because the
  environment rejected the explicit recursive cleanup operation.  It is an
  acceptance artifact, not an orphan process.

## Test harness and range correction

The acceptance driver is `scratch/run_amd_child_final_gui_acceptance.py`.  It
opens the real `QApplication`, `AppController`, `MainWindow`, loads the project
through the normal GUI signal, selects AMD/source/Auto/Preview ON, and starts
each render through `RenderTab._on_render()`.

After the initial attempt exposed the AMD native range issue, the driver used
the existing `VideoTimeline.subset()` contract to pass two real source-local
segments directly to the renderer.  Every short run asserted `[500, 500] =
1000` frames.  The long run asserted `[5000, 5000] = 10000` frames.  This was a
test-only correction; the production GUI range bug remains unfixed and is a
release blocker.

## Required parent/child table

Values are post-run parent snapshots after ordinary `gc.collect()` and a
five-second cleanup wait.  MiB means 1,048,576 bytes.  The 10,000 row is the
last independently captured snapshot after the child had exited but while the
parent terminal-state hang persisted.

| Run | Parent PID | Child PID | Parent RSS MiB | Parent Private MiB | Private delta MiB | Threads | Handles | Child exited |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| baseline | 14816 | — | 1533.4 | 2743.2 | — | 72 | 1241 | N/A |
| 1 | 14816 | 17768 | 1670.1 | 2879.4 | +136.2 | 68 | 1238 | YES |
| 2 | 14816 | 22624 | 1772.5 | 2981.8 | +102.3 | 66 | 1234 | YES |
| 3 | 14816 | 7732 | 1854.7 | 3064.0 | +82.2 | 66 | 1230 | YES |
| 4 | 14816 | 24188 | 1908.9 | 3119.2 | +55.2 | 68 | 1238 | YES |
| 5 | 14816 | 12984 | 1955.2 | 3166.4 | +47.2 | 66 | 1230 | YES |
| cancel @ 300 | 14816 | 17852 | 2005.3 | 3216.3 | +49.9 | 66 | 1230 | YES |
| error | 14816 | 836 | 2062.8 | 3289.2 | +72.9 | 66 | 1236 | YES |
| 10000 | 14816 | 13056 | 2012.5 | 3316.0 | +26.8 | 58 | 1210 | YES; parent terminal hung |

All nine render attempts received unique child PIDs.  After final GUI shutdown,
`Get-Process`/`Win32_Process` found neither parent PID 14816 nor any listed
child/ffmpeg process.

## Memory, handles, threads, and system commit

Five-run parent private sequence in bytes:

```text
3,019,313,152
3,126,616,064
3,212,836,864
3,270,737,920
3,320,225,792
```

The per-run retained deltas decreased from 136.2 to 47.2 MiB.  This is not the
historical same-process linear +500/+700/+800 MiB pattern.  The automatic
acceptance plateau check passed.  There is still a small monotonically rising
warm-up/cache tail, so it should continue to be watched in a later fixed long
run.

Parent handles after runs 1–5 were `1238, 1234, 1230, 1238, 1230`; threads were
`68, 66, 66, 68, 66`.  Both are a clear plateau.

Short-run child peak private was 2685.6–2745.7 MiB; successful short-run child
peak RSS was 1864.6–1888.5 MiB.  During the 10,000-frame run an independent
snapshot observed child PID 13056 at RSS 1896.2 MiB/private 2735.3 MiB, 38
threads, and 885 handles.  This is an observation, not a proven long-run peak.
The entire child allocation disappeared on child exit.

System snapshots:

| Point | Committed | Commit limit | Available RAM |
|---|---:|---:|---:|
| loaded-GUI baseline | 29,935,738,880 B (27.88 GiB) | 64,317,124,608 B (59.90 GiB) | 16,722,423,808 B (15.57 GiB) |
| sampled acceptance peak | 33,722,978,304 B (31.41 GiB) | 64,317,124,608 B | — |
| after final GUI shutdown | 27,005,497,344 B (25.15 GiB) | 64,317,124,608 B | 18,531,934,208 B (17.26 GiB) |

**CHILD EXIT RECLAIMS MEMORY: PASS.**

## RenderJob pickle and startup

Normal GUI Edit Preview had already materialized all eight IMU
`LazySampleList` objects (274,920 samples each).  Consequently the real job was
larger than the prior synthetic/earlier measurement:

- pickle size: 106,162,781–106,162,819 bytes; mean 101.245 MiB
- pickle time: 12,710–13,201 ms; mean 12,967 ms
- child restored/startup: 14,237–14,734 ms; mean 14,510 ms
- first run parent transient private delta: 344,588,288 bytes
- first run retained pickle delta after GC: 67,719,168 bytes
- ninth run retained pickle delta after GC: 10,489,856 bytes

This is a significant startup cost and differs materially from the previous
~46.70 MiB/~1.65 s result.  Per instruction it was measured but not optimized
and the pickle contract was not changed.

## Five normal renders

Runs 1–5 each completed 1000/1000 frames, returned OS child exit code 0,
produced a valid output, and left no matching `.part`, named pipe, or child
process.  Each produced 67 GPU frame-tap Preview updates.  After every run:

- Export Preview stopped;
- `rendering`, `export_preview_gpu_tap`, and `export_preview_hevc` were false;
- the export preview session and queued payload were absent;
- the normal Edit Preview slot and HUD overlay were visible;
- no stale timestamp/payload/signal remained.

**5 SEQUENTIAL AMD CHILD RENDERS: PASS.**

## Cancel and recovery

- Cancel source: GUI button path.
- Cancel frame: 300 (within required 200–500).
- Terminal state: `cancelled`.
- Child PID 17852 exited; no orphan or stale pipe remained.
- Parent returned to the resource plateau and Edit Preview state.
- A new real 1000-frame render started in child PID 1244 and completed.
- Failure: `run_cancel_1000f.mp4.part.temp_video.mp4` remained at 11,859,896
  bytes.

**CANCEL: FAIL** because scratch/output cleanup is part of the criterion.
**NEXT RENDER AFTER CANCEL: PASS.**

## Controlled child error and recovery

A test-only unexpected renderer keyword caused a deterministic child-side
`TypeError`.  The full traceback reached the parent, child PID 836 disappeared,
GPU Export Preview stopped, and normal Edit Preview returned.  The next real
render (the 10,000-frame run) started in child PID 13056.

The diagnostic log was intentionally retained at
`scratch\amd_child_8_1788854442289.log`.  The child communicated a logical error
but its OS exit code was 0; error containment passed, but that exit-status
semantic is a risk worth fixing or explicitly documenting.

**ERROR CONTAINMENT: PASS.**
**NEXT RENDER AFTER ERROR: PASS.**

## 10,000-frame full-HUD run

The child rendered and muxed exactly 10,000 frames.  AMD profile:

| Metric | Value |
|---|---:|
| precompute/HUD preparation | 2,858.574 ms |
| export start to first encoded frame | 4,792.196 ms |
| video render wall | 237,483.113 ms |
| audio/final mux | 3,618.224 ms |
| export total | 245,958.517 ms |
| Render FPS | 42.108 |
| Effective FPS | 40.657 |
| profile total wall | 244.983 s |
| Preview updates | 667 |
| Preview drops/restarts | 0 / 0 |

Frame accounting is internally exact: requested, decoded, HUD, native
processed, VP processed, AMF submitted/output, and muxed are all 10,000.

The media artifact itself is PASS, but the GUI acceptance is FAIL because the
child exited and the complete file/profile existed while the parent worker
never emitted a completed terminal state.  No post-completion Edit Preview
restore or subsequent render could be proven without closing the GUI.

**10000 FULL HUD: FAIL (parent completion hang).**

## ffprobe

`run_10000_10000f.mp4`:

```text
container size: 1,863,728,432 bytes
container duration: 333.666667 s
video: HEVC, 3840x2160, 30000/1001 fps, nb_frames=10000
audio: AAC, 48000 Hz, stereo, duration=333.651792 s
```

**OUTPUT FFPROBE: PASS.**

## Event Log

Read-only queries covered events since `2026-09-08T07:49:37Z` for:

- Resource Exhaustion Event 2004;
- Display 4101 / TDR and relevant Display/dxgkrnl providers;
- Application Error/Hang 1000/1002 containing `dwm.exe`, `python.exe`,
  `d3d11.dll`, or `explorer.exe`.

No matching new event was found.

**NO EVENT 2004: PASS.**
**NO DWM CRASH: PASS.**
**NO D3D11 CRASH/TDR: PASS.**

## Acceptance matrix

| Criterion | Result |
|---|---|
| 5 sequential AMD child renders | PASS |
| New child PID each run | PASS |
| No orphan child | PASS |
| Parent private plateau vs historical leak | PASS, small declining warm-up tail remains |
| Parent handles plateau | PASS |
| Parent threads plateau | PASS |
| Cancel | **FAIL — temp video residue** |
| Error containment | PASS |
| Next render after cancel/error | PASS |
| Edit Preview restore | PASS for normal/cancel/error; **FAIL/NOT PROVEN after 10000** |
| 10000 full HUD | **FAIL — output complete, parent terminal hang** |
| Child exit reclaims memory | PASS |
| No Event 2004 | PASS |
| No DWM crash | PASS |
| No D3D11 crash/TDR | PASS |
| Output ffprobe | PASS |
| Normal GUI IN/OUT limits AMD native workload | **FAIL — cut regions ignored** |

## Changed files

- `scratch/run_amd_child_final_gui_acceptance.py` — acceptance-only GUI driver
  and measurements; no production path change.
- `scratch/amd_child_final_gui_acceptance_console.log` — raw acceptance log.
- `Raporty/RAPORT_AMD_CHILD_PROCESS_FINAL_GUI_MEMORY_ACCEPTANCE.md` — this
  report.

Existing dirty-tree changes, including AMD/Intel/NVIDIA/HUD code, were not
discarded or rewritten by this stage.

## Tests

- `python -m py_compile scratch/run_amd_child_final_gui_acceptance.py`: PASS.
- `pytest -q tests/test_amd_child_process.py tests/test_export_preview_video_restore.py`:
  **13 passed**.
- Five sequential real 1000-frame GUI/AMD child renders: PASS.
- Cancel at frame 300 plus next real render: functional recovery PASS, cleanup
  FAIL.
- Controlled child error plus next real render: PASS (exit-code risk noted).
- Real 10,000-frame child render and ffprobe: media PASS, GUI completion FAIL.
- Final process inventory after normal GUI close: no parent/child/ffmpeg orphan.
- `git diff --check`: pre-existing dirty-tree whitespace failures remain in
  `src/video_helpers.py` and `tests/test_multifile_avg_speed.py`; this acceptance
  added no tracked production whitespace changes.

## Backend isolation and risks

- Intel, NVIDIA, HUD implementation, native renderer, and pickle contract were
  not changed.
- The test exercised only AMD native child containment.
- Production blockers requiring a separate scoped fix:
  1. apply GUI IN/OUT/cut ranges to the AMD native timeline/frame plan;
  2. remove partial Stage-A output on cancel;
  3. diagnose the parent IPC/worker completion hang after the 10,000-frame child
     exit;
  4. decide whether a child logical failure should return a non-zero OS exit
     code;
  5. investigate why normal GUI preview materializes all IMU lazy lists before
     render and raises pickle startup to ~13 s (do not optimize implicitly).

## Summary

The child process successfully contains the large native AMD memory allocation
and eliminates the historical per-render +500–800 MiB parent leak signature.
However, because cancel cleanup fails and the 10,000-frame child completion
leaves the parent render worker hung—and because normal GUI IN/OUT does not
bound AMD native rendering—the requested final status is **NOT READY**.
