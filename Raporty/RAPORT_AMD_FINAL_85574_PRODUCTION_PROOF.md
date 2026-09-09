# AMD FINAL PRODUCTION PROOF — full 85,574-frame GUI render

## TASK

Execute the requested production proof in the normal GUI path:

```text
QApplication -> AppController -> MainWindow -> RenderTab._on_render
```

Inputs explicitly requested by the user (this is a real-project validation, not
the canonical `BENCHMARKS.md` workload):

```text
D:\GoPro\2026-09-01\GX010244.MP4
D:\GoPro\2026-09-01\GX010245.MP4
D:\GoPro\2026-09-01\12_naprawiony.fit
D:\GoPro\2026-09-01\GX010244.layout.json
```

Requested configuration: source 3840x2160, full HUD, AMD Native D3D11VA / native
D3D11 HUD+map / AMF, GPU frame-tap Preview ON, full GUI timeline with no IN/OUT
cuts, then a real 1,000-frame render without restarting the GUI.

Branch / HEAD at task start: `integration/intel-amd` / `59277b4`.  The worktree
was already dirty and was preserved.  No reset, clean, rebase, commit, push,
renderer optimisation, HUD change, LazySampleList/pickle change, or Intel/NVIDIA
change was made.

## INITIAL STATE AND PREFLIGHT

The required preceding reports were read before the run.  `BENCHMARKS.md` was
also read; it makes clear that this user-specified two-clip/FIT project is not a
canonical benchmark pairing.

At the actual full-proof baseline (`2026-09-08 12:37:56+02:00`):

```text
parent private:               2,169,716,736 B
system committed / limit:    31,866,675,200 / 64,317,124,608 B
available physical:          14,957,330,432 B
active pagefile:             D:\pagefile.sys, 32,768 MiB
pagefile current / peak:     141 / 151 MiB
D: free:                     36,513,914,880 B
```

The acceptance harness required a conservative 22 GiB output budget, which was
available at preflight.  This was insufficient for the actual two-stage mux:
Stage A alone later occupied 26,517,705,374 B and Stage C needed a second near-
full-size output on the same drive.

## HARNESS AND FULL GUI PLAN

Only the acceptance driver was extended, with a `TELEM_ACCEPTANCE_FINAL_PROOF_ONLY`
mode.  It restores the original loaded timeline, clears GUI cut regions, asserts
the exact full frame count, captures process/system/pagefile/disk/pipe evidence
at sparse checkpoints, and then performs the existing post-render smoke.  No
production module was changed.

The actual GUI plan was:

```text
full frame count:       85,574
clip segments:          41,474 + 44,100
project duration:       2,855.319133333 s
GUI cuts:               []
AMD child PID:          3032
job pickle:             48,967,113 B / 1,698.481 ms
child restore:          2,106.968 ms
```

The child log proves the intended path, with no fallback at startup:

```text
RENDER PATH: ... exporter=amd_native_exporter decode=D3D11VA
video_frame_path=GPU hud=amd_native map=amd_native encode=AMF fallback_reason=none
```

All eight large transported IMU fields remained `LazySampleList(state=lazy)` in
the job diagnostic.

## FULL-RUN OBSERVATION

GPU frame-tap Preview was live throughout the native stage (`5,688` delivered
preview frames, no drops).  The harness saved normal-GUI screenshots at start,
1k, 5k, 10k, 20k, 40k, 60k and 80k in the result directory.  The final 85,574
checkpoint was not emitted because finalisation failed before a completed GUI
state was published.

| Target frame | Observed | Parent private | Child private | Preview frames |
|---:|---:|---:|---:|---:|
| 0 | 0 | 2,171,867,136 B | n/a | 0 |
| 1,000 | 1,000 | 2,387,955,712 B | 2,265,325,568 B | 67 |
| 5,000 | 5,000 | 2,387,775,488 B | 2,380,820,480 B | 331 |
| 10,000 | 10,000 | 2,391,810,048 B | 2,408,505,344 B | 662 |
| 20,000 | 20,000 | 2,391,810,048 B | 2,422,435,840 B | 1,326 |
| 40,000 | 40,000 | 2,391,805,952 B | 2,516,217,856 B | 2,657 |
| 60,000 | 60,000 | 2,393,923,584 B | 2,498,347,008 B | 3,987 |
| 80,000 | 80,000 | 2,391,810,048 B | 2,639,568,896 B | 5,319 |

No monitored `telem_amf_*` / `telem_cpu_p010_*` named-pipe residue was observed
at checkpoints or after the child exited.  The full run's child peak private
usage was 3,377,975,296 B.  The parent did not inherit that native allocation;
after the failed full run it was 2,223,607,808 B.

## EXACT FAILURE

The native render did reach Stage A completion.  Its direct mux diagnostics
reported 26,517,016,425 encoded bytes fed through the pipe and FFmpeg successfully
closed a video-only container:

```text
[AMD MULTI-FILE MUX] Stage A complete (video-only container created).
video-only artifact: 26,517,705,374 B
duration reported by FFmpeg: 00:47:35.32
```

Stage C then attempted the required stream-copy remux of that video-only file
plus concatenated audio to a second file on `D:`.  It wrote 9,985,589,292 B in
80.621 s before FFmpeg failed:

```text
Error submitting a packet to the muxer: No space left on device
Error writing trailer: No space left on device
Conversion failed!
```

At this point Stage A already consumed about 26.5 GB of the 36.5 GB initial free
space, so there was not enough room for a second final MP4.  The incomplete Stage
C product was subsequently cleaned by the existing failure path; this recovered
space, but the valid Stage-A video-only recovery artifact was intentionally
preserved:

```text
D:\GoPro\2026-09-01\TeleM_child_final_acceptance_20260908_123756\
  run_85574_85574f.mp4.part.temp_video.mp4
```

After the native Stage-C failure the legacy software fallback was attempted and
raised `MemoryError` in `PIL.Image.tobytes()` while converting a HUD image in a
shared-memory worker.  That is a secondary failure after the already conclusive
disk-full remux failure, not evidence that the AMD Stage-A renderer stopped at
85,570.  The run's system committed peak was 64,296,521,728 B against a
64,317,124,608-B limit (only 20,602,880 B headroom), so this fallback also ran
under near-exhausted commit.

The GUI showed `85,570 / 85,574` while it was entering final work.  It never
produced a successful `completed` terminal state because Stage C failed.  The
full record correctly reports `terminal=failed`; exact `ffprobe -count_frames`
of the 26.5-GB recovery artifact was started but deliberately stopped because a
full decode scan was long-running and cannot change the failed production proof.
Therefore exact Stage-A `nb_read_frames` is **NOT TESTED**.  The completed Stage
A container and its reported duration are preserved for later recovery/audit.

## POST-FULL GUI RECOVERY SMOKE

The same parent GUI then executed the mandatory real 1,000-frame render without
restart:

```text
child PID / exit:             6140 / 0
terminal:                     completed
requested / muxed frames:     1,000 / 1,000
ffprobe video/audio:          HEVC 3840x2160 / AAC, 1,000 video frames
GPU Preview frames:           67
render FPS / effective FPS:   36.769 / 29.422
render wall / mux wall:       27.197 s / 0.310 s
parent after smoke private:   2,255,040,512 B
child exited / residue:       yes / none
event log:                    no Event 2004, DWM, D3D11, Display or explorer event
```

This proves parent/child containment and GUI readiness after the failure.  It
does not repair or convert the failed full remux into a PASS.

## TESTS

```text
python -m py_compile scratch/run_amd_child_final_gui_acceptance.py: PASS
full normal GUI project load: PASS
full GUI no-cut plan (85,574 = 41,474 + 44,100): PASS
AMD Native D3D11VA / native HUD/map / AMF Stage A: PASS
GPU Preview ON through 80,000 and finalisation start: PASS
Stage-A recovery artifact preserved: PASS
Stage-C audio remux on D:: FAIL — no space left on device
successful full MP4 with audio: FAIL
final 85,574 checkpoint / completed terminal: FAIL
exact `ffprobe -count_frames` on Stage A: NOT TESTED
post-full 1,000-frame no-restart GUI render: PASS
orphan child / named-pipe residue after termination: PASS
pixel-parity comparison: NOT TESTED (no successful full final output)
```

## CHANGED

- `scratch/run_amd_child_final_gui_acceptance.py` — acceptance-only full-timeline
  mode, resource checkpoints and GUI screenshots.  No production behavior was
  changed.
- `Raporty/RAPORT_AMD_FINAL_85574_PRODUCTION_PROOF.md` — this report.

## BACKEND ISOLATION

- AMD: exercised only through the existing normal GUI AMD child path.
- NVIDIA/NVENC/CUDA: not modified.
- Intel/QSV: not modified.
- HUD layer order, map, charts, gauge, LazySampleList/pickle transport and
  containment production code: not modified.

## RISKS / REQUIRED NEXT ACTION

The preserved Stage-A file must not be deleted.  A future recovery/remux needs
space for both the 26.5-GB Stage-A video and a near-full-size final MP4: use an
output volume with at least 55 GB genuinely free, or first move the preserved
Stage-A artifact to such a volume.  Do not rerun the full proof on the current
`D:` free-space budget.  The software fallback `MemoryError` under near-exhausted
commit is a separate follow-up issue; it was not changed in this validation task.

## FINAL PASS / FAIL SUMMARY

```text
FULL AMD FRAME PRODUCTION:     PASS (Stage A completed and was preserved)
FULL FINAL MP4 + AUDIO:        FAIL (Stage C disk-full remux)
85,574 COMPLETED TERMINAL:     FAIL
FINAL PRODUCTION PROOF:        FAIL
POST-FULL GUI RECOVERY:        PASS (real 1,000f, no restart)
AMD PRODUCTION READY:          NO
```
