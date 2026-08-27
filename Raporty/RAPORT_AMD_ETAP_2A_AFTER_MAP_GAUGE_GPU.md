# RAPORT AMD ETAP 2A — AFTER-MAP GPU Speed Gauge (cross-widget parity fix, validation, benchmark)

**Data:** 2026-08-25 · **Branch:** `amd-render` @ `d9afa75` · **Backend:** `AMD_NATIVE_D3D11`

---

## 1. Task

ETAP 2A: AFTER-MAP GPU Speed Gauge (`AMD_AFTER_MAP_GAUGE_GPU`, default **OFF**).
This stage completed:

1. verification that the destructive early-clear fix reaches zero parity on the
   originally-failing `dist_visual` ROI,
2. root-cause analysis of newly surfaced HUD-canvas diffs,
3. ghosting validation (needle sweep),
4. full 1131-frame benchmark REF vs CAND,
5. this report.

## 2. Initial state (handoff)

* Early-clear reorder + below-widget force-dirty were implemented; the original
  2253-px missing-ruler diff was fixed (DIST_VISUAL ROI = 0 on frames 30/300).
* The strict gate surfaced NEW diffs: GAUGE=5037 px, CADENCE=985 px, HR=2404 px,
  identical counts on frames 30 and 300 → suspected *static* cause.
* Signature: `ref=(0,0,0,0)` vs `cand=(0,0,0,170)`, strips along the ruler band
  extending beyond the assumed widget bbox.

## 3. Root cause (evidence chain)

1. `GPU_CHART_UNSAFE_LAYOUT -> all charts CPU_REFERENCE` (both runs) — charts
   ride inside the CPU ABOVE layer in BOTH runs. The unsafe-layout log revealed
   the TRUE `dist_visual` bbox: `(1373,1549,1095,98)` — far wider than the
   assumed `(1445,1575,299,47)`.
2. Compose ground-truth dumps (`composed_img`, env-gated probe) contain a
   translucent ruler band: **2683 pure `(0,0,0,170)` px**, byte-identical
   (MD5) between REF and CAND runs → the α=170 content is REAL compose data.
3. Three-way zone table (frames 30 & 300, HUD canvas vs compose truth):

   | zone | ref~truth | cand~truth | ref~cand | wiped ref | wiped cand |
   |---|---|---|---|---|---|
   | DIST_ROI (victim) | 0 | 0 | **0** | 0 | 0 |
   | DIST zone (full bbox) | 9137/9197 | 1786/1846 | 7371 | **7400** | **49** |
   | CONTROL (text) | 888 | 888 | 0 | 0 | 0 |

4. Conclusion: **CAND is more correct than REF.** The legacy ordering runs
   `ClearPreviousAboveMap()` AFTER `telem_amd_update_hud_regions()`
   (`d3d11_vp_pipeline.cpp` L2642; region uploads happen before
   `ProcessFrame`), so restored below-widget pixels under previous
   ABOVE/chart regions are erased and never re-uploaded. This REF defect is
   independent of the ETAP 2A flag (all CAND changes are flag-gated; the REF
   code path is unchanged).
5. Residual cand wipes = **49 px** (ruler tick x[1773..1782] y[1615..1621],
   inside the gauge tile) caused by an ABOVE-cluster replace-crop writing
   transparent pixels over restored content — same class as item 6.
6. A shared STATIC AA-stroke artifact family (black strokes, varied alpha,
   e.g. `(0,0,0,224)` where truth is transparent) exists on BOTH canvases
   (~70 471 px canvas-wide, identical count both runs; inside the gauge tile:
   1606 px regime ≤f150, 1571 px regime ≥f151). It cancels completely in
   ref-vs-cand: **inside the tile, all 5037 ref-vs-cand diffs lie within the
   band rows; 0 outside.** Pre-existing, out of scope — documented for a
   later task.

## 4. Changed files

* `src/ffmpeg/amd_native_exporter.py`
  * (prior segment) early-clear ordering + BELOW force-dirty for widgets
    intersecting previous/current gauge tile;
  * (this segment) env-gated diagnostics `AMD_ETAP2A_COMPOSE_PROBE`
    (compose truth dumps + band census + gauge capture/meta dumps; frame list
    follows `AMD_HUD_DUMP_FRAMES`, default 30/300).
* `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`
  * env-configurable HUD dump frames `AMD_HUD_DUMP_FRAMES` (diagnostic only;
    fixed 30/300/900 behavior unchanged). DLL rebuilt (`build-etap8s`, target
    `telem_amd_native`; pre-existing unrelated `d3d11_etap2c_poc` breakage in
    `main_etap2c.cpp` not touched).
* `scratch/etap2a_parity_check.py` — final gate script.
* `scratch/etap2a_ghosting_check.py`, `scratch/etap2a_mask_probe.py`,
  `scratch/etap2a_bench_compare.py` — validation/benchmark analyzers.
* Artifacts under `scratch/etap2a_test/`.

Backend isolation: NVIDIA/Intel untouched; shared change limited to an
env-gated diagnostic condition in the AMD pipeline.

## 5. Parity gate (final semantics) — PASS

```
GATE_TRUTH_DETERMINISM: PASS     (ref/cand compose byte-identical)
GATE_VICTIM_ROI:        PASS     (f30/f300: ref~cand=0, cand~truth=0)
GATE_NO_NEW_WIPES:      PASS     (cand_wiped=49 < 1% of ref_wiped=7400)
GATE_CONTROL_UNTOUCHED: PASS     (control zone ref~cand=0)
ROI_TABLE f30=f300: FULL=7371 GAUGE=5037 MAP=0 CADENCE=985 HR=2404 DIST_VISUAL=0
PARITY_GATE: PASS
```

Interpretation: the remaining ref-vs-cand deltas are entirely REF-side
pre-existing wipes of truth content that CAND now restores (7400→49 wiped px),
plus the shared static stroke family that cancels between runs.

## 6. Ghosting validation — PASS

Needle-sweep dumps (13 frames: 100–105, 150/151, 200/201, 250/251, 320),
expected tile per frame = Pillow `alpha_composite(compose_truth.crop(tile),
gauge_capture)`:

* gauge tile bbox constant across sweep: x=1440 y=665 w=960 h=960 ✓
* gauge art varies across sweep (needle/value move) ✓
* every tile pixel equals expected EXCEPT one static frame-invariant artifact
  set (1606/1571 px, constant values per regime; same signature as §3.6,
  present identically in REF);
* **zero transient deviations** → no stale needle/value/trail is possible:
  any ghost would break per-frame equality outside the static set.

## 7. Benchmark (1131 frames, GX010115, cycling_dashboard_v10, 3840×2160)

| metric (avg ms/frame) | REF | CAND | Δ |
|---|---|---|---|
| RENDER FPS | 26.465 | 25.033 | **−1.43** |
| true_fps (user effective) | 22.546 | 20.646 | −1.90 |
| producer_prepare | 31.220 | 31.556 | +0.34 |
| above_total | 21.776 | **18.231** | **−3.55** |
| — above_region_to_bytes | 3.411 | 1.023 | −2.39 |
| — above_exact_crop | 1.999 | 0.824 | −1.18 |
| — above_compose | 18.294 | 17.148 | −1.15 |
| compose_overlay | 5.382 | 7.103 | +1.72 |
| gauge_tobytes (new) | 0 | 1.964 | +1.96 |
| gauge_upload (new) | 0 | 0.616 | +0.62 |
| consumer_upload | 2.096 | 2.848 | +0.75 |
| pipeline_total | 6.298 | 7.388 | +1.09 |
| map_cpu_upload | 0.077 | 0.092 | +0.02 |

Honest reading: CPU ABOVE improved exactly as intended (−3.55 ms), but
per-frame FULL-tile gauge tobytes+upload (3.7 MB), extra force-dirty uploads
and capture-side compose overhead exceed the savings → small net regression
(~5–8% fps). Per scope discipline this is **documented, not optimized here**.
Candidate follow-ups (later dedicated task): cache gauge upload when art hash
unchanged, shrink tile to tight gauge bbox, drop duplicate dist_visual rect
(padded+raw), revisit capture-side compose overhead.

## 8. Regressions / risks

* Feature remains **default OFF** until a later dedicated enable task.
* REF-path pre-existing wipe defect now precisely characterized — fixing REF
  is a separate task.
* Shared static stroke family (~70 k px) — pre-existing on both paths;
  separate investigation recommended.
* Temporary diagnostics left env-gated OFF (probe + dump-frame list);
  removal optional in a later cleanup.

## 9. Not tested / blocked

* `H_hud_canvas_900.png` fixed-dump branch — **NOT TESTED** (short runs stop
  at 340 frames; full runs run diagnostics OFF). Code path for fixed frames
  unchanged.
* GUI smoke with flag ON — **NOT TESTED** this session (earlier smoke at
  defaults PASS; flag default unchanged OFF).
* AMF encode comparison — intentionally skipped; pre-encode surfaces compared
  per pixel-parity discipline.

## 10. Final summary

```
TASK:    ETAP 2A AFTER-MAP GPU gauge — parity root-cause, gate, ghosting, bench
STATUS:  COMPLETE (parity objectives MET; feature stays OFF; perf follow-up noted)

CHANGED: amd_native_exporter.py (+diag probes), d3d11_vp_pipeline.cpp
         (+env dump frames), scratch validators; DLL rebuilt
TESTED:  parity gates PASS (4/4), ghosting sweep PASS (13 frames),
         full 1131f benchmark REF+CAND
NOT TESTED: f900 dump branch, GUI smoke (this session)
PERFORMANCE: above_total −3.55 ms; net fps −1.43 (RENDER) — documented
RISKS:   REF legacy wipe defect (pre-existing), shared stroke family
         (pre-existing) — both queued as separate future tasks

REPORT:  Raporty/RAPORT_AMD_ETAP_2A_AFTER_MAP_GAUGE_GPU.md (this file)
```
