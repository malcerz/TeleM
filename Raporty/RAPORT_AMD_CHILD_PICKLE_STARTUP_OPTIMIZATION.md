# AMD CHILD PROCESS — PICKLE / STARTUP OPTIMIZATION

## Task and scope

AMD-only optimization of the real GUI `RenderJob` transport. Intel/QSV,
NVIDIA/NVENC/CUDA, HUD pixels/layer order, GUI IN/OUT semantics and the bounded
child-process lifecycle were not changed.

Initial branch/HEAD: `integration/intel-amd` / `59277b4`. The worktree was
already dirty and was preserved. No reset, clean, rebase, commit or push was
performed.

## Exact root cause

The observed `~106.16 MB / 12.35–13.86 s` payload was not caused by Windows
spawn itself. It was already materialized in the long-lived GUI before the
RenderJob dictionary was built.

An opt-in one-shot provenance diagnostic was added:

```text
TELEM_LAZY_MATERIALIZATION_AUDIT=1
```

It showed these exact production stacks on the real two-clip project:

1. `ProjectMixin._merge_clip_telemetry()` called
   `curr.sort(key=lambda x: x[0])` after joining cache-backed IMU vectors.
   The callback sort caused `LazySampleList.sort()` to expand the complete
   `accelerometer_samples` and `gyroscope_samples` lists.
2. `IndicatorMixin._discover_data_streams()` ran
   `vals = [v for _, v in samples]` for each of the eight axis/magnitude
   fields only to calculate the DataStream min/max. `__iter__()` then expanded
   all eight 274,920-sample fields into Python datetime/tuple lists.
3. The normal Preview then requested Lean. Its full, deterministic Lean
   timeline is genuinely required, but it previously expanded both raw vector
   source lists before deriving it.

Thus the eight `field_samples` handed to spawn were materialized during project
load/Preview preparation, not by `pickle.dumps` and not by a GUI callback in
the child.

## Architecture chosen

No cache-path descriptor layer was necessary. The proven `LazySampleList`
pickle contract remains the child transport:

- `sort_by_timestamp()` sorts the backing NumPy timestamp column stably;
- IMU DataStream min/max reads the backing `arr[:, 1]` with NumPy instead of
  enumerating Python sample tuples;
- Lean Preview computes the same derived roll cache directly from the compact
  `[timestamp, x, y, z]` arrays, avoiding expansion of the two raw sources;
- the derived Lean timeline remains the existing deterministic Python timeline
  used by preview/final interpolation, preserving its semantics.

The materialization audit is dormant by default and emits at most one stack per
object only when explicitly enabled.

## Lazy state — real GUI load and Preview seek

Real project:

```text
D:\GoPro\2026-09-01\GX010244.MP4
D:\GoPro\2026-09-01\GX010245.MP4
D:\GoPro\2026-09-01\12_naprawiony.fit
D:\GoPro\2026-09-01\GX010244.layout.json
```

The audit opened the real QApplication/Controller/Window and sought to clip 1
start/middle/end, the clip boundary, and clip 2 end.

Before the fix, diagnostics reported materialization of both vectors plus all
eight axis fields. After the fix the final audit emitted **no**
`[LAZY MATERIALIZE AUDIT]` line. Before and after all seeks, all eight
transported fields were `LazySampleList(materialized=False, count=274920)`.

## Transport measurements

| Measurement | Before | After, real GUI runs |
|---|---:|---:|
| RenderJob pickle size | 106,162,823 B (101.25 MiB) | 48,967,150–48,967,155 B (46.70 MiB) |
| Preflight `pickle.dumps` | 12.35–13.86 s | 1.690–1.956 s |
| `Process.start → JOB RESTORED` | 14–15 s | 2.048–2.783 s |
| Eight IMU fields | materialized | all lazy |

All targets pass: size <60 MiB, pickle <3 s, startup <5 s.

The diagnostic preflight still performs a second serialization deliberately;
it now costs <2 s and remains the spawn-contract safeguard. The actual spawn
serialization is measured separately by `JOB RESTORED`; no unsafe removal of
the validation was made.

## Telemetry and Preview parity

- Scalar telemetry resolution (`speed`, `altitude`, `distance`, HR, cadence,
  power, slope, gyro, accel) was not changed; only range discovery changed from
  tuple enumeration to equivalent NumPy min/max.
- `compute_roll_timeline_from_arrays()` has a direct parity unit test against
  the prior tuple-based complementary-filter implementation, including exact
  timestamps and roll values.
- Cold GUI load plus real seek positions on clip 1, boundary and clip 2 passed
  with Lean enabled and no materialization audit events.
- Real AMD outputs remained valid: 1000/1000 and 10000/10000 frames, GPU
  Preview ON, and Edit Preview restore after each render.

Formal surface-before-HEVC pixel hash comparison is **NOT TESTED**: no HUD
compositing code was changed.

## Real AMD matrix

Results: `D:\GoPro\2026-09-01\TeleM_child_final_acceptance_20260908_120356\acceptance_results.json`

| Run | pickle ms | child restore ms | terminal | muxed frames | Preview restored |
|---|---:|---:|---|---:|---|
| 1 | 1789.226 | 2262.459 | completed | 1000 | yes |
| 2 | 1748.734 | 2145.361 | completed | 1000 | yes |
| 3 | 1690.233 | 2097.878 | completed | 1000 | yes |
| 4 | 1801.621 | 2048.779 | completed | 1000 | yes |
| 5 | 1727.966 | 2217.569 | completed | 1000 | yes |
| 10000 | 1956.149 | 2782.677 | completed | 10000 | yes |

Five-run memory plateau: PASS.

```text
parent private: 2,198,016,000 → 2,263,330,816 B
handles:        1215, 1215, 1209, 1211, 1211
threads:        68, 68, 66, 66, 66
```

10000f full HUD / GPU Preview ON:

```text
requested = decoded = native processed = muxed = 10000
cross-clip plan = 5000 + 5000
render FPS = 40.963
effective FPS = 39.384
video render wall = 244.125 s
final mux = 3.216 s
```

No orphan child or output residue remained. GUI IN/OUT/cross-clip accounting,
terminal completion, Preview restore, cancel cleanup and Event-log safety were
not modified; their dedicated previous production acceptance remains valid.
The new matrix also found no Event 2004/DWM/D3D11 event.

## Tests

```text
py_compile changed modules: PASS
pytest selected regression suite: 89 passed, 1 deselected
real cold GUI lazy audit: PASS
real Preview seek across both clips: PASS
real 1000f AMD child smoke: PASS
5 sequential real 1000f: PASS
real 10000f full HUD/GPU Preview: PASS
```

The deselected test is pre-existing `test_zero_offset_subtracts`, whose expected
offset sign conflicts with the current dirty-tree implementation; it is outside
this task and untouched.

## Changed files

- `src/telemetry_processed_cache.py` — audit flag/labels and lazy timestamp sort.
- `src/gui/qt/_mixins/project_mixin.py` — lazy-safe merge sort.
- `src/gui/qt/_mixins/indicator_mixin.py` — NumPy IMU range discovery.
- `src/telemetry_imu.py` and `src/gui/telemetry_manager.py` — array-backed Lean
  precompute with tuple-path parity retained.
- `scratch/run_amd_child_final_gui_acceptance.py` — audit-only/smoke/startup-matrix
  modes plus Lazy state capture; default full acceptance remains unchanged.
- `tests/test_telemetry_processed_cache.py`, `tests/test_lean_imu_contract.py`.

## Final status

```text
EDIT PREVIEW PARITY: PASS
TELEMETRY PARITY: PASS
LAZYSAMPLELIST REMAINS LAZY: PASS
PICKLE SIZE < 60 MiB: PASS
PICKLE TIME < 3 s: PASS
CHILD STARTUP < 5 s: PASS
1000f REAL RENDER: PASS
5 SEQUENTIAL RENDERS: PASS
10000f FULL HUD: PASS
MEMORY PLATEAU: PASS
NO ORPHAN: PASS
GUI IN/OUT STILL PASS
CANCEL STILL PASS (unchanged path; prior production acceptance)
NO EVENT 2004/DWM/D3D11: PASS

STATUS: READY
```
