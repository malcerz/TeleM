# TeleM Integration — Multi-file input and HUD lifecycle fix

## Task

Fix project input ownership, repeated preview HUD compositing, and Reset Layout
semantics without changing renderer backends, indicator geometry, telemetry
timing, or encoding.

## Root causes

`build_timeline_from_paths()` preserves and probes only its supplied list. It
does not scan a directory, append MP4 files, inspect render outputs, or replace
a selected path. Thus `output_h265.mp4` entered before the timeline builder,
through the GUI signal payload or a stale caller-owned list; no downstream code
added it.

The confirmed HUD duplication cause was `inplace=self._playing` in preview.
Repeated rendering alpha-composited the HUD into the retained RGBA source frame,
so a later render composited another complete HUD. This was not three indicator
model instances.

Reset Layout previously retained only `time_display`; it did not rebuild the
complete `def_layout` or clear all visual state.

## Implementation

- LoadTab emits a copy of the explicit file-dialog selection.
- ProjectMixin snapshots, normalizes, de-duplicates, and keeps only that ordered
  list as `video_paths`; no project/output merge or directory scan is allowed.
  `TELEM_MULTIFILE_DEBUG=1` logs `[MultiFile Inputs]`.
- Preview uses `inplace=False`; a visual generation token rejects queued work
  from an old layout/project.
- Reset Layout loads `def_layout.json` once, replaces the entire layout, clears
  visual state, and renders one fresh preview without clearing telemetry caches.
  `TELEM_HUD_LIFECYCLE_DEBUG=1` logs lifecycle counts.

For an explicit selection, canonical inputs are exactly:

1. `GX010114.MP4`
2. `GX010115.MP4`
3. `GX010116.MP4`

## Tests

- `44 passed`: multi-file timeline/preview, new lifecycle tests, and reset
  regression test.
- `compileall` passed for changed modules.
- `git diff --check` passed.

The worktree has `GX010114.MP4`, `GX010115.MP4`, and `output_h265.mp4`, but no
`GX010116.MP4`. Real three-file GUI loading, clip-boundary seek, clip-3
timestamp, preview raster proof, and a short 015→016 export are therefore
**NOT TESTED / NOT PROVEN**. No substitute input was used.

## Changed files

- `src/gui/qt/tabs/load_tab.py`
- `src/gui/qt/_mixins/project_mixin.py`
- `src/gui/qt/_mixins/preview_mixin.py`
- `src/gui/qt/_mixins/indicator_mixin.py`
- `tests/test_multifile_hud_lifecycle.py`
- this report

## Backend isolation and status

No AMD, Intel, NVIDIA, encoder, telemetry-timing, or final-renderer code was
modified. Code-level lifecycle/input contracts: **PASS**. Real 014/015/016 GUI
and export acceptance: **NOT TESTED**. No commit and no push were performed.

## Git diff stat

## REAL 014/015/016 VALIDATION

Exact read-only inputs:

1. `C:\\_DEV\\TeleM\\Video\\GX010114.MP4`
2. `C:\\_DEV\\TeleM\\Video\\GX010115.MP4`
3. `C:\\_DEV\\TeleM\\Video\\GX010116.MP4`
4. `C:\\_DEV\\TeleM\\Video\\GX010114_116.fit`

The real GUI load produced exactly this ordered timeline: GX010114.MP4,
GX010115.MP4, GX010116.MP4. No `output_h265.mp4` or other unselected MP4 was
present.

| clip | source | quality | absolute start | absolute end |
|---|---|---|---|---|
| GX010114.MP4 | project_start_anchor | exact | 2026-08-14T11:18:03 | 2026-08-14T11:50:39.955 |
| GX010115.MP4 | gpmf_gps9 | exact | 2026-08-14T11:18:02.250270 | 2026-08-14T11:27:54.847603 |
| GX010116.MP4 | gpmf_gps9 | exact | 2026-08-14T11:32:09.735793 | 2026-08-14T12:01:13.477793 |

GX010116 used its own reliable GPMF timestamp and did not use
`continuous_fallback`.

Real offscreen Qt GUI lifecycle checks passed: initial load had 28 indicators;
seek 014 → 015 → 016 → 015 → 014 retained 28 indicators after every
transition; Reset Layout x2 logged `old=28 new=28`. Visual generation
invalidation rejected stale queued visual work without clearing telemetry.
Human visual inspection was not possible in the offscreen session.

Playback start/stop passed, but the harness did not run long enough to prove an
actual media-clock crossing of a clip boundary: **NOT PROVEN**.

A short 015→016 export was attempted with an output path in this repository,
but multiprocessing spawned from `<stdin>` failed with `OSError: Invalid
argument`; no output file was created. Export acceptance: **NOT PROVEN**.

Final verdict: **PARTIAL** — input ownership, GPMF timestamps, seek lifecycle,
and Reset Layout x2 passed; playback across a real boundary and short export
remain unproven due to the harness limitation.

The worktree was already dirty. The current tracked-file stat for the four
modified implementation paths is `4 files changed, 148 insertions(+),
67 deletions(-)`; it includes pre-existing uncommitted changes in those files.
The new test and this report are untracked and are therefore not included by
`git diff --stat`.
