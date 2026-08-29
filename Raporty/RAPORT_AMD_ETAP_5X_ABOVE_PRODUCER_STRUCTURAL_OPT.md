# TeleM — AMD ETAP 5X — ABOVE producer structural audit

TASK:
AMD ETAP 5X — ABOVE PRODUCER STRUCTURAL OPTIMIZATION, ALLOCATION/COPY ELIMINATION & CONDITIONAL PRODUCTION ENABLEMENT

STATUS:
COMPLETE — diagnostic accounting completed; no candidate met the production gate.

BRANCH:
`amd-render`

HEAD:
`3ab0b89` at task start.

CANONICAL:
- video = `Video/GX020079.MP4`
- fit = `Video/GX020079.fit`
- layout = `C:\\_DEV\\TeleM\\def_layout.json`
- frames = 1131; resolution = 3840x2160
- fingerprint = canonical production-defaults fingerprint

PRODUCTION DEFAULT:
SYNC, Q0, VP REFERENCE, processor ring 1, pool 8, AMF REFERENCE, GPU map,
GPU_SPLIT charts, GPU gauge, GPU lean, GPU_HUD, DIRTY upload, FUSED NV12.
ABOVE batching/fine-dirty/optimized HUD buffer are OFF. Base conversion is
VP_REFERENCE.

## PROFILER OVERHEAD

Six 300-frame canonical runs in OFF/ON/OFF/ON/OFF/ON order:

```text
OFF mean video wall = 9085.5 ms
ON  mean video wall = 9238.1 ms
delta               = +1.68%
gate                = PASS (<=3%)
```

The corrected ON profiler collected 301 producer frames, including the runner's
initial frame.

## FRESH REF

Three measured OFF runs after warmup:

```text
wall mean        = 9085.5 ms
render FPS mean  = 33.131
producer_prepare = 11.225 ms/frame
above_compose    = 6.650 ms/frame
above_total      = 7.745 ms/frame
above_upload     = 0.232 ms/frame (update_hud aggregate)
```

Dedicated 100-frame allocation audit:

```text
ABOVE parent              = 7.9800 ms/frame
explicit children sum     = 7.9800 ms/frame
accounting error          = 0.000%
other compose bookkeeping = 0.9693 ms/frame
```

## ABOVE ACCOUNTING

Production widget accounting from the 300-frame ON profile:

```text
alt_text             1.9441 ms/frame
speed_text           1.8720 ms/frame
fit_distance_text    0.5432 ms/frame
fit_heart_rate_text  0.4493 ms/frame
lean_indicator       0.4403 ms/frame
fit_cadence_text     0.3089 ms/frame
fit_gopro_battery    0.2610 ms/frame
iso_text             0.1567 ms/frame
exposure_text        0.1136 ms/frame
temp_text            0.1099 ms/frame
regional_clear       0.7012 ms/frame
```

The remaining bucket is shared compositor bookkeeping, layout traversal, and
final state handling. Most of the measured ABOVE budget is actual widget
rendering plus shared Pillow operations, not a per-frame full-size canvas
allocation.

## CPU ACTIVE TOP15

From the corrected Pillow operation profiler:

1. pillow.crop — 2.6486 ms/frame, 14.26 calls/frame
2. pillow.alpha_composite — 2.3903 ms/frame, 4.39 calls/frame
3. indicator.alt_text.alpha_composite — 2.1083 ms/frame
4. indicator.alt_text.total — 1.9594 ms/frame
5. indicator.speed_text.total — 1.8977 ms/frame
6. indicator.alt_text.paste_composite — 1.8385 ms/frame
7. pillow.paste — 1.6817 ms/frame, 19.52 calls/frame
8. pillow.copy — 1.0736 ms/frame, 2.37 calls/frame
9. indicator.speed_text.copy — 0.9264 ms/frame
10. canvas.regional_clear — 0.8002 ms/frame, 1.99 calls/frame
11. map.crop_resize — 0.7901 ms/frame
12. fit_distance_text.total — 0.6328 ms/frame
13. alt_text.crop — 0.5163 ms/frame
14. fit_heart_rate_text.total — 0.4894 ms/frame
15. fit_distance_text.paste_composite — 0.4749 ms/frame

## ALLOCATION TOP15

The lightweight audit measured allocation pressure, not Python object identity:

```text
producer allocated blocks = 886.6/frame average, median 543, p95 745.2
consumer allocated blocks = 40.2/frame average, median 34, p95 160.3
traced bytes              = unavailable; tracemalloc was not active
```

Pillow proxies showed approximately 2.57 Image.new, 2.37 Image.copy, and
14.26 Image.crop calls/frame in the ON profile. The production ABOVE canvas is
already persistent through reuse_canvas="above"; no per-frame 3840x2160 RGBA
canvas allocation was observed.

## COPY TOP15 / CALL COUNT TOP15

Measured copy-like operations:

1. pillow.crop — 2.6486 ms/frame; 23.89M source pixels/frame
2. pillow.alpha_composite — 2.3903 ms/frame; 9.30M result pixels/frame
3. pillow.paste — 1.6817 ms/frame; 135.63M touched pixels/frame
4. pillow.copy — 1.0736 ms/frame; 0.75M source pixels/frame
5. pillow.Image.new — 0.1209 ms/frame; 0.13M pixels/frame

Call counts include diagnostic wrappers:

```text
pillow.crop              14.26/frame
pillow.paste             19.52/frame
pillow.ImageDraw         13.58/frame
pillow.textbbox/getbbox   2.88/frame
pillow.alpha_composite    4.39/frame
pillow.getbbox            3.09/frame
pillow.copy                2.37/frame
pillow.Image.new           2.57/frame
font cache lookup         23.57/frame
```

## ALLOCATION / COPY / UPLOAD CHAIN

```text
widget renderer
 -> Pillow image / alpha compositing
 -> renderer-provided exact bbox
 -> crop only where required
 -> RGBA bytes or direct contiguous row pointer
 -> ctypes/native region descriptor
 -> AMD native dirty-region upload
 -> D3D11 HUD surface
```

The current EXACT + DIRECT path already avoids a full-canvas alpha scan and uses
the existing direct pointer/buffer bridge where possible. No CPU P010 conversion
or GPU readback is involved.

## ALT/SPEED AND FONT/GLYPH CACHE

alt_text and speed_text are the two largest leaves, but no single shared
removable mechanism was proven. Font lookup/load was negligible at about
0.0045 ms/frame; the existing font cache lookup was about 23.57 calls/frame.
No large string cache was introduced.

## CANDIDATES

Candidate A — allocation/canvas reuse:
- root cause: already addressed by persistent ABOVE canvas
- local cost: Image.new ~0.121 ms/frame; regional clear ~0.701 ms/frame
- expected E2E: below the 3% gate based on measured budget
- risk: stale pixels/ghosting if clear semantics change
- decision: not selected

Candidate B — crop/copy elimination:
- root cause: Pillow crop/composite/paste chain
- local cost: crop 2.649 + alpha composite 2.390 + paste 1.682 ms/frame
- headroom: EXACT + DIRECT already avoids the full-frame scan and most bridge copies
- expected E2E: unproven without a safe common rewrite
- risk: stride, alpha, dirty geometry, and pixel parity regression
- decision: not selected

Candidate C — global static/dynamic split:
- root cause: possible repeated static artwork rendering
- local cost/headroom: not isolated as a common dominant bucket
- expected E2E: unproven
- risk: widget-specific semantics and stale pixels
- decision: not selected

## HEADROOM RESULTS

A whole-HUD `AMD_5P_HUD_DISABLED=1` control was run as HEADROOM_ONLY. It
changed execution behavior and was slower:

```text
REF mean    = 9302.7 ms
NO-HUD mean = 10853.9 ms
result      = invalid as a production optimization control
```

It is not used to claim that HUD rendering is intrinsically beneficial.

SELECTED TARGET:
NONE

IMPLEMENTATION AUTHORIZED:
NO

IMPLEMENTATION:
Added only the missing frame start/finish calls for the existing diagnostic
overlay profiler and a governance test proving compute mode is explicit and
VP_REFERENCE is default. No ABOVE rendering, geometry, buffer, copy, or upload
semantics changed.

FEATURE FLAG:
`AMD_BASE_CONVERT_MODE` remains governed and defaults to `VP_REFERENCE`.
The rejected 5W compute prototype was not repaired or enabled.

PIXEL PARITY:
NOT TESTED for a candidate; no candidate was selected.

TEMPORAL 150F / GHOSTING / VISUAL / FULL A/B:
NOT TESTED for a candidate because no candidate passed the decision gate.
Existing production safeguards remain unchanged.

ALLOCATIONS:
REF producer = 886.6 allocated blocks/frame average in the 100-frame audit;
candidate = NOT RUN.

MEMORY:
Candidate = NOT TESTED; no persistent candidate buffer was introduced.

FRAME INTEGRITY / AUDIO-A/V / HDR / MULTIFILE / CONTEXT RESET / CANCEL /
REPEATED EXPORT:
Existing production path was not semantically changed; candidate acceptance was
not authorized.

PRODUCTION DEFAULT CHANGED:
NO

FINAL PRODUCTION:
Existing SYNC/Q0/VP_REFERENCE configuration with processor ring 1, output pool 8,
and ABOVE batching/fine-dirty/optimized HUD buffer modes OFF.

DECISION:
NO PRODUCTION OPTIMIZATION

NEXT TRUE BOTTLENECK:
The remaining ABOVE budget is distributed between real widget rasterization
and shared Pillow crop/composite/paste work. A future stage needs a controlled,
exact multi-widget renderer/buffer experiment, not another leaf bypass.

NEXT ETAP:
Only after a separately authorized common renderer candidate is identified.

FILES CHANGED:
- `src/ffmpeg/amd_native_exporter.py` — diagnostic profiler frame scopes
- `tests/test_amd_benchmark_governance.py` — compute default-off governance test
- `Raporty/RAPORT_AMD_ETAP_5X_ABOVE_PRODUCER_STRUCTURAL_OPT.md`

PRE-EXISTING PRESERVED:
YES. Existing dirty worktree changes, benchmark governance, reports, native
diagnostics, and unrelated files were preserved. GX010115 + Lunch FIT data was
excluded.

## Verification

- profiler overhead: PASS, +1.68% (<=3%)
- 300-frame OFF/ON/OFF/ON/OFF/ON runs: PASS
- 100-frame allocation audit: PASS
- parent/child ABOVE accounting: PASS, 0.000% error
- focused AMD/governance tests: run after final patch
- exact candidate parity: NOT TESTED; no candidate selected
- native VP/compute behavior: unchanged in this stage

