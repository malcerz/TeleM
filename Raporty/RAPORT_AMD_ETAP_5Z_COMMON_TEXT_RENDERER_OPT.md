# AMD ETAP 5Z — Common Simple-Text Renderer

## TASK

AMD ETAP 5Z — COMMON SIMPLE-TEXT RENDERER, DIRECT-CANVAS COMPOSITING & CONDITIONAL PRODUCTION ENABLEMENT.

## STATUS

**COMPLETE — NO PRODUCTION OPTIMIZATION.**

The common-text headroom gate failed before a production renderer was
justified. The AMD production default remains unchanged and the experimental
flag is explicit, fingerprinted, and default-off.

## Initial state

- Branch: `amd-render`
- Backend: `AMD_NATIVE_D3D11`
- Canonical workload: `Video/GX020079.MP4` + `Video/GX020079.fit`,
  `C:\_DEV\TeleM\def_layout.json`, 3840x2160, 1131 frames.
- Production defaults: SYNC/Q0, VP_REFERENCE, VP ring 1, VP pool 8,
  AMF_REFERENCE, GPU map/charts/gauge/lean/HUD, DIRTY/EXACT/DIRECT/FUSED.
- ETAP 5Y final ABOVE extraction is already zero-crop/strided/direct and was
  not changed.

## Semantic audit

| Widget | Actual renderer/form | Rotation | Extra geometry/art | 5Z classification |
|---|---|---:|---|---|
| `alt_text` | `_render_bar_indicator` / ruler bar | 0 | ruler, ticks, labels, marker | NOT ELIGIBLE |
| `speed_text` | `_render_gauge_indicator` / gauge | 0 | gauge artwork/geometry | NOT ELIGIBLE |
| `fit_distance_text` | `_render_bar_indicator` / ruler bar | 0 | ruler, ticks, marker, labels | NOT ELIGIBLE |
| `fit_heart_rate_text` | `_render_chart_indicator` / chart | 0 | chart history, grid, labels, dynamic value | NOT ELIGIBLE |
| `fit_cadence_text` | `_render_chart_indicator` / chart | 0 | chart history, grid, labels, dynamic value | NOT ELIGIBLE |
| `fit_gopro_battery_text` | `_render_bar_indicator` / segment bar | 0 | segment geometry/color | NOT ELIGIBLE |
| `iso_text` | `_render_text_indicator` / text | 0 | no icon/art in canonical layout | ELIGIBLE EXACT |
| `exposure_text` | `_render_text_indicator` / text | 0 | exposure-specific `1/N` formatting | ELIGIBLE EXACT |
| `temp_text` | `_render_text_indicator` / text | 0 | temperature-specific unit formatting | ELIGIBLE EXACT |

The common contract for the last three is: cached font lookup, deterministic
formatted string, opaque text fill, global text outline as black stroke,
transparent local RGBA image, `getbbox`, crop to the exact non-transparent
box, then final `rotated_paste` onto the persistent ABOVE canvas. There is no
shadow, background, icon, or custom artwork in the canonical configuration.
The renderer still uses a temporary image and the final compositor may use
`copy`/`crop`/`alpha_composite`/`paste` according to overlap and transparency.
Geometry and prior-frame bboxes are tracked by the existing compositor.

The other six requested audit entries are deliberately excluded; their names
contain “text” but their actual forms are not simple text renderers.

## Cost attribution and headroom

ETAP 5X production profiler evidence (300-frame local run) attributed the
canonical simple-text widgets approximately as follows:

| Widget | Inclusive avg ms/frame |
|---|---:|
| `iso_text` | 0.1567 |
| `exposure_text` | 0.1136 |
| `temp_text` | 0.1099 |
| **eligible total** | **0.3802** |

The existing profiler also measured the broader widget/Pillow totals, but
nested operation timers are not added to the widget totals. The eligible
total above is therefore the non-double-counted upper bound for replacing the
three canonical simple-text widgets. Even removing every eligible temporary
allocation/copy/crop/composite operation would remain below the required
0.8 ms/frame budget and below 3% theoretical E2E headroom against the fresh
5X reference (~33 FPS, ~9.09 s/300 frames). The actual removable portion is
smaller because text formatting, font measurement, rasterization, stroke,
exact bbox calculation, and bookkeeping remain necessary.

Conclusion: **COMMON TEXT RENDERER HEADROOM INSUFFICIENT**. A large fast path
would not satisfy the stage gate.

## Direct-canvas parity probe

A focused Pillow probe compared the existing reference sequence (transparent
local RGBA image → `alpha_composite`) with direct `ImageDraw.Draw` on a
non-transparent RGBA destination. The direct path differed in antialiased
pixel values (maximum channel difference 8; 453 pixels in the probe), so it
was not accepted as an exact replacement. No direct-canvas renderer was
enabled.

Because the headroom gate failed, reusable tight scratch was not built either.
That would preserve the same reference drawing semantics but could not meet
the required E2E threshold on the canonical eligible set.

## Governance change

Added explicit AMD candidate flag:

```text
AMD_ABOVE_COMMON_TEXT_FAST=0|1
```

It is resolved as `common_text_fast`, included in the benchmark fingerprint,
and defaults to `0`. The eligibility module always reports the reference
fallback as the proven behavior; no widget can disappear when the flag is
requested. The production default remains reference/off.

## Tests

Added pure governance/eligibility tests covering:

- default-off and explicit flag resolution;
- fingerprint distinction;
- exclusion of bar/gauge/chart/segment-bar forms;
- exact eligibility of canonical simple text and conditional rotation;
- unproven fast-path fallback.

## Not tested / not authorized

- No 300-frame REF/FAST A/B was run because no exact candidate passed the
  precondition and the candidate implementation was not enabled.
- No 1131-frame acceptance, temporal/visual/HDR/multifile/cancel/repeated
  export acceptance was authorized.
- No VP, compute, upload, map, chart, gauge, lean, queue, AMF, or unrelated
  backend changes were made.

## Decision

**NO PRODUCTION OPTIMIZATION.** Keep `AMD_ABOVE_COMMON_TEXT_FAST=0` and the
existing reference text renderer. The next performance work must target a
different, sufficiently large measured budget; this stage does not justify
maintaining a common-text production fast path.

## Files changed

- `src/ffmpeg/amd_config.py`
- `src/indicators/common_text.py`
- `tests/test_amd_common_text_governance.py`
- `Raporty/RAPORT_AMD_ETAP_5Z_COMMON_TEXT_RENDERER_OPT.md`

Pre-existing ETAP 5X/5Y changes were preserved.
