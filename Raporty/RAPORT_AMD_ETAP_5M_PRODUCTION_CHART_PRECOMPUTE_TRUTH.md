# TeleM — AMD ETAP 5M — Production Chart Precompute Truth / Above Compose Rebaseline

## TASK
AMD ETAP 5M — PRODUCTION CHART PRECOMPUTE TRUTH / ABOVE_COMPOSE REBASELINE

## STATUS
**PASS — NO PRODUCTION FIX REQUIRED / REBASELINE**

The canonical production exporter already prepares and reuses both chart
histories. An empty-cache control reproduced the historical chart cost,
proving that the old ~5.8 ms observation was an empty-cache condition, not
the current production state.

Branch: `amd-render`  
HEAD: `3ab0b89` (working tree contains pre-existing user changes)

## CANONICAL WORKLOAD
```text
video      = Video/GX020079.MP4
fit        = Video/GX020079.fit
preset     = presets/cycling_dashboard_v10.json
frames     = 1131
resolution = 3840x2160
fps        = 29.97
backend    = AMD_NATIVE_D3D11 / GPU_HUD_D3D11VA / AMF
config     = ASYNC, queue 2, STATIC_CACHE, DRAIN_READY, GPU map,
             GPU_SPLIT charts, GPU gauge, FUSED NV12
```

## PRODUCTION PATH AUDIT
1. `src/ffmpeg/streaming.py:841` calls `init_worker(...)` before frame
   processing. The AMD path also initializes it at
   `src/ffmpeg/amd_native_exporter.py:2457`.
2. `src/ffmpeg/worker_cache.py:25` defines `init_worker`; line 126 populates
   `WORKER_CACHE["_precomputed_chart_data"]` with `build_chart_data(...)`.
3. `src/ffmpeg/amd_native_exporter.py:2991-3030` builds the per-frame
   `TelemetryFrameCache` before the loop and passes prepared chart data at
   line 3017.
4. `src/ffmpeg/amd_native_exporter.py:3182` obtains chart data for frame
   preparation; the above-map composition is at line 3539.
5. `src/indicators/chart.py:389` implements `_render_chart_indicator`.
   Empty history substitutes `[value, value]` at lines 408-409.
6. `src/ffmpeg/amd_native_exporter.py:3765-3855` captures GPU_SPLIT chart
   tiles; lines 4703-4724 submit after-map tiles natively.

## CURRENT PRODUCTION PRECOMPUTE
```text
present                = true
type                   = dict
keys                   = fit_cadence_text, fit_heart_rate_text
cadence points         = 1704
heart-rate points      = 1704
precompute build       = 26.5 ms
cadence precomputed hits     = 1132 (one probe + 1131 frames)
cadence dynamic fallbacks    = 0
heart-rate precomputed hits  = 1132 (one probe + 1131 frames)
heart-rate dynamic fallbacks = 0
total precomputed hits       = 2264
total dynamic fallbacks      = 0
```

The production log classified both charts as AFTER-MAP GPU_SPLIT charts and
reported CPU chart rendering disabled.

## ROOT CAUSE OF THE HISTORICAL ~5.8 ms
The controlled run forcibly replaced the prepared chart dictionary with `{}`
after worker initialization. It produced 1132 dynamic fallback calls for each
chart and changed the canonical export:

| State | `above_compose` mean | `above_total` mean | TRUE FPS | Total export |
|---|---:|---:|---:|---:|
| Current production | 7.112 ms | 8.172 ms | 38.848 | 29.113 s |
| Empty-cache control | 12.989 ms | 14.120 ms | 38.435 | 29.426 s |
| Delta | **+5.876 ms** | **+5.948 ms** | -0.414 | +0.313 s |

Thus the historical ~5.8 ms was caused by an empty
`WORKER_CACHE["_precomputed_chart_data"]`; the current exporter does not
exhibit that condition. No cache-key, lifetime, ordering, or propagation
defect was found.

## ACCOUNTING
The current clean exporter exposes stage boundaries but does not provide a
complete non-overlapping decomposition of every `above_compose` child. The
5L accounting harness uses prepared/synthetic data and is not equivalent to
the full production exporter.

```text
above_compose   = 7.112 ms mean / 6.649 ms median
stages_sum      = NOT PROVEN for complete production decomposition
accounting_error = NOT PROVEN
```

## CURRENT
From `Raporty/AMD_ETAP5G/5m_canonical_audit.mp4.amd_profile.json`:
```text
TRUE FPS           = 38.848
RENDER FPS         = 40.897
USER EFFECTIVE FPS = 37.764
above_total        = 8.172 ms mean
above_compose      = 7.112 ms mean
cadence chart CPU  = 0.000 ms (GPU_SPLIT)
heart-rate chart CPU = 0.000 ms (GPU_SPLIT)
CPU ABOVE widgets  = not independently decomposed by clean exporter
producer_prepare   = 11.179 ms mean
total export       = 29.113 s
```

## FORCED PRECOMPUTE
The current production state is already the valid-precompute case:
```text
above_compose = 7.112 ms mean
cadence chart = 0.000 ms CPU / GPU_SPLIT
heart-rate chart = 0.000 ms CPU / GPU_SPLIT
fallback count = 0 + 0
```

## NO-PRECOMPUTE CONTROL
```text
above_compose = 12.989 ms mean
cadence chart = dynamic fallback, 1132 calls
heart-rate chart = dynamic fallback, 1132 calls
fallback count = 1132 + 1132 = 2264
```

## CODE CHANGE REQUIRED
**NO.** No production chart lifecycle change was justified. Temporary audit
instrumentation was removed after measurement.

## CHANGED
- `scratch/run_etap5g_export.py` — accepts and uses the canonical FIT path;
  its previous hardcoded `Morning_Ride.fit` was invalid for this task.
- `tests/test_amd_etap5m_chart_lifecycle.py` — verifies first/second export,
  different-dataset replacement, and restart-equivalent cache replacement.
- `Raporty/RAPORT_AMD_ETAP_5M_PRODUCTION_CHART_PRECOMPUTE_TRUTH.md` — report.

No NVIDIA, Intel, generic CPU renderer, GUI layout, map, dirty-region,
compass, BAR, slope, altitude, VideoProcessor, AMF, or queue code was changed
for ETAP 5M.

## PARITY
`python scratch/test_etap5j_golden_parity.py` passed all required checkpoints
`0, 50, 100, 300, 500, 750, 900, 965, 1130`:
```text
MaxDiff = 0
DifferentPixels = 0
```
Map/lean presence and unchanged BAR/dirty-region geometry were also confirmed
by the golden run.

## LIFETIME TEST
```text
first export      = PASS — chart A data prepared and used
second export     = PASS — chart B replaces chart A
different dataset = PASS — synthetic telemetry values do not leak
cancel/restart    = PASS at cache-lifecycle/unit level; hardware cancel/restart NOT TESTED
stale cache       = PASS — no stale chart telemetry
```
Focused result: `14 passed, 1 skipped`.

## AFTER / TOP15 MEASURED PIPELINE COSTS
Current clean production timing buckets (not all mutually exclusive):
1. `consumer_native_call` — 17.379 ms mean
2. `VideoProcessor CPU submit` — 16.482 ms
3. `producer_queue_wait` — 13.377 ms
4. `producer_prepare` — 11.179 ms
5. `above_compose` — 7.112 ms
6. `consumer_upload` — 5.661 ms
7. `above_region_upload` — 1.938 ms
8. `map_cpu_upload` — 1.189 ms
9. `MF ReadSample/decode availability` — 0.961 ms
10. `gauge_capture` — 0.569 ms
11. `gauge_upload` — 0.481 ms
12. `AMF submit/backpressure` — 0.446 ms
13. `update_hud` — 0.331 ms
14. `AMF QueryOutput` — 0.141 ms
15. `Packet write` — 0.107 ms

## NEXT TRUE CRITICAL PATH
Do not optimize charts: production fallback is zero. The next investigation
target is the real production `above_compose` path (~7.1 ms), with
`consumer_native_call`/VideoProcessor scheduling as the larger end-to-end
system bucket. A future stage must first add complete non-overlapping
production child timers.

## ETAP 5N RECOMMENDATION
Make ETAP 5N measurement-only: instrument the full exporter with
non-overlapping child timers, prove accounting error ≤5%, then select the next
critical path from the canonical workload. Do not start another chart/widget
optimization stage.

## FINAL SUMMARY
```text
production precompute present = YES
production dynamic fallback   = 0 / 0
historical empty-cache delta  = ~5.88 ms/frame, reproduced
production lifecycle fix      = NO
golden parity                 = PASS, MaxDiff 0, DifferentPixels 0
full production accounting    = NOT PROVEN
```
