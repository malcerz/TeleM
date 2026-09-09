# Quantized continuous telemetry — plateau-aware dequantization

## Root cause

The previous presentation resolver used the raw predecessor and successor for
every lookup. With `98,98,98,98,97`, every duplicate pair returned a flat 98
and the ramp only began at the final duplicate. This was a presentation-layer
problem; FIT/GPMF arrays and processed payloads were not changed.

## Implementation

`src/telemetry_resolver.py` now builds a bounded, immutable
`QuantizedChangeTimeline` once per source-series identity. It stores one event
at the first sample of each quantized run and separate event lists for cadence
segments. Lookup remains binary-search based and does not construct a
per-frame interpolated array.

For a continuous quantized field and display precision finer than native
resolution:

```
event_i.time <= target < event_i+1.time
value = event_i.value + (event_i+1.value-event_i.value) * time_fraction
```

An exact change-event timestamp returns the new raw level. Repeated samples do
not reset the ramp. The final run holds its last value; no extrapolation is
performed. Real cadence gaps, active-time pauses and segment boundaries remain
hold boundaries. Discrete ISO/SHUT/status/mode/ID/counter fields stay STEP.
Battery is represented generically by registry metadata (`continuous`, native
resolution 1.0, quantized); there is no Battery filename/field special case.

## Real FIT inventory

The requested FIT was parsed fresh from:
`D:\\GoPro\\2026-09-02\\Poranna_jazda_na_rowerze.fit`.
The file does **not** contain 98/97 levels. Its complete Battery stream is:

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

Detected runs/events:

| run | start | end | count | change event |
|---|---|---|---:|---|
| 96 | 04:22:27 | 04:34:57 | 11 | (04:22:27, 96) |
| 95 | 04:35:57 | 04:47:57 | 10 | (04:35:57, 95) |
| 94 | 04:49:57 | 04:55:57 | 6 | (04:49:57, 94) |

Thus this real file provides 96→95 and 95→94 acceptance transitions, not
98→97 or 97→96. The absence is recorded rather than fabricated.

## Synthetic proof

The required many-duplicate case is covered by tests:

```
98,98,98,98,97,96,96,96,95
```

At 0/60/120/180/240 seconds the presentation values are
`98.00, 97.75, 97.50, 97.25, 97.00`; the following plateau ramps to 96 and
then 95. Rising `20,20,21,21,22` is also interpolated, proving no direction
assumption. A final `96,96` run holds 96 forever.

## Real GUI proof

Normal Windows GUI (`QApplication → AppController → MainWindow`) was run with
the real MP4/FIT, visible top-level HUD, 12 playback captures, 7 seeks and
paused/resumed decimal changes. Evidence is under
`D:\\TeleM_live_acceptance\\presentation_architecture\\quantized_gui`.

Playback inside the real first 96 plateau produced changing floats/text:
`95.90%, 95.90%, 95.89%, 95.89%, 95.89%, 95.89%, 95.88%, 95.88%, 95.88%,
95.88%, 95.87%, 95.87%` (the video begins after the FIT's first timestamp).
Seek checkpoints across the real 96→95 transition produced:
`95.99, 95.90, 95.75, 95.50, 95.25, 95.10, 95.00%`.
The visible HUD captures include `seek_3_hud.png` (`95.50%`).

Paused midpoint property changes produced 0 DP `96%`, 1 DP `95.5%`, 2 DP
`95.50%`, 3 DP `95.500%`, without moving the slider. The same value then
continued changing during playback.

## Gap and cache safety

The lower-median cadence gate prevents a `60 s, 600 s` interval from becoming
an artificial 330-second normal cadence. The change-event index splits the
source at that gap; no ramp crosses it. Active-time pauses and
`NormalizedFitDistance.segment_start_indices` retain their existing hold
semantics. Metadata is bounded to 128 source series and retains the source
reference; raw arrays remain semantically identical.

## BAR / Final / discrete regression

The segment BAR test observes the full `95.437284` presentation float as its
numeric input; text formatting is independent and segment count is not used as
display value. Final-worker/Preview shared-resolver tests pass for the same
transition. ISO/SHUT remain STEP even with `decimals=2` and stale linear policy.

## Tests and performance

Focused suite (presentation architecture, display precision, GPMF first
sample, chart decimals, Lean/bar label, FIT distance parity): **60 passed**.
`compileall` passed. New tests cover repeated plateaus, both directions,
before/exact/after, no extrapolation, large gaps, merged cuts, cache identity,
and full-float BAR input.

The previously measured 10k warm lookup cost remains O(log N): STEP median
7.7 µs / p95 8.8 µs; linear median 9.5 µs / p95 9.9 µs.

## Changed files

Presentation resolver and focused tests were extended; no FIT/GPMF parser, raw
telemetry, processed cache, Lean, AMD, Intel, NVIDIA, Hybrid or audio code was
changed for this task. No commit or push was made.

## Gate

Synthetic plateau dequantization, generic direction handling, final hold,
decimal matrix, real GUI playback/seek/property change, BAR full float, gap
safety and discrete regression: **PASS**.

The literal real-file 98→97 and 97→96 gates are **NOT TESTABLE** because the
specified FIT contains no 98 or 97 sample. Real equivalent transitions 96→95
and 95→94 are present and tested. Under the prompt's strict requirement that
those literal real levels be proven, final status is:

**STATUS = NOT READY (missing requested 98/97 data in supplied FIT)**
