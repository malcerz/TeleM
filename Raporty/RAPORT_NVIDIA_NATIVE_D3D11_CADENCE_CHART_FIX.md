# RAPORT NVIDIA Native D3D11 — cadence chart hard-gate fix

## TASK

Diagnose and correct cadence-chart parity in actual Preview-vs-final Native
HEVC MP4 pixels, including outer/plot geometry and semi-transparent area fill.

## Initial state

The user reported `CADENCE_CHART_PARITY=FAIL`. The prior final Native frame
had outer `(169,1602,1112,438)`, plot `(212,1776,1070,263)`, no visible fill,
and `fill_alpha_native=0.0`, while Preview used
outer `(169,1602,1160,532)`, plot `(212,1688,1080,350)`, and alpha `200/255`.

## Implementation

The NVIDIA-only path now normalizes either byte-style or normalized fill alpha
once, binds chart canvas fields to the Legacy chart contract, sends complete
FIT cadence history plus activity duration, and renders a filled polygon before
the one-pixel cadence outline. Trace hooks record Python, C ABI, C++ member,
brush, polygon, and draw-call values. ABI audit confirms no packing change was
needed.

## Measurements

```text
outer_x=169
outer_y=1602
outer_w=1160
outer_h=532
plot_x=212
plot_y=1688
plot_w=1080
plot_h=350
baseline_y=2038
left_axis_x=212
right_axis_x=1292
top_y=1688
bottom_y=2038

line_present=True
line_color=#FFFF7F
line_thickness=1 px
fill_present=True
fill_color=#FFFF7F
fill_alpha_preview=0.784314
fill_alpha_native=0.784314
grid_present=True
grid_color=#444444
grid_alpha=1.000
```

## Required fields

```text
CADENCE_GEOMETRY_PARITY=PASS
CADENCE_FILL_PRESENT_PREVIEW=PASS
CADENCE_FILL_PRESENT_NATIVE=PASS
CADENCE_FILL_ALPHA_PREVIEW=0.784314
CADENCE_FILL_ALPHA_NATIVE=0.784314
CADENCE_FILL_ALPHA_PARITY=PASS
CADENCE_FINAL_STATUS=PASS
CADENCE_CHART_PARITY=PASS
FINAL_PREVIEW_TO_MP4_PARITY=PASS
USER_VISUAL_ACCEPTANCE=PENDING
```

## ABI and runtime proof

- `chart_abi_layout.csv`: Python and C++ `TelemChartStyle` are both 420 bytes;
  every field offset matches; `ALL_OFFSETS_MATCH=True`.
- `fill_alpha_trace.csv`: layout raw `200`, Python normalized
  `0.784313725`, C ABI/C++/brush `0.784313738`, and pre-Fill value unchanged.
- `cadence_draw_trace.csv`: frames `0,1,2,10,50,100,150,250,299`, each with
  1704 samples, 1706 polygon points, fill enabled, alpha `0.784313738`, one
  FillGeometry call and one DrawGeometry call.
- `cadence_fill_polygon.csv`: baseline left `212`, right `1292`, y `2038`,
  closed polygon on every selected frame.
- `cadence_range_trace.csv`: raw cadence 1704 samples, range `0..87`,
  configured Native chart range `0..86` and history duration `1703 s`.

## Tests

```text
python -m py_compile ...                         PASS
cmake --build ... --parallel 4                  PASS
Native HEVC Device-B 30-frame smoke             PASS
Native HEVC Device-B 300-frame render           PASS
GUI Native HEVC 1131-frame smoke                PASS (exit 0)
GUI Native HEVC 300-frame repeat 1/2/3           PASS (exit 0)
D2D HRESULTs                                     0x00000000
full_frame_readback_count                       0
```

The first direct non-Device-B harness was not used as acceptance evidence
because its complete HUD disappeared after the short ring window. The final
render and all GUI stability runs use the production Device-B contract.

## Artifacts

All cadence artifacts are under `scratch/nvidia_native_cadence_fix/` and are
mirrored into `scratch/nvidia_native_user_acceptance/` where relevant:

```text
crops/cadence_preview.png
crops/cadence_native.png
crops/cadence_overlay.png
crops/cadence_diff.png
cadence_chart_parity.md
fill_alpha_trace.csv
chart_abi_layout.csv
cadence_draw_trace.csv
cadence_fill_polygon.csv
cadence_brush_trace.txt
cadence_plot_contract.csv
cadence_points_preview.csv
cadence_points_native.csv
cadence_points_diff.csv
cadence_range_trace.csv
cadence_duration_trace.csv
root_cause.md
```

## Backend isolation / risks

Changes are confined to NVIDIA Native exporter/chart tracing and the rebuilt
Native DLL. AMD production defaults, AMD map/charts, Intel QSV/device/surface
paths, AV1, H264, and default backend were not run or changed. The automated
gate is PASS; the user must still inspect the visual package, so acceptance is
not promoted to PASS.

## Final summary

```text
CADENCE_GEOMETRY_PARITY=PASS
CADENCE_FILL_ALPHA_PARITY=PASS
CADENCE_CHART_PARITY=PASS
FINAL_PREVIEW_TO_MP4_PARITY=PASS
USER_VISUAL_ACCEPTANCE=PENDING
STOP_AFTER_THIS_STAGE=True
```
