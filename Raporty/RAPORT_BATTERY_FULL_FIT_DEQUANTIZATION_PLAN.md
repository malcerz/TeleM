# Battery full-FIT dequantization plan

## Scope and root cause

The former contract resolved Battery from the raw predecessor/successor on
every frame. Repeated integer samples therefore reset the ramp (`96,96,96`
stayed flat until the final duplicate). The FIT parser, raw series, processed
cache payloads and all backends remain unchanged.

The new contract is:

```
full FIT Battery prepass → BatteryPresentationPlan → plan.value_at(target_dt)
```

`BatteryPresentationPlan` is immutable and cached by source-series identity.
It stores only change events and lightweight segments. The first unknown drop
is back-predicted from the next observed drop duration; confirmed transitions
use their own real timestamps; the final unconfirmed level uses an open tail
to `N - 0.99` when effective video coverage is known. No extrapolation is
used without a coverage endpoint. A two-state file uses the available
video-start→first-change interval, then an open tail. A single-state file uses
`N.00 → N-0.99` over the effective coverage. Jumps larger than 1% are direct
linear transitions over their real event interval. Increases are retained and
interpolated in their observed direction.

## Real full-FIT inventory

Source: `D:\\GoPro\\2026-09-02\\Poranna_jazda_na_rowerze.fit`; 27 Battery
records. The complete parsed series is:

```
04:22:27 96   04:23:57 96   04:24:57 96   04:25:57 96
04:26:57 96   04:28:57 96   04:29:57 96   04:30:57 96
04:32:57 96   04:33:57 96   04:34:57 96
04:35:57 95   04:37:57 95   04:38:57 95   04:39:57 95
04:40:57 95   04:42:57 95   04:43:57 95   04:45:57 95
04:46:57 95   04:47:57 95
04:49:57 94   04:50:57 94   04:51:57 94   04:52:57 94
04:53:57 94   04:55:57 94
```

Change events and observed durations:

| event | first timestamp | level | duration to next |
|---|---|---:|---:|
| E0 | 04:22:27 | 96 | 810 s |
| E1 | 04:35:57 | 95 | 840 s |
| E2 | 04:49:57 | 94 | — |

Observed durations: `810 s`, `840 s`; median `825 s`, min `810 s`, max
`840 s`. The first back-predicted duration is the later observed `840 s`.

For GX010246 video coverage (`04:22:38.224128 → 04:56:44.902095`), the plan
is:

| segment | start | end | values | kind |
|---|---|---|---|---|
| 0 | 04:22:38.224128 | 04:35:57 | 96.00 → 95.00 | back_predicted_first_transition |
| 1 | 04:35:57 | 04:49:57 | 95.00 → 94.00 | observed_transition |
| 2 | 04:49:57 | 04:56:44.902095 | 94.00 → 93.01 | open_tail_estimate |

Because a real FIT sample visible in the video explicitly reports 96, the
product start rule keeps video start at `96.00`, despite the inferred
historical ramp beginning before the clip.

## Synthetic acceptance

Fixtures cover:

- `98,98,98,98,97,96,96,96,95`: first ramp uses the later observed duration;
  repeated samples do not reset it.
- `20,20,21,21,22`: increasing direction works.
- one state `90,90`: `90.00 → 89.01` across coverage.
- two states `90,90,89,89`: confirmed first transition then `89 → 88.01` tail.
- large gap: no depletion ramp crosses the outage.
- ISO/SHUT: always STEP.

## Real GUI acceptance

Normal Windows GUI (`QApplication → AppController → MainWindow`) was run on
the real GX010246/FIT after planner integration. Evidence:
`D:\\TeleM_live_acceptance\\presentation_architecture\\battery_plan_gui`.

Playback inside the first real plateau produced changing values
`95.87, 95.86, 95.86, 95.86, 95.85, 95.85, 95.85, 95.85, 95.84%`.
Seek checkpoints across 96→95 yielded `95.95, 95.87, 95.72, 95.48, 95.24,
95.10, 95.00%`; `seek_3_hud.png` visibly shows `95.48%`. Paused property
changes at the midpoint produced `96%`, `95.5%`, `95.48%`, `95.482%` for
0/1/2/3 DP, and playback continued changing afterward.

The requested literal real 98→97 and 97→96 transitions cannot be shown: the
specified FIT contains no 98 or 97 sample. Real equivalent 96→95 and 95→94
transitions are present and pass. This is reported as a data limitation, not
replaced with fabricated timestamps.

## Preview/Final, BAR, gaps and performance

Preview and Final call the same resolver/plan cache; no backend-specific
Battery logic was added. Short Final-worker parity was rerun after planner
integration; rendered artifacts are in
`D:\\TeleM_live_acceptance\\presentation_architecture\\final_worker_plan`.
BAR receives the full presentation float and
formats independently; segment count never becomes display value. Effective
timeline gaps, pauses and cuts remain hold boundaries; MP4 filename boundaries
alone do not split a continuous plan.

Focused regression suite: **62 passed**. `compileall` passed. New planner tests
cover change-event ramps, back-prediction, open tails, single/two-state rules,
direction changes, raw immutability, gaps, discrete fields and BAR float input.
The 10k resolver measurement remains O(log N): STEP median 7.7 µs / p95 8.8
µs; linear median 9.5 µs / p95 9.9 µs.

Changed files: `src/telemetry_resolver.py`, `src/gui/telemetry_manager.py`,
`src/ffmpeg/worker_cache.py`, planner-focused tests, and this report. The
manager and worker now warm the full plan at source initialization, before the
first presentation frame. No parser, raw FIT, processed cache, Lean, AMD,
Intel, NVIDIA, Hybrid or audio changes; no commit/push.

## Gate

Planner prepass, repeated-plateau dequantization, later-duration inference,
observed transitions, tails, decimals, GUI playback/seek/property changes,
BAR float, gap safety and discrete regression: **PASS**.

Literal real 98→97 / 97→96 GUI gates: **NOT TESTABLE** because the specified
FIT has no such levels.

**STATUS = NOT READY (required 98/97 real data is absent)**
