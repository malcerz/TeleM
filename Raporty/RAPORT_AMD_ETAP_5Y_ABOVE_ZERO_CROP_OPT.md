# TeleM — AMD ETAP 5Y — ABOVE zero-crop strided upload

TASK:
AMD ETAP 5Y — ABOVE ZERO-CROP STRIDED UPLOAD, COPY-CHAIN COLLAPSE & CONDITIONAL MULTI-WIDGET FAST PATH

STATUS:
COMPLETE — zero-crop strided upload is already implemented in the production EXACT path. No new production candidate was enabled.

BRANCH:
amd-render

HEAD:
3ab0b89 at task start.

CANONICAL:
video = Video/GX020079.MP4
fit = Video/GX020079.fit
layout = C:\\_DEV\\TeleM\\def_layout.json
frames = 1131
fingerprint = canonical production-defaults fingerprint

PRODUCTION DEFAULT:
SYNC/Q0, VP_REFERENCE, processor ring 1, pool 8, AMF_REFERENCE, GPU map,
GPU_SPLIT charts, GPU gauge, GPU lean, GPU_HUD, DIRTY upload, FUSED NV12.
AMD_ABOVE_BATCHED=0, AMD_ABOVE_FINE_DIRTY=0, AMD_HUD_BUFFER_MODE=REFERENCE.

PROFILER OVERHEAD:
OFF/ON/OFF/ON/OFF/ON, 300 frames:
OFF mean wall = 9085.5 ms
ON mean wall = 9238.1 ms
delta = +1.68%, gate PASS (<=3%).

CROP BREAKDOWN:
FINAL_DIRTY_EXTRACTION:
calls/frame = 5.0 native UpdateSubresource calls in the representative trace
ms/frame = 0.086 ms Python pre-upload control
pixels/frame = 1,392,359 candidate pixels
bytes/frame = 4,051,332 uploaded bytes
exact crop = 0.000 ms/frame in steady contiguous EXACT path
alpha scan = 0.000 ms/frame in steady EXACT path
exact union/planning = 0.034 ms/frame
native upload = 3.690 ms/frame
UpdateSubresource CPU timing = 3.610 ms/frame

ALT_INTERNAL:
alt_text internal crop about 0.516 ms/frame; alt_text total about 1.944 ms/frame.

SPEED_INTERNAL:
speed_text internal copy about 0.926 ms/frame; speed_text total about 1.872 ms/frame.

OTHER:
The remaining Pillow crop/composite/paste cost is widget-local/intermediate:
crop 2.6486 ms/frame, alpha_composite 2.3903 ms/frame, paste 1.6817
ms/frame, copy 1.0736 ms/frame. These are inclusive operation diagnostics and
are not added to mutually-exclusive widget totals.

COPY BREAKDOWN:
Pillow copy = 1.0736 ms/frame, 2.37 calls/frame.
Final exact extraction copy/crop = zero in steady contiguous mode.
No CPU P010 conversion or GPU readback exists in this path.

ALPHA_COMPOSITE BREAKDOWN:
Pillow alpha_composite = 2.3903 ms/frame, 4.39 calls/frame, primarily
widget-local composition. Regional clear = about 0.701 ms/frame.

PASTE BREAKDOWN:
Pillow paste = 1.6817 ms/frame, 19.52 calls/frame, covering widget/canvas
composition. Final dirty extraction adds no Pillow paste.

EXCLUSIVE CPU TOP15:
1. pillow.crop — 2.6486 ms/frame
2. pillow.alpha_composite — 2.3903 ms/frame
3. alt_text — 1.9441 ms/frame
4. speed_text — 1.8720 ms/frame
5. pillow.paste — 1.6817 ms/frame
6. pillow.copy — 1.0736 ms/frame
7. regional clear — 0.7012 ms/frame
8. fit_distance_text — 0.5432 ms/frame
9. fit_heart_rate_text — 0.4493 ms/frame
10. lean_indicator — 0.4403 ms/frame
11. fit_cadence_text — 0.3089 ms/frame
12. pillow.getbbox — 0.4478 ms/frame
13. fit_gopro_battery_text — 0.2610 ms/frame
14. iso_text — 0.1567 ms/frame
15. exposure_text — 0.1136 ms/frame

FINAL EXTRACTION CHAIN:
persistent ABOVE RGBA canvas -> exact bbox union -> Pillow row-table pointer
-> full-canvas base pointer plus x/y offset -> full physical row stride
-> native descriptor -> UpdateSubresource with SrcRowPitch=canvasStride and
DstBox=dirty rect -> native ABOVE texture.

PERSISTENT CANVAS:
format = RGBA
size = 3840x2160 canonical
bytes/pixel = 4
stride = 15360 bytes/row
orientation = top-down Pillow row table
owner/lifetime = thread-local reusable ABOVE canvas for the render worker
stable pointer = YES for validated contiguous storage; crop/tobytes fallback
remains for non-contiguous/unavailable storage.

STRIDED UPLOAD FEASIBILITY:
YES. It already exists in the current EXACT path.

REQUIRED ABI CHANGE:
None. Existing ABI accepts pointer, width, height, source stride, and
destination coordinates. Native UpdateSubresource already accepts the full
canvas source pitch.

STATIC PATTERN TEST:
NOT RUN as a new standalone GPU harness. Existing code audit proves non-origin
offset and full source stride are passed to UpdateSubresource.

EDGE BBOX TEST:
NOT RUN as a new standalone matrix. Existing clipping/contiguity guards remain.

MULTI REGION TEST:
NOT RUN as a new standalone equality harness. Existing exact multi-region
planner and direct row-pointer path remain unchanged.

STRIDED REF:
Current production EXACT + DIRECT path.

STRIDED CANDIDATE:
No distinct implementation exists to benchmark; the requested optimization is
already active where storage is contiguous.

STRIDED GAIN:
No attributable delta; a new flag would duplicate the same implementation.

STRIDED PRODUCTION CANDIDATE:
NO — already present in production.

PHASE C REQUIRED:
YES for any future work. Final extraction crop is already zero and its
Python preparation budget is too small for a credible standalone >=3% E2E gain.
Future work would need one exact common simple-widget renderer candidate.

COMMON SIMPLE-WIDGET PATTERN:
Many widgets use local raster creation, drawing, alpha composition, and paste
to the persistent ABOVE canvas. The pattern is not proven identical across
bars, shadows, strokes, rotations, anchors, gauge, lean, and charts.

ELIGIBLE WIDGETS:
Only fixed-rotation text widgets with fully known font, stroke, shadow, alpha,
anchor, and fallback semantics could be considered. No such candidate was
implemented in 5Y.

SELECTED TARGET:
NONE. STRIDED_UPLOAD is existing behavior; COMMON_WIDGET_PATH lacks proof.

FULL A/B AUTHORIZED:
NO

PIXEL PARITY / TEMPORAL 200F / GHOSTING:
NOT RUN for a new candidate because no distinct candidate was selected.
Existing production behavior was not changed.

ALLOCATIONS:
100-frame audit: producer 886.6 allocated blocks/frame average, median 543,
p95 745.2; consumer 40.2 average, median 34, p95 160.3.

CROP CALLS:
All Pillow crop operations 14.26/frame and 2.6486 ms/frame; steady final
EXACT extraction crop zero.

COPY BYTES:
Representative exact uploaded bytes 4,051,332/frame; candidate reduction NOT RUN.

FRAME INTEGRITY / AUDIO / HDR / MULTIFILE / CONTEXT RESET / CANCEL /
REPEATED EXPORT:
No production semantics changed; candidate-specific acceptance NOT TESTED.

PRODUCTION DEFAULT CHANGED:
NO

FINAL PRODUCTION:
Unchanged canonical production configuration. Existing EXACT + DIRECT zero-crop
strided upload remains active, with safe crop/tobytes fallback.

DECISION:
NO PRODUCTION OPTIMIZATION

NEXT TRUE BOTTLENECK:
Widget-internal Pillow crop/alpha-composite/paste and actual rasterization, not
final dirty extraction.

NEXT ETAP:
A separately authorized common simple-widget renderer experiment with exact
eligibility and parity contract.

FILES CHANGED:
No new source changes in 5Y. Report only:
Raporty/RAPORT_AMD_ETAP_5Y_ABOVE_ZERO_CROP_OPT.md

PRE-EXISTING PRESERVED:
YES. All prior governance, diagnostics, native code, layout and unrelated dirty
work were preserved. GX010115 + Lunch FIT was excluded.

VERIFICATION:
Profiler overhead PASS (+1.68%).
Exact extraction audit PASS (zero steady-state final crop).
Persistent canvas/stride/native source audit PASS.
Standalone static/edge/multi-region GPU harness NOT TESTED.
Candidate parity/full A/B NOT AUTHORIZED.

