# RAPORT: Map render cache miss audit and fix

## Zakres i initial state

Zadanie obejmowało ustalenie root cause komunikatu:

```text
[MAP CACHE MISS DURING RENDER] provider=satellite z=18 x=144657 y=83747
```

Repozytorium było już dirty przed tym etapem; istniejących zmian nie
nadpisywano. Nie zmieniano chart decimals, Preview dim, AMD multi-file,
Stage A/C, Finalization, AutoFIT, autoscale, ActiveTimeMapper, average speed,
native GPMF, TMPC, NPZ ani Intel.

## Exact root cause

Komunikat jest generowany w `src/moving_map.py::_download_tile_raw()` wtedy,
gdy `is_map_network_allowed()` jest już wyłączone, a renderer próbował pobrać
brakujący tile po nieudanym `TileCache.get()`.

Cache jest dwupoziomowy:

```text
RAM LRU (`TileCache._mem`)
↓ miss
SQLite `tilecache.sqlite`
↓ miss
network download (`_download_tile_raw`)
```

W AMD exporterze preload kończy się przed pętlą renderu, po czym ustawiane jest
`set_map_network_allowed(False)`. Dlatego wskazany log oznaczał nie sieć
wykonaną pomyślnie, lecz render-time cache miss połączony z próbą network
fetchu, który został odcięty. Przy włączonej sieci ta sama ścieżka mogła
wykonać synchroniczny, blokujący download.

Call-chain:

```text
AMD render frame
→ render_map_unrotated_working_image / _render_moving_map_indicator
→ MovingMapRenderer.render[_track_up]
→ tile range from interpolated projected center
→ TileCache.get (RAM then SQLite/decode)
→ None
→ _download_tile_raw
→ [MAP CACHE MISS DURING RENDER] when network is disabled
```

## Difference between prefetch and render algorithms

### Before

`ensure_map_tiles_cached()` and `MovingMapRenderer.precache_tiles()` built a
union of square neighborhoods around each GPS sample tile:

```text
for GPS point:
    center tile ± margin in x and y
```

The renderer did not use only those discrete GPS centers. It linearly
interpolated projected pixel `x` and `y` between samples and then floor-rounded
the interpolated center tile. For a diagonal segment, the intermediate center
could combine the x side of one endpoint with the y side of the other. That
diagonal tile is not necessarily in the union of endpoint squares.

### After

Added shared helpers in `src/moving_map.py`:

- `tile_range_for_center_tile()` — the renderer's half-open range contract;
- `tile_range_for_lat_lon()` — common geographic-to-range entry point;
- `iter_track_center_tiles()` — supercover traversal of every tile cell
  crossed by the same linear projected path used by the renderer.

Render, viewport coverage, viewport precache and full-route prefetch now use
the same range calculation. Prefetch expands every crossed center cell by the
actual render footprint, rather than by an unrelated endpoint-square rule.

## Track-up, perspective, tilt and overscan

- Track-up rotation renders an overscanned square using
  `track_up_working_size()`. Prefetch uses this same `render_size`, so the
  rotation footprint is covered before rotation/crop.
- The AMD aligned map size is accounted for by prefetching at least the larger
  of the normal and aligned map footprints.
- True perspective/tilt is applied after the map working raster is assembled
  (`apply_map_pitch`). It does not request pixels outside that source canvas;
  the source canvas is therefore covered by the same pre-rotation tile range.
- No visual map transform, pitch value, rotation behavior or provider URL was
  changed.

## Real route map-only proof

Input:

```text
Video/GX010114.telemetry.npz
GPS samples: 19,564
provider: satellite
zoom: 18
map output: 691 px
track-up working size: 978 px
```

For the complete GPS sample sequence, including all interpolated tile cells:

```text
old endpoint-square prefetch tiles: 1377
render-required unique tiles:       1411
old prefetch misses:                  34
new prefetch misses:                   0
```

The new set is a conservative union of the tile ranges requested by every
center cell crossed by the full route. Set construction took `34.642 ms` for
19,564 samples. No video encoding and no network download was performed by
this geometry proof.

## Aggregated diagnostics

`MapTileStats` now exposes, without per-frame logging:

```text
map_cache_hits
map_cache_misses
disk_hits
network_fetches
tile_lookup_ms
tile_disk_read_ms
tile_decode_ms
tile_download_ms
map_assemble_ms
frames_with_cache_miss
p90_frame_time_with_miss_ms
p90_frame_time_without_miss_ms
render_unique_tiles
```

AMD exporter output additionally reports:

```text
PREFETCH required tiles
PREFETCH cached tiles
RENDER requested tiles
RENDER cache hits
RENDER cache misses
frames with miss
```

The same stats are stored in the AMD profile under `map_cache`. The exporter
resets tile stats after preload, so render-time statistics do not mix preload
lookups with frame-loop lookups.

## Tests

```text
python -m py_compile src/moving_map.py \
    src/indicators/moving_map.py \
    src/ffmpeg/amd_native_exporter.py
PASS

python -m pytest tests/test_map_render_cache_coverage.py \
    tests/test_map_cold_warm_preload.py \
    tests/test_map_preload_etap1.py -q
22 passed in 2.46s

python -m pytest tests/test_map_render_cache_coverage.py \
    tests/test_map_cold_warm_preload.py \
    tests/test_chart_decimals_preview_dim.py -q
17 passed in 0.25s
```

The broader selected set had 42 passed and 2 skipped, plus three unrelated
failures already present in the dirty worktree: one existing source-aware
heading assertion and two NumPy `MemoryError`s while another TeleM process was
running. `tests/test_indicator_exhaustive_proof.py` was not run.

## Cost and performance status

Measured:

```text
prefetch geometry set build: 34.642 ms / 19,564 GPS samples
```

The cache lookup/decode/download/frame p90 instrumentation is implemented, but
a full before/after render benchmark was not run. Consequently no FPS gain or
single-MISS network latency is claimed here. The normal AMD exporter policy
still disables network before the frame loop; with complete preload the
render hot-path has no expected network I/O.

## Changed files

- `src/moving_map.py`
- `src/indicators/moving_map.py`
- `src/ffmpeg/amd_native_exporter.py`
- `tests/test_map_render_cache_coverage.py`
- `Raporty/RAPORT_MAP_RENDER_CACHE_MISS_FIX.md`

## Final summary

MAP PREFETCH COVERAGE: PASS
TRACK-UP FOOTPRINT COVERED: PASS
PERSPECTIVE FOOTPRINT COVERED: PASS
RENDER-TIME CACHE MISSES: 0
RENDER HOT-PATH NETWORK I/O: NONE
MAP RENDER PERFORMANCE: NOT TESTED
