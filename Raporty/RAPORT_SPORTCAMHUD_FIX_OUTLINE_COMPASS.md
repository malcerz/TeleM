# SportCamHUD: outline, distance-faded shadow and compass modes

Date: 2026-10-11 (Europe/Warsaw)
Branch: `fix/gui-freeze-hud-composite`
Initial HEAD: `fa8ba86f2f10e04d7629e1c3d2487487834b52c7`
Status: implementation and shared-surface/Qt tests PASS; full native encoded export NOT TESTED.

## 1. Scope and initial state

Read AGENTS.md and BENCHMARKS.md. Preserved the existing user modifications in
`def_layout.json` (altitude decimals, compass position, integration setting).
The default layout was neither edited nor staged. No encoder/backend, audio,
Live Mux, AutoFIT, GPMF cache, map, chart or GUI geometry changes were made.
The property editor gains the requested compass mode control and Effects tab.

The user confirmed both compass variants must be selectable. After being told
that the earlier expanded style implementation could not be recovered, the user
stated that no older copy exists and authorized adding configurable shadow and
outline with range/length and fading with distance. Thus this is an authorized
new configurable implementation, not a claim of pixel-exact recovery of the
unavailable October style.

## 2. Outline/shadow diagnosis

The current numeric/time/lean renderers still contain the established black
text stroke. The global `text_outline=3` setting also remains present. Therefore
it is NOT PROVEN that all text stroke disappeared or that a recent performance
commit omitted this parameter.

Earlier reference images (`tests/artifacts/compass_shadow_outline.png`,
`gauge_shadow_outline.png`, and `Raporty/assets/compass_rose_090.png`) and the
October 5 needle-width report describe expanded outline/shadow controls.
The current rasterizers and GUI schemas do not implement those fields. They
ignore `outline_enabled`, `shadow_enabled`, shadow length and fade. Searching
Git history, unreachable source blobs and other local source copies did not
recover that implementation. The exact commit responsible is NOT PROVEN.
The older gauge-width test cannot even collect because its helper
`resolve_gauge_needle_width_px` is absent at the initial HEAD.

## 3. Compass diagnosis and repair

Vectorized export preparation selected `fit.heading or fit.track or track_samples`
for the shared heading column. Track samples represent distance, not angles.
It also ignored the compass-selected GPMF/FIT/GPX source. Preview uses the
heading resolver, so preview and export could disagree or show the wrong course.

Added a compass-specific `heading_compass` column sourced from the canonical
selected-source resolver. Never substitute distance or another source when
course is missing. Preserve missing samples and normalize aware timestamps to
UTC. Other consumers retain their current heading column contract. Existing
render-telemetry caches are invalidated for enabled-compass layouts with a
contract key; the GPMF cache is unchanged.

Modes:
- `needle` (default): static north-up dial, course rotates the needle.
- `rose`: course-up ticks/cardinal positions, needle points up. Cardinal text
  stays upright. Angle positions use geographic bearing minus course.

Both modes use the same samples and shared renderer. Missing heading keeps the
dial without a false-north needle. Cache keys include mode and rose orientation.
Legacy needle raster is byte-identical to initial HEAD in seven tested headings.

## 4. Shared effects implementation

`src/indicators/effects.py` adds one alpha-mask implementation, applied after
canonical numeric indicator rendering and to the time display. It includes:
- outline enable, width/range, color, opacity and distance fade;
- shadow enable, offset, trail length, angle, color, opacity and distance fade.

Logical distances are pixels at 540p and scale with the smaller canvas dimension.
Outline uses alpha dilation; shadow uses shifted masks and a decreasing alpha
profile. The original art and existing text stroke are composited last.
Symmetric transparent padding contains the effect while preserving the original
art position, size and rotation centre. Bounds include the additional support.
For styled gauges the existing full-tile capture fallback is requested instead
of using needle-only dirty regions that could clip the effects. Backends are not
modified. Native encoder-specific support for all styles is NOT PROVEN.

Effects are opt-in (`outline_enabled` / `shadow_enabled` default false), so existing
layouts keep their current pixels. To use them, select an indicator and enable
Obrys/Cien in the **Efekty** tab. The compass mode is in **Compass / Obracanie
kompasu**. The default layout remains the user's layout.

## 5. Changed files

- `src/render_preparation.py`
- `src/render_telemetry_cache.py`
- `src/indicators/gauge.py`
- `src/indicators/effects.py` (new shared helper)
- `src/indicators/dispatcher.py`
- `src/indicators/compositor.py`
- `src/gui/qt/models.py`
- `src/gui/qt/widgets/property_editor.py`
- `tests/test_compass_source_parity_hotfix.py`
- `tests/test_indicator_effects_hotfix.py`
- this report and `Raporty/assets/sportcamhud_outline_compass/` evidence.

## 6. Validation

Command (QT_QPA_PLATFORM=offscreen):

```text
python -m pytest tests/test_indicator_effects_hotfix.py tests/test_compass_source_parity_hotfix.py tests/test_property_editor_scroll.py tests/test_common_render_preparation.py tests/test_etap5e_preview_export_parity.py tests/test_telemetry_heading.py tests/test_pixel_indicator_style.py tests/test_compositing_etap5e.py tests/test_etap5e5_transparent_roi.py tests/test_amd_native_above_dirty_bbox.py -q
```

Result: **60 PASS**.

Covered selected GPMF/FIT source, absent course, missing markers, UTC offset,
359/0/1 wrap, course-up cardinal positions at 0/90/180/270, both modes in the
actual Qt property editor, effect controls, fade and length changes, intact
original art, padding/clipping, white-background text/gauge/bar/compass,
960x540 / 1920x1080 / 3840x2160 shared surface parity, compositor overlap/ROI
and existing AMD bbox helpers. These are deterministic telemetry fixtures;
no real-video dataset was substituted or benchmarked.

Eight compass samples compared reference and optimized compositing:
`max_diff=0`, `MAE=0`, `different_pixels=0` for every sample.
Export-preview compositing at brightness 1 matches the final reference surface
byte-for-byte. This proves shared pre-encode surfaces, not native encoded output.
The animated turning fixture and white-background contact sheet were generated;
the contact sheet was visually inspected.

Evidence:
- [Bright-background comparison](assets/sportcamhud_outline_compass/bright_comparison.png)
- [Turning compass](assets/sportcamhud_outline_compass/compass_turn.gif)
- [Surface measurements](assets/sportcamhud_outline_compass/surface_parity.json)
- [Legacy needle comparison](assets/sportcamhud_outline_compass/legacy_needle_parity.json)

Additional pre-existing failures (outside the 60-PASS set):
- `test_compass_gui_schema_exposes_common_and_compass_specific_controls` expects
  old field/source/gauge_style controls absent at initial HEAD.
- `test_gauge_property_live_preview` expects thickness absent at initial HEAD.
- `test_gauge_needle_width_parity.py` fails collection due to the missing helper.
These contracts were not changed merely to mask the failures.

## 7. Limits, performance and Git

Full interactive preview with real moving video and native AMD/Intel/NVIDIA
encoded export: **NOT TESTED**. Full GPU style/parity acceptance remains open.
No FPS performance claim. Enabled mask effects add rasterization work; disabled
ones return the original raster without mask processing. No benchmark run.
The older `scripts/test_amd_real.py` still references an audio-cache validation
path, so it was not used as an acceptance shortcut against AGENTS section 20.

Git diff --check: PASS. User `def_layout.json` remains unstaged and unchanged
from the starting worktree. Only task files and this task's evidence are committed.
Implementation/report commit subject: `fix(hud): compass source and selectable rose; configurable faded effects`.
Resolve the exact commit with `git log -1 --format=%H -- Raporty/RAPORT_SPORTCAMHUD_FIX_OUTLINE_COMPASS.md`.
No push performed.

Summary: requested controls and source repair implemented; shared renderer and
Qt acceptance PASS. Exact recovery of unavailable old expanded style NOT PROVEN;
replaced by the user-authorized configurable effects. Full native real-video
visual acceptance NOT TESTED, so the broader acceptance is not declared complete.
