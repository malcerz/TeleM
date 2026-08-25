# AGENTS.md — TeleM Repository Instructions

## Purpose

This file defines mandatory rules for any coding agent working in the TeleM repository.

These rules apply to:

- Codex,
- Luna,
- Gemini,
- AntiGRAVITY,
- Copilot agents,
- any other automated coding agent.

A fresh agent may have **no access to previous conversation history**.

Therefore:

- this repository,
- this `AGENTS.md`,
- the explicit task prompt,
- the current source code,
- and explicitly named reports

are the authoritative working context.

Do not assume hidden chat history.

---

# 1. Instruction Priority

For every task, use this priority:

1. the explicit current task prompt,
2. this `AGENTS.md`,
3. current repository code,
4. current tests,
5. explicitly named current reports,
6. older reports/history.

If a report conflicts with the current source code, the **current code wins**.

If the prompt conflicts with the current repository state in a way that makes the requested change unsafe or ambiguous, report the conflict before making broad changes.

---

# 2. Reports Are Evidence, Not Authority

Files in:

```text
Raporty/
```

describe the state measured when they were created.

They may become stale.

Do not blindly implement architecture described in an old report without checking the current code.

When a report contains:

- benchmark numbers,
- backend status,
- test counts,
- known bugs,
- class names,
- file paths,

verify the relevant current implementation first.

Do not copy old benchmark values into a new report and present them as newly measured.

Clearly distinguish:

```text
historical measurement
```

from:

```text
current measurement
```

---

# 3. Reports Location

All new coding-task reports must be written under:

```text
Raporty/
```

Do not create task reports in the project root.

Examples:

```text
Raporty/RAPORT_INTEL_ETAP_1.md
Raporty/RAPORT_MAP_ETAP_2.md
Raporty/RAPORT_MULTIFILE_ETAP_X.md
```

If `Raporty/` does not exist, create it.

---

# 4. Supported Rendering Backends

Treat ALL of the following as first-class supported paths.

## CPU

```text
CPU_REFERENCE
CPU fallback
```

CPU reference is the correctness baseline where such a reference implementation exists.

## AMD

Current AMD paths may include:

```text
D3D11
D3D11VA
AMF
AMD_NATIVE_D3D11
standard AMD/AMF pipeline
```

Do not assume all AMD paths are equivalent.

## NVIDIA

Current NVIDIA paths may include:

```text
CUDA
NVDEC
NVENC
hardware frame contexts
current NVIDIA GPU compositor path
```

Preserve the currently implemented NVIDIA architecture.

## Intel

Current Intel paths may include:

```text
D3D11 / DXVA where currently implemented
QSV
Intel hardware decode
Intel hardware encode
current Intel GPU pipeline
```

Intel is a full supported backend.

It must not be treated as a secondary or temporary implementation.

---

# 5. Cross-Vendor Mandatory Rule

A development machine's hardware does NOT define the supported product.

Absence of a vendor's GPU is not permission to:

- delete its code,
- simplify it away,
- bypass it,
- replace it with CPU,
- change its APIs speculatively,
- make another backend unconditional.

Specifically:

**Do not sacrifice NVIDIA compatibility to fix AMD.**

**Do not sacrifice AMD compatibility to fix NVIDIA.**

**Do not sacrifice AMD/NVIDIA compatibility to fix Intel.**

**Do not sacrifice Intel compatibility to fix AMD/NVIDIA.**

**Do not sacrifice correct CPU reference behavior merely to simplify GPU code.**

---

# 6. Intel Development Machine Rules

When working on an Intel development machine:

You may:

- run Intel/QSV runtime tests,
- benchmark Intel,
- inspect D3D11/DXVA/QSV behavior,
- optimize Intel-specific code.

You must also:

- preserve AMD paths,
- preserve NVIDIA paths,
- preserve CPU fallback,
- avoid Intel-only assumptions in shared modules,
- avoid introducing QSV-only dependencies into generic code,
- inspect diffs for accidental AMD/NVIDIA changes.

If AMD or NVIDIA cannot be runtime-tested, report:

```text
AMD path preserved statically; runtime validation was not possible on this machine.
```

and/or:

```text
NVIDIA path preserved statically; runtime validation was not possible on this machine.
```

Do NOT write:

```text
AMD/NVIDIA works
```

when only Intel was actually tested.

If the machine contains another GPU, for example an NVIDIA card, but the task explicitly requires Intel-only operation, do not initialize/use the other GPU merely because it exists.

Respect explicit backend selection.

---

# 7. AMD Development Machine Rules

On AMD hardware:

You may:

- test AMD,
- benchmark AMF/D3D11,
- inspect AMD-specific code,
- optimize AMD paths.

You must preserve:

- Intel,
- NVIDIA,
- CPU reference/fallback.

Do not claim Intel or NVIDIA runtime validation based on AMD tests.

---

# 8. NVIDIA Development Machine Rules

On NVIDIA hardware:

You may:

- test CUDA/NVDEC/NVENC,
- benchmark NVIDIA,
- optimize NVIDIA-specific code.

You must preserve:

- Intel,
- AMD,
- CPU reference/fallback.

Do not introduce CUDA-only requirements into shared modules.

---

# 9. CPU_REFERENCE Is the Correctness Baseline

Where a CPU reference implementation exists, treat it as the visual and semantic baseline.

GPU implementations may use different optimizations, but must preserve:

- geometry,
- position,
- scale,
- z-order,
- opacity,
- alpha,
- text,
- values,
- colors,
- timing,
- clipping,
- interpolation,
- orientation,
- data semantics,
- visibility rules.

Do not change CPU reference output merely to make a GPU implementation easier.

If a GPU result differs from CPU reference, investigate the GPU path first unless evidence proves the CPU reference is wrong.

---

# 10. Preview and Final Render Parity

TeleM has multiple visual paths.

Behavior must remain aligned between:

```text
main GUI preview
render/export preview
final export
CPU reference
GPU paths where applicable
```

A feature is not complete merely because it works in one of these.

When investigating a discrepancy, compare the paths at the **first point where their inputs or state differ**.

Do not immediately rewrite the renderer.

Compare items such as:

```text
target_dt
telemetry values
indicator config
bbox
map context
provider
orientation
render form
cached geometry
worker state
```

---

# 11. Indicator Work Must Stay Local

For tasks concerning:

- indicator appearance,
- fonts,
- ticks,
- labels,
- icons,
- gauge geometry,
- chart appearance,
- spacing,
- color,
- size,
- position,
- rotation,
- visibility,

do NOT redesign the video pipeline unless required.

Prefer the smallest change in:

```text
relevant indicator module
shared indicator primitive
indicator schema/config
shared geometry helper
backend implementation for that same indicator
```

Do not modify unrelated encoder/decoder code during a visual task.

---

# 12. Protected Rendering Areas

Do not modify these as a side effect of unrelated work:

- decoder selection,
- encoder selection,
- NVENC settings,
- AMF settings,
- QSV settings,
- D3D11 device creation,
- CUDA initialization,
- Intel hardware device setup,
- hardware frame contexts,
- FFmpeg hardware devices,
- pixel formats,
- color formats,
- color management,
- GPU frame ownership,
- synchronization,
- frame pooling,
- GPU upload/download,
- encoder handoff,
- backend priority,
- preview timing,
- final render timing,
- telemetry synchronization.

These require a dedicated task.

---

# 13. Do Not "Clean Up" Vendor Code Without Permission

Do not merge:

```text
AMD
NVIDIA
Intel
```

implementations merely because they look duplicated.

Vendor paths may intentionally differ because of:

- driver behavior,
- API restrictions,
- surface formats,
- memory layout,
- synchronization,
- resource lifetime,
- encoder requirements,
- hardware-frame restrictions,
- vendor performance characteristics.

Less duplicated code is NOT automatically better.

Correct behavior is more important.

---

# 14. Preserve Backend Selection

Do not:

- hard-code AMD,
- hard-code NVIDIA,
- hard-code Intel,
- force CPU silently,
- change backend priority,
- remove fallback paths,
- initialize an unrelated GPU without reason.

Use the current backend-selection architecture.

Any policy change must be explicitly requested.

---

# 15. Fallbacks Must Be Explicit

A fallback is acceptable when necessary.

It must:

- preserve correct output,
- have a documented reason,
- be logged,
- not silently become the normal path.

Do not remove a correctness fallback merely to improve benchmark results.

---

# 16. Diagnostic Logging Is Part of the Product Workflow

Preserve useful diagnostics.

Examples may include:

```text
AMD_MAP_PATH
AMD_CHART_PATH
AMD_GAUGE_PATH
AMD_TELEMETRY_MODE
AMD_AMF_MODE
Intel/QSV path diagnostics
NVIDIA path diagnostics
CPU_REFERENCE fallback reason
MultiFile diagnostics
MapPreload diagnostics
encoder path
hardware selection
```

When adding a fallback or backend branch, log:

```text
which path
why
```

Do not spam logs per frame unless a diagnostic task explicitly requires it.

---

# 17. Windows Console Logging Safety

TeleM is primarily developed on Windows.

Do not assume the console code page is UTF-8.

Diagnostic `print()` output must not crash because of Unicode characters.

Prefer ASCII-safe diagnostics such as:

```text
->
<=
>=
```

instead of decorative Unicode arrows/symbols unless the logging layer explicitly guarantees UTF-8.

A logging statement must NEVER prevent production logic from running.

---

# 18. GPU Memory Transfer Rule

TeleM's performance target is to keep frames on the GPU as long as practical.

Avoid unnecessary:

```text
GPU -> CPU -> GPU
```

round trips.

Do not introduce a CPU readback merely because implementation is simpler.

However:

```text
correctness > performance
```

If a GPU optimization changes image semantics, keep the correct fallback.

---

# 19. Z-Order Is Functional Behavior

Indicator order is part of the visual contract.

Do not reorder rendering stages casually.

Pay special attention to:

```text
map
charts
gauges
text
icons
above-map indicators
below-map indicators
```

If a GPU optimization requires a different compositing order and would change the image, retain the safe fallback.

---

# 20. Telemetry Data Flow Contract

Preferred architecture:

```text
FIT / GPX / GPMF / camera metadata
        ↓
telemetry parser
        ↓
canonical telemetry representation
        ↓
explicit source resolver
        ↓
time synchronization / offset
        ↓
interpolation / STEP semantics
        ↓
derived values
        ↓
unit conversion / formatting
        ↓
indicator renderer
        ↓
compositor
```

Indicator renderers should not invent their own telemetry source policies.

---

# 21. No Hidden Telemetry Source Priority

Do not reintroduce hidden source preference such as:

```text
FIT always wins
GPMF always wins
GPX always wins
```

when the user/project explicitly selected a source.

Respect explicit telemetry-source configuration.

Fallback behavior must follow the current resolver contract.

Map preload may use an available GPS source for technical preparation, but this must not silently change the data source of unrelated indicators.

---

# 22. FIT / GPX / GPMF Protection Rule

For visual tasks, do not alter:

- FIT parser,
- GPX parser,
- GPMF parser,
- SmartSync,
- timestamp extraction,
- telemetry interpolation,
- explicit source selection,
- pause semantics.

If the task concerns telemetry correctness, then inspect those systems deliberately.

---

# 23. GoPro Absolute Time Contract

Do not regress the accurate GoPro/GPMF time implementation.

When precise GPS9 timing is available, preserve use of:

```text
GPS9 days
GPS9 secs
```

and other existing reliable timing fields.

Do not revert to synthetic timing such as:

```text
creation_time + sample_index * 0.1
```

when more accurate embedded timing exists.

`creation_time` is not universally reliable.

---

# 24. Datetime Normalization Rule

TeleM has encountered bugs caused by mixing:

```text
timezone-aware datetime
timezone-naive datetime
```

Do not compare/subtract them without normalization.

Use the project's canonical UTC convention.

Do not fix datetime mismatches locally with random timezone stripping if a canonical helper already exists.

Preview, final render, GPMF, FIT, map and IMU calculations must agree on timestamp representation.

---

# 25. Multi-File Core Contract

TeleM supports:

```text
1 telemetry activity
+
N video clips
```

The final/global video timeline contains clips back-to-back.

Real-world gaps between video files are removed from the VIDEO timeline.

Example:

```text
clip1 absolute 10:05-10:15
clip2 absolute 10:35-10:50
```

Global video timeline:

```text
clip1 0-600
clip2 600-1500
```

There is NO 20-minute blank video section.

---

# 26. Three Different Times in Multi-File

Never confuse:

```text
GLOBAL PROJECT TIME
LOCAL CLIP TIME
ABSOLUTE TELEMETRY TIME
```

Contract:

```text
global_time
    ↓
VideoTimeline
    ↓
active clip
    ↓
local clip time
    ↓
absolute timestamp
    ↓
telemetry
```

Decoder/player uses:

```text
local clip time
```

GUI seek/progress uses:

```text
global project time
```

Telemetry uses:

```text
absolute timestamp
```

---

# 27. Multi-File Gaps

Real gaps between video files are intentionally removed from the output video.

Do NOT remove or compress pauses from FIT itself.

For example:

```text
video gap = removed from final video
FIT pause/activity semantics = preserved
```

Do not change FIT pause logic merely because clips are concatenated.

---

# 28. Multi-File File Order

Preserve the order chosen by the user.

Do not automatically reorder clips solely by:

```text
timestamp
filename
GoPro chapter naming
```

unless a task explicitly requests automatic sorting.

---

# 29. Multi-File Boundary Contract

Exactly at:

```text
clip1.global_end == clip2.global_start
```

the boundary belongs to:

```text
clip2 local=0
```

Preview, export, telemetry and tests must use one consistent boundary rule.

---

# 30. Multi-File Single-File Compatibility

A project with:

```text
video_clips = [clip0]
```

must behave like legacy single-file operation.

Do not create a separate duplicated renderer just for multi-file if the existing renderer can be generalized.

---

# 31. Multi-File GPMF Status Must Be Verified From Current Code

Do not assume full per-clip GPMF telemetry streams are already merged merely because per-clip absolute timestamps exist.

Before changing GPMF multi-file behavior, inspect the current code.

A report describing an older stage is not proof of the present implementation.

---

# 32. Map Architecture Contract

Map work is split into:

```text
GPS/map geometry
tile provider/cache
MapContext/preload
indicator rendering
current-position/heading logic
```

Do not collapse these concerns back into one synchronous renderer.

---

# 33. Map Preload Contract

Where current code implements MapPreload:

- start map preparation during project loading,
- use available FIT/GPX GPS early where appropriate,
- allow map preparation to run concurrently with heavy GPMF work,
- do not parse the same FIT fully twice unnecessarily,
- keep GUI responsive.

Heavy map preparation must not run synchronously in Qt GUI thread.

---

# 34. MapContext Contract

Where current code uses `MapContext`, preserve its role as shared prepared map state.

Typical state may include:

```text
generation_id
gps_source
gps_track
bounds
center
overview_zoom
provider
status
progress
required_tiles
loaded_tiles
overview_image
error
```

Do not create a second unrelated map state object inside an indicator unless explicitly required.

---

# 35. Map Overview-First Rule

If a coarse/overview map is ready, show it.

Do not keep displaying:

```text
Loading map...
```

merely because high-detail viewport tiles are still loading.

Preferred behavior:

```text
overview available
→ display overview immediately
→ load detail asynchronously
→ replace/refine later
```

Do not block first visible map on full-detail preparation.

---

# 36. Map Tile Bounds Rule

Initial overview map must use bounded tile counts.

If a route covers a large area:

```text
reduce map zoom
```

rather than constructing a gigantic high-resolution bitmap of the whole route.

Detail loading should generally cover the current viewport, not the entire activity at high zoom.

---

# 37. Map Provider Contract

Map geometry and provider/style are separate concerns.

Changing:

```text
Standard -> Satellite
```

must NOT require reparsing:

```text
FIT
GPX
GPMF
GPS track
```

Reuse existing geometry.

Change the tile provider/cache namespace.

---

# 38. Map Cache Contract

Tile cache keys must distinguish provider/style.

At minimum, cache identity must include the relevant equivalent of:

```text
provider/style
z
x
y
```

Standard and Satellite tiles must never collide.

---

# 39. Map Stale-Job Rule

Background map jobs must not overwrite newer state.

Use the current generation/job guard.

Example:

```text
Standard job generation 1
Satellite job generation 2
```

If generation 1 finishes later, its result must be ignored.

---

# 40. Map Preview vs Export Preview

If a map is correct in:

```text
export preview
```

but missing/stuck in:

```text
main preview
```

do NOT immediately blame:

- network,
- tile source,
- FIT bounds,
- downloaded tiles.

First compare the two runtime paths:

```text
MapContext identity
status
provider
overview_image
async_map
detail coverage
target_dt
render form
preview invalidation/refresh
```

Find the first divergence.

---

# 41. Map Placeholder Rule

A placeholder is valid only while usable map data is genuinely unavailable.

If `overview_image` for the active provider is ready, the map renderer should normally return/display that image rather than an indefinite placeholder.

Placeholder/progress must not become a permanent UI state.

---

# 42. GUI Thread Rule

Do not run long work in the Qt event thread.

Potentially heavy work includes:

- GPMF parsing,
- large JSON parsing/conversion,
- map tile network access,
- tile composition,
- large GPS processing,
- expensive preprocessing.

Use the existing worker/thread architecture.

Workers must communicate with GUI using appropriate signals/state.

Avoid GUI-thread:

```text
join()
wait()
future.result()
blocking queue.get()
```

for long tasks.

---

# 43. Loading Progress Rule

Loading progress should reflect real work where practical.

Do not fake smooth progress using timers.

For measurable operations, use real units such as:

```text
processed / total
tiles ready / tiles required
```

When exact percentage is unavailable, prefer a meaningful stage/status or indeterminate state.

Do not let the GUI appear frozen for a long time under an inaccurate label such as:

```text
Loading JSON 45%
```

if unrelated heavy work is actually occurring.

---

# 44. Indicator Interaction Contract

The user must be able to:

- click/select indicators,
- drag/move indicators,
- resize/configure them where supported,
- edit them in Properties.

The position modified by mouse dragging and by Properties must use the same underlying configuration.

---

# 45. Real Mouse Event Routing

Do not treat a successful direct call to:

```text
_hit_test()
```

as proof that real GUI interaction works.

The full runtime contract is:

```text
physical mouse
→ actual visible preview surface
→ Qt event
→ interaction handler
→ coordinate conversion
→ current bbox
→ hit-test
→ selection
→ controller state
→ Properties
```

MPV/QVideoWidget/native child windows may receive events differently.

When debugging interaction, identify the actual runtime receiver.

---

# 46. Headless Is Not Physical GUI Testing

Be precise in reports.

These are NOT equivalent:

```text
unit test
headless/offscreen Qt test
real visible GUI test
physical mouse test
```

Do not call an offscreen test a physical/manual GUI test.

If physical GUI interaction cannot be tested, write:

```text
REAL GUI PHYSICAL INTERACTION: NOT TESTED
```

---

# 47. Bounding Box Contract

Rendered indicator geometry and interaction geometry must agree.

Bboxes must correspond to:

- current frame,
- current layout,
- current canvas,
- current scale,
- current z-order.

Do not maintain a stale independent interaction geometry system.

---

# 48. Legacy Indicators

Do not reintroduce removed legacy indicators.

In particular, legacy IDs that have been intentionally removed must not return through:

```text
Reset Layout
registry
factory
default layout
old preset migration
```

Old projects containing removed IDs should preferably:

```text
skip removed indicator
log warning
continue loading
```

rather than crash or silently restore obsolete UI.

---

# 49. Reset Layout Rule

`Reset Layout` must use the current indicator system.

It must not recreate obsolete hard-coded indicators.

Do not treat reset as "load an old legacy preset" unless explicitly intended.

---

# 50. Chart Random-Access Contract

For a chart with:

```text
chart_window_s = W
```

at absolute time:

```text
t
```

history must be:

```text
[t-W, t]
```

subject to actual telemetry availability.

It must work when `t` is reached by:

- normal playback,
- forward seek,
- backward seek,
- first frame after load,
- final/random-access render,
- multi-file clip transition.

Chart history must not depend solely on samples accumulated since playback began.

---

# 51. Charts Must Be Causal

Do not use future samples to draw a chart at current time `t`.

No sample with:

```text
timestamp > t
```

may influence the chart unless a specific indicator explicitly defines non-causal behavior.

---

# 52. Multi-File Chart History

At the beginning of a later video clip, use the actual absolute telemetry time.

Example:

```text
clip1 end = 10:15
clip2 start = 10:35
chart window = 60 s
```

First chart frame in clip2 should query approximately:

```text
10:34-10:35
```

NOT:

```text
10:14-10:15
```

The FIT data in the removed video gap may legitimately be used for chart history.

---

# 53. Canonical Heading Contract

Use the existing canonical `heading` telemetry path.

Do not independently recalculate heading inside visual renderers unless the task explicitly concerns heading derivation.

---

# 54. Map Orientation Contract

Preserve the current semantics of:

```text
north_up
track_up
```

For `track_up`:

- rotate map according to canonical heading,
- directional marker should point according to the existing output-space contract,
- do not apply heading rotation twice.

For missing heading:

- do not fabricate a false physical heading merely to keep rendering moving.

Use the existing safe fallback.

---

# 55. Lean / IMU Indicator

Lean is no longer to be treated as automatically "deferred" merely because an older AGENTS version said so.

Inspect the current implementation.

If the current UI exposes and renders Lean:

- preserve its current canonical IMU/telemetry path,
- preserve preview behavior,
- maintain preview/final parity,
- do not independently recalibrate IMU during unrelated tasks.

Do not change physical lean sign/calibration without an explicit calibration task.

---

# 56. Altitude / Vertical Indicator Orientation

Text orientation is part of indicator semantics.

Do not rotate:

- labels,
- numeric text,
- units

merely because the gauge axis is vertical unless that is explicitly the intended visual contract.

Preview and final render must agree.

---

# 57. Export Resolution Contract

Do not assume that selecting a smaller export resolution automatically means all overlay work is performed at that resolution.

When optimizing resolution scaling, measure:

```text
decode resolution
overlay canvas resolution
compose resolution
encoder input resolution
```

before changing architecture.

Do not silently degrade indicator quality.

If scaling can happen earlier without changing semantics, treat that as a dedicated performance task.

---

# 58. Indicator Architecture Guidance

Where practical, separate:

## Data binding

Which canonical/resolved value is used.

## State

Current value, history, range, derived state.

## Geometry

Paths, coordinates, bboxes, ticks.

## Style

Fonts, colors, line width, fill, opacity.

## Rendering backend

CPU / AMD / NVIDIA / Intel specifics.

Avoid one large indicator module that independently resolves telemetry, computes physics, defines layout and manages GPU resources.

---

# 59. Reusable Indicator Families

Prefer reusable families where appropriate:

- text/digital indicators,
- horizontal gauges,
- vertical gauges,
- circular gauges,
- charts,
- bars,
- rotating icons,
- maps.

Do not create a completely separate rendering engine for every new indicator unless its semantics genuinely require it.

---

# 60. User-Configurable Layout

TeleM is not a fixed dashboard renderer.

Users must be able to configure layouts.

Do not hard-code one reference layout as the only allowed arrangement.

Preserve:

- enable/disable,
- position,
- size,
- source selection,
- styling,
- preset/project configuration.

Reference screenshots are visual targets, not architectural constraints.

---

# 61. Current Reference Assets

When present, reference assets under:

```text
wzor/
```

may be used for visual comparison.

Do not delete or replace them during unrelated work.

Do not infer new telemetry semantics solely from a screenshot.

---

# 62. Dependencies

Do not upgrade/replace major dependencies during unrelated tasks, including:

- FFmpeg,
- OpenCV,
- PyAV,
- Qt/PySide,
- NumPy,
- CUDA components,
- AMF components,
- DirectX/D3D dependencies,
- Intel/QSV integration,
- GPU rendering libraries.

A dependency change must have explicit justification.

---

# 63. No Opportunistic Refactors

Do not perform large refactors "while here."

Avoid unrelated:

- renames,
- module moves,
- renderer rewrites,
- architecture replacements,
- registry replacements,
- backend consolidation,
- dead-code purges.

If unrelated technical debt is discovered, report it separately.

---

# 64. No New Framework Without Need

Do not introduce:

- a new GUI framework,
- a new GPU framework,
- a new map engine,
- a new telemetry architecture,
- a new async framework

merely to fix a local bug.

Use existing project primitives where reasonable.

---

# 65. Task Scope Discipline

The task prompt defines allowed scope.

If the task says:

```text
AUDIT ONLY
```

do not leave production changes.

If the task concerns:

```text
map
```

do not optimize encoders.

If the task concerns:

```text
Intel
```

do not rewrite AMD/NVIDIA.

If the task concerns:

```text
mouse interaction
```

do not rebuild map loading.

Adjacent issues should be reported separately.

---

# 66. Work Sequence

Before changing code:

1. Read this entire `AGENTS.md`.
2. Read the exact current task.
3. Read reports explicitly named by the task.
4. Inspect current relevant code.
5. Identify affected paths:
   - CPU,
   - AMD,
   - NVIDIA,
   - Intel,
   - preview,
   - export preview,
   - final render.
6. Identify the smallest required scope.
7. Reproduce/measure the problem if practical.
8. Only then modify production code.

---

# 67. Root Cause Before Fix

Do not patch a symptom without identifying where the pipeline first becomes incorrect.

For example:

```text
correct tiles
→ wrong MapContext?
→ wrong preview state?
→ wrong compose?
```

or:

```text
correct bbox
→ event not delivered?
→ selection signal lost?
```

Find the first broken contract.

---

# 68. Diff Discipline

After modifications:

```text
git diff
```

must be inspected.

Check for:

- unrelated files,
- accidental generated files,
- accidental backend changes,
- debug instrumentation,
- stale temporary code.

Revert unrelated changes before completion.

---

# 69. Do Not Leave Debug Artifacts

Temporary:

- PNG dumps,
- raw YUV,
- huge logs,
- profiling frames,
- scratch exports

must not be left in tracked source directories unless the task explicitly requires them.

Use existing:

```text
scratch/
debug/
Raporty/
```

or equivalent appropriate locations.

Do not commit large video files.

---

# 70. Build Is Not Validation

A successful import/build means only that code can load/compile.

It does NOT prove:

- visual correctness,
- GPU execution,
- map visibility,
- mouse interaction,
- timeline correctness,
- telemetry correctness,
- final export parity.

Use appropriate runtime validation.

---

# 71. Targeted Test Economy

Do not run the entire test suite after every tiny edit.

During iteration, prefer:

```text
focused unit tests
focused integration test
short preview/render
short backend smoke test
```

Run broader regression when:

- shared infrastructure changed,
- task explicitly requires it,
- focused tests expose wider risk,
- preparing a major checkpoint.

---

# 72. Performance Test Economy

Do not repeatedly run long 4K exports while diagnosing a local issue.

Prefer short representative tests, often:

```text
720p
short duration
small segment
```

unless the bug only reproduces at full resolution.

Then validate the final relevant resolution once.

---

# 73. Performance Regression Rule

For performance-sensitive changes, measure relevant metrics where practical:

- preview FPS,
- frame time,
- compose time,
- telemetry lookup,
- decode,
- scale,
- encode,
- GPU usage,
- CPU usage,
- transfers,
- VRAM.

Do not claim optimization without measurement.

---

# 74. Test Hardware Path Selection

For GPU tests, verify the backend actually used.

Do not call a test:

```text
Intel test
```

if it silently fell back to CPU.

Do not call a test:

```text
AMD test
```

if it actually used a generic fallback.

Record backend diagnostics.

---

# 75. Unavailable Hardware

If a vendor backend is unavailable:

1. preserve it,
2. inspect it statically,
3. run shared/backend-neutral tests,
4. do not make speculative vendor-specific edits,
5. report it as not runtime-tested.

---

# 76. Full Regression Counts Are Not Permanent Contracts

Do not put a fixed expected total such as:

```text
650 tests
1044 tests
```

into architectural logic or assume such counts remain current.

The suite grows.

Report the actual result obtained in the current task.

---

# 77. Known-Failure Discipline

If tests fail:

do not automatically label them:

```text
pre-existing
```

Prove that assertion where practical by:

- checking baseline/clean state,
- checking unchanged affected files,
- reproducing before the new change,
- referencing recent reliable evidence.

Do not hide new regressions under "known failure."

---

# 78. Real Test Material

When available, current useful regression material includes:

```text
Video/GX010114.MP4
Video/GX010115.MP4
Video/GX010116.MP4
Video/Jazda_na_rowerze_w_porze_lunchu.fit
```

This combination is useful for multi-file + FIT testing.

Another commonly used pair is:

```text
Video/GX010115.MP4
Video/Jazda_na_rowerze_w_porze_lunchu.fit
```

The current task may specify newer material.

Task-specified material takes priority.

Do not assume historical offsets/timestamps still apply to a different MP4.

---

# 79. SmartSync

Do not rerun or redesign SmartSync during unrelated work.

Only modify SmartSync when:

- task explicitly asks for synchronization work,
- current evidence demonstrates incorrect alignment.

Do not use SmartSync as a workaround for an incorrectly determined per-clip absolute timestamp.

---

# 80. Project Loading

Project loading must remain responsive.

Do not serially perform independent heavy work if the existing architecture safely allows concurrency.

Current architecture may prepare map data concurrently with GPMF.

Do not regress this into synchronous GUI-thread work.

---

# 81. Cache Correctness

Caches must include every parameter that changes the cached output.

Examples:

```text
map provider/style
geometry
font
layout
size
orientation
render style
```

Do not improve cache hit rate by returning semantically wrong cached data.

Correct cache miss is better than incorrect cache hit.

---

# 82. Cache Invalidation

If changing a cache key or cache representation:

- preserve compatibility where reasonable,
- version the cache if needed,
- avoid serving stale incompatible entries.

Do not globally clear unrelated caches as a permanent solution unless unavoidable.

---

# 83. Thread Safety

Background workers must not directly mutate Qt widgets.

Use:

- signals,
- thread-safe shared state,
- generation IDs,
- existing project mechanisms.

Be careful with:

- SQLite connections,
- PIL images,
- process worker cache,
- shared memory,
- global context objects.

---

# 84. Stale Async Results

Any asynchronous work that may be superseded by:

- new project,
- new map provider,
- new layout,
- removed indicator,
- new generation,

must not overwrite current state when it finishes late.

Use generation/job identity.

---

# 85. Main Preview vs Export Preview Debugging

When one preview is correct and another is not:

do not assume renderer math is wrong.

Compare:

```text
input frame
target_dt
telemetry snapshot
indicator list
layout
map context
render flags
canvas resolution
backend mode
```

This comparison is often more valuable than rewriting shared rendering code.

---

# 86. Final Export Visual Parity

If an indicator:

- works in GUI preview,
- but freezes/disappears/rotates incorrectly in final export,

treat that as a parity bug.

Compare the data/state supplied to both paths before altering indicator geometry.

---

# 87. Audio and Multi-File

When multiple video clips are concatenated:

real-time gaps between clips must not create equivalent silent video gaps unless explicitly requested.

Preserve audio/video synchronization at clip boundaries.

Do not create intermediate re-encoded MP4 files merely to concatenate when the existing single-pipeline approach works.

---

# 88. Final Render Architecture

Prefer:

```text
N source clips
→ one logical global timeline
→ overlay
→ one final encoder pipeline
```

rather than:

```text
render N temporary MP4s
→ concatenate them
```

unless a task proves the latter is technically required.

---

# 89. GPU Backend-Specific Multi-File Limitations

Do not assume every vendor-specific native exporter automatically supports N input clips.

Inspect current implementation.

If a backend supports only one clip:

- do not silently render only clip 1,
- use/log the current safe fallback,
- or implement multi-file support only in a dedicated task.

---

# 90. Current Runtime Observations — Not Permanent Invariants

The following are currently observed issues/context and MUST be verified against the current branch before acting.

They are not permanent architecture rules.

## Main preview map

On the current Intel-machine test, map tiles were loaded during project loading, but the main preview remained for a long time in:

```text
Loading/Building map...
```

while export preview showed the map completely.

If still reproducible, compare main preview vs export preview state first.

Do not automatically redownload/rebuild all tiles.

## Indicator mouse interaction

A previous real GUI test showed that indicators could render and be moved through Properties while mouse selection/dragging did not work.

If still reproducible, debug actual Qt event routing rather than only unit-testing `_hit_test()`.

## Final export visual parity

Current user-observed issues have included:

- time area apparently covered/incorrect in final render,
- Lean icon moving in preview but not in final export,
- altitude indicator labels/text orientation incorrect in final export.

Do not assume these are still present after later changes.

Reproduce before modifying code.

---

# 91. Do Not Infer Implementation State From Report Names

A file such as:

```text
RAPORT_MULTIFILE_ETAP_4B_RENDER.md
```

does not by itself prove that the current branch contains or should contain every change from that report.

Always inspect:

```text
git status
git log
current source
current tests
```

when implementation state matters.

---

# 92. Current Map Reports

For map-specific tasks, recent reports may include:

```text
Raporty/RAPORT_MAP_PRELOAD_ETAP_1.md
Raporty/RAPORT_MAP_PRELOAD_ETAP_1B_RUNTIME_GUI.md
```

Read them if the map task explicitly depends on that work.

Verify current code afterward.

Do not read every report in `Raporty/` automatically.

---

# 93. Fresh-Agent Context Economy

Do not waste task time reading the entire repository or every historical report.

Fresh-agent startup:

1. read `AGENTS.md`,
2. read current prompt,
3. read explicitly relevant report(s),
4. inspect relevant code,
5. expand scope only if evidence requires it.

---

# 94. Changes Requiring Explicit User Request

Do not perform these without explicit scope:

- replace rendering architecture,
- merge vendor pipelines,
- delete CPU reference,
- replace FFmpeg,
- replace map provider architecture,
- rewrite telemetry synchronization,
- change project-wide pixel format,
- change global color-management policy,
- change backend default priority,
- remove a vendor backend,
- introduce a new GPU framework,
- migrate GUI framework.

---

# 95. Completion Report Contract

At the end of every coding task, report sections equivalent to:

## Changed

Exact production files and behavior changed.

## Root cause

What actually caused the demonstrated problem.

## Preserved

Important protected behavior/backends left unchanged.

## Tested

Exact tests and runtime scenarios actually run.

## Hardware tested

For example:

```text
Intel runtime: tested
AMD runtime: not available
NVIDIA runtime: not available
```

## Not tested

Anything relevant that could not actually be exercised.

## Performance

Only if relevant, with actual measurements.

## Risks / Remaining issues

Known limitations and deferred work.

## Report

Path under:

```text
Raporty/
```

if a report was requested.

---

# 96. No False Validation Claims

Never claim:

```text
works in real GUI
```

if only an offscreen test was run.

Never claim:

```text
NVIDIA works
```

if only static inspection was possible.

Never claim:

```text
performance improved
```

without measurement.

Never claim:

```text
bug fixed
```

when only a lower-level helper test passed but the original runtime scenario was not reproduced.

---

# 97. Final Rule

Prefer the smallest change that:

1. fixes the demonstrated root cause,
2. preserves current semantics,
3. preserves CPU/AMD/NVIDIA/Intel compatibility,
4. preserves preview/final parity,
5. preserves multi-file time semantics,
6. preserves telemetry source rules,
7. preserves z-order,
8. preserves safe fallbacks,
9. is covered by focused tests,
10. avoids unrelated refactoring.

Order of priorities:

```text
correctness
→ regression safety
→ measured performance
→ cleanup/refactoring
```

Do not reverse this order.