# NVIDIA final Git freeze — 2026-09-18

## Scope

This is a selective snapshot of the current NVIDIA research state. No production
code was changed by the freeze operation; the working tree was audited and only
explicitly selected NVIDIA source/configuration and reports were staged.

## Initial audit

Commands executed before staging:

```text
git status
git branch --show-current
git log -1 --oneline
git remote -v
git diff --stat
git diff --name-only
git ls-files --others --exclude-standard
```

```text
SOURCE_BRANCH=main
BASE_COMMIT=1b5485c
REMOTE=origin https://github.com/malcerz/TeleM.git
```

The pre-existing worktree contains a large mixture of tracked changes and
untracked benchmark/build/render artifacts. Scratch outputs, source videos,
generated binaries, build trees, and unrelated backend changes were intentionally
left outside this snapshot.

## Stage policy

ADD:

- `native/d3d11_nvenc_pipeline` source/configuration files changed in the current NVIDIA state, including the untracked HUD profile and Lean indicator source files.
- `src/ffmpeg/nvidia_config.py`
- `src/ffmpeg/nvidia_native_exporter.py`
- `src/ffmpeg/streaming.py`
- `src/ffmpeg/worker_cache.py`
- NVIDIA final/parity reports under `Raporty/` listed in `STAGED_FILES`.

SKIP:

- all `scratch/` render outputs, logs, benchmark time series, MP4/HEVC/YUV files,
  temporary scripts not required for the snapshot, and input `Video/` media;
- native build directories, object files, DLL/PYD/EXE/PDB artifacts and CMake
  caches;
- tracked scratch/archive deletions and unrelated AMD/GUI/telemetry changes;
- reports outside `Raporty/` (the repository report-directory rule is preserved).

## Freeze result

```text
SOURCE_BRANCH=main
SNAPSHOT_BRANCH=nvidia-final-20260918
BASE_COMMIT=1b5485c
NEW_COMMIT=b1518cc (primary snapshot commit; subsequent commits only finalize report/NTFY bookkeeping)
PUSH_RESULT=SUCCESS (origin/nvidia-final-20260918)

STAGED_FILES=28 files: native/d3d11_nvenc_pipeline NVIDIA source/config (15 files), src/ffmpeg/nvidia_config.py, src/ffmpeg/nvidia_native_exporter.py, src/ffmpeg/streaming.py, src/ffmpeg/worker_cache.py, scratch/nvidia_real_perf_truth/run_gui_render.py, and 8 Raporty reports (including this report and cadence parity)
SKIPPED_FILES=pre-existing non-NVIDIA tracked changes, scratch outputs, build/generated binaries, input media, unrelated reports/files
SKIPPED_LARGE_ARTIFACTS=MP4, HEVC, YUV, PNG, DLL, EXE, PDB, OBJ, build/CMake cache, benchmark logs/time-series

REMOTE_BRANCH_VERIFIED=True (git ls-remote --heads origin nvidia-final-20260918 matched the local upstream branch)
WORKTREE_REMAINING_FILES=2083 pre-existing changes (1149 deletions, 904 untracked; none staged)
NTFY_SUCCESS=True (3/3 attempts, exit code 0)
```

No AMD synchronization, merge, cleanup, or force-push is part of this freeze.
