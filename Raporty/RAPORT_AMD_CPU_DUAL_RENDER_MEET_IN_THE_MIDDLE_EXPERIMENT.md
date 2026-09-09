# AMD + CPU DUAL RENDER — MEET IN THE MIDDLE EXPERIMENT

Date: 2026-09-08  
Branch: `integration/intel-amd`  
HEAD: `59277b4`  
Result: **NO-GO — experimental dual rendering is not promoted**

## Scope and safety

Real unchanged project:

```text
D:\GoPro\2026-09-01\GX010244.MP4
D:\GoPro\2026-09-01\GX010245.MP4
D:\GoPro\2026-09-01\12_naprawiony.fit
D:\GoPro\2026-09-01\GX010244.layout.json
3840x2160, full HUD, FIT/telemetry unchanged
```

Only D: was used for artifacts. No reset, clean, rebase, commit or push was
performed. No Intel/NVIDIA path, production AMD default, renderer or HUD
source was changed. Scheduler/20,000f stages were not started after NO-GO.

## Existing CPU renderer

The production CPU fallback is the existing
`src.ffmpeg.streaming.stream_overlay_to_ffmpeg` path:

```text
decode:    FFmpeg software decode (no GPU decoder)
HUD/map:   existing telemetry cache + multiprocessing RenderExecutor + SHM
compose:   FFmpeg software overlay filter
encode:    libx265, preset=medium, crf=24, yuv420p output
container: MP4
audio:     existing map/copy path; scratch CPU artifacts removed audio
```

The input is HEVC Main 10 HLG. CPU output is 8-bit `yuvj420p` with BT.2020/HLG
signalling; AMD output is `yuv420p`/BT.709. Direct lossless assembly is unsafe
without an explicit codec/color contract.

## A — AMD alone, exact 10,000 frames

Normal GUI path: `QApplication -> AppController -> MainWindow ->
RenderTab._on_render()`, range `0:10000` of clip 1.

Artifact:

```text
D:\GoPro\2026-09-01\TeleM_DUAL_EXPERIMENT\TeleM_child_final_acceptance_20260908_183326\run_experiment_amd_10000f.mp4
```

Independent `ffprobe -count_packets`: 10,000 HEVC video packets and 15,641
AAC packets; 3840x2160; 30000/1001; video duration 333.666667 s; size
3,607,819,125 B. AMD child exited 0 and no residue/orphan remained.

```text
native profile total wall: 255.242 s
native true/render FPS:    39.178
GUI effective FPS:         10000 / 269.373 s = 37.123
```

WMI sparse samples during the render interval (76 samples):

```text
CPU total:       avg 15.84%, peak 36%
GPU engines:     avg 160.91%, peak 187%
GPU video encode avg 90.21%, peak 105%
system commit:   avg 32.27 GiB, peak 32.70 GiB
available RAM:   minimum 16.20 GiB
D read:          avg 8.97 MB/s, peak 140.10 MB/s
D write:         avg 12.20 MB/s, peak 97.41 MB/s
AMD process tree private peak: 4.55 GiB
```

GPU engine percentages are sums of WMI engine instances and may exceed 100%.

## B — CPU alone, exact 10,000 frames

The same GUI path rendered `0:10000` as a video-only artifact with four
existing CPU workers. Four workers were required for safety: the unbounded
default (15 workers on this 16-logical-CPU machine) reached 61.28 GB committed
of a 64.32 GB limit in the pilot.

Artifact:

```text
D:\GoPro\2026-09-01\TeleM_DUAL_EXPERIMENT\cpu_alone_10000_4w_20260908_184937\TeleM_child_final_acceptance_20260908_184939\run_experiment_cpu_10000f.mp4
```

Independent `ffprobe -count_packets`: exactly 10,000 HEVC packets, no audio,
3840x2160, 30000/1001, duration 333.666667 s, size 2,680,465,676 B. Harness
terminal was `completed`; its exit code 6 is only the bookkeeping check
`parent_terminal_delay_s=None`, not a render/mux failure.

```text
GUI effective wall:   4192.912 s (69.88 min)
effective FPS:        2.385
ffmpeg_write average: 497.13 ms/frame (~2.01 writer FPS)
```

WMI sparse samples (233):

```text
CPU total:       avg 96.61%, peak 100%
GPU engines:     avg 0.86%, peak 53%
GPU video encode avg 0.20%, peak 17%
system commit:   avg 40.42 GiB, peak 42.26 GiB
available RAM:   minimum 8.11 GiB
D read:          avg 0.73 MB/s, peak 18.71 MB/s
D write:         avg 0.52 MB/s, peak 6.83 MB/s
```

## C — concurrent AMD + CPU, 10,000 total frames

The split was selected from measured rates and a listed chunk size:

```text
AMD: frames 0:9750       (9,750, left front)
CPU: frames 9750:10000   (250, right front, internally forward)
```

Both ranges came from `VideoTimeline`; coverage has no gap or overlap. AMD
remained in its own child process. CPU was a separate GUI process with four
existing workers. CPU had no audio; AMD retained its normal muxed audio. No
final assembly was attempted.

Artifacts:

```text
D:\GoPro\2026-09-01\TeleM_DUAL_EXPERIMENT\concurrent_9750_250_20260908_184210\amd\...\run_experiment_amd_9750f.mp4
D:\GoPro\2026-09-01\TeleM_DUAL_EXPERIMENT\concurrent_9750_250_20260908_184210\cpu\...\run_experiment_cpu_250f.mp4
```

Independent packet counts were 9,750 AMD and 250 CPU video packets. Concurrent
overlap was 238.724 s:

```text
AMD concurrent true/render FPS: 30.555
AMD concurrent GUI effective:   9750 / 335.804 s = 29.035
CPU concurrent GUI effective:    250 / 244.159 s = 1.024
CPU concurrent ffmpeg_write:     498.63 ms/frame (~2.01 writer FPS)
combined useful render rate:     30.555 + 2.005 = 32.560 FPS
```

Against AMD-alone, combined useful throughput is
`(32.560 / 39.178) - 1 = -16.89%`. GUI-effective sum gives −19.02%; whole
concurrent wall is 29.779 FPS, −19.80% versus AMD-alone GUI-effective.

Concurrent WMI samples during overlap (57 samples):

```text
CPU total:       avg 64.68%, peak 100%
GPU engines:     avg 144.23%, peak 182%
GPU video encode avg 75.32%, peak 102%
system commit:   avg 41.09 GiB, peak 45.22 GiB
available RAM:   minimum 7.13 GiB
D read:          avg 7.52 MB/s, peak 144.61 MB/s
D write:         avg 7.90 MB/s, peak 50.77 MB/s
AMD role private peak: 4.55 GiB; CPU role private peak: 12.20 GiB
```

AMD encode utilisation fell from 90.21% alone to 75.32% during overlap while
CPU was saturated. The existing CPU path therefore materially disturbs AMD.

## Visual/state boundary check

Boundary images:

```text
...\concurrent_9750_250_20260908_184210\boundary_checks\gpu_last.png
...\concurrent_9750_250_20260908_184210\boundary_checks\cpu_first.png
```

The GPU last frame (9749) is upright with map, cadence/HR graphs, gauge, BAR
and telemetry. CPU first frame (9750) has populated HUD/map/history and the
canonical timestamp region, but the complete image is rotated 180 degrees.
The same rotation is present in CPU-alone frame 0. Visual parity at the
GPU→CPU boundary is therefore **FAIL**. No empty chart/history reset was seen.
This existing CPU rotation/source-display-matrix issue was not changed here.

## Memory, disk and audio

Artifacts were bounded chunks, not two full movies. Largest successful
temporary/export artifact was the AMD 9,750-frame MP4 at 3,505,498,483 B; CPU
10,000-frame video-only MP4 was 2,680,465,676 B. No `.part.temp_video.mp4` or
full-size Stage-C copy was created. No final assembly was attempted.

The CPU chunk has no audio, so no duplicate CPU audio exists. The production
AMD exporter has no scratch-only video-only switch and retained its normal
audio for the performance artifact. Canonical single-audio assembly was
**NOT TESTED** after the NO-GO gate. AMD/CPU codec and color metadata differ,
so lossless concat would also require a contract change.

## Scheduler decision and extrapolation

The dynamic `FREE/CLAIMED_GPU/CLAIMED_CPU/DONE` scheduler and chunk matrix
250/500/1000/2000 were **not implemented** after the gate. The static C split
was checked for exact coverage. No 20,000f or full 85,574f dual render ran.

Estimated 85,574-frame wall times (extrapolation only):

```text
AMD-alone exact-A effective rate: ~38.4 min
CPU-alone effective rate:         ~10.0 h
Concurrent measured whole-wall:   ~47.9 min
previous validated AMD baseline:  ~35.5 min
```

## Final decision

```text
GPU ALONE 10,000f:                 PASS (39.178 render FPS)
CPU ALONE 10,000f:                 PASS (10,000 valid video packets)
CONCURRENT 10,000f accounting:     PASS (9,750 + 250, no gap/overlap)
COMBINED >= AMD ALONE +5%:         FAIL (−16.89% render throughput)
HUD/telemetry visual parity:       FAIL (CPU output rotated 180°)
MEMORY SAFE:                       PASS only with 4 workers; default 15 unsafe
AMD child containment:             PASS
CPU video-only chunk:              PASS
CANONICAL single-audio assembly:   NOT TESTED (NO-GO gate)
SCHEDULER / 20,000f / 85,574f:     NOT RUN
PRODUCTION DEFAULT CHANGED:        NO

STATUS = NO-GO — DO NOT IMPLEMENT PRODUCTION DUAL RENDER
```

## Evidence and scratch harnesses

The run evidence is under
`D:\GoPro\2026-09-01\TeleM_DUAL_EXPERIMENT`. Scratch-only files used for the
bounded experiment are:

```text
scratch/run_amd_child_final_gui_acceptance.py
scratch/run_dual_experiment_sample.ps1
scratch/run_dual_concurrent_sample.ps1
```

The acceptance harness changes are opt-in through `TELEM_EXPERIMENT_*` and do
not alter production defaults. The normal AMD child path, Intel/NVIDIA paths,
HUD source and repository history remain untouched.
