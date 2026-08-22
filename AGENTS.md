# AGENTS.md — TeleM Repository Instructions

## Purpose

This file defines mandatory rules for any coding agent working in the TeleM repository.

TeleM supports multiple rendering paths and hardware vendors. Changes made on one development machine must not regress other supported backends.

The current development machine may use AMD hardware. This does **not** make AMD the only supported target.

---

# 1. Supported Rendering Backends

Treat the following as first-class supported paths:

- AMD GPU path
  - D3D11
  - AMF
  - `AMD_NATIVE_D3D11`
- NVIDIA GPU path
  - CUDA / NVDEC / NVENC or the currently implemented NVIDIA pipeline
- CPU reference / fallback path

All three paths are important.

## Mandatory rule

**Absence of NVIDIA hardware on the current machine is NOT permission to simplify, remove, disable, rewrite, or bypass the NVIDIA path.**

Likewise, work done on NVIDIA hardware must not break AMD.

---

# 2. CPU_REFERENCE Is the Correctness Baseline

Where TeleM has a CPU reference implementation, treat it as the visual and semantic correctness baseline.

GPU implementations may be optimized differently, but they must preserve:

- geometry,
- positioning,
- scale,
- z-order,
- opacity,
- text,
- values,
- timing,
- colors,
- clipping,
- interpolation semantics,
- indicator behavior.

Do not change CPU reference behavior merely to make a GPU implementation easier.

If a GPU path differs from CPU reference, investigate the GPU path first.

---

# 3. Indicator Work Must Stay Local

When a task concerns:

- indicator appearance,
- gauge geometry,
- fonts,
- tick marks,
- labels,
- colors,
- spacing,
- widget configuration,
- indicator sizing,
- indicator positioning,

do **not** redesign or refactor the rendering pipeline unless the task explicitly requires it.

Prefer the smallest possible change in:

- the relevant indicator module,
- shared indicator primitives,
- configuration/model code,
- GPU implementation of that same indicator.

Do not modify unrelated rendering stages.

---

# 4. Protected Rendering Areas

Do not change the following as a side effect of indicator work unless explicitly requested:

- decoder selection,
- encoder selection,
- NVENC configuration,
- AMF configuration,
- D3D11 device creation,
- CUDA initialization,
- hardware frame contexts,
- FFmpeg hardware-device setup,
- pixel formats,
- color formats,
- frame ownership,
- GPU/CPU synchronization,
- GPU upload/download logic,
- frame pooling,
- compositing order,
- final encoder handoff,
- preview timing,
- render timing,
- telemetry synchronization,
- telemetry source priority,
- FIT/GPMF/GPX resolver semantics.

These areas require a dedicated task and dedicated validation.

---

# 5. Do Not "Clean Up" Vendor-Specific Code Without Permission

Do not merge AMD and NVIDIA code simply because it appears duplicated.

Vendor-specific code may intentionally differ because of:

- API constraints,
- memory layout,
- synchronization behavior,
- encoder requirements,
- driver behavior,
- GPU resource lifetime,
- pixel format restrictions,
- hardware-specific optimizations.

A refactor that reduces duplication but changes behavior is a regression.

Only consolidate vendor-specific code when explicitly requested and after proving equivalent behavior.

---

# 6. Preserve Existing Backend Selection

Do not:

- hard-code AMD because the current PC uses AMD,
- hard-code NVIDIA because a previous PC used NVIDIA,
- make one vendor path the unconditional default,
- silently route a working GPU path through CPU,
- remove fallback logic,
- change backend priority without an explicit task.

Backend selection must continue to respect the existing project logic.

---

# 7. Preserve Diagnostic Logging

Do not remove or rename existing rendering diagnostics unless explicitly requested.

Examples include diagnostics such as:

- `AMD_MAP_PATH`
- `AMD_CHART_PATH`
- `AMD_GAUGE_PATH`
- `AMD_TELEMETRY_MODE`
- `AMD_AMF_MODE`
- GPU/CPU fallback reasons
- NVIDIA backend diagnostics
- encoder-path diagnostics

When adding a new fallback or rendering branch, add a concise diagnostic message explaining which path was selected and why.

Diagnostics are part of the validation workflow.

---

# 8. Z-Order and Compositing Are Behavior, Not Cosmetics

The order in which indicators are rendered is part of the visual contract.

Do not reorder indicators or move an element to another compositing stage unless required.

Pay particular attention to cases where a GPU path is only safe when an indicator is:

- first,
- last,
- isolated,
- rendered before text,
- rendered after maps,
- rendered before final compositing.

If a GPU optimization would change z-order, keep the existing fallback rather than silently changing the image.

---

# 9. Preview and Final Render Must Match

Indicator semantics must remain consistent between:

- GUI preview,
- frame preview,
- final render/export.

A change is not complete if it only works in preview or only in final rendering.

For every indicator change, verify or reason through both paths.

If preview and final use different implementations, keep their behavior aligned.

---

# 10. Telemetry Pipeline Is Out of Scope for Visual Tasks

For tasks limited to indicator appearance or layout, do not alter:

- FIT parsing,
- GPX parsing,
- GPMF parsing,
- timestamp extraction,
- SmartSync,
- absolute-time alignment,
- telemetry interpolation,
- telemetry resolver rules,
- explicit source selection,
- source fallback priority.

Rendering code should consume resolved telemetry values.

It should not invent a new source-selection policy.

---

# 11. Data Flow Contract

Preferred architecture:

```text
FIT / GPMF / GPX / camera metadata
        ↓
telemetry resolver
        ↓
time synchronization / offset
        ↓
interpolation
        ↓
smoothing / derived value
        ↓
unit conversion / formatting
        ↓
indicator renderer
        ↓
compositor
        ↓
preview or final encode
```

Indicator renderers should not independently reimplement telemetry resolution unless the existing architecture explicitly requires it.

---

# 12. AMD Development Machine Rules

On an AMD development machine:

You may:

- build AMD code,
- run AMD GPU tests,
- benchmark AMD,
- inspect D3D11/AMF behavior,
- optimize AMD-specific code.

You must also:

- preserve NVIDIA imports and code paths,
- keep NVIDIA configuration valid,
- avoid changing NVIDIA APIs without need,
- inspect diffs for accidental NVIDIA changes,
- state clearly which NVIDIA behavior could not be runtime-tested.

Do not claim "NVIDIA works" solely because AMD tests passed.

Use wording such as:

> NVIDIA path preserved statically; runtime validation was not possible on this machine.

---

# 13. NVIDIA Development Machine Rules

The inverse also applies.

On NVIDIA hardware:

- do not remove AMD code,
- do not replace AMF with NVENC-only assumptions,
- do not introduce CUDA-only dependencies into shared code,
- do not assume CUDA is available in common modules.

---

# 14. Dependency Changes Require Explicit Justification

Do not upgrade or replace the following during unrelated tasks:

- FFmpeg,
- PyAV,
- OpenCV,
- DirectX/D3D libraries,
- AMF SDK components,
- CUDA-related libraries,
- NVIDIA encode/decode bindings,
- Qt/PySide/PyQt,
- NumPy,
- GPU rendering libraries.

A dependency update must be its own deliberate change unless required to fix the assigned task.

---

# 15. No Opportunistic Refactors

Do not perform large refactors "while here."

Avoid:

- renaming large module trees,
- moving rendering classes,
- changing public APIs,
- replacing factories/registries,
- rewriting working renderers,
- introducing new frameworks,
- deleting "unused" backend code based only on the current machine.

If unrelated technical debt is discovered, report it separately.

---

# 16. Work Sequence for Every Task

Before editing:

1. Read this `AGENTS.md`.
2. Inspect the relevant files.
3. Identify all affected rendering paths:
   - CPU
   - AMD
   - NVIDIA
   - preview
   - final render
4. Identify whether the change is:
   - visual only,
   - data-related,
   - GPU/backend-related,
   - encoder-related.
5. State the minimum intended scope.
6. Only then modify code.

---

# 17. Diff Discipline

After modifications:

- inspect `git diff`,
- verify that unrelated files were not changed,
- verify AMD-only work did not touch NVIDIA unnecessarily,
- verify NVIDIA-only work did not touch AMD unnecessarily,
- verify shared changes are backend-neutral.

Unexpected changes must be reverted before considering the task complete.

---

# 18. Build Is Not Sufficient Validation

A successful build means only that syntax/imports may be valid.

It does not prove rendering correctness.

For indicator changes, validation should include as applicable:

- visual comparison,
- CPU reference comparison,
- preview test,
- final-render test,
- sample-frame render,
- log inspection,
- performance sanity check.

For GPU changes, also verify that the expected hardware path was actually selected.

---

# 19. Performance Regression Rule

Do not accept a visual improvement that causes a major performance regression without explicitly reporting it.

For performance-sensitive code, compare where practical:

- frame time,
- render time,
- preview FPS,
- GPU utilization,
- CPU utilization,
- GPU↔CPU transfers,
- VRAM use,
- encoder throughput.

Do not add a CPU round-trip to a GPU path merely because it is simpler.

---

# 20. GPU Memory Transfer Rule

TeleM's performance goal is to keep frames on the GPU as long as practical.

Avoid unnecessary:

```text
GPU → CPU → GPU
```

transfers.

However, **correctness comes before optimization**.

If an optimization changes visual output, z-order, alpha, timing, or data semantics, preserve the correct fallback and report the limitation.

---

# 21. Fallbacks Must Be Explicit

Fallbacks are allowed and often necessary.

A fallback must:

- preserve correct output,
- have a clear reason,
- be logged,
- not silently become the default due to an unrelated change.

Do not remove a fallback solely to improve benchmark numbers.

---

# 22. Indicator Architecture Guidance

Where practical, keep these concerns separate:

## Data binding
Which resolved telemetry value is used.

## Indicator state
Current value, history window, range, derived state.

## Geometry
Positions, radii, tick locations, paths, bounding boxes.

## Style
Fonts, line width, fill, opacity, shadows.

## Rendering backend
CPU / AMD / NVIDIA implementation details.

This separation is preferred over one large indicator class containing source resolution, calculations, layout, and GPU code.

---

# 23. Current Indicator Development Goal

The current indicator work is focused on reproducing and improving the selected TeleM cycling dashboard layout while keeping the system user-configurable.

The user must ultimately be able to:

- enable/disable individual indicators,
- move indicators,
- resize indicators,
- configure indicator appearance,
- select relevant telemetry,
- save custom layouts/presets.

Do not hard-code the reference dashboard as the only layout.

Treat it as a preset.

---

# 24. Reference Indicator Families

Prefer reusable families rather than separate engines for every gauge:

- digital/text blocks,
- horizontal linear gauges,
- vertical linear gauges,
- circular gauges,
- history charts,
- rotating image/icon indicators,
- maps.

A new indicator should reuse an existing family where reasonable.

Do not force reuse if it would create incorrect behavior or excessive complexity.

---

# 25. Changes Requiring Explicit User Approval

Do not perform these without a task explicitly asking for them:

- replacing the rendering architecture,
- merging AMD and NVIDIA pipelines,
- deleting CPU reference implementations,
- replacing FFmpeg,
- replacing AMF/NVENC integration,
- changing telemetry synchronization architecture,
- changing project-wide pixel formats,
- changing color-management behavior,
- changing encoder defaults,
- changing backend selection policy,
- rewriting the map pipeline,
- introducing a new GPU framework.

---

# 26. When Hardware Is Unavailable

If a backend cannot be tested on the current machine:

1. Preserve its code.
2. Perform static inspection.
3. Check imports/API usage where possible.
4. Avoid speculative edits.
5. Report exactly what was and was not tested.

Never hide the testing limitation.

---

# 27. Task Completion Report

At the end of a coding task, provide a concise report containing:

## Changed
Files and behavior changed.

## Preserved
Relevant AMD/NVIDIA/CPU paths intentionally left unchanged.

## Tested
What was actually run.

## Not tested
Hardware/backend paths unavailable on the current machine.

## Risks
Any remaining compatibility or performance concern.

---

# 28. Core Rule

When uncertain, prefer the smallest change that preserves existing behavior across all backends.

**Do not sacrifice NVIDIA compatibility to fix AMD.**

**Do not sacrifice AMD compatibility to fix NVIDIA.**

**Do not sacrifice correct CPU reference output merely to make GPU code simpler.**

**Do not modify the rendering pipeline when the assigned task only requires changing an indicator.**

---

# 26. Fresh-Agent / Gemini / AntiGRAVITY Operating Rules

This repository may be opened by a fresh coding agent with no access to the previous chat history.

Therefore, do not assume hidden conversational context.

At the start of every task:

1. Read this `AGENTS.md` completely.
2. Read the exact task prompt completely.
3. Read only the reports/files explicitly named by the task first.
4. Inspect only the minimum relevant code needed to verify the task assumptions.
5. Do not broaden into a whole-repository audit unless the task explicitly asks for one or the narrow inspection proves insufficient.
6. Prefer measured facts from the current repository over assumptions from an older report.
7. If the prompt, repository state, and report disagree, stop and report the conflict before making broad changes.

These rules are model-independent and apply equally to Gemini, AntiGRAVITY, Codex, or any other coding agent.

---

# 27. Task-Scope Discipline

A task prompt defines the allowed scope.

If the task says `AUDIT ONLY`:

- do not leave production-code changes,
- temporary instrumentation must be removed before completion,
- do not turn the audit into an optimization/refactor task.

If the task says to modify one renderer or subsystem:

- do not optimize neighboring renderers "while here",
- do not change unrelated presets,
- do not fix unrelated technical debt,
- report adjacent opportunities separately.

If the task names a maximum number of benchmark runs, renders, or iterations, obey it.

---

# 28. Test and Benchmark Economy

Do not run the full test suite by default.

Use:

- narrow regression tests for local changes,
- one representative CPU render when required,
- one short AMD runtime smoke/benchmark when required,
- static preservation review for NVIDIA on an AMD machine.

Run the full suite only when:

- the task explicitly requests a checkpoint/full regression,
- a broad shared change materially affects many subsystems,
- targeted tests reveal a reason that requires broader validation.

Do not repeatedly run long 4K exports during iterative development.

Prefer 1280×720 short benchmarks for performance diagnosis unless the task explicitly requires 4K.

---

# 29. Reports Are Evidence, Not Authority

Previous `Raporty/*.md` files describe the state measured at the time they were created.

They may become stale after later changes.

When a current task depends on a metric or implementation detail:

- verify the current code/path,
- reproduce the relevant current behavior where practical,
- do not optimize from an old timing if a newer production measurement contradicts it.

Do not silently copy old benchmark values into a new report as if they were newly measured.

Clearly label historical baseline values versus current measurements.

---

# 30. Current Stable Dashboard Baseline

As of the current project checkpoint, the active dashboard baseline is:

```text
presets/cycling_dashboard_v10.json
```

The v10 checkpoint passed a full regression:

```text
650 passed
17 skipped
0 failed
```

Do not create `v11` unless a task explicitly asks for a new preset version.

Do not modify historical presets `v1` through `v10` as a side effect of performance/debug work unless the task explicitly requires it.

---

# 31. Current Primary Test Material

Use the current primary material unless a task explicitly names something else:

```text
Video/GX010115.MP4
Video/GX010115.json
Video/Jazda_na_rowerze_w_porze_lunchu.fit
```

The currently confirmed synchronization for this MP4/FIT pair is:

```text
offset = +2.000 s
confidence = high
median_error = 7.6 m
p90_error = 12.9 m
coverage = 1.00
```

Do not rerun SmartSync unless the task explicitly asks for it or current evidence indicates the pairing is wrong.

Older material such as `GX030120` remains useful for historical/regression checks but is not the default current test pair.

---

# 32. Active Telemetry-Overlay References

Two active reference images represent the same Telemetry Overlay layout:

```text
wzor/00000.png
wzor/Zrzut ekranu 2026-08-22 092614.png
```

Use them differently:

## `wzor/00000.png`

Primary reference for:

- geometry,
- positions,
- proportions,
- tick density,
- line/marker shapes,
- icon shapes,
- clean HUD appearance.

## `wzor/Zrzut ekranu 2026-08-22 092614.png`

Primary reference for:

- readability over real video,
- contrast,
- outline strength,
- opacity/fill behavior,
- visibility of small elements on footage.

They are not competing layouts.

Do not choose one and discard the other.

`wzor/rower_ico.png` is reserved for the future Bike Lean indicator and must remain untouched unless a task explicitly reopens Lean work.

---

# 33. Current Dashboard Data Contracts

Important current bindings/semantics include:

## Solar

Use the exact FIT developer field:

```text
solar_pct
```

Confirmed semantics:

```text
source = fit
unit = %
range = 0..100
STEP / hold-last semantics
```

There is also a distinct FIT field:

```text
solar
```

It is NOT an alias for `solar_pct`.

Do not merge or substitute these fields.

## Charts

Cadence and Heart Rate use:

```text
chart_time_scope = window
chart_window_s = 60
```

The visible X-axis semantics are relative time:

```text
-60 ... 0
```

Charts must remain causal: no future sample may be used for time `t`.

## Heading / Compass

Use the existing canonical `heading` telemetry path.

Do not recalculate heading independently inside the renderer.

## Slope

Use the existing canonical derived `slope` path.

Do not change slope derivation during visual/performance tasks.

---

# 34. Current Chart Performance Optimization

A production-confirmed Chart axis/layout cache exists in:

```text
src/indicators/chart_utils.py
```

It significantly reduced the AMD `CPU_REFERENCE` chart cost.

Current validated production-level phase results included approximately:

```text
above_compose: 33.236 ms -> 8.022 ms
above_total:   35.571 ms -> 10.558 ms
```

The chart overlap guard remains intentionally preserved and charts may still use:

```text
CPU_REFERENCE
```

Do not remove `GPU_CHART_UNSAFE_LAYOUT` merely to improve benchmark numbers.

The cache must remain:

- bounded,
- font-aware,
- style/layout-aware,
- independent of current history/timestamp for static-axis entries,
- visually identical on cache miss vs hit.

---

# 35. ACTIVE BLOCKER: Chart Seek / Random-Access History

Before continuing with further renderer optimization such as `time_display`, the currently observed chart-history bug must be resolved.

Observed behavior in interactive playback:

- after seeking directly to a later timestamp, HR/Cadence history begins mostly empty,
- the chart then fills progressively as playback time advances,
- expected behavior is to display the complete previous 60-second window immediately on the first rendered frame after the seek.

Required semantic contract:

For a current time `t` and `chart_window_s = 60`:

```text
history = samples in [t - 60, t]
```

subject to actual telemetry availability.

This must be true regardless of whether the frame is reached by:

- sequential playback from the beginning,
- a forward seek,
- a backward seek,
- a fresh session whose first render is at time `t`,
- final/random-access frame rendering.

Therefore chart history must be random-access safe and must not depend on samples accumulated only since playback/session start.

Do not assume this bug was introduced by the recent axis-cache optimization. The user first noticed it only now, so the regression point is not established.

Do not proceed to Time Display optimization until the chart seek/history task is closed or the task prompt explicitly overrides this rule.

---

# 36. Current Performance Direction After Chart Fix

The most recent production profile before discovery of the chart seek/history bug measured approximately:

## CPU_BELOW_MAP steady state

```text
time_display          ~3.834 ms total
Distance              ~1.709 ms total
Battery               ~2.897 ms total
Solar                 ~1.921 ms total
```

## CPU_ABOVE_MAP steady state

```text
Compass               ~0.890 ms
Slope                 ~1.741 ms
ISO                   ~0.352 ms
Shutter               ~0.431 ms
Temperature           ~0.148 ms
Altitude              ~0.969 ms
Virtual Power         ~0.939 ms
Cadence               ~0.890 ms
Speed Gauge           ~0.715 ms
Heart Rate            ~1.193 ms
```

These measurements identify `time_display` as the next likely renderer optimization target AFTER correctness of Chart seek/history is restored.

Do not optimize `time_display` while the active Chart history bug remains unresolved unless the current task explicitly instructs otherwise.

---

# 37. Current Map Contract

The current dashboard uses:

```text
map_orientation = track_up
map_style = satellite
map_marker_style = directional
```

For `track_up`:

- the map rotates according to canonical heading,
- the directional marker points UP in final output space,
- do not rotate the marker a second time by heading.

For `north_up`:

- a directional marker rotates according to heading.

For `heading=None`:

- do not fabricate heading 0°,
- use the existing safe fallback behavior.

Preserve map center, zoom, crop and tile semantics unless the task explicitly concerns the map engine.

---

# 38. Current Visual Features to Preserve

The current v10 dashboard includes and expects preservation of:

- Time / Date / Activity,
- Distance,
- Battery,
- Solar (`solar_pct`),
- ISO,
- Shutter,
- Temperature,
- Altitude,
- Virtual Power,
- Cadence 60 s chart,
- Speed Gauge,
- Heart Rate 60 s chart,
- Compass,
- Slope,
- Track-Up satellite map,
- directional map marker,
- procedural HUD icons,
- optional `tick_profile = pixel`,
- per-widget font-selection infrastructure.

Font visual matching is intentionally postponed.

Do not select or commit a target font unless the task explicitly asks for it.

---

# 39. Lean Is Deferred

Bike Lean / IMU-derived lean remains intentionally deferred.

Current status:

```text
DEFERRED — IMU NOT RELIABLE
```

Previous offline calibration against GPS did not provide reliable physical sign/timing/mount calibration.

Do not productionize Lean, do not use `wzor/rower_ico.png`, and do not reopen IMU work unless a task explicitly asks for controlled calibration or a new data source.

---

# 40. Agent Completion Report Contract

At the end of every coding task, report these sections or their equivalent:

## Changed

Exact production files changed and what changed.

## Preserved

Protected paths/semantics intentionally left unchanged.

## Tested

Exact tests, renders, benchmarks, and runtime paths actually executed.

## Not tested

Anything relevant that could not be runtime-tested, especially NVIDIA on an AMD machine.

## Risks / Remaining issues

Known limitations, deferred work, unresolved questions.

Never claim a runtime path was validated if it was only inspected statically.

---

# 41. Final Rule

Prefer the smallest change that:

1. fixes the demonstrated problem,
2. preserves visual/data semantics,
3. preserves CPU/AMD/NVIDIA behavior,
4. preserves z-order and fallbacks,
5. is covered by a focused regression test,
6. does not create unrelated cleanup/refactor work.

Correctness first, then measured performance, then refactoring.
