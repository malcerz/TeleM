# TeleM — Integration — Chart Transparency and Axes Fix

## Task

Separate chart fill transparency from the chart line and chart structure, align
axes/labels with the indicator font system, and make time/value autoscaling
deterministic for preview and final rendering.

## Initial state and root cause

Chart rendering is shared by preview and final render through
`src/indicators/chart.py` and `src/indicators/chart_utils.py`.

The existing `fill_alpha` was intended for the area polygon, but axes, grid,
ticks, and labels were rasterized into the same image before that polygon. A
semi-transparent fill could therefore alter the final pixels of structural
chart elements. Axis labels also had no general text outline and their default
font size was not tied to the indicator's general font sizing.

## Implementation

- `fill_alpha` remains applied only to the area polygon.
- The polyline is drawn with alpha 255.
- Axes, grid, ticks, and axis labels are kept in an immutable structural layer
  and composited after the fill and line. Structural colors do not inherit
  `fill_alpha`; grid strokes are stored as opaque structural pixels.
- Axis labels use the same `font_path` and indicator-derived font size as the
  chart's general text system, while an explicitly configured
  `label_font_size` remains respected.
- Axis labels now use the general text outline (`axis_outline`), and the axis
  cache key includes all font/outline parameters to prevent stale cache reuse.
- The same structural-layer ordering is used by the progressive prefix path.
- Window time ticks now use a shared nice-step generator and retain
  time-accurate positions. The 60-second contract remains `-60, -45, -30,
  -15, 0 s`.
- Automatic value scales now use a padded 1/2/5-style domain and matching
  value ticks. Explicit `min_val`/`max_val` and explicit labels remain
  authoritative.

Preview and final render continue to call the same chart utility path; no
backend-specific code was changed.

## Changed files

- `src/indicators/chart.py`
- `src/indicators/chart_utils.py`
- `tests/test_chart_transparency_axes_autoscale.py`

The worktree already contained unrelated user modifications. They were
preserved and not included in the implementation scope.

## Tests

Passed:

```text
python -m pytest -q tests/test_chart_transparency_axes_autoscale.py \
  tests/test_chart_rendering.py tests/test_chart_axis_cache.py \
  tests/test_etap10m2_chart_time_axis.py tests/test_etap6_chart_window.py \
  tests/test_etap5e_preview_export_parity.py
28 passed
```

The broader chart-related selection produced `125 passed, 1 skipped` and the
following unrelated/known failures:

- 3 progressive-prefix parity assertions use `time_scope=activity` while the
  production progressive-prefix condition is limited to `time_scope=window`;
  this is outside this task and was not changed.
- 3 chart seek tests require the absent fixture
  `Video/Jazda_na_rowerze_w_porze_lunchu.fit`.

`python -m py_compile` passed for the changed Python modules and test. `git
diff --check` passed.

## Acceptance summary

- Fill transparency isolated from line: PASS.
- Fill transparency isolated from axes/grid/ticks/labels: PASS.
- General font and outline used for axes/labels: PASS.
- Time-axis autoscale: PASS.
- Value-axis autoscale: PASS.
- Preview/final shared-path parity: PASS in the targeted parity suite.
- Other indicators and GPU backends: unchanged by this task.

## Diff/stat and risks

Task-specific tracked diff:

```text
src/indicators/chart.py       |  26 +++---
src/indicators/chart_utils.py | 188 +++++++++++++++++++++++++++++++++---------
2 files changed, 161 insertions(+), 53 deletions(-)
```

The repository-wide tracked `git diff --stat` also includes pre-existing dirty
work from earlier tasks (`32 files changed, 772 insertions(+), 641 deletions(-)`).

Risk: automatic scales can gain a small visual margin compared with the old
raw data extrema when no explicit min/max is configured. Explicit scales are
unchanged. The missing FIT fixture and activity-prefix test contract remain
unresolved and should be handled separately.

## Final status

PASS for the requested chart transparency/axes implementation. No commit and
no push were performed.
