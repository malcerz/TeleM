# AMD — FULL HUD MEMORY GROWTH / Pillow MemoryError

## Status

The production failure was reproduced without `tracemalloc`: Pillow raised
`MemoryError` in `Image.tobytes("raw", "RGBA")` while preparing the map or an
EXACT ABOVE dirty region. The largest map image was 978×978 RGBA (3,825,936
bytes), created once per frame. The native map path already had a direct-pointer
design, but it was never reached because the ctypes calls to
`PyCapsule_GetName`/`PyCapsule_GetPointer` had no prototypes and raised
`ArgumentError`. Thus every frame allocated and copied a new multi-megabyte
buffer; after roughly 1,300–1,400 frames this produced enough allocator/commit
pressure for Pillow to fail.

This was temporary-allocation churn/peak pressure, not an unbounded Python map
tile cache. The bounded tile cache remained at 256 entries after warm-up and
the Python image count plateaued. Native/D3D11 warm-up allocations remain
process-local and are not claimed to be eliminated by this change.

## Minimal implementation

Changed only the AMD exporter/test harness:

- Added `_pillow_rgba_contiguous_pointer()` in
  `src/ffmpeg/amd_native_exporter.py`. It installs explicit ctypes prototypes
  for the CPython capsule functions, validates the Pillow RGBA row table and
  returns a borrowed contiguous pointer plus stride.
- The map preparation path now uses that pointer while retaining the image
  reference in `PreparedFrame`; the byte-copy fallback remains available for
  unsupported Pillow layouts.
- Added opt-in (`AMD_MEMORY_AUDIT=1`) Windows process-memory/Pillow/map-cache
  sampling and bounded region-size diagnostics. It is disabled by default and
  does not enable `tracemalloc`.
- Added `tests/test_amd_map_pillow_pointer.py` (RGBA pointer byte parity and
  non-RGBA fallback).
- Extended the untracked scratch audit harness with component ablations and a
  configurable timeout; this does not alter production GUI behavior.

No native source, DLL, pipe writer, mux command, Stage A/B/C, watchdog, Intel
path, GPU-tap implementation, or Preview lifecycle code was changed.

## Ablation evidence (200 frames, same 4K full-HUD source)

| Ablation | frame-0 private after preparation | result | Render FPS |
|---|---:|---|---:|
| map removed | ~0.97 GB | PASS | 38.81 |
| charts removed | ~1.08 GB | PASS | 37.16 |
| gauge removed | ~1.09 GB | PASS | 36.59 |
| ABOVE removed | ~0.93 GB | PASS | 35.18 |
| BELOW removed | ~1.10 GB | PASS | 36.27 |
| lean removed | ~0.98 GB | PASS | 34.95 |

The map/ABOVE compositor accounts for substantial warm-up memory, but none of
these ablations showed an unbounded Python cache. The decisive difference was
eliminating the per-frame map `tobytes()` allocation.

## Memory trend after the fix

With `AMD_MEMORY_AUDIT=1` (no `tracemalloc`), full-HUD Preview ON showed:

| frame | private/commit | RSS | Pillow images | map tiles |
|---:|---:|---:|---:|---:|
| 0, after map | ~1.11 GB | ~0.55 GB | 264 | 422 |
| 2,000 | ~1.72 GB | ~0.86 GB | 744 | 302 |
| 3,000 | ~1.79 GB | ~0.92 GB | 746 | 306 |
| 4,000 | ~1.75 GB | ~0.89 GB | 750 | 314 |
| 6,000 | ~1.79 GB | ~0.93 GB | 761 | 330 |
| 7,000 | ~1.83 GB | ~0.97 GB | 767 | 342 |
| 9,000 | ~1.80 GB | ~0.83 GB | 773 | 354 |

This is a warm-up/plateau pattern, not the former multi-megabyte map-copy
churn. Exact ABOVE regions stayed bounded (largest observed 2,247,264 bytes).

## Acceptance runs

All runs used the canonical scratch source/layout, 3840×2160, native D3D11/AMF,
Preview GPU tap where enabled, and no `tracemalloc`.

| Test | Result | Render FPS | Effective FPS | ffprobe |
|---|---|---:|---:|---|
| Full HUD, Preview OFF, 3,000 | PASS | 58.55 (profile) | — | 3,000 HEVC frames |
| Full HUD, Preview OFF, 10,000 | PASS | 37.25 | 36.49 | 10,000 HEVC frames, 3840×2160 |
| Full HUD, Preview ON, 3,000 | PASS | 38.73 | 37.00 | 3,000 HEVC frames, 3840×2160 |
| Full HUD, Preview ON, 10,000 | PASS | 35.62 | 34.89 | 10,000 HEVC frames, 3840×2160 |
| Chrome-running foreground attempt, 3,000 | PASS render | 30.31 | 29.20 | 3,000 HEVC frames |

The 10,000-frame OFF/ON files were validated with `ffprobe` as HEVC,
3840×2160, exactly 10,000 video frames plus AAC audio. No `MemoryError`, pipe
failure, false cancel, or invalid MP4 occurred in these completed runs.

## Tests

```text
python -m pytest -q tests/test_amd_map_pillow_pointer.py \
  tests/test_amd_above_exact_tight_bbox_etap10r.py
16 passed

python -m pytest -q tests/test_amd_gpu_frame_tap_preview.py \
  tests/test_amd_background_preview_audit.py \
  tests/test_amd_native_ordered_map.py
8 passed
```

Edit-preview lifecycle/parity unit coverage remained green; no edit-preview
code was changed. A real interactive play/pause/seek GUI session was not
automated in this headless audit.

## Chrome foreground caveat

Chrome was running during the 3,000-frame foreground attempts and rendering
passed. In this Windows session `SetForegroundWindow` returned `False` and
`GetForegroundWindow()` returned `0`, so an OS-level proof that Chrome—not
another desktop window—held foreground focus is **NOT PROVEN**. This is an
environment limitation, not a renderer failure.

## Final assessment

- Root cause: **confirmed** per-frame Pillow map `tobytes()` fallback caused by
  missing ctypes PyCapsule prototypes; this created sustained allocation/peak
  pressure and eventually exposed the same failure site in ABOVE region
  conversion.
- Python/map cache: bounded after warm-up.
- Native/D3D11: warm-up memory remains process-global/driver-managed; no native
  leak claim was made or changed here.
- 3,000/10,000 OFF and ON: **PASS**.
- No MemoryError / no pipe failure in completed acceptance runs: **PASS**.
- GPU-preview regression: ON 10,000 effective FPS 34.89 vs OFF 36.49
  (4.4%, within the requested 10%): **PASS**.
- Chrome foreground proof: **NOT PROVEN**.
- Edit Preview interactive parity: **NOT TESTED** in this headless session.

**READY: NOT READY** — the renderer/memory fix is validated, but the requested
OS-level Chrome-foreground and interactive Edit Preview checks still require a
user-visible GUI session.
