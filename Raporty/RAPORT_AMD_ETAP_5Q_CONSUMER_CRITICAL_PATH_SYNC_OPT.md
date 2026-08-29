# TeleM — AMD ETAP 5Q — Consumer critical-path truth

TASK:
AMD ETAP 5Q — CONSUMER CRITICAL-PATH TRUTH, SYNC/BACKPRESSURE ABLATION & CONDITIONAL PRODUCTION OPTIMIZATION

STATUS:
COMPLETE — NO PRODUCTION OPTIMIZATION.

BRANCH:
amd-render

HEAD:
3ab0b89

CANONICAL WORKLOAD:
video = `Video/GX020079.mp4`
fit = `Video/GX020079.fit`
layout = `C:\_DEV\TeleM\def_layout.json`
layout hash = `0B937CCDEE699809F4DC7CBEF5C563140E6D7B9265D21D8C0D2EBC3346B2BBCE`
frames = 1131 requested / 1131 encoded
resolution = 3840x2160, 29.97 fps
output location/type = `\\192.168.1.99\Torrenty\TeleM_5Q`, same network share for all 5Q runs; `video_render_wall` is primary.

METRIC DEFINITIONS:
video_render_wall = first consumer frame begin through the end of the consumed-frame loop, before final AMF flush and mux; includes consumer API calls, packet writes and queue effects, excludes final flush/mux.
TRUE FPS = encoded output count divided by end-to-end elapsed time; includes render, final drain, mux and file/probe work.
RENDER FPS = encoded output count divided by `video_render_wall`.
effective FPS = encoded output count divided by total export elapsed time.
total_export = export-start through export-end; includes precompute, render, AMF drain, mux/file I/O and final probing.

PROFILER OVERHEAD:
OFF = 7.445–7.562 s across the interleaved 300-frame OFF samples.
ON = 7.562–7.606 s across the interleaved 300-frame ON samples.
delta = approximately +1.3% ON mean versus OFF mean.
gate = PASS, below the required 3% (preferred 2% boundary is narrowly exceeded).

QUEUE:
size 0 fraction = approximately 0.1% before consumer get across the 5 full Q2 runs.
size 1 fraction = remainder of observed queue states.
size 2 fraction = dominant producer-side state; approximately 62.2% full-before-put across the 5 runs.

producer blocked frames = approximately 62.2% (queue full before put).
producer blocked fraction = approximately 62.2%.
producer block avg = approximately 13.01 ms.
producer block p95 = approximately 40–45 ms in the full runs.

consumer blocked frames = approximately 0.12% (queue empty before get).
consumer blocked fraction = approximately 0.12%.
consumer block avg = approximately 0.44 ms.

CONSUMER_LIMITED:
YES for throughput direction: producer is frequently stopped by a full queue while consumer rarely waits for data. The queue truth proves consumer throughput is lower than producer throughput under Q2. This does not by itself identify a safe optimization.

CONSUMER NATIVE BREAKDOWN:
entry = included in native `process_frame_total`; not separately exposed.
input surface = `surf_acquire` avg 0.055 ms.
VP setup = `vp_setup` avg 0.006 ms.
VP API = `vp_blt` avg 13.580 ms; median 4.540 ms; p95 35.534 ms; max 141.294 ms. This is API-call wall, not CPU compute or GPU execution.
map CPU submit = `map_resample` avg 0.018 ms in native timing; Python map upload is separately accounted.
HUD CPU submit = `vp_hud_compute` avg 0.008 ms native call wall.
copies = no material per-frame native copy bucket in the GPU decode path.
AMF wrap = `amf_create_surface` avg 0.021 ms.
AMF SubmitInput = avg 0.419 ms in the native trace.
AMF backpressure = zero `INPUT_FULL`; zero retry count.
AMF QueryOutput = avg 0.146 ms; approximately 1.995 calls/frame under DRAIN_READY.
output = packet write avg 2.413 ms.
bookkeeping = residual inside `process_frame_total`.
total = `process_frame_total` avg 16.798 ms; median 7.353 ms; p95 43.459 ms; max 167.538 ms.
accounting error = native trace is non-overlapping stage accounting with residual/parent checks; GPU execution is not inferred from CPU wall.

BLOCKING API TOP10:
1. `VideoProcessorBlt` API wall — high p95/max, likely driver/resource/availability stall; root cause not uniquely proven.
2. packet write/file I/O — avg approximately 2.41 ms, p95 approximately 7.52 ms.
3. AMF SubmitInput — avg approximately 0.42 ms, no INPUT_FULL.
4. AMF QueryOutput — avg approximately 0.15 ms.
5. VP setup/CreateView/stream setters — sub-0.01 ms averages.
6–10. map/chart/gauge/HUD native submissions — individually sub-0.02 ms averages in the native trace.

RESOURCE POOLS:
VP = persistent NV12 output pool size 8; reuse distance 8 frames.
HUD = persistent GPU HUD texture and persistent NV12 target; no per-frame texture creation observed.
AMF = same-device VP output passed directly to AMF; no additional AMF input pool expansion made.
other = persistent map/chart/gauge resources; ABOVE region upload buffers are persistent/direct where supported.

RESOURCE HAZARD:
No correctness failure or frame loss was observed. The high `VideoProcessorBlt` tail is consistent with API wall stalls, but this run does not prove premature reuse; no pool increase was authorized.

AMF:
submitted = 1131 per full run.
output = 1131 per full run.
INPUT_FULL = 0.
REPEAT = normal DRAIN_READY not-ready termination; no busy wait or retry loop observed in the per-frame path.
retry time = 0 ms attributable to INPUT_FULL.
QueryOutput calls/frame = approximately 1.995.
backpressure time = no material AMF backpressure.

EXPLICIT SYNC:
Flush = final AMF drain only; not inserted per-frame for measurement.
GetData = no blocking GPU readback in the main 5Q profiler.
Wait = queue timeout polling and final drain timeout safeguards; no observed consumer wait pressure.
other = `yield` only in the AMF INPUT_FULL retry path, unused in canonical runs; no per-frame Sleep/Flush/query readback.

UPLOAD:
ABOVE = approximately 4.58 MiB/frame uploaded in the full run; native UpdateSubresource path, persistent resources.
MAP = approximately 2.73 MiB/frame; persistent map texture update path.
GAUGE = approximately 0.25 MiB/frame; persistent GPU gauge tile, mostly regional updates.
CHART = GPU_SPLIT path; no recurring full chart upload in the canonical profile.
OTHER = HUD dirty uploads and small control/resource updates.
TOTAL bytes/frame = approximately 7.6 MiB/frame for the measured major paths; byte count is not treated as API-time equivalent.
TOTAL ms/frame = consumer upload avg approximately 5.76 ms across the five full runs.

CANONICAL BASELINE:
video wall mean = 27.601 s.
median = 27.641 s.
CV = 0.614%.
TRUE FPS = approximately 34.0 on the network-share run; secondary metric only.
RENDER FPS = approximately 41.0 (encoded count/video wall).
effective FPS = 33.973 fps mean.
producer active = approximately 11.40 ms/frame.
producer blocked = approximately 13.01 ms/frame, 62.2% full-before-put.
consumer active = approximately 17.4 ms native/consumer path plus upload and bookkeeping.
consumer blocked = approximately 0.44 ms, 0.12% empty-before-get.
native call = approximately 17.2 ms Python boundary mean; native process-frame average approximately 16.8 ms in the detailed trace.
upload = approximately 5.76 ms.
AMF = SubmitInput approximately 0.42 ms; QueryOutput approximately 0.15 ms; no backpressure.

QUEUE ABLATION:
Q1 = 7.458/7.581 s video wall in two 300-frame measured runs; no stable improvement.
Q2 = 7.544/7.370 s; production reference.
Q3 = 7.576/7.442 s; no stable improvement.
Q4 = 7.420/7.493 s; no stable improvement.

QUEUE VERDICT:
Q2 is consumer-limited in queue occupancy terms, but Q1/Q3/Q4 do not provide a stable E2E gain. Queue depth was not changed in production.

SURFACE ABLATION:
performed = NO; hazard was not sufficiently proven to authorize a pool change.
reference = pool 8.
candidate = NOT APPLICABLE.
gain = NOT APPLICABLE.

AMF POLICY ABLATION:
performed = NO; `INPUT_FULL=0` and no material polling/backpressure were observed.
reference = DRAIN_READY.
candidate = NOT APPLICABLE.
gain = NOT APPLICABLE.

SYNC ABLATION:
performed = NO production sync change; no per-frame explicit synchronization was found that met the authorization gate.
reference = existing canonical path.
candidate = NOT APPLICABLE.
gain = NOT APPLICABLE.

REAL CRITICAL PATH:
- Throughput is consumer-limited by queue occupancy.
- The largest measured native wall bucket is `VideoProcessorBlt`, with a low median and high p95/max; this is API-call wall and likely stall/driver/resource interaction, not proven CPU work.
- AMF backpressure and QueryOutput policy are not the cause in the canonical run.

TOP5 CONSUMER TARGETS:
1. VP API wall/resource-stall investigation — high local tail, no safe E2E candidate yet.
2. packet write/file interaction — measurable but outside native scheduling authorization.
3. consumer upload path — approximately 5.76 ms, no single safe attribution candidate.
4. queue architecture — full queue proven, but depth ablation has no stable gain.
5. AMF policy — ruled out by zero INPUT_FULL and low QueryOutput cost.

SELECTED TARGET:
NONE.

ROOT CAUSE:
Consumer throughput is lower than producer throughput, but the evidence isolates a high-variance `VideoProcessorBlt` API wall rather than a proven reusable surface hazard or removable synchronization.

EXPECTED E2E HEADROOM:
No controlled candidate reached the required 3% E2E threshold.

PRODUCTION OPTIMIZATION AUTHORIZED:
NO.

IMPLEMENTATION:
- Added opt-in in-memory queue truth under `AMD_5Q_QUEUE_DIAG=1`.
- Reused existing native `AMD_NATIVE_FRAME_ACCOUNTING=1` QPC/steady-clock trace; no synchronized GPU readback.
- No queue depth, surface pool, AMF policy, or native scheduling production change.

KILL SWITCH:
No new production feature switch; diagnostics are disabled by default.

BEFORE:
video wall = 27.601 s mean in canonical full runs.
TRUE FPS = secondary network-share metric.
producer blocked = 62.2% full-before-put.
consumer active = native/consumer path approximately 17 ms.
selected stage = none.

AFTER:
video wall = NOT APPLICABLE.
TRUE FPS = NOT APPLICABLE.
producer blocked = NOT APPLICABLE.
consumer active = NOT APPLICABLE.
selected stage = none.

PAIRED DELTA:
video wall = NOT APPLICABLE.
TRUE FPS = NOT APPLICABLE.
selected stage = NOT APPLICABLE.

PARITY:
MaxDiff = previous canonical golden test: 0.
DifferentPixels = previous canonical golden test: 0.

OUTPUT:
frames = 1131 encoded per canonical full run.
duration = validated by existing ffprobe/profile path; no dropped or duplicate frames observed.
audio = present.
A/V sync = no scheduling change made; NOT REPROVEN after a production candidate because none was selected.
PTS/DTS = no buffering change made; NOT REPROVEN after a production candidate.

HDR/COLOR:
No surface-flow change. Canonical input remains Main 10/P010 BT.2020 HLG; existing VP path converts to NV12 for AMF. No color semantics were changed.

CANCEL/DRAIN:
No queue/surface/AMF lifecycle change was made; new cancellation acceptance is NOT APPLICABLE.

MEMORY DELTA:
0 production delta. Queue and surface pools were not enlarged.

DECISION:
NO PRODUCTION OPTIMIZATION.

FILES CHANGED:
- `src/ffmpeg/amd_native_exporter.py` — opt-in queue truth and profile export.
- `Raporty/RAPORT_AMD_ETAP_5Q_CONSUMER_CRITICAL_PATH_SYNC_OPT.md` — this report.

PRE-EXISTING CHANGES PRESERVED:
YES.

NEXT TRUE BOTTLENECK:
VP `VideoProcessorBlt` API-call wall tail: isolate resource reuse/driver stall with a targeted non-production experiment before considering any pool or scheduling change.

ETAP 5R RECOMMENDATION:
Perform a focused VP API-stall/resource-lifetime experiment with explicit hazard evidence and no synchronized GPU readback. Do not increase all pools or alter AMF policy without a new E2E proof.
