# NVIDIA real GPU + CPU prepared-frame handoff

**Date:** 2026-09-09  
**Branch / HEAD:** `integration/intel-amd` / `59277b4`  
**Scope:** backend-neutral handoff primitives, NVIDIA-first adapter contract  
**Production default:** unchanged; Hybrid remains capability-gated

## Result

The common mechanism is implemented, but a real NVIDIA production proof is
**NOT RUN / NOT PROVEN** on this desktop. The machine exposes no `nvidia-smi`
and the active desktop is the previously validated Ryzen 7 7730U AMD APU. The
implementation therefore does not claim a NVIDIA throughput gain or production
readiness.

## Existing NVIDIA pipeline audit

The current NVIDIA path in `src/ffmpeg/streaming.py` is one FFmpeg process and
one `hevc_nvenc` session:

```text
source decode: detect_gpu_decoder("nv") -> CUDA when available
source surface: FFmpeg CUDA hardware frames (CPU fallback for required rotation)
HUD: CPU Pillow workers -> RGBA shared-memory slots
composition: FFmpeg filter graph / overlay_cuda where CUDA is active
pre-encode: CUDA surface (or yuv420p rotation fallback)
encoder: hevc_nvenc, preset p1, hq, VBR, CQ 24, selected -gpu
audio: copy on an uncut timeline; AAC 192k only when select/aselect cuts require it
PTS: raw frame rate + filter setpts N/FRAME_RATE/TB; audio remains canonical input timeline
ordering: bounded SHM/reorder window drains consecutive frame indexes
```

This audit also identifies the missing piece: the existing CPU workers produce
an overlay surface, not a complete canonical pre-encode video frame that can be
uploaded into the already-open NVENC session. No CPU x265 chunk, concat, second
audio stream, or mixed encoder was added.

## Implemented common contract

`src/ffmpeg/hybrid_render.py` now provides:

- `PreparedVideoFrame`, carrying frame index, PTS/duration, effective timeline
  time, pixel format, dimensions, color metadata and orientation;
- `HybridFrameState` and `HybridWorkScheduler` with the required
  `FREE → CLAIMED_GPU/CLAIMED_CPU → READY → ENCODED` ownership states;
- `HybridReorderBuffer(capacity)` with duplicate/late-frame rejection, strict
  next-index draining, `peak_frames` and exact `peak_payload_bytes`;
- `SingleEncoderHandoff`, which accepts GPU/CPU completions and invokes one
  encoder callback only after ordered draining (including transition tracking);
- `HybridAdaptiveController`, implementing conservative rolling worker gates
  (`<1%` gain or `>3%` GPU regression reduces workers; unsafe memory/clock can
  reach zero without restarting the export);
- `NvidiaPreparedFrameAdapter`, which validates full RGBA/NV12/P010 payloads
  (including native P010 3-bytes-per-pixel sizing) and timing and delegates the
  CUDA/D3D11 upload to an NVIDIA-owned surface adapter. It never performs an
  implicit 8-bit conversion and never creates an encoder.

The adapter boundary is intentionally the only backend-specific piece. AMD
AMF and Intel QSV adapters are not enabled or modified by this task.

## Scheduler and handoff proof (unit level)

`tests/test_hybrid_render_contract.py` covers:

- CPU cannot claim a frame already claimed by GPU;
- out-of-order completion drains as `0, 1, ...`;
- capacity and exact peak payload accounting;
- frame timing/payload/color contract validation;
- GPU→CPU transition through one encoder callback;
- conservative adaptive disable on regression or memory-unsafety.

```text
python -m pytest -q tests/test_hybrid_render_contract.py
9 passed
```

## Required production measurements

The following are deliberately **NOT TESTED** because no NVIDIA dGPU is
available on this machine:

- GPU-only 10,000-frame baseline with full HUD and preview;
- CPU prepared-frame decode/HUD/conversion/upload timing;
- NVIDIA matrix: GPU-only, 1, 2 and 4 CPU workers (6/8 conditional);
- CPU/GPU clocks, package utilization, NVENC/NVDEC utilization and disk I/O;
- 120/250/500/1000-frame chunk proof and 10,000-frame Hybrid proof;
- pre-encode pixel parity at frames 0/100/1000/5000/9999;
- same-session GOP/PTS transition proof and canonical audio packet proof;
- cancel/error/recovery proof for a real NVIDIA handoff;
- production gate (`combined gain >=5%`, preferred `>=10%`, GPU regression `<3%`).

The active desktop has an existing TeleM GUI process; no render was started,
no output was written to `F:`, and no full 85574-frame render was attempted.
`D:` was the only permitted volume and currently had approximately 114.8 GB
free at inspection.

## APU policy and backend isolation

The existing policy remains fail-safe: Ryzen 7 7730U / shared-memory AMD
resolves Hybrid to GPU-only with zero CPU contribution. NVIDIA capability is
still marked not production-proven, so selecting GPU+CPU cannot silently claim
that CPU frames are active. AMD/Intel renderer code, defaults, HUD semantics,
audio mux and encoder settings were not changed.

For AMD dGPU, the missing adapter must upload a canonical prepared frame to the
same AMF session while preserving P010/HDR and native compositor semantics.
For Intel Arc, an analogous QSV surface upload adapter is required. The common
scheduler, reorder buffer, progress and adaptive controller can be reused;
only those surface adapters and their independent proofs should differ.

## GO / NO-GO

```text
COMMON CONTRACT / BOUNDED HANDOFF: PASS (unit-tested)
ONE ENCODER / NO x265 CONCAT:       PASS (structural design)
NVIDIA REAL SAME-NVENC HANDOFF:     NOT PROVEN
NVIDIA 10,000f MATRIX:              NOT TESTED
VISUAL / COLOR PARITY:              NOT TESTED
AUDIO / PTS CONTINUITY:             NOT TESTED
CANCEL / ERROR ON NVIDIA:           NOT TESTED
PRODUCTION GATE:                    NO-GO / EXPERIMENTAL
```

**Status: implementation ready for a NVIDIA dGPU proof; not production-ready
and no default was changed.**
