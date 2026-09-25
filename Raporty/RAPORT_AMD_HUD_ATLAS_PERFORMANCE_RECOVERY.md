# RAPORT: AMD HUD Atlas Performance Recovery & Bottleneck Analysis

## 1. Executive Summary & Mandatory Variables

```text
ATLAS_MODE_BEFORE=FULL_CANVAS_FALLBACK
ATLAS_MODE_AFTER=PACKED

CANVAS_PIXELS=8294400 (3840x2160)
ATLAS_PIXELS_BEFORE=8294400 (3840x2160)
ATLAS_PIXELS_AFTER=6318400 (3590x1760)

ATLAS_MB_BEFORE=33.18 MB
ATLAS_MB_AFTER=25.27 MB

FULL_CANVAS_REGRESSION_PROVEN=True

BARE_FPS=42.867 (effective 38.033 FPS)
HUD_FPS=21.480 (effective 19.248 FPS)
MAP_FLAT_FPS=16.716 (effective 14.977 FPS)

HUD_ATLAS_COPY_MS=27.82 ms (producer buffer preparation / PIL upload copy)
SHM_WRITE_MS=0.00 ms (direct pointer / internal pipe)
FFMPEG_WRITE_MS=0.00 ms (GPU direct AMF encode)
CPU_HUD_RENDER_MS=17.60 ms (Pillow indicator compose_overlay)

RAWVIDEO_CONTRACT=PASS
OOM_ERRORS=0
AMF_INIT=PASS

BASELINE_35FPS_RECOVERED=False (HUD=21.48 FPS, capped by CPU producer)
TARGET_38FPS_RECOVERED=False
STRETCH_40FPS_RECOVERED=False

MAP_CORRECTNESS=FROZEN (unmodified)
ONE_RENDER_PROGRESS_BAR=True

ROOT_CAUSE=Atlas height calculation in get_layout_hud_regions overestimated bar/text indicators causing packing height to reach 2980px (>2160px), triggering safety fallback to 3840x2160 full canvas. After fixing packer to 3590x1760, profiling proved GPU consumer runs at ~53 FPS (18.7ms), but Python CPU producer thread takes ~46.4ms (17.6ms Pillow drawing + 27.8ms RGBA frame buffer memory handling), keeping FPS at ~21.5 FPS.
FIX=Tightened indicator bounds estimations (horizontal bar height from runaway 856px to realistic 240px; text bounding box) and added multi-candidate packing engine (Best-Fit Decreasing shelf packing + hierarchical clustering).

TOTAL_STAGE_WALL_TIME=~30 min
LONGEST_SINGLE_COMMAND_SECONDS=20.75 s

CASE=CASE D — full-canvas regression fixed but another bottleneck remains
```

---

## 2. Initial State & Problem Statement

In the previous frame-contract crash fix, a safety condition was added to `src/ffmpeg/command_builder.py`:
```python
if (
    best_res is None
    or best_res[0] > canvas_w
    or best_res[1] > canvas_h
    or best_res[0] * best_res[1] >= canvas_w * canvas_h
):
    return canvas_w, canvas_h, [(0, 0, 0, 0, canvas_w, canvas_h)]
```
Because the existing hierarchical clustering packing algorithm frequently produced packed heights exceeding 2160 px (specifically 2980 px for standard 4K layouts), this condition triggered on **100% of 4K renders**, forcing the system into `FULL_CANVAS_FALLBACK` (3840x2160 RGBA = 33,177,600 bytes/frame).

User reports indicated real GUI production renders ran at ~21 FPS despite GPU utilization at ~78%.

---

## 3. Step 1: Atlas Logging & Contract Verification

Initial diagnostic run on `GX010303.layout.json` (4K canvas: 3840x2160):
- `PACKED_ATLAS_W`: 1832 px
- `PACKED_ATLAS_H`: 2980 px (> 2160 px!)
- `PACKED_ATLAS_PIXELS`: 5,459,360 px
- `ATLAS_MODE`: `FULL_CANVAS_FALLBACK`
- `FALLBACK_REASON`: `packed_h (2980) > canvas_h (2160)`
- `FINAL_ATLAS_W`: 3840 px
- `FINAL_ATLAS_H`: 2160 px
- `FINAL_ATLAS_PIXELS`: 8,294,400 px
- `FINAL_FRAME_BYTES`: 33,177,600 bytes (33.18 MB)

**Conclusion:** `FULL_CANVAS_REGRESSION_PROVEN=True`. The atlas was indeed falling back to full 4K canvas on every frame.

---

## 4. Root Cause Analysis

Two interacting factors caused the packed atlas to blow past 2160 px height:
1. **Gross Overestimation of Indicator Bounds:**
   - For horizontal bar indicators, the legacy code used:
     ```python
     bh = max(60, min(856, int(canvas_h * 0.40) + 60))  # 856 px on 4K!
     ```
     Real horizontal bars are typically only 60–120 px tall. Estimating 856 px forced massive vertical shelves.
   - Text bounding boxes were also padded up to `int(canvas_h * 0.10) + 20` (236 px) regardless of font size.
2. **Rigid 6-Cluster Permutation Packing:**
   - The hierarchical clustering clustered indicators down to 6 groups, then tried all permutations of a single-shelf layout. If cluster heights summed to >2160 px on a single shelf or 2 tall rows, it breached 2160 px.

---

## 5. Technical Implementation (The Fix)

File modified: [command_builder.py](file:///C:/_DEV/BikeRideHUD-amd/src/ffmpeg/command_builder.py)

1. **Tightened Bounding Box Estimations:**
   - Horizontal bars: capped at `max(60, min(240, int(size_px * 0.10) + 60))`.
   - Text boxes: width `min(canvas_w - bx1, int(canvas_w * 0.20))`, height `min(canvas_h - by1, int(canvas_h * 0.08))`.
   - Guaranteed even alignment (`x % 2 == 0`, `w % 2 == 0`).
2. **Multi-Candidate Packing Strategy:**
   - **Candidate 1: Best-Fit Decreasing (BFD) Shelf Packing:** Sorts individual bounding boxes by descending height, finds best fitting shelf with minimum vertical waste within `canvas_w`.
   - **Candidate 2: Multi-level Hierarchical Clustering:** Evaluates packing at every clustering iteration, selecting the permutation with smallest total area.
   - Filters all candidates that exceed `canvas_w` or `canvas_h`.
   - Ranks candidates by total pixel area with a slight bias for fewer disjoint regions.
3. **Safety Fallback Preserved:**
   - If no candidate fits within `canvas_w x canvas_h`, the full canvas fallback remains active as guaranteed OOM protection.

### Verification Across All Production 4K Layouts
- `GX010303.layout.json`: 3590x1760 (25.27 MB, 76.2% of 4K, 9 regions, `PACKED`)
- `def_layout.json`: 3590x1760 (25.27 MB, 76.2% of 4K, 9 regions, `PACKED`)
- `GX010115.layout.json`: 3590x1760 (25.27 MB, 76.2% of 4K, 9 regions, `PACKED`)
- `GX020079.layout.json`: 3590x1760 (25.27 MB, 76.2% of 4K, 9 regions, `PACKED`)
- Direct region mapping: 15/15 indicators mapped (100% assigned, 0 unassigned).

---

## 6. Empirical Performance Gate (300 Frames A/B Test)

Conducted on canonical AMD benchmark dataset (`Video/GX020079.MP4` + `Video/GX020079.fit`):

| Test Condition | Render FPS | Effective FPS | Encode Duration | Wall Time | Pipeline Time (GPU Consumer) | Producer Time (CPU Preparation) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A. HUD OFF, MAP OFF** | **42.87 FPS** | 38.03 FPS | 6.998 s | 8.78 s | **18.62 ms** | 0.00 ms |
| **B. HUD ON, MAP OFF** | **21.48 FPS** | 19.25 FPS | 13.967 s | 16.36 s | **18.73 ms** | **46.39 ms** |
| **C. HUD ON, MAP ON (flat)** | **16.72 FPS** | 14.98 FPS | 17.947 s | 20.75 s | **19.39 ms** | **60.13 ms** |

### Breakdown of Time in HUD ON Path (46.39 ms producer):
- `above_compose` (Pillow CPU indicator rendering): **17.60 ms**
- `above_total_ms_avg` / buffer preparation (memory handling of 25.27 MB RGBA buffer): **27.82 ms**
- GPU consumer pipeline: **18.73 ms** (capable of **53.4 FPS**!)
- GPU consumer wait on queue: **27.89 ms** (consumer is completely starved waiting for CPU producer!)

### Map Flat Cost:
- Difference between HUD ON (MAP OFF) and HUD ON (MAP ON): `60.13 ms - 46.39 ms = 13.74 ms`
- Drops FPS from 21.48 down to 16.72 FPS.

---

## 7. Gate Decision & Safety Discipline

Because `HUD ON` 300f FPS is **21.48 FPS (< 35 FPS minimum requirement)**:
- Per Rule 8 and Rule 10: **Long runs (1000f, 6000f, 38k f) are STRICTLY STOPPED AND PROHIBITED**.
- `CASE D — full-canvas regression fixed but another bottleneck remains` is declared.
- Moving the atlas from 33.2 MB down to 25.3 MB saved 7.9 MB per frame of bandwidth (a 23.8% reduction), but the Python Pillow indicator rendering (17.6 ms) plus host memory buffer manipulation (27.8 ms) totals 46.4 ms per frame, creating an insurmountable 21.5 FPS ceiling in the CPU producer thread.

---

## 8. Artifacts Manifest

Saved in `scratch/amd_atlas_regression/`:
- `atlas_contract.txt`: Full atlas geometry and mode comparison
- `atlas_before_after.csv`: Summary metrics table before vs after
- `packing_regions_before.csv`: 1 region (3840x2160)
- `packing_regions_after.csv`: 9 packed regions (3590x1760)
- `300f_hud_off.txt`: Run summary for Test A
- `300f_hud_on.txt`: Run summary for Test B
- `300f_map_flat.txt`: Run summary for Test C
- `frame_contract.txt`: Verification of byte equality and AMF init
- `performance.txt`: Detailed timing breakdown from profile JSONs
- `root_cause.md`: Detailed root cause documentation
- `fix.md`: Step-by-step description of packer improvements
- `modified_files.txt`: List of modified files (`src/ffmpeg/command_builder.py`)
- `created_files.txt`: Artifact files inventory
- `reproduction_commands.txt`: Commands to reproduce tests
- `artifacts_manifest.txt`: SHA256 checksums of all artifacts
- `ntfy_result.txt`: NTFY push receipt
