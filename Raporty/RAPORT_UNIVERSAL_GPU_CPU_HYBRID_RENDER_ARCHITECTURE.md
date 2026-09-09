# Universal GPU / GPU+CPU / CPU render mode

**Date:** 2026-09-09  
**Branch / HEAD:** `integration/intel-amd` / `59277b4`  
**Scope:** progress correctness for the existing CPU renderer and a safe, opt-in Hybrid architecture. Production GPU defaults are unchanged.

## Result

CPU progress is production-ready. Hybrid is intentionally **experimental**: it has a common semantic-frame contract and an adaptive safety controller, but it never creates independently encoded CPU and GPU chunks. On the tested Ryzen 7 7730U APU, `GPU + CPU` resolves to **GPU-only** with zero CPU contribution.

## Root cause of missing CPU statistics

The CPU renderer in `src/ffmpeg/streaming.py` already knew `done`, `total`, elapsed time and FPS. It emitted a payload containing only `frame` and `ts`, however. `RenderMixin` requires `phase="render"` to turn a callback into the canonical live render state; an unlabelled payload was treated as preparation, hence the GUI could remain at `0%`, `Frame: --`, `FPS: --` even after software frames were flowing.

It also emitted only every 50 piped frames. At measured CPU rates of roughly 2–3 FPS this makes the UI appear stalled for tens of seconds.

The fix emits the CPU callback for every real bounded frame handoff and includes:

```text
backend=cpu, role=cpu, phase=render,
frame_done, frame_total, fps_instant, fps_average, frame/ts
```

No timer is used. `done` is a real frame accepted into the bounded CPU→FFmpeg handoff.

## Shared progress contract

`RenderProgressState` now also carries the backend-neutral fields:

```text
backend, role, phase,
frame_done, frame_total,
fps_instant, fps_average,
elapsed, eta, percent
```

Legacy `frame`, `total_frames` and `fps` remain intact for existing Qt consumers. The shared GUI representation is therefore, for CPU-only for example:

```text
TOTAL  302 / 1000 | 2.45 FPS | ETA derived from real average
CPU    302 / 1000 | 2.45 FPS
```

GPU progress remains on the existing native tracker. No synthetic producer/consumer counter was added.

## Render-mode UI and safety

The render settings now expose:

| Choice | Effective path |
|---|---|
| GPU | Existing selected GPU backend / production default |
| CPU | Existing software renderer (`encoder=cpu`) with real progress |
| GPU + CPU | Experimental policy decision; currently safe GPU-only fallback unless a backend proves canonical CPU-frame handoff |

`src/ffmpeg/hybrid_render.py` defines `PreparedVideoFrame`:

```text
frame_index, pts, duration, effective_timeline_timestamp,
pixel_format, width, height,
color_primaries, transfer, matrix, range, orientation,
payload/surface
```

This is the required common producer contract. It preserves the semantic timeline and explicitly prohibits changing HUD, map, charts, Lean, BAR, telemetry/FIT continuity or canonical audio as a side effect of scheduling.

## One final encoder contract

No mixed-codec concat is implemented.

| Backend | Canonical final encoder | CPU-frame handoff today | Hybrid result |
|---|---|---|---|
| AMD | AMF | not production-proven | experimental, GPU-only fallback |
| NVIDIA | NVENC | not production-proven | experimental, GPU-only fallback |
| Intel | QSV | not production-proven | experimental, GPU-only fallback |

Consequently there is one canonical audio timeline and no CPU-owned audio stream. A future contributor must hand a `PreparedVideoFrame` to the same backend-native encoder before Hybrid may contribute a frame.

## Adaptive policy

The policy uses the requested mode, topology, backend capability, memory safety, rolling GPU regression and combined gain:

```text
APU/shared package                 -> CPU workers 0
missing canonical handoff          -> CPU workers 0
GPU regression > 3%                -> CPU workers 0
combined gain < 1%                 -> CPU workers 0
otherwise (future verified handoff)-> bounded experimental contribution
```

This is deliberately not a fixed 90/10 split. The current AMD APU resolves at the first rule. `1/2/4/AUTO` contribution is therefore not fabricated: AUTO=0 on this machine. The prior real worker evidence remains decisive:

| Variant | Result on Ryzen 7 7730U |
|---|---|
| GPU alone | 39.178 FPS (10k dual-render evidence) |
| CPU alone, 4 workers | 2.385 FPS; ~96.61% CPU |
| Concurrent GPU + CPU | 32.560 combined useful FPS; **-16.89%** vs GPU alone |
| Hybrid AUTO | GPU-only / 0 CPU workers |

CPU clock/frequency was not exposed by the existing WMI sampler, so no invented clock number is reported. The observed saturation, commit and GPU regression are sufficient for the APU AUTO decision. A dGPU is classified separately but remains benchmark-ready rather than enabled until its encoder receives a safe handoff implementation.

## Real CPU GUI proof (D: only)

Normal path used: `QApplication → AppController → MainWindow → RenderTab._on_render()`.

Clean run, 4 CPU workers, video-only 1000-frame range:

```text
artifact: D:\TeleM_CPU_PROGRESS_CLEAN_20260909\TeleM_child_final_acceptance_20260909_085717\run_experiment_cpu_1000f.mp4
terminal: completed
GUI terminal state: frame=1000 / total=1000 / fps=3.0444
output: HEVC 3840x2160, 30000/1001, 1000 frames, 33.366667 s
parent wall: 348.195 s
render button / next render: ready
scratch residue: none
system commit peak: 40.63 GiB
```

CPU cancel proof, same normal GUI path:

```text
artifact: D:\TeleM_CPU_PROGRESS_CANCEL_FIXED_20260909\TeleM_child_final_acceptance_20260909_090911\run_experiment_cpu_1000f.mp4
cancel requested: frame 300
GUI terminal: cancelled, frame=302 / 1000, FPS=2.4477
FFmpeg graceful stop: 9.768 s
valid partial MP4: 297 HEVC frames, 9.909900 s
next render: ready; no scratch residue; no orphan worker
```

An initial cancel exposed a cleanup-only `ProcessPoolExecutor._processes=None` exception after its workers were already stopped. `_RenderExecutor.__exit__` now treats that mapping as already-clean; the repeated proof above passed.

## Changed files

- `src/ffmpeg/streaming.py` — real per-frame CPU progress contract; idempotent CPU cancel cleanup.
- `src/render_progress.py` — shared semantic fields.
- `src/gui/qt/_mixins/render_mixin.py` — maps common contract and resolves mode safely.
- `src/gui/qt/tabs/render_tab.py` — GPU / GPU+CPU / CPU selector.
- `src/gui/qt/controller.py`, `src/gui/qt/_mixins/preset_mixin.py` — persists mode.
- `src/ffmpeg/hybrid_render.py` — capability matrix, topology policy and `PreparedVideoFrame` contract.
- `tests/test_hybrid_render_contract.py` — contract / APU / dGPU-safe-fallback tests.
- `scratch/run_amd_child_final_gui_acceptance.py` — opt-in CPU cancellation harness control only.

## Verification

```text
pytest tests/test_hybrid_render_contract.py tests/test_render_progress_single_source.py: 13 passed
pytest with test_render_no_legacy_json included before the real run: 16 passed
```

The pre-existing `test_amd_native_etap4.py` source-string failures remain unrelated to this change and were not altered.

## Acceptance

```text
CPU FRAME PROGRESS:                 PASS
CPU FPS:                            PASS
CPU ETA:                            PASS (derived only from real frames)
CPU CANCEL:                         PASS
NO MIXED-ENCODER UNSAFE CONCAT:     PASS
ONE FINAL ENCODER CONTRACT:         PASS (design gate)
ADAPTIVE CPU BUDGET:                PASS (safe policy)
GPU PRIORITY / APU AUTO-THROTTLE:   PASS (AUTO=GPU-only on 7730U)
DESKTOP-dGPU READY FOR BENCHMARK:   PASS (capability-gated, not enabled)
NO HUD/TELEMETRY REGRESSION:        PASS (no compositor semantics changed)
MEMORY BOUNDED:                     PASS for 4-worker CPU proof
HYBRID CPU CONTRIBUTION:            NOT ENABLED / EXPERIMENTAL
```

No default GPU backend, image quality, Intel/NVIDIA renderer behavior, AMD single-pass mux, commit or push was changed.
