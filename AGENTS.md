# TeleM — AGENTS.md

## 1. Purpose

This repository contains TeleM, a Windows video telemetry overlay application with separate rendering paths for:

- NVIDIA
- AMD
- Intel
- CPU/reference paths

GPU backends are intentionally isolated.

Changes for one backend must not silently alter another backend.

---

# 2. Absolute Git Safety Rules

Before changing code always run:

```text
git status
git branch --show-current
git rev-parse --short HEAD
```

Never use without explicit user approval:

```text
git reset --hard
git clean -fd
git checkout -- .
git restore .
git rebase
git push --force
```

Never discard uncommitted user work.

Never merge an entire experimental backend branch into another backend branch unless explicitly requested.

If the working tree already contains modifications:

- inspect them,
- preserve them,
- determine whether they belong to the current task.

Do not overwrite them merely because they are not committed.

---

# 3. Backend Isolation

## AMD

AMD production path:

```text
AMD_NATIVE_D3D11
```

Uses:

- Media Foundation / D3D11VA decode
- native D3D11 compositor
- AMF HEVC encode

Current validated AMD GPU features:

```text
AMD_GPU_MAP_ROTATE = ON by default
AMD_AFTER_MAP_CHART_GPU = ON by default
```

These features are production-enabled and must not be removed or silently disabled.

Current AMD capabilities include:

- GPU Track-Up map rotation
- GPU map marker
- GPU HR AFTER-MAP chart
- GPU Cadence AFTER-MAP chart
- native D3D11 HUD compositing
- AMF encode

Current validated combined baseline:

```text
4K / 1131 frames

RENDER FPS:          26.359
USER EFFECTIVE FPS:  22.183

map_cpu_upload:       ~0.08 ms
above_compose:        19.065 ms
above_total:          22.612 ms
producer_prepare:     31.759 ms
consumer_native_call: 2.948 ms
pipeline_total:        5.991 ms
```

Normal GUI smoke after GPU defaults were enabled:

```text
RENDER FPS:     24.162
map_cpu_upload: 0.079 ms
above_total:    21.963 ms
```

Do not regress these paths while working on unrelated features.

---

## NVIDIA

Do not modify NVIDIA/NVENC/CUDA behavior during AMD tasks unless explicitly requested.

Shared code changes must be proven backend-neutral.

---

## Intel

Do not modify:

- QSV
- Intel device selection
- Intel GPU surfaces
- Intel-specific FFmpeg filters
- Intel encoder/decode path

during AMD tasks unless explicitly requested.

---

# 4. Current AMD Layer Order

Current native D3D11 compositing approximately follows:

```text
Video
↓
BELOW HUD
↓
GPU Track-Up Map
↓
CPU ABOVE
↓
AFTER-MAP GPU charts
↓
Final HUD → NV12
↓
AMF
```

Current AFTER-MAP charts:

```text
Cadence
Heart Rate
```

The logical layout order in the production v10 preset includes:

```text
Cadence
→ Speed Gauge
→ Heart Rate
```

Any work moving the speed gauge to GPU must preserve pixel-equivalent Z-order.

Do not infer correctness solely from function names.

Inspect actual pixel compositing order.

---

# 5. Critical Clear / Dirty-Region Rule

Persistent HUD textures require correct cleanup of previous-frame pixels.

Never insert a clear operation after MAP or ABOVE without checking whether it destroys underlying pixels.

For a widget moved to AFTER-MAP GPU:

prefer clearing its previous region at the beginning of the following frame rather than clearing the destination after underlying layers have already been drawn.

Always verify:

- no ghosting,
- no stale cursor/value,
- no erased map pixels,
- no erased underlying HUD.

---

# 6. Current Map State

Map preload/cache work is completed.

During the video frame loop:

```text
HTTP requests = 0
tile misses = 0
```

GPU Track-Up replaced per-frame Pillow BICUBIC rotation.

Previous CPU map cost:

```text
~34 ms/frame
```

Current AMD GPU-map CPU preparation cost:

```text
~0.08 ms/frame
```

Do not reintroduce:

- synchronous HTTP during rendering,
- per-frame Pillow map rotation,
- unnecessary full-map reconstruction.

Do not optimize map preload unless explicitly requested.

---

# 7. Current Charts State

HR and Cadence AFTER-MAP charts use native GPU_SPLIT.

When GPU chart path is active:

```text
CPU ABOVE HR = NO
CPU ABOVE Cadence = NO
```

Do not render them both on CPU and GPU.

Do not regress their resource lifecycle or Z-order.

---

# 8. Current Optimization Target

AMD ETAP 2A/2B/2C/2D (AFTER-MAP GPU Speed Gauge) are complete:

```text
AMD_AFTER_MAP_GAUGE_GPU = ON by default (production since ETAP 2D)
Transfer mode: AUTO regions preferred; FULL_TILE safe fallback
Explicit AMD_AFTER_MAP_GAUGE_GPU=0 restores the legacy CPU gauge path
```

ETAP 2D validated default-config perf smoke (300f, GX010115/v10/4K):

```text
RENDER FPS:               34.344   (2C AUTO 1131f reference: 35.965;
                                   short-run fixed mux cost amortization)
above_total:              13.95 ms (reference 13.90 ms)
gauge bytes/frame median: 338612   (reference 329780)
region frames 297 / full resyncs 3 (AMD_GAUGE_FULL_REFRESH_N=120)
```

Remaining CPU ABOVE bottlenecks include approximately:

```text
alt_visual                ~3.2 ms
slope_text                ~2.1 ms
compass                   ~1.8 ms
fit_enhanced_speed_text   ~1.5 ms
fit_curVpower_text        ~1.4 ms
temp_text                 ~1.2 ms
```

(the speed gauge itself left CPU ABOVE via the GPU path)

Do not optimize later items automatically.

One optimization stage per task.

---

# 9. Speed Gauge Existing GPU Path

An older GPU gauge implementation already exists.

Do NOT implement a new gauge renderer from scratch unless proven necessary.

Reuse:

- existing gauge texture/capture path,
- existing native upload,
- existing shader,
- existing `BlendGauge` logic where possible.

Historical tests showed the GPU gauge itself can achieve exact parity.

AFTER-MAP placement and safe clearing/Z-order were solved in ETAP 2A–2C;
production enablement with AUTO dynamic regions was validated in ETAP 2D
(see `Raporty/RAPORT_AMD_ETAP_2D_GAUGE_PRODUCTION_ENABLE.md`).

---

# 10. ETAP 2A Important Constraint

Do NOT globally move the existing BEFORE-MAP `BlendGauge` to AFTER-MAP.

Existing layouts may rely on the old position.

Implement an AFTER-MAP mode/pass while preserving legacy behavior.

The feature is production-enabled since ETAP 2D validation completed:

```text
AMD_AFTER_MAP_GAUGE_GPU = ON by default
```

An explicit `AMD_AFTER_MAP_GAUGE_GPU=0` restores the legacy CPU gauge path.

Unsupported AUTO configs (widget rotation != 0, compass-style gauges)
degrade safely to FULL_TILE GPU — never CPU-only, never missing art.

---

# 11. Correctness Before Performance

For renderer changes:

1. implementation
2. smoke test
3. Z-order validation
4. ghosting validation
5. pixel/reference validation
6. benchmark

Do not benchmark a visually incorrect renderer.

Do not accept a performance gain as justification for changing output semantics.

---

# 12. Pixel Parity

Whenever possible compare compositor surfaces before HEVC encoding.

Do not blame large differences on AMF compression if a pre-encode comparison is available.

For components that previously achieved exact parity, retain exact parity unless there is a technically proven reason otherwise.

Report:

```text
max_diff
MAE
different_pixels
```

Do not invent new acceptance thresholds.

---

# 13. Benchmark Discipline

Read `BENCHMARKS.md` before running TeleM benchmarks. The VIDEO/FIT pairing in
`BENCHMARKS.md` is authoritative.

Hard rules:

- Never infer or guess a FIT file from an MP4 filename, activity title,
  timestamps, metadata dates, or folder order.
- Never silently substitute a different FIT.
- The primary AMD single-file benchmark is exactly:

```text
Video/GX020079.MP4
Video/GX020079.fit
C:\_DEV\TeleM\def_layout.json
3840x2160
1131 frames
AMD_NATIVE_D3D11
```

- The secondary single-file benchmark is exactly:
  `Video/GX030120.MP4` + `Video/GX030120.fit`.
- The canonical multi-file benchmark is exactly:
  `Video/GX010114.MP4`, `Video/GX010115.MP4`, `Video/GX010116.MP4` plus
  `Video/GX010114_116.fit`.
- `GX030120.MP4 + Jazda_na_rowerze_w_porze_lunchu.fit` is an invalid pairing.
- If a task requires a different dataset, explicitly report the proposed
  VIDEO/FIT pairing before using it.
- Code and the working tree take precedence over reports, but benchmark
  pairings in `BENCHMARKS.md` must not be changed implicitly.

Comparisons must use the same source video, FIT, layout, output resolution,
frame count, encoder settings, and feature flags. Do not compare different
workloads as if they were equivalent.

---

# 14. Reports Are Mandatory

Every implementation stage must produce a Markdown report in the repository.

Report must include:

- task
- initial state
- changed files
- exact implementation
- tests
- benchmark if relevant
- regressions / risks
- backend isolation
- final PASS/FAIL summary

Do not mark a task COMPLETE if an acceptance criterion was not actually tested.

Use:

```text
NOT TESTED
NOT PROVEN
BLOCKED
```

when appropriate.

---

# 15. Do Not Trust Previous Reports Blindly

Previous reports are evidence, not authority.

If a report says PASS but raw numbers contradict its acceptance criteria:

call that out.

Do not copy conclusions without checking the measurements.

---

# 16. Scope Discipline

Do not perform opportunistic refactors.

Do not fix unrelated issues during an optimization task.

If another issue is discovered:

document it for a later task.

Do not silently expand scope.

---

# 17. Coding Style

Prefer:

- minimal patches,
- reuse existing architecture,
- explicit feature flags for experimental renderer paths,
- clear runtime diagnostics,
- deterministic fallback.

Avoid:

- parallel duplicate implementations,
- speculative abstraction layers,
- large refactors during performance work.

---

# 18. Required Final Response

At the end of a task, report concisely:

```text
TASK:
STATUS:

CHANGED:
TESTED:
NOT TESTED:
PERFORMANCE:
RISKS:

REPORT:
```

Do not automatically start the next optimization stage.
