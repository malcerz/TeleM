CADENCE_GEOMETRY_PARITY=PASS
CADENCE_FILL_PRESENT_PREVIEW=PASS
CADENCE_FILL_PRESENT_NATIVE=PASS
CADENCE_FILL_ALPHA_PREVIEW=0.784314
CADENCE_FILL_ALPHA_NATIVE=0.784314
CADENCE_FILL_ALPHA_PARITY=PASS
CADENCE_FINAL_STATUS=PASS
CADENCE_CHART_PARITY=PASS

Source frames are actual 3840x2160 HEVC Native D3D11 GUI Device-B output.

Geometry contract (configured and traced):
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

Separate measured/configured contracts:
PREVIEW_outer_x=169
PREVIEW_outer_y=1602
PREVIEW_outer_w=1160
PREVIEW_outer_h=532
PREVIEW_plot_x=212
PREVIEW_plot_y=1688
PREVIEW_plot_w=1080
PREVIEW_plot_h=350
PREVIEW_baseline_y=2038
PREVIEW_left_axis_x=212
PREVIEW_right_axis_x=1292
PREVIEW_top_y=1688
PREVIEW_bottom_y=2038
NATIVE_outer_x=169
NATIVE_outer_y=1602
NATIVE_outer_w=1160
NATIVE_outer_h=532
NATIVE_plot_x=212
NATIVE_plot_y=1688
NATIVE_plot_w=1080
NATIVE_plot_h=350
NATIVE_baseline_y=2038
NATIVE_left_axis_x=212
NATIVE_right_axis_x=1292
NATIVE_top_y=1688
NATIVE_bottom_y=2038

Style:
line_present=True
line_color=#FFFF7F
line_thickness=1 px
fill_present_preview=True
fill_present_native=True
fill_color=#FFFF7F
fill_alpha_preview=0.784314
fill_alpha_native=0.784314
grid_present=True
grid_color=#444444
grid_alpha=1.000

Raster evidence:
{
  "preview": {
    "path": "scratch\\nvidia_native_final_geometry\\frames\\legacy\\frame_007.png",
    "fill_pixels": 227934,
    "bbox": [
      220,
      1752,
      1288,
      2039
    ],
    "row_max": 968,
    "col_max": 316,
    "dense_rows": 273,
    "configured_plot": [
      212,
      1688,
      1292,
      2038
    ]
  },
  "native": {
    "path": "scratch\\nvidia_native_cadence_fix\\run300b\\frames\\native_08.png",
    "fill_pixels": 249585,
    "bbox": [
      216,
      1730,
      1292,
      2039
    ],
    "row_max": 1010,
    "col_max": 339,
    "dense_rows": 295,
    "configured_plot": [
      212,
      1688,
      1292,
      2038
    ]
  }
}

Trace evidence: fill_alpha_trace.csv, cadence_draw_trace.csv, cadence_fill_polygon.csv, cadence_brush_trace.txt
Artifacts: crops/cadence_preview.png, crops/cadence_native.png, crops/cadence_overlay.png, crops/cadence_diff.png
