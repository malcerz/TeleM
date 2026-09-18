# RAPORT NVIDIA Native D3D11 — final geometry and cadence gate

## TASK

Close the Preview-to-Native cadence-chart hard gate for the canonical NVIDIA
Native D3D11 GUI Device-B HEVC render. AMD, Intel, AV1, H264, and the
default-backend paths are out of scope.

## STATUS

Automated parity is PASS. The refreshed package is ready for the user's
manual visual check; `USER_VISUAL_ACCEPTANCE` remains `PENDING` by design.

```text
FINAL_CASE=CASE A
CHART_GEOMETRY_PARITY=PASS
GAUGE_GEOMETRY_PARITY=PASS
RULER_GEOMETRY_PARITY=PASS
SEGMENT_BAR_GEOMETRY_PARITY=PASS
TEXT_GEOMETRY_PARITY=PASS
MAP_GEOMETRY_PARITY=PASS
LEAN_GEOMETRY_PARITY=PASS
CADENCE_GEOMETRY_PARITY=PASS
CADENCE_FILL_ALPHA_PARITY=PASS
CADENCE_CHART_PARITY=PASS
FINAL_PREVIEW_TO_MP4_PARITY=PASS
USER_VISUAL_ACCEPTANCE=PENDING
```

## Initial state

The previous final MP4 failed the cadence hard gate: Native used a smaller,
shifted plot and had no visible area fill (`fill_alpha=0`). The prior measured
Native geometry was outer `1112x438`, plot `1070x263`, with `plot_y=1776`.

## Changed files

- `src/ffmpeg/nvidia_native_exporter.py`: normalize byte or normalized fill
  alpha exactly once, bind cadence geometry to the Legacy chart contract, send
  complete FIT history and activity duration, and emit Python trace stages.
- `native/d3d11_nvenc_pipeline/src/indicators/chart_indicator.cpp/.h`:
  preserve normalized alpha through brush creation, perform the cadence
  `FillGeometry` before the one-pixel outline, and emit C++ draw/brush traces.
- `native/d3d11_nvenc_pipeline/src/d3d11_nvenc_pipeline.cpp`: emit C ABI and
  descriptor-copy trace stages.

No layout, AMD, Intel, AV1, H264, or default-backend behavior was changed.

## Cadence contract (actual 3840x2160 pixels)

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

Preview and Native configured contracts match. The fresh Native crop contains
`249585` yellow area pixels and `295` dense fill rows; Preview contains
`227934` and `273`, respectively. The visible data bboxes are data-dependent
and are recorded separately in `cadence_plot_contract.csv`.

## Alpha/ABI proof

`fill_alpha_trace.csv` proves the chain
`layout 200 -> Python 0.784313725 -> C ABI 0.784313738 -> C++ brush
0.784313738 -> FillGeometry 0.784313738`. `cadence_draw_trace.csv` records
all required frames with `sample_count=1704`, `fill_enabled=1`, one
`FillGeometry` call and one `DrawGeometry` call. `chart_abi_layout.csv` records
`PYTHON_SIZE=420`, `CPP_SIZE=420`, and `ALL_OFFSETS_MATCH=True`; `fill_enabled`
and `line_width` are renderer semantics, not ABI fields.

## Tests

- `python -m py_compile ...` — PASS.
- `cmake --build native/d3d11_nvenc_pipeline/build_lean_final --parallel 4` —
  PASS; Native DLL relinked.
- 30-frame Native HEVC smoke — PASS.
- 300-frame Native HEVC render with GUI Device-B contract — PASS; output is
  `scratch/nvidia_native_cadence_fix/run300b/native_300_cadence_fix_deviceb.mp4`.
- GUI Native 1131-frame smoke — exit 0, D2D HRESULTs zero,
  `full_frame_readback_count=0`.
- GUI Native 300-frame repeat ×3 — all repeats exit 0; no D2D error lines,
  `full_frame_readback_count=0`.
- Decoded frame crops, points, ranges, duration and draw traces are under
  `scratch/nvidia_native_cadence_fix/`.

## Reports and package

- Detailed cadence report: `Raporty/RAPORT_NVIDIA_NATIVE_D3D11_CADENCE_CHART_FIX.md`.
- Small parity report: `Raporty/cadence_chart_parity.md`.
- Manual package: `scratch/nvidia_native_user_acceptance/`.
- The package contains the refreshed Native 300-frame HEVC MP4 and the five
  requested compare images/contact sheet. `README.txt` instructs the user to
  inspect the left Legacy and right Native images.

## Risks / not tested

`USER_VISUAL_ACCEPTANCE` is intentionally `PENDING`: only the user can give
the final visual acceptance. No AV1, H264, default-backend, AMD, or Intel
render was run. Full-frame HEVC/Pillow-vs-DirectWrite differences remain
diagnostic, not a byte-identical gate.

## Final summary

```text
GEOMETRY=PASS
VISUAL_PACKAGE=PASS
FINAL_PREVIEW_TO_MP4_PARITY=PASS
USER_VISUAL_ACCEPTANCE=PENDING
NTFY_ATTEMPTS=3
NTFY_SUCCESS=True
STOP_AFTER_THIS_STAGE=True
```
