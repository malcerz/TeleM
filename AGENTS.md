# AGENTS.md — TeleM

## Purpose

This repository contains **TeleM**, a Windows application for rendering telemetry overlays from GoPro / FIT / GPX data onto video and exporting the final encoded movie.

Work conservatively. Preserve existing behavior unless the task explicitly asks for a change.

---

## Environment

Primary development / test environment:

- Windows 11
- Python
- FFmpeg 8.1.1
- NVIDIA test GPU: GeForce RTX 5070 Ti 16 GB
- NVIDIA driver: 610.62
- CUDA: 13.3

The project must remain portable across supported backends unless a task is explicitly scoped to one backend.

---

## Current NVIDIA pipeline

The production NVIDIA export path uses:

- NVDEC
- CUDA
- `overlay_cuda`
- NVENC

Current encoder configuration is approximately:

- `hevc_nvenc`
- `preset p1`
- `tune hq`
- `rc vbr`
- `cq 24`
- `b:v 40M`
- `maxrate 40M`
- `bufsize 80M`
- `gpu 0`

Current base video path intentionally converts GoPro Main10 input to:

- `yuv420p`
- 8-bit

Do **not** change 8-bit / 10-bit / HDR behavior unless explicitly requested.

## NVIDIA frozen baseline

The validated NVIDIA production baseline is frozen at:

- Direct-Region with Multi-Region Atlas transport;
- MAX5 / GRID16 HUD geometry;
- zero-copy SharedMemory RGBA targets;
- four workers and `MAX_IN_FLIGHT = 8`;
- one `BufferedWriter.write(memoryview(SHM))` writer, releasing the slot after the write;
- the current preview-enabled CUDA/NVENC graph.

The raw RGBA pipe remains the known future bottleneck. GPU-native transport is a
separate future stage and is not part of this baseline.

---

## Worker configuration

For the NVIDIA production overlay path, keep the current tested defaults unless a task explicitly benchmarks alternatives:

- `workers = 4`
- `MAX_IN_FLIGHT = 8`

Do not increase worker count based only on CPU core count.

Previous tests showed that excessive worker counts severely reduce throughput because of memory bandwidth, cache pressure, IPC and SharedMemory traffic.

---

## HUD transport architecture

The NVIDIA renderer supports three transport modes:

1. `SINGLE_BBOX`
2. `MULTI_REGION_ATLAS`
3. `FULL_FRAME`

The goal is to avoid transporting full 1920×1080 RGBA overlays when the actual HUD occupies only part of the frame.

Do not bypass or remove these modes casually.

Current Multi-Region Atlas behavior may use multiple HUD regions packed into one RGBA atlas and sent through a single `pipe:0`.

FFmpeg unpacks regions with combinations of:

- `split`
- `crop`
- `scale`
- `format=yuva420p`
- `hwupload_cuda`
- `overlay_cuda`

Preserve alpha.

---

## Telemetry precompute

The project contains per-frame telemetry precomputation.

Its purpose is to replace repeated per-frame FIT / GPMF / GPX lookup and interpolation with O(1) frame-index lookup in workers.

Important invariants:

- no silent source fallback;
- if an indicator requests FIT, do not silently substitute GPMF or GPX;
- `None` means missing data;
- numeric `0` is valid data and must not be treated as missing;
- source identity must be preserved;
- SmartSync / timeline resolution must be finalized before precompute;
- do not rebuild the complete telemetry cache independently in every worker;
- do not pickle the full telemetry dataset with every frame job.

Frame jobs should remain small, ideally containing only identifiers such as:

- frame index
- SHM slot

---

## Chart data regression rule

A previous telemetry-precompute integration caused `fit_cadence_text` and `fit_heart_rate_text` history to disappear.

The root causes included:

- building `chart_data` in the main process using a resolver that depended on worker-only `WORKER_CACHE`;
- incorrect source helper return shape;
- `fit_*_text` names being reduced to aliases such as `cad` / `hr` instead of the actual FIT field names such as `cadence` / `heart_rate`.

Do not reintroduce this behavior.

Before modifying telemetry or chart precompute, verify that full chart history remains available.

For reference materials already tested, cadence and heart-rate history must remain complete.

---

## Source isolation

Never silently change the selected telemetry source.

Examples:

- requested FIT + FIT missing + GPMF available -> do not silently use GPMF;
- requested GPX -> do not silently use FIT;
- requested GPMF -> do not silently use FIT.

If fallback behavior is desired, it must be explicit and requested.

---

## `None` vs zero

Preserve this distinction everywhere:

- `None` = unavailable / missing
- `0`, `0.0` = real measured value

This applies especially to:

- speed
- cadence
- power
- heart rate
- temperature
- battery
- dynamic FIT fields

Do not use truthiness checks such as:

```python
if value:
```

when `0` is a valid value.

Prefer explicit checks such as:

```python
if value is not None:
```

---

## Bar renderer

`src/indicators/bar.py` is the unified bar renderer.

It supports:

- `bar_style = "ruler"`
- `bar_style = "segments"`

The public entry point remains:

```python
_render_bar_indicator(...)
```

Legacy `segment_bar` compatibility may be provided by a shim.

Do not recreate two independent bar implementations.

Default behavior for `form="bar"` without `bar_style` is `ruler`.

---

## Preview vs final-render metrics

Do not confuse GUI preview timing with final export timing.

Metrics such as:

- `overlay_rendering`
- `preview_cycle`

may refer to GUI preview work and are not automatically representative of production export throughput.

For NVIDIA final-render performance, prioritize:

- `FRAME_PIPELINE`
- `PIPELINE_FPS`
- `PRODUCTION_TOTAL`
- `REAL_EXPORT_FPS`
- end-to-end wall-clock
- `ffmpeg_write avg`
- `ffmpeg_write p95`

Always state which timer a reported FPS value comes from.

---

## Production benchmark methodology

When comparing optimizations, use A/B tests on identical:

- source video
- FIT / GPX inputs
- layout
- FFmpeg build
- encoder settings
- worker count
- `MAX_IN_FLIGHT`
- output dimensions

Prefer at least 3 runs and report the median.

Do not compare a synthetic reduced-layout benchmark directly against a production-layout run as if they were equivalent.

Synthetic benchmarks may be used only to isolate a component.

---

## Hardware reference values

Historical measurements on the RTX 5070 Ti for the current type of 4K HEVC workload:

- NVDEC-only: roughly 485 FPS
- synthetic NVENC-only: roughly 510+ FPS
- bare NVDEC -> `scale_cuda` -> NVENC: roughly 418 FPS
- 3-region CUDA atlas filter graph with no real Pillow HUD: roughly 332 FPS

These are diagnostic reference points, not permanent guarantees.

Re-measure if relevant code, FFmpeg, driver, codec parameters or source format changes.

---

## Performance workflow

For optimization tasks:

1. Audit current code first.
2. Measure before changing.
3. Change one major thing per stage.
4. Re-run the same benchmark.
5. Verify semantic and visual parity.
6. Write a Markdown report.
7. Stop.

Do not stack unrelated optimizations into one task unless explicitly requested.

---

## Visual correctness

Performance changes must not cause:

- clipping;
- shifted HUD elements;
- wrong rotation;
- changed source selection;
- changed timeline synchronization;
- missing chart history;
- alpha corruption;
- z-order changes;
- incorrect min/max ranges;
- duplicated labels;
- missing labels.

Whenever practical, compare pre-encode RGBA output.

For true pixel parity:

- `max_diff = 0`
- `different_pixels = 0`

Do not call independently encoded lossy HEVC files “bit-exact” unless decoded pixels are actually identical.

---

## Rotation

The NVIDIA pipeline supports a CUDA fast path for videos carrying 180-degree display rotation metadata.

Do not break:

- displaymatrix handling;
- HUD coordinate transforms;
- atlas-region transforms;
- final rotation metadata.

When changing region geometry, verify rotation 0° and 180° at minimum.

For indicator-local geometry, also consider 90° / 270° where supported.

---

## SharedMemory / IPC

Be careful with:

- SHM slot shape;
- byte counts;
- strides;
- `memoryview` lifetime;
- Pillow / NumPy exported buffers;
- cleanup on FFmpeg failure;
- process termination;
- `queue.Empty`;
- `BufferError`.

Release exported views before closing or unlinking SharedMemory.

Do not copy large buffers unnecessarily.

---

## FFmpeg failure handling

If FFmpeg exits early:

- detect process death promptly;
- stop producers cleanly;
- release SHM slots;
- close stdin safely;
- avoid waiting indefinitely on queues;
- do not mask the original FFmpeg error with secondary cleanup exceptions.

---

## Geometry / HUD bbox rules

Do not assume declared geometry is optimal.

Distinguish between:

- declared indicator bbox;
- actual alpha bbox;
- global bbox;
- region bbox;
- atlas packing rectangle.

When investigating oversized atlases, measure these separately.

Do not “fix” a large atlas merely by raising the full-frame fallback threshold.

Find the source of wasted geometry first.

---

## Current optimization frontier

The current active area of investigation is the NVIDIA HUD atlas geometry on real production layouts.

On some layouts, the atlas may become too large and trigger:

```text
FULL_FRAME
```

even though the visible HUD appears much smaller.

Potential causes to investigate include:

- overly conservative indicator bbox;
- phantom bbox;
- poor region merge decisions;
- `MAX_HUD_REGIONS`;
- inefficient shelf packing;
- excessive padding.

Do not implement Direct-Region Rendering until the current task explicitly asks for it.

---

## Do not change without explicit instruction

Do not independently modify:

- SmartSync;
- source resolver semantics;
- selected telemetry sources;
- 8-bit / 10-bit / HDR policy;
- NVENC preset / CQ / bitrate;
- worker count;
- `MAX_IN_FLIGHT`;
- bar architecture;
- telemetry precompute semantics;
- chart-data semantics;
- AV1 support;
- AMD pipeline;
- Intel pipeline;
- D3D11 compositor architecture.

---

## Reports

For substantial audit / optimization stages, create a Markdown report named according to the requested stage, for example:

```text
RAPORT_NVIDIA_ETAP_5B3_ATLAS_GEOMETRY.md
```

Reports should include:

- baseline;
- methodology;
- changed files/functions;
- benchmark results;
- parity checks;
- root cause;
- remaining bottleneck;
- explicit final conclusion.

Do not proceed automatically to the next stage after writing the report.

---

## Git discipline

Before editing:

- inspect `git status`;
- do not overwrite unrelated user changes;
- keep diffs scoped to the requested task.

Do not:

- reset unrelated files;
- perform broad cleanup;
- reformat unrelated modules;
- delete reports or test artifacts unless explicitly requested.

At the end, summarize exactly which files changed.

---

## Testing discipline

Run the smallest relevant tests first, then broader tests if needed.

For telemetry / chart changes, include regression coverage for:

- source isolation;
- `None` vs zero;
- full chart history;
- per-frame parity.

For renderer / atlas changes, include:

- bbox coverage;
- no clipping;
- alpha preservation;
- rotation;
- FULL_FRAME vs atlas parity when applicable.

If a test cannot be run because of environment limitations, say so explicitly.

---

## Agent behavior

Do not assume a report proves the current repository still has the same state.

Inspect the current code before making conclusions.

If measurements contradict earlier reports:

- trust the current reproducible measurement;
- explain why the old number is no longer comparable.

Prefer precise, minimal changes over broad rewrites.
