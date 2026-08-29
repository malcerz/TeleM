# TeleM — AMD ETAP 5P — GPU critical-path headroom proof

TASK:
AMD ETAP 5P — GPU CRITICAL-PATH HEADROOM PROOF + CONDITIONAL SINGLE GPU OPTIMIZATION

STATUS:
COMPLETE — no production GPU optimization selected.

BRANCH:
amd-render

HEAD:
3ab0b89

CANONICAL WORKLOAD:
video = `Video/GX020079.mp4` (brief spelling: `GX020079.MP4`)
fit = `Video/GX020079.fit`
layout = `def_layout.json`
layout SHA256 = `0B937CCDEE699809F4DC7CBEF5C563140E6D7B9265D21D8C0D2EBC3346B2BBCE`
frames = 1131 requested, 29.97 fps, 3840x2160
AMD_NATIVE_D3D11, ASYNC queue2, STATIC_CACHE, DRAIN_READY, GPU MAP, GPU_SPLIT charts, GPU gauge, GPU HUD, FUSED NV12, AMD_ABOVE_BATCHED=0.

5O TRUE-FPS DEFINITION AUDIT:
5O used a different output location/harness timing mix, including network-volume output. Therefore its TRUE FPS is secondary. ETAP 5P uses `video_render_wall_ms` as the primary E2E metric and reports TRUE/RENDER/effective FPS only after frame-count validation. The 5N.1 canonical full-run reference was approximately 27.8 s video wall, TRUE FPS approximately 38.95, RENDER FPS approximately 40.7, effective FPS approximately 37.9.

HUD_CPU NAMEERROR:
root cause = `lean_cfg` was created only inside `if lean_gpu_enabled`, but the shared `_prepare_frame_cpu` diagnostics closure referenced it when `AMD_NATIVE_HUD_MODE=CPU_REFERENCE` disabled the GPU lean path.
fix = define `lean_cfg` before the conditional GPU-lean setup. Also supply the existing `PreparedFrame.map_heading` field in the no-HUD diagnostic constructor, exposed by `HUD_DISABLED`.
production impact = diagnostic-only fixes; default GPU HUD/lean/map/chart/gauge behavior is unchanged.

BASELINE:
video wall = approximately 27.8 s (5N.1 canonical full run; current 5P short GPU controls are not substituted for this full baseline)
TRUE FPS = approximately 38.95
RENDER FPS = approximately 40.7
effective FPS = approximately 37.9
total export = approximately 29.8 s

VP ARCHITECTURE:
Persistent D3D11 VideoProcessor converts P010 input to an NV12 output pool. Current setup uses progressive 30000/1001 content, 3840x2160 output, playback usage, and checks NV12 output support. `STATIC_CACHE` skips unchanged stream setters; `REFERENCE` reapplies them. No safe zero-cost VP bypass exists because P010→NV12 conversion is required before AMF.

HUD ARCHITECTURE:
GPU HUD uses a persistent RGBA `DXGI_FORMAT_R8G8B8A8_UNORM` texture and direct NV12 Y/UV UAV composition. The fused shader performs alpha-aware RGB→studio-range YUV conversion and read-modify-write blending over the VP output. Dispatch covers the complete output through the selected fused variant. CPU_REFERENCE is a separate full CPU reference path.

MAP ARCHITECTURE:
GPU map uses a persistent map SRV and compute resample/blend into the shared HUD canvas, with direct 1:1 or fused resample paths, followed by CPU ABOVE_MAP and final fused HUD composition. Production order is `CPU_BELOW_MAP → GPU_MAP → CPU_ABOVE_MAP → gauge/charts → final HUD→NV12`.

GPU LOCAL COSTS:
VP = mean approximately 7.9205 ms in the available 5N.1 GPU timestamp trace; this is a GPU timestamp allocation, not an E2E headroom proof.
HUD = mean approximately 4.0063 ms in the same trace.
MAP = mean approximately 2.8854 ms in the same trace.
GPU span = mean approximately 14.8163 ms, median approximately 11.8679 ms, p95 approximately 29.9102 ms.

ABLATION:
REF = 5P GPU control completed for the 300-frame control probe: 7.741 s video wall, 38.884 RENDER FPS, 25.921 effective FPS, 11.612 s total.
VP_CONTROL = `AMD_VP_STATE_MODE=REFERENCE` 300-frame probe: 7.721 s video wall, 38.982 RENDER FPS, 25.910 effective FPS, 11.617 s total; no gain over REF.
HUD_CPU = warmup + two measured 1131-frame exports completed after the fix; measured video walls 298.875 s and 316.161 s. The third automated artifact was empty and a duplicate standalone attempt was stopped after contention; the required third clean measured run is NOT PROVEN.
HUD_DISABLED = 1 warmup + 3 measured 1131-frame exports completed, but disabling all indicators also disables the map and overlapped the slow CPU_REFERENCE probe. Video walls: 47.930 s, 46.711 s, 51.486 s. This is maximum-removal diagnostics only; isolated HUD headroom is NOT PROVEN.
MAP_DISABLED = 1 warmup + 3 measured 1131-frame exports completed cleanly. Video walls: 28.934 s, 29.246 s, 29.135 s; totals: 34.134 s, 34.652 s, 34.336 s. This is slower than the 5N.1 GPU baseline, so no E2E map headroom is shown.
MAP_CPU optional = 300-frame probe: 7.592 s video wall, 39.647 RENDER FPS, 26.679 effective FPS, 11.282 s total; semantic CPU replacement, not accepted as GPU headroom proof.

E2E HEADROOM:
VP = no positive headroom proven; VP control was effectively 0%/noise.
HUD = not isolated: HUD_DISABLED also removes the map and CPU_REFERENCE changes decode/map/HUD architecture.
MAP = no positive headroom; MAP_DISABLED is approximately 4.5% slower in video wall than the approximately 27.8 s baseline.

VP VERDICT:
No production candidate.
HUD VERDICT:
Diagnostic CPU path is fixed and expensive; no safe single GPU optimization selected.
MAP VERDICT:
No positive headroom.

SELECTED TARGET:
NONE

SELECTION CONFIDENCE:
High for the no-change decision; medium for exact isolated HUD attribution.

ROOT CAUSE:
The available local GPU timestamps show non-zero VP/HUD/MAP work, but the current E2E wall is shared with decode, queueing, AMF, packet write, and mux. A timestamp cost alone does not establish a production optimization opportunity.

EXPECTED MAX E2E GAIN:
No safe candidate cleared the required 3% same-semantics E2E threshold. No production change is authorized.

PRODUCTION CHANGE:
None.

KILL SWITCH:
No new production switch. `AMD_5P_HUD_DISABLED`, `AMD_5P_MAP_DISABLED`, and `AMD_5O_BYPASS` are process-local diagnostic controls only.

BEFORE:
video wall = see baseline above
TRUE FPS = see baseline above
CV = NOT COMPUTED for final 5P paired set

AFTER:
video wall = NOT APPLICABLE
TRUE FPS = NOT APPLICABLE
CV = NOT APPLICABLE

PAIRED E2E GAIN:
NOT APPLICABLE — no candidate selected.

LOCAL GPU GAIN:
NOT APPLICABLE.

PIXEL PARITY:
MaxDiff = NOT RUN for a new production candidate; previous golden checkpoints remain exact parity.
DifferentPixels = NOT RUN for a new production candidate; previous golden checkpoints remain exact parity.

HDR/COLOR:
Current input is Main 10/P010 BT.2020 HLG and the output path uses the existing VP/HUD color configuration. New candidate validation is NOT APPLICABLE.

GHOSTING:
MAP: NOT RUN for a new candidate.
HUD: CPU diagnostic completed without the prior exception; visual ghosting acceptance is NOT RUN.

BACKEND ISOLATION:
AMD-only diagnostic/exporter changes. No NVIDIA, Intel, CPU/reference production backend, or `def_layout.json` changes were made for ETAP 5P.

DECISION:
`NO GPU OPTIMIZATION`. VP control is neutral, MAP_DISABLED is slower, and HUD_DISABLED is a confounded maximum-removal diagnostic rather than a safe same-semantics optimization candidate. No 5-pair A/B was applicable.

FILES CHANGED:
`src/ffmpeg/amd_native_exporter.py` — diagnostic `lean_cfg` scope fix and no-HUD `map_heading` constructor fix.
`scratch/run_etap5g_export.py` — canonical input/layout reporting plus process-local HUD/MAP diagnostic ablations.
`Raporty/RAPORT_AMD_ETAP_5P_GPU_CRITICAL_PATH_HEADROOM_OPT.md` — this report.

PRE-EXISTING CHANGES PRESERVED:
YES

NEXT REAL BOTTLENECK:
Not selected until the ablation matrix proves a safe target; current measured CPU ABOVE and queue/consumer costs remain separate from GPU-local timestamps.

ETAP 5Q RECOMMENDATION:
If the clean matrix does not produce a same-semantics ≥3% E2E win, keep the production GPU pipeline unchanged and investigate the next bottleneck only under a separate ETAP 5Q task.
