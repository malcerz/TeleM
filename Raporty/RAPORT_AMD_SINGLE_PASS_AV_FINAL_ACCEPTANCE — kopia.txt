# AMD SINGLE-PASS A/V MUX — FINAL AUDIO / SINGLE-FILE ACCEPTANCE

Date: 2026-09-08  
Branch: `integration/intel-amd`  
Backend: `AMD_NATIVE_D3D11`  
Full 85,574-frame proof: **not run**

## Scope and implementation change

The existing single-pass implementation was retained. One production fix was
needed after packet testing: concat-demuxer `inpoint` can preserve a positive
source timestamp for a clip-2 fragment. The single-pass concat audio input now
uses:

```text
-copyts -avoid_negative_ts make_zero
```

This keeps copied audio timestamps anchored to the effective timeline before the
global `-t` limit. No renderer, HUD, Intel, NVIDIA, QSV, or CUDA code was
changed.

## 1. Real single-file GUI smoke

Normal GUI path:

```text
QApplication → AppController → MainWindow → RenderTab._on_render()
```

Input: `GX010244.MP4`, `12_naprawiony.fit`, `GX010244.layout.json`; full HUD,
AMD GPU HUD, GPU Preview ON; 1000 frames from the single source.

Result: **PASS**

```text
terminal:       completed
requested:      1000
muxed video:    1000 HEVC frames
video:          3840x2160, 30000/1001, 33.366667 s
audio:          AAC, 48000 Hz, stereo, 33.386667 s
Preview:        67 frames; restored after render
child:          exited
residue:        none
next render:    button enabled, worker stopped, preview slot visible
```

## 2. Packet-level A/V validation

Packet-only `ffprobe -show_packets` was used; no video decode scan was
performed.  The final-code short cross-boundary output was 1000 frames,
500 from each clip, with effective boundary at `16.683333333 s`.

```text
audio packets: 1601
video packets observed by CSV: 999 (stream metadata: 1000 frames)
audio PTS monotonic: PASS
audio DTS monotonic: PASS
video PTS/DTS monotonic: PASS
max positive packet gap: 0.000000 s
max packet overlap:       0.000000 s
```

The first AAC packet is a standard priming packet:

```text
raw first audio PTS/DTS: -0.808458 s
Skip Samples:            38806 samples (0.808458 s)
audio stream start_time: 0.000000 s
video stream start_time: 0.000000 s
```

Therefore the negative priming packet is not an audible A/V offset.

| Position | Audio | Video | A/V difference |
|---|---:|---:|---:|
| Playback start | 0.000000 s stream start | 0.000000 s stream start | 0.000000 s |
| Clip boundary | 16.683333 s | 16.683333 s | 0.000000 s |
| Last packet start | 33.366000 s | 33.333300 s | +0.032700 s |
| End of last packet | 33.387333 s | 33.366667 s | +0.020666 s |

The end difference is AAC packet-duration/priming granularity, with no gap,
overlap, PTS restart, or duplicated audio. The 10,000-frame cross-clip output
also had monotonic audio/video packets and an end-duration delta of 6.458 ms.

## 3. GUI IN/OUT and cut shapes

Real source timeline: `GX010244.MP4 → GX010245.MP4`, boundary
`1383.849133333 s`, 29.97002997 fps.

| Case | GUI/effective shape | Video | Audio | Difference | Result |
|---|---|---:|---:|---:|---|
| A | single-file middle range (clip 1) | 33.366667 s | 33.386667 s | +20.000 ms | PASS |
| B | cross clip 1→2, 500+500 frames | 33.366667 s | 33.387333 s | +20.666 ms | PASS |
| C | clip-2 fragment, local 100→133.366667 s | 33.366667 s | 33.376104 s | +9.437 ms | PASS |
| D | two retained 500-frame segments with internal cut | 33.366667 s | 33.386667 s | +20.000 ms | PASS |

The real C and D GUI outputs completed with 1000 video frames, AAC audio,
Preview restore, enabled next-render control, and no residue.  The effective
audio plans for A–D were also generated from the real `VideoTimeline` and
verified with `-copyts -avoid_negative_ts make_zero`.

## 4. CPU / GPU / disk sampling

One real 10,000-frame cross-clip single-pass GUI render was sampled with native
Windows WMI performance classes (no external profiler).  Samples were taken
periodically and at render checkpoints 1000/3000/5000/8000/10000.

Checkpoint samples:

| Frame | CPU total | GPU engines* | GPU encode* | Disk read | Disk write | System committed |
|---:|---:|---:|---:|---:|---:|---:|
| 1000 | 15% | 173% | 98% | 221.6 MB/s | 0 | 33.441 GB |
| 3000 | 14% | 176% | 99% | 0 | 0 | 33.216 GB |
| 5000 | 17% | 175% | 100% | 0 | 1.0 MB/s | 33.228 GB |
| 8000 | 16% | 167% | 97% | 262.2 MB/s | 0 | 33.208 GB |
| 10000 | 15% | 1% | 0% | 2,211.8 MB/s | 173.9 MB/s | 33.096 GB |

Periodic aggregate (190 samples):

```text
CPU total:       avg 14.25%, peak 42%
GPU engines*:    avg 144.61%, peak 188%
GPU encode*:     avg 81.55%, peak 105%
disk read:      avg 10.31 MB/s, peak 543.81 MB/s
disk write:     avg 14.40 MB/s, peak 197.29 MB/s
system commit:  avg 32.85 GB, peak 33.58 GB
parent private at end: 2.212 GB
child peak private:    2.340 GB
```

`GPU engines` is the sum of concurrently active WMI engine instances and can
exceed 100%; it is not a single normalized GPU percentage.

## 5. Performance versus two-stage baseline

Same real 10,000-frame cross-clip workload:

| Metric | Two-stage baseline | Single-pass final run | Change |
|---|---:|---:|---:|
| Render FPS | 41.698 | 41.885 | +0.45% |
| Effective FPS | 40.194 | 40.651 | +1.14% |
| Video wall | 239.820 s | 238.747 s | -0.45% |
| Finalization wall | 3.920 s | 1.441 s | -63.2% |
| Total export wall | 248.796 s | 245.996 s | -1.13% |

Render regression is below the required 2% limit: **PASS**.

## 6. Disk and temporary artifacts

```text
single-pass 10000f final MP4: 1,863,566,180 B
largest persistent non-final temporary: 126-byte audio concat plan
successful output directory: final MP4 + profile only
.part.temp_video.mp4: absent
audio plan after rename: absent
```

The transient `.part` is the final MP4 staging file and is expected to grow to
final size; no second full-size video copy is created.

## 7. Cancel / error regression

Final-code GUI recovery sequence:

```text
cancel @300:        cancelled, no residue
post-cancel:        completed 1000f, no residue
controlled error:   failed as expected, child exited, no residue
post-error:         completed 1000f, no residue
```

Parent GUI remained usable and the next-render control was available after both
cancel and error. No orphan child or AMD named-pipe residue remained.

## Tests and changed files

```text
python -m py_compile src/ffmpeg/amd_native_exporter.py src/ffmpeg/streaming.py scratch/run_amd_child_final_gui_acceptance.py scratch/analyze_audio_video_packets.py scratch/validate_effective_audio_ranges.py
python -m pytest -q tests/test_amd_direct_mp4_mux.py tests/test_amd_child_process.py tests/test_amd_gui_range_contract.py
24 passed
```

Changed for this acceptance:

- `src/ffmpeg/amd_native_exporter.py` — concat timestamp anchoring.
- `scratch/run_amd_child_final_gui_acceptance.py` — bounded single/range/recovery harness modes.
- `scratch/run_amd_perf_sample.ps1` — native WMI sampling harness.
- `scratch/analyze_audio_video_packets.py` — packet-only audit.
- `scratch/validate_effective_audio_ranges.py` — real A/B/C/D audio-plan audit.
- this report.

The repository was already dirty; unrelated changes were preserved. No commit,
push, reset, clean, rebase, Intel/NVIDIA change, HUD change, or renderer
optimization was performed.

## READY criteria

```text
REAL SINGLE-FILE GUI:              PASS
MULTI-FILE CROSS-CLIP:             PASS
AUDIO PTS MONOTONIC:               PASS
NO AUDIO GAP/OVERLAP:              PASS
A/V SYNC:                          PASS (AAC priming explicitly accounted)
GUI IN/OUT AUDIO:                  PASS
MULTIPLE CUTS AUDIO:               PASS
NO FULL-SIZE TEMP VIDEO:           PASS
RENDER FPS REGRESSION <=2%:        PASS
CPU/GPU/DISK MEASURED:             PASS
CANCEL:                            PASS
ERROR RECOVERY:                    PASS
NO ORPHAN:                         PASS
```

```text
STATUS = READY FOR FINAL 85574 SINGLE-PASS PROOF
```

The requested final 85,574-frame proof is intentionally left for the next
task and must be run only with sufficient output-disk headroom.
