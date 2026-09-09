# AMD FINAL 85,574 SINGLE-PASS PRODUCTION PROOF

Date: 2026-09-08  
Branch: `integration/intel-amd`  
HEAD: `59277b4`  
Backend: `AMD_NATIVE_D3D11`  
Output volume: `D:` only

## Task and scope

Final proof was executed through the normal GUI path:

```text
QApplication -> AppController -> MainWindow -> RenderTab._on_render()
```

Inputs: `D:\GoPro\2026-09-01\GX010244.MP4`, `GX010245.MP4`,
`12_naprawiony.fit`, and `GX010244.layout.json`.  Configuration was 3840x2160,
full HUD, AMD native D3D11/AMF, GPU Preview (`gpu_frame_tap`) enabled, and the
uncut full timeline.  No renderer, HUD, Intel, NVIDIA, child-containment, or
single-pass implementation change was made for this proof.  No reset, clean,
rebase, commit, or push was performed.

## Preflight and disk

Output directory:

```text
D:\GoPro\2026-09-01\TeleM_AMD_FINAL_85574_20260908\TeleM_child_final_acceptance_20260908_170838
```

```text
free before:              83,361,746,944 B (77.64 GiB)
minimum during full run:  56,744,968,192 B (52.85 GiB)
free after post-smoke:    56,603,385,856 B (52.72 GiB)
final MP4:                26,608,644,661 B (24.78 GiB)
```

The 22 GiB preflight budget passed.  Only D: was used for proof output.

```text
parent PID/private/RSS/threads/handles: 1952 / 1,505,755,136 B / 805,158,912 B / 73 / 1,736
committed/limit: 33,480,433,664 B / 64,317,124,608 B
available physical: 14,620,741,632 B
pagefile: D:\pagefile.sys, 32 GiB allocated, 651 MiB current, 1,575 MiB peak
pickle: 48,967,144 B (46.70 MiB), 1,746.137 ms
child restore: 2,122.390 ms
```

## Full GUI result

```text
full terminal/requested: completed / 85,574
full preview frames: 5,689
post-smoke terminal/frames/preview: completed / 1,000 / 67
child after each: exited
residue: none
rendering: false; worker: stopped; render button: enabled
Edit Preview: restored/visible
```

Checkpoints 0, child start, 1,000, 5,000, 10,000, 20,000, 40,000, 60,000,
80,000, and 85,574 were captured with screenshots.  No stale frame, preview
restart, or pending GPU payload remained.

## Exact frame accounting

```text
requested = 85,574
decoded = 85,574
HUD/native = 85,574
VP processed = 85,574
AMF submitted = 85,574
AMF output = 85,574
muxed = 85,574
```

Per-clip accounting was `41,474 + 44,100`, with no discarded or null samples.

## Single-pass A/V and final container

The native profile reports `single_pass_av_mux=true`, `stage_a.mode=N/A`, zero
Stage C elapsed/output bytes, and no software fallback.

```text
video: HEVC, 3840x2160, 30000/1001, 85,574 frames, 2,855.319133 s
audio: AAC-LC, 48,000 Hz, stereo, 133,843 packets, 2,855.337125 s
container duration: 2,855.337125 s
```

`ffprobe -count_packets` independently returned 85,574 video packets and
133,843 audio packets, matching the packet CSV audit.  No
`.part.temp_video.mp4`, Stage C copy, or concat residue remains.  The concat
plan is tiny (126 B); the `.part` is only the final MP4 staging file before
atomic rename, not a second full-size video.

## Packet-level A/V timestamp audit

Packet-only `ffprobe -show_packets` was used after rendering; no video decode
scan ran on the GUI thread.  Both streams have `start_time=0.000000`.

```text
audio PTS monotonic: PASS
audio DTS monotonic: PASS
video PTS monotonic: PASS
video DTS monotonic: PASS
max packet gap: 0
max packet overlap: 0
PTS restart: none
```

Real clip boundary: `1383.849133333 s`.

| Position | Audio | Video | A/V delta |
|---|---:|---:|---:|
| First packet PTS | 0.000000 s | 0.000000 s | 0.000 ms |
| Clip boundary | 1383.849125 s | 1383.849133 s | -0.008 ms |
| Last packet PTS | 2855.315792 s | 2855.285767 s | +30.025 ms |
| Stream end | 2855.337125 s | 2855.319133 s | +17.992 ms |

The boundary is effectively sample/frame aligned; the end difference is AAC
packet granularity, with no gap, overlap, restart, or duplicated audio.

## CPU/GPU/disk sampling

Native Windows WMI classes were sampled periodically and at every full-proof
checkpoint (no external profiler and no `tracemalloc`).  GPU total is the sum
of concurrently active engine instances and can exceed 100%.

Periodic aggregate (134 samples):

```text
CPU total:        avg 16.46%, peak 29%
GPU engines:      avg 161.86%, peak 183%
GPU video encode: avg 92.37%, peak 104%
disk read:        avg 40.05 MiB/s, peak 1,895.8 MiB/s
disk write:       avg 30.91 MiB/s, peak 908.3 MiB/s
system committed: avg 33.69 GiB, peak 34.53 GiB
```

| Frame | CPU | GPU engines | GPU encode | Read MiB/s | Write MiB/s | Commit GiB | Free GiB |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 13% | 168% | 99% | 50.6 | 0.0 | 33.70 | 77.55 |
| 5,000 | 12% | 176% | 101% | 0.0 | 14.4 | 33.85 | 76.22 |
| 10,000 | 13% | 166% | 98% | 0.0 | 0.0 | 33.57 | 74.22 |
| 20,000 | 13% | 171% | 100% | 0.0 | 0.0 | 33.69 | 70.94 |
| 40,000 | 19% | 175% | 99% | 0.0 | 0.0 | 33.54 | 66.30 |
| 60,000 | 18% | 174% | 101% | 0.0 | 0.0 | 33.76 | 60.58 |
| 80,000 | 18% | 175% | 101% | 0.0 | 0.0 | 33.91 | 54.61 |
| 85,574 | 7% | 0% | 0% | 0.0 | 0.2 | 31.15 | 52.85 |

Parent private ended at 1,549,520,896 B.  Child peak private was
2,426,748,928 B and was reclaimed after child exit.  System peak committed was
37,218,496,512 B.  No orphan child or named-pipe residue remained.

## Performance

```text
render FPS:          41.0905
effective FPS:       40.1840
video render wall:   2,082.575 s
finalization wall:   38.953 s
total native export: 2,129.555 s
parent end-to-end:   2,145.928 s
```

Compared with the measured 10,000-frame single-pass run (41.885 FPS), the
full-run render FPS change is -1.90%, within the 2% limit.  Stage C was not
run.

## Event log and backend isolation

The post-run Windows event-log query returned no Event 2004, DWM crash/hang,
Display 4101, dxgkrnl/TDR, Python/D3D11, Explorer, or resource-exhaustion
events.  Intel/QSV/NVIDIA/NVENC/CUDA code and HUD semantics were not changed.

## Tests and evidence

Files changed for this proof were limited to this report and the scratch
packet-audit reader's UTF-8-BOM handling; production AMD, HUD, Intel, and
NVIDIA code was unchanged.

```text
py_compile: PASS
pytest selected AMD GUI/child/mux suite: 24 passed in 3.38 s
```

Evidence:

```text
D:\GoPro\2026-09-01\TeleM_AMD_FINAL_85574_20260908\TeleM_child_final_acceptance_20260908_170838\acceptance_results.json
D:\GoPro\2026-09-01\TeleM_AMD_FINAL_85574_20260908\TeleM_child_final_acceptance_20260908_170838\packet_audit.json
D:\GoPro\2026-09-01\TeleM_AMD_FINAL_85574_20260908\full_20260908_170836.samples.jsonl
```

## Final acceptance

```text
FULL 85574:                         PASS
SINGLE-PASS A/V:                    PASS
REQUESTED/DECODED/NATIVE/AMF/MUXED: PASS
FINAL MP4:                          PASS
AUDIO:                              PASS
A/V SYNC:                           PASS
NO FULL-SIZE TEMP VIDEO:            PASS
DISK USAGE BOUNDED:                PASS
GPU PREVIEW:                       PASS
PARENT MEMORY BOUNDED:             PASS
CHILD MEMORY RECLAIMED:            PASS
NO ORPHAN:                          PASS
EDIT PREVIEW RESTORE:              PASS
POST-FULL 1000F:                   PASS
NO EVENT 2004/DWM/D3D11/TDR:       PASS
```

```text
STATUS = AMD SINGLE-PASS PRODUCTION READY
```
